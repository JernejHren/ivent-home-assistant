"""Podpora za i-Vent ventilatorje (skupine)."""
from typing import Any, Dict

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ATTR_GROUP_ID,
    ATTR_DEVICES,
    API_MODE_WORK_OFF,
)
from .entity import IVentGroupEntity

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi fan entitete iz konfiguracijskega vnosa."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    info_data = coordinator.data.get("info", {})
    
    async_add_entities(
        IVentFan(coordinator, group)
        for group in info_data.get("groups", []) if group.get("id") is not None
    )


class IVentFan(IVentGroupEntity, FanEntity):
    """Predstavlja i-Vent ventilator (logično skupino) kot stikalo za VKLOP/IZKLOP."""

    _attr_supported_features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(self, coordinator, group_data: Dict[str, Any]):
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_fan"
        self._attr_name = "Ventilator"
        self._update_state()

    def _prepare_fan_payload(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Lokalna funkcija za pripravo payload-a samo za ventilator."""
        payload = self._remote_data.copy()
        payload.update(changes)
        
        final_payload = {
            "work_mode": payload.get("work_mode", "IVentRecuperation1"),
            "special_mode": payload.get("special_mode", "IVentSpecialOff"),
            "remote_control_speed": payload.get("remote_control_speed", 1),
            "remote_control_work_mode": payload.get("remote_control_work_mode", "Normal"),
            "bypass_rotation": payload.get("bypass_rotation", "BypassForward"),
        }
        
        return {"remote_work_mode": final_payload}

    def _update_state(self):
        """Posodobi interno stanje na podlagi novih podatkov."""
        self._work_mode = self._remote_data.get("work_mode")
        devices = self._group_data.get("devices", [])
        self._attr_extra_state_attributes = {
            ATTR_GROUP_ID: self._group_id,
            ATTR_DEVICES: [d.get("mac_address") for d in devices],
        }

    @property
    def is_on(self) -> bool:
        """Vrne True, če je ventilator vklopljen."""
        return self._work_mode != API_MODE_WORK_OFF

    async def async_turn_on(self, speed_percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        """Vklopi ventilator."""
        try:
            speed = self._remote_data.get("remote_control_speed", 1) if speed_percentage is None else self._percentage_to_speed(speed_percentage)
            vent_mode = self._remote_data.get("remote_control_work_mode", "Normal") if preset_mode is None else preset_mode
            vent_mode_str = "Recuperation" if vent_mode == "Normal" else "Bypass"
            new_work_mode = f"IVent{vent_mode_str}{speed}"

            payload = self._prepare_fan_payload({"work_mode": new_work_mode})
            await self.coordinator.client.async_modify_group(self._group_id, payload)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Error turning on fan: {err}")
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Izklopi ventilator."""
        try:
            payload = self._prepare_fan_payload({"work_mode": API_MODE_WORK_OFF})
            await self.coordinator.client.async_modify_group(self._group_id, payload)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Error turning off fan: {err}")
            raise

    def _percentage_to_speed(self, percentage: int | None) -> int:
        """Pretvori odstotek hitrosti v stopnjo (1, 2, 3)."""
        if percentage is None:
            return 1
        if percentage <= 33:
            return 1
        elif percentage <= 66:
            return 2
        else:
            return 3