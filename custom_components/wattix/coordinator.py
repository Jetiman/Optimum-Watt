"""Core cascade control logic for the Wattix integration.

As long as enough power is being fed into the grid for a sustained period,
devices are switched on one after another in priority order (list order).
As soon as the surplus drops away for a sustained period, the most
recently activated device is switched off again (LIFO), with hysteresis
to avoid short-cycling the relays. Each device's own power requirement
doubles as the surplus threshold needed to switch it on.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    DEFAULT_HYSTERESIS_W,
    DEFAULT_ON_DELAY_S,
    DEFAULT_OFF_DELAY_S,
    DOMAIN,
    MODE_AUTO,
    MODE_OFF,
    MODE_ON,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _storage_key(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_devices"


@dataclass
class Device:
    """A single PV-surplus controlled consumer."""

    id: str
    name: str
    entity_id: str
    power_w: float
    hysteresis_w: float = DEFAULT_HYSTERESIS_W
    on_delay_s: int = DEFAULT_ON_DELAY_S
    off_delay_s: int = DEFAULT_OFF_DELAY_S
    mode: str = MODE_AUTO

    active: bool = False
    surplus_since: datetime | None = None
    deficit_since: datetime | None = None
    last_on_at: datetime | None = None

    @property
    def on_threshold_w(self) -> float:
        return self.power_w

    @property
    def off_threshold_w(self) -> float:
        return max(self.power_w - self.hysteresis_w, 0)

    def status_text(self) -> str:
        if self.mode == MODE_ON:
            return "manual_on"
        if self.mode == MODE_OFF:
            return "manual_off"
        return "auto_on" if self.active else "auto_off"

    def to_storage(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entity_id": self.entity_id,
            "power_w": self.power_w,
            "hysteresis_w": self.hysteresis_w,
            "on_delay_s": self.on_delay_s,
            "off_delay_s": self.off_delay_s,
            "mode": self.mode,
        }

    def to_dict(self, remaining_seconds: int | None) -> dict[str, Any]:
        data = self.to_storage()
        data.update(
            {
                "active": self.active,
                "status": self.status_text(),
                "on_threshold_w": self.on_threshold_w,
                "off_threshold_w": self.off_threshold_w,
                "remaining_seconds": remaining_seconds,
            }
        )
        return data

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> "Device":
        return cls(
            id=data["id"],
            name=data["name"],
            entity_id=data["entity_id"],
            power_w=data["power_w"],
            hysteresis_w=data.get("hysteresis_w", DEFAULT_HYSTERESIS_W),
            on_delay_s=data.get("on_delay_s", DEFAULT_ON_DELAY_S),
            off_delay_s=data.get("off_delay_s", DEFAULT_OFF_DELAY_S),
            mode=data.get("mode", MODE_AUTO),
        )


class WattixCoordinator(DataUpdateCoordinator[None]):
    """Coordinates surplus readings and drives the device cascade."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.grid_power_entity: str = entry.data[CONF_GRID_POWER_ENTITY]
        self.invert: bool = entry.data.get(CONF_INVERT, False)

        self.auto_mode: bool = True
        self.current_power_w: float | None = None
        self.devices: list[Device] = []

        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, _storage_key(entry.entry_id))
        self._remove_power_listener = None

    async def async_setup(self) -> None:
        """Load persisted devices and start listening to the grid power sensor."""
        stored = await self._store.async_load() or {}
        self.devices = [Device.from_storage(d) for d in stored.get("devices", [])]

        self._update_power_from_state(self.hass.states.get(self.grid_power_entity))

        @callback
        def _power_changed(event) -> None:
            self._update_power_from_state(event.data.get("new_state"))
            self.hass.async_create_task(self.async_request_refresh())

        self._remove_power_listener = async_track_state_change_event(
            self.hass, [self.grid_power_entity], _power_changed
        )

    @callback
    def async_unload(self) -> None:
        if self._remove_power_listener:
            self._remove_power_listener()
            self._remove_power_listener = None

    @staticmethod
    async def async_remove_storage(hass: HomeAssistant, entry_id: str) -> None:
        """Delete the persisted device list when the config entry is removed."""
        await Store(hass, STORAGE_VERSION, _storage_key(entry_id)).async_remove()

    @callback
    def _update_power_from_state(self, state: State | None) -> None:
        if state is None or state.state in ("unknown", "unavailable", ""):
            self.current_power_w = None
            return
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            self.current_power_w = None
            return
        self.current_power_w = -value if self.invert else value

    async def _async_update_data(self) -> None:
        await self._evaluate()

    async def request_reeval(self) -> None:
        """Public helper for entities/services to trigger an immediate re-evaluation."""
        await self.async_request_refresh()

    # -- Device CRUD -----------------------------------------------------

    async def _async_save_devices(self) -> None:
        await self._store.async_save({"devices": [d.to_storage() for d in self.devices]})

    def _get_device(self, device_id: str) -> Device:
        for device in self.devices:
            if device.id == device_id:
                return device
        raise KeyError(device_id)

    async def async_add_device(
        self,
        *,
        name: str,
        entity_id: str,
        power_w: float,
        hysteresis_w: float | None = None,
        on_delay_s: int | None = None,
        off_delay_s: int | None = None,
    ) -> Device:
        device = Device(
            id=uuid.uuid4().hex[:8],
            name=name,
            entity_id=entity_id,
            power_w=float(power_w),
            hysteresis_w=float(hysteresis_w) if hysteresis_w is not None else DEFAULT_HYSTERESIS_W,
            on_delay_s=int(on_delay_s) if on_delay_s is not None else DEFAULT_ON_DELAY_S,
            off_delay_s=int(off_delay_s) if off_delay_s is not None else DEFAULT_OFF_DELAY_S,
        )
        self.devices.append(device)
        await self._async_save_devices()
        await self.async_request_refresh()
        return device

    async def async_update_device(self, device_id: str, **fields: Any) -> Device:
        device = self._get_device(device_id)
        for key in (
            "name",
            "entity_id",
            "power_w",
            "hysteresis_w",
            "on_delay_s",
            "off_delay_s",
            "mode",
        ):
            if key in fields and fields[key] is not None:
                setattr(device, key, fields[key])
        await self._async_save_devices()
        await self.async_request_refresh()
        return device

    async def async_remove_device(self, device_id: str) -> None:
        device = self._get_device(device_id)
        self.devices.remove(device)
        await self._async_save_devices()
        await self.async_request_refresh()

    async def async_reorder_devices(self, device_ids: list[str]) -> None:
        by_id = {d.id: d for d in self.devices}
        if set(device_ids) != set(by_id):
            raise ValueError("device_ids must match the existing device set")
        self.devices = [by_id[i] for i in device_ids]
        await self._async_save_devices()
        await self.async_request_refresh()

    # -- Cascade evaluation ------------------------------------------------

    async def _evaluate(self) -> None:
        now = dt_util.utcnow()

        self._sync_active_from_states()

        for device in self.devices:
            await self._sync_manual_mode(device)

        if not self.auto_mode:
            return

        power = self.current_power_w
        if power is None:
            return

        # Turn ON: the highest-priority (first) inactive device in auto mode.
        candidate_on = next(
            (d for d in self.devices if d.mode == MODE_AUTO and not d.active), None
        )
        if candidate_on is not None:
            if power >= candidate_on.on_threshold_w:
                if candidate_on.surplus_since is None:
                    candidate_on.surplus_since = now
                elif now - candidate_on.surplus_since >= timedelta(seconds=candidate_on.on_delay_s):
                    await self._turn_on(candidate_on, now)
            else:
                candidate_on.surplus_since = None

        # Turn OFF: the lowest-priority (last) active device in auto mode (LIFO).
        active_auto_devices = [d for d in self.devices if d.mode == MODE_AUTO and d.active]
        if active_auto_devices:
            candidate_off = active_auto_devices[-1]
            if power < candidate_off.off_threshold_w:
                if candidate_off.deficit_since is None:
                    candidate_off.deficit_since = now
                elif now - candidate_off.deficit_since >= timedelta(seconds=candidate_off.off_delay_s):
                    await self._turn_off(candidate_off)
            else:
                candidate_off.deficit_since = None

    def _sync_active_from_states(self) -> None:
        """Reconcile our tracked state with the real switch (restart, manual toggle)."""
        for device in self.devices:
            live_state = self.hass.states.get(device.entity_id)
            if live_state is not None and live_state.state in ("on", "off"):
                device.active = live_state.state == "on"

    async def _sync_manual_mode(self, device: Device) -> None:
        """Force the relay to match a manual override, independent of surplus."""
        if device.mode == MODE_ON and not device.active:
            await self._turn_on(device, dt_util.utcnow())
        elif device.mode == MODE_OFF and device.active:
            await self._turn_off(device)

    async def _turn_on(self, device: Device, now: datetime) -> None:
        device.active = True
        device.surplus_since = None
        device.deficit_since = None
        device.last_on_at = now
        _LOGGER.debug("Wattix: switching %s ON", device.entity_id)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": device.entity_id}, blocking=True
        )

    async def _turn_off(self, device: Device) -> None:
        device.active = False
        device.surplus_since = None
        device.deficit_since = None
        _LOGGER.debug("Wattix: switching %s OFF", device.entity_id)
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": device.entity_id}, blocking=True
        )

    def device_seconds_remaining(self, device: Device) -> int | None:
        """Seconds left until this device's pending on/off action fires."""
        now = dt_util.utcnow()
        if device.surplus_since is not None:
            remaining = device.on_delay_s - (now - device.surplus_since).total_seconds()
            return max(int(remaining), 0)
        if device.deficit_since is not None:
            remaining = device.off_delay_s - (now - device.deficit_since).total_seconds()
            return max(int(remaining), 0)
        return None

    @property
    def active_device_count(self) -> int:
        return sum(1 for d in self.devices if d.active)

    def state_dict(self) -> dict[str, Any]:
        """Full serialized state, used by the websocket API and card."""
        return {
            "auto_mode": self.auto_mode,
            "surplus_w": self.current_power_w,
            "active_count": self.active_device_count,
            "devices": [
                d.to_dict(self.device_seconds_remaining(d)) for d in self.devices
            ],
        }
