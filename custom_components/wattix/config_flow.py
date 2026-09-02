"""Config flow for Wattix.

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

from .const import (
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    CONF_PV_PRODUCTION_ENTITY,
    CONF_STORAGE_INVERT,
    CONF_STORAGE_POWER_ENTITY,
    CONF_STORAGE_SOC_ENTITY,
    DOMAIN,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_GRID_POWER_ENTITY, default=defaults.get(CONF_GRID_POWER_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_INVERT, default=defaults.get(CONF_INVERT, False)
            ): BooleanSelector(),
            vol.Optional(
                CONF_PV_PRODUCTION_ENTITY,
                description={"suggested_value": defaults.get(CONF_PV_PRODUCTION_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_STORAGE_POWER_ENTITY,
                description={"suggested_value": defaults.get(CONF_STORAGE_POWER_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_STORAGE_INVERT, default=defaults.get(CONF_STORAGE_INVERT, False)
            ): BooleanSelector(),
            vol.Optional(
                CONF_STORAGE_SOC_ENTITY,
                description={"suggested_value": defaults.get(CONF_STORAGE_SOC_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop optional entity fields the user left empty instead of storing ''."""
    data = dict(user_input)
    for key in (CONF_PV_PRODUCTION_ENTITY, CONF_STORAGE_POWER_ENTITY, CONF_STORAGE_SOC_ENTITY):
        if not data.get(key):
            data.pop(key, None)
    return data


class WattixConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="Wattix", data=_normalize(user_input))

        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WattixOptionsFlow(config_entry)


class WattixOptionsFlow(OptionsFlow):
    """Allow editing the grid sensor after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self._entry, data=_normalize(user_input)
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self._entry.data))
        )
