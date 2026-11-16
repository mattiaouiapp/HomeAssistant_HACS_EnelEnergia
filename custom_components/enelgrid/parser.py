"""Pure functions to parse Enel consumption data (no Home Assistant imports)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import logging
import re
from typing import Any

from .const import ENEL_TZ

_LOGGER = logging.getLogger(__name__)

_HOUR_BIN = re.compile(r"^H(\d+)$")


@dataclass(frozen=True, slots=True)
class HourlyReading:
    """Energy consumed in one hour."""

    start: datetime  # timezone-aware, UTC
    kwh: float


@dataclass(frozen=True, slots=True)
class ConsumptionSummary:
    """Values exposed by the sensors."""

    current_month_kwh: float
    previous_month_kwh: float
    last_day: date | None
    last_day_kwh: float | None
    last_reading_end: datetime | None
    readings_count: int


def _hours_in_day(day: date) -> int:
    start = datetime.combine(day, time(), ENEL_TZ).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), ENEL_TZ).astimezone(UTC)
    return round((end - start) / timedelta(hours=1))


def _bin_start(day: date, hour_number: int, elapsed: bool) -> datetime:
    """Return the UTC start of the Enel bin H<hour_number> of an Italian day.

    elapsed=True:  H<n> is the n-th elapsed hour of the day (correct when Enel
                   returns 23 bins in March and 25 in October).
    elapsed=False: H<n> is the wall-clock hour n-1 (fallback when Enel returns
                   24 bins on a DST day). The nonexistent 02:00 in March lands
                   on the same UTC hour as 03:00 and gets summed with it.
    """
    if elapsed:
        midnight = datetime.combine(day, time(), ENEL_TZ).astimezone(UTC)
        return midnight + timedelta(hours=hour_number - 1)
    local = datetime.combine(day, time(hour_number - 1), ENEL_TZ)
    return local.astimezone(UTC)


def parse_hourly_consumption(data: dict[str, Any]) -> list[HourlyReading]:
    """Extract hourly readings (sorted, UTC) from an aggregateConsumption response.

    Returns an empty list when the response contains no hourly data.
    """
    aggregations = (data or {}).get("data", {}).get("aggregationResult", {}).get("aggregations") or []
    hourly = next(
        (agg for agg in aggregations if agg.get("referenceID") == "hourlyConsumption"),
        None,
    )
    if hourly is None:
        _LOGGER.debug("No hourlyConsumption aggregation in Enel response")
        return []

    by_start: dict[datetime, float] = defaultdict(float)
    for day_result in hourly.get("results") or []:
        try:
            day = datetime.strptime(day_result["date"], "%d%m%Y").date()
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Skipping Enel result with invalid date: %s", day_result.get("date"))
            continue

        bins: list[tuple[int, float]] = []
        for entry in day_result.get("binValues") or []:
            match = _HOUR_BIN.match(str(entry.get("name", "")))
            value = entry.get("value")
            if not match or value is None:
                continue
            bins.append((int(match.group(1)), float(value)))
        if not bins:
            continue
        bins.sort()

        hours = _hours_in_day(day)
        elapsed = len(bins) == hours or hours == 24
        if not elapsed:
            _LOGGER.debug(
                "Enel returned %s bins for %s (%s hours long): using wall-clock mapping",
                len(bins),
                day,
                hours,
            )
        for hour_number, kwh in bins:
            if hour_number < 1 or hour_number > max(hours, 24):
                if kwh:
                    _LOGGER.warning("Ignoring unexpected bin H%s=%s on %s", hour_number, kwh, day)
                continue
            if elapsed and hour_number > hours:
                if kwh:
                    _LOGGER.warning("Ignoring unexpected bin H%s=%s on %s", hour_number, kwh, day)
                continue
            by_start[_bin_start(day, hour_number, elapsed)] += kwh

    return [HourlyReading(start, kwh) for start, kwh in sorted(by_start.items())]


def local_day(moment: datetime) -> date:
    """Italian calendar day of a UTC timestamp."""
    return moment.astimezone(ENEL_TZ).date()


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def first_of_previous_month(day: date) -> date:
    return (day.replace(day=1) - timedelta(days=1)).replace(day=1)


def month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into per-month ranges, newest first."""
    ranges: list[tuple[date, date]] = []
    cursor = end
    while cursor >= start:
        month_start = max(first_of_month(cursor), start)
        ranges.append((month_start, cursor))
        cursor = first_of_month(cursor) - timedelta(days=1)
    return ranges


def summarize(readings: list[HourlyReading], today: date) -> ConsumptionSummary:
    """Compute the values shown by the sensors."""
    daily: dict[date, float] = defaultdict(float)
    for reading in readings:
        daily[local_day(reading.start)] += reading.kwh

    this_month = first_of_month(today)
    prev_month = first_of_previous_month(today)
    current = sum(v for d, v in daily.items() if d >= this_month)
    previous = sum(v for d, v in daily.items() if prev_month <= d < this_month)

    # Enel may return zero-filled days that are not published yet: the last
    # meaningful day is the last one with consumption > 0.
    days_with_data = sorted(d for d, v in daily.items() if v > 0)
    last_day = days_with_data[-1] if days_with_data else None
    last_reading_end = None
    if last_day is not None:
        last_reading_end = max(r.start for r in readings if local_day(r.start) == last_day) + timedelta(
            hours=1
        )

    return ConsumptionSummary(
        current_month_kwh=round(current, 3),
        previous_month_kwh=round(previous, 3),
        last_day=last_day,
        last_day_kwh=round(daily[last_day], 3) if last_day else None,
        last_reading_end=last_reading_end,
        readings_count=len(readings),
    )


def build_cumulative(
    readings: list[HourlyReading],
    kwh_offset: float,
    cost_offset: float,
    price_per_kwh: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build hourly statistic rows ({"start", "state", "sum"}) for energy and cost."""
    kwh_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    kwh_total = kwh_offset
    cost_total = cost_offset
    for reading in readings:
        kwh_total += reading.kwh
        cost_total += reading.kwh * price_per_kwh
        kwh_rows.append({"start": reading.start, "state": reading.kwh, "sum": round(kwh_total, 6)})
        cost_rows.append(
            {
                "start": reading.start,
                "state": round(reading.kwh * price_per_kwh, 6),
                "sum": round(cost_total, 6),
            }
        )
    return kwh_rows, cost_rows
