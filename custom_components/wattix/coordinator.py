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
    CASCADE_STAGGER_S,
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    DEFAULT_HYSTERESIS_W,
    DEFAULT_ON_DELAY_S,
    DEFAULT_OFF_DELAY_S,
    DOMAIN,
    MODE_AUTO,
    MODE_DISABLED,
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

    # Daily minimum runtime guarantee ("Mindestlaufzeit"): if the device
    # hasn't accumulated min_runtime_s of runtime today by the deadline,
    # it gets forced on regardless of surplus so it still makes it.
    min_runtime_s: int = 0
    min_runtime_deadline: str | None = None  # local "HH:MM", e.g. "19:00"
    runtime_today_s: float = 0.0
    runtime_date: str | None = None  # ISO date the counter above applies to

    # Minimum runtime per activation ("Mindestlaufzeit pro Aktivierung"):
    # once switched on, the device stays on for at least this long even if
    # the surplus disappears again right away.
    min_on_duration_s: int = 0

    active: bool = False
    surplus_since: datetime | None = None
    deficit_since: datetime | None = None
    last_on_at: datetime | None = None
    catchup_active: bool = False  # forced on right now to meet min_runtime_s

    @property
    def on_threshold_w(self) -> float:
        return self.power_w

    @property
    def off_threshold_w(self) -> float:
        return max(self.power_w - self.hysteresis_w, 0)

    def status_text(self) -> str:
        if self.mode == MODE_DISABLED:
            return "disabled"
        if self.mode == MODE_ON:
            return "manual_on"
        if self.mode == MODE_OFF:
            return "manual_off"
        if self.catchup_active:
            return "catchup"
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
            "min_runtime_s": self.min_runtime_s,
            "min_runtime_deadline": self.min_runtime_deadline,
            "runtime_today_s": self.runtime_today_s,
            "runtime_date": self.runtime_date,
            "min_on_duration_s": self.min_on_duration_s,
        }

    def to_dict(self, remaining_seconds: int | None, runtime_today_s: float) -> dict[str, Any]:
        data = self.to_storage()
        data.update(
            {
                "active": self.active,
                "status": self.status_text(),
                "on_threshold_w": self.on_threshold_w,
                "off_threshold_w": self.off_threshold_w,
                "remaining_seconds": remaining_seconds,
                "runtime_today_s": runtime_today_s,
                "catchup_active": self.catchup_active,
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
            min_runtime_s=data.get("min_runtime_s", 0),
            min_runtime_deadline=data.get("min_runtime_deadline"),
            runtime_today_s=data.get("runtime_today_s", 0.0),
            runtime_date=data.get("runtime_date"),
            min_on_duration_s=data.get("min_on_duration_s", 0),
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
        self._last_cascade_on_at: datetime | None = None
        self._last_cascade_off_at: datetime | None = None

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
        """Schedule a cascade re-evaluation without blocking the caller on it.

        Evaluation can call out to real switch entities (network round trips
        to physical devices), which must never make a button in the UI feel
        like it hung. Callers that change device/auto-mode state should push
        a state update immediately (see `_notify_and_reeval`) and let this
        run after.
        """
        self.hass.async_create_task(self.async_request_refresh())

    def _notify_and_reeval(self) -> None:
        """Push current state to listeners now, then re-evaluate in the background."""
        self.async_update_listeners()
        self.hass.async_create_task(self.async_request_refresh())

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
        min_runtime_s: int | None = None,
        min_runtime_deadline: str | None = None,
        min_on_duration_s: int | None = None,
    ) -> Device:
        device = Device(
            id=uuid.uuid4().hex[:8],
            name=name,
            entity_id=entity_id,
            power_w=float(power_w),
            hysteresis_w=float(hysteresis_w) if hysteresis_w is not None else DEFAULT_HYSTERESIS_W,
            on_delay_s=int(on_delay_s) if on_delay_s is not None else DEFAULT_ON_DELAY_S,
            off_delay_s=int(off_delay_s) if off_delay_s is not None else DEFAULT_OFF_DELAY_S,
            min_runtime_s=int(min_runtime_s) if min_runtime_s else 0,
            min_runtime_deadline=min_runtime_deadline or None,
            min_on_duration_s=int(min_on_duration_s) if min_on_duration_s else 0,
        )
        self.devices.append(device)
        await self._async_save_devices()
        self._notify_and_reeval()
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
            "min_runtime_s",
            "min_runtime_deadline",
            "min_on_duration_s",
        ):
            if key in fields and fields[key] is not None:
                setattr(device, key, fields[key])
        if "mode" in fields and fields["mode"] is not None:
            # Avoid a stale timer instantly firing if the device returns to auto later.
            device.surplus_since = None
            device.deficit_since = None
        await self._async_save_devices()
        self._notify_and_reeval()
        return device

    async def async_remove_device(self, device_id: str) -> None:
        device = self._get_device(device_id)
        self.devices.remove(device)
        await self._async_save_devices()
        self._notify_and_reeval()

    async def async_reorder_devices(self, device_ids: list[str]) -> None:
        by_id = {d.id: d for d in self.devices}
        if set(device_ids) != set(by_id):
            raise ValueError("device_ids must match the existing device set")
        self.devices = [by_id[i] for i in device_ids]
        await self._async_save_devices()
        self._notify_and_reeval()

    def set_auto_mode(self, enabled: bool) -> None:
        self.auto_mode = enabled
        self._notify_and_reeval()

    # -- Cascade evaluation ------------------------------------------------

    async def _evaluate(self) -> None:
        now = dt_util.utcnow()
        now_local = dt_util.now()

        self._sync_active_from_states()

        for device in self.devices:
            await self._sync_manual_mode(device)

        if not self.auto_mode:
            return

        for device in self.devices:
            self._roll_over_runtime(device, now_local)
            await self._evaluate_min_runtime(device, now_local)

        power = self.current_power_w
        if power is None:
            return

        # Turn ON: every inactive device in auto mode, in priority (list)
        # order, that currently fits within the surplus together with the
        # higher-priority devices already reserved ahead of it - not just
        # the first one. A big-enough surplus lets several on-delay timers
        # run at once instead of fully serializing through each device's
        # on_delay_s one after another; the actual switch-on actions are
        # still spaced at least CASCADE_STAGGER_S apart below so they don't
        # all fire in the same instant. A device that no longer fits (or
        # is no longer first in line) has its timer cleared here too, which
        # also prevents the stale-timer bug where a device that once briefly
        # qualified kept counting down in the background and fired instantly
        # (stuck "0s") once it qualified again.
        reserved_w = 0.0
        for d in self.devices:
            if d.mode != MODE_AUTO or d.active:
                continue
            if power - reserved_w >= d.on_threshold_w:
                reserved_w += d.power_w
                if d.surplus_since is None:
                    d.surplus_since = now
                elif now - d.surplus_since >= timedelta(seconds=d.on_delay_s) and (
                    self._last_cascade_on_at is None
                    or (now - self._last_cascade_on_at).total_seconds() >= CASCADE_STAGGER_S
                ):
                    await self._turn_on(d, now)
                    self._last_cascade_on_at = now
            else:
                d.surplus_since = None

        # Turn OFF: active devices in reverse priority order (LIFO - the
        # lowest-priority, last-in-list device first), mirroring the ON
        # cascade above. Every active device whose own threshold is still
        # not covered by the surplus - even after hypothetically freeing up
        # the power of the lower-priority devices already queued to turn
        # off ahead of it - gets its own off-delay timer running
        # concurrently, instead of waiting for each device to actually
        # finish turning off before the next one's timer even starts. A
        # device that's forced on for its daily minimum runtime, hasn't yet
        # run its minimum time per activation, or no longer shows a deficit
        # has its timer cleared here too (same stale-timer fix as the ON
        # cascade).
        freed_w = 0.0
        for d in reversed(self.devices):
            if d.mode != MODE_AUTO or not d.active:
                continue
            if d.catchup_active or not self._min_on_duration_satisfied(d, now):
                d.deficit_since = None
                continue
            if power + freed_w < d.off_threshold_w:
                freed_w += d.power_w
                if d.deficit_since is None:
                    d.deficit_since = now
                elif now - d.deficit_since >= timedelta(seconds=d.off_delay_s) and (
                    self._last_cascade_off_at is None
                    or (now - self._last_cascade_off_at).total_seconds() >= CASCADE_STAGGER_S
                ):
                    await self._turn_off(d)
                    self._last_cascade_off_at = now
            else:
                d.deficit_since = None

    def _sync_active_from_states(self) -> None:
        """Reconcile our tracked state with the real switch (restart, manual toggle)."""
        now = dt_util.utcnow()
        for device in self.devices:
            live_state = self.hass.states.get(device.entity_id)
            if live_state is None or live_state.state not in ("on", "off"):
                continue
            was_active = device.active
            device.active = live_state.state == "on"
            if device.active and device.last_on_at is None:
                # Restored from a restart, or turned on outside our own _turn_on.
                device.last_on_at = now
            if was_active and not device.active:
                # Turned off externally (physical button, another automation) -
                # still credit the runtime it accumulated before we noticed.
                if device.last_on_at is not None:
                    device.runtime_today_s += max((now - device.last_on_at).total_seconds(), 0)
                device.last_on_at = None
                device.catchup_active = False

    async def _sync_manual_mode(self, device: Device) -> None:
        """Force the relay to match a manual override, independent of surplus."""
        if device.mode == MODE_ON and not device.active:
            await self._turn_on(device, dt_util.utcnow())
        elif device.mode == MODE_OFF and device.active:
            await self._turn_off(device)

    def _roll_over_runtime(self, device: Device, now_local: datetime) -> None:
        """Reset the daily runtime counter at the start of a new local day."""
        today_str = now_local.date().isoformat()
        if device.runtime_date != today_str:
            device.runtime_date = today_str
            device.runtime_today_s = 0.0
            if device.active:
                # Don't credit yesterday's running time to the new day.
                device.last_on_at = dt_util.utcnow()

    def _effective_runtime_today_s(self, device: Device) -> float:
        """Today's accumulated runtime, including the currently running session."""
        live_session = 0.0
        if device.active and device.last_on_at is not None:
            live_session = max((dt_util.utcnow() - device.last_on_at).total_seconds(), 0)
        return device.runtime_today_s + live_session

    @staticmethod
    def _min_on_duration_satisfied(device: Device, now: datetime) -> bool:
        """Whether the device has been on long enough to be allowed off again."""
        if device.min_on_duration_s <= 0 or device.last_on_at is None:
            return True
        return (now - device.last_on_at).total_seconds() >= device.min_on_duration_s

    @staticmethod
    def _deadline_today(deadline_str: str, now_local: datetime) -> datetime | None:
        try:
            hour_str, minute_str = deadline_str.split(":", 1)
            hour, minute = int(hour_str), int(minute_str)
        except (ValueError, AttributeError):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    async def _evaluate_min_runtime(self, device: Device, now_local: datetime) -> None:
        """Force a device on if it's running out of time to meet its daily minimum."""
        if device.mode != MODE_AUTO or device.min_runtime_s <= 0 or not device.min_runtime_deadline:
            device.catchup_active = False
            return

        deadline_dt = self._deadline_today(device.min_runtime_deadline, now_local)
        if deadline_dt is None or now_local >= deadline_dt:
            device.catchup_active = False
            return

        remaining_needed = device.min_runtime_s - self._effective_runtime_today_s(device)
        if remaining_needed <= 0:
            device.catchup_active = False
            return

        time_left = (deadline_dt - now_local).total_seconds()
        if time_left <= remaining_needed:
            device.catchup_active = True
            if not device.active:
                _LOGGER.debug(
                    "Wattix: forcing %s ON to meet daily minimum runtime before %s",
                    device.entity_id,
                    device.min_runtime_deadline,
                )
                await self._turn_on(device, dt_util.utcnow())
        else:
            device.catchup_active = False

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
        now = dt_util.utcnow()
        if device.last_on_at is not None:
            device.runtime_today_s += max((now - device.last_on_at).total_seconds(), 0)
        device.active = False
        device.last_on_at = None
        device.surplus_since = None
        device.deficit_since = None
        device.catchup_active = False
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
    def regulated_device_count(self) -> int:
        """How many devices are under active cascade control (mode auto).

        Deliberately not a count of devices currently drawing power: a
        device that is off because there isn't enough surplus right now is
        still being regulated, while a "Regelung aus" device never is.
        """
        return sum(1 for d in self.devices if d.mode == MODE_AUTO)

    def state_dict(self) -> dict[str, Any]:
        """Full serialized state, used by the websocket API and card."""
        return {
            "auto_mode": self.auto_mode,
            "surplus_w": self.current_power_w,
            "regulated_count": self.regulated_device_count,
            "devices": [
                d.to_dict(self.device_seconds_remaining(d), self._effective_runtime_today_s(d))
                for d in self.devices
            ],
        }
