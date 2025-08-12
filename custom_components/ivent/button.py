"""Podpora za i-Vent gumbe."""
from typing import Any, Dict

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import IVentGroupEntity

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi button entitete iz konfiguracijskega vnosa."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})

    async_add_entities(
        IVentDeleteGroupButton(coordinator, group)
        for group in info_data.get("groups", []) if group.get("id") is not None
    )


class IVentDeleteGroupButton(IVentGroupEntity, ButtonEntity):
    """Predstavlja gumb za izbris skupine."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator, group_data: Dict[str, Any]):
        """Inicializira gumb."""
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_delete"
        self._attr_name = "Izbriši skupino"
        self._attr_icon = "mdi:delete-forever"

    async def async_press(self) -> None:
        """Obravnava pritisk na gumb."""
        # Pošljemo preprost in direkten ukaz za izbris, brez dodatnega sestavljanja.
        payload = {"delete": True}
        await self.coordinator.client.async_modify_group(self._group_id, payload)
        await self.coordinator.async_request_refresh()
