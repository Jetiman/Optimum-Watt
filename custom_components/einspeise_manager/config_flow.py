"""Config flow for Einspeise-Manager."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    CONF_STAGE_ENTITY,
    CONF_STAGE_NAME,
    CONF_STAGE_RATED_POWER,
    CONF_STAGES,
    DEFAULT_STAGE_COUNT,
    DOMAIN,
    MAX_STAGE_COUNT,
    MIN_STAGE_COUNT,
)

STAGE_COUNT_KEY = "stage_count"


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_GRID_POWER_ENTITY, default=defaults.get(CONF_GRID_POWER_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_INVERT, default=defaults.get(CONF_INVERT, False)
            ): BooleanSelector(),
            vol.Required(
                STAGE_COUNT_KEY, default=defaults.get(STAGE_COUNT_KEY, DEFAULT_STAGE_COUNT)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_STAGE_COUNT,
                    max=MAX_STAGE_COUNT,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _stages_schema(stage_count: int, defaults: list[dict[str, Any]]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for i in range(stage_count):
        stage_default = defaults[i] if i < len(defaults) else {}
        fields[
            vol.Required(
                f"stage_{i}_name",
                default=stage_default.get(CONF_STAGE_NAME, f"Heizung {i + 1}"),
            )
        ] = TextSelector()
        fields[
            vol.Required(
                f"stage_{i}_entity",
                default=stage_default.get(CONF_STAGE_ENTITY),
            )
        ] = EntitySelector(EntitySelectorConfig(domain="switch"))
        fields[
            vol.Required(
                f"stage_{i}_power",
                default=stage_default.get(CONF_STAGE_RATED_POWER, 2000),
            )
        ] = NumberSelector(
            NumberSelectorConfig(min=0, max=20000, step=50, mode=NumberSelectorMode.BOX)
        )
    return vol.Schema(fields)


def _parse_stages(stage_count: int, user_input: dict[str, Any]) -> list[dict[str, Any]]:
    stages = []
    for i in range(stage_count):
        stages.append(
            {
                CONF_STAGE_NAME: user_input[f"stage_{i}_name"],
                CONF_STAGE_ENTITY: user_input[f"stage_{i}_entity"],
                CONF_STAGE_RATED_POWER: int(user_input[f"stage_{i}_power"]),
            }
        )
    return stages


class EinspeiseManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._stage_count = DEFAULT_STAGE_COUNT

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_GRID_POWER_ENTITY] = user_input[CONF_GRID_POWER_ENTITY]
            self._data[CONF_INVERT] = user_input[CONF_INVERT]
            self._stage_count = int(user_input[STAGE_COUNT_KEY])
            return await self.async_step_stages()

        return self.async_show_form(
            step_id="user", data_schema=_user_schema({}), errors=errors
        )

    async def async_step_stages(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_STAGES] = _parse_stages(self._stage_count, user_input)
            return self.async_create_entry(
                title="Einspeise-Manager", data=self._data
            )

        return self.async_show_form(
            step_id="stages",
            data_schema=_stages_schema(self._stage_count, []),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EinspeiseManagerOptionsFlow(config_entry)


class EinspeiseManagerOptionsFlow(OptionsFlow):
    """Allow editing the grid sensor and heater stages after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict[str, Any] = dict(config_entry.data)
        self._stage_count = len(self._data.get(CONF_STAGES, []))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self._data[CONF_GRID_POWER_ENTITY] = user_input[CONF_GRID_POWER_ENTITY]
            self._data[CONF_INVERT] = user_input[CONF_INVERT]
            self._stage_count = int(user_input[STAGE_COUNT_KEY])
            return await self.async_step_stages()

        defaults = dict(self._data)
        defaults[STAGE_COUNT_KEY] = self._stage_count
        return self.async_show_form(
            step_id="init", data_schema=_user_schema(defaults)
        )

    async def async_step_stages(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            self._data[CONF_STAGES] = _parse_stages(self._stage_count, user_input)
            self.hass.config_entries.async_update_entry(self._entry, data=self._data)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="stages",
            data_schema=_stages_schema(
                self._stage_count, self._data.get(CONF_STAGES, [])
            ),
        )
