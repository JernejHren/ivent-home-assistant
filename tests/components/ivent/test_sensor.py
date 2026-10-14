# tests/components/ivent/test_sensor.py
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

SENSOR_IDS = {
    "sensor.enota_1_signal": "AA:BB:CC:DD:EE:FF_rssi",
    "sensor.dnevna_soba_last_mode_change": "{entry}_1_work_mode_changed_at",
    "sensor.dnevna_soba_special_mode_ends_at": "{entry}_1_special_mode_ends_at",
}


def _enable_sensors(hass: HomeAssistant, entry) -> None:
    """Sensorji so privzeto onemogočeni: pred zagonom jih vnaprej omogočimo."""
    registry = er.async_get(hass)
    for entity_id, uid in SENSOR_IDS.items():
        registry.async_get_or_create(
            "sensor", "ivent", uid.format(entry=entry.entry_id),
            config_entry=entry, suggested_object_id=entity_id.split(".")[1],
            disabled_by=None,
        )


async def test_sensors_disabled_by_default(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Diagnostični sensorji so privzeto onemogočeni v registru."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for uid in SENSOR_IDS.values():
        entity_id = registry.async_get_entity_id(
            "sensor", "ivent", uid.format(entry=mock_config_entry.entry_id))
        assert entity_id is not None
        assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None

async def test_sensor_entities(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test sensor entities for i-Vent."""
    _enable_sensors(hass, mock_config_entry)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # RSSI Sensor
    rssi_state = hass.states.get("sensor.enota_1_signal")
    assert rssi_state is not None
    assert rssi_state.state == "-65"
    assert rssi_state.attributes.get("unit_of_measurement") == "dBm"

    # Last Changed Timestamp Sensor
    last_changed_state = hass.states.get("sensor.dnevna_soba_last_mode_change")
    assert last_changed_state is not None
    # 1700000000 is 2023-11-14T22:13:20+00:00
    assert "2023-11-14" in last_changed_state.state

    ends_at_state = hass.states.get("sensor.dnevna_soba_special_mode_ends_at")
    assert ends_at_state is not None
    assert ends_at_state.state == "unknown"  # 0 in mock means None

async def test_sensor_updates(hass: HomeAssistant, mock_config_entry, mock_api_client):
    """Test that sensor values update correctly from API changes."""
    _enable_sensors(hass, mock_config_entry)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Initial state
    rssi_state = hass.states.get("sensor.enota_1_signal")
    assert rssi_state.state == "-65"

    # Mock new data
    from .conftest import MOCK_INFO_DATA
    import copy
    new_data = copy.deepcopy(MOCK_INFO_DATA)
    new_data["groups"][0]["devices"][0]["rssi"] = -70
    mock_api_client.async_get_info.return_value = new_data

    # Trigger update
    from custom_components.ivent.const import DOMAIN
    coordinator = mock_config_entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Verify updated state
    rssi_state = hass.states.get("sensor.enota_1_signal")
    assert rssi_state.state == "-70"


async def test_cloud_mode_sensor(hass, mock_config_entry, mock_api_client):
    from homeassistant.helpers import entity_registry as er
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    ent = er.async_get(hass).async_get_entity_id(
        "sensor", "ivent", f"{mock_config_entry.entry_id}_connection_mode")
    assert ent and hass.states.get(ent).state == "cloud"
