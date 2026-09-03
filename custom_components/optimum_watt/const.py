"""Constants for the Optimum Watt integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "optimum_watt"

# Config entry data keys
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_INVERT = "invert"

# Defaults for a newly added device
DEFAULT_HYSTERESIS_W = 100
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
MODE_DISABLED = "disabled"  # "Regelung aus": Optimum Watt does not touch this device at all
DEVICE_MODES = [MODE_AUTO, MODE_ON, MODE_OFF, MODE_DISABLED]

PLATFORMS = ["sensor", "switch"]

STORAGE_VERSION = 1
