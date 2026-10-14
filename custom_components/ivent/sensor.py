"""Podpora za i-Vent senzorje."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MODE, DOMAIN, MODE_CLOUD, MODE_HYBRID, MODE_LOCAL
from .coordinator import IVentConfigEntry, IVentCoordinator, IVentDeviceData, IVentGroupData
from .entity import IVentGroupEntity, IVentDeviceEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IVentConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi senzor entitete iz konfiguracijskega vnosa."""
    coordinator: IVentCoordinator = entry.runtime_data.coordinator

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return
            
        new_entities: list[SensorEntity] = []

        entry_id = coordinator.config_entry.entry_id

        for group in coordinator.data.groups_by_id.values():
            uid1 = f"{entry_id}_{group.id}_work_mode_changed_at"
            if uid1 not in added_entities:
                added_entities.add(uid1)
                new_entities.append(IVentTimestampSensor(coordinator, group, "work_mode_changed_at"))

            uid2 = f"{entry_id}_{group.id}_special_mode_ends_at"
            if uid2 not in added_entities:
                added_entities.add(uid2)
                new_entities.append(IVentTimestampSensor(coordinator, group, "special_mode_ends_at"))

        for device in coordinator.data.devices_by_mac.values():
            uid = f"{device.mac_address}_rssi"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentRssiSensor(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    async_add_entities([IVentConnectionModeSensor(entry)])
    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


# ---------------------------------------------------------------------------
# Servisna naprava "i-Vent System": način povezave
# ---------------------------------------------------------------------------

class IVentConnectionModeSensor(SensorEntity):
    """Kateri način povezave je nastavljen: samo oblak, samo lokalno ali kombinirano.

    Vrednost se spremeni samo z rekonfiguracijo (ta ponovno naloži vnos), zato
    entiteta ne potrebuje koordinatorja in je vedno na voljo.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "connection_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [MODE_CLOUD, MODE_LOCAL, MODE_HYBRID]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: IVentConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connection_mode"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> str:
        mode = self._entry.data.get(CONF_MODE, MODE_CLOUD)
        return mode if mode in self._attr_options else MODE_CLOUD


# ---------------------------------------------------------------------------
# Device (physical unit) sensors
# ---------------------------------------------------------------------------

class IVentRssiSensor(IVentDeviceEntity, SensorEntity):
    """Senzor za moč signala (RSSI) i-Vent naprave.

    unique_id: {mac_address}_rssi  (stable — MAC never changes)
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_rssi"
        self._attr_translation_key = "rssi"

    @property
    def native_value(self) -> int | None:
        device = self._device
        return device.rssi if device else None


# ---------------------------------------------------------------------------
# Group (zone) sensors
# ---------------------------------------------------------------------------

class IVentTimestampSensor(IVentGroupEntity, SensorEntity):
    """Generični senzor za časovne znamke iz API-ja.

    unique_id: {entry_id}_{group_id}_{key}  (stable — group_id is immutable API int)
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: IVentCoordinator,
        group_data: IVentGroupData,
        key: str,
    ) -> None:
        super().__init__(coordinator, group_data)
        self._key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_{key}"
        self._attr_translation_key = key

    @property
    def native_value(self) -> datetime | None:
        group = self._group
        if group is None:
            return None
        return (
            group.work_mode_changed_at
            if self._key == "work_mode_changed_at"
            else group.special_mode_ends_at
        )

