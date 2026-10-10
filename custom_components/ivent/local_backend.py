"""Backendi za lokalno in kombinirano delovanje (adapter nad ``ivent_local``).

Napake knjižnice ``ivent_local`` se preslikajo v ``IVentApiClientError`` in
podrazrede, ki jih koordinator že pozna. Brez uvozov iz Home Assistanta.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, cast

from .api import (
    IVentApiClientError,
    IVentApiConnectionError,
    IVentApiInvalidResponseError,
    IVentApiUnsupportedError,
    IVentGroup,
    IVentInfoData,
    IVentScheduleGroup,
)
from .backend import IVentBackend, MasterPushCallback, RemotePushCallback
from .ivent_local import const as local_const
from .ivent_local.client import IVentLocalClient
from .ivent_local.protocol import ProtocolError
from .ivent_local.transport import (
    IVentLocalDeviceError,
    IVentLocalError,
    IVentLocalProtocolError,
    IVentLocalTimeout,
    IVentLocalUnsupported,
    UdpTransport,
)
from .ivent_local.wire import WireError

_LOGGER = logging.getLogger(__name__)


@contextmanager
def _mapped() -> Iterator[None]:
    """Preslika napake lokalne knjižnice v napake integracije."""
    try:
        yield
    except IVentLocalUnsupported as err:
        raise IVentApiUnsupportedError(str(err)) from err
    except IVentLocalTimeout as err:
        raise IVentApiConnectionError(str(err)) from err
    except IVentLocalDeviceError as err:
        raise IVentApiClientError(str(err)) from err
    except IVentLocalProtocolError as err:
        raise IVentApiInvalidResponseError(str(err)) from err
    except IVentLocalError as err:
        raise IVentApiClientError(str(err)) from err
    except WireError as err:
        raise IVentApiInvalidResponseError(f"neveljaven odgovor naprave: {err}") from err
    except ProtocolError as err:
        raise IVentApiClientError(str(err)) from err
    except OSError as err:
        raise IVentApiConnectionError(f"omrežna napaka: {err}") from err


class IVentLocalBackend:
    """Lokalni backend: vse prek UDP, urniki in ustvarjanje skupin niso podprti."""

    def __init__(self, client: IVentLocalClient, transport: UdpTransport) -> None:
        self._client = client
        self._transport = transport

    @classmethod
    def create(cls, *, location_id: int, master_host: str, master_mac: int | str,
               bind_port: int = local_const.UDP_PORT, port: int = local_const.UDP_PORT,
               timeout: float = 3.0, retries: int = 2) -> "IVentLocalBackend":
        transport = UdpTransport(bind_port=bind_port, port=port, timeout=timeout, retries=retries)
        client = IVentLocalClient(transport, location_id=location_id, master_host=master_host,
                                  master_mac=master_mac)
        return cls(client, transport)

    # -- življenjski cikel / push (IVentPushBackend) -------------------------
    async def async_start(self) -> None:
        await self._transport.start()

    async def async_stop(self) -> None:
        await self._transport.stop()

    def start_push(self, on_remote: Optional[RemotePushCallback] = None,
                   on_master: Optional[MasterPushCallback] = None) -> Callable[[], None]:
        return self._client.start_push(on_remote, on_master)

    # -- IVentBackend --------------------------------------------------------
    async def async_ping(self) -> int:
        """Preveri, da Master odgovarja; vrne ``networkHash``."""
        with _mapped():
            return await self._client.async_ping()

    async def async_get_info(self) -> IVentInfoData:
        with _mapped():
            return cast(IVentInfoData, await self._client.async_get_info())

    async def async_get_schedules(self) -> List[IVentScheduleGroup]:
        with _mapped():
            return cast(List[IVentScheduleGroup], await self._client.async_get_schedules())

    async def async_modify_schedules(self, schedules: List[IVentScheduleGroup]) -> None:
        with _mapped():
            await self._client.async_modify_schedules(cast(List[Any], schedules))

    async def async_create_group(self, name: str) -> IVentGroup:
        with _mapped():
            return cast(IVentGroup, await self._client.async_create_group(name))

    async def async_modify_group(self, group_id: int, payload: Dict[str, Any]) -> None:
        with _mapped():
            await self._client.async_modify_group(group_id, payload)

    async def async_modify_device(self, device_mac: str, payload: Dict[str, Any]) -> None:
        with _mapped():
            await self._client.async_modify_device(device_mac, payload)

    async def async_beacon(self, device_mac: str) -> None:
        with _mapped():
            await self._client.async_beacon(device_mac)


class IVentHybridBackend:
    """Kombinirano: stanje in pisanje lokalno; oblak za urnike in kot rezerva za pisanje.

    Rezerva za pisanje velja le, ko Master ni dosegljiv (``IVentApiConnectionError``).
    Če naprava ukaz zavrne (ErrorCode), se ne ponavlja prek oblaka.
    ``info_fallback=True`` doda rezervo tudi za branje stanja (privzeto izklopljena,
    da stanje ne preskakuje med dvema viroma).
    """

    def __init__(self, local: IVentLocalBackend, cloud: Optional[IVentBackend],
                 *, info_fallback: bool = False) -> None:
        self._local = local
        self._cloud = cloud
        self._info_fallback = info_fallback

    # -- življenjski cikel / push: vedno lokalno ------------------------------
    async def async_start(self) -> None:
        await self._local.async_start()

    async def async_stop(self) -> None:
        await self._local.async_stop()

    def start_push(self, on_remote: Optional[RemotePushCallback] = None,
                   on_master: Optional[MasterPushCallback] = None) -> Callable[[], None]:
        return self._local.start_push(on_remote, on_master)

    async def async_beacon(self, device_mac: str) -> None:
        await self._local.async_beacon(device_mac)

    # -- branje ---------------------------------------------------------------
    async def async_get_info(self) -> IVentInfoData:
        try:
            return await self._local.async_get_info()
        except IVentApiConnectionError:
            if self._cloud is not None and self._info_fallback:
                _LOGGER.warning("Master ni dosegljiv, stanje berem iz oblaka")
                return await self._cloud.async_get_info()
            raise

    async def async_get_schedules(self) -> List[IVentScheduleGroup]:
        if self._cloud is None:
            raise IVentApiUnsupportedError("urniki zahtevajo oblak")
        return await self._cloud.async_get_schedules()

    # -- pisanje --------------------------------------------------------------
    async def async_modify_schedules(self, schedules: List[IVentScheduleGroup]) -> None:
        if self._cloud is None:
            raise IVentApiUnsupportedError("urniki zahtevajo oblak")
        await self._cloud.async_modify_schedules(schedules)

    async def async_create_group(self, name: str) -> IVentGroup:
        if self._cloud is None:
            raise IVentApiUnsupportedError("ustvarjanje skupin zahteva oblak")
        return await self._cloud.async_create_group(name)

    async def async_modify_group(self, group_id: int, payload: Dict[str, Any]) -> None:
        try:
            await self._local.async_modify_group(group_id, payload)
        except IVentApiConnectionError:
            if self._cloud is None:
                raise
            _LOGGER.warning("Master ni dosegljiv, ukaz za skupino %s gre prek oblaka", group_id)
            await self._cloud.async_modify_group(group_id, payload)

    async def async_modify_device(self, device_mac: str, payload: Dict[str, Any]) -> None:
        try:
            await self._local.async_modify_device(device_mac, payload)
        except IVentApiConnectionError:
            if self._cloud is None:
                raise
            _LOGGER.warning("Naprava %s ni dosegljiva lokalno, ukaz gre prek oblaka", device_mac)
            await self._cloud.async_modify_device(device_mac, payload)
