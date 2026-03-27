"""Podpora za i-Vent binarne senzorje."""
from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Nastavi binary_sensor entitete iz konfiguracijskega vnosa."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    all_devices = {}

    for group in coordinator.data.get("info", {}).get("groups", []):
        for device in group.get("devices", []):
            if device["mac_address"] not in all_devices:
                all_devices[device["mac_address"]] = device
                entities.append(IVentProblemSensor(coordinator, device))
                entities.append(IVentAliveSensor(coordinator, device))

    async_add_entities(entities)


class IVentProblemSensor(CoordinatorEntity, BinarySensorEntity):
    """Predstavlja senzor težav za i-Vent enoto (filter, napake)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: DataUpdateCoordinator, device_data: Dict[str, Any]):
        """Inicializira senzor."""
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._device_data = device_data

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
        )
        self._attr_unique_id = f"{self._device_mac}_problem"
        self._attr_name = "Stanje naprave"

    @property
    def is_on(self) -> bool:
        """Vrne True, če obstaja težava (status ni 0)."""
        return self._device_data.get("status_esp", 0) != 0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Vrne kodo stanja kot dodaten atribut."""
        return {"status_code": self._device_data.get("status_esp")}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje."""
        updated = False
        for group in self.coordinator.data.get("info", {}).get("groups", []):
            for device in group.get("devices", []):
                if device["mac_address"] == self._device_mac:
                    self._device_data = device
                    updated = True
                    break
            if updated:
                break
        self.async_write_ha_state()


class IVentAliveSensor(CoordinatorEntity, BinarySensorEntity):
    """Predstavlja senzor povezljivosti za i-Vent enoto."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: DataUpdateCoordinator, device_data: Dict[str, Any]):
        """Inicializira senzor."""
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._device_data = device_data

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
        )
        self._attr_unique_id = f"{self._device_mac}_alive"
        self._attr_name = "Povezljivost"

    @property
    def is_on(self) -> bool:
        """Vrne True, če je naprava dosegljiva."""
        return self._device_data.get("alive", False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje."""
        updated = False
        for group in self.coordinator.data.get("info", {}).get("groups", []):
            for device in group.get("devices", []):
                if device["mac_address"] == self._device_mac:
                    self._device_data = device
                    updated = True
                    break
            if updated:
                break
        self.async_write_ha_state()
