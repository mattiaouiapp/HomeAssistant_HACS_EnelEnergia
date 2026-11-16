"""Config flow for enelgrid."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

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
)

_LOGGER = logging.getLogger(__name__)

PRICE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=5, step=0.001, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="€/kWh"
    )
)


def _normalize_pod(pod: str) -> str:
    return "".join(pod.split()).upper()


async def _validate(username: str, password: str, pod: str, user_number: str) -> str | None:
    """Try to log in. Return an error key or None."""
    try:
        async with EnelGridClient(username, password, pod, user_number):
            pass
    except EnelGridAuthError:
        return "invalid_auth"
    except EnelGridError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating Enel credentials")
        return "unknown"
    return None


class EnelGridConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for enelgrid."""

    VERSION = 5

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            pod = _normalize_pod(user_input[CONF_POD])
            user_number = user_input[CONF_USER_NUMBER].strip()
            await self.async_set_unique_id(pod)
            self._abort_if_unique_id_configured()

            if not user_number.isdigit():
                errors[CONF_USER_NUMBER] = "invalid_user_number"
            elif error := await _validate(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD], pod, user_number
            ):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Enel {pod}",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_POD: pod,
                        CONF_USER_NUMBER: user_number,
                        CONF_PRICE_PER_KWH: user_input[CONF_PRICE_PER_KWH],
                        # New installs also get the full history.
                        DATA_HISTORICAL_FETCH_NEEDED: True,
                        DATA_HISTORICAL_FETCH_COMPLETED: False,
                    },
                )

        user_input = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL, autocomplete="username")
                ),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD, autocomplete="current-password"
                    )
                ),
                vol.Required(CONF_POD, default=user_input.get(CONF_POD, "")): str,
                vol.Required(CONF_USER_NUMBER, default=user_input.get(CONF_USER_NUMBER, "")): str,
                vol.Required(
                    CONF_PRICE_PER_KWH,
                    default=user_input.get(CONF_PRICE_PER_KWH, DEFAULT_PRICE_PER_KWH),
                ): PRICE_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data[CONF_POD],
                entry.data[CONF_USER_NUMBER],
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={"pod": entry.data[CONF_POD]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EnelGridOptionsFlow:
        return EnelGridOptionsFlow()


class EnelGridOptionsFlow(OptionsFlowWithReload):
    """Options: price per kWh."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_PRICE_PER_KWH,
            self.config_entry.data.get(CONF_PRICE_PER_KWH, DEFAULT_PRICE_PER_KWH),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_PRICE_PER_KWH, default=current): PRICE_SELECTOR}),
        )
