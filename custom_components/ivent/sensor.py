"""Podpora za i-Vent senzorje."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IVentCoordinator, IVentDeviceData, IVentGroupData
from .entity import IVentGroupEntity, IVentDeviceEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi senzor entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

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

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


# ---------------------------------------------------------------------------
# Device (physical unit) sensors
# ---------------------------------------------------------------------------

class IVentRssiSensor(IVentDeviceEntity, SensorEntity):
    """Senzor za moč signala (RSSI) i-Vent naprave.

    unique_id: {mac_address}_rssi  (stable — MAC never changes)
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
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

