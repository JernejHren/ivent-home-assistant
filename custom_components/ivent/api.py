"""Odjemalec za i-Vent Smart Home Cloud API."""
import asyncio
import aiohttp
from typing import Any, Dict, List

BASE_URL = "https://cloud.i-vent.com/api/v1"

class IVentApiClientError(Exception):
    """Splošna napaka za API odjemalca."""

class IVentApiAuthError(IVentApiClientError):
    """Napaka pri avtentikaciji."""

class IVentApiClient:
    """Odjemalec za komunikacijo z i-Vent API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, location_id: str):
        self._session = session
        self._api_key = api_key
        self._location_id = location_id
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Splošna metoda za pošiljanje zahtevkov."""
        url = f"{BASE_URL}{endpoint}"
        try:
            async with self._session.request(method, url, headers=self._headers, timeout=10, **kwargs) as response:
                if response.status == 401 or response.status == 403:
                    raise IVentApiAuthError("Invalid API key or location ID")
                response.raise_for_status()
                if response.status == 200 and response.content_type == 'application/json':
                    return await response.json()
                return {} # Vrnemo prazen slovar za uspešne klice brez vsebine
        except asyncio.TimeoutError as e:
            raise IVentApiClientError(f"Timeout connecting to i-Vent API on {endpoint}") from e
        except aiohttp.ClientError as e:
            raise IVentApiClientError(f"Error connecting to i-Vent API on {endpoint}: {e}") from e

    async def async_get_info(self) -> Dict[str, Any]:
        """Pridobi stanje sistema, vključno s skupinami in napravami."""
        return await self._request("get", f"/live/{self._location_id}/info")

    async def async_get_schedules(self) -> List[Dict[str, Any]]:
        """Pridobi seznam urnikov."""
        return await self._request("get", f"/live/{self._location_id}/schedules")

    async def async_modify_schedules(self, schedules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Posodobi urnike."""
        payload = {"schedules": schedules}
        return await self._request("post", f"/live/{self._location_id}/modify_schedules", json=payload)

    async def async_create_group(self, name: str) -> Dict[str, Any]:
        """Ustvari novo skupino."""
        return await self._request("post", f"/live/{self._location_id}/create_group", json={"name": name})

    async def async_modify_group(self, group_id: int, payload: dict) -> Dict[str, Any]:
        """Pošlje ukaz za spremembo skupine."""
        full_payload = {"group_id": group_id, **payload}
        return await self._request("post", f"/live/{self._location_id}/modify_group", json=full_payload)

    async def async_modify_device(self, device_mac: str, payload: dict) -> Dict[str, Any]:
        """Pošlje ukaz za spremembo naprave."""
        full_payload = {"device_mac": device_mac, **payload}
        return await self._request("post", f"/live/{self._location_id}/modify_device", json=full_payload)
