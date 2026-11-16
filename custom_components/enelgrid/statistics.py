"""Import Enel readings into Home Assistant long-term statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .parser import HourlyReading, build_cumulative

_LOGGER = logging.getLogger(__name__)

CURRENCY = "EUR"


def normalize_pod(pod: str) -> str:
    """POD as used in statistic ids (kept identical to v1.x to preserve history)."""
    return pod.lower().replace("-", "_").replace(".", "_").replace(" ", "")


def consumption_statistic_id(pod: str) -> str:
    # NOTE: the "sensor:" prefix is not the recommended one for external
    # statistics, but it is kept so that existing history and Energy dashboard
    # configurations keep working.
    return f"sensor:enelgrid_{normalize_pod(pod)}_consumption"


def cost_statistic_id(pod: str) -> str:
    return f"sensor:enelgrid_{normalize_pod(pod)}_kw_cost"


def _metadata(statistic_id: str, name: str, unit: str, unit_class: str | None) -> dict:
    return {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": name,
        "source": statistic_id.split(":", 1)[0],
        "statistic_id": statistic_id,
        "unit_class": unit_class,
        "unit_of_measurement": unit,
    }


async def async_get_last_statistic_start(hass: HomeAssistant, statistic_id: str) -> datetime | None:
    """Start (UTC) of the newest stored hour, or None if there is none."""
    result = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, False, {"sum"}
    )
    rows = result.get(statistic_id)
    if not rows:
        return None
    return dt_util.utc_from_timestamp(rows[0]["start"])


async def async_get_sum_before(hass: HomeAssistant, statistic_id: str, before: datetime) -> float | None:
    """Cumulative sum of the last stored hour strictly before `before`."""

    def _query(start: datetime) -> float | None:
        result = statistics_during_period(hass, start, before, {statistic_id}, "hour", None, {"sum"})
        rows = [r for r in result.get(statistic_id, []) if r.get("sum") is not None]
        return rows[-1]["sum"] if rows else None

    recorder = get_instance(hass)
    value = await recorder.async_add_executor_job(_query, before - timedelta(days=35))
    if value is None:
        # Rare: a gap longer than 35 days. Look at the whole history.
        value = await recorder.async_add_executor_job(_query, datetime(2000, 1, 1, tzinfo=UTC))
    return value


async def async_import_readings(
    hass: HomeAssistant,
    pod: str,
    readings: list[HourlyReading],
    price_per_kwh: float,
    *,
    from_zero: bool = False,
) -> None:
    """Write readings as hourly statistics.

    The cumulative sum continues from the value stored for the hour right
    before the first reading, so re-importing an overlapping window (as the
    daily update does) rewrites those hours with the same values instead of
    stacking them on top of the latest total.
    """
    if not readings:
        return

    kwh_id = consumption_statistic_id(pod)
    cost_id = cost_statistic_id(pod)

    if from_zero:
        kwh_offset = cost_offset = 0.0
    else:
        first_start = readings[0].start
        kwh_offset = await async_get_sum_before(hass, kwh_id, first_start) or 0.0
        cost_offset = await async_get_sum_before(hass, cost_id, first_start)
        if cost_offset is None:
            cost_offset = kwh_offset * price_per_kwh

    kwh_rows, cost_rows = build_cumulative(readings, kwh_offset, cost_offset, price_per_kwh)

    async_add_external_statistics(
        hass,
        _metadata(kwh_id, f"Enel {pod} Consumption", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
        kwh_rows,
    )
    async_add_external_statistics(
        hass,
        _metadata(cost_id, f"Enel {pod} Cost", CURRENCY, None),
        cost_rows,
    )
    _LOGGER.debug(
        "Queued %s hourly statistics for %s (%s -> %s, offset %.3f kWh)",
        len(kwh_rows),
        pod,
        readings[0].start,
        readings[-1].start,
        kwh_offset,
    )


def async_clear(hass: HomeAssistant, pod: str) -> None:
    """Queue deletion of both statistics (runs in order in the recorder queue)."""
    get_instance(hass).async_clear_statistics([consumption_statistic_id(pod), cost_statistic_id(pod)])
