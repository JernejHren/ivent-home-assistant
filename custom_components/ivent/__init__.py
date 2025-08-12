"""i-Vent Smart Home integracija."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, PLATFORMS
from .api import IVentApiClient, IVentApiClientError

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nastavi i-Vent integracijo iz konfiguracijskega vnosa."""
    hass.data.setdefault(DOMAIN, {})
    
    client = IVentApiClient(
        session=async_get_clientsession(hass),
        api_key=entry.data["api_key"],
        location_id=entry.data["location_id"],
    )

    async def async_update_data():
        """Pridobi najnovejše podatke iz API-ja."""
        try:
            # Vzporedno pridobimo oba vira podatkov
            info_data, schedules_data = await asyncio.gather(
                client.async_get_info(),
                client.async_get_schedules(),
            )
            return {"info": info_data, "schedules": schedules_data}
        except IVentApiClientError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=60),
    )

    coordinator.client = client
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_create_group(call: ServiceCall):
        await client.async_create_group(call.data["name"])
        await coordinator.async_request_refresh()

    async def handle_delete_group(call: ServiceCall):
        await client.async_modify_group(call.data["group_id"], {"delete": True})
        await coordinator.async_request_refresh()

    async def handle_rename_group(call: ServiceCall):
        await client.async_modify_group(call.data["group_id"], {"name": call.data["new_name"]})
        await coordinator.async_request_refresh()

    async def handle_rename_device(call: ServiceCall):
        await client.async_modify_device(call.data["device_mac"], {"name": call.data["new_name"]})
        await coordinator.async_request_refresh()

    async def handle_move_device(call: ServiceCall):
        await client.async_modify_device(call.data["device_mac"], {"group_id": call.data["group_id"]})
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "create_group", handle_create_group)
    hass.services.async_register(DOMAIN, "delete_group", handle_delete_group)
    hass.services.async_register(DOMAIN, "rename_group", handle_rename_group)
    hass.services.async_register(DOMAIN, "rename_device", handle_rename_device)
    hass.services.async_register(DOMAIN, "move_device_to_group", handle_move_device)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Odstrani konfiguracijski vnos."""
    hass.services.async_remove(DOMAIN, "create_group")
    hass.services.async_remove(DOMAIN, "delete_group")
    hass.services.async_remove(DOMAIN, "rename_group")
    hass.services.async_remove(DOMAIN, "rename_device")
    hass.services.async_remove(DOMAIN, "move_device_to_group")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
