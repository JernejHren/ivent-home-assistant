"""Podpora za i-Vent stikala."""
import copy
from typing import Any, Dict

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, 
    API_MODE_SPECIAL_OFF, 
    API_MODE_NIGHT, 
    API_MODE_SNOOZE, 
    API_MODE_BOOST
)
from .entity import IVentGroupEntity

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi switch entitete iz konfiguracijskega vnosa."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})
    schedules_data = coordinator.data.get("schedules", [])

    entities = []
    all_devices = {}
    
    location_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}
    for schedule_group in schedules_data:
        for schedule in schedule_group.get("schedules", []):
             entities.append(IVentScheduleSwitch(coordinator, schedule, schedule_group, location_device_info))

    for group in info_data.get("groups", []):
        if group.get("id") is None: continue
        entities.append(IVentLedSwitch(coordinator, group))
        entities.append(IVentBuzzerSwitch(coordinator, group))
        entities.append(IVentSpecialModeSwitch(coordinator, group, "Nočni način", API_MODE_NIGHT, "mdi:weather-night"))
        entities.append(IVentSpecialModeSwitch(coordinator, group, "Dremež", API_MODE_SNOOZE, "mdi:timer-sand"))
        entities.append(IVentSpecialModeSwitch(coordinator, group, "Boost", API_MODE_BOOST, "mdi:fan-plus"))
        
        for device in group.get("devices", []):
            if device.get("mac_address") and device["mac_address"] not in all_devices:
                all_devices[device["mac_address"]] = device
                entities.append(IVentReverseFlowSwitch(coordinator, device))

    async_add_entities(entities)


class IVentSpecialModeSwitch(IVentGroupEntity, SwitchEntity):
    """Generično stikalo za posebne načine delovanja (Boost, Night, Snooze)."""
    
    def __init__(self, coordinator, group_data: Dict[str, Any], name: str, api_mode: str, icon: str):
        super().__init__(coordinator, group_data)
        self._api_mode = api_mode
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_{api_mode.lower()}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return self._remote_data.get("special_mode") == self._api_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Vklopi poseben način."""
        payload = self._prepare_payload({"special_mode": self._api_mode})
        await self.coordinator.client.async_modify_group(self._group_id, payload)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Izklopi poseben način."""
        payload = self._prepare_payload({"special_mode": API_MODE_SPECIAL_OFF})
        await self.coordinator.client.async_modify_group(self._group_id, payload)
        await self.coordinator.async_request_refresh()


class IVentLedSwitch(IVentGroupEntity, SwitchEntity):
    def __init__(self, coordinator, group_data: Dict[str, Any]):
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_led"
        self._attr_name = "LED lučke"
        self._attr_icon = "mdi:led-on"
    @property
    def is_on(self) -> bool:
        return self._group_data.get("led_work_mode") != "LedOffMode"
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_group(self._group_id, {"led_mode": "LedOnMode"})
        await self.coordinator.async_request_refresh()
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_group(self._group_id, {"led_mode": "LedOffMode"})
        await self.coordinator.async_request_refresh()

# --- Ostali razredi ostanejo večinoma nespremenjeni ---
class IVentScheduleSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    def __init__(self, coordinator, schedule_data: Dict[str, Any], schedule_group: Dict[str, Any], device_info: Dict):
        super().__init__(coordinator)
        self._schedule_id = schedule_data["meta"]["schedule_id"]
        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_schedule_{self._schedule_id}"
        days = self._parse_days(schedule_data["repeat"]["days"])
        time = f"{schedule_data['repeat']['hour']:02}:{schedule_data['repeat']['minute']:02}"
        self._attr_name = f"Urnik: {schedule_group['name']} ({days} ob {time})"
        self._update_state(schedule_data)
    def _parse_days(self, day_mask: int) -> str:
        days = ["Pon", "Tor", "Sre", "Čet", "Pet", "Sob", "Ned"]
        active_days = [days[i] for i in range(7) if (day_mask >> i) & 1]
        if len(active_days) == 7: return "Vsak dan"
        if not active_days: return "Nikoli"
        return ", ".join(active_days)
    @callback
    def _handle_coordinator_update(self) -> None:
        schedules_data = self.coordinator.data.get("schedules", [])
        found = False
        for schedule_group in schedules_data:
            for schedule in schedule_group.get("schedules", []):
                if schedule["meta"]["schedule_id"] == self._schedule_id:
                    self._update_state(schedule)
                    self.async_write_ha_state()
                    found = True
                    break
            if found: break
    def _update_state(self, schedule_data: Dict[str, Any]):
        self._attr_is_on = schedule_data["header"]["schedule_item_enabled"]
    async def _set_schedule_state(self, enabled: bool):
        current_schedules = copy.deepcopy(self.coordinator.data.get("schedules", []))
        found = False
        for schedule_group in current_schedules:
            for schedule in schedule_group.get("schedules", []):
                if schedule["meta"]["schedule_id"] == self._schedule_id:
                    schedule["header"]["schedule_item_enabled"] = enabled
                    found = True
                    break
            if found: break
        if found:
            await self.coordinator.client.async_modify_schedules(current_schedules)
            await self.coordinator.async_request_refresh()
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_schedule_state(True)
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_schedule_state(False)

class IVentBuzzerSwitch(IVentGroupEntity, SwitchEntity):
    def __init__(self, coordinator, group_data: Dict[str, Any]):
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_buzzer"
        self._attr_name = "Zvočni signali"
        self._attr_icon = "mdi:volume-high"
    @property
    def is_on(self) -> bool:
        return self._group_data.get("buzzer_work_mode") not in ["BuzzerOffMode", "BuzzerOffWithErrMode"]
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_group(self._group_id, {"buzzer_mode": "BuzzerOnMode"})
        await self.coordinator.async_request_refresh()
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_group(self._group_id, {"buzzer_mode": "BuzzerOffMode"})
        await self.coordinator.async_request_refresh()

class IVentReverseFlowSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, device_data: Dict[str, Any]):
        super().__init__(coordinator)
        self._device_mac = device_data["mac_address"]
        self._device_data = device_data
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._device_mac)})
        self._attr_unique_id = f"{self._device_mac}_reverse_flow"
        self._attr_name = "Obratni tok"
        self._attr_icon = "mdi:swap-horizontal-bold"
    @property
    def is_on(self) -> bool:
        return self._device_data.get("reverse_flow", False)
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_device(self._device_mac, {"reverse_flow": True})
        await self.coordinator.async_request_refresh()
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_modify_device(self._device_mac, {"reverse_flow": False})
        await self.coordinator.async_request_refresh()
    @callback
    def _handle_coordinator_update(self) -> None:
        info_data = self.coordinator.data.get("info", {})
        updated = False
        for group in info_data.get("groups", []):
            for device in group.get("devices", []):
                if device.get("mac_address") == self._device_mac:
                    self._device_data = device
                    updated = True
                    break
            if updated: break
        self.async_write_ha_state()
