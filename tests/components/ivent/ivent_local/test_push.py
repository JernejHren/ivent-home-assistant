"""Push dogodki: MasterAdvertise (tip 2) in RemoteControl (tip 6) iz živih zajemov."""
import collections

from custom_components.ivent.ivent_local import const as c
from custom_components.ivent.ivent_local import convert as cv
from custom_components.ivent.ivent_local import protocol as p

from .conftest import FAKE_LOC, FAKE_MACS


def _packets(events, mtype):
    return [p.parse_packet(bytes.fromhex(e["hex"])) for e in events if e["type"] == mtype]


def test_all_events_parse_as_legacy_with_location(events):
    for e in events:
        pk = p.parse_packet(bytes.fromhex(e["hex"]))
        assert pk.legacy and pk.msg_type == e["type"] and pk.location_id == FAKE_LOC


def test_master_advertise_identifies_master(events):
    ads = [cv.decode_master_advertise(pk.body) for pk in _packets(events, c.T_MASTER_ADVERTISE)]
    assert ads
    assert {a["mac"] for a in ads} == {FAKE_MACS[0]}
    assert {a["ip"] for a in ads} == {"192.168.1.179"}
    assert {a["became_master"] for a in ads} == {1790396130}


def test_remote_control_events_come_in_threes(events):
    seen = collections.Counter()
    for pk in _packets(events, c.T_REMOTE_CONTROL):
        gid, r = cv.decode_remote_control(pk.body)
        seen[(gid, r["work_mode_changed_at"], r["special_mode"], r["work_mode"],
              r["remote_control_speed"])] += 1
    # UDP brez potrditve: vsak dogodek 3x; izjema je dogodek na meji zajema
    assert len(seen) == 49
    assert set(seen.values()) <= {2, 3} and list(seen.values()).count(2) == 1
    assert {k[0] for k in seen} == {1, 0x3165197B, 0x4D6D0DC1}


def test_special_mode_ends_at_is_changed_at_plus_profile_duration(events):
    durations = {"IVentBoost": 3600, "IVentSnooze": 3600, "IVentNight1": 3600}
    checked = 0
    for pk in _packets(events, c.T_REMOTE_CONTROL):
        _, r = cv.decode_remote_control(pk.body)
        if r["special_mode"] in durations:
            assert r["special_mode_ends_at"] - r["work_mode_changed_at"] == durations[r["special_mode"]]
            checked += 1
    assert checked >= 5


def test_recuperation_is_seen_with_normal_remote_mode(events):
    modes = set()
    for pk in _packets(events, c.T_REMOTE_CONTROL):
        _, r = cv.decode_remote_control(pk.body)
        modes.add((r["work_mode"], r["remote_control_work_mode"]))
    assert ("IVentRecuperation2", "Normal") in modes and ("IVentBypass3", "Bypass") in modes
