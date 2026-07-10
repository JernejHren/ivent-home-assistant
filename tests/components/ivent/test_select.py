# tests/components/ivent/test_select.py
import copy
import pytest
import asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from custom_components.ivent.const import API_MODE_WORK_OFF
from tests.components.ivent.conftest import MOCK_INFO_DATA

async def test_select_entities(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test select entities for i-Vent."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Ventilation Mode Select
    # Entity ID is slugified from "Način prezračevanja"
    vm_entity = "select.dnevna_soba_ventilation_mode"
    state = hass.states.get(vm_entity)
    
    if state is None:
        # Fallback debug
        print(f"DEBUG: All entities: {hass.states.async_entity_ids()}")
    
    assert state is not None
    assert state.state == "Rekuperacija"  # Normal in mock

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": vm_entity, "option": "Prezračevanje (Bypass)"},
        blocking=True,
    )
    mock_api_client.async_modify_group.assert_called()
    args = mock_api_client.async_modify_group.call_args
    assert args[0][1]["remote_work_mode"]["remote_control_work_mode"] == "Bypass"
    assert args[0][1]["remote_work_mode"]["remote_control_speed"] == 1
    assert args[0][1]["remote_work_mode"]["work_mode"] == "IVentBypass1"
    mock_api_client.async_modify_group.reset_mock()

    # Hitrost Select
    speed_entity = "select.dnevna_soba_speed"
    state = hass.states.get(speed_entity)
    assert state is not None
    assert state.state == "Stopnja 1"  # 1 in mock

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": speed_entity, "option": "Stopnja 2"},
        blocking=True,
    )
    # Check that payload contains speed 2
    args = mock_api_client.async_modify_group.call_args
    assert args[0][1]["remote_work_mode"]["remote_control_speed"] == 2
    assert args[0][1]["remote_work_mode"]["remote_control_work_mode"] == "Bypass"
    assert args[0][1]["remote_work_mode"]["work_mode"] == "IVentBypass2"

    # Premakni v skupino Select
    move_entity = "select.enota_1_move_to_group"
    state = hass.states.get(move_entity)
    assert state is not None
    assert state.state == "Dnevna soba"

async def test_move_device_select_option(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test selecting an option in the move device select."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    move_entity = "select.enota_1_move_to_group"
    
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": move_entity, "option": "Dnevna soba"},
        blocking=True,
    )
    
    # Verify that async_modify_device was called with the correct group ID (1 in mock)
    mock_api_client.async_modify_device.assert_called_once_with(
        "AA:BB:CC:DD:EE:FF", {"group_id": 1}
    )

async def test_select_optimistic_update(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that select applies optimistic state without blocking other updates."""
    import time
    from unittest.mock import patch
    from custom_components.ivent.const import DOMAIN
    
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    speed_entity = "select.dnevna_soba_speed"
    
    # Send an update to Stopnja 3
    await hass.services.async_call('select', 'select_option', {'entity_id': speed_entity, 'option': 'Stopnja 3'}, blocking=True)
    
    # State should optimistically be "Stopnja 3"
    assert hass.states.get(speed_entity).state == "Stopnja 3"
    
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
    
    # Patch only integration optimistic timer usage, not global asyncio clock.
    with patch("custom_components.ivent.entity.monotonic", return_value=time.monotonic() + 0.5):
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        # Should remain Stopnja 3 due to optimistic caching
        assert hass.states.get(speed_entity).state == "Stopnja 3"
    
    # Simulate time passing beyond optimistic window.
    with patch("custom_components.ivent.entity.monotonic", return_value=time.monotonic() + 3.0):
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        # Should now reflect the API data (which is still mocked to speed 1 -> Stopnja 1)
        assert hass.states.get(speed_entity).state == "Stopnja 1"


async def test_select_optimistic_rollback_on_error(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Test optimistic select state is rolled back when API write fails."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    speed_unique_id = f"{mock_config_entry.entry_id}_1_speed"
    speed_entity = entity_registry.async_get_entity_id("select", "ivent", speed_unique_id)
    assert speed_entity is not None

    # Initial mocked speed is 1.
    assert hass.states.get(speed_entity).state == "Stopnja 1"

    api_call_started = asyncio.Event()
    allow_api_failure = asyncio.Event()

    async def _delayed_api_failure(*_args, **_kwargs):
        api_call_started.set()
        await allow_api_failure.wait()
        raise Exception("API failed")

    mock_api_client.async_modify_group.side_effect = _delayed_api_failure

    # Use non-blocking call so we can observe optimistic state before rollback.
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": speed_entity, "option": "Stopnja 3"},
        blocking=False,
    )

    # Wait until API write has started but is still blocked from failing.
    await api_call_started.wait()

    # During in-flight write, state should be optimistic.
    assert hass.states.get(speed_entity).state == "Stopnja 3"

    # Release the API call so failure can propagate and rollback can happen.
    allow_api_failure.set()
    await hass.async_block_till_done()
    assert hass.states.get(speed_entity).state == "Stopnja 1"


async def test_ventilation_mode_off_on_cycle(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Test mode change while off then fan turn-on keeps API fields in sync."""
    bypass_data = copy.deepcopy(MOCK_INFO_DATA)
    bypass_data["groups"][0]["remote"].update({
        "work_mode": "IVentBypass2",
        "remote_control_work_mode": "Bypass",
        "remote_control_speed": 2,
    })
    mock_api_client.async_get_info.return_value = bypass_data

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    fan_entity = "fan.dnevna_soba_fan"
    vm_entity = "select.dnevna_soba_ventilation_mode"

    await hass.services.async_call(
        "fan", "turn_off", {"entity_id": fan_entity}, blocking=True
    )
    mock_api_client.async_modify_group.reset_mock()

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": vm_entity, "option": "Rekuperacija"},
        blocking=True,
    )
    args = mock_api_client.async_modify_group.call_args
    remote = args[0][1]["remote_work_mode"]
    assert remote["work_mode"] == API_MODE_WORK_OFF
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2
    mock_api_client.async_modify_group.reset_mock()

    bypass_data["groups"][0]["remote"].update({
        "work_mode": API_MODE_WORK_OFF,
        "remote_control_work_mode": "Normal",
        "remote_control_speed": 2,
    })
    mock_api_client.async_get_info.return_value = bypass_data

    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": fan_entity}, blocking=True
    )
    args = mock_api_client.async_modify_group.call_args
    remote = args[0][1]["remote_work_mode"]
    assert remote["work_mode"] == "IVentRecuperation2"
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2


async def test_ventilation_mode_change_while_on_syncs_work_mode(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Test changing mode while running sends a fully synchronized payload."""
    bypass_data = copy.deepcopy(MOCK_INFO_DATA)
    bypass_data["groups"][0]["remote"].update({
        "work_mode": "IVentBypass2",
        "remote_control_work_mode": "Bypass",
        "remote_control_speed": 2,
    })
    mock_api_client.async_get_info.return_value = bypass_data

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    vm_entity = "select.dnevna_soba_ventilation_mode"
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": vm_entity, "option": "Rekuperacija"},
        blocking=True,
    )
    remote = mock_api_client.async_modify_group.call_args[0][1]["remote_work_mode"]
    assert remote["work_mode"] == "IVentRecuperation2"
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2

