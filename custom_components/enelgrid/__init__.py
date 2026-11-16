"""The enelgrid integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_POD,
    CONF_USER_NUMBER,
    DATA_HISTORICAL_FETCH_COMPLETED,
    DATA_HISTORICAL_FETCH_NEEDED,
    LEGACY_CONF_POD,
    LEGACY_CONF_USER_NUMBER,
)
from .coordinator import EnelGridConfigEntry, EnelGridCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CURRENT_VERSION = 5


async def async_setup_entry(hass: HomeAssistant, entry: EnelGridConfigEntry) -> bool:
    """Set up enelgrid from a config entry."""
    coordinator = EnelGridCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if coordinator.historical_pending:
        entry.async_create_background_task(
            hass, coordinator.async_historical_import(), "enelgrid historical import"
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnelGridConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _find_legacy(data: dict[str, Any], exact: tuple[str, ...], prefix: str) -> Any:
    for key in exact:
        if data.get(key) not in (None, ""):
            return data[key]
    for key, value in data.items():
        if key.lower().startswith(prefix) and value not in (None, ""):
            return value
    return None


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to version 5.

    Versions 1-4 used the form labels as keys ("pod: IT1234567890",
    "numero utente"). v1.6.0 also corrupted the statistics on every daily
    update (the overlapping window was stacked on top of the latest total),
    so a full historical rebuild is scheduled.
    """
    if entry.version > CURRENT_VERSION:
        return False
    if entry.version == CURRENT_VERSION:
        return True

    data = dict(entry.data)
    pod = _find_legacy(data, (CONF_POD, LEGACY_CONF_POD), "pod")
    user_number = _find_legacy(data, (CONF_USER_NUMBER, LEGACY_CONF_USER_NUMBER), "numero")
    if pod is None or user_number is None:
        _LOGGER.error("enelgrid: cannot migrate entry %s, POD or user number missing", entry.entry_id)
        return False

    for key in (LEGACY_CONF_POD, LEGACY_CONF_USER_NUMBER, "clear_statistics_needed"):
        data.pop(key, None)
    data[CONF_POD] = str(pod).strip()
    data[CONF_USER_NUMBER] = str(user_number).strip()
    data[DATA_HISTORICAL_FETCH_NEEDED] = True
    data[DATA_HISTORICAL_FETCH_COMPLETED] = False

    hass.config_entries.async_update_entry(entry, data=data, version=CURRENT_VERSION)
    _LOGGER.info(
        "enelgrid: migrated entry for %s to version %s, statistics will be rebuilt",
        pod,
        CURRENT_VERSION,
    )
    return True
