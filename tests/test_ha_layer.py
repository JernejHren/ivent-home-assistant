"""Adapter, hibridni backend in koordinator (push + adaptivni polling) nad lažno lokacijo."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ivent import coordinator as coord_mod
from custom_components.ivent.api import (
    IVentApiClientError, IVentApiConnectionError, IVentApiUnsupportedError,
)
from custom_components.ivent.backend import IVentBackend, IVentPushBackend
from custom_components.ivent.coordinator import (
    SCAN_INTERVAL, SCAN_INTERVAL_PUSH, IVentCoordinator,
)
from custom_components.ivent.local_backend import IVentHybridBackend, IVentLocalBackend

from .conftest import FAKE_MACS
from .test_client import BYPASS3
from .test_decode import DNEVNA, TILEN


@pytest.fixture
def local(lab):
    return IVentLocalBackend(lab.client, lab.transport)


def _cloud():
    cloud = MagicMock()
    for name in ("async_get_info", "async_get_schedules", "async_modify_schedules",
                 "async_create_group", "async_modify_group", "async_modify_device"):
        setattr(cloud, name, AsyncMock(return_value=None))
    cloud.async_get_info.return_value = {"groups": []}
    cloud.async_get_schedules.return_value = [{"name": "x", "schedules": []}]
    return cloud


# --- adapter ---------------------------------------------------------------

def test_local_backend_satisfies_protocols(local):
    assert isinstance(local, IVentBackend) and isinstance(local, IVentPushBackend)
    assert isinstance(IVentHybridBackend(local, None), IVentBackend)


async def test_errors_are_mapped_to_integration_errors(lab, local):
    lab.fake.force_error = 3
    with pytest.raises(IVentApiClientError) as err:
        await local.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    assert not isinstance(err.value, IVentApiConnectionError)  # zavrnitev naprave != povezava
    lab.fake.drop_next = 99
    with pytest.raises(IVentApiConnectionError):
        await local.async_get_info()
    with pytest.raises(IVentApiUnsupportedError):
        await local.async_get_schedules()
    with pytest.raises(IVentApiClientError):
        await local.async_modify_group(DNEVNA, {"led_mode": "nope"})


async def test_local_info_normalizes_like_cloud_data(local):
    data = coord_mod._normalize((await local.async_get_info())["groups"], [])
    assert data.group_ids == [1, DNEVNA, TILEN]
    assert set(data.all_device_macs) == set(FAKE_MACS)
    assert data.devices_by_mac[FAKE_MACS[1]].group_id == TILEN


# --- hibrid ----------------------------------------------------------------

async def test_hybrid_state_and_writes_stay_local(lab, local):
    cloud = _cloud()
    hybrid = IVentHybridBackend(local, cloud)
    assert len((await hybrid.async_get_info())["groups"]) == 3
    await hybrid.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    await hybrid.async_modify_device(FAKE_MACS[1], {"name": "n"})
    cloud.async_get_info.assert_not_called()
    cloud.async_modify_group.assert_not_called()
    cloud.async_modify_device.assert_not_called()


async def test_hybrid_schedules_and_create_group_use_cloud(local):
    cloud = _cloud()
    hybrid = IVentHybridBackend(local, cloud)
    assert await hybrid.async_get_schedules() == [{"name": "x", "schedules": []}]
    await hybrid.async_modify_schedules([])
    await hybrid.async_create_group("g")
    cloud.async_modify_schedules.assert_awaited_once()
    cloud.async_create_group.assert_awaited_once_with("g")


async def test_hybrid_without_cloud_reports_unsupported(local):
    hybrid = IVentHybridBackend(local, None)
    for coro in (hybrid.async_get_schedules(), hybrid.async_modify_schedules([]),
                 hybrid.async_create_group("g")):
        with pytest.raises(IVentApiUnsupportedError):
            await coro


async def test_hybrid_write_falls_back_to_cloud_only_when_master_unreachable(lab, local):
    cloud = _cloud()
    hybrid = IVentHybridBackend(local, cloud)
    lab.fake.drop_next = 99
    await hybrid.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    cloud.async_modify_group.assert_awaited_once_with(DNEVNA, {"led_mode": "LedOnMode"})
    cloud.async_modify_group.reset_mock()
    lab.fake.drop_next = 0
    lab.fake.force_error = 3  # naprava zavrne: brez ponovitve prek oblaka
    with pytest.raises(IVentApiClientError):
        await hybrid.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    cloud.async_modify_group.assert_not_called()


async def test_hybrid_write_without_cloud_propagates_connection_error(lab, local):
    lab.fake.drop_next = 99
    with pytest.raises(IVentApiConnectionError):
        await IVentHybridBackend(local, None).async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})


async def test_hybrid_info_fallback_is_opt_in(lab, local):
    cloud = _cloud()
    lab.fake.drop_next = 99
    with pytest.raises(IVentApiConnectionError):
        await IVentHybridBackend(local, cloud).async_get_info()
    lab.fake.drop_next = 99
    info = await IVentHybridBackend(local, cloud, info_fallback=True).async_get_info()
    assert info == {"groups": []}


# --- koordinator -----------------------------------------------------------



@pytest.fixture
async def coordinator(hass, lab, local):
    entry = MockConfigEntry(domain="ivent", data={})
    entry.add_to_hass(hass)
    coord = IVentCoordinator(hass, IVentHybridBackend(local, None), entry)
    await coord.async_start_push()
    await coord.async_refresh()  # (first_refresh zahteva stanje SETUP_IN_PROGRESS)
    assert coord.last_update_success
    yield coord
    await coord.async_stop_push()
    await coord.async_shutdown()


def _client_addr(lab):
    return lab.fake.requests[-1][3]


async def test_first_refresh_without_schedules_is_quiet(coordinator, caplog):
    assert set(coordinator.data.group_ids) == {1, DNEVNA, TILEN}
    assert coordinator.data.schedules_by_id == {}
    with caplog.at_level(logging.WARNING):
        await coordinator.async_refresh()
    assert "schedules" not in caplog.text.lower()


async def test_push_updates_state_without_polling(hass, lab, coordinator):
    await lab.client.async_read_group(DNEVNA)  # naslov odjemalca za fake
    fake_g = lab.fake.groups[DNEVNA]["remote"]
    fake_g.update(work_mode="IVentBypass3", remote_control_speed=3, work_mode_changed_at=1790999999)
    updates = []
    coordinator.async_add_listener(lambda: updates.append(1))
    addr = _client_addr(lab)
    lab.fake.requests.clear()
    lab.fake.broadcast_remote(DNEVNA, addr)
    await asyncio.sleep(0.1)
    remote = coordinator.data.groups_by_id[DNEVNA].remote
    assert (remote["work_mode"], remote["remote_control_speed"]) == ("IVentBypass3", 3)
    assert len(updates) == 1                      # 3 ponovitve -> 1 posodobitev
    assert lab.fake.requests == []                # brez ene same poizvedbe
    assert coordinator.data.groups_by_id[TILEN].remote["work_mode"] == "IVentBypass1"


async def test_push_for_unknown_group_requests_refresh(hass, lab, coordinator):
    lab.fake.groups[0xBEEF] = {**lab.fake.groups[DNEVNA], "id": 0xBEEF}
    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
        lab.fake.broadcast_remote(0xBEEF, _client_addr(lab))
        await asyncio.sleep(0.1)
    refresh.assert_awaited()


async def test_adaptive_interval_follows_master_adverts(lab, coordinator):
    assert coordinator.update_interval == SCAN_INTERVAL and not coordinator.push_active
    lab.fake.advertise(_client_addr(lab))
    await asyncio.sleep(0.1)
    assert coordinator.push_active and coordinator.update_interval == SCAN_INTERVAL_PUSH
    with patch.object(coord_mod, "monotonic", return_value=coord_mod.monotonic() + 60):
        assert not coordinator.push_active
        await coordinator.async_refresh()
        assert coordinator.update_interval == SCAN_INTERVAL  # broadcast je utihnil


async def test_master_change_triggers_refresh_but_repeat_does_not(lab, coordinator):
    addr = _client_addr(lab)
    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
        for _ in range(3):
            lab.fake.advertise(addr)
        await asyncio.sleep(0.1)
        refresh.assert_not_awaited()
        lab.fake.advertise(addr, ip="127.0.0.9")
        await asyncio.sleep(0.1)
        refresh.assert_awaited()
    assert coordinator.master_info["ip"] == "127.0.0.9"


async def test_stop_push_unsubscribes(lab, coordinator):
    addr = _client_addr(lab)
    await coordinator.async_stop_push()
    lab.fake.advertise(addr)
    await asyncio.sleep(0.1)
    assert coordinator.master_info is None


async def test_cloud_client_has_no_push_and_keeps_polling(hass):
    entry = MockConfigEntry(domain="ivent", data={})
    entry.add_to_hass(hass)
    cloud = _cloud()
    coord = IVentCoordinator(hass, cloud, entry)
    assert await coord.async_start_push() is False
    assert coord.update_interval == SCAN_INTERVAL
    await coord.async_shutdown()


async def test_unopenable_socket_means_not_ready(hass, local):
    entry = MockConfigEntry(domain="ivent", data={})
    entry.add_to_hass(hass)
    coord = IVentCoordinator(hass, local, entry)
    with patch.object(local, "async_start", AsyncMock(side_effect=OSError("address in use"))):
        with pytest.raises(ConfigEntryNotReady):
            await coord.async_start_push()
    await coord.async_shutdown()
