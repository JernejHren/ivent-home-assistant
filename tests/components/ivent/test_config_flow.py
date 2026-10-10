# tests/components/ivent/test_config_flow.py
import pytest
from unittest.mock import AsyncMock, patch
from homeassistant.data_entry_flow import FlowResultType
from custom_components.ivent.api import IVentApiAuthError, IVentApiClientError
from custom_components.ivent.const import DOMAIN
from .conftest import MOCK_INFO_DATA

async def _cloud_form(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={'source': 'user'})
    assert result['type'] is FlowResultType.MENU
    assert result['step_id'] == 'user'
    assert set(result['menu_options']) == {'cloud', 'local', 'hybrid'}
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'next_step_id': 'cloud'})
    assert result['type'] is FlowResultType.FORM and result['step_id'] == 'cloud'
    return result


# TEST 1: Uspešen setup (API ključ + ročni ID lokacije)
async def test_full_flow_success(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info = AsyncMock(return_value=MOCK_INFO_DATA)
        result = await _cloud_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result['flow_id'], {'api_key': 'valid-key', 'location_id': 'loc-1'})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['title'] == 'i-Vent Cloud'
    assert result['data'] == {'mode': 'cloud', 'api_key': 'valid-key', 'location_id': 'loc-1'}


# TEST 2: ID lokacije je v oblaku obvezen (uradni API nima seznama lokacij)
async def test_cloud_location_id_is_required(hass):
    from homeassistant.data_entry_flow import InvalidData
    result = await _cloud_form(hass)
    with pytest.raises(InvalidData):  # polje je Required: brez njega obrazca ni mogoče oddati
        await hass.config_entries.flow.async_configure(result['flow_id'], {'api_key': 'key'})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'api_key': 'key', 'location_id': '   '})
    assert result['type'] is FlowResultType.FORM
    assert result['errors']['base'] == 'location_id_required'  # prazen niz ni ID


# TEST 3: Napačen API ključ
async def test_flow_auth_error(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch('custom_components.ivent.config_flow.IVentApiClient') as mock:
        mock.return_value.async_get_info.side_effect = IVentApiAuthError()
        result = await _cloud_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result['flow_id'], {'api_key': 'bad', 'location_id': 'loc-1'})
    assert result['type'] is FlowResultType.FORM
    assert result['errors']['base'] == 'auth_error'


# TEST 4: Napaka pri povezavi
async def test_flow_cannot_connect(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch('custom_components.ivent.config_flow.IVentApiClient') as mock:
        mock.return_value.async_get_info.side_effect = IVentApiClientError()
        result = await _cloud_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result['flow_id'], {'api_key': 'key', 'location_id': 'loc-1'})
    assert result['errors']['base'] == 'cannot_connect'


# TEST 4b: ključ ali lokacija neveljavna (HTTP 403/404 pri preverjanju lokacije)
async def test_flow_unknown_location_is_an_error(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch('custom_components.ivent.config_flow.IVentApiClient') as mock:
        mock.return_value.async_get_info.side_effect = IVentApiClientError("HTTP error 404", status=404)
        result = await _cloud_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result['flow_id'], {'api_key': 'key', 'location_id': 'nope'})
    assert result['type'] is FlowResultType.FORM and result['errors']['base'] == 'cannot_connect'


# TEST 5: Duplikat — ista lokacija
async def test_flow_duplicate(hass, mock_config_entry):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info = AsyncMock(return_value=MOCK_INFO_DATA)
        result = await _cloud_form(hass)
        result = await hass.config_entries.flow.async_configure(
            result['flow_id'], {'api_key': 'key', 'location_id': 'test-location-99'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'already_configured'

# TEST 5: Reauth flow success
async def test_reauth_flow_success(hass, mock_config_entry):
    """Test the reauthentication flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": mock_config_entry.entry_id, "title_placeholders": {"name": mock_config_entry.title}},
        data=mock_config_entry.data,
    )
    
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info = AsyncMock(return_value=MOCK_INFO_DATA)
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "new-valid-key"},
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert mock_config_entry.data["api_key"] == "new-valid-key"

# TEST 6: Reauth flow auth error
async def test_reauth_flow_auth_error(hass, mock_config_entry):
    """Test the reauthentication flow resulting in auth error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": mock_config_entry.entry_id, "title_placeholders": {"name": mock_config_entry.title}},
        data=mock_config_entry.data,
    )

    with patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info.side_effect = IVentApiAuthError()
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "new-invalid-key"},
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reauth_confirm"
    assert result2["errors"]["base"] == "auth_error"

# TEST 7: Reconfigure flow
async def test_reconfigure_flow_success(hass, mock_config_entry):
    """Test the reconfiguration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": mock_config_entry.entry_id},
    )
    
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cloud"

    with patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info = AsyncMock(return_value=MOCK_INFO_DATA)
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "new-valid-key-2", "location_id": "new-location"},
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["api_key"] == "new-valid-key-2"
    assert mock_config_entry.data["location_id"] == "new-location"

# TEST 8: Reconfigure flow auth error
async def test_reconfigure_flow_auth_error(hass, mock_config_entry):
    """Test the reconfiguration flow resulting in auth error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": mock_config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud"})

    with patch("custom_components.ivent.config_flow.IVentApiClient") as mock:
        mock.return_value.async_get_info.side_effect = IVentApiAuthError()
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_key": "bad-key", "location_id": "bad-location"},
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "cloud"
    assert result2["errors"]["base"] == "auth_error"