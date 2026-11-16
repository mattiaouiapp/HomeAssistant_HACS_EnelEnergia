"""Diagnostics for enelgrid (replaces the old /config/enelgrid_debug JSON dumps)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_POD, CONF_USER_NUMBER, CONF_USERNAME
from .coordinator import EnelGridConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_POD,
    CONF_USER_NUMBER,
    "pod",
    "userNumber",
    "customerName",
    "address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnelGridConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "historical_import": coordinator.historical_status,
        "last_update_success": coordinator.last_update_success,
        "summary": asdict(coordinator.data) if coordinator.data else None,
        "last_raw_response": async_redact_data(coordinator.last_raw_response or {}, TO_REDACT),
    }
