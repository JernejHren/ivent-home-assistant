"""Podpora za i-Vent vnosna polja."""
from typing import Any, Dict

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi text entitete iz konfiguracijskega vnosa."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})

    entities = []
    all_devices = {}

    for group in info_data.get("groups", []):
        entities.append(IVentGroupNameText(coordinator, group))
        for device in group.get("devices", []):
            if device["mac_address"] not in all_devices:
                all_devices[device["mac_address"]] = device
                entities.append(IVentDeviceNameText(coordinator, device))

    async_add_entities(entities)


class IVentGroupNameText(CoordinatorEntity, TextEntity):
    """Predstavlja polje za preimenovanje skupine."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, group_data: Dict[str, Any]):
        """Inicializira polje."""
        super().__init__(coordinator)
        self._group_id = group_data["id"]
        self._group_data = group_data
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.config_entry.entry_id}_{self._group_id}")}
        }
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_rename"
        self._attr_name = "Ime skupine"
        self._attr_icon = "mdi:rename-box"

    @property
    def native_value(self) -> str:
        """Vrne trenutno ime skupine."""
        return self._group_data.get("name")

    async def async_set_value(self, value: str) -> None:
        """Nastavi novo ime skupine."""
        await self.coordinator.client.async_modify_group(self._group_id, {"name": value})
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje."""
        info_data = self.coordinator.data.get("info", {})
        for group in info_data.get("groups", []):
            if group["id"] == self._group_id:
                self._group_data = group
                self.async_write_ha_state()
                break


class IVentDeviceNameText(CoordinatorEntity, TextEntity):
    """Predstavlja polje za preimenovanje fizične enote."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, device_data: Dict[str, Any]):
        """Inicializira polje."""
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._device_data = device_data
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
        )
        self._attr_unique_id = f"{self._device_mac}_rename"
        self._attr_name = "Ime enote"
        self._attr_icon = "mdi:rename-box"

    @property
    def native_value(self) -> str:
        """Vrne trenutno ime enote."""
        return self._device_data.get("device_name")

    async def async_set_value(self, value: str) -> None:
        """Nastavi novo ime enote."""
        await self.coordinator.client.async_modify_device(self._device_mac, {"name": value})
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje."""
        info_data = self.coordinator.data.get("info", {})
        updated = False
        for group in info_data.get("groups", []):
            for device in group.get("devices", []):
                if device["mac_address"] == self._device_mac:
                    self._device_data = device
                    updated = True
                    break
            if updated:
                break
        self.async_write_ha_state()
