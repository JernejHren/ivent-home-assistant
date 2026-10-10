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
CONF_LOCATION_ID: Final = "location_id"  # u64 kot decimalni niz; enak v oblaku in lokalno
CONF_MODE: Final = "mode"
CONF_LOCAL_HOST: Final = "local_host"  # IP Location Masterja
CONF_LOCAL_MAC: Final = "local_mac"  # MAC Location Masterja (naslov v UDPC glavi)

MODE_CLOUD: Final = "cloud"
MODE_LOCAL: Final = "local"
MODE_HYBRID: Final = "hybrid"
LOCAL_MODES: Final = (MODE_LOCAL, MODE_HYBRID)

# Nastavitve (options)
OPT_INFO_FALLBACK: Final = "info_fallback"  # hibrid: stanje iz oblaka, ko Master ni dosegljiv

# Rezervirana skupina "vse naprave" (Group_0 v dokumentaciji, id 1 v praksi).
# Oblak ukazov nanjo ne razširi na ostale skupine, zato jih integracija
# razširi sama (kot uradna aplikacija).
ALL_GROUPS_ID: Final = 1

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
