"""Podpora za i-Vent gumbe."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.exceptions import HomeAssistantError

from .api import IVentApiClientError
from .backend import IVentActionBackend
from .const import DOMAIN
from .coordinator import IVentConfigEntry, IVentCoordinator, IVentDeviceData, IVentGroupData
from .entity import IVentDeviceEntity, IVentGroupEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IVentConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi button entitete iz konfiguracijskega vnosa."""
    coordinator: IVentCoordinator = entry.runtime_data.coordinator

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

        # "Najdi napravo" in ponastavitev filtra obstajata samo lokalno (oblačni API ju nima)
        if isinstance(coordinator.client, IVentActionBackend):
            for device in coordinator.data.devices_by_mac.values():
                uid_beacon = f"{device.mac_address}_beacon"
                if uid_beacon not in added_entities:
                    added_entities.add(uid_beacon)
                    new_entities.append(IVentBeaconButton(coordinator, device))
                uid_filter = f"{device.mac_address}_filter_reset"
                if uid_filter not in added_entities:
                    added_entities.add(uid_filter)
                    new_entities.append(IVentFilterResetButton(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class IVentDeleteGroupButton(IVentGroupEntity, ButtonEntity):
    """Predstavlja gumb za izbris skupine."""

    _attr_entity_category = EntityCategory.CONFIG

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


class _IVentDeviceActionButton(IVentDeviceEntity, ButtonEntity):
    """Gumb, ki napravi pošlje enkratni ukaz (Action) prek lokalnega backenda."""

    _attr_entity_category = EntityCategory.CONFIG
    _key: str

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_{self._key}"
        self._attr_translation_key = self._key

    async def _async_run(self, backend: IVentActionBackend) -> None:
        raise NotImplementedError

    async def async_press(self) -> None:
        backend = self.coordinator.client
        if not isinstance(backend, IVentActionBackend):  # pragma: no cover - entiteta se ne ustvari
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="action_unsupported")
        try:
            await self._async_run(backend)
        except IVentApiClientError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class IVentBeaconButton(_IVentDeviceActionButton):
    """\"Najdi napravo\": enota zapiska (Action Beacon, prek Masterja)."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _key = "beacon"

    async def _async_run(self, backend: IVentActionBackend) -> None:
        await backend.async_beacon(self._device_mac)


class IVentFilterResetButton(_IVentDeviceActionButton):
    """Ponastavi opozorilo za filter (Action FilterCleaned). Pritisnite po čiščenju filtra."""

    _key = "filter_reset"

    async def _async_run(self, backend: IVentActionBackend) -> None:
        await backend.async_filter_cleaned(self._device_mac)
        # stanje opozorila (statusEsp) se spremeni na enoti; osveži podatke
        await self.coordinator.async_request_delayed_refresh()
