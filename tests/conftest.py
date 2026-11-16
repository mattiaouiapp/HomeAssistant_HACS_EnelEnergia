"""Shared fixtures for enelgrid tests."""

from __future__ import annotations

from datetime import date, timedelta
import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Enable custom components (and a real recorder) for every test."""
    yield


def enel_response(days: dict[date, list[float]]) -> dict[str, Any]:
    """Build an aggregateConsumption response: {day: [H1, H2, ...]}."""
    return {
        "data": {
            "aggregationResult": {
                "aggregations": [
                    {
                        "referenceID": "hourlyConsumption",
                        "results": [
                            {
                                "date": day.strftime("%d%m%Y"),
                                "binValues": [
                                    {"name": f"H{i + 1}", "value": v} for i, v in enumerate(values)
                                ],
                            }
                            for day, values in days.items()
                        ],
                    }
                ]
            }
        }
    }


def flat_days(start: date, end: date, kwh_per_hour: float = 0.5) -> dict[date, list[float]]:
    days = {}
    cursor = start
    while cursor <= end:
        days[cursor] = [kwh_per_hour] * 24
        cursor += timedelta(days=1)
    return days


def bill_archive() -> dict[str, Any]:
    """getArchivioBollette 'data' with one unpaid and two paid bills (newest not first)."""

    def bill(issue, due, amount, residual, status, period, paid=None):
        raw = {
            "Tipodocumento": "F",
            "Numerodocumento": "000000000000",
            "Dataemissione": issue,
            "Datascadenza": due,
            "Importofattura": amount,
            "Importoresiduo": residual,
            "ImportocanoneTV": "9.00",
            "Statopagabilita": status,
            "Periododiriferimento": period,
        }
        if paid:
            raw["Datapagamento"] = paid
        return raw

    return {
        "dataAggiornamento": "01-04-2025 10:00:00",
        "results": [
            {
                "contoContrattuale": "000000000000",
                "fatture": [
                    bill("2025-01-10", "2025-01-27", "98.40", "0.00", "PAGATA", "112024122024", "2025-01-30"),
                    bill("2025-03-12", "2025-03-28", "120.50", "120.50", "DA PAGARE", "012025022025"),
                    bill("2024-11-08", "2024-11-25", "87.15", "0.00", "PAGATA", "092024102024", "2024-11-20"),
                ],
            }
        ],
    }


class FakeEnelClient:
    """Stand-in for EnelGridClient.

    Returns 0.5 kWh/hour for every requested day between `first_day` and
    `last_day` (inclusive), nothing outside. Class attributes allow tests to
    tweak the behaviour.
    """

    first_day = date(2025, 6, 1)
    last_day = date(2025, 11, 13)
    login_error: Exception | None = None
    fetch_error: Exception | None = None
    bills_error: Exception | None = None
    calls: list[tuple[date, date]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        if FakeEnelClient.login_error:
            raise FakeEnelClient.login_error
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_consumption(self, start: date, end: date):
        FakeEnelClient.calls.append((start, end))
        if FakeEnelClient.fetch_error:
            raise FakeEnelClient.fetch_error
        lo = max(start, FakeEnelClient.first_day)
        hi = min(end, FakeEnelClient.last_day)
        return enel_response(flat_days(lo, hi) if lo <= hi else {})

    async def fetch_bills(self):
        if FakeEnelClient.bills_error:
            raise FakeEnelClient.bills_error
        return bill_archive()


@pytest.fixture
def fake_client():
    FakeEnelClient.first_day = date(2025, 6, 1)
    FakeEnelClient.last_day = date(2025, 11, 13)
    FakeEnelClient.login_error = None
    FakeEnelClient.fetch_error = None
    FakeEnelClient.bills_error = None
    FakeEnelClient.calls = []
    from unittest.mock import patch

    with (
        patch("custom_components.enelgrid.coordinator.EnelGridClient", FakeEnelClient),
        patch("custom_components.enelgrid.config_flow.EnelGridClient", FakeEnelClient),
    ):
        yield FakeEnelClient
