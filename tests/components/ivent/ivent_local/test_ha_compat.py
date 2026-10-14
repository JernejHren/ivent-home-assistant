"""Združljivost s HA 2026.x (via_device -> via_device_id) in ravnanje z ID-jem lokacije v oblaku."""
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ivent import entity as entity_mod
from custom_components.ivent.api import (
    IVentApiAuthError, IVentApiClientError, IVentApiConnectionError,
)
from custom_components.ivent.const import DOMAIN
from custom_components.ivent.ivent_local.discovery import DiscoveredMaster

from .conftest import FAKE_LOC, FAKE_MACS

LOC = str(FAKE_LOC)


# --- via_device ----------------------------------------------------------------

def _coordinator(hass, entry):
    coord = MagicMock()
    coord.hass = hass
    coord.config_entry = entry
    return coord


async def test_via_device_tuple_on_old_home_assistant(hass):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    with patch.object(entity_mod, "_supports_via_device_id", return_value=False):
        assert entity_mod._via_device(_coordinator(hass, entry)) == {
            "via_device": (DOMAIN, entry.entry_id)}


async def test_via_device_id_on_new_home_assistant(hass):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="i-Vent System")
    with patch.object(entity_mod, "_supports_via_device_id", return_value=True):
        info = entity_mod._via_device(_coordinator(hass, entry))
    assert info == {"via_device_id": hub.id}  # id naprave v registru, ne tuple identifikatorjev


async def test_missing_hub_device_gives_no_link_instead_of_error(hass):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    with patch.object(entity_mod, "_supports_via_device_id", return_value=True):
        assert entity_mod._via_device(_coordinator(hass, entry)) == {}


def test_support_detection_follows_deviceinfo_keys():
    # v tem okolju je rezultat odvisen od verzije HA; mora biti bool in skladen z DeviceInfo
    keys = getattr(entity_mod.DeviceInfo, "__annotations__", {})
    assert entity_mod._supports_via_device_id() == ("via_device_id" in keys)


# --- ID lokacije: v oblaku obvezen, pri hibridu ga lahko določi lokalno odkrivanje ---------

async def _menu(hass, mode):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": mode})


def _location_key(result):
    return next(k for k in result["data_schema"].schema if k == "location_id")


async def test_location_id_is_required_in_cloud_form_and_optional_in_hybrid_form(hass):
    import voluptuous as vol
    cloud = await _menu(hass, "cloud")
    assert isinstance(_location_key(cloud), vol.Required)
    hybrid = await _menu(hass, "hybrid")
    assert isinstance(_location_key(hybrid), vol.Optional)


async def test_cloud_never_calls_the_nonexistent_locations_endpoint(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud, \
            patch("custom_components.ivent.async_setup_entry", return_value=True):
        cloud.return_value.async_get_info = AsyncMock(return_value={"groups": []})
        result = await _menu(hass, "cloud")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "location_id": LOC})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"mode": "cloud", "api_key": "k", "location_id": LOC}
    assert not hasattr(cloud.return_value, "async_get_locations") or \
        not cloud.return_value.async_get_locations.called


async def _hybrid_without_location(hass):
    """Hibrid s samim API ključem: brez omrežnega klica gre naravnost v lokalni korak."""
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud:
        result = await _menu(hass, "hybrid")
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"api_key": "k"})
        cloud.assert_not_called()  # ključ se preveri šele z odkritim ID-jem lokacije
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "local"
    assert "location_id" in result["data_schema"].schema  # ID še ni znan: obrazec ga ponudi
    return result


async def test_hybrid_without_location_id_takes_it_from_local_discovery(hass):
    found = DiscoveredMaster("192.168.1.179", FAKE_MACS[0], FAKE_LOC, 1)
    backend = MagicMock(async_start=AsyncMock(), async_ping=AsyncMock(return_value=1),
                        async_stop=AsyncMock())
    result = await _hybrid_without_location(hass)
    with patch("custom_components.ivent.config_flow.discover_master", AsyncMock(return_value=found)), \
            patch("custom_components.ivent.config_flow.IVentLocalBackend") as cls, \
            patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud, \
            patch("custom_components.ivent.async_setup_entry", return_value=True):
        cls.create.return_value = backend
        cloud.return_value.async_get_info = AsyncMock(return_value={"groups": []})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "i-Vent Hybrid"
    assert result["data"] == {"mode": "hybrid", "api_key": "k", "location_id": LOC,
                              "local_host": "192.168.1.179", "local_mac": FAKE_MACS[0]}
    assert cloud.call_args.args[2] == LOC  # oblak je preverjen z odkritim ID-jem lokacije


async def test_hybrid_discovery_with_wrong_api_key_reports_auth_error(hass):
    found = DiscoveredMaster("192.168.1.179", FAKE_MACS[0], FAKE_LOC, 1)
    backend = MagicMock(async_start=AsyncMock(), async_ping=AsyncMock(return_value=1),
                        async_stop=AsyncMock())
    result = await _hybrid_without_location(hass)
    with patch("custom_components.ivent.config_flow.discover_master", AsyncMock(return_value=found)), \
            patch("custom_components.ivent.config_flow.IVentLocalBackend") as cls, \
            patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud:
        cls.create.return_value = backend
        cloud.return_value.async_get_info = AsyncMock(side_effect=IVentApiAuthError("bad"))
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM and result["errors"]["base"] == "auth_error"


async def test_hybrid_with_manual_location_id_validates_cloud_first(hass):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud:
        cloud.return_value.async_get_info = AsyncMock(side_effect=IVentApiAuthError("bad"))
        result = await _menu(hass, "hybrid")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "location_id": LOC})
    assert result["step_id"] == "hybrid" and result["errors"]["base"] == "auth_error"


async def test_setup_logs_mode_without_location_id(hass, caplog):
    import logging
    from custom_components.ivent import _build_backend  # noqa: F401  (uvoz paketa)
    import custom_components.ivent as ivent
    entry = MockConfigEntry(domain=DOMAIN, data={
        "mode": "local", "location_id": LOC, "local_host": "192.168.1.179",
        "local_mac": FAKE_MACS[0]})
    entry.add_to_hass(hass)
    with caplog.at_level(logging.INFO, logger="custom_components.ivent"), \
            patch.object(ivent, "_build_backend", side_effect=RuntimeError("stop")):
        try:
            await ivent.async_setup_entry(hass, entry)
        except RuntimeError:
            pass
    assert "local mode (Master 192.168.1.179)" in caplog.text
    assert LOC not in caplog.text  # ID lokacije je poverilnica: nikoli v dnevnik
