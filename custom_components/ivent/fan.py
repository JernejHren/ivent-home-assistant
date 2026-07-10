"""Podpora za i-Vent ventilatorje (skupine)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ATTR_GROUP_ID, ATTR_DEVICES, API_MODE_WORK_OFF
from .coordinator import IVentCoordinator, IVentGroupData
from .entity import IVentGroupEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi fan entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
             return
        
        new_entities: list[FanEntity] = []

        entry_id = coordinator.config_entry.entry_id

        for group in coordinator.data.groups_by_id.values():
            uid = f"{entry_id}_{group.id}_fan"
            if uid not in added_entities:
                added_entities.add(uid)
                new_entities.append(IVentFan(coordinator, group))
                 
        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class IVentFan(IVentGroupEntity, FanEntity):
    """Predstavlja i-Vent ventilator (logično skupino) kot stikalo za VKLOP/IZKLOP."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = ["Normal", "Bypass"]

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_fan"
        self._attr_translation_key = "fan_main"
        self._update_state()

    def _update_state(self) -> None:
        """Posodobi atribute iz koordinatorjevih podatkov."""
        group = self._group
        if group is None:
            return
        self._attr_extra_state_attributes = {
            ATTR_GROUP_ID: self._group_id,
            ATTR_DEVICES: group.device_macs,
        }

    @property
    def is_on(self) -> bool:
        group = self._group
        actual = group is not None and group.work_mode != API_MODE_WORK_OFF
        return self._get_optimistic_attr("is_on", actual)  # type: ignore[no-any-return]

    @property
    def percentage(self) -> int | None:
        group = self._group
        if not group or group.work_mode == API_MODE_WORK_OFF:
            return 0
        actual = self._speed_to_percentage(group.remote_control_speed)
        return self._get_optimistic_attr("percentage", actual)  # type: ignore[no-any-return]

    @property
    def preset_mode(self) -> str | None:
        group = self._group
        if not group:
            return None
        actual = group.remote_control_work_mode
        return self._get_optimistic_attr("preset_mode", actual)  # type: ignore[no-any-return]

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Vklopi ventilator z uporabo HA 2024+ `percentage` API."""
        if percentage == 0:
            await self.async_turn_off()
            return

        group = self._group
        if group is None:
            return
        speed = (
            group.remote_control_speed
            if percentage is None
            else self._percentage_to_speed(percentage)
        )
        vent_mode = (
            group.remote_control_work_mode if preset_mode is None else preset_mode
        )
        payload = self._build_remote_settings_payload(vent_mode, speed)

        updates: dict[str, Any] = {"is_on": True}
        if preset_mode is not None:
            updates["preset_mode"] = preset_mode
        if percentage is not None:
            updates["percentage"] = percentage

        await self._async_handle_writes(updates, self.async_update_group(payload))

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage.

        Required when advertising SET_SPEED feature; otherwise HA uses the
        base implementation that raises NotImplementedError in a background task.
        """
        if percentage == 0:
            await self.async_turn_off()
            return
        await self.async_turn_on(percentage=percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Izklopi ventilator."""
        payload = self._prepare_payload({"work_mode": API_MODE_WORK_OFF})
        await self._async_handle_write("is_on", False, self.async_update_group(payload))

    @staticmethod
    def _percentage_to_speed(percentage: int | None) -> int:
        if percentage is None or percentage == 0:
            return 1
        if percentage <= 33:
            return 1
        if percentage <= 66:
            return 2
        return 3

    @staticmethod
    def _speed_to_percentage(speed: int) -> int:
        if speed == 2:
            return 66
        if speed == 3:
            return 100
        return 33
