"""Dodatni testi: preslikava napak, rezerva v hibridu, transport, migracija."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ivent.api import (
    IVentApiClientError, IVentApiConnectionError, IVentApiInvalidResponseError,
    IVentApiUnsupportedError,
)
from custom_components.ivent.ivent_local.protocol import ProtocolError
from custom_components.ivent.ivent_local.transport import (
    IVentLocalDeviceError, IVentLocalError, IVentLocalProtocolError,
    IVentLocalTimeout, IVentLocalUnsupported, UdpTransport,
)
from custom_components.ivent.ivent_local.wire import WireError
from custom_components.ivent.local_backend import (
    IVentHybridBackend, IVentLocalBackend,
)


@pytest.mark.parametrize(("raised", "expected"), [
    (IVentLocalUnsupported("x"), IVentApiUnsupportedError),
    (IVentLocalTimeout("x"), IVentApiConnectionError),
    (IVentLocalDeviceError("x"), IVentApiClientError),
    (IVentLocalProtocolError("x"), IVentApiInvalidResponseError),
    (IVentLocalError("x"), IVentApiClientError),
    (WireError("x"), IVentApiInvalidResponseError),
    (ProtocolError("x"), IVentApiClientError),
    (OSError("x"), IVentApiConnectionError),
])
@pytest.mark.parametrize("method", [
    ("async_get_schedules", ()),
    ("async_modify_schedules", ([],)),
    ("async_create_group", ("a",)),
    ("async_modify_group", (5, {})),
    ("async_modify_device", ("aa:bb:cc:00:00:01", {})),
    ("async_beacon", ("aa:bb:cc:00:00:01",)),
])
async def test_local_backend_maps_errors(raised, expected, method):
    name, args = method
    client = MagicMock()
    setattr(client, name, AsyncMock(side_effect=raised))
    backend = IVentLocalBackend(client, MagicMock())
    with pytest.raises(expected):
        await getattr(backend, name)(*args)


async def test_hybrid_modify_device_falls_back_to_cloud():
    local, cloud = MagicMock(), MagicMock()
    local.async_modify_device = AsyncMock(side_effect=IVentApiConnectionError("x"))
    cloud.async_modify_device = AsyncMock()
    hybrid = IVentHybridBackend(local, cloud)
    await hybrid.async_modify_device("aa:bb:cc:00:00:01", {"name": "n"})
    cloud.async_modify_device.assert_awaited_once_with("aa:bb:cc:00:00:01", {"name": "n"})


async def test_hybrid_modify_device_without_cloud_raises():
    local = MagicMock()
    local.async_modify_device = AsyncMock(side_effect=IVentApiConnectionError("x"))
    with pytest.raises(IVentApiConnectionError):
        await IVentHybridBackend(local, None).async_modify_device("m", {})


async def test_hybrid_beacon_and_push_delegate_to_local():
    local = MagicMock()
    local.async_beacon = AsyncMock()
    local.start_push = MagicMock(return_value=lambda: None)
    hybrid = IVentHybridBackend(local, None)
    await hybrid.async_beacon("m")
    local.async_beacon.assert_awaited_once_with("m")
    cb = MagicMock()
    hybrid.start_push(cb, None)
    local.start_push.assert_called_once_with(cb, None)


async def test_transport_listener_lifecycle_and_bad_packets(caplog):
    transport = UdpTransport(bind_host="127.0.0.1", bind_port=0)
    seen = []
    remove = transport.add_listener(lambda pkt, addr: seen.append(pkt))
    boom = transport.add_listener(lambda pkt, addr: 1 / 0)
    transport._on_datagram(b"\xff\xff not a packet", ("127.0.0.1", 1))  # neveljaven paket
    assert seen == []
    remove()
    remove()  # dvojna odjava ni napaka
    boom()
    await transport.stop()  # brez zagnanega socketa


async def test_transport_start_error_closes_socket(socket_enabled):
    transport = UdpTransport(bind_host="203.0.113.1", bind_port=0)  # naslov, ki ni naš
    with pytest.raises(OSError):
        await transport.start()
    assert transport._transport is None


async def test_transport_stop_cancels_pending(socket_enabled):
    transport = UdpTransport(bind_host="127.0.0.1", bind_port=0)
    await transport.start()
    fut = asyncio.get_running_loop().create_future()
    transport._pending[123] = fut
    await transport.stop()
    assert fut.cancelled()
