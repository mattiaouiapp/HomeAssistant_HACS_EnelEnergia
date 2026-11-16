"""Config, reauth and options flow tests."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.enelgrid.api import EnelGridAuthError, EnelGridError
from custom_components.enelgrid.const import (
    CONF_PASSWORD,
    CONF_POD,
    CONF_PRICE_PER_KWH,
    CONF_USER_NUMBER,
    CONF_USERNAME,
    DATA_HISTORICAL_FETCH_NEEDED,
    DOMAIN,
)

USER_INPUT = {
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "password123",
    CONF_POD: " it001e 00000001 ",
    CONF_USER_NUMBER: "012345678",
    CONF_PRICE_PER_KWH: 0.25,
}


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.enelgrid.async_setup_entry", return_value=True):
        yield


async def test_user_flow_success(hass: HomeAssistant, fake_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Enel IT001E00000001"
    data = result["data"]
    assert data[CONF_POD] == "IT001E00000001"
    assert data[CONF_USER_NUMBER] == "012345678"  # leading zero preserved
    assert data[DATA_HISTORICAL_FETCH_NEEDED] is True
    assert result["result"].unique_id == "IT001E00000001"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (EnelGridAuthError("x"), "invalid_auth"),
        (EnelGridError("x"), "cannot_connect"),
        (RuntimeError("x"), "unknown"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, fake_client, error, expected):
    fake_client.login_error = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    fake_client.login_error = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_number_must_be_digits(hass: HomeAssistant, fake_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_USER_NUMBER: "abc"}
    )
    assert result["errors"] == {CONF_USER_NUMBER: "invalid_user_number"}


async def test_already_configured(hass: HomeAssistant, fake_client):
    MockConfigEntry(domain=DOMAIN, unique_id="IT001E00000001", version=5).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, fake_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="IT001E00000001",
        version=5,
        data={**USER_INPUT, CONF_POD: "IT001E00000001", CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    fake_client.login_error = EnelGridAuthError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    fake_client.login_error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data[CONF_POD] == "IT001E00000001"


async def test_options_flow(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, version=5, data={CONF_PRICE_PER_KWH: 0.3})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_PRICE_PER_KWH: 0.21})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PRICE_PER_KWH] == 0.21
