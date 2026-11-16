"""Setup, historical import, sensors and migration tests."""

from datetime import UTC, date, datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.enelgrid.api import EnelGridAuthError
from custom_components.enelgrid.const import (
    CONF_PASSWORD,
    CONF_POD,
    CONF_PRICE_PER_KWH,
    CONF_USER_NUMBER,
    CONF_USERNAME,
    DATA_HISTORICAL_FETCH_COMPLETED,
    DATA_HISTORICAL_FETCH_NEEDED,
    DOMAIN,
    LEGACY_CONF_POD,
    LEGACY_CONF_USER_NUMBER,
)
from custom_components.enelgrid.statistics import consumption_statistic_id

POD = "IT001E00000001"
DATA = {
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "pw",
    CONF_POD: POD,
    CONF_USER_NUMBER: "12345678",
    CONF_PRICE_PER_KWH: 0.2,
}


@pytest.fixture(autouse=True)
def frozen_time(freezer):
    freezer.move_to("2025-11-16 10:00:00+00:00")


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await async_wait_recording_done(hass)


async def _sums(hass):
    stat_id = consumption_statistic_id(POD)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        {stat_id},
        "hour",
        None,
        {"sum"},
    )
    return [r["sum"] for r in result.get(stat_id, [])]


async def test_new_entry_imports_full_history_and_creates_sensors(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(
        domain=DOMAIN, version=5, unique_id=POD, data={**DATA, DATA_HISTORICAL_FETCH_NEEDED: True}
    )
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[DATA_HISTORICAL_FETCH_NEEDED] is False
    assert entry.data[DATA_HISTORICAL_FETCH_COMPLETED] is True

    sums = await _sums(hass)
    hours = (date(2025, 11, 13) - date(2025, 6, 1)).days * 24 + 24
    assert len(sums) == hours
    assert sums[-1] == pytest.approx(hours * 0.5)

    # Legacy entity_id kept, value = 13 days of November * 12 kWh
    monthly = hass.states.get("sensor.enelgrid_it001e00000001_monthly_consumption")
    assert monthly is not None
    assert float(monthly.state) == pytest.approx(13 * 12)

    registry = er.async_get(hass)
    entities = {
        e.unique_id.removeprefix("it001e00000001_"): e.entity_id
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
    }
    assert set(entities) == {
        "monthly_consumption",
        "previous_month_consumption",
        "last_day_consumption",
        "monthly_cost",
        "last_reading",
        "last_bill",
        "previous_bill",
        "amount_due",
    }
    assert float(hass.states.get(entities["previous_month_consumption"]).state) == pytest.approx(31 * 12)
    last_day = hass.states.get(entities["last_day_consumption"])
    assert float(last_day.state) == pytest.approx(12)
    assert last_day.attributes["date"] == "2025-11-13"
    assert float(hass.states.get(entities["monthly_cost"]).state) == pytest.approx(13 * 12 * 0.2)
    last_reading = hass.states.get(entities["last_reading"])
    assert last_reading.state == "2025-11-13T23:00:00+00:00"
    assert last_reading.attributes["historical_import"] == "completed"


async def test_regular_update_does_not_create_jumps(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(
        domain=DOMAIN, version=5, unique_id=POD, data={**DATA, DATA_HISTORICAL_FETCH_NEEDED: True}
    )
    await _setup(hass, entry)

    fake_client.last_day = date(2025, 11, 14)
    await entry.runtime_data.async_refresh()
    await async_wait_recording_done(hass)
    fake_client.last_day = date(2025, 11, 15)
    await entry.runtime_data.async_refresh()
    await async_wait_recording_done(hass)

    sums = await _sums(hass)
    deltas = {round(b - a, 6) for a, b in zip(sums, sums[1:])}
    assert deltas == {0.5}
    assert sums[-1] == pytest.approx(len(sums) * 0.5)


async def test_migration_from_v4(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        unique_id=POD,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "pw",
            LEGACY_CONF_POD: POD,
            LEGACY_CONF_USER_NUMBER: 12345678,
            CONF_PRICE_PER_KWH: 0.2,
            "historical_fetch_completed": True,
            "clear_statistics_needed": False,
        },
    )
    await _setup(hass, entry)
    assert entry.version == 5
    assert entry.data[CONF_POD] == POD
    assert entry.data[CONF_USER_NUMBER] == "12345678"
    assert LEGACY_CONF_POD not in entry.data
    assert "clear_statistics_needed" not in entry.data
    # Statistics are rebuilt after the migration
    assert entry.data[DATA_HISTORICAL_FETCH_COMPLETED] is True
    assert len(await _sums(hass)) > 0


async def test_auth_failure_starts_reauth(hass: HomeAssistant, fake_client):
    fake_client.login_error = EnelGridAuthError("bad")
    entry = MockConfigEntry(domain=DOMAIN, version=5, unique_id=POD, data=DATA)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_unload(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(domain=DOMAIN, version=5, unique_id=POD, data=DATA)
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_bill_sensors(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(domain=DOMAIN, version=5, unique_id=POD, data=DATA)
    await _setup(hass, entry)
    registry = er.async_get(hass)

    def state(key):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"it001e00000001_{key}")
        return hass.states.get(entity_id)

    last = state("last_bill")
    assert float(last.state) == pytest.approx(120.50)
    assert last.attributes["issue_date"] == "2025-03-12"
    assert last.attributes["due_date"] == "2025-03-28"
    assert last.attributes["period"] == "gennaio - febbraio 2025"
    assert last.attributes["status"] == "Da pagare"

    previous = state("previous_bill")
    assert float(previous.state) == pytest.approx(98.40)
    assert previous.attributes["paid_on"] == "2025-01-30"

    due = state("amount_due")
    assert float(due.state) == pytest.approx(120.50)
    assert due.attributes["unpaid_bills"] == 1
    assert due.attributes["next_due_date"] == "2025-03-28"


async def test_bill_error_does_not_break_consumption(hass: HomeAssistant, fake_client):
    from custom_components.enelgrid.api import EnelGridError

    fake_client.bills_error = EnelGridError("archive down")
    entry = MockConfigEntry(domain=DOMAIN, version=5, unique_id=POD, data=DATA)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.bills is None
    assert entry.runtime_data.bills_error == "archive down"
