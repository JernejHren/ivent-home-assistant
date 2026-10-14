"""Servisi: napake API-ja in prazni vnosi se pretvorijo v ServiceValidationError."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.ivent.api import IVentApiClientError
from custom_components.ivent.const import DOMAIN

CALLS = [
    ("create_group", {"name": "Soba"}, "async_create_group"),
    ("delete_group", {"group_id": 5}, "async_modify_group"),
    ("rename_group", {"group_id": 5, "new_name": "Nova"}, "async_modify_group"),
    ("rename_device", {"device_mac": "aa:bb:cc:00:00:01", "new_name": "Nova"}, "async_modify_device"),
    ("move_device_to_group", {"device_mac": "aa:bb:cc:00:00:01", "group_id": 5}, "async_modify_device"),
]


@pytest.mark.parametrize(("service", "data", "method"), CALLS)
async def test_service_api_error(hass: HomeAssistant, mock_config_entry, mock_api_client,
                                 service, data, method):
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    getattr(mock_api_client, method).side_effect = IVentApiClientError("boom")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


@pytest.mark.parametrize(("service", "data"), [
    ("create_group", {"name": "   "}),
    ("rename_group", {"group_id": 5, "new_name": "  "}),
    ("rename_device", {"device_mac": "aa:bb:cc:00:00:01", "new_name": " "}),
    ("rename_device", {"device_mac": "", "new_name": "x"}),
    ("move_device_to_group", {"device_mac": "", "group_id": 5}),
])
async def test_service_empty_input(hass: HomeAssistant, mock_config_entry, mock_api_client,
                                   service, data):
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_services_rename_success(hass: HomeAssistant, mock_config_entry, mock_api_client):
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "rename_group", {"group_id": 5, "new_name": "N"}, blocking=True)
    await hass.services.async_call(DOMAIN, "rename_device",
                                   {"device_mac": "aa:bb:cc:00:00:01", "new_name": "N"}, blocking=True)
    await hass.services.async_call(DOMAIN, "move_device_to_group",
                                   {"device_mac": "aa:bb:cc:00:00:01", "group_id": 5}, blocking=True)
    mock_api_client.async_modify_group.assert_called_with(5, {"name": "N"})
    mock_api_client.async_modify_device.assert_called_with("aa:bb:cc:00:00:01", {"group_id": 5})
