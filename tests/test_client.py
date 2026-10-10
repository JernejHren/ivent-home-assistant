"""Odjemalec + transport proti lažni lokaciji (en socket, prirejanje po messageId)."""
import asyncio

import pytest

from custom_components.ivent.ivent_local import const as c
from custom_components.ivent.ivent_local.client import IVentLocalClient
from custom_components.ivent.ivent_local.transport import (
    IVentLocalDeviceError, IVentLocalTimeout, IVentLocalUnsupported, UdpTransport,
)

from .conftest import FAKE_LOC, FAKE_MACS
from .test_decode import DNEVNA, TILEN

BYPASS3 = {"special_mode": "IVentSpecialOff", "work_mode": "IVentBypass3",
           "bypass_rotation": "BypassForward", "remote_control_work_mode": "Bypass",
           "remote_control_speed": 3}


def _group(info, gid):
    return next(g for g in info["groups"] if g["id"] == gid)


async def test_ping_returns_network_hash(lab):
    assert await lab.client.async_ping() == 2434161996280914071


async def test_get_info_matches_cloud_shape(lab, cloud_info):
    info = await lab.client.async_get_info()
    cloud = {g["id"]: g for g in cloud_info["groups"]}
    assert {g["id"] for g in info["groups"]} == set(cloud)
    for g in info["groups"]:
        cg = cloud[g["id"]]
        for k in ("name", "led_work_mode", "buzzer_work_mode", "enable_schedule"):
            assert g[k] == cg[k], k
        assert [d["mac_address"] for d in g["devices"]] == [d["mac_address"] for d in cg["devices"]]


async def test_modify_group_remote_is_read_modify_write(lab):
    """Hitrost 3 na Dnevni: najprej ReadGroup, nato ModifyGroup; Tilen nespremenjen."""
    before = _group(await lab.client.async_get_info(), TILEN)
    lab.fake.requests.clear()
    await lab.client.async_modify_group(DNEVNA, {"remote_work_mode": BYPASS3})
    assert [r[0] for r in lab.fake.requests] == [c.T_READ_GROUP, c.T_MODIFY_GROUP]
    info = await lab.client.async_get_info()
    d = _group(info, DNEVNA)["remote"]
    assert (d["work_mode"], d["remote_control_speed"]) == ("IVentBypass3", 3)
    assert d["work_mode_changed_at"] > 1790790098  # naprava je osvežila čas
    assert _group(info, TILEN) == before            # druga skupina se ne dotakne


async def test_special_mode_ends_at_set_by_device(lab):
    boost = {**BYPASS3, "work_mode": "IVentBypass2", "remote_control_speed": 2,
             "special_mode": "IVentBoost"}
    await lab.client.async_modify_group(DNEVNA, {"remote_work_mode": boost})
    r = _group(await lab.client.async_get_info(), DNEVNA)["remote"]
    assert r["special_mode"] == "IVentBoost" and r["work_mode"] == "IVentBypass2"  # overlay
    assert r["special_mode_ends_at"] - r["work_mode_changed_at"] == 3600


async def test_led_write_needs_no_read(lab):
    lab.fake.requests.clear()
    await lab.client.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    assert [r[0] for r in lab.fake.requests] == [c.T_MODIFY_GROUP]
    assert _group(await lab.client.async_get_info(), DNEVNA)["led_work_mode"] == "LedOnMode"


async def test_rename_group_and_buzzer(lab):
    await lab.client.async_modify_group(TILEN, {"name": "Tilen2", "buzzer_mode": "BuzzerOnMode"})
    g = _group(await lab.client.async_get_info(), TILEN)
    assert (g["name"], g["buzzer_work_mode"]) == ("Tilen2", "BuzzerOnMode")


async def test_modify_device_goes_direct(lab):
    mac = FAKE_MACS[1]
    await lab.client.async_modify_device(mac, {"reverse_flow": False, "name": "ivent-test"})
    dev = next(d for d in lab.fake.devices if d["mac_address"] == mac)
    assert (dev["reverse_flow"], dev["device_name"]) == (False, "ivent-test")
    last = lab.fake.requests[-1]
    assert last[0] == c.T_MODIFY_DEVICE and last[1] == 0  # forward=0


async def test_modify_device_falls_back_to_master_with_forward(lab):
    lab.fake.ignore_direct = True
    mac = FAKE_MACS[2]
    await lab.client.async_modify_device(mac, {"name": "via-master"})
    assert next(d for d in lab.fake.devices if d["mac_address"] == mac)["device_name"] == "via-master"
    assert lab.fake.requests[-1][1] == 1  # forward=1


async def test_beacon_via_master(lab):
    await lab.client.async_beacon(FAKE_MACS[1])
    assert lab.fake.beacons == [FAKE_MACS[1]]
    assert lab.fake.requests[-1][:2] == (c.T_ACTION, 1)


async def test_lost_packet_is_retried_with_same_message_id(lab):
    lab.fake.drop_next = 1
    assert await lab.client.async_ping() == 2434161996280914071
    assert len([r for r in lab.fake.requests if r[0] == c.T_MASTER_PING]) == 2


async def test_timeout_when_all_attempts_lost(lab):
    lab.fake.drop_next = 99
    with pytest.raises(IVentLocalTimeout):
        await lab.client.async_ping()
    assert len(lab.fake.requests) == 3  # 1 + 2 ponovitvi


async def test_wrong_location_id_gets_no_answer(lab):
    bad = IVentLocalClient(lab.transport, location_id=FAKE_LOC ^ 1, master_host="127.0.0.1",
                           master_mac=lab.fake.master_mac)
    with pytest.raises(IVentLocalTimeout):
        await bad.async_ping()


async def test_device_error_code_is_raised(lab):
    lab.fake.force_error = 3
    with pytest.raises(IVentLocalDeviceError) as err:
        await lab.client.async_modify_group(DNEVNA, {"led_mode": "LedOnMode"})
    assert err.value.code == 3


async def test_unknown_group_raises_device_error(lab):
    with pytest.raises(IVentLocalDeviceError):
        await lab.client.async_read_group(0xDEAD)


async def test_concurrent_requests_are_matched_by_message_id(lab):
    hash_, groups, devices = await asyncio.gather(
        lab.client.async_ping(), lab.client.async_get_groups(), lab.client.async_get_devices())
    assert hash_ == 2434161996280914071 and len(groups) == 3 and len(devices) == 3


async def test_schedules_and_create_group_unsupported(lab):
    for coro in (lab.client.async_get_schedules(), lab.client.async_modify_schedules([]),
                 lab.client.async_create_group("x")):
        with pytest.raises(IVentLocalUnsupported):
            await coro


async def test_push_remote_is_deduplicated_to_one_event(lab):
    events = []
    lab.client.start_push(on_remote=lambda gid, r: events.append((gid, r)))
    await lab.client.async_get_info()  # naslov odjemalca je zdaj znan fake-u
    await lab.client.async_modify_group(DNEVNA, {"remote_work_mode": BYPASS3})
    await asyncio.sleep(0.1)
    assert len(events) == 1  # 3 enake ponovitve -> 1 dogodek
    gid, remote = events[0]
    assert gid == DNEVNA and remote["work_mode"] == "IVentBypass3"


async def test_push_ignores_foreign_location(lab):
    events = []
    lab.client.start_push(on_remote=lambda gid, r: events.append(gid))
    lab.fake.location_id = FAKE_LOC ^ 7
    addr = ("127.0.0.1", lab.transport.local_port)
    lab.fake.broadcast_remote(DNEVNA, addr)
    await asyncio.sleep(0.1)
    assert events == []


async def test_push_master_advertise_reports_every_advert(lab):
    seen = []
    lab.client.start_push(on_master=seen.append)
    addr = ("127.0.0.1", lab.transport.local_port)
    for _ in range(3):
        lab.fake.advertise(addr)
    lab.fake.advertise(addr, ip="127.0.0.9")  # menjava Masterja / IP
    await asyncio.sleep(0.1)
    assert [m["ip"] for m in seen] == ["127.0.0.1"] * 3 + ["127.0.0.9"]
    assert seen[0]["mac"] == FAKE_MACS[0]


async def test_unsubscribe_stops_events(lab):
    events = []
    off = lab.client.start_push(on_master=events.append)
    off()
    lab.fake.advertise(("127.0.0.1", lab.transport.local_port))
    await asyncio.sleep(0.1)
    assert events == []


async def test_stopped_transport_rejects_requests():
    t = UdpTransport(bind_host="127.0.0.1", bind_port=0, port=9, timeout=0.1, retries=0)
    from custom_components.ivent.ivent_local.transport import IVentLocalError
    with pytest.raises(IVentLocalError):
        await t.request("127.0.0.1", b"x", 1)
