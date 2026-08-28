"""Config flow for Einspeise-Manager.

Only the grid feed-in power sensor is configured here. Devices are added,
prioritized and tuned afterwards in the integration's own dashboard card.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
)

from .const import CONF_GRID_POWER_ENTITY, CONF_INVERT, DOMAIN


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_GRID_POWER_ENTITY, default=defaults.get(CONF_GRID_POWER_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_INVERT, default=defaults.get(CONF_INVERT, False)
            ): BooleanSelector(),
        }
    )


class EinspeiseManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="Einspeise-Manager", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EinspeiseManagerOptionsFlow(config_entry)


class EinspeiseManagerOptionsFlow(OptionsFlow):
    """Allow editing the grid sensor after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(self._entry, data=user_input)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self._entry.data))
        )
