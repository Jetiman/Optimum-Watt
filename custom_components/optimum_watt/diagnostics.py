"""Diagnostics for Optimum Watt.

Settings → Geräte & Dienste → Optimum Watt → ⋯ → Diagnose herunterladen.
Shows the coordinator's internal timer state per device - useful when the
cascade looks stuck.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    now = dt_util.utcnow()

    def age(ts: datetime | None) -> float | None:
        return None if ts is None else round((now - ts).total_seconds(), 1)

    return {
        "version": coordinator.version,
        "build": coordinator.build,
        "auto_mode": coordinator.auto_mode,
        "last_update_success": coordinator.last_update_success,
        "last_evaluate_age_s": age(coordinator._last_evaluate_at),  # noqa: SLF001
        "power": {
            "current_power_w": coordinator.current_power_w,
            "production_w": coordinator.production_w,
            "storage_w": coordinator.storage_w,
            "storage_soc": coordinator.storage_soc,
            "surplus_pre_storage_w": coordinator.surplus_pre_storage_w,
            "grid_charge_w": coordinator.grid_charge_w,
            "pre_storage_grid_blocked": coordinator.pre_storage_grid_blocked,
        },
        "settings": {
            "sensor_timeout_s": coordinator.sensor_timeout_s,
            "max_grid_charge_w": coordinator.max_grid_charge_w,
            "sensor_stale": coordinator._is_sensor_stale(now),  # noqa: SLF001
        },
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "entity_id": d.entity_id,
                "entity_state": getattr(hass.states.get(d.entity_id), "state", None),
                "mode": d.mode,
                "mode_effective": d.mode_effective,
                "schedule_active": d.schedule_active,
                "active": d.active,
                "status": d.status_text(),
                "power_w": d.power_w,
                "threshold_basis": d.threshold_basis,
                "on_delay_s": d.on_delay_s,
                "off_delay_s": d.off_delay_s,
                "surplus_since_age_s": age(d.surplus_since),
                "deficit_since_age_s": age(d.deficit_since),
                "insufficient_since_age_s": age(d.insufficient_since),
                "recovered_since_age_s": age(d.recovered_since),
                "last_on_at_age_s": age(d.last_on_at),
                "surplus_met": d.surplus_met,
                "deficit_met": d.deficit_met,
                "catchup_active": d.catchup_active,
                "switch_unreachable": d.switch_unreachable,
                "remaining_seconds": coordinator.device_seconds_remaining(d),
                "runtime_today_s": round(d.runtime_today_s, 1),
                "schedules": d.schedules,
            }
            for d in coordinator.devices
        ],
    }
