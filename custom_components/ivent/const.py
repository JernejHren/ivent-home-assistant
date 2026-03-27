"""Konstante za i-Vent Smart Home integracijo."""
from typing import Final

DOMAIN: Final = "ivent"
PLATFORMS: Final = [
    "fan", 
    "sensor", 
    "select", 
    "switch", 
    "button", 
    "text", 
    "binary_sensor"
]

# Konfiguracijske vrednosti
CONF_API_KEY: Final = "api_key"
CONF_LOCATION_ID: Final = "location_id"

# Atributi
ATTR_GROUP_ID: Final = "group_id"
ATTR_DEVICES: Final = "devices"
ATTR_RSSI: Final = "rssi"
ATTR_FIRMWARE: Final = "firmware_version"

# API vrednosti za posebne načine
API_MODE_SPECIAL_OFF = "IVentSpecialOff"
API_MODE_NIGHT1 = "IVentNight1"
API_MODE_NIGHT2 = "IVentNight2"
API_MODE_SNOOZE = "IVentSnooze"
API_MODE_BOOST = "IVentBoost"

# API vrednosti za delovne načine
API_MODE_WORK_OFF = "IVentWorkOff"
API_MODE_WORK_ON = "IVentOn"
API_MODE_WORK_CUSTOM = "IVentCustom"
API_MODE_DEFAULT_ON = "IVentRecuperation1" # Privzeto ob vklopu
