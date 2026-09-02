"""Constants for the Wattix integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "wattix"

# Config entry data keys
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_INVERT = "invert"
# Optional: raw PV production and battery power, so a device's switch-on
# threshold can be based on something other than grid feed-in (see
# THRESHOLD_BASIS_* below). Both optional - existing setups keep working
# unchanged with just the grid sensor.
CONF_PV_PRODUCTION_ENTITY = "pv_production_entity"
CONF_STORAGE_POWER_ENTITY = "storage_power_entity"
CONF_STORAGE_INVERT = "storage_invert"
# Optional: battery state of charge (%), so a device can additionally
# require the battery to already be charged enough before switching on -
# see Device.min_soc_percent in coordinator.py.
CONF_STORAGE_SOC_ENTITY = "storage_soc_entity"

# Defaults for a newly added device
DEFAULT_HYSTERESIS_W = 0
DEFAULT_ON_DELAY_S = 300
DEFAULT_OFF_DELAY_S = 300

UPDATE_INTERVAL = timedelta(seconds=10)

# Minimum gap between two devices switching on, or two devices switching
# off, in the same cascade step - so a sudden change in surplus (or enough
# headroom for several devices at once) ramps load up/down gradually
# instead of switching everything at the same instant.
CASCADE_STAGGER_S = 10

# How long the opposite condition must persist before an on/off delay timer
# actually gets reset, so a brief reading blip (e.g. a battery/storage
# regulating and briefly overshooting the threshold) doesn't wipe out an
# almost-complete wait.
RESET_GRACE_S = 30

# Default instance-level setting: 0 = disabled (opt-in). If > 0, all
# switches get shut down (staggered by CASCADE_STAGGER_S) once the grid
# power sensor hasn't reported a fresh value for this many seconds - a
# safety fallback for a stuck/dead sensor.
DEFAULT_SENSOR_TIMEOUT_S = 0

# Device mode
MODE_AUTO = "auto"
MODE_ON = "on"
MODE_OFF = "off"
MODE_DISABLED = "disabled"  # "Regelung aus": Wattix does not touch this device at all
DEVICE_MODES = [MODE_AUTO, MODE_ON, MODE_OFF, MODE_DISABLED]

# What a device's on/off threshold is measured against.
#   surplus             - grid feed-in (Überschuss), the default: what's left
#                          over after the house and a charging battery.
#   production          - raw PV production, regardless of house consumption
#                          or battery state. E.g. "always on once the panels
#                          make at least 50W".
#   surplus_pre_storage  - production minus house consumption, *before* a
#                          charging battery is subtracted (surplus + whatever
#                          currently goes into the battery). Lets a device
#                          outrank battery charging in the priority order.
THRESHOLD_BASIS_SURPLUS = "surplus"
THRESHOLD_BASIS_PRODUCTION = "production"
THRESHOLD_BASIS_SURPLUS_PRE_STORAGE = "surplus_pre_storage"
THRESHOLD_BASES = [
    THRESHOLD_BASIS_SURPLUS,
    THRESHOLD_BASIS_PRODUCTION,
    THRESHOLD_BASIS_SURPLUS_PRE_STORAGE,
]
DEFAULT_THRESHOLD_BASIS = THRESHOLD_BASIS_SURPLUS

PLATFORMS = ["sensor", "switch"]

STORAGE_VERSION = 1
