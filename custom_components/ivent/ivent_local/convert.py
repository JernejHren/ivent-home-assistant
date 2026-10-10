"""Dekodiranje odgovorov lokalnega protokola v oblike cloud API-ja.

Rezultat ustreza ``IVentInfoData`` / ``IVentGroup`` / ``IVentDevice``
(potrjeno 1:1 v primerjavi lokalno <-> oblak).
"""
from __future__ import annotations

import socket
import struct
from typing import Any, Dict, List, Optional, Tuple

from . import const as c
from .wire import Field, get, get_all, parse_fields, to_signed64


def mac_to_str(v: int) -> str:
    return ":".join(f"{b:02x}" for b in v.to_bytes(6, "little"))


def mac_from_str(s: str) -> int:
    return int.from_bytes(bytes(int(x, 16) for x in s.split(":")), "little")


def ip_to_str(v: int) -> str:
    return socket.inet_ntoa(struct.pack("<I", v & 0xFFFFFFFF))


def _name(table: Dict[int, str], n: int) -> str:
    return table.get(n, f"Unknown{n}")


def _text(v: Any) -> str:
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else ""


def decode_remote(raw: Optional[bytes]) -> Dict[str, Any]:
    """RemoteControlMessage -> cloud ``remote`` (manjkajoča polja = privzete vrednosti)."""
    f = parse_fields(raw) if raw else []
    changed = get(f, 7, 0)
    return {
        "special_mode": _name(c.SPECIAL_MODE, get(f, 1, 0)),
        "work_mode": _name(c.WORK_MODE, get(f, 2, 0)),
        "bypass_rotation": _name(c.BYPASS_ROTATION, get(f, 3, 1)),
        "remote_control_work_mode": _name(c.REMOTE_WORK_MODE, get(f, 4, 1)),
        "remote_control_speed": get(f, 5, 0),
        "special_mode_ends_at": get(f, 6, 0),
        "work_mode_changed_at": changed or None,
    }


def decode_profile(raw: Optional[bytes]) -> Dict[str, int]:
    f = parse_fields(raw) if raw else []
    return {name: get(f, i, 0) for i, name in enumerate(c.GROUP_PROFILE_FIELDS, 1)}


def decode_master_group(raw: bytes) -> Dict[str, Any]:
    f = parse_fields(raw)
    return {
        "id": get(f, 1, 0),
        "name": _text(get(f, 2, b"")),
        "remote": decode_remote(get(f, 3)),
        "profile": decode_profile(get(f, 4)),
        "current_mode_duration_in": get(f, 5, 0),
        "current_mode_duration_out": get(f, 6, 0),
        "disable_schedule_until": get(f, 7, 0),
    }


def decode_master_device(raw: bytes) -> Dict[str, Any]:
    """MasterListDevice -> cloud ``LiveDevice`` (+ ``group_id`` in ``ip`` za lokalno rabo)."""
    f = parse_fields(raw)
    return {
        "mac_address": mac_to_str(get(f, 1, 0)),
        "group_id": get(f, 2, 0),
        "rssi": to_signed64(get(f, 3, 0)),
        "alive": bool(get(f, 4, 0)),
        "reverse_flow": bool(get(f, 6, 0)),
        "device_name": _text(get(f, 7, b"")),
        "firmware_version": get(f, 10, 0),
        "ip": ip_to_str(get(f, 11, 0)),
        "status_esp": get(f, 12, 0),
    }


def decode_masterlist(res: bytes, devices: bool) -> Tuple[int, List[Dict[str, Any]]]:
    """Ena stran MasterlistGroups/Devices -> (totalCount, elementi)."""
    f = parse_fields(res)
    dec = decode_master_device if devices else decode_master_group
    return get(f, 1, 0), [dec(item) for item in get_all(f, 2)]


def decode_read_group(res: bytes) -> Dict[str, Any]:
    f = parse_fields(res)
    return {
        "id": get(f, 9, 0),
        "name": _text(get(f, 3, b"")),
        "remote": decode_remote(get(f, 4)),
        "remote_raw": parse_fields(get(f, 4)) if get(f, 4) is not None else None,
        "enable_schedule": bool(get(f, 2, 0)),
        "led_work_mode": _name(c.LED_MODE, get(f, 5, 0)),
        "buzzer_work_mode": _name(c.BUZZER_MODE, get(f, 6, 0)),
        "profile": decode_profile(get(f, 7)),
        "current_mode_duration_in": get(f, 11, 0),
        "current_mode_duration_out": get(f, 12, 0),
    }


def build_info(groups: List[Dict[str, Any]], devices: List[Dict[str, Any]],
               read_groups: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Sestavi ``IVentInfoData`` iz lokalnih seznamov.

    ``read_groups`` (id -> decode_read_group) doda led/buzzer/enable_schedule,
    ki jih MasterlistGroups ne nosi; brez njih veljajo privzeti Led/Buzzer Off
    in ``enable_schedule`` = False.
    """
    read_groups = read_groups or {}
    out_groups = []
    for g in groups:
        full = read_groups.get(g["id"], {})
        out_groups.append({
            "id": g["id"],
            "name": g["name"],
            "led_work_mode": full.get("led_work_mode", "LedOffMode"),
            "buzzer_work_mode": full.get("buzzer_work_mode", "BuzzerOffMode"),
            "enable_schedule": full.get("enable_schedule", False),
            "remote": g["remote"],
            "devices": [
                {k: d[k] for k in ("mac_address", "device_name", "rssi", "firmware_version",
                                   "alive", "status_esp", "reverse_flow")}
                for d in devices if d["group_id"] == g["id"]
            ],
        })
    return {"groups": out_groups}


# --- legacy broadcast ---------------------------------------------------------

def decode_master_advertise(body: List[Field]) -> Dict[str, Any]:
    f = parse_fields(get(body, 2, b""))
    return {"became_master": get(f, 1, 0), "mac": mac_to_str(get(f, 2, 0)),
            "ip": ip_to_str(get(f, 3, 0))}


def decode_remote_control(body: List[Field]) -> Tuple[int, Dict[str, Any]]:
    """Push stanja skupine (tip 6) -> (groupId, cloud ``remote``)."""
    f = parse_fields(get(body, 5, b""))
    return get(f, 2, 0), decode_remote(get(f, 1))


def decode_response(body: List[Field], field: int) -> Optional[bytes]:
    res: Optional[bytes] = get(body, field)
    return res
