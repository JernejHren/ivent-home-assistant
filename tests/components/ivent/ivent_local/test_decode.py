"""Dekodiranje resničnih (anonimiziranih) odgovorov naprave."""
from custom_components.ivent.ivent_local import const as c
from custom_components.ivent.ivent_local import convert as cv
from custom_components.ivent.ivent_local import protocol as p
from custom_components.ivent.ivent_local.wire import get

from .conftest import FAKE_LOC, FAKE_MACS

DNEVNA, TILEN = 0x3165197B, 0x4D6D0DC1


def _res(reads, key, field):
    pk = p.parse_packet(reads[key])
    assert not pk.legacy
    assert pk.location_id == FAKE_LOC
    return pk, get(pk.body, field)


def _groups(reads):
    _, res = _res(reads, "groups", c.F_GROUPS[1])
    return cv.decode_masterlist(res, devices=False)


def _devices(reads):
    _, res = _res(reads, "devices", c.F_DEVICES[1])
    return cv.decode_masterlist(res, devices=True)


def test_response_types_are_request_plus_flag(reads):
    assert p.parse_packet(reads["ping"]).msg_type == c.T_MASTER_PING | c.RESPONSE_FLAG
    assert p.parse_packet(reads["groups"]).msg_type == c.T_MASTERLIST_GROUPS | c.RESPONSE_FLAG
    assert p.parse_packet(reads["devices"]).msg_type == c.T_MASTERLIST_DEVICES | c.RESPONSE_FLAG


def test_ping_version_location(reads):
    _, res = _res(reads, "ping", c.F_PING[1])
    assert get(cv.parse_fields(res), 1) == 2434161996280914071
    _, res = _res(reads, "version", c.F_VERSION[1])
    assert cv.parse_fields(res)[0][2] == 1
    _, res = _res(reads, "location", c.F_LOCATION[1])
    prof = cv.parse_fields(get(cv.parse_fields(res), 1))
    assert get(prof, 2) == b"CET-1CEST,M3.5.0,M10.5.0/3"


def test_groups(reads):
    total, groups = _groups(reads)
    assert total == len(groups) == 3
    by_id = {g["id"]: g for g in groups}
    assert set(by_id) == {1, DNEVNA, TILEN}
    d = by_id[DNEVNA]
    assert d["name"] == "Dnevna"
    assert d["remote"] == {
        "special_mode": "IVentSpecialOff", "work_mode": "IVentBypass2",
        "bypass_rotation": "BypassForward", "remote_control_work_mode": "Bypass",
        "remote_control_speed": 2, "special_mode_ends_at": 0,
        "work_mode_changed_at": 1790790098,
    }
    t = by_id[TILEN]
    assert t["remote"]["work_mode"] == "IVentBypass1"
    # zastarel konec posebnega načina ostane (pomen ima samo ob special_mode != 0)
    assert t["remote"]["special_mode_ends_at"] == 1790527650
    assert t["profile"]["bypassTime"] == 1800 and t["profile"]["doNotDisturbStart"] == 22
    assert by_id[1]["remote"]["work_mode"] == "IVentRecuperation1"
    assert by_id[1]["remote"]["work_mode_changed_at"] is None  # nikoli spremenjeno


def test_devices(reads):
    total, devs = _devices(reads)
    assert total == len(devs) == 3
    by_mac = {d["mac_address"]: d for d in devs}
    assert set(by_mac) == set(FAKE_MACS)
    a = by_mac[FAKE_MACS[0]]
    assert (a["group_id"], a["rssi"], a["alive"], a["reverse_flow"]) == (DNEVNA, -54, True, False)
    assert (a["ip"], a["firmware_version"], a["status_esp"]) == ("192.168.1.179", 204070000, 1024)
    assert a["device_name"] == FAKE_MACS[0]  # ime = MAC, ne pravi MAC
    assert by_mac[FAKE_MACS[1]]["reverse_flow"] is True


def test_sensor_signed_speed_and_status(reads):
    for key, speed in (("sensor [98:cd:ac:00:00:41 192.168.1.179]", 46),
                       ("sensor [98:cd:ac:00:00:43 192.168.1.211]", -44)):
        _, res = _res(reads, key, c.F_SENSOR[1])
        f = cv.parse_fields(res)
        assert cv.to_signed64(get(f, 6)) == speed  # predznak = smer pretoka
        assert get(f, 24) == 1024  # statusEsp: bit 1024 = filter


def test_static_info(reads):
    _, res = _res(reads, "static [98:cd:ac:00:00:42 192.168.1.216]", c.F_STATIC[1])
    f = cv.parse_fields(res)
    assert cv.mac_to_str(get(f, 1)) == FAKE_MACS[1]
    assert get(f, 3) == TILEN and get(f, 6) == 204070000 and get(f, 8) == b"v3.4-75-gc858b1ba"


def test_build_info_matches_cloud_shape(reads, cloud_info):
    """Stanje (09-30) in oblak (10-02) se razlikujeta le po času; struktura mora biti ista."""
    _, groups = _groups(reads)
    _, devices = _devices(reads)
    info = cv.build_info(groups, devices)
    cloud = {g["id"]: g for g in cloud_info["groups"]}
    assert {g["id"] for g in info["groups"]} == set(cloud)
    for g in info["groups"]:
        cg = cloud[g["id"]]
        assert g["name"] == cg["name"]
        assert set(g) == set(cg)
        shared = set(g["remote"]) & set(cg["remote"])
        assert {"work_mode", "special_mode", "remote_control_speed", "bypass_rotation",
                "remote_control_work_mode"} <= shared
        assert g["remote"]["work_mode"].startswith("IVent")
        assert [d["mac_address"] for d in g["devices"]] == [d["mac_address"] for d in cg["devices"]]
        for d, cd in zip(g["devices"], cg["devices"]):
            for k in ("reverse_flow", "device_name", "firmware_version", "status_esp", "alive"):
                assert d[k] == cd[k], k
