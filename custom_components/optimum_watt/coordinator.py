"""Core cascade control logic for the Optimum Watt integration.

As long as enough power is being fed into the grid for a sustained period,
devices are switched on one after another in priority order (list order).
As soon as the surplus drops away for a sustained period, the most
recently activated device is switched off again (LIFO), with hysteresis
to avoid short-cycling the relays. Each device's own power requirement
doubles as the surplus threshold needed to switch it on.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.loader import async_get_integration
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    CASCADE_STAGGER_S,
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    CONF_PV_PRODUCTION_ENTITY,
    CONF_STORAGE_INVERT,
    CONF_STORAGE_POWER_ENTITY,
    CONF_STORAGE_SOC_ENTITY,
    DEFAULT_HYSTERESIS_W,
    DEFAULT_ON_DELAY_S,
    DEFAULT_OFF_DELAY_S,
    DEFAULT_MAX_GRID_CHARGE_W,
    DEFAULT_SENSOR_TIMEOUT_S,
    DEFAULT_THRESHOLD_BASIS,
    DOMAIN,
    MODE_AUTO,
    MODE_DISABLED,
    MODE_OFF,
    MODE_ON,
    RESET_GRACE_S,
    STORAGE_VERSION,
    THRESHOLD_BASIS_PRODUCTION,
    THRESHOLD_BASIS_SURPLUS_PRE_STORAGE,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _storage_key(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_devices"


def _compute_build_hash() -> str:
    """Short hash over this package's Python + card source.

    Lets a specific build be identified in the UI even when the manifest
    version string hasn't changed - e.g. between rolling beta pushes. Any
    code change to a .py or .js file flips it.
    """
    pkg = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(pkg.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".js"):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:7]


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

    # What the threshold below is measured against - see THRESHOLD_BASIS_*
    # in const.py. Defaults to "surplus" (grid feed-in), matching every
    # device created before this setting existed.
    threshold_basis: str = DEFAULT_THRESHOLD_BASIS

    # Extra gate on top of the threshold basis above: the device may only
    # switch ON while the battery is at least this charged. 0 = no gate.
    # Doesn't affect switching off - a running device isn't forced off by
    # the battery level dropping.
    min_soc_percent: float = 0.0

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

    # Extra entities shown read-only next to this device on the card - e.g.
    # a temperature or a live power sensor. Purely informational, never
    # part of the cascade logic.
    info_entities: list[str] = field(default_factory=list)

    active: bool = False
    surplus_since: datetime | None = None
    deficit_since: datetime | None = None
    last_on_at: datetime | None = None
    catchup_active: bool = False  # forced on right now to meet min_runtime_s
    # Last switch.turn_on/off service call for this device failed (switch
    # entity unavailable or missing). Purely informational for the card.
    switch_unreachable: bool = False

    # How long a running on/off timer has currently seen the *opposite*
    # condition (e.g. a battery/storage regulation blip briefly pushing the
    # surplus reading the wrong way). Only once this persists for
    # RESET_GRACE_S does the timer above actually get cleared - a single
    # bad reading can no longer wipe out an almost-complete delay.
    insufficient_since: datetime | None = None
    recovered_since: datetime | None = None
    # Whether the raw surplus/deficit condition is met on the *current*
    # tick - independent of whether a grace-protected timer above is still
    # running. Used to keep the countdown shown to the user (and its
    # "pending" styling) honest: a timer surviving a brief blip shouldn't
    # be displayed as "switches in 0s" while the device very much isn't
    # about to switch, because right now it doesn't qualify at all.
    surplus_met: bool = False
    deficit_met: bool = False

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
            "threshold_basis": self.threshold_basis,
            "min_soc_percent": self.min_soc_percent,
            "min_runtime_s": self.min_runtime_s,
            "min_runtime_deadline": self.min_runtime_deadline,
            "runtime_today_s": self.runtime_today_s,
            "runtime_date": self.runtime_date,
            "min_on_duration_s": self.min_on_duration_s,
            "info_entities": list(self.info_entities),
        }

    def to_dict(
        self,
        remaining_seconds: int | None,
        runtime_today_s: float,
        info_readings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
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
                "switch_unreachable": self.switch_unreachable,
                "info_readings": info_readings or [],
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
            threshold_basis=data.get("threshold_basis", DEFAULT_THRESHOLD_BASIS),
            min_soc_percent=data.get("min_soc_percent", 0.0),
            min_runtime_s=data.get("min_runtime_s", 0),
            min_runtime_deadline=data.get("min_runtime_deadline"),
            runtime_today_s=data.get("runtime_today_s", 0.0),
            runtime_date=data.get("runtime_date"),
            min_on_duration_s=data.get("min_on_duration_s", 0),
            info_entities=[str(e) for e in data.get("info_entities", []) if e],
        )


class OptimumWattCoordinator(DataUpdateCoordinator[None]):
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
        # Optional: raw PV production and battery power, so devices can key
        # their threshold off something other than grid feed-in.
        self.pv_production_entity: str | None = entry.data.get(CONF_PV_PRODUCTION_ENTITY)
        self.storage_power_entity: str | None = entry.data.get(CONF_STORAGE_POWER_ENTITY)
        self.storage_invert: bool = entry.data.get(CONF_STORAGE_INVERT, False)
        self.storage_soc_entity: str | None = entry.data.get(CONF_STORAGE_SOC_ENTITY)

        self.auto_mode: bool = True
        self.version: str = ""  # integration version, filled in async_setup
        self.build: str = ""  # short source hash, filled in async_setup
        self.current_power_w: float | None = None
        # Raw PV production (W) and battery power, normalized so positive =
        # charging / negative = discharging. None while unconfigured.
        self.production_w: float | None = None
        self.storage_w: float | None = None
        # Battery state of charge (%). None while unconfigured.
        self.storage_soc: float | None = None
        self.devices: list[Device] = []
        self._last_cascade_on_at: datetime | None = None
        self._last_cascade_off_at: datetime | None = None

        # Instance-level safety setting: shut every switch down (staggered)
        # if any configured power sensor stops reporting a fresh value. 0 = off.
        self.sensor_timeout_s: int = DEFAULT_SENSOR_TIMEOUT_S
        # See DEFAULT_MAX_GRID_CHARGE_W. Guards the "surplus before storage"
        # basis against counting grid-sourced battery charging as surplus.
        self.max_grid_charge_w: int = DEFAULT_MAX_GRID_CHARGE_W
        self._power_last_seen: datetime | None = None
        self._production_last_seen: datetime | None = None
        self._storage_last_seen: datetime | None = None
        self._storage_soc_last_seen: datetime | None = None

        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, _storage_key(entry.entry_id))
        self._remove_power_listener = None
        self._remove_production_listener = None
        self._remove_storage_listener = None
        self._remove_storage_soc_listener = None

    async def async_setup(self) -> None:
        """Load persisted devices/settings and start listening to the grid power sensor."""
        try:
            self.version = str((await async_get_integration(self.hass, DOMAIN)).version or "")
        except Exception:  # noqa: BLE001 - version is cosmetic, never fatal
            self.version = ""
        self.build = await self.hass.async_add_executor_job(_compute_build_hash)

        stored = await self._store.async_load() or {}
        self.devices = [Device.from_storage(d) for d in stored.get("devices", [])]
        settings = stored.get("settings", {})
        self.sensor_timeout_s = settings.get("sensor_timeout_s", DEFAULT_SENSOR_TIMEOUT_S)
        self.max_grid_charge_w = settings.get("max_grid_charge_w", DEFAULT_MAX_GRID_CHARGE_W)

        # Start the staleness clock at startup, even if the sensor's first
        # reading turns out invalid - a sensor that's broken from the start
        # must still eventually trip the timeout instead of never starting.
        self._power_last_seen = dt_util.utcnow()
        self._update_power_from_state(self.hass.states.get(self.grid_power_entity))

        @callback
        def _power_changed(event) -> None:
            self._update_power_from_state(event.data.get("new_state"))
            self.hass.async_create_task(self.async_request_refresh())

        self._remove_power_listener = async_track_state_change_event(
            self.hass, [self.grid_power_entity], _power_changed
        )

        if self.pv_production_entity:
            self._production_last_seen = dt_util.utcnow()
            self._update_production_from_state(self.hass.states.get(self.pv_production_entity))

            @callback
            def _production_changed(event) -> None:
                self._update_production_from_state(event.data.get("new_state"))
                self.hass.async_create_task(self.async_request_refresh())

            self._remove_production_listener = async_track_state_change_event(
                self.hass, [self.pv_production_entity], _production_changed
            )

        if self.storage_power_entity:
            self._storage_last_seen = dt_util.utcnow()
            self._update_storage_from_state(self.hass.states.get(self.storage_power_entity))

            @callback
            def _storage_changed(event) -> None:
                self._update_storage_from_state(event.data.get("new_state"))
                self.hass.async_create_task(self.async_request_refresh())

            self._remove_storage_listener = async_track_state_change_event(
                self.hass, [self.storage_power_entity], _storage_changed
            )

        if self.storage_soc_entity:
            self._storage_soc_last_seen = dt_util.utcnow()
            self._update_storage_soc_from_state(self.hass.states.get(self.storage_soc_entity))

            @callback
            def _storage_soc_changed(event) -> None:
                self._update_storage_soc_from_state(event.data.get("new_state"))
                self.hass.async_create_task(self.async_request_refresh())

            self._remove_storage_soc_listener = async_track_state_change_event(
                self.hass, [self.storage_soc_entity], _storage_soc_changed
            )

    @callback
    def async_unload(self) -> None:
        if self._remove_power_listener:
            self._remove_power_listener()
            self._remove_power_listener = None
        if self._remove_production_listener:
            self._remove_production_listener()
            self._remove_production_listener = None
        if self._remove_storage_listener:
            self._remove_storage_listener()
            self._remove_storage_listener = None
        if self._remove_storage_soc_listener:
            self._remove_storage_soc_listener()
            self._remove_storage_soc_listener = None

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
        self._power_last_seen = dt_util.utcnow()

    @callback
    def _update_production_from_state(self, state: State | None) -> None:
        if state is None or state.state in ("unknown", "unavailable", ""):
            self.production_w = None
            return
        try:
            self.production_w = float(state.state)
        except (ValueError, TypeError):
            self.production_w = None
            return
        self._production_last_seen = dt_util.utcnow()

    @callback
    def _update_storage_from_state(self, state: State | None) -> None:
        """Normalize so positive = charging, negative = discharging."""
        if state is None or state.state in ("unknown", "unavailable", ""):
            self.storage_w = None
            return
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            self.storage_w = None
            return
        self.storage_w = -value if self.storage_invert else value
        self._storage_last_seen = dt_util.utcnow()

    @callback
    def _update_storage_soc_from_state(self, state: State | None) -> None:
        if state is None or state.state in ("unknown", "unavailable", ""):
            self.storage_soc = None
            return
        try:
            self.storage_soc = float(state.state)
        except (ValueError, TypeError):
            self.storage_soc = None
            return
        self._storage_soc_last_seen = dt_util.utcnow()

    @property
    def surplus_pre_storage_w(self) -> float | None:
        """Production minus house consumption, before battery charging is deducted.

        Equal to grid feed-in plus whatever is currently charging into the
        battery (or minus whatever it's discharging) - see THRESHOLD_BASIS_
        SURPLUS_PRE_STORAGE in const.py.
        """
        if self.current_power_w is None or self.storage_w is None:
            return None
        return self.current_power_w + self.storage_w

    @property
    def grid_charge_w(self) -> float:
        """How many watts of the battery's charging come from the grid.

        When the battery charges (storage_w > 0) *and* the grid is
        importing (current_power_w < 0), that overlap is grid power going
        into the battery - not surplus.
        """
        if self.current_power_w is None or self.storage_w is None:
            return 0.0
        charging = max(self.storage_w, 0.0)
        importing = max(-self.current_power_w, 0.0)
        return min(charging, importing)

    @property
    def pre_storage_grid_blocked(self) -> bool:
        """Whether the 'surplus before storage' basis is currently paused
        because the battery is charging from the grid."""
        return self.max_grid_charge_w > 0 and self.grid_charge_w > self.max_grid_charge_w

    def _basis_value(self, basis: str) -> float | None:
        if basis == THRESHOLD_BASIS_PRODUCTION:
            return self.production_w
        if basis == THRESHOLD_BASIS_SURPLUS_PRE_STORAGE:
            value = self.surplus_pre_storage_w
            if value is None:
                return None
            if self.pre_storage_grid_blocked:
                # Battery is grid-charging: its charge power isn't surplus,
                # so devices on this basis must switch off, not stay on.
                return -1_000_000.0
            return value
        return self.current_power_w

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

    async def _async_save_state(self) -> None:
        await self._store.async_save(
            {
                "devices": [d.to_storage() for d in self.devices],
                "settings": {
                    "sensor_timeout_s": self.sensor_timeout_s,
                    "max_grid_charge_w": self.max_grid_charge_w,
                },
            }
        )

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
        threshold_basis: str | None = None,
        min_soc_percent: float | None = None,
        min_runtime_s: int | None = None,
        min_runtime_deadline: str | None = None,
        min_on_duration_s: int | None = None,
        info_entities: list[str] | None = None,
    ) -> Device:
        device = Device(
            id=uuid.uuid4().hex[:8],
            name=name,
            entity_id=entity_id,
            power_w=float(power_w),
            hysteresis_w=float(hysteresis_w) if hysteresis_w is not None else DEFAULT_HYSTERESIS_W,
            on_delay_s=int(on_delay_s) if on_delay_s is not None else DEFAULT_ON_DELAY_S,
            off_delay_s=int(off_delay_s) if off_delay_s is not None else DEFAULT_OFF_DELAY_S,
            threshold_basis=threshold_basis or DEFAULT_THRESHOLD_BASIS,
            min_soc_percent=float(min_soc_percent) if min_soc_percent else 0.0,
            min_runtime_s=int(min_runtime_s) if min_runtime_s else 0,
            min_runtime_deadline=min_runtime_deadline or None,
            min_on_duration_s=int(min_on_duration_s) if min_on_duration_s else 0,
            info_entities=[str(e) for e in (info_entities or []) if e],
        )
        self.devices.append(device)
        await self._async_save_state()
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
            "threshold_basis",
            "min_soc_percent",
            "min_runtime_s",
            "min_runtime_deadline",
            "min_on_duration_s",
        ):
            if key in fields and fields[key] is not None:
                setattr(device, key, fields[key])
        if "info_entities" in fields and fields["info_entities"] is not None:
            device.info_entities = [str(e) for e in fields["info_entities"] if e]
        if "mode" in fields and fields["mode"] is not None:
            # Avoid a stale timer instantly firing if the device returns to auto later.
            device.surplus_since = None
            device.deficit_since = None
            device.insufficient_since = None
            device.recovered_since = None
        await self._async_save_state()
        self._notify_and_reeval()
        return device

    async def async_remove_device(self, device_id: str) -> None:
        device = self._get_device(device_id)
        self.devices.remove(device)
        await self._async_save_state()
        self._notify_and_reeval()

    async def async_reorder_devices(self, device_ids: list[str]) -> None:
        by_id = {d.id: d for d in self.devices}
        if set(device_ids) != set(by_id):
            raise ValueError("device_ids must match the existing device set")
        self.devices = [by_id[i] for i in device_ids]
        await self._async_save_state()
        self._notify_and_reeval()

    def set_auto_mode(self, enabled: bool) -> None:
        self.auto_mode = enabled
        self._notify_and_reeval()

    async def async_set_settings(
        self,
        *,
        sensor_timeout_s: int | None = None,
        max_grid_charge_w: int | None = None,
    ) -> None:
        if sensor_timeout_s is not None:
            self.sensor_timeout_s = max(int(sensor_timeout_s), 0)
        if max_grid_charge_w is not None:
            self.max_grid_charge_w = max(int(max_grid_charge_w), 0)
        await self._async_save_state()
        self._notify_and_reeval()

    # -- Cascade evaluation ------------------------------------------------

    def _entity_is_fresh(self, entity_id: str, last_seen: datetime | None, now: datetime) -> bool:
        """Whether one entity counts as reporting fresh data right now.

        A sensor's value can legitimately sit unchanged for a long time
        (e.g. PV production is exactly 0 W all night) - Home Assistant then
        never fires a new state_changed event for it (identical value+
        attributes are suppressed), so relying only on "time since last
        event" would flag it stale even though it's perfectly alive and
        still being polled. Checking its current state directly sidesteps
        that: as long as it currently holds a valid, parseable value, it's
        fresh, full stop. Only once it actually goes unavailable/unknown
        does the timeout-based "how long since we last saw a good value"
        grace period (tracked via `last_seen`) kick in.
        """
        state = self.hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable", ""):
            try:
                float(state.state)
                return True
            except (ValueError, TypeError):
                pass
        return last_seen is not None and (now - last_seen).total_seconds() < self.sensor_timeout_s

    def _is_sensor_stale(self, now: datetime) -> bool:
        """Whether any configured power sensor has gone stale.

        Covers the grid sensor plus, if set up, the PV production and
        battery sensors - a device relying on either of those for its
        threshold is just as blind to a dead one as the cascade normally
        is to a dead grid sensor.
        """
        if self.sensor_timeout_s <= 0:
            return False
        checks = [(self.grid_power_entity, self._power_last_seen)]
        if self.pv_production_entity:
            checks.append((self.pv_production_entity, self._production_last_seen))
        if self.storage_power_entity:
            checks.append((self.storage_power_entity, self._storage_last_seen))
        if self.storage_soc_entity:
            checks.append((self.storage_soc_entity, self._storage_soc_last_seen))
        return not all(self._entity_is_fresh(entity_id, last_seen, now) for entity_id, last_seen in checks)

    async def _run_stale_sensor_shutdown(self, now: datetime) -> None:
        """Safety fallback for a stuck/dead grid power sensor.

        We can no longer trust it to drive the cascade, so every switch
        (except ones set to "Regelung aus") gets shut down regardless of
        mode, one every CASCADE_STAGGER_S so they don't all drop at once.
        """
        candidates = [d for d in reversed(self.devices) if d.mode != MODE_DISABLED and d.active]
        if not candidates:
            return
        if (
            self._last_cascade_off_at is not None
            and (now - self._last_cascade_off_at).total_seconds() < CASCADE_STAGGER_S
        ):
            return
        _LOGGER.warning(
            "Optimum Watt: a configured power sensor is stale for %ss, switching %s off as a safety fallback",
            self.sensor_timeout_s,
            candidates[0].entity_id,
        )
        await self._turn_off(candidates[0])
        self._last_cascade_off_at = now

    async def _evaluate(self) -> None:
        now = dt_util.utcnow()
        now_local = dt_util.now()

        self._sync_active_from_states()

        if self._is_sensor_stale(now):
            await self._run_stale_sensor_shutdown(now)
            return

        for device in self.devices:
            await self._sync_manual_mode(device)

        if not self.auto_mode:
            return

        for device in self.devices:
            self._roll_over_runtime(device, now_local)
            await self._evaluate_min_runtime(device, now_local)

        # Turn ON: every inactive device in auto mode, in priority (list)
        # order, that currently fits within its own threshold basis
        # together with the higher-priority devices already reserved ahead
        # of it - not just the first one. A big-enough surplus lets several
        # on-delay timers run at once instead of fully serializing through
        # each device's on_delay_s one after another; the actual switch-on
        # actions are still spaced at least CASCADE_STAGGER_S apart below so
        # they don't all fire in the same instant. A device that no longer
        # fits (or is no longer first in line) has its timer cleared here
        # too, which also prevents the stale-timer bug where a device that
        # once briefly qualified kept counting down in the background and
        # fired instantly (stuck "0s") once it qualified again. A running
        # timer survives a brief dip below threshold via
        # _debounced_still_qualifies (see there) so a single noisy reading
        # can't wipe out an almost-complete wait.
        #
        # `reserved_w` tracks real wattage already committed to
        # higher-priority devices, regardless of *their* threshold basis -
        # once one of them switches on it draws real power, which reduces
        # what's left over for anyone below it that measures against a
        # shared pool (surplus / surplus_pre_storage). A device measured
        # against raw PV production isn't reduced by it though: production
        # doesn't care how much the house is drawing.
        reserved_w = 0.0
        for d in self.devices:
            if d.mode != MODE_AUTO or d.active:
                continue
            basis_value = self._basis_value(d.threshold_basis)
            if basis_value is None:
                continue
            available = (
                basis_value
                if d.threshold_basis == THRESHOLD_BASIS_PRODUCTION
                else basis_value - reserved_w
            )
            met = available >= d.on_threshold_w
            if met and d.min_soc_percent > 0:
                # Extra gate: normally won't switch on until the battery
                # itself is charged enough - but only actually applies while
                # this device would be competing with the battery for power
                # (i.e. it only qualifies via the surplus_pre_storage boost).
                # If the grid is already exporting enough on its own (e.g.
                # production exceeds the battery's max charge rate, so some
                # is spilling to the grid regardless of SoC), the device
                # isn't taking anything away from charging and the gate is
                # waived. Fails closed - no SoC reading, no switch-on.
                grid_alone = self.current_power_w
                grid_covers_it = grid_alone is not None and grid_alone - reserved_w >= d.on_threshold_w
                if not grid_covers_it:
                    met = self.storage_soc is not None and self.storage_soc >= d.min_soc_percent
            d.surplus_met = met
            qualifies, d.insufficient_since = self._debounced_still_qualifies(
                now, met, d.surplus_since, d.insufficient_since
            )
            if not qualifies:
                d.surplus_since = None
                continue
            reserved_w += d.power_w
            if d.surplus_since is None:
                d.surplus_since = now
            elif met and now - d.surplus_since >= timedelta(seconds=d.on_delay_s) and (
                self._last_cascade_on_at is None
                or (now - self._last_cascade_on_at).total_seconds() >= CASCADE_STAGGER_S
            ):
                await self._turn_on(d, now)
                self._last_cascade_on_at = now

        # Turn OFF: active devices in reverse priority order (LIFO - the
        # lowest-priority, last-in-list device first), mirroring the ON
        # cascade above. Every active device whose own threshold is still
        # not covered by the surplus - even after hypothetically freeing up
        # the power of the lower-priority devices already queued to turn
        # off ahead of it - gets its own off-delay timer running
        # concurrently, instead of waiting for each device to actually
        # finish turning off before the next one's timer even starts. A
        # device that's forced on for its daily minimum runtime, or hasn't
        # yet run its minimum time per activation, has its timer cleared
        # here too. A running timer survives a brief spike back above
        # threshold the same way the ON cascade does - e.g. a battery or
        # storage system regulating and briefly overshooting into positive
        # surplus shouldn't cancel an almost-complete off-delay wait.
        freed_w = 0.0
        for d in reversed(self.devices):
            if d.mode != MODE_AUTO or not d.active:
                continue
            if d.catchup_active or not self._min_on_duration_satisfied(d, now):
                d.deficit_since = None
                d.recovered_since = None
                d.deficit_met = False
                continue
            basis_value = self._basis_value(d.threshold_basis)
            if basis_value is None:
                continue
            available = (
                basis_value
                if d.threshold_basis == THRESHOLD_BASIS_PRODUCTION
                else basis_value + freed_w
            )
            met = available < d.off_threshold_w
            d.deficit_met = met
            qualifies, d.recovered_since = self._debounced_still_qualifies(
                now, met, d.deficit_since, d.recovered_since
            )
            if not qualifies:
                d.deficit_since = None
                continue
            freed_w += d.power_w
            if d.deficit_since is None:
                d.deficit_since = now
            elif met and now - d.deficit_since >= timedelta(seconds=d.off_delay_s) and (
                self._last_cascade_off_at is None
                or (now - self._last_cascade_off_at).total_seconds() >= CASCADE_STAGGER_S
            ):
                await self._turn_off(d)
                self._last_cascade_off_at = now

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
    def _debounced_still_qualifies(
        now: datetime, met: bool, timer_since: datetime | None, break_since: datetime | None
    ) -> tuple[bool, datetime | None]:
        """Whether a device with a running on/off-delay timer still qualifies.

        A running timer (`timer_since` set) survives a brief interruption of
        `met` - e.g. a battery/storage regulation blip briefly pushing the
        surplus reading the wrong way - instead of being wiped by a single
        bad reading. Only once the interruption has lasted at least
        RESET_GRACE_S does it count as a real, sustained change and the
        timer actually gets cleared. Returns (still_qualifies, updated
        break_since) - the caller is expected to store break_since back
        onto the device.
        """
        if met:
            return True, None
        if timer_since is None:
            return False, None
        if break_since is None:
            break_since = now
        if (now - break_since).total_seconds() >= RESET_GRACE_S:
            return False, None
        return True, break_since

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
                    "Optimum Watt: forcing %s ON to meet daily minimum runtime before %s",
                    device.entity_id,
                    device.min_runtime_deadline,
                )
                await self._turn_on(device, dt_util.utcnow())
        else:
            device.catchup_active = False

    async def _call_switch(self, device: Device, action: str) -> bool:
        """Call switch.turn_on / switch.turn_off for a device.

        Returns False (and logs a warning) if the service call fails - e.g.
        the switch entity is unavailable or missing. The caller must not
        update its internal state in that case, and crucially the failure
        must not bubble up: otherwise a single dead relay aborts the whole
        cascade evaluation every tick and every other device freezes with a
        stale status (stuck "switches in 0s") until the relay comes back.
        """
        _LOGGER.debug("Optimum Watt: switch.%s %s", action, device.entity_id)
        try:
            await self.hass.services.async_call(
                "switch", action, {"entity_id": device.entity_id}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - HA raises many types here
            _LOGGER.warning(
                "Optimum Watt: could not switch.%s %s: %s",
                action,
                device.entity_id,
                err,
            )
            device.switch_unreachable = True
            return False
        device.switch_unreachable = False
        return True

    async def _turn_on(self, device: Device, now: datetime) -> None:
        if not await self._call_switch(device, "turn_on"):
            return
        device.active = True
        device.surplus_since = None
        device.deficit_since = None
        device.insufficient_since = None
        device.recovered_since = None
        device.last_on_at = now

    async def _turn_off(self, device: Device) -> None:
        if not await self._call_switch(device, "turn_off"):
            return
        now = dt_util.utcnow()
        if device.last_on_at is not None:
            device.runtime_today_s += max((now - device.last_on_at).total_seconds(), 0)
        device.active = False
        device.last_on_at = None
        device.surplus_since = None
        device.deficit_since = None
        device.insufficient_since = None
        device.recovered_since = None
        device.catchup_active = False

    def device_seconds_remaining(self, device: Device) -> int | None:
        """Seconds left until this device's pending on/off action fires.

        Only shown while the underlying condition is actually met right
        now - a timer kept alive through a brief reading blip (see
        _debounced_still_qualifies) isn't about to fire, so it shouldn't
        display a misleading "switches in 0s" countdown while power very
        much doesn't support it.
        """
        now = dt_util.utcnow()
        if device.surplus_since is not None and device.surplus_met:
            remaining = device.on_delay_s - (now - device.surplus_since).total_seconds()
            return max(int(remaining), 0)
        if device.deficit_since is not None and device.deficit_met:
            remaining = device.off_delay_s - (now - device.deficit_since).total_seconds()
            return max(int(remaining), 0)
        return None

    def _info_readings(self, device: Device) -> list[dict[str, Any]]:
        """Resolve a device's info entities to current display values."""
        readings: list[dict[str, Any]] = []
        for entity_id in device.info_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                readings.append(
                    {"entity_id": entity_id, "name": entity_id, "state": None, "unit": None}
                )
                continue
            readings.append(
                {
                    "entity_id": entity_id,
                    "name": state.attributes.get("friendly_name") or entity_id,
                    "state": state.state,
                    "unit": state.attributes.get("unit_of_measurement"),
                }
            )
        return readings

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
            "version": self.version,
            "build": self.build,
            "surplus_w": self.current_power_w,
            "production_w": self.production_w,
            "storage_w": self.storage_w,
            "surplus_pre_storage_w": self.surplus_pre_storage_w,
            "storage_soc": self.storage_soc,
            "has_pv_production_entity": bool(self.pv_production_entity),
            "has_storage_entity": bool(self.storage_power_entity),
            "has_storage_soc_entity": bool(self.storage_soc_entity),
            "regulated_count": self.regulated_device_count,
            "sensor_timeout_s": self.sensor_timeout_s,
            "sensor_stale": self._is_sensor_stale(dt_util.utcnow()),
            "max_grid_charge_w": self.max_grid_charge_w,
            "grid_charge_w": self.grid_charge_w,
            "pre_storage_grid_blocked": self.pre_storage_grid_blocked,
            "devices": [
                d.to_dict(
                    self.device_seconds_remaining(d),
                    self._effective_runtime_today_s(d),
                    self._info_readings(d),
                )
                for d in self.devices
            ],
        }
