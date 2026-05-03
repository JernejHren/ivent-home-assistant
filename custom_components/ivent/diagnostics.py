from dataclasses import asdict
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

# Polja, ki vsebujejo osebne/občutljive podatke
TO_REDACT = {"api_key", "mac_address", "Authorization"}


def _redact_coordinator_data(data: Any) -> Dict[str, Any]:
    """Rekurzivno redaktira občutljive podatke iz coordinator.data."""
    if not data:
        return {}

    result = asdict(data)

    # Redaktiraj MAC naslove iz naprav v vseh skupinah
    for group in result.get("groups_by_id", {}).values():
        raw_group = group.get("raw", {})
        for device in raw_group.get("devices", []):
            if "mac_address" in device:
                device["mac_address"] = "**REDACTED**"

    # Redaktiraj MAC naslove iz zbirke devices_by_mac
    for mac in result.get("devices_by_mac", {}):
        if "raw" in result["devices_by_mac"][mac]:
            result["devices_by_mac"][mac]["raw"]["mac_address"] = "**REDACTED**"

    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Vrne diagnostične podatke za konfiguracijski vnos."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Redaktiraj API ključ iz entry.data
    safe_entry_data = async_redact_data(dict(entry.data), TO_REDACT)

    return {
        "entry_data": safe_entry_data,
        "coordinator_data": _redact_coordinator_data(coordinator.data or {}),
        "last_update_success": coordinator.last_update_success,
    }
