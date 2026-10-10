import pytest
import copy
from homeassistant.core import HomeAssistant
from custom_components.ivent.const import API_MODE_WORK_OFF
from .conftest import MOCK_INFO_DATA

async def test_fan_is_on(hass, mock_config_entry, mock_api_client):
    """Test fan is on with default mock data."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get('fan.dnevna_soba_fan')
    assert state is not None
    assert state.state == 'on'  # work_mode != IVentWorkOff

async def test_fan_is_off_when_work_mode_off(hass, mock_config_entry, mock_api_client):
    """Test fan is off when work_mode is IVentWorkOff."""
    off_data = copy.deepcopy(MOCK_INFO_DATA)
    off_data['groups'][0]['remote']['work_mode'] = API_MODE_WORK_OFF
    mock_api_client.async_get_info.return_value = off_data
    
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    state = hass.states.get('fan.dnevna_soba_fan')
    assert state.state == 'off'

async def test_fan_turn_on(hass, mock_config_entry, mock_api_client):
    """Test fan turn_on service."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    await hass.services.async_call(
        'fan', 'turn_on',
        {'entity_id': 'fan.dnevna_soba_fan'},
        blocking=True,
    )
    
    mock_api_client.async_modify_group.assert_called_once()
    # Default speed 1 -> IVentRecuperation1
    args = mock_api_client.async_modify_group.call_args[0]
    assert args[0] == 1 # group_id
    assert args[1]["remote_work_mode"]["work_mode"] == "IVentRecuperation1"
    assert args[1]["remote_work_mode"]["remote_control_speed"] == 1
    assert args[1]["remote_work_mode"]["remote_control_work_mode"] == "Normal"

async def test_fan_turn_off(hass, mock_config_entry, mock_api_client):
    """Test fan turn_off service."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    await hass.services.async_call(
        'fan', 'turn_off',
        {'entity_id': 'fan.dnevna_soba_fan'},
        blocking=True,
    )
    
    mock_api_client.async_modify_group.assert_called_once()
    args = mock_api_client.async_modify_group.call_args[0]
    assert args[1]["remote_work_mode"]["work_mode"] == API_MODE_WORK_OFF

@pytest.mark.parametrize(
    "percentage,expected_work_mode,expected_speed",
    [
        (33, "IVentRecuperation1", 1),
        (34, "IVentRecuperation2", 2),
        (66, "IVentRecuperation2", 2),
        (67, "IVentRecuperation3", 3),
        (100, "IVentRecuperation3", 3),
    ],
)
async def test_fan_turn_on_with_percentage(hass, mock_config_entry, mock_api_client, percentage, expected_work_mode, expected_speed):
    """Test fan turn_on with percentage mapping."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    await hass.services.async_call(
        'fan', 'turn_on',
        {'entity_id': 'fan.dnevna_soba_fan', 'percentage': percentage},
        blocking=True,
    )
    
    args = mock_api_client.async_modify_group.call_args[0]
    assert args[1]["remote_work_mode"]["work_mode"] == expected_work_mode
    assert args[1]["remote_work_mode"]["remote_control_speed"] == expected_speed


async def test_fan_turn_on_with_bypass_preset(hass, mock_config_entry, mock_api_client):
    """Test fan turn_on sends matching bypass mode and speed fields."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        'fan', 'turn_on',
        {'entity_id': 'fan.dnevna_soba_fan', 'percentage': 100, 'preset_mode': 'Bypass'},
        blocking=True,
    )

    args = mock_api_client.async_modify_group.call_args[0]
    assert args[1]["remote_work_mode"]["work_mode"] == "IVentBypass3"
    assert args[1]["remote_work_mode"]["remote_control_speed"] == 3
    assert args[1]["remote_work_mode"]["remote_control_work_mode"] == "Bypass"


async def test_fan_turn_on_with_zero_percentage(hass, mock_config_entry, mock_api_client):
    """Test fan turns off when percentage is 0."""
    from custom_components.ivent.const import API_MODE_WORK_OFF
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    
    await hass.services.async_call(
        'fan', 'turn_on',
        {'entity_id': 'fan.dnevna_soba_fan', 'percentage': 0},
        blocking=True,
    )
    
    args = mock_api_client.async_modify_group.call_args[0]
    assert args[1]["remote_work_mode"]["work_mode"] == API_MODE_WORK_OFF


async def test_fan_optimistic_update(hass, mock_config_entry, mock_api_client):
    """Test that fan applies optimistic state for percentage and mode without blocking other updates."""
    import time
    from unittest.mock import patch
    from custom_components.ivent.const import DOMAIN
    
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Original state is on, percentage might be 33
    fan_id = "fan.dnevna_soba_fan"
    
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
    import copy
    original_remotes = {
        gid: copy.deepcopy(g.raw["remote"]) for gid, g in coordinator.data.groups_by_id.items()
    }

    # We turn it to 100%
    await hass.services.async_call('fan', 'turn_on', {'entity_id': fan_id, 'percentage': 100}, blocking=True)
    
    state = hass.states.get(fan_id)
    assert state.attributes.get("percentage") == 100

    # A successful write is applied to the coordinator data right away (see
    # _apply_successful_group_write), so a poll that still returns the OLD state
    # (cloud lag) has to be simulated by restoring the pre-write remote data.
    for gid, remote in original_remotes.items():
        coordinator.data.groups_by_id[gid].raw["remote"].update(remote)
    
    # Simulate a coordinator polling within 2 seconds. The data still says speed is 1 (33%)
    # Patch only integration monotonic usage used by optimistic cache logic.
    # Patching global time.monotonic can break asyncio internals and cause timeouts.
    with patch(
        "custom_components.ivent.entity.monotonic",
        return_value=time.monotonic() + 0.5,
    ):
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        state = hass.states.get(fan_id)
        # Should remain 100 due to optimistic caching
        assert state.attributes.get("percentage") == 100
    
    # Simulate time passing beyond 2 seconds
    with patch(
        "custom_components.ivent.entity.monotonic",
        return_value=time.monotonic() + 3.0,
    ):
        coordinator.async_set_updated_data(coordinator.data)
        await hass.async_block_till_done()
        
        state = hass.states.get(fan_id)
        # Should now reflect the API data (which is still mocked to speed 1 -> 33%)
        assert state.attributes.get("percentage") == 33

async def test_fan_optimistic_state_rollback_on_error(hass, mock_config_entry, mock_api_client):
    """Test that optimistic state is rolled back if the API call fails."""
    from custom_components.ivent.api import IVentApiClientError
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    fan_id = "fan.dnevna_soba_fan"
    
    # Verify initial state is on
    state = hass.states.get(fan_id)
    assert state.state == "on"

    # Make the API call fail
    mock_api_client.async_modify_group.side_effect = IVentApiClientError("Mocked failure")

    # Call turn_off, expecting an error
    with pytest.raises((IVentApiClientError, HomeAssistantError, Exception)):
        await hass.services.async_call(
            'fan', 'turn_off',
            {'entity_id': fan_id},
            blocking=True,
        )

    # State should be reverted to 'on' because the optimistic 'off' was rolled back
    state = hass.states.get(fan_id)
    assert state.state == "on"


async def test_fan_turn_on_optimistic_state_rollback_on_error(hass, mock_config_entry, mock_api_client):
    """Test that optimistic state is rolled back if the API call fails during turn_on."""
    from custom_components.ivent.api import IVentApiClientError
    from homeassistant.helpers import entity_registry as er
    import pytest
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ivent.const import API_MODE_WORK_OFF
    import copy

    # Set initial state to off so we can test turn_on
    off_data = copy.deepcopy(MOCK_INFO_DATA)
    off_data['groups'][0]['remote']['work_mode'] = API_MODE_WORK_OFF
    mock_api_client.async_get_info.return_value = off_data

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Dynamic entity lookup
    entity_registry = er.async_get(hass)
    fan_entries = er.async_entries_for_config_entry(entity_registry, mock_config_entry.entry_id)
    fan_entry = next(e for e in fan_entries if e.domain == "fan")
    fan_id = fan_entry.entity_id

    # Verify initial state is off
    state = hass.states.get(fan_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes.get("percentage") == 0
    original_preset = state.attributes.get("preset_mode")

    # Make the API call fail
    mock_api_client.async_modify_group.side_effect = IVentApiClientError("Mocked failure")

    # Call turn_on with percentage and preset_mode, expecting an error
    with pytest.raises((IVentApiClientError, HomeAssistantError)):
        await hass.services.async_call(
            'fan', 'turn_on',
            {'entity_id': fan_id, 'percentage': 100, 'preset_mode': 'Bypass'},
            blocking=True,
        )
    await hass.async_block_till_done()

    # State should be reverted to 'off' because the optimistic 'on' was rolled back
    state = hass.states.get(fan_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes.get("percentage") == 0
    assert state.attributes.get("preset_mode") != "Bypass"
    assert state.attributes.get("preset_mode") == original_preset