"""Odkrivanje Masterja s poslušanjem MasterAdvertise."""
import asyncio
import socket

import pytest

from custom_components.ivent.ivent_local.discovery import discover_master

from .conftest import FAKE_LOC, FAKE_MACS


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _advertise_forever(fake, port, ip="127.0.0.1"):
    while True:
        fake.advertise(("127.0.0.1", port), ip=ip)
        await asyncio.sleep(0.03)


async def test_discovers_master_from_advert(lab):
    port = _free_port()
    task = asyncio.create_task(_advertise_forever(lab.fake, port))
    try:
        found = await discover_master(timeout=2, bind_host="127.0.0.1", bind_port=port)
    finally:
        task.cancel()
    assert found.ip == "127.0.0.1" and found.mac == FAKE_MACS[0]
    assert found.location_id == FAKE_LOC and found.became_master == 1790396130


async def test_host_filter_ignores_other_masters(lab):
    port = _free_port()
    task = asyncio.create_task(_advertise_forever(lab.fake, port))
    try:
        found = await discover_master(timeout=0.4, host="10.9.9.9", bind_host="127.0.0.1",
                                      bind_port=port)
    finally:
        task.cancel()
    assert found is None


async def test_times_out_without_adverts(socket_enabled):
    assert await discover_master(timeout=0.2, bind_host="127.0.0.1", bind_port=_free_port()) is None


async def test_socket_is_released_after_discovery(socket_enabled):
    port = _free_port()
    await discover_master(timeout=0.1, bind_host="127.0.0.1", bind_port=port)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))  # prosto: odkrivanje je socket zaprlo
    s.close()
