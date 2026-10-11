import pytest
from unittest.mock import AsyncMock, patch
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from custom_components.ivent.const import DOMAIN
from custom_components.ivent.api import IVentApiClientError

async def test_partial_failure_schedules(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that schedule failures preserve previous data instead of breaking the coordinator."""
    # 1. First refresh succeeds during setup
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    # Verify initial state: schedules exist
    coordinator = mock_config_entry.runtime_data.coordinator
    assert len(coordinator.data.raw_schedules) > 0
    assert hass.states.get("fan.dnevna_soba_fan").state == "on"
    
    # 2. Second refresh fails on schedules
    mock_api_client.async_get_schedules.side_effect = IVentApiClientError("Schedules API down")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Verify coordinator preserved previous schedules
    assert len(coordinator.data.raw_schedules) > 0
    assert hass.states.get("fan.dnevna_soba_fan").state == "on"

async def test_critical_failure_info(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that the integration fails to load if info fails."""
    mock_api_client.async_get_info.side_effect = IVentApiClientError("Info API down")
    
    # Setup entry should return False (failed setup) or throw it?
    # If setup throws during task, HA handles it.
    # async_setup_entry calls first_refresh which will raise UpdateFailed.
    # HA catches this and logs it, entry is NOT ready.
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hasattr(mock_config_entry, "runtime_data")
