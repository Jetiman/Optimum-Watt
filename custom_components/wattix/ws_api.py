"""WebSocket API used by the Wattix dashboard card.

All device management (add/edit/remove/reorder) happens through these
commands so the card can offer a live, app-like interface without round
trips through the config-entry options flow.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, MODE_AUTO, MODE_DISABLED, MODE_OFF, MODE_ON
from .coordinator import WattixCoordinator

# Local "HH:MM" time of day, e.g. "19:00" - the deadline for a device's
# daily minimum runtime.
DEADLINE_SCHEMA = vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$")


def _get_coordinator(
    hass: HomeAssistant, entry_id: str
) -> WattixCoordinator | None:
    return hass.data.get(DOMAIN, {}).get(entry_id)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/list_devices",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_list_devices(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/add_device",
        vol.Required("entry_id"): str,
        vol.Required("name"): str,
        vol.Required("entity_id"): str,
        vol.Required("power_w"): vol.Coerce(float),
        vol.Optional("hysteresis_w"): vol.Coerce(float),
        vol.Optional("on_delay_s"): vol.Coerce(int),
        vol.Optional("off_delay_s"): vol.Coerce(int),
        vol.Optional("min_runtime_s"): vol.Coerce(int),
        vol.Optional("min_runtime_deadline"): DEADLINE_SCHEMA,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_add_device(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    await coordinator.async_add_device(
        name=msg["name"],
        entity_id=msg["entity_id"],
        power_w=msg["power_w"],
        hysteresis_w=msg.get("hysteresis_w"),
        on_delay_s=msg.get("on_delay_s"),
        off_delay_s=msg.get("off_delay_s"),
        min_runtime_s=msg.get("min_runtime_s"),
        min_runtime_deadline=msg.get("min_runtime_deadline"),
    )
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/update_device",
        vol.Required("entry_id"): str,
        vol.Required("device_id"): str,
        vol.Optional("name"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("power_w"): vol.Coerce(float),
        vol.Optional("hysteresis_w"): vol.Coerce(float),
        vol.Optional("on_delay_s"): vol.Coerce(int),
        vol.Optional("off_delay_s"): vol.Coerce(int),
        vol.Optional("mode"): vol.In([MODE_AUTO, MODE_ON, MODE_OFF, MODE_DISABLED]),
        vol.Optional("min_runtime_s"): vol.Coerce(int),
        vol.Optional("min_runtime_deadline"): DEADLINE_SCHEMA,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update_device(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    fields = {
        key: value
        for key, value in msg.items()
        if key not in ("type", "id", "entry_id", "device_id")
    }
    try:
        await coordinator.async_update_device(msg["device_id"], **fields)
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unbekannte device_id")
        return
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/remove_device",
        vol.Required("entry_id"): str,
        vol.Required("device_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_remove_device(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    try:
        await coordinator.async_remove_device(msg["device_id"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unbekannte device_id")
        return
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/reorder_devices",
        vol.Required("entry_id"): str,
        vol.Required("device_ids"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reorder_devices(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    try:
        await coordinator.async_reorder_devices(msg["device_ids"])
    except ValueError:
        connection.send_error(
            msg["id"], "invalid_format", "device_ids passt nicht zu den vorhandenen Geräten"
        )
        return
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/set_auto_mode",
        vol.Required("entry_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_auto_mode(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return
    coordinator.set_auto_mode(msg["enabled"])
    connection.send_result(msg["id"], coordinator.state_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "wattix/subscribe",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_subscribe(hass, connection, msg):
    coordinator = _get_coordinator(hass, msg["entry_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Unbekannte entry_id")
        return

    @callback
    def _push() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], coordinator.state_dict())
        )

    remove_listener = coordinator.async_add_listener(_push)
    connection.subscriptions[msg["id"]] = remove_listener
    connection.send_result(msg["id"])
    _push()


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all wattix/* websocket commands, once per hass instance."""
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_add_device)
    websocket_api.async_register_command(hass, ws_update_device)
    websocket_api.async_register_command(hass, ws_remove_device)
    websocket_api.async_register_command(hass, ws_reorder_devices)
    websocket_api.async_register_command(hass, ws_set_auto_mode)
    websocket_api.async_register_command(hass, ws_subscribe)
