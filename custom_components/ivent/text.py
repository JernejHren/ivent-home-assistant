"""Podpora za i-Vent vnosna polja."""
from __future__ import annotations

import time
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IVentCoordinator, IVentGroupData, IVentDeviceData
from .entity import IVentGroupEntity, IVentDeviceEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi text entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return
            
        new_entities: list[TextEntity] = []

        entry_id = coordinator.config_entry.entry_id

        for group in coordinator.data.groups_by_id.values():
            uid = f"{entry_id}_{group.id}_rename"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentGroupNameText(coordinator, group))

        for device in coordinator.data.devices_by_mac.values():
            uid = f"{device.mac_address}_rename"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentDeviceNameText(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class IVentGroupNameText(IVentGroupEntity, TextEntity):
    """Polje za preimenovanje skupine.

    unique_id: {entry_id}_{group_id}_rename  (stable — group_id is immutable API int)
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rename-box"

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_rename"
        self._attr_translation_key = "group_name"

    @property
    def native_value(self) -> str | None:
        group = self._group
        actual = group.name if group else None
        return self._get_optimistic_attr("native_value", actual)  # type: ignore[no-any-return]

    async def async_set_value(self, value: str) -> None:
        await self._async_handle_write("native_value", value, self.async_update_group({"name": value}))


class IVentDeviceNameText(IVentDeviceEntity, TextEntity):
    """Polje za preimenovanje fizične enote.

    unique_id: {mac_address}_rename  (stable — MAC never changes)
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:rename-box"

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_rename"
        self._attr_translation_key = "device_name"

    @property
    def native_value(self) -> str | None:
        device = self._device
        actual = device.device_name if device else None
        return self._get_optimistic_attr("native_value", actual)  # type: ignore[no-any-return]

    async def async_set_value(self, value: str) -> None:
        await self._async_handle_write("native_value", value, self.async_update_device({"name": value}))
