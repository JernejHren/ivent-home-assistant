# tests/components/ivent/test_button.py
import pytest
from homeassistant.core import HomeAssistant

async def test_button_press(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test button press for i-Vent."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Izbriši skupino button
    entity_id = "button.dnevna_soba_delete_group"
    state = hass.states.get(entity_id)
    assert state is not None

    await hass.services.async_call(
        "button", "press",
        {"entity_id": entity_id},
        blocking=True,
    )
    
    mock_api_client.async_modify_group.assert_called_once()
    # Check that payload contains delete=True
    args = mock_api_client.async_modify_group.call_args
    assert args[0][1] == {"delete": True}


async def test_cloud_mode_has_no_action_buttons(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Beacon in ponastavitev filtra obstajata samo lokalno/hibridno."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    ids = [s.entity_id for s in hass.states.async_all("button")]
    assert ids and not any(i.endswith(("_beacon", "_find_device", "_reset_filter_alarm")) for i in ids)
