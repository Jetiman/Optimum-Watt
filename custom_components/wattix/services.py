"""Service handlers for Wattix (automation-friendly device control)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MODE_AUTO, MODE_DISABLED, MODE_OFF, MODE_ON
from .coordinator import WattixCoordinator

SERVICE_ADD_DEVICE = "add_device"
SERVICE_REMOVE_DEVICE = "remove_device"
SERVICE_SET_DEVICE_MODE = "set_device_mode"
SERVICE_SET_AUTO_MODE = "set_auto_mode"

ATTR_ENTRY_ID = "entry_id"
ATTR_DEVICE_ID = "device_id"
ATTR_NAME = "name"
ATTR_ENTITY_ID = "entity_id"
ATTR_POWER_W = "power_w"
ATTR_HYSTERESIS_W = "hysteresis_w"
ATTR_ON_DELAY_S = "on_delay_s"
ATTR_OFF_DELAY_S = "off_delay_s"
ATTR_MODE = "mode"
ATTR_ENABLED = "enabled"
ATTR_MIN_RUNTIME_S = "min_runtime_s"
ATTR_MIN_RUNTIME_DEADLINE = "min_runtime_deadline"

DEADLINE_SCHEMA = vol.Any(vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$"), "")

ADD_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_POWER_W): vol.Coerce(float),
        vol.Optional(ATTR_HYSTERESIS_W): vol.Coerce(float),
        vol.Optional(ATTR_ON_DELAY_S): vol.Coerce(int),
        vol.Optional(ATTR_OFF_DELAY_S): vol.Coerce(int),
        vol.Optional(ATTR_MIN_RUNTIME_S): vol.Coerce(int),
        vol.Optional(ATTR_MIN_RUNTIME_DEADLINE): DEADLINE_SCHEMA,
    }
)

REMOVE_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_DEVICE_ID): cv.string,
    }
)

SET_DEVICE_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_MODE): vol.In([MODE_AUTO, MODE_ON, MODE_OFF, MODE_DISABLED]),
    }
)

SET_AUTO_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_ENABLED): cv.boolean,
    }
)


def _coordinator(hass: HomeAssistant, entry_id: str) -> WattixCoordinator:
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        raise ServiceValidationError(f"Unbekannte entry_id: {entry_id}")
    return coordinator


async def async_register_services(hass: HomeAssistant) -> None:
    """Register wattix.* services, once per hass instance."""

    async def handle_add_device(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data[ATTR_ENTRY_ID])
        await coordinator.async_add_device(
            name=call.data[ATTR_NAME],
            entity_id=call.data[ATTR_ENTITY_ID],
            power_w=call.data[ATTR_POWER_W],
            hysteresis_w=call.data.get(ATTR_HYSTERESIS_W),
            on_delay_s=call.data.get(ATTR_ON_DELAY_S),
            off_delay_s=call.data.get(ATTR_OFF_DELAY_S),
            min_runtime_s=call.data.get(ATTR_MIN_RUNTIME_S),
            min_runtime_deadline=call.data.get(ATTR_MIN_RUNTIME_DEADLINE),
        )

    async def handle_remove_device(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data[ATTR_ENTRY_ID])
        try:
            await coordinator.async_remove_device(call.data[ATTR_DEVICE_ID])
        except KeyError as err:
            raise ServiceValidationError(
                f"Unbekannte device_id: {call.data[ATTR_DEVICE_ID]}"
            ) from err

    async def handle_set_device_mode(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data[ATTR_ENTRY_ID])
        try:
            await coordinator.async_update_device(
                call.data[ATTR_DEVICE_ID], mode=call.data[ATTR_MODE]
            )
        except KeyError as err:
            raise ServiceValidationError(
                f"Unbekannte device_id: {call.data[ATTR_DEVICE_ID]}"
            ) from err

    async def handle_set_auto_mode(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call.data[ATTR_ENTRY_ID])
        coordinator.set_auto_mode(call.data[ATTR_ENABLED])

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_DEVICE, handle_add_device, schema=ADD_DEVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_DEVICE, handle_remove_device, schema=REMOVE_DEVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEVICE_MODE,
        handle_set_device_mode,
        schema=SET_DEVICE_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_AUTO_MODE, handle_set_auto_mode, schema=SET_AUTO_MODE_SCHEMA
    )
