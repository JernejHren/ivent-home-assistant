"""Konstante lokalnega i-Vent protokola (UDP 1028, protobuf).

Vse vrednosti so iz Blutter analize aplikacije in potrjene z živimi testi.
"""
from __future__ import annotations

UDP_PORT = 1028

# --- legacy broadcast (BaseMessage.field3) ---------------------------------
T_WHOIS_MASTER = 1
T_MASTER_ADVERTISE = 2
T_REMOTE_CONTROL = 6

# --- UDPC zahteve (BaseMessage.field4 = UDPCBody) ---------------------------
T_READ_STATIC_INFO = 257
T_READ_SENSOR_DATA = 258
T_PROTOCOL_VERSION = 264
T_MASTERLIST_GROUPS = 267
T_MASTERLIST_DEVICES = 268
T_READ_GROUP = 275
T_MASTER_PING = 279
T_READ_LOCATION = 281
T_MODIFY_DEVICE = 4358
T_ACTION = 4362
T_MODIFY_GROUP = 4370
RESPONSE_FLAG = 0x8000  # veljá za branja: 275 -> 33043
T_RESPONSE_EMPTY = 33279  # odgovor na vse WRITE ukaze

# številka polja v UDPCBody: zahteva / odgovor
F_REQ_ACTION = 78
F_REQ_MODIFY_DEVICE = 72
F_REQ_MODIFY_GROUP = 88
F_RES_EMPTY = 77
F_STATIC = (64, 65)
F_SENSOR = (66, 67)
F_VERSION = (74, 75)
F_GROUPS = (79, 80)
F_DEVICES = (81, 82)
F_READ_GROUP = (89, 90)
F_PING = (96, 97)
F_LOCATION = (99, 100)

# ActionType
ACTION_BEACON = 0x01
ACTION_FILTER_CLEANED = 0x12

# ErrorCode
ERROR_NAMES = {0: "NoError", 1: "UnknownOperation", 2: "UnknownError", 3: "WrongState",
               4: "RestartRequired", 5: "UdpFrameWouldOverflow"}

# --- enumi: protobuf številka <-> ime v cloud API ---------------------------
WORK_MODE = {0: "IVentWorkOff", 1: "IVentOn", 2: "IVentCustom",
             16: "IVentRecuperation1", 17: "IVentRecuperation2", 18: "IVentRecuperation3",
             32: "IVentBypass1", 33: "IVentBypass2", 34: "IVentBypass3"}
SPECIAL_MODE = {0: "IVentSpecialOff", 1: "IVentBoost", 2: "IVentSnooze",
                3: "IVentNight1", 4: "IVentNight2"}
REMOTE_WORK_MODE = {1: "Normal", 2: "Bypass"}
BYPASS_ROTATION = {1: "BypassForward", 2: "BypassReverse"}
LED_MODE = {0: "LedOffMode", 1: "LedOnMode", 2: "LedDebugMode", 3: "LedOffWithErrMode"}
BUZZER_MODE = {0: "BuzzerOffMode", 1: "BuzzerOnMode", 2: "BuzzerDebugMode",
               3: "BuzzerOffWithErrMode", 4: "BuzzerOnMuteErrMode"}


def _inv(d: dict[int, str]) -> dict[str, int]:
    return {v: k for k, v in d.items()}


WORK_MODE_NUM = _inv(WORK_MODE)
SPECIAL_MODE_NUM = _inv(SPECIAL_MODE)
REMOTE_WORK_MODE_NUM = _inv(REMOTE_WORK_MODE)
BYPASS_ROTATION_NUM = _inv(BYPASS_ROTATION)
LED_MODE_NUM = _inv(LED_MODE)
BUZZER_MODE_NUM = _inv(BUZZER_MODE)

# imena polj GroupProfile (tag = indeks od 1)
GROUP_PROFILE_FIELDS = [
    "boostTime", "recuperation1TimeIn", "recuperation2TimeIn", "recuperation3TimeIn",
    "recuperation1TimeOut", "recuperation2TimeOut", "recuperation3TimeOut", "snoozeTime",
    "sleepModeStart", "sleepModeDuration1", "sleepModeDuration2", "bypassTime",
    "doNotDisturbActive", "doNotDisturbStart", "doNotDisturbEnd", "differentialSpeedForward",
    "differentialSpeedReverse", "differentialMode",
]
