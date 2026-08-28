"""Aggregate status sensors for Wattix.

Per-device state is not exposed as individual entities — it lives in the
coordinator and is served to the dashboard card via the websocket API.
These two sensors give a stable, dashboard/automation-friendly summary.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WattixCoordinator
from .entity import WattixEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WattixCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SurplusSensor(coordinator), ActiveDeviceCountSensor(coordinator)])


class SurplusSensor(WattixEntity, SensorEntity):
    """Current grid feed-in surplus, normalized to positive = feed-in."""

    _attr_name = "Überschuss"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: WattixCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_surplus"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.current_power_w


class ActiveDeviceCountSensor(WattixEntity, SensorEntity):
    """How many devices are currently switched on."""

    _attr_name = "Aktive Geräte"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: WattixCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_active_devices"

    @property
    def native_value(self) -> int:
        return self.coordinator.active_device_count

    @property
    def extra_state_attributes(self) -> dict:
        return {"geraete_gesamt": len(self.coordinator.devices)}
