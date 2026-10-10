"""Odjemalec za i-Vent Smart Home Cloud API."""
import asyncio
import aiohttp
from typing import Any, Dict, List, cast
from typing import NotRequired, TypedDict

BASE_URL = "https://cloud.i-vent.com/api/v1"


# ---------------------------------------------------------------------------
# TypedDict — schema API odgovorov
# ---------------------------------------------------------------------------

class IVentRemote(TypedDict):
    """Stanje daljinskega upravljača skupne naprave."""
    work_mode: str
    special_mode: str
    remote_control_speed: int
    remote_control_work_mode: str
    bypass_rotation: str
    work_mode_changed_at: int
    special_mode_ends_at: int


class IVentDevice(TypedDict):
    """Podatki o posamezni fizični enoti."""
    mac_address: str
    device_name: str
    rssi: int
    firmware_version: str | int | None
    alive: bool
    status_esp: int
    diagnostic_flags: NotRequired[int | None]
    reverse_flow: bool


class IVentGroup(TypedDict):
    """Skupina naprav (zona) v sistemu."""
    id: int
    name: str
    led_work_mode: str
    buzzer_work_mode: str
    remote: IVentRemote
    devices: List[IVentDevice]


class IVentInfoData(TypedDict):
    """Celoten odgovor info endpointa."""
    groups: List[IVentGroup]


class IVentScheduleMeta(TypedDict):
    schedule_id: int


class IVentScheduleRepeat(TypedDict):
    days: int
    hour: int
    minute: int


class IVentScheduleHeader(TypedDict):
    schedule_item_enabled: bool


class IVentScheduleItem(TypedDict):
    meta: IVentScheduleMeta
    repeat: IVentScheduleRepeat
    header: IVentScheduleHeader


class IVentScheduleGroup(TypedDict):
    name: str
    schedules: List[IVentScheduleItem]


class IVentLocation(TypedDict):
    id: str
    name: str


class IVentApiClientError(Exception):
    """Splošna napaka za API odjemalca."""

class IVentApiAuthError(IVentApiClientError):
    """Napaka pri avtentikaciji."""

class IVentApiConnectionError(IVentApiClientError):
    """Napaka pri povezavi ali casovna prekoracitev (timeout)."""

class IVentApiInvalidResponseError(IVentApiClientError):
    """Napaka zaradi neveljavnega ali nepričakovanega odgovora API."""

class IVentApiClient:
    """Odjemalec za komunikacijo z i-Vent API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, location_id: str | None = None) -> None:
        self._session = session
        self._api_key = api_key
        self._location_id = location_id
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=10)

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Splošna metoda za pošiljanje zahtevkov z retry logiko in backoffom."""
        url = f"{BASE_URL}{endpoint}"
        retries = 3
        backoff = 1.0
        
        kwargs.setdefault("timeout", self._timeout)
        kwargs.setdefault("headers", self._headers)

        for attempt in range(1, retries + 1):
            try:
                async with self._session.request(method, url, **kwargs) as response:
                    # Obravnava avtentikacijskih napak
                    if response.status in (401, 403):
                        raise IVentApiAuthError("Invalid API key or location ID")
                    
                    # Za začasne strežniške napake izvedemo retry
                    if response.status >= 500 and attempt < retries:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue

                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError as e:
                        raise IVentApiClientError(f"HTTP error {response.status} from API: {e}") from e

                    # Obravnava uspešnih odgovorov
                    if response.status == 204:
                        return None
                    
                    try:
                        return await response.json()
                    except aiohttp.ContentTypeError as e:
                        raise IVentApiInvalidResponseError(f"Invalid JSON response from {endpoint}") from e

            # Obravnava napak povezave in timeoutov
            except (TimeoutError, aiohttp.ClientError) as e:
                if attempt == retries:
                    raise IVentApiConnectionError(
                        f"Failed connecting to i-Vent API on {endpoint} after {retries} attempts: {e}"
                    ) from e
                
                # Eksponentni backoff pri omrežnih napakah
                await asyncio.sleep(backoff)
                backoff *= 2

    async def async_get_locations(self) -> List[IVentLocation]:
        """Pridobi seznam razpoložljivih lokacij."""
        result = await self._request("get", "/locations")
        return cast(List[IVentLocation], result)

    async def async_get_info(self) -> IVentInfoData:
        """Pridobi stanje sistema, vključno s skupinami in napravami."""
        result = await self._request("get", f"/live/{self._location_id}/info")
        return cast(IVentInfoData, result)

    async def async_get_schedules(self) -> List[IVentScheduleGroup]:
        """Pridobi seznam urnikov."""
        result = await self._request("get", f"/live/{self._location_id}/schedules")
        return cast(List[IVentScheduleGroup], result)

    async def async_modify_schedules(self, schedules: List[IVentScheduleGroup]) -> None:
        """Posodobi urnike."""
        payload = {"schedules": schedules}
        await self._request("post", f"/live/{self._location_id}/modify_schedules", json=payload)

    async def async_create_group(self, name: str) -> IVentGroup:
        """Ustvari novo skupino."""
        result = await self._request("post", f"/live/{self._location_id}/create_group", json={"name": name})
        return cast(IVentGroup, result)

    async def async_modify_group(self, group_id: int, payload: Dict[str, Any]) -> None:
        """Pošlje ukaz za spremembo skupine."""
        full_payload = {"group_id": group_id, **payload}
        await self._request("post", f"/live/{self._location_id}/modify_group", json=full_payload)

    async def async_modify_device(self, device_mac: str, payload: Dict[str, Any]) -> None:
        """Pošlje ukaz za spremembo naprave."""
        full_payload = {"device_mac": device_mac, **payload}
        await self._request("post", f"/live/{self._location_id}/modify_device", json=full_payload)
