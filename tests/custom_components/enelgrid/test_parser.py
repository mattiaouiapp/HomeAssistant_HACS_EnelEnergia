"""Tests for the pure parsing helpers."""

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.enelgrid.parser import (
    HourlyReading,
    build_cumulative,
    month_ranges,
    parse_hourly_consumption,
    summarize,
)
from tests.conftest import enel_response


def _assert_contiguous(readings):
    starts = [r.start for r in readings]
    assert len(starts) == len(set(starts))
    for a, b in zip(starts, starts[1:]):
        assert b - a == timedelta(hours=1)


def test_normal_day_is_converted_to_utc():
    readings = parse_hourly_consumption(enel_response({date(2025, 1, 15): [1.0] * 24}))
    assert len(readings) == 24
    # 00:00 CET = 23:00 UTC of the previous day
    assert readings[0].start == datetime(2025, 1, 14, 23, tzinfo=UTC)
    assert readings[-1].start == datetime(2025, 1, 15, 22, tzinfo=UTC)
    _assert_contiguous(readings)


def test_spring_dst_day_with_23_bins():
    readings = parse_hourly_consumption(enel_response({date(2025, 3, 30): [float(i) for i in range(1, 24)]}))
    assert len(readings) == 23
    _assert_contiguous(readings)
    assert sum(r.kwh for r in readings) == sum(range(1, 24))


def test_spring_dst_day_with_24_bins_keeps_all_energy():
    values = [1.0] * 24
    readings = parse_hourly_consumption(enel_response({date(2025, 3, 30): values}))
    assert len(readings) == 23
    _assert_contiguous(readings)
    assert sum(r.kwh for r in readings) == pytest.approx(24.0)


def test_autumn_dst_day_with_25_bins_does_not_overlap_next_day():
    readings = parse_hourly_consumption(
        enel_response({date(2025, 10, 26): [1.0] * 25, date(2025, 10, 27): [2.0] * 24})
    )
    assert len(readings) == 49
    _assert_contiguous(readings)
    assert sum(r.kwh for r in readings) == pytest.approx(25 + 48)


def test_missing_aggregation_returns_empty():
    assert parse_hourly_consumption({"data": {"aggregationResult": {"aggregations": []}}}) == []
    assert parse_hourly_consumption({}) == []


def test_null_values_are_skipped():
    data = enel_response({date(2025, 1, 15): [1.0] * 24})
    data["data"]["aggregationResult"]["aggregations"][0]["results"][0]["binValues"][5]["value"] = None
    assert len(parse_hourly_consumption(data)) == 23


def test_summarize_months_and_last_day():
    days = {}
    for d in range(1, 31):
        days[date(2025, 10, d)] = [0.1] * 24  # 2.4 kWh/day
    for d in range(1, 13):
        days[date(2025, 11, d)] = [0.5] * 24  # 12 kWh/day
    for d in range(13, 16):
        days[date(2025, 11, d)] = [0.0] * 24  # not published yet
    readings = parse_hourly_consumption(enel_response(days))

    summary = summarize(readings, date(2025, 11, 16))
    assert summary.current_month_kwh == pytest.approx(144.0)
    assert summary.previous_month_kwh == pytest.approx(72.0)
    assert summary.last_day == date(2025, 11, 12)
    assert summary.last_day_kwh == pytest.approx(12.0)
    assert summary.last_reading_end == datetime(2025, 11, 12, 23, tzinfo=UTC)


def test_build_cumulative_continues_from_offsets():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    readings = [HourlyReading(start + timedelta(hours=i), 1.0) for i in range(3)]
    kwh, cost = build_cumulative(readings, kwh_offset=100.0, cost_offset=30.0, price_per_kwh=0.5)
    assert [r["sum"] for r in kwh] == [101.0, 102.0, 103.0]
    assert [r["sum"] for r in cost] == [30.5, 31.0, 31.5]


def test_month_ranges():
    assert month_ranges(date(2025, 10, 1), date(2025, 11, 16)) == [
        (date(2025, 11, 1), date(2025, 11, 16)),
        (date(2025, 10, 1), date(2025, 10, 31)),
    ]
    assert month_ranges(date(2025, 10, 20), date(2025, 10, 25)) == [(date(2025, 10, 20), date(2025, 10, 25))]
