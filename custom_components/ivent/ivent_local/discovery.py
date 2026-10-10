"""Samodejno odkrivanje Location Masterja s pasivnim poslušanjem MasterAdvertise (tip 2).

Master oglašuje na broadcast (~vsakih 5 s) svoj MAC, IP in ``locationId``. Iz enega
oglasa dobimo vse, kar potrebuje lokalni odjemalec, brez QR kode. Ne deluje iz
omrežij brez dostopa do broadcasta (npr. Docker bridge): tam podaj vrednosti ročno.

Varnostna opomba: ``locationId`` je edina poverilnica protokola in se oddaja v čistopisu.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from . import const as c
from . import convert as cv
from .protocol import Packet
from .transport import UdpTransport


@dataclass(frozen=True)
class DiscoveredMaster:
    ip: str
    mac: str
    location_id: int
    became_master: int


async def discover_master(*, timeout: float = 8.0, host: Optional[str] = None,
                          bind_host: str = "0.0.0.0", bind_port: int = c.UDP_PORT,
                          port: int = c.UDP_PORT) -> Optional[DiscoveredMaster]:
    """Počaka na oglas Masterja; ``host`` omeji na oglase s tega IP-ja.

    Vrne None ob izteku časa. ``OSError`` (npr. zaseden port 1028) se ne ujame.
    """
    transport = UdpTransport(bind_host=bind_host, bind_port=bind_port, port=port)
    await transport.start()
    found: asyncio.Future[DiscoveredMaster] = asyncio.get_running_loop().create_future()

    def listener(packet: Packet, addr: tuple[str, int]) -> None:
        if not packet.legacy or packet.msg_type != c.T_MASTER_ADVERTISE or found.done():
            return
        if packet.location_id is None:
            return
        info = cv.decode_master_advertise(packet.body)
        if host and info["ip"] != host:
            return
        found.set_result(DiscoveredMaster(info["ip"], info["mac"], packet.location_id,
                                          info["became_master"]))

    remove = transport.add_listener(listener)
    try:
        return await asyncio.wait_for(found, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        remove()
        await transport.stop()
