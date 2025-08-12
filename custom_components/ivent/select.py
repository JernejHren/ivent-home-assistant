"""Podpora za i-Vent izbirnike."""
from typing import Any, Dict

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import IVentGroupEntity

# --- Izbirnik za način prezračevanja ---
VENTILATION_MODE_NORMAL = "Normal"
VENTILATION_MODE_BYPASS = "Bypass"
HA_MODE_RECUPERATION = "Rekuperacija"
HA_MODE_BYPASS = "Prezračevanje (Bypass)"
API_TO_HA_MODE_MAP = {VENTILATION_MODE_NORMAL: HA_MODE_RECUPERATION, VENTILATION_MODE_BYPASS: HA_MODE_BYPASS}
HA_TO_API_MODE_MAP = {v: k for k, v in API_TO_HA_MODE_MAP.items()}

# --- Izbirnik za hitrost ---
SPEED_MAP = {"Stopnja 1": 1, "Stopnja 2": 2, "Stopnja 3": 3}
SPEED_MAP_REV = {v: k for k, v in SPEED_MAP.items()}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi select entitete iz konfiguracijskega vnosa."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})

    entities = []
    all_devices = {}

    for group in info_data.get("groups", []):
        if group.get("id") is None: continue
        entities.append(IVentVentilationModeSelect(coordinator, group))
        entities.append(IVentSpeedSelect(coordinator, group))
        for device in group.get("devices", []):
            if device.get("mac_address") and device["mac_address"] not in all_devices:
                all_devices[device["mac_address"]] = (device, group["id"])

    for mac, (device_data, group_id) in all_devices.items():
        entities.append(IVentMoveDeviceSelect(coordinator, device_data, group_id))

    async_add_entities(entities)


class IVentVentilationModeSelect(IVentGroupEntity, SelectEntity):
    """Predstavlja izbirnik načina prezračevanja (Rekuperacija/Bypass)."""
    def __init__(self, coordinator, group_data: Dict[str, Any]):
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_ventilation_mode"
        self._attr_name = "Način prezračevanja"
        self._attr_options = list(HA_TO_API_MODE_MAP.keys())
        self._update_state()

    def _update_state(self):
        api_mode = self._remote_data.get("remote_control_work_mode")
        self._attr_current_option = API_TO_HA_MODE_MAP.get(api_mode)

    async def async_select_option(self, option: str) -> None:
        api_mode = HA_TO_API_MODE_MAP.get(option)
        if not api_mode: return
        payload = self._prepare_payload({"remote_control_work_mode": api_mode})
        await self.coordinator.client.async_modify_group(self._group_id, payload)
        await self.coordinator.async_request_refresh()


class IVentSpeedSelect(IVentGroupEntity, SelectEntity):
    """Predstavlja izbirnik za hitrost ventilatorja."""
    def __init__(self, coordinator, group_data: Dict[str, Any]):
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_speed"
        self._attr_name = "Hitrost"
        self._attr_icon = "mdi:fan-speed-2"
        self._attr_options = list(SPEED_MAP.keys())
        self._update_state()

    def _update_state(self):
        speed = self._remote_data.get("remote_control_speed")
        self._attr_current_option = SPEED_MAP_REV.get(speed)

    async def async_select_option(self, option: str) -> None:
        speed = SPEED_MAP.get(option)
        if speed is None: return
        payload = self._prepare_payload({"remote_control_speed": speed})
        await self.coordinator.client.async_modify_group(self._group_id, payload)
        await self.coordinator.async_request_refresh()


class IVentMoveDeviceSelect(CoordinatorEntity, SelectEntity):
    """Predstavlja izbirnik za premik enote v drugo skupino."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_data: Dict[str, Any], current_group_id: int):
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._current_group_id = current_group_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._device_mac)})
        self._attr_unique_id = f"{self._device_mac}_move_to_group"
        self._attr_name = "Premakni v skupino"
        self._attr_icon = "mdi:arrow-right-bold-box-outline"
        self._update_options()

    def _update_options(self):
        info_data = self.coordinator.data.get("info", {})
        self._groups_map = {g["name"]: g["id"] for g in info_data.get("groups", []) if g.get("name")}
        self._attr_options = list(self._groups_map.keys())
        for name, group_id in self._groups_map.items():
            if group_id == self._current_group_id:
                self._attr_current_option = name
                break
    @callback
    def _handle_coordinator_update(self) -> None:
        info_data = self.coordinator.data.get("info", {})
        found = False
        for group in info_data.get("groups", []):
            for device in group.get("devices", []):
                if device.get("mac_address") == self._device_mac:
                    self._current_group_id = group["id"]
                    found = True
                    break
            if found: break
        self._update_options()
        self.async_write_ha_state()
    async def async_select_option(self, option: str) -> None:
        target_group_id = self._groups_map.get(option)
        if not target_group_id: return
        await self.coordinator.client.async_modify_device(self._device_mac, {"group_id": target_group_id})
        await self.coordinator.async_request_refresh()
