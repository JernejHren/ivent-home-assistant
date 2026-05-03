"""Podpora za i-Vent binarne senzorje."""
from __future__ import annotations
from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IVentCoordinator, IVentDeviceData
from .entity import IVentDeviceEntity

PARALLEL_UPDATES = 1

# Preslikava bitnih mask status_code v posamezne senzorje
# Ključ: bitna maska
# Vrednost: metapodatki za senzor
STATUS_FLAGS: Dict[int, Dict[str, Any]] = {
    1024: {
        "key": "filter",
        "device_class": BinarySensorDeviceClass.PROBLEM,
        "category": EntityCategory.DIAGNOSTIC,
    },
    # Tukaj lahko dodamo nove maske (npr. 2048: {"key": "hardware_error", ...})
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi binary_sensor entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return

        entity_registry = er.async_get(hass)
        existing_entries = er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        )
        existing_unique_ids = {ent.unique_id for ent in existing_entries}

        new_entities: list[BinarySensorEntity] = []

        for device in coordinator.data.devices_by_mac.values():
            # 1. Osnovni senzor težav (povzetek vseh napak)
            uid_prob = f"{entry.entry_id}_{device.mac_address}_problem"
            if uid_prob not in existing_unique_ids:
                new_entities.append(IVentProblemSensor(coordinator, device))

            # 2. Specifični diagnostični senzorji iz bitne maske
            for mask, config in STATUS_FLAGS.items():
                uid_diag = f"{entry.entry_id}_{device.mac_address}_{config['key']}"
                if uid_diag not in existing_unique_ids:
                    new_entities.append(
                        IVentDiagnosticSensor(coordinator, device, mask, config)
                    )

            # 3. Senzor povezljivosti
            uid_alive = f"{entry.entry_id}_{device.mac_address}_alive"
            if uid_alive not in existing_unique_ids:
                new_entities.append(IVentAliveSensor(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class IVentProblemSensor(IVentDeviceEntity, BinarySensorEntity):
    """Predstavlja splošni senzor težav (True, če je kateri koli bit v statusu nastavljen)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._device_mac}_problem"
        self._attr_translation_key = "problem"

    @property
    def is_on(self) -> bool:
        device = self._device
        # status_esp != 0 pomeni, da je vsaj ena napaka/opozorilo aktivno
        return device is not None and device.status_esp != 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device
        return {"status_code": device.status_esp if device else None}


class IVentDiagnosticSensor(IVentDeviceEntity, BinarySensorEntity):
    """Senzor za specifično napako iz bitne maske status_code."""

    def __init__(
        self,
        coordinator: IVentCoordinator,
        device_data: IVentDeviceData,
        mask: int,
        config: Dict[str, Any],
    ) -> None:
        super().__init__(coordinator, device_data)
        self._mask = mask
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._device_mac}_{config['key']}"
        self._attr_translation_key = config["key"]
        self._attr_device_class = config["device_class"]
        self._attr_entity_category = config["category"]

    @property
    def is_on(self) -> bool:
        device = self._device
        if device is None:
            return False
        flags = (
            device.diagnostic_flags
            if device.diagnostic_flags is not None
            else device.status_esp
        )
        return bool(flags & self._mask)


class IVentAliveSensor(IVentDeviceEntity, BinarySensorEntity):
    """Senzor povezljivosti."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._device_mac}_alive"
        self._attr_translation_key = "alive"

    @property
    def is_on(self) -> bool:
        device = self._device
        return device is not None and device.alive

