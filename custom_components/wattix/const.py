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

# Device mode
MODE_AUTO = "auto"
MODE_ON = "on"
MODE_OFF = "off"
DEVICE_MODES = [MODE_AUTO, MODE_ON, MODE_OFF]

PLATFORMS = ["sensor", "switch"]

STORAGE_VERSION = 1
