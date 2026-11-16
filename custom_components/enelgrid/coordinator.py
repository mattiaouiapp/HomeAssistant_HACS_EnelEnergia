"""Data update coordinator for enelgrid."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EnelGridAuthError, EnelGridClient, EnelGridError
from .const import (
    CONF_PASSWORD,
    CONF_POD,
    CONF_PRICE_PER_KWH,
    CONF_USER_NUMBER,
    CONF_USERNAME,
    DATA_HISTORICAL_FETCH_COMPLETED,
    DATA_HISTORICAL_FETCH_NEEDED,
    DEFAULT_PRICE_PER_KWH,
    DOMAIN,
    ENEL_TZ,
    HISTORICAL_FETCH_RETRIES,
    HISTORICAL_MAX_MONTHS,
    UPDATE_INTERVAL,
)
from .parser import (
    Bill,
    ConsumptionSummary,
    HourlyReading,
    first_of_month,
    first_of_previous_month,
    local_day,
    month_ranges,
    parse_bills,
    parse_hourly_consumption,
    summarize,
)
from .statistics import (
    async_clear,
    async_get_last_statistic_start,
    async_import_readings,
    consumption_statistic_id,
)

_LOGGER = logging.getLogger(__name__)

# How far back the regular update goes to fill a gap (e.g. HA offline for weeks).
MAX_GAP_FILL = timedelta(days=365)

type EnelGridConfigEntry = ConfigEntry[EnelGridCoordinator]


class EnelGridCoordinator(DataUpdateCoordinator[ConsumptionSummary]):
    """Fetch Enel data, import it as statistics and expose a summary."""

    config_entry: EnelGridConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EnelGridConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_POD]}",
            update_interval=UPDATE_INTERVAL,
        )
        self._lock = asyncio.Lock()
        self.last_raw_response: dict[str, Any] | None = None
        # Bills are optional: an error there never fails the consumption update.
        self.bills: list[Bill] | None = None
        self.bills_error: str | None = None
        self.historical_status: str = (
            "pending" if entry.data.get(DATA_HISTORICAL_FETCH_NEEDED) else "not_needed"
        )

    @property
    def pod(self) -> str:
        return self.config_entry.data[CONF_POD]

    @property
    def price_per_kwh(self) -> float:
        return float(
            self.config_entry.options.get(
                CONF_PRICE_PER_KWH,
                self.config_entry.data.get(CONF_PRICE_PER_KWH, DEFAULT_PRICE_PER_KWH),
            )
        )

    @property
    def historical_pending(self) -> bool:
        return bool(self.config_entry.data.get(DATA_HISTORICAL_FETCH_NEEDED))

    def _client(self) -> EnelGridClient:
        data = self.config_entry.data
        return EnelGridClient(
            data[CONF_USERNAME], data[CONF_PASSWORD], data[CONF_POD], data[CONF_USER_NUMBER]
        )

    async def _fetch_month(self, client: EnelGridClient, start: date, end: date) -> list[HourlyReading]:
        raw = await client.fetch_consumption(start, end)
        self.last_raw_response = raw
        return parse_hourly_consumption(raw)

    async def _async_update_data(self) -> ConsumptionSummary:
        async with self._lock:
            today = dt_util.now(ENEL_TZ).date()
            window_start = first_of_previous_month(today)

            # Fill gaps: if the newest stored hour is older than the window,
            # start from that day (bounded) so no consumption is lost.
            if not self.historical_pending:
                last = await async_get_last_statistic_start(self.hass, consumption_statistic_id(self.pod))
                if last is not None and local_day(last) < window_start:
                    window_start = max(local_day(last), today - MAX_GAP_FILL)

            readings: list[HourlyReading] = []
            try:
                async with self._client() as client:
                    for start, end in reversed(month_ranges(window_start, today)):
                        readings.extend(await self._fetch_month(client, start, end))
                    await self._update_bills(client)
            except EnelGridAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except EnelGridError as err:
                raise UpdateFailed(str(err)) from err

            readings.sort(key=lambda r: r.start)
            if readings and not self.historical_pending:
                # The historical import rewrites everything anyway.
                await async_import_readings(self.hass, self.pod, readings, self.price_per_kwh)
            elif not readings:
                _LOGGER.info("Enel returned no hourly data for %s -> %s", window_start, today)

            return summarize(readings, today)

    async def _update_bills(self, client: EnelGridClient) -> None:
        """Refresh the bill list, keeping the previous one on errors."""
        try:
            self.bills = parse_bills(await client.fetch_bills())
            self.bills_error = None
        except (EnelGridError, KeyError, TypeError, ValueError) as err:
            self.bills_error = str(err)
            _LOGGER.warning("enelgrid %s: cannot read bills: %s", self.pod, err)

    async def async_historical_import(self) -> None:
        """Download the whole history and rebuild both statistics from scratch."""
        async with self._lock:
            self.historical_status = "running"
            today = dt_util.now(ENEL_TZ).date()
            _LOGGER.info("enelgrid %s: starting historical import", self.pod)

            readings: list[HourlyReading] = []
            months_with_data = 0
            complete = False
            month_end = today
            try:
                async with self._client() as client:
                    for _ in range(HISTORICAL_MAX_MONTHS):
                        month_start = first_of_month(month_end)
                        month = await self._fetch_with_retries(client, month_start, month_end)
                        if month:
                            readings.extend(month)
                            months_with_data += 1
                        # The current (and, early in the month, the previous) month
                        # can be empty because of Enel's publication delay: stop at
                        # the first empty month only once data has been found.
                        elif months_with_data or month_start < first_of_previous_month(today):
                            complete = True
                            break
                        month_end = month_start - timedelta(days=1)
                    else:
                        complete = True
            except EnelGridAuthError as err:
                _LOGGER.warning("enelgrid %s: historical import aborted, login failed: %s", self.pod, err)
                self.historical_status = "auth_failed"
                self.config_entry.async_start_reauth(self.hass)
                return
            except EnelGridError as err:
                _LOGGER.warning(
                    "enelgrid %s: historical import stopped after %s months: %s",
                    self.pod,
                    months_with_data,
                    err,
                )

            if not readings:
                # Keep the flag: it will be retried at the next restart/reload.
                _LOGGER.warning("enelgrid %s: historical import found no data, will retry later", self.pod)
                self.historical_status = "no_data"
                return

            readings.sort(key=lambda r: r.start)
            # Clearing and importing are both queued in the recorder queue, so
            # they run in order. Old statistics are deleted only now, after a
            # successful download.
            async_clear(self.hass, self.pod)
            await async_import_readings(self.hass, self.pod, readings, self.price_per_kwh, from_zero=True)

            new_data = {
                **self.config_entry.data,
                DATA_HISTORICAL_FETCH_NEEDED: False,
                DATA_HISTORICAL_FETCH_COMPLETED: True,
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            self.historical_status = "completed" if complete else "partial"
            self.async_update_listeners()
            _LOGGER.info(
                "enelgrid %s: historical import %s, %s months, %s hours (%s -> %s)",
                self.pod,
                self.historical_status,
                months_with_data,
                len(readings),
                readings[0].start,
                readings[-1].start,
            )

    async def _fetch_with_retries(
        self, client: EnelGridClient, start: date, end: date
    ) -> list[HourlyReading]:
        for attempt in range(1, HISTORICAL_FETCH_RETRIES + 1):
            try:
                return await self._fetch_month(client, start, end)
            except EnelGridAuthError:
                raise
            except EnelGridError as err:
                if attempt == HISTORICAL_FETCH_RETRIES:
                    raise
                _LOGGER.debug("Retry %s for %s -> %s: %s", attempt, start, end, err)
                await asyncio.sleep(5 * attempt)
        return []
