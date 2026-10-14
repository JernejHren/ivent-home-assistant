"""Minimalen protobuf wire-format (brez .proto sheme, brez odvisnosti)."""
from __future__ import annotations

import struct
from typing import Any, Iterable, List, Tuple

Field = Tuple[int, int, Any]  # (številka polja, wire type, vrednost)


class WireError(ValueError):
    """Neveljaven protobuf."""


def enc_varint(v: int) -> bytes:
    if v < 0:
        v &= 0xFFFFFFFFFFFFFFFF  # int64 v dvojiškem komplementu (10 bajtov)
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def enc_tag(f: int, w: int) -> bytes:
    return enc_varint((f << 3) | w)


def enc_varint_field(f: int, v: int) -> bytes:
    return enc_tag(f, 0) + enc_varint(v)


def enc_fixed32_field(f: int, v: int) -> bytes:
    return enc_tag(f, 5) + struct.pack("<I", v & 0xFFFFFFFF)


def enc_fixed64_field(f: int, v: int) -> bytes:
    return enc_tag(f, 1) + struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)


def enc_bytes_field(f: int, d: bytes) -> bytes:
    return enc_tag(f, 2) + enc_varint(len(d)) + d


def enc_fields(fields: Iterable[Field]) -> bytes:
    out = b""
    for f, w, v in fields:
        if w == 0:
            out += enc_varint_field(f, v)
        elif w == 1:
            out += enc_fixed64_field(f, v)
        elif w == 5:
            out += enc_fixed32_field(f, v)
        elif w == 2:
            out += enc_bytes_field(f, v)
        else:
            raise WireError(f"wire type {w}")
    return out


def _dec_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise WireError("nepopoln varint")
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 70:
            raise WireError("predolg varint")


def parse_fields(data: bytes) -> List[Field]:
    """Razčleni sporočilo -> seznam (polje, wire, vrednost)."""
    out: List[Field] = []
    pos = 0
    try:
        while pos < len(data):
            tag, pos = _dec_varint(data, pos)
            f, w = tag >> 3, tag & 7
            v: Any
            if w == 0:
                v, pos = _dec_varint(data, pos)
            elif w == 1:
                v = struct.unpack_from("<Q", data, pos)[0]
                pos += 8
            elif w == 5:
                v = struct.unpack_from("<I", data, pos)[0]
                pos += 4
            elif w == 2:
                n, pos = _dec_varint(data, pos)
                if pos + n > len(data):
                    raise WireError("dolžina presega paket")
                v = data[pos:pos + n]
                pos += n
            else:
                raise WireError(f"wire type {w}")
            out.append((f, w, v))
    except struct.error as err:
        raise WireError(str(err)) from err
    return out


def get(fields: Iterable[Field], num: int, default: Any = None) -> Any:
    for f, _, v in fields:
        if f == num:
            return v
    return default


def get_all(fields: Iterable[Field], num: int) -> List[Any]:
    return [v for f, _, v in fields if f == num]


def set_varint(fields: List[Field], num: int, value: int) -> None:
    """Prepiše varint polje (ohrani vrstni red) ali ga doda."""
    for i, (f, _, _) in enumerate(fields):
        if f == num:
            fields[i] = (num, 0, value)
            return
    fields.append((num, 0, value))
    fields.sort(key=lambda t: t[0])


def to_signed64(v: int) -> int:
    return v - (1 << 64) if v >= 1 << 63 else v
