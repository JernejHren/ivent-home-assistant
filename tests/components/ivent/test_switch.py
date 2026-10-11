# tests/components/ivent/test_switch.py
import pytest
from homeassistant.core import HomeAssistant

async def test_switch_entities(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test switch entities setup and initial states."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # LED Switch
    led_entity = "switch.dnevna_soba_led_lights"
    state = hass.states.get(led_entity)
    assert state is not None
    assert state.state == "on"

    # Buzzer Switch
    buzzer_entity = "switch.dnevna_soba_buzzer"
    state = hass.states.get(buzzer_entity)
    assert state.state == "on"

    # Reverse Flow Switch
    reverse_entity = "switch.enota_1_reverse_flow"
    assert hass.states.get(reverse_entity).state == "off"

    # Schedule Switch
    schedule_entity = "switch.i_vent_system_schedule"
    state = hass.states.get(schedule_entity)
    assert state is not None
    assert state.state == "on"

async def test_led_switch_turn_on_off(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test LED switch turn_on and turn_off."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    led_entity = "switch.dnevna_soba_led_lights"

    await hass.services.async_call("switch", "turn_off", {"entity_id": led_entity}, blocking=True)
    mock_api_client.async_modify_group.assert_called_with(1, {"led_mode": "LedOffMode"})

    await hass.services.async_call("switch", "turn_on", {"entity_id": led_entity}, blocking=True)
    mock_api_client.async_modify_group.assert_called_with(1, {"led_mode": "LedOnMode"})

async def test_buzzer_switch_turn_on_off(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test Buzzer switch turn_on and turn_off."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    buzzer_entity = "switch.dnevna_soba_buzzer"

    await hass.services.async_call("switch", "turn_off", {"entity_id": buzzer_entity}, blocking=True)
    mock_api_client.async_modify_group.assert_called_with(1, {"buzzer_mode": "BuzzerOffMode"})

    await hass.services.async_call("switch", "turn_on", {"entity_id": buzzer_entity}, blocking=True)
    mock_api_client.async_modify_group.assert_called_with(1, {"buzzer_mode": "BuzzerOnMode"})

async def test_special_mode_switches(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test all special mode switches (Night1, Night2, Snooze, Boost)."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    modes = [
        ("switch.dnevna_soba_night_mode_1", "IVentNight1"),
        ("switch.dnevna_soba_night_mode_2", "IVentNight2"),
        ("switch.dnevna_soba_snooze", "IVentSnooze"),
        ("switch.dnevna_soba_boost", "IVentBoost"),
    ]

    for entity_id, api_mode in modes:
        await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
        # Check payload
        args = mock_api_client.async_modify_group.call_args[0]
        assert args[1]["remote_work_mode"]["special_mode"] == api_mode

    # Test turn_off (should reset to IVentSpecialOff)
    await hass.services.async_call("switch", "turn_off", {"entity_id": modes[0][0]}, blocking=True)
    args = mock_api_client.async_modify_group.call_args[0]
    assert args[1]["remote_work_mode"]["special_mode"] == "IVentSpecialOff"

async def test_reverse_flow_switch_turn_on_off(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test Reverse Flow switch turn_on and turn_off."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    reverse_entity = "switch.enota_1_reverse_flow"

    await hass.services.async_call("switch", "turn_on", {"entity_id": reverse_entity}, blocking=True)
    mock_api_client.async_modify_device.assert_called_with("AA:BB:CC:DD:EE:FF", {"reverse_flow": True})

    await hass.services.async_call("switch", "turn_off", {"entity_id": reverse_entity}, blocking=True)
    mock_api_client.async_modify_device.assert_called_with("AA:BB:CC:DD:EE:FF", {"reverse_flow": False})

async def test_schedule_switch_turn_on_off(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test Schedule switch turn_on and turn_off."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    schedule_entity = "switch.i_vent_system_schedule"

    await hass.services.async_call("switch", "turn_off", {"entity_id": schedule_entity}, blocking=True)
    mock_api_client.async_modify_schedules.assert_called_once()
    # Check that it set enabled = False in the first schedule
    schedules = mock_api_client.async_modify_schedules.call_args[0][0]
    assert schedules[0]["schedules"][0]["header"]["schedule_item_enabled"] is False

    await hass.services.async_call("switch", "turn_on", {"entity_id": schedule_entity}, blocking=True)
    schedules = mock_api_client.async_modify_schedules.call_args[0][0]
    assert schedules[0]["schedules"][0]["header"]["schedule_item_enabled"] is True

async def test_optimistic_state_ignores_stale_data(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that optimistic state ignores stale coordinator data during the window."""
    import time
    from unittest.mock import patch

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    led_entity = "switch.dnevna_soba_led_lights"
    
    # Send a turn off command
    await hass.services.async_call("switch", "turn_off", {"entity_id": led_entity}, blocking=True)
    
    # Verify entity optimistically updated to "off"
    assert hass.states.get(led_entity).state == "off"

    # Mock the coordinator fetching old stale data (where LED is still ON)
    # and trigger an update, simulating read-after-write inconsistency
    from custom_components.ivent.const import DOMAIN
    coordinator = mock_config_entry.runtime_data.coordinator
    
    # Patch only optimistic timer usage from integration, not global asyncio time.
    with patch("custom_components.ivent.entity.monotonic", return_value=time.monotonic() + 0.5):
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        # State should STILL be "off" because of optimistic fallback
        assert hass.states.get(led_entity).state == "off"

    # Move time FORWARD past the 2.0 second window
    with patch("custom_components.ivent.entity.monotonic", return_value=time.monotonic() + 3.0):
        # Now trigger an update with the same stale data
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        # Now it should have reverted to "on" based on the coordinator's stale polling
        assert hass.states.get(led_entity).state == "on"
