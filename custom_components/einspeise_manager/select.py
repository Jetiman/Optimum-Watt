"""Per-stage mode select (Automatik / An / Aus) for Einspeise-Manager."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, STAGE_MODES
from .coordinator import EinspeiseManagerCoordinator, Stage
from .entity import EinspeiseManagerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EinspeiseManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        StageModeSelect(coordinator, stage) for stage in coordinator.stages
    )


class StageModeSelect(EinspeiseManagerEntity, RestoreEntity, SelectEntity):
    """Lets the user force a stage on/off or leave it on automatic control."""

    _attr_icon = "mdi:tune-variant"
    _attr_options = STAGE_MODES

    def __init__(self, coordinator: EinspeiseManagerCoordinator, stage: Stage) -> None:
        super().__init__(coordinator)
        self._stage = stage
        self._attr_name = f"{stage.name} Modus"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_stage_{stage.index}_mode"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in STAGE_MODES:
            self._stage.mode = last_state.state

    @property
    def current_option(self) -> str:
        return self._stage.mode

    async def async_select_option(self, option: str) -> None:
        self._stage.mode = option
        self.async_write_ha_state()
        await self.coordinator.request_reeval()
