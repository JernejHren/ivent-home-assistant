"""Sestavljanje zahtev in razčlenjevanje paketov lokalnega i-Vent protokola.

Čiste funkcije brez vhodno-izhodnih operacij: vse delujejo nad ``bytes``.
Varnostni model protokola: edina "poverilnica" je ``locationId``; ``messageId``
(UDPCBody polje 2) NI kriptografski, samo korelacija odgovora.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import const as c
from .wire import (
    Field, WireError, enc_bytes_field, enc_fields, enc_fixed32_field, enc_fixed64_field,
    enc_varint_field, get, parse_fields, set_varint,
)


class ProtocolError(ValueError):
    """Paket ni veljaven i-Vent paket."""


@dataclass(frozen=True)
class Header:
    """Glava UDPCBody. ``destination`` = MAC ciljne naprave (celo število)."""

    location_id: int
    destination: int
    forward: int = 0
    source: int = 0
    source_device_type: int = 2  # 2 = telefon/odjemalec, 1 = naprava

    def encode(self, message_id: int, now: Optional[int] = None) -> bytes:
        return (enc_fixed64_field(1, self.location_id)
                + enc_fixed32_field(2, message_id)
                + enc_varint_field(3, self.forward)
                + enc_varint_field(4, self.source)
                + enc_varint_field(5, self.destination)
                + enc_varint_field(6, int(time.time()) if now is None else now)
                + enc_varint_field(7, self.source_device_type))


def wrap(msg_type: int, body: bytes) -> bytes:
    """BaseMessage: 1 = tip, 2 = verzija (1), 4 = UDPCBody."""
    return enc_varint_field(1, msg_type) + enc_varint_field(2, 1) + enc_bytes_field(4, body)


def build_request(header: Header, message_id: int, msg_type: int, field: int,
                  payload: bytes = b"", now: Optional[int] = None) -> bytes:
    return wrap(msg_type, header.encode(message_id, now) + enc_bytes_field(field, payload))


def compute_set_fields(fields: List[Field]) -> int:
    """Enako kot UDPC.generateSetFields: bit N = polje s tagom N je nastavljeno."""
    mask = 0
    for f, _, _ in fields:
        if 1 <= f < 64:
            mask |= 1 << f
    return mask


def _with_set_fields(fields: List[Field]) -> bytes:
    # setFields je Int64 -> na žici FIXED64 (ne varint!)
    return enc_fields(fields + [(99, 1, compute_set_fields(fields))])


def build_read_group(header: Header, message_id: int, group_id: int,
                     now: Optional[int] = None) -> bytes:
    return build_request(header, message_id, c.T_READ_GROUP, c.F_READ_GROUP[0],
                         enc_fixed32_field(1, group_id), now)


def build_masterlist(header: Header, message_id: int, devices: bool,
                     offset: int = 0, limit: int = 16, now: Optional[int] = None) -> bytes:
    t, f = (c.T_MASTERLIST_DEVICES, c.F_DEVICES[0]) if devices else (
        c.T_MASTERLIST_GROUPS, c.F_GROUPS[0])
    return build_request(header, message_id, t, f,
                         enc_varint_field(1, offset) + enc_varint_field(2, limit), now)


def build_simple(header: Header, message_id: int, msg_type: int, field: int,
                 now: Optional[int] = None) -> bytes:
    """Zahteve s praznim telesom: ping, location, static, sensor, version."""
    return build_request(header, message_id, msg_type, field, b"", now)


def build_modify_group(header: Header, message_id: int, group_id: int,
                       fields: List[Field], now: Optional[int] = None) -> bytes:
    """``fields`` = polja UDPCReq_ModifyGroup brez groupId in setFields."""
    all_fields = sorted([(1, 5, group_id)] + list(fields), key=lambda t: t[0])
    return build_request(header, message_id, c.T_MODIFY_GROUP, c.F_REQ_MODIFY_GROUP,
                         _with_set_fields(all_fields), now)


def build_modify_device(header: Header, message_id: int, fields: List[Field],
                        now: Optional[int] = None) -> bytes:
    """Cilj naprave je v ``header.destination`` (zahtevek nima ID-ja naprave)."""
    return build_request(header, message_id, c.T_MODIFY_DEVICE, c.F_REQ_MODIFY_DEVICE,
                         _with_set_fields(sorted(fields, key=lambda t: t[0])), now)


def build_action(header: Header, message_id: int, action: int,
                 now: Optional[int] = None) -> bytes:
    return build_request(header, message_id, c.T_ACTION, c.F_REQ_ACTION,
                         enc_varint_field(1, action), now)


@dataclass(frozen=True)
class Packet:
    """Razčlenjen paket. Pri ``legacy`` je ``message_id`` None."""

    msg_type: int
    legacy: bool
    body: List[Field]
    message_id: Optional[int] = None
    location_id: Optional[int] = None


def parse_packet(data: bytes) -> Packet:
    try:
        outer = parse_fields(data)
        msg_type = get(outer, 1)
        legacy = get(outer, 3)
        udpc = get(outer, 4)
        if msg_type is None or (legacy is None and udpc is None):
            raise ProtocolError("ni i-Vent paket")
        if legacy is not None:
            body = parse_fields(legacy)
            return Packet(msg_type, True, body, None, get(body, 1))
        body = parse_fields(udpc)
        return Packet(msg_type, False, body, get(body, 2), get(body, 1))
    except WireError as err:
        raise ProtocolError(str(err)) from err


def response_error(packet: Packet) -> Optional[int]:
    """ErrorCode iz ResponseEmpty (None, če paket ni ResponseEmpty)."""
    res = get(packet.body, c.F_RES_EMPTY)
    if res is None:
        return None
    code: int = get(parse_fields(res), 1, 0)
    return code


def merge_remote(current: Optional[List[Field]], changes: Dict[int, int]) -> List[Field]:
    """Kopija prebranega ``remote`` s prepisanimi polji (kot uradna appka).

    Polji 8, 9 (trajanji) nastavi naprava, zato se ne pošiljata; 6 in 7
    (specialModeEndsAt, workModeChangedAt) ostaneta, kot sta prebrani.
    """
    new = list(current or [])
    for tag, value in changes.items():
        set_varint(new, tag, value)
    return [t for t in new if t[0] not in (8, 9)]


def remote_changes_from_cloud(remote: Dict[str, Any]) -> Dict[int, int]:
    """Cloud ``remote_work_mode`` payload -> {tag: številka enuma}."""
    changes: Dict[int, int] = {}
    mapping = (
        ("special_mode", 1, c.SPECIAL_MODE_NUM),
        ("work_mode", 2, c.WORK_MODE_NUM),
        ("bypass_rotation", 3, c.BYPASS_ROTATION_NUM),
        ("remote_control_work_mode", 4, c.REMOTE_WORK_MODE_NUM),
    )
    for key, tag, table in mapping:
        if key in remote:
            if remote[key] not in table:
                raise ProtocolError(f"neznana vrednost {key}={remote[key]!r}")
            changes[tag] = table[remote[key]]
    if "remote_control_speed" in remote:
        changes[5] = int(remote["remote_control_speed"])
    return changes


def group_fields_from_cloud(payload: Dict[str, Any],
                            current_remote: Optional[List[Field]]) -> List[Field]:
    """Cloud ``modify_group`` payload (brez group_id) -> polja UDPCReq_ModifyGroup."""
    fields: List[Field] = []
    if payload.get("delete"):
        fields.append((2, 0, 1))
    if "name" in payload:
        fields.append((3, 2, str(payload["name"]).encode("utf-8")))
    if "led_mode" in payload:
        if payload["led_mode"] not in c.LED_MODE_NUM:
            raise ProtocolError(f"neznan led_mode {payload['led_mode']!r}")
        fields.append((6, 0, c.LED_MODE_NUM[payload["led_mode"]]))
    if "buzzer_mode" in payload:
        if payload["buzzer_mode"] not in c.BUZZER_MODE_NUM:
            raise ProtocolError(f"neznan buzzer_mode {payload['buzzer_mode']!r}")
        fields.append((7, 0, c.BUZZER_MODE_NUM[payload["buzzer_mode"]]))
    if "remote_work_mode" in payload:
        remote = merge_remote(current_remote, remote_changes_from_cloud(payload["remote_work_mode"]))
        fields.append((8, 2, enc_fields(remote)))
    return fields


def device_fields_from_cloud(payload: Dict[str, Any]) -> List[Field]:
    """Cloud ``modify_device`` payload (brez device_mac) -> polja UDPCReq_ModifyDevice.

    ``reverse_flow`` in ``name`` sta potrjena na pravi napravi; ``group_id`` še ni.
    """
    fields: List[Field] = []
    if "reverse_flow" in payload:
        fields.append((1, 0, 1 if payload["reverse_flow"] else 0))
    if "group_id" in payload:
        fields.append((2, 5, int(payload["group_id"])))
    if "name" in payload:
        fields.append((3, 2, str(payload["name"]).encode("utf-8")))
    return fields
