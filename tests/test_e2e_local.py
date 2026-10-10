"""E2E: pravi async_setup_entry / unload v lokalnem načinu nad lažno lokacijo."""
import asyncio
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.ivent as ivent
from custom_components.ivent.const import (
    CONF_LOCAL_HOST, CONF_LOCAL_MAC, CONF_MODE, DOMAIN, MODE_LOCAL,
)
from custom_components.ivent.local_backend import IVentLocalBackend

from .conftest import FAKE_LOC, FAKE_MACS
from .test_decode import DNEVNA, TILEN

LOC = str(FAKE_LOC)


def _entry(mode, **extra):
    data = {CONF_MODE: mode, "location_id": LOC, "api_key": "k",
            CONF_LOCAL_HOST: "192.168.1.179", CONF_LOCAL_MAC: FAKE_MACS[0]}
    return MockConfigEntry(domain=DOMAIN, data=data, **extra)


async def test_local_entry_end_to_end(hass, lab):
    """Vnos v lokalnem načinu: entitete, ukaz skupine 1 (fan-out), push in unload."""
    entry = _entry(MODE_LOCAL, unique_id=LOC, version=4)
    entry.add_to_hass(hass)
    backend = IVentLocalBackend(lab.client, lab.transport)
    with patch.object(IVentLocalBackend, "create", return_value=backend):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        assert set(coordinator.data.group_ids) == {1, DNEVNA, TILEN}
        assert coordinator.data.schedules_by_id == {}  # lokalno brez urnikov, brez napak

        # vse naprave so povezane s servisno napravo (via_device_id na novem, via_device na starem HA)
        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        hub = next(d for d in devices if (DOMAIN, entry.entry_id) in d.identifiers)
        children = [d for d in devices if d.id != hub.id]
        assert len(children) == 3 + 3  # 3 skupine + 3 fizične enote
        assert all(d.via_device_id == hub.id for d in children)

        reg = er.async_get(hass)
        boost_all = reg.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_1_iventboost")
        assert boost_all
        await hass.services.async_call("switch", "turn_on", {"entity_id": boost_all}, blocking=True)
        assert lab.fake.groups[DNEVNA]["remote"]["special_mode"] == "IVentBoost"
        assert lab.fake.groups[TILEN]["remote"]["special_mode"] == "IVentBoost"  # fan-out
        # push potrdi stanje v koordinatorju brez dodatne poizvedbe
        await asyncio.sleep(0.2)
        assert coordinator.data.groups_by_id[DNEVNA].remote["special_mode"] == "IVentBoost"

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_config_flow_validates_with_real_backend(hass, lab):
    """Lokalni korak preveri povezavo z resničnim IVentLocalBackend (ne mockom)."""
    from homeassistant.data_entry_flow import FlowResultType

    backend = IVentLocalBackend(lab.client, lab.transport)
    with patch.object(IVentLocalBackend, "create", return_value=backend) as create, \
            patch("custom_components.ivent.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "local"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"local_host": "127.0.0.1", "local_mac": FAKE_MACS[0], "location_id": LOC})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    create.assert_called_once()
    assert create.call_args.kwargs["location_id"] == FAKE_LOC
    assert lab.fake.requests[0][0] == 279  # MasterPing je res šel proti (lažni) napravi


async def test_options_change_reloads_without_update_listener_warning(hass, lab, caplog):
    """HA 2026.x: brez update listenerja (OptionsFlowWithReload); star HA: listener + primerjava."""
    from custom_components.ivent.config_flow import OPTIONS_AUTO_RELOAD
    from custom_components.ivent.const import MODE_HYBRID, OPT_INFO_FALLBACK
    from unittest.mock import AsyncMock, MagicMock

    entry = _entry(MODE_HYBRID, unique_id=LOC, version=4)
    entry.add_to_hass(hass)
    backend = IVentLocalBackend(lab.client, lab.transport)
    cloud = MagicMock()
    for name in ("async_get_info", "async_get_schedules", "async_modify_schedules",
                 "async_create_group", "async_modify_group", "async_modify_device"):
        setattr(cloud, name, AsyncMock(return_value=None))
    cloud.async_get_schedules.return_value = []
    with patch.object(IVentLocalBackend, "create", return_value=backend), \
            patch("custom_components.ivent.IVentApiClient", return_value=cloud):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # nov HA: noben update listener; star HA: točno eden
        assert len(entry.update_listeners) == (0 if OPTIONS_AUTO_RELOAD else 1)

        with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_, \
                patch.object(hass.config_entries, "async_schedule_reload") as schedule:
            result = await hass.config_entries.options.async_init(entry.entry_id)
            await hass.config_entries.options.async_configure(
                result["flow_id"], {OPT_INFO_FALLBACK: True})
            await hass.async_block_till_done()
            assert entry.options[OPT_INFO_FALLBACK] is True
            reloads = schedule.call_count + reload_.await_count
            assert reloads == 1  # točno eno ponovno nalaganje

            # nespremenjene nastavitve ne sprožijo ponovnega nalaganja
            result = await hass.config_entries.options.async_init(entry.entry_id)
            await hass.config_entries.options.async_configure(
                result["flow_id"], {OPT_INFO_FALLBACK: True})
            await hass.async_block_till_done()
            assert schedule.call_count + reload_.await_count == reloads
        await hass.config_entries.async_unload(entry.entry_id)
    assert "update listener" not in caplog.text
