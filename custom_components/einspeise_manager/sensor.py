"""Status sensors for Einspeise-Manager."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EinspeiseManagerCoordinator, Stage
from .entity import EinspeiseManagerEntity

STATUS_LABELS = {
    "manual_on": "Manuell an",
    "manual_off": "Manuell aus",
    "auto_on": "An (Automatik)",
    "auto_off": "Aus (Automatik)",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EinspeiseManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        SurplusSensor(coordinator),
        ActiveStageCountSensor(coordinator),
    ]
    entities.extend(StageStatusSensor(coordinator, stage) for stage in coordinator.stages)
    async_add_entities(entities)


class SurplusSensor(EinspeiseManagerEntity, SensorEntity):
    """Current grid feed-in surplus, normalized to positive = feed-in."""

    _attr_name = "Überschuss"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: EinspeiseManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_surplus"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.current_power_w


class ActiveStageCountSensor(EinspeiseManagerEntity, SensorEntity):
    """How many heater stages are currently switched on."""

    _attr_name = "Aktive Stufen"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EinspeiseManagerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_active_stages"

    @property
    def native_value(self) -> int:
        return self.coordinator.active_stage_count

    @property
    def extra_state_attributes(self) -> dict:
        return {"stufen_gesamt": len(self.coordinator.stages)}


class StageStatusSensor(EinspeiseManagerEntity, SensorEntity):
    """Human-readable state of a single heater stage."""

    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: EinspeiseManagerCoordinator, stage: Stage) -> None:
        super().__init__(coordinator)
        self._stage = stage
        self._attr_name = f"{stage.name} Status"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_stage_{stage.index}_status"

    @property
    def native_value(self) -> str:
        return STATUS_LABELS[self._stage.status_text()]

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "entity_id": self._stage.entity_id,
            "leistung_w": self._stage.rated_power_w,
            "einschaltschwelle_w": self._stage.on_threshold_w,
            "ausschaltschwelle_w": self._stage.off_threshold_w,
            "aktiv": self._stage.active,
            "modus": self._stage.mode,
            "verbleibende_sekunden": self.coordinator.stage_seconds_remaining(
                self._stage
            ),
        }
