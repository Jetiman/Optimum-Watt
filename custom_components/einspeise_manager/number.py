"""Tunable numbers (thresholds and delays) for Einspeise-Manager."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DELAY_MAX_MIN,
    DELAY_MIN_MIN,
    DELAY_STEP_MIN,
    DEFAULT_HYSTERESIS_W,
    DOMAIN,
    HYSTERESIS_MAX_W,
    HYSTERESIS_MIN_W,
    HYSTERESIS_STEP_W,
    THRESHOLD_MAX_W,
    THRESHOLD_MIN_W,
    THRESHOLD_STEP_W,
)
from .coordinator import EinspeiseManagerCoordinator, Stage
from .entity import EinspeiseManagerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EinspeiseManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = [
        StageThresholdNumber(coordinator, stage) for stage in coordinator.stages
    ]
    entities.append(HysteresisNumber(coordinator))
    entities.append(OnDelayNumber(coordinator))
    entities.append(OffDelayNumber(coordinator))
    async_add_entities(entities)


class _BaseNumber(EinspeiseManagerEntity, RestoreEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._restore(float(last_state.state))
            except ValueError:
                pass

    def _restore(self, value: float) -> None:
        raise NotImplementedError


class StageThresholdNumber(_BaseNumber):
    """Surplus power (W) that must be sustained to switch this stage on."""

    _attr_icon = "mdi:flash-alert"
    _attr_native_unit_of_measurement = "W"
    _attr_native_min_value = THRESHOLD_MIN_W
    _attr_native_max_value = THRESHOLD_MAX_W
    _attr_native_step = THRESHOLD_STEP_W

    def __init__(self, coordinator: EinspeiseManagerCoordinator, stage: Stage) -> None:
        super().__init__(coordinator)
        self._stage = stage
        self._attr_name = f"{stage.name} Einschaltschwelle"
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_stage_{stage.index}_threshold"
        )

    def _restore(self, value: float) -> None:
        self._stage.on_threshold_w = value

    @property
    def native_value(self) -> float:
        return self._stage.on_threshold_w

    async def async_set_native_value(self, value: float) -> None:
        self._stage.on_threshold_w = value
        self.async_write_ha_state()
        await self.coordinator.request_reeval()


class HysteresisNumber(_BaseNumber):
    """Gap between on- and off-threshold, applied to every stage."""

    _attr_icon = "mdi:swap-vertical"
    _attr_native_unit_of_measurement = "W"
    _attr_native_min_value = HYSTERESIS_MIN_W
    _attr_native_max_value = HYSTERESIS_MAX_W
    _attr_native_step = HYSTERESIS_STEP_W
    _attr_name = "Hysterese"

    def __init__(self, coordinator: EinspeiseManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_hysteresis"

    def _restore(self, value: float) -> None:
        for stage in self.coordinator.stages:
            stage.hysteresis_w = value

    @property
    def native_value(self) -> float:
        if not self.coordinator.stages:
            return DEFAULT_HYSTERESIS_W
        return self.coordinator.stages[0].hysteresis_w

    async def async_set_native_value(self, value: float) -> None:
        for stage in self.coordinator.stages:
            stage.hysteresis_w = value
        self.async_write_ha_state()
        await self.coordinator.request_reeval()


class OnDelayNumber(_BaseNumber):
    """How many minutes the surplus must hold before a stage switches on."""

    _attr_icon = "mdi:timer-plus-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = DELAY_MIN_MIN
    _attr_native_max_value = DELAY_MAX_MIN
    _attr_native_step = DELAY_STEP_MIN
    _attr_name = "Einschaltverzögerung"

    def __init__(self, coordinator: EinspeiseManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_on_delay"

    def _restore(self, value: float) -> None:
        self.coordinator.on_delay = timedelta(minutes=value)

    @property
    def native_value(self) -> float:
        return self.coordinator.on_delay.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.on_delay = timedelta(minutes=value)
        self.async_write_ha_state()
        await self.coordinator.request_reeval()


class OffDelayNumber(_BaseNumber):
    """How many minutes the deficit must hold before a stage switches off."""

    _attr_icon = "mdi:timer-minus-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = DELAY_MIN_MIN
    _attr_native_max_value = DELAY_MAX_MIN
    _attr_native_step = DELAY_STEP_MIN
    _attr_name = "Ausschaltverzögerung"

    def __init__(self, coordinator: EinspeiseManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_off_delay"

    def _restore(self, value: float) -> None:
        self.coordinator.off_delay = timedelta(minutes=value)

    @property
    def native_value(self) -> float:
        return self.coordinator.off_delay.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.off_delay = timedelta(minutes=value)
        self.async_write_ha_state()
        await self.coordinator.request_reeval()
