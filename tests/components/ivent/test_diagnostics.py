"""Diagnostics: občutljivi podatki (API ključ, ID lokacije, MAC) morajo biti skriti."""
import json

from homeassistant.core import HomeAssistant

from custom_components.ivent.diagnostics import async_get_config_entry_diagnostics

from .conftest import MOCK_API_KEY, MOCK_LOCATION_ID


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, mock_config_entry, mock_api_client):
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    text = json.dumps(diag, default=str)

    assert MOCK_API_KEY not in text
    assert str(MOCK_LOCATION_ID) not in text
    assert diag["entry_data"]["api_key"] == "**REDACTED**"
    assert diag["entry_data"]["location_id"] == "**REDACTED**"
    assert diag["last_update_success"] is True
    assert diag["coordinator_data"]["groups_by_id"]
    for dev in diag["coordinator_data"]["devices_by_mac"].values():
        assert dev["raw"]["mac_address"] == "**REDACTED**"
    # ključi slovarja devices_by_mac so MAC naslovi: ne smejo uhajati
    assert not any(":" in k for k in diag["coordinator_data"]["devices_by_mac"])


async def test_diagnostics_local_mac_redacted(hass: HomeAssistant, mock_config_entry, mock_api_client):
    from custom_components.ivent.diagnostics import TO_REDACT
    assert {"local_mac", "location_id", "api_key"} <= TO_REDACT
