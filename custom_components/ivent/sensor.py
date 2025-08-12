"""Podpora za i-Vent senzorje."""
from datetime import datetime, timezone
from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
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
    """Nastavi senzor entitete iz konfiguracijskega vnosa."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})

    entities = []
    all_devices = {}

    for group in info_data.get("groups", []):
        group_device_info = {"identifiers": {(DOMAIN, f"{entry.entry_id}_{group['id']}")}}
        entities.append(IVentTimestampSensor(coordinator, group, "Zadnja sprememba načina", "work_mode_changed_at", group_device_info))
        entities.append(IVentTimestampSensor(coordinator, group, "Konec posebnega načina", "special_mode_ends_at", group_device_info))

        for device in group.get("devices", []):
            if device["mac_address"] not in all_devices:
                all_devices[device["mac_address"]] = device
                entities.append(IVentRssiSensor(coordinator, device))

    async_add_entities(entities)


class IVentBaseDeviceSensor(CoordinatorEntity, SensorEntity):
    """Osnovni razred za senzorje, vezane na fizično enoto."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, device_data: Dict[str, Any]):
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._device_data = device_data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
            name=device_data["device_name"],
            manufacturer="i-Vent", model="Smart Ventilator",
            sw_version=device_data.get("firmware_version"),
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        info_data = self.coordinator.data.get("info", {})
        updated = False
        for group in info_data.get("groups", []):
            for device in group.get("devices", []):
                if device["mac_address"] == self._device_mac:
                    self._device_data = device
                    updated = True
                    break
            if updated: break
        self.async_write_ha_state()


class IVentRssiSensor(IVentBaseDeviceSensor):
    """Predstavlja senzor za moč signala (RSSI) i-Vent naprave."""
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: DataUpdateCoordinator, device_data: Dict[str, Any]):
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_rssi"
        self._attr_name = "Moč signala"

    @property
    def native_value(self) -> int | None:
        return self._device_data.get("rssi")


class IVentTimestampSensor(CoordinatorEntity, SensorEntity):
    """Generični senzor za časovne znamke iz API-ja."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DataUpdateCoordinator, group_data: Dict[str, Any], name: str, key: str, device_info: Dict):
        super().__init__(coordinator)
        self._group_id = group_data["id"]
        self._key = key
        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_{key}"
        self._attr_name = name
        self._update_state(group_data)

    @callback
    def _handle_coordinator_update(self) -> None:
        info_data = self.coordinator.data.get("info", {})
        for group in info_data.get("groups", []):
            if group["id"] == self._group_id:
                self._update_state(group)
                self.async_write_ha_state()
                break

    def _update_state(self, data: Dict[str, Any]):
        timestamp = data.get("remote", {}).get(self._key)
        if timestamp and timestamp > 0:
            self._attr_native_value = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            self._attr_native_value = None
