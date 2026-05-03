"""Podpora za i-Vent stikala."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    API_MODE_SPECIAL_OFF,
    API_MODE_NIGHT1,
    API_MODE_NIGHT2,
    API_MODE_SNOOZE,
    API_MODE_BOOST,
)
from .coordinator import IVentCoordinator, IVentGroupData, IVentDeviceData
from .entity import IVentGroupEntity, IVentDeviceEntity, IVentScheduleEntity
from .api import IVentScheduleItem

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi switch entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return
            
        new_entities: list[SwitchEntity] = []

        entry_id = coordinator.config_entry.entry_id

        # Urniki
        for schedule in coordinator.data.schedules_by_id.values():
            uid = f"{entry_id}_schedule_{schedule['meta']['schedule_id']}"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentScheduleSwitch(coordinator, schedule))

        # Skupine
        for group in coordinator.data.groups_by_id.values():
            uid_led = f"{entry_id}_{group.id}_led"
            if uid_led not in added_entities:
                added_entities.add(uid_led)
                new_entities.append(IVentLedSwitch(coordinator, group))
                
            uid_buzzer = f"{entry_id}_{group.id}_buzzer"
            if uid_buzzer not in added_entities:
                added_entities.add(uid_buzzer)
                new_entities.append(IVentBuzzerSwitch(coordinator, group))

            for api_mode, icon in [("night1", "mdi:weather-night"), ("night2", "mdi:weather-night"), ("snooze", "mdi:alarm-snooze"), ("boost", "mdi:rocket-launch")]:
                uid_special = f"{entry_id}_{group.id}_{api_mode}"
                if uid_special not in added_entities:
                    added_entities.add(uid_special)
                    api_mode_map = {"night1": API_MODE_NIGHT1, "night2": API_MODE_NIGHT2, "snooze": API_MODE_SNOOZE, "boost": API_MODE_BOOST}
                    new_entities.append(IVentSpecialModeSwitch(coordinator, group, api_mode, api_mode_map[api_mode], icon))

        # Naprave
        for device in coordinator.data.devices_by_mac.values():
            uid_rev = f"{device.mac_address}_reverse_flow"
            if uid_rev not in added_entities:
                added_entities.add(uid_rev)
                new_entities.append(IVentReverseFlowSwitch(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


# ---------------------------------------------------------------------------
# Group switches — all use IVentGroupEntity._group property (O(1))
# ---------------------------------------------------------------------------

class IVentSpecialModeSwitch(IVentGroupEntity, SwitchEntity):
    """Generično stikalo za posebne načine delovanja (Boost, Night, Snooze)."""

    def __init__(
        self,
        coordinator: IVentCoordinator,
        group_data: IVentGroupData,
        translation_key: str,
        api_mode: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, group_data)
        self._api_mode = api_mode
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_{api_mode.lower()}"
        self._attr_translation_key = translation_key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        group = self._group
        actual = group is not None and group.special_mode == self._api_mode
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    async def async_turn_on(self, **kwargs: Any) -> None:
        payload = self._prepare_payload({"special_mode": self._api_mode})
        await self._async_handle_write("is_on", True, self.async_update_group(payload))

    async def async_turn_off(self, **kwargs: Any) -> None:
        payload = self._prepare_payload({"special_mode": API_MODE_SPECIAL_OFF})
        await self._async_handle_write("is_on", False, self.async_update_group(payload))


class IVentLedSwitch(IVentGroupEntity, SwitchEntity):
    """Stikalo za LED osvetlitev skupine."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:led-on"

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_led"
        self._attr_translation_key = "led"

    @property
    def is_on(self) -> bool:
        group = self._group
        actual = group is not None and group.led_work_mode != "LedOffMode"
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", True, self.async_update_group({"led_mode": "LedOnMode"}))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", False, self.async_update_group({"led_mode": "LedOffMode"}))


class IVentBuzzerSwitch(IVentGroupEntity, SwitchEntity):
    """Stikalo za zvočni signal skupine."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:volume-high"

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_buzzer"
        self._attr_translation_key = "buzzer"

    @property
    def is_on(self) -> bool:
        group = self._group
        actual = group is not None and group.buzzer_work_mode not in ("BuzzerOffMode", "BuzzerOffWithErrMode")
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", True, self.async_update_group({"buzzer_mode": "BuzzerOnMode"}))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", False, self.async_update_group({"buzzer_mode": "BuzzerOffMode"}))


# ---------------------------------------------------------------------------
# Schedule switch — uses O(1) schedules_by_id lookup
# ---------------------------------------------------------------------------

class IVentScheduleSwitch(IVentScheduleEntity, SwitchEntity):
    """Stikalo za vklop/izklop urnika."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: IVentCoordinator, schedule_data: IVentScheduleItem) -> None:
        super().__init__(coordinator, schedule_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_schedule_{self._schedule_id}"
        self._attr_translation_key = "schedule"

    @property
    def is_on(self) -> bool:
        schedule = self._schedule
        actual = schedule is not None and schedule["header"]["schedule_item_enabled"]
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", True, self.async_update_schedule_enabled(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", False, self.async_update_schedule_enabled(False))


# ---------------------------------------------------------------------------
# Device switch — uses IVentDeviceEntity base (stable MAC-based identity)
# ---------------------------------------------------------------------------

class IVentReverseFlowSwitch(IVentDeviceEntity, SwitchEntity):
    """Stikalo za obratni pretok zraka fizične enote.

    unique_id: {mac_address}_reverse_flow  (stable — MAC never changes)
    """

    _attr_icon = "mdi:swap-horizontal-bold"

    def __init__(self, coordinator: IVentCoordinator, device_data: IVentDeviceData) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_reverse_flow"
        self._attr_translation_key = "reverse_flow"

    @property
    def is_on(self) -> bool:
        device = self._device
        actual = device is not None and device.reverse_flow
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", True, self.async_update_device({"reverse_flow": True}))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_handle_write("is_on", False, self.async_update_device({"reverse_flow": False}))
