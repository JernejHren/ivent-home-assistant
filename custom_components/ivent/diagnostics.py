from dataclasses import asdict
from typing import Any, Dict

from homeassistant.core import HomeAssistant

from .coordinator import IVentConfigEntry
from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

# Polja, ki vsebujejo osebne/občutljive podatke
# location_id je v lokalnem načinu edina poverilnica protokola
TO_REDACT = {"api_key", "mac_address", "Authorization", "location_id", "local_mac"}


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

    # MAC naslovi so tudi ključi v devices_by_mac in vrednosti v all_device_macs:
    # zamenjaj jih s stabilnimi oznakami (device_1, ...), da se naprave še vedno ločijo.
    macs = list(result.get("devices_by_mac", {}))
    alias = {mac: f"device_{i}" for i, mac in enumerate(macs, start=1)}
    devices = {}
    for mac, dev in result.get("devices_by_mac", {}).items():
        if "raw" in dev:
            dev["raw"]["mac_address"] = "**REDACTED**"
        devices[alias[mac]] = dev
    result["devices_by_mac"] = devices
    if "all_device_macs" in result:
        result["all_device_macs"] = [alias.get(m, "**REDACTED**") for m in result["all_device_macs"]]

    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IVentConfigEntry
) -> Dict[str, Any]:
    """Vrne diagnostične podatke za konfiguracijski vnos."""
    coordinator = entry.runtime_data.coordinator

    # Redaktiraj API ključ iz entry.data
    safe_entry_data = async_redact_data(dict(entry.data), TO_REDACT)

    return {
        "entry_data": safe_entry_data,
        "coordinator_data": _redact_coordinator_data(coordinator.data or {}),
        "last_update_success": coordinator.last_update_success,
    }
