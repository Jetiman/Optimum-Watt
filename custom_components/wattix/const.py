"""Constants for the Wattix integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "wattix"

# Config entry data keys
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_INVERT = "invert"

# Defaults for a newly added device
DEFAULT_HYSTERESIS_W = 100
DEFAULT_ON_DELAY_S = 300
DEFAULT_OFF_DELAY_S = 300

UPDATE_INTERVAL = timedelta(seconds=10)

# Minimum gap between two devices turning off in the same power dip, so a
# sudden loss of surplus sheds load gradually instead of dropping everything
# on the grid at once.
CASCADE_OFF_STAGGER_S = 10

# Device mode
MODE_AUTO = "auto"
MODE_ON = "on"
MODE_OFF = "off"
MODE_DISABLED = "disabled"  # "Regelung aus": Wattix does not touch this device at all
DEVICE_MODES = [MODE_AUTO, MODE_ON, MODE_OFF, MODE_DISABLED]

PLATFORMS = ["sensor", "switch"]

STORAGE_VERSION = 1
