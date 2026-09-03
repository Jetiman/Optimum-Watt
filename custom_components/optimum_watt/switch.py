"""The global automatic-mode switch for Optimum Watt."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import OptimumWattCoordinator
from .entity import OptimumWattEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: OptimumWattCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AutoModeSwitch(coordinator)])


class AutoModeSwitch(OptimumWattEntity, RestoreEntity, SwitchEntity):
    """Enable/disable the whole surplus cascade."""

    _attr_name = "Automatik"
    _attr_icon = "mdi:sun-wireless"

    def __init__(self, coordinator: OptimumWattCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_auto_mode"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self.coordinator.auto_mode = last_state.state == "on"

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.auto_mode = True
        self.async_write_ha_state()
        await self.coordinator.request_reeval()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.auto_mode = False
        self.async_write_ha_state()
