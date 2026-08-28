"""Constants for the Einspeise-Manager integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "einspeise_manager"

# Config entry data keys
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_INVERT = "invert"
CONF_STAGES = "stages"

# Per-stage keys (inside CONF_STAGES list of dicts, stored in entry.data)
CONF_STAGE_ENTITY = "entity_id"
CONF_STAGE_NAME = "name"
CONF_STAGE_RATED_POWER = "rated_power_w"

# Defaults
DEFAULT_ON_THRESHOLD_W = 1000
DEFAULT_HYSTERESIS_W = 200
DEFAULT_ON_DELAY_MIN = 5
DEFAULT_OFF_DELAY_MIN = 5
DEFAULT_STAGE_COUNT = 3
MIN_STAGE_COUNT = 1
MAX_STAGE_COUNT = 6

UPDATE_INTERVAL = timedelta(seconds=15)

# Stage mode select options
MODE_AUTO = "auto"
MODE_ON = "on"
MODE_OFF = "off"
STAGE_MODES = [MODE_AUTO, MODE_ON, MODE_OFF]

# Number entity bounds
THRESHOLD_MIN_W = 0
THRESHOLD_MAX_W = 20000
THRESHOLD_STEP_W = 50

HYSTERESIS_MIN_W = 0
HYSTERESIS_MAX_W = 5000
HYSTERESIS_STEP_W = 50

DELAY_MIN_MIN = 0
DELAY_MAX_MIN = 60
DELAY_STEP_MIN = 1

PLATFORMS = ["sensor", "switch", "select", "number"]
