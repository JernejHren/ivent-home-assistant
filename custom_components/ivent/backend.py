"""Abstrakcija backenda za i-Vent (oblak, v prihodnje tudi lokalno).

Protocol opisuje točno tisto, kar integracija potrebuje, in vrača iste JSON
oblike kot cloud API (``IVentInfoData``, payloadi ``modify_group`` /
``modify_device``). Tako lahko lokalni odjemalec zamenja oblačnega brez
sprememb v koordinatorju in entitetah (potrjeno 1:1 v primerjavi
lokalno <-> oblak).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from .api import (
    IVentGroup,
    IVentInfoData,
    IVentScheduleGroup,
)


@runtime_checkable
class IVentBackend(Protocol):
    """Vmesnik, ki ga mora izpolnjevati vsak vir podatkov in izvajalec ukazov."""

    async def async_get_info(self) -> IVentInfoData:
        """Stanje lokacije: skupine, naprave, remote stanja."""
        ...

    async def async_get_schedules(self) -> List[IVentScheduleGroup]:
        """Urniki skupin."""
        ...

    async def async_modify_schedules(self, schedules: List[IVentScheduleGroup]) -> None:
        """Zapiše urnike."""
        ...

    async def async_create_group(self, name: str) -> IVentGroup:
        """Ustvari skupino."""
        ...

    async def async_modify_group(self, group_id: int, payload: Dict[str, Any]) -> None:
        """Spremeni skupino (remote_work_mode, led_mode, buzzer_mode, name, delete)."""
        ...

    async def async_modify_device(self, device_mac: str, payload: Dict[str, Any]) -> None:
        """Spremeni napravo (name, group_id, reverse_flow)."""
        ...


RemotePushCallback = Callable[[int, Dict[str, Any]], None]
MasterPushCallback = Callable[[Dict[str, Any]], None]


@runtime_checkable
class IVentPushBackend(Protocol):
    """Backend, ki poleg zahtevkov sam javlja spremembe (lokalni UDP broadcast).

    Oblačni odjemalec tega ne podpira; koordinator zato pri njem ostane pri pollingu.
    """

    async def async_start(self) -> None:
        """Odpre vire (socket). Lahko vrže OSError (npr. port 1028 je zaseden)."""
        ...

    async def async_stop(self) -> None:
        """Zapre vire."""
        ...

    def start_push(
        self,
        on_remote: Optional[RemotePushCallback] = None,
        on_master: Optional[MasterPushCallback] = None,
    ) -> Callable[[], None]:
        """Naroči se na dogodke; vrne funkcijo za odjavo."""
        ...
