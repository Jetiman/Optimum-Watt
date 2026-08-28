"""Core cascade control logic for the Einspeise-Manager integration.

Mirrors how solarmanager.ch style controllers work: as long as enough
power is being fed into the grid for a sustained period, consumers are
switched on one after another (stage by stage). As soon as the surplus
drops away for a sustained period, the most recently activated consumer
is switched off again (LIFO), with hysteresis to avoid short-cycling the
relays.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    CONF_GRID_POWER_ENTITY,
    CONF_INVERT,
    CONF_STAGE_ENTITY,
    CONF_STAGE_NAME,
    CONF_STAGE_RATED_POWER,
    CONF_STAGES,
    DEFAULT_HYSTERESIS_W,
    DEFAULT_ON_DELAY_MIN,
    DEFAULT_OFF_DELAY_MIN,
    DEFAULT_ON_THRESHOLD_W,
    DOMAIN,
    MODE_AUTO,
    MODE_OFF,
    MODE_ON,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Stage:
    """Runtime state of a single controlled heater stage."""

    index: int
    name: str
    entity_id: str
    rated_power_w: int

    on_threshold_w: float = DEFAULT_ON_THRESHOLD_W
    hysteresis_w: float = DEFAULT_HYSTERESIS_W
    mode: str = MODE_AUTO

    active: bool = False
    surplus_since: datetime | None = None
    deficit_since: datetime | None = None
    last_on_at: datetime | None = None

    @property
    def off_threshold_w(self) -> float:
        return max(self.on_threshold_w - self.hysteresis_w, 0)

    def status_text(self) -> str:
        if self.mode == MODE_ON:
            return "manual_on"
        if self.mode == MODE_OFF:
            return "manual_off"
        return "auto_on" if self.active else "auto_off"


class EinspeiseManagerCoordinator(DataUpdateCoordinator[None]):
    """Coordinates surplus readings and drives the heater cascade."""

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

        self.on_delay = timedelta(minutes=DEFAULT_ON_DELAY_MIN)
        self.off_delay = timedelta(minutes=DEFAULT_OFF_DELAY_MIN)

        self.stages: list[Stage] = [
            Stage(
                index=i,
                name=stage.get(CONF_STAGE_NAME, f"Heizung {i + 1}"),
                entity_id=stage[CONF_STAGE_ENTITY],
                rated_power_w=stage.get(CONF_STAGE_RATED_POWER, 2000),
            )
            for i, stage in enumerate(entry.data.get(CONF_STAGES, []))
        ]

        self._remove_power_listener = None

    async def async_setup(self) -> None:
        """Start listening to the grid power sensor and read initial state."""
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
        """Public helper for entities to trigger an immediate re-evaluation."""
        await self.async_request_refresh()

    async def _evaluate(self) -> None:
        now = dt_util.utcnow()

        self._sync_active_from_states()

        for stage in self.stages:
            await self._sync_manual_mode(stage)

        if not self.auto_mode:
            return

        power = self.current_power_w
        if power is None:
            return

        # Turn ON: the lowest-index inactive stage that is in auto mode.
        candidate_on = next(
            (s for s in self.stages if s.mode == MODE_AUTO and not s.active), None
        )
        if candidate_on is not None:
            if power >= candidate_on.on_threshold_w:
                if candidate_on.surplus_since is None:
                    candidate_on.surplus_since = now
                elif now - candidate_on.surplus_since >= self.on_delay:
                    await self._turn_on(candidate_on, now)
            else:
                candidate_on.surplus_since = None

        # Turn OFF: the highest-index active stage that is in auto mode (LIFO).
        active_auto_stages = [
            s for s in self.stages if s.mode == MODE_AUTO and s.active
        ]
        if active_auto_stages:
            candidate_off = active_auto_stages[-1]
            if power < candidate_off.off_threshold_w:
                if candidate_off.deficit_since is None:
                    candidate_off.deficit_since = now
                elif now - candidate_off.deficit_since >= self.off_delay:
                    await self._turn_off(candidate_off)
            else:
                candidate_off.deficit_since = None

    def _sync_active_from_states(self) -> None:
        """Reconcile our tracked state with the real switch (restart, manual toggle)."""
        for stage in self.stages:
            live_state = self.hass.states.get(stage.entity_id)
            if live_state is not None and live_state.state in ("on", "off"):
                stage.active = live_state.state == "on"

    async def _sync_manual_mode(self, stage: Stage) -> None:
        """Force the relay to match a manual override, independent of surplus."""
        if stage.mode == MODE_ON and not stage.active:
            await self._turn_on(stage, dt_util.utcnow())
        elif stage.mode == MODE_OFF and stage.active:
            await self._turn_off(stage)

    async def _turn_on(self, stage: Stage, now: datetime) -> None:
        stage.active = True
        stage.surplus_since = None
        stage.deficit_since = None
        stage.last_on_at = now
        _LOGGER.debug("Einspeise-Manager: switching %s ON", stage.entity_id)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": stage.entity_id}, blocking=True
        )

    async def _turn_off(self, stage: Stage) -> None:
        stage.active = False
        stage.surplus_since = None
        stage.deficit_since = None
        _LOGGER.debug("Einspeise-Manager: switching %s OFF", stage.entity_id)
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": stage.entity_id}, blocking=True
        )

    def stage_seconds_remaining(self, stage: Stage) -> int | None:
        """Seconds left until this stage's pending on/off action fires."""
        now = dt_util.utcnow()
        if stage.surplus_since is not None:
            remaining = (stage.surplus_since + self.on_delay - now).total_seconds()
            return max(int(remaining), 0)
        if stage.deficit_since is not None:
            remaining = (stage.deficit_since + self.off_delay - now).total_seconds()
            return max(int(remaining), 0)
        return None

    @property
    def active_stage_count(self) -> int:
        return sum(1 for s in self.stages if s.active)
