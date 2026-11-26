import pytest
from unittest.mock import AsyncMock, patch
import copy
import sys
import importlib
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_API_KEY = 'test-api-key-12345'
MOCK_LOCATION_ID = 'test-location-99'

# Primer API odgovora — prilagodi glede na dejanski API odgovor
MOCK_INFO_DATA = {
    'groups': [{
        'id': 1,
        'name': 'Dnevna soba',
        'led_work_mode': 'LedOnMode',
        'buzzer_work_mode': 'BuzzerOnMode',
        'remote': {
            'work_mode': 'IVentRecuperation1',
            'special_mode': 'IVentSpecialOff',
            'remote_control_speed': 1,
            'remote_control_work_mode': 'Normal',
            'bypass_rotation': 'BypassForward',
            'work_mode_changed_at': 1700000000,
            'special_mode_ends_at': 0,
        },
        'profile': {
            'boostTime': 3600,
            'snoozeTime': 1800,
            'sleepModeDuration1': 28800,
            'sleepModeDuration2': 21600,
        },
        'devices': [{
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'device_name': 'Enota 1',
            'rssi': -65,
            'firmware_version': '1.2.3',
            'alive': True,
            'status_esp': 0,
            'reverse_flow': False,
        }]
    }]
}

MOCK_SCHEDULES_DATA = [
    {
        "name": "Dnevni urnik",
        "schedules": [
            {
                "meta": {"schedule_id": 101},
                "repeat": {"days": 127, "hour": 8, "minute": 30},
                "header": {"schedule_item_enabled": True}
            },
            {
                "meta": {"schedule_id": 102},
                "repeat": {"days": 62, "hour": 22, "minute": 0},
                "header": {"schedule_item_enabled": False}
            }
        ]
    }
]

@pytest.fixture
def mock_api_client():
    """Mock the IVentApiClient."""
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    importlib.invalidate_caches()

    with patch("custom_components.ivent.IVentApiClient", autospec=True, create=True) as mock_client:
        client = mock_client.return_value
        client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
        client.async_get_schedules.return_value = copy.deepcopy(MOCK_SCHEDULES_DATA)

        # Patchamo tudi v config_flow
        with patch("custom_components.ivent.config_flow.IVentApiClient", new=mock_client):
            yield client


@pytest.fixture
def mock_config_entry(hass):
    """Mock a config entry."""
    entry = MockConfigEntry(
        domain="ivent",
        data={"api_key": MOCK_API_KEY, "location_id": MOCK_LOCATION_ID},
        unique_id=MOCK_LOCATION_ID,
    )
    entry.add_to_hass(hass)
    return entry
