# tests/components/ivent/test_init.py
from unittest.mock import AsyncMock, patch
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from custom_components.ivent.const import DOMAIN

async def test_setup_entry(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test setup of the config entry."""
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.coordinator is not None

async def test_unload_entry(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test unloading of the config entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "create_group")

async def test_services_registered(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that custom services are registered upon setup."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "create_group")
    assert hass.services.has_service(DOMAIN, "delete_group")
    assert hass.services.has_service(DOMAIN, "rename_group")
    assert hass.services.has_service(DOMAIN, "rename_device")
    assert hass.services.has_service(DOMAIN, "move_device_to_group")

async def test_service_create_group(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test create_group service call."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "create_group", {"name": "Test Room"}, blocking=True
    )
    mock_api_client.async_create_group.assert_called_once_with("Test Room")

async def test_service_delete_group(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test delete_group service call."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "delete_group", {"group_id": 123}, blocking=True
    )
    mock_api_client.async_modify_group.assert_called_with(123, {"delete": True})

async def test_service_rename_group(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test rename_group service call."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "rename_group", {"group_id": 1, "new_name": "New Name"}, blocking=True
    )
    mock_api_client.async_modify_group.assert_called_with(1, {"name": "New Name"})

async def test_service_rename_device(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test rename_device service call."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "rename_device", {"device_mac": "AA:BB", "new_name": "New Name"}, blocking=True
    )
    mock_api_client.async_modify_device.assert_called_with("AA:BB", {"name": "New Name"})

async def test_service_move_device_to_group(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test move_device_to_group service call."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN, "move_device_to_group", {"device_mac": "AA:BB", "group_id": 2}, blocking=True
    )
    mock_api_client.async_modify_device.assert_called_with("AA:BB", {"group_id": 2})

async def test_services_removed_on_unload(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that customer services are removed when unloaded."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "create_group")
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "create_group")

async def test_multiple_entries_service_lifecycle(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that services remain active if another entry is still loaded."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Setup entry A
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    
    # Setup entry B
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "test-b", "location_id": "loc-b"},
        unique_id="loc-b"
    )
    entry_b.add_to_hass(hass)
    await hass.config_entries.async_setup(entry_b.entry_id)
    await hass.async_block_till_done()

    # Both loaded, services should exist
    assert hass.services.has_service(DOMAIN, "create_group")

    # Unload entry A
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Services must still exist because entry B is loaded
    assert hass.services.has_service(DOMAIN, "create_group")

    # Unload entry B
    await hass.config_entries.async_unload(entry_b.entry_id)
    await hass.async_block_till_done()

    # No entries loaded, services must be removed
    assert not hass.services.has_service(DOMAIN, "create_group")
