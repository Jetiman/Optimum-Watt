"""Shared base entity for Wattix."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattixCoordinator


class WattixEntity(CoordinatorEntity[WattixCoordinator]):
    """Base entity tying every platform entity to one config-entry device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WattixCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Wattix",
            model="Überschuss-Kaskadensteuerung",
        )
