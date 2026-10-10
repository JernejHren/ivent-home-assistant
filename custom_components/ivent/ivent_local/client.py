"""Lokalni i-Vent odjemalec: iste operacije kot IVentBackend, prek UDP.

Vrača iste JSON oblike kot cloud API. Brez uvozov iz Home Assistanta.
Urniki in ustvarjanje skupin lokalno še nista podprta (``IVentLocalUnsupported``).
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

from . import const as c
from . import convert as cv
from . import protocol as p
from .transport import (
    IVentLocalDeviceError, IVentLocalProtocolError, IVentLocalTimeout, IVentLocalUnsupported,
    UdpTransport,
)
from .wire import get, get_all, parse_fields

_LOGGER = logging.getLogger(__name__)

PAGE_LIMIT = 16
RemoteCallback = Callable[[int, Dict[str, Any]], None]
MasterCallback = Callable[[Dict[str, Any]], None]


class IVentLocalClient:
    """Govori z Location Masterjem (skupine) in neposredno z napravami (ModifyDevice)."""

    def __init__(self, transport: UdpTransport, *, location_id: int, master_host: str,
                 master_mac: int | str) -> None:
        self._t = transport
        self._location_id = location_id
        self._master_host = master_host
        self._master_mac = cv.mac_from_str(master_mac) if isinstance(master_mac, str) else master_mac
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._recent: Deque[Tuple[Any, ...]] = deque(maxlen=128)

    # -- osnovni klic -------------------------------------------------------
    async def _call(self, host: str, dest_mac: int, build: Callable[[p.Header, int], bytes],
                    expect: int, *, forward: int = 0) -> p.Packet:
        header = p.Header(self._location_id, dest_mac, forward=forward)
        mid = self._t.new_message_id()
        packet = await self._t.request(host, build(header, mid), mid)
        err = p.response_error(packet)
        if err not in (None, 0) and packet.msg_type == c.T_RESPONSE_EMPTY:
            raise IVentLocalDeviceError(err)
        if packet.msg_type != expect:
            raise IVentLocalProtocolError(f"tip odgovora {packet.msg_type}, pričakovan {expect}")
        return packet

    async def _master_read(self, req_type: int, fields: Tuple[int, int],
                           build: Callable[[p.Header, int], bytes]) -> bytes:
        packet = await self._call(self._master_host, self._master_mac, build,
                                  req_type | c.RESPONSE_FLAG)
        res = get(packet.body, fields[1])
        if res is None:
            raise IVentLocalProtocolError(f"v odgovoru ni polja {fields[1]}")
        data: bytes = res
        return data

    # -- branje ---------------------------------------------------------------
    async def async_ping(self) -> int:
        """``networkHash``: sledi spremembam na lokaciji (enak kot cloud ``network_hash``)."""
        res = await self._master_read(
            c.T_MASTER_PING, c.F_PING,
            lambda h, m: p.build_simple(h, m, c.T_MASTER_PING, c.F_PING[0]))
        hash_: int = get(parse_fields(res), 1, 0)
        return hash_

    async def _paged(self, devices: bool) -> List[Dict[str, Any]]:
        t, f = (c.T_MASTERLIST_DEVICES, c.F_DEVICES) if devices else (c.T_MASTERLIST_GROUPS, c.F_GROUPS)
        items: List[Dict[str, Any]] = []
        while True:
            offset = len(items)
            def build(h: p.Header, m: int, o: int = offset) -> bytes:
                return p.build_masterlist(h, m, devices, o, PAGE_LIMIT)

            res = await self._master_read(t, f, build)
            total, page = cv.decode_masterlist(res, devices)
            items += page
            if not page or len(items) >= total:
                return items

    async def async_get_groups(self) -> List[Dict[str, Any]]:
        return await self._paged(False)

    async def async_get_devices(self) -> List[Dict[str, Any]]:
        devices = await self._paged(True)
        self._devices = {d["mac_address"]: d for d in devices}
        return devices

    async def async_read_group(self, group_id: int) -> Dict[str, Any]:
        res = await self._master_read(
            c.T_READ_GROUP, c.F_READ_GROUP,
            lambda h, m: p.build_read_group(h, m, group_id))
        return cv.decode_read_group(res)

    async def async_get_info(self, *, read_group_details: bool = True) -> Dict[str, Any]:
        """Stanje lokacije v obliki ``IVentInfoData``.

        ``read_group_details`` doda led/buzzer/enable_schedule (en ReadGroup na skupino).
        """
        groups = await self.async_get_groups()
        devices = await self.async_get_devices()
        details: Dict[int, Dict[str, Any]] = {}
        if read_group_details:
            for g in groups:
                details[g["id"]] = await self.async_read_group(g["id"])
        return cv.build_info(groups, devices, details)

    # -- pisanje --------------------------------------------------------------
    async def async_modify_group(self, group_id: int, payload: Dict[str, Any]) -> None:
        """Enako kot cloud ``modify_group``; ``remote_work_mode`` je read-modify-write."""
        current = None
        if "remote_work_mode" in payload:
            current = (await self.async_read_group(group_id)).get("remote_raw")
        fields = p.group_fields_from_cloud(payload, current)
        await self._call(self._master_host, self._master_mac,
                         lambda h, m: p.build_modify_group(h, m, group_id, fields),
                         c.T_RESPONSE_EMPTY)

    async def async_modify_device(self, device_mac: str, payload: Dict[str, Any]) -> None:
        """Neposredno na napravo (potrjeno); če ne odgovori, prek Masterja z forward=1."""
        mac_int = cv.mac_from_str(device_mac)
        device = self._devices.get(device_mac)
        if device is None:
            await self.async_get_devices()
            device = self._devices.get(device_mac)
        fields = p.device_fields_from_cloud(payload)

        def build(h: p.Header, m: int) -> bytes:
            return p.build_modify_device(h, m, fields)

        if device is not None:
            try:
                await self._call(device["ip"], mac_int, build, c.T_RESPONSE_EMPTY)
                return
            except IVentLocalTimeout:
                _LOGGER.debug("Naprava %s ni odgovorila neposredno, poskušam prek Masterja", device_mac)
        await self._call(self._master_host, mac_int, build, c.T_RESPONSE_EMPTY, forward=1)

    async def async_beacon(self, device_mac: str) -> None:
        """"Najdi napravo": naprava zapiska. Kot uradna appka: prek Masterja, forward=1."""
        await self._call(self._master_host, cv.mac_from_str(device_mac),
                         lambda h, m: p.build_action(h, m, c.ACTION_BEACON),
                         c.T_RESPONSE_EMPTY, forward=1)

    async def async_get_schedules(self) -> List[Any]:
        raise IVentLocalUnsupported("urniki lokalno še niso podprti")

    async def async_modify_schedules(self, schedules: List[Any]) -> None:
        raise IVentLocalUnsupported("urniki lokalno še niso podprti")

    async def async_create_group(self, name: str) -> Dict[str, Any]:
        raise IVentLocalUnsupported("ustvarjanje skupin lokalno še ni podprto")

    # -- push -----------------------------------------------------------------
    def start_push(self, on_remote: Optional[RemoteCallback] = None,
                   on_master: Optional[MasterCallback] = None) -> Callable[[], None]:
        """Posluša broadcast: tip 6 (stanje skupine, 3× ponovitev) in tip 2 (Master).

        ``on_remote(group_id, remote)`` se pokliče enkrat na dogodek (deduplikacija),
        ``on_master(info)`` ob VSAKEM oglasu Masterja (~5 s): to je znak, da broadcast do nas
        res prihaja; spremembo IP/MAC/becameMaster zazna klicatelj sam.
        Vrne funkcijo za odjavo.
        """
        def listener(packet: p.Packet, addr: Tuple[str, int]) -> None:
            if not packet.legacy or packet.location_id != self._location_id:
                return
            if packet.msg_type == c.T_REMOTE_CONTROL and on_remote:
                gid, remote = cv.decode_remote_control(packet.body)
                key = (gid, remote["work_mode_changed_at"], remote["special_mode"],
                       remote["work_mode"], remote["remote_control_speed"],
                       remote["remote_control_work_mode"], remote["bypass_rotation"])
                if key in self._recent:
                    return
                self._recent.append(key)
                on_remote(gid, remote)
            elif packet.msg_type == c.T_MASTER_ADVERTISE and on_master:
                on_master(cv.decode_master_advertise(packet.body))

        return self._t.add_listener(listener)
