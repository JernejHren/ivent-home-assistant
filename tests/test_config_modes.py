"""Config flow (lokalno/kombinirano), options, migracija, izbira backenda in E2E nad lažno lokacijo."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.ivent as ivent
from custom_components.ivent.api import IVentApiClient, IVentApiConnectionError
from custom_components.ivent.const import (
    CONF_LOCAL_HOST, CONF_LOCAL_MAC, CONF_MODE, DOMAIN, MODE_CLOUD, MODE_HYBRID, MODE_LOCAL,
    OPT_INFO_FALLBACK,
)
from custom_components.ivent.diagnostics import TO_REDACT
from custom_components.ivent.ivent_local.discovery import DiscoveredMaster
from custom_components.ivent.local_backend import IVentHybridBackend, IVentLocalBackend

from .conftest import FAKE_LOC, FAKE_MACS
from .test_decode import DNEVNA, TILEN

LOC = str(FAKE_LOC)
MAC = FAKE_MACS[0]
FOUND = DiscoveredMaster("192.168.1.179", MAC, FAKE_LOC, 1790396130)
MANUAL = {"local_host": "192.168.1.179", "local_mac": MAC.upper(), "location_id": hex(FAKE_LOC)}


@pytest.fixture(autouse=True)
def no_real_setup():
    """Config flow po uspehu naloži vnos; tu testiramo samo tok (setup je lažen)."""
    with patch("custom_components.ivent.async_setup_entry", return_value=True):
        yield


@pytest.fixture
def fake_local():
    """Zamenja IVentLocalBackend in odkrivanje; vrne mocke za preverjanje."""
    backend = MagicMock()
    backend.async_start = AsyncMock()
    backend.async_ping = AsyncMock(return_value=1)
    backend.async_stop = AsyncMock()
    discover = AsyncMock(return_value=FOUND)
    with patch("custom_components.ivent.config_flow.IVentLocalBackend") as cls, \
            patch("custom_components.ivent.config_flow.discover_master", discover):
        cls.create.return_value = backend
        yield MagicMock(backend=backend, discover=discover, create=cls.create)


async def _pick(hass, mode, source="user", entry=None):
    ctx = {"source": source}
    if entry:
        ctx["entry_id"] = entry.entry_id
    result = await hass.config_entries.flow.async_init(DOMAIN, context=ctx)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": mode})


async def _local(hass, mode, user_input):
    result = await _pick(hass, mode)
    assert result["step_id"] == "local"
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


# --- lokalno ---------------------------------------------------------------

async def test_local_manual_entry_normalizes_and_skips_discovery(hass, fake_local):
    result = await _local(hass, "local", MANUAL)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "i-Vent Local"
    assert result["data"] == {"mode": "local", "location_id": LOC, "local_host": "192.168.1.179",
                              "local_mac": MAC}  # MAC male črke, locationId decimalno
    assert "api_key" not in result["data"]
    fake_local.discover.assert_not_awaited()
    fake_local.create.assert_called_once_with(location_id=FAKE_LOC, master_host="192.168.1.179",
                                              master_mac=MAC)
    fake_local.backend.async_stop.assert_awaited_once()


async def test_local_discovers_everything_when_fields_empty(hass, fake_local):
    result = await _local(hass, "local", {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LOCAL_HOST] == FOUND.ip and result["data"]["location_id"] == LOC
    fake_local.discover.assert_awaited_once()
    assert fake_local.discover.await_args.kwargs["host"] is None


async def test_local_host_given_restricts_discovery(hass, fake_local):
    await _local(hass, "local", {"local_host": "192.168.1.179"})
    assert fake_local.discover.await_args.kwargs["host"] == "192.168.1.179"


@pytest.mark.parametrize("patch_target,effect,expected", [
    ("discover", None, "discovery_failed"),
    ("discover", OSError("in use"), "port_in_use"),
    ("start", OSError("in use"), "port_in_use"),
    ("ping", IVentApiConnectionError("x"), "cannot_connect_local"),
])
async def test_local_errors_keep_form_and_release_socket(hass, fake_local, patch_target, effect, expected):
    if patch_target == "discover":
        fake_local.discover.side_effect = effect
        fake_local.discover.return_value = None
        user_input = {}
    else:
        getattr(fake_local.backend, f"async_{patch_target}").side_effect = effect
        user_input = MANUAL
    result = await _local(hass, "local", user_input)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "local"
    assert result["errors"]["base"] == expected
    if patch_target != "discover":
        fake_local.backend.async_stop.assert_awaited_once()


async def test_local_rejects_bad_mac_and_location(hass, fake_local):
    result = await _local(hass, "local", {**MANUAL, "local_mac": "nonsense"})
    assert result["errors"]["base"] == "invalid_mac"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**MANUAL, "location_id": "abc"})
    assert result["errors"]["base"] == "invalid_location_id"


async def test_local_given_location_must_match_discovered_master(hass, fake_local):
    fake_local.discover.return_value = DiscoveredMaster("192.168.1.179", MAC, FAKE_LOC ^ 1, 1)
    result = await _local(hass, "local", {"location_id": LOC})
    assert result["errors"]["base"] == "location_mismatch"


async def test_second_local_entry_is_refused(hass, fake_local):
    MockConfigEntry(domain=DOMAIN, unique_id="other", data={CONF_MODE: MODE_LOCAL,
                    "location_id": "other"}).add_to_hass(hass)
    result = await _pick(hass, "local")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "single_local_entry"


async def test_cloud_entries_do_not_block_local_entry(hass, fake_local):
    MockConfigEntry(domain=DOMAIN, unique_id="other", data={CONF_MODE: MODE_CLOUD,
                    "location_id": "other"}).add_to_hass(hass)
    assert (await _local(hass, "local", MANUAL))["type"] is FlowResultType.CREATE_ENTRY


# --- kombinirano -----------------------------------------------------------

async def _hybrid_to_local(hass, location_id=LOC):
    with patch("custom_components.ivent.config_flow.async_get_clientsession"), \
            patch("custom_components.ivent.config_flow.IVentApiClient") as cloud:
        cloud.return_value.async_get_info = AsyncMock(return_value={"groups": []})
        result = await _pick(hass, "hybrid")
        assert result["step_id"] == "hybrid"
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "k", "location_id": location_id})


async def test_hybrid_flow_creates_entry_with_cloud_and_local_data(hass, fake_local):
    result = await _hybrid_to_local(hass)
    assert result["step_id"] == "local"
    assert "location_id" not in result["data_schema"].schema  # že znan iz oblaka
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"local_host": "192.168.1.179", "local_mac": MAC})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "i-Vent Hybrid"
    assert result["data"] == {"mode": "hybrid", "api_key": "k", "location_id": LOC,
                              "local_host": "192.168.1.179", "local_mac": MAC}
    assert result["result"].unique_id == LOC


async def test_hybrid_discovery_of_other_location_is_rejected(hass, fake_local):
    fake_local.discover.return_value = DiscoveredMaster("192.168.1.179", MAC, FAKE_LOC ^ 1, 1)
    result = await _hybrid_to_local(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"]["base"] == "location_mismatch"


async def test_hybrid_accepts_signed_cloud_location_id(hass, fake_local):
    signed = str(FAKE_LOC - (1 << 64)) if FAKE_LOC >= 1 << 63 else LOC
    result = await _hybrid_to_local(hass, signed)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"local_host": "h", "local_mac": MAC})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    fake_local.create.assert_called_once()
    assert fake_local.create.call_args.kwargs["location_id"] == FAKE_LOC


# --- rekonfiguracija / options ---------------------------------------------

async def test_reconfigure_cloud_to_local_replaces_data(hass, fake_local):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=LOC, version=4,
                            data={CONF_MODE: MODE_CLOUD, "api_key": "k", "location_id": LOC})
    entry.add_to_hass(hass)
    result = await _pick(hass, "local", "reconfigure", entry)
    assert result["step_id"] == "local" and "location_id" not in result["data_schema"].schema
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"local_host": "192.168.1.179", "local_mac": MAC})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert dict(entry.data) == {"mode": "local", "location_id": LOC,
                                "local_host": "192.168.1.179", "local_mac": MAC}


async def test_reconfigure_releases_running_socket_and_restores_on_failure(hass, fake_local):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=LOC, version=4, data={
        CONF_MODE: MODE_LOCAL, "location_id": LOC, "local_host": "192.168.1.179", "local_mac": MAC})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    fake_local.backend.async_ping.side_effect = IVentApiConnectionError("x")
    with patch.object(hass.config_entries, "async_unload", AsyncMock(return_value=True)) as unload, \
            patch.object(hass.config_entries, "async_setup", AsyncMock()) as setup:
        result = await _pick(hass, "local", "reconfigure", entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"local_host": "192.168.1.179", "local_mac": MAC})
    assert result["errors"]["base"] == "cannot_connect_local"
    unload.assert_awaited_once_with(entry.entry_id)
    setup.assert_awaited_once_with(entry.entry_id)  # vnos je spet naložen


async def test_options_flow_only_for_hybrid(hass):
    hybrid = MockConfigEntry(domain=DOMAIN, unique_id="h", data={CONF_MODE: MODE_HYBRID})
    hybrid.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(hybrid.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPT_INFO_FALLBACK: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY and hybrid.options[OPT_INFO_FALLBACK] is True
    cloud = MockConfigEntry(domain=DOMAIN, unique_id="c", data={CONF_MODE: MODE_CLOUD})
    cloud.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(cloud.entry_id)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_options"


# --- migracija, backend, diagnostika ----------------------------------------

async def test_migration_marks_old_entries_as_cloud(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=3, unique_id="x",
                            data={"api_key": "k", "location_id": "x"})
    entry.add_to_hass(hass)
    assert await ivent.async_migrate_entry(hass, entry)
    assert entry.version == 4 and entry.data[CONF_MODE] == MODE_CLOUD
    assert entry.data["api_key"] == "k"  # nič drugega se ne spremeni


def _entry(mode, **extra):
    data = {CONF_MODE: mode, "location_id": str(FAKE_LOC - (1 << 64)), "api_key": "k",
            CONF_LOCAL_HOST: "192.168.1.179", CONF_LOCAL_MAC: MAC}
    return MockConfigEntry(domain=DOMAIN, data=data, **extra)


async def test_backend_is_chosen_by_mode(hass):
    assert isinstance(ivent._build_backend(hass, MockConfigEntry(
        domain=DOMAIN, data={"api_key": "k", "location_id": "x"})), IVentApiClient)  # brez mode = oblak
    assert isinstance(ivent._build_backend(hass, _entry(MODE_CLOUD)), IVentApiClient)
    assert isinstance(ivent._build_backend(hass, _entry(MODE_LOCAL)), IVentLocalBackend)
    hybrid = ivent._build_backend(hass, _entry(MODE_HYBRID, options={OPT_INFO_FALLBACK: True}))
    assert isinstance(hybrid, IVentHybridBackend) and hybrid._info_fallback is True
    assert hybrid._local._client._location_id == FAKE_LOC  # predznačeno iz oblaka -> u64


def test_location_id_and_mac_are_redacted_in_diagnostics():
    assert {"location_id", "local_mac", "api_key"} <= TO_REDACT
