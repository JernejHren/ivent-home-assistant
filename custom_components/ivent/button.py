"""Podpora za i-Vent gumbe."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IVentCoordinator, IVentGroupData
from .entity import IVentGroupEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi button entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return
            
        new_entities: list[ButtonEntity] = []

        entry_id = coordinator.config_entry.entry_id

        for group in coordinator.data.groups_by_id.values():
            uid = f"{entry_id}_{group.id}_delete"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentDeleteGroupButton(coordinator, group))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class IVentDeleteGroupButton(IVentGroupEntity, ButtonEntity):
    """Predstavlja gumb za izbris skupine."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:delete-forever"

    def __init__(
        self,
        coordinator: IVentCoordinator,
        group_data: IVentGroupData,
    ) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_delete"
        self._attr_translation_key = "delete_group"

    async def async_press(self) -> None:
        """Obravnava pritisk na gumb."""
        await self.async_update_group({"delete": True})
