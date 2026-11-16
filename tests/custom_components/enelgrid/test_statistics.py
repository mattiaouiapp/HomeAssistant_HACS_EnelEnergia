"""Regression tests for the statistics import (the v1.6.0 'monthly jump' bug)."""

from datetime import UTC, date, datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.enelgrid.parser import parse_hourly_consumption
from custom_components.enelgrid.statistics import (
    async_import_readings,
    consumption_statistic_id,
    cost_statistic_id,
)
from tests.conftest import enel_response, flat_days

POD = "IT001E00000001"


async def _rows(hass, statistic_id):
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    return result.get(statistic_id, [])


async def test_daily_reimport_of_overlapping_window_is_continuous(hass: HomeAssistant):
    # Historical import: September -> 10 November
    history = parse_hourly_consumption(enel_response(flat_days(date(2025, 9, 1), date(2025, 11, 10))))
    await async_import_readings(hass, POD, history, 0.2, from_zero=True)
    await async_wait_recording_done(hass)

    # Two daily updates: window = 1 October -> today, with new days each time
    for last in (date(2025, 11, 11), date(2025, 11, 12)):
        window = parse_hourly_consumption(enel_response(flat_days(date(2025, 10, 1), last)))
        await async_import_readings(hass, POD, window, 0.2)
        await async_wait_recording_done(hass)

    rows = await _rows(hass, consumption_statistic_id(POD))
    sums = [r["sum"] for r in rows]
    deltas = {round(b - a, 6) for a, b in zip(sums, sums[1:])}
    assert deltas == {0.5}, "every hour must add exactly 0.5 kWh (no jump at the window start)"
    assert sums[-1] == pytest.approx(len(rows) * 0.5)

    cost = [r["sum"] for r in await _rows(hass, cost_statistic_id(POD))]
    assert cost[-1] == pytest.approx(len(rows) * 0.5 * 0.2)


async def test_price_change_only_affects_window(hass: HomeAssistant):
    history = parse_hourly_consumption(enel_response(flat_days(date(2025, 9, 1), date(2025, 9, 30))))
    await async_import_readings(hass, POD, history, 0.2, from_zero=True)
    await async_wait_recording_done(hass)

    window = parse_hourly_consumption(enel_response(flat_days(date(2025, 10, 1), date(2025, 10, 31))))
    await async_import_readings(hass, POD, window, 0.4)
    await async_wait_recording_done(hass)

    cost = [r["sum"] for r in await _rows(hass, cost_statistic_id(POD))]
    sept_hours = 30 * 24
    oct_hours = 31 * 24  # the fake data has 24 bins also on 26 October
    assert cost[sept_hours - 1] == pytest.approx(sept_hours * 0.5 * 0.2)
    assert cost[-1] == pytest.approx(sept_hours * 0.5 * 0.2 + oct_hours * 0.5 * 0.4)
