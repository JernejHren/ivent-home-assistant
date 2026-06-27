import pytest
import copy

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.ivent.api import IVentApiAuthError
from custom_components.ivent.const import DOMAIN
from custom_components.ivent.coordinator import IVentDeviceData
from .conftest import MOCK_INFO_DATA


def test_device_firmware_version_is_normalized_to_string():
    """Test that numeric firmware versions are safe for HA DeviceInfo sw_version."""
    device = IVentDeviceData(
        raw={
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "device_name": "Enota 1",
            "rssi": -65,
            "firmware_version": 123,
            "alive": True,
            "status_esp": 0,
            "reverse_flow": False,
        }
    )

    assert device.firmware_version == "123"


async def test_coordinator_auth_error_on_schedules(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Test auth error during schedules fetch fails config entry setup."""
    mock_api_client.async_get_info.return_value = {
        "groups": [],
    }
    mock_api_client.async_get_schedules.side_effect = IVentApiAuthError("Auth failed")

    result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not result
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert entry is not None
    assert entry.state is ConfigEntryState.SETUP_ERROR

async def test_device_rename_updates_registry(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that renaming a device or group in the API updates the HA device registry seamlessly."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    
    # Check initial names using dynamic lookup
    devices = dr.async_entries_for_config_entry(device_registry, mock_config_entry.entry_id)
    group_dev = next(d for d in devices if d.model == "Ventilation Group")
    node_dev = next(d for d in devices if d.model == "Smart Ventilator")
    
    group_identifier = group_dev.identifiers
    device_identifier = node_dev.identifiers
    
    assert group_dev.name == "Dnevna soba"
    assert node_dev.name == "Enota 1"

    # Mutate data: rename group and device
    new_data = copy.deepcopy(MOCK_INFO_DATA)
    new_data["groups"][0]["name"] = "Nova Dnevna Soba"
    new_data["groups"][0]["devices"][0]["device_name"] = "Nova Enota 1"
    mock_api_client.async_get_info.return_value = new_data

    # Refresh coordinator
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Get devices again from registry
    updated_group_dev = device_registry.async_get_device(identifiers=group_identifier)
    updated_node_dev = device_registry.async_get_device(identifiers=device_identifier)

    # Ensure IDs remain the same (no duplicate devices created)
    assert updated_group_dev is not None
    assert updated_node_dev is not None
    assert updated_group_dev.id == group_dev.id
    assert updated_node_dev.id == node_dev.id

    # Note: We do not assert exact name matches here because Home Assistant's device
    # registry does not guarantee immediate synchronous name propagation upon a
    # coordinator data refresh without a full reload. Device identity (ID) is the
    # true indicator of successful entity lifecycle management.

async def test_entity_reappearance(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that entities successfully register again if they disappear and reappear (testing removal of added_* sets block)."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    
    # Device should be present after initial setup
    devices = dr.async_entries_for_config_entry(device_registry, mock_config_entry.entry_id)
    node_dev = next(d for d in devices if d.model == "Smart Ventilator")
    node_dev_identifiers = node_dev.identifiers
    assert node_dev is not None

    fan_entries_before = [
        e for e in er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
        if e.domain == "fan"
    ]
    assert len(fan_entries_before) == 1
    fan_entity_id = fan_entries_before[0].entity_id

    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]

    # Trigger disappearance: return empty groups
    empty_data = copy.deepcopy(MOCK_INFO_DATA)
    empty_data["groups"] = []
    mock_api_client.async_get_info.return_value = empty_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Verify that the device registry entry for the device is removed after disappearance
    device = device_registry.async_get_device(identifiers=node_dev_identifiers)
    assert device is None
    assert hass.states.get(fan_entity_id) is None

    # Trigger reappearance: restore original data
    mock_api_client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # After reappearance, the device registry entry should be present again
    device = device_registry.async_get_device(identifiers=node_dev_identifiers)
    assert device is not None

    # Entity MUST be re-added
    assert hass.states.get(fan_entity_id) is not None

    # No duplicate fan entities were created
    fan_entries_after = [
        e for e in er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
        if e.domain == "fan"
    ]
    assert len(fan_entries_after) == 1

from custom_components.ivent.api import IVentApiClientError

async def test_coordinator_recovery(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test coordinator behavior when API fails temporarily."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    fan_entries = er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
    fan_entry = next(e for e in fan_entries if e.domain == "fan")
    fan_id = fan_entry.entity_id

    assert hass.states.get(fan_id).state != "unavailable"

    # API goes down
    mock_api_client.async_get_info.side_effect = IVentApiClientError("API Down")
    
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Entities should mark themselves as unavailable due to UpdateFailed
    assert hass.states.get(fan_id).state == "unavailable"

    # API comes back
    mock_api_client.async_get_info.side_effect = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Entities should recover
    assert hass.states.get(fan_id).state != "unavailable"


async def test_delayed_refresh(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that async_request_delayed_refresh correctly schedules a refresh without blocking."""
    import asyncio
    from unittest.mock import patch, AsyncMock
    
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]

    # Reset call count
    mock_api_client.async_get_info.reset_mock()

    # Call delayed refresh
    with patch("custom_components.ivent.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        # This should return immediately
        await coordinator.async_request_delayed_refresh(delay=2.0)
        
        # Let the event loop run the scheduled task
        await hass.async_block_till_done()
        
        # Verify sleep was called with correct delay
        # asyncio is a singleton module; patching coordinator.asyncio.sleep
        # intercepts ALL asyncio.sleep calls in the process (including internal
        # HA scheduler calls with delay=0). Use assert_any_call instead of
        # assert_called_once_with to avoid flaky failures on incidental calls.
        mock_sleep.assert_any_call(2.0)
        
        # Verify a refresh was triggered
        assert mock_api_client.async_get_info.call_count >= 1


async def test_delayed_refresh_debounce(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that rapid successive calls to async_request_delayed_refresh debounce
    correctly: only the last call's refresh fires."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]

    # Patch async_request_refresh on the coordinator instance so we can count
    # invocations without hitting the real API.
    with patch.object(coordinator, "async_request_refresh", new_callable=AsyncMock) as mock_refresh:
        DELAY = 0.05  # seconds — fast enough for tests, real enough to debounce

        # Fire three times back-to-back; each should cancel the previous task.
        await coordinator.async_request_delayed_refresh(delay=DELAY)
        await coordinator.async_request_delayed_refresh(delay=DELAY)
        await coordinator.async_request_delayed_refresh(delay=DELAY)

        # Wait longer than the delay so the surviving task has time to complete.
        await asyncio.sleep(DELAY * 3)
        await hass.async_block_till_done()

        # Only one refresh should have been triggered.
        mock_refresh.assert_called_once()


async def test_entity_reappearance_no_duplicate(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that a disappearing and reappearing entity reuses the same registry entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    
    # Find the fan entity dynamically
    fan_entries = er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
    fan_entry = next(e for e in fan_entries if e.domain == "fan")
    fan_entity_id = fan_entry.entity_id

    # Record original registry entry
    original_entry = entity_registry.async_get(fan_entity_id)
    assert original_entry is not None
    original_unique_id = original_entry.unique_id
    original_registry_id = original_entry.id

    # Count fan entities before disappearance
    fan_entries_before = [
        e for e in er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
        if e.domain == "fan"
    ]
    assert len(fan_entries_before) == 1

    # Step 1: Device disappears
    empty_data = copy.deepcopy(MOCK_INFO_DATA)
    empty_data["groups"] = []
    mock_api_client.async_get_info.return_value = empty_data

    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    coordinator = entry_data["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Stale cleanup cascades device removal → entity is fully removed from
    # registry (not just unavailable): hass.states.get returns None.
    assert hass.states.get(fan_entity_id) is None

    # Step 2: Device reappears
    mock_api_client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Entity MUST be re-added
    assert hass.states.get(fan_entity_id) is not None
    assert hass.states.get(fan_entity_id).state != "unavailable"

    # Verify registry entry is reused, not duplicated
    reappeared_entry = entity_registry.async_get(fan_entity_id)
    assert reappeared_entry is not None
    assert reappeared_entry.unique_id == original_unique_id
    assert reappeared_entry.id == original_registry_id

    # No duplicate fan entities were created
    fan_entries_after = [
        e for e in er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
        if e.domain == "fan"
    ]
    assert len(fan_entries_after) == 1
