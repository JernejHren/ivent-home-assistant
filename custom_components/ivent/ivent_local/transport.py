"""Asyncio UDP transport za lokalni i-Vent protokol.

Ključne lastnosti (vse potrjene na pravi napravi):
  * naprava filtrira po IZVORNEM portu 1028, zato mora ISTI socket pošiljati
    zahtevke in poslušati broadcast (en socket na gostitelja);
  * odgovori se prirejajo po echo-ju ``messageId``, ne po tipu: vmes prihajajo
    ambientni paketi (MasterAdvertise, RemoteControl);
  * UDP brez potrditve: zahtevek se ob izgubi ponovi (isti paket, isti messageId).
"""
from __future__ import annotations

import asyncio
import logging
import random
import socket
from typing import Callable, Dict, List, Optional, Tuple

from . import const as c
from .protocol import Packet, ProtocolError, parse_packet

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[Packet, Tuple[str, int]], None]


class IVentLocalError(Exception):
    """Osnovna napaka lokalnega odjemalca."""


class IVentLocalTimeout(IVentLocalError):
    """Naprava ni odgovorila (tudi ob ponovitvah)."""


class IVentLocalProtocolError(IVentLocalError):
    """Nepričakovan ali neveljaven odgovor."""


class IVentLocalDeviceError(IVentLocalError):
    """Naprava je vrnila ResponseEmpty z ErrorCode != NoError."""

    def __init__(self, code: int) -> None:
        super().__init__(f"device error {code} ({c.ERROR_NAMES.get(code, '?')})")
        self.code = code


class IVentLocalUnsupported(IVentLocalError):
    """Operacija lokalno (še) ni podprta; uporabi oblak."""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "UdpTransport") -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        self._owner._on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover - OS odvisno
        _LOGGER.debug("UDP error: %s", exc)


class UdpTransport:
    """En socket: pošiljanje zahtevkov + poslušanje broadcasta."""

    def __init__(self, *, bind_host: str = "0.0.0.0", bind_port: int = c.UDP_PORT,
                 port: int = c.UDP_PORT, timeout: float = 3.0, retries: int = 2) -> None:
        self._bind = (bind_host, bind_port)
        self._port = port
        self._timeout = timeout
        self._retries = retries
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._pending: Dict[int, asyncio.Future[Packet]] = {}
        self._listeners: List[Listener] = []
        self._lock = asyncio.Lock()  # naprave obdelujejo en zahtevek naenkrat

    @property
    def local_port(self) -> int:
        assert self._transport is not None
        port: int = self._transport.get_extra_info("sockname")[1]
        return port

    async def start(self) -> None:
        if self._transport is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(self._bind)
            sock.setblocking(False)
            loop = asyncio.get_running_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _Protocol(self), sock=sock)
        except OSError:
            sock.close()
            raise

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        await asyncio.sleep(0)  # socket se zapre v naslednji iteraciji zanke: počakaj

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Registrira poslušalca ambientnih paketov; vrne funkcijo za odjavo."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return remove

    def _on_datagram(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            packet = parse_packet(data)
        except ProtocolError:
            _LOGGER.debug("Ignoriran neveljaven paket od %s", addr)
            return
        fut = self._pending.get(packet.message_id) if packet.message_id is not None else None
        if fut is not None and not fut.done():
            fut.set_result(packet)
            return
        for listener in list(self._listeners):
            try:
                listener(packet, addr)
            except Exception:  # noqa: BLE001 - poslušalec ne sme podreti sprejema
                _LOGGER.exception("Napaka v poslušalcu paketov")

    @staticmethod
    def new_message_id() -> int:
        return random.randint(1, 0xFFFFFFFF)

    async def request(self, host: str, packet: bytes, message_id: int, *,
                      timeout: Optional[float] = None,
                      retries: Optional[int] = None) -> Packet:
        """Pošlje zahtevek in vrne odgovor z istim ``messageId``."""
        if self._transport is None:
            raise IVentLocalError("transport ni zagnan")
        timeout = self._timeout if timeout is None else timeout
        attempts = (self._retries if retries is None else retries) + 1
        async with self._lock:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[Packet] = loop.create_future()
            self._pending[message_id] = fut
            try:
                for attempt in range(1, attempts + 1):
                    self._transport.sendto(packet, (host, self._port))
                    try:
                        return await asyncio.wait_for(asyncio.shield(fut), timeout)
                    except asyncio.TimeoutError:
                        _LOGGER.debug("Brez odgovora od %s (poskus %d/%d)", host, attempt, attempts)
                raise IVentLocalTimeout(f"brez odgovora od {host} po {attempts} poskusih")
            finally:
                self._pending.pop(message_id, None)
