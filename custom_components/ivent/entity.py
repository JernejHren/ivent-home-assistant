"""Osnovni razredi za i-Vent entitete."""
from typing import Any, Dict

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

class IVentGroupEntity(CoordinatorEntity):
    """Osnovni razred za entitete, ki so vezane na skupino (group)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, group_data: Dict[str, Any]):
        """Inicializira entiteto skupine."""
        super().__init__(coordinator)
        self._group_id = group_data["id"]
        self._group_data = group_data
        self._remote_data = group_data.get("remote", {})
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.config_entry.entry_id}_{self._group_id}")},
            "name": group_data.get("name"),
            "manufacturer": "i-Vent",
            "model": "Ventilation Group",
            "via_device": (DOMAIN, coordinator.config_entry.entry_id),
        }

    def _prepare_payload(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Pripravi veljaven payload za pošiljanje na API."""
        # Vedno začnemo s trenutnim stanjem, da ohranimo vse nastavitve
        payload = self._remote_data.copy()
        
        # Uveljavimo želene spremembe
        payload.update(changes)
        
        # API zahteva celoten objekt, zato ga sestavimo iz posodobljenih podatkov
        # To preprečuje napake, če vmes manjka kateri od ključev
        final_payload = {
            "work_mode": payload.get("work_mode", "IVentRecuperation1"),
            "special_mode": payload.get("special_mode", "IVentSpecialOff"),
            "remote_control_speed": payload.get("remote_control_speed", 1),
            "remote_control_work_mode": payload.get("remote_control_work_mode", "Normal"),
            "bypass_rotation": payload.get("bypass_rotation", "BypassForward"),
        }
        
        return {"remote_work_mode": final_payload}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje entitete, ko koordinator prejme nove podatke."""
        info_data = self.coordinator.data.get("info", {})
        for group in info_data.get("groups", []):
            if group["id"] == self._group_id:
                self._group_data = group
                self._remote_data = group.get("remote", {})
                # Poskrbimo, da se posodobi tudi ime naprave
                if self._attr_device_info:
                    self._attr_device_info["name"] = group.get("name")
                self._update_state()
                self.async_write_ha_state()
                return # Prekinemo, ko najdemo našo skupino
        
        # Če skupina ne obstaja več (je bila izbrisana), se entiteta ne bo posodobila
        # Home Assistant bo sam poskrbel za opozorilo o neobstoječi entiteti

    def _update_state(self):
        """Metoda, ki jo podrazredi implementirajo za posodobitev svojega stanja."""
        # To metodo prepišejo podrazredi, če potrebujejo dodatno logiko
        pass
