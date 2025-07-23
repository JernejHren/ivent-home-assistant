"""i-Vent integration for Home Assistant"""

import logging
import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_LOCATION_ID, CONF_API_KEY

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    session = async_get_clientsession(hass)
    api_key = entry.data[CONF_API_KEY]
    location_id = entry.data[CONF_LOCATION_ID]

    client = IVentApiClient(api_key, location_id, session)
    coordinator = IVentDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client
    }

    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, "sensor"))
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, "button"))

    return True

class IVentApiClient:
    def __init__(self, api_key, location_id, session):
        self._api_key = api_key
        self._loc_id = location_id
        self._session = session
        self._base_url = "https://cloud.i-vent.com/api/v1"

    async def get_info(self):
        url = f"{self._base_url}/live/{self._loc_id}/info"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with async_timeout.timeout(10):
            async with self._session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise UpdateFailed(f"Status: {response.status}")
                return await response.json()

    async def set_group_mode(self, group_id: int, work_mode: str, special_mode: str = "IVentSpecialOff"):
        url = f"{self._base_url}/live/{self._loc_id}/modify_group"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {
            "group_id": group_id,
            "remote_work_mode": {
                "work_mode": work_mode,
                "special_mode": special_mode,
                "remote_control_work_mode": "Normal",
                "remote_control_speed": 2,
                "bypass_rotation": "BypassForward"
            }
        }
        async with async_timeout.timeout(10):
            async with self._session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    raise UpdateFailed(f"Failed to set mode: {response.status}")

class IVentDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client):
        super().__init__(
            hass,
            _LOGGER,
            name="i-Vent Coordinator",
            update_interval=hass.helpers.event.dt_util.timedelta(seconds=30),
        )
        self._client = client

    async def _async_update_data(self):
        return await self._client.get_info()
