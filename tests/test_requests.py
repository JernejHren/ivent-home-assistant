"""Sestavljanje zahtev: oblika paketa, setFields, prevod cloud payloadov."""
import pytest

from custom_components.ivent.ivent_local import const as c
from custom_components.ivent.ivent_local import convert as cv
from custom_components.ivent.ivent_local import protocol as p
from custom_components.ivent.ivent_local import wire

from .conftest import FAKE_LOC, FAKE_MACS
from .test_decode import DNEVNA, TILEN, _groups

MAC = cv.mac_from_str(FAKE_MACS[0])
H = p.Header(FAKE_LOC, MAC)
NOW = 1790800000
MID = 0x12345678


def _body(pkt, field):
    packet = p.parse_packet(pkt)
    return packet, wire.parse_fields(wire.get(packet.body, field))


def test_header_layout():
    pkt = p.build_read_group(H, MID, DNEVNA, NOW)
    packet, inner = _body(pkt, c.F_READ_GROUP[0])
    assert (packet.msg_type, packet.message_id, packet.location_id) == (275, MID, FAKE_LOC)
    assert inner == [(1, 5, DNEVNA)]  # groupId je fixed32
    kinds = {f: w for f, w, _ in packet.body}
    assert kinds[1] == 1 and kinds[2] == 5  # locationId fixed64, messageId fixed32
    assert wire.get(packet.body, 5) == MAC and wire.get(packet.body, 7) == 2


def test_masterlist_payload():
    _, inner = _body(p.build_masterlist(H, MID, devices=False, offset=0, limit=16, now=NOW), 79)
    assert inner == [(1, 0, 0), (2, 0, 16)]
    packet, _ = _body(p.build_masterlist(H, MID, devices=True, now=NOW), 81)
    assert packet.msg_type == c.T_MASTERLIST_DEVICES


def _remote(reads, gid):
    pk = p.parse_packet(reads["groups"])
    _, items = cv.decode_masterlist(wire.get(pk.body, c.F_GROUPS[1]), devices=False)
    for raw in wire.get_all(wire.parse_fields(wire.get(pk.body, c.F_GROUPS[1])), 2):
        f = wire.parse_fields(raw)
        if wire.get(f, 1) == gid:
            return wire.parse_fields(wire.get(f, 3))
    raise AssertionError(gid)


BYPASS3 = {"special_mode": "IVentSpecialOff", "work_mode": "IVentBypass3",
           "bypass_rotation": "BypassForward", "remote_control_work_mode": "Bypass",
           "remote_control_speed": 3}


@pytest.mark.parametrize("gid,length", [(DNEVNA, 79), (TILEN, 83)])
def test_modify_group_matches_captured_packet_shape(reads, gid, length):
    """Dolžini 79/83 B in setFields=258 (fixed64) kot pri ujetih paketih uradne appke."""
    fields = p.group_fields_from_cloud({"remote_work_mode": BYPASS3}, _remote(reads, gid))
    pkt = p.build_modify_group(H, MID, gid, fields, NOW)
    assert len(pkt) == length
    packet, inner = _body(pkt, c.F_REQ_MODIFY_GROUP)
    assert packet.msg_type == c.T_MODIFY_GROUP
    assert wire.get(inner, 1) == gid
    assert [(w, v) for f, w, v in inner if f == 99] == [(1, 258)]
    remote = {f: v for f, _, v in wire.parse_fields(wire.get(inner, 8))}
    assert (remote[1], remote[2], remote[3], remote[4], remote[5]) == (0, 34, 1, 2, 3)
    assert 8 not in remote and 9 not in remote  # trajanji nastavi naprava


def test_modify_group_keeps_stale_f6_f7_from_read(reads):
    cur = _remote(reads, TILEN)
    fields = p.group_fields_from_cloud({"remote_work_mode": BYPASS3}, cur)
    new = {f: v for f, _, v in wire.parse_fields(wire.get(fields, 8))}
    old = {f: v for f, _, v in cur}
    assert new[6] == old[6] == 1790527650 and new[7] == old[7]


def test_led_buzzer_name_set_fields():
    f = p.group_fields_from_cloud({"led_mode": "LedOnMode"}, None)
    assert f == [(6, 0, 1)]
    _, inner = _body(p.build_modify_group(H, MID, DNEVNA, f, NOW), 88)
    assert wire.get(inner, 99) == (1 << 1) | (1 << 6) == 66
    f = p.group_fields_from_cloud({"buzzer_mode": "BuzzerOnMode"}, None)
    _, inner = _body(p.build_modify_group(H, MID, DNEVNA, f, NOW), 88)
    assert wire.get(inner, 99) == 130
    f = p.group_fields_from_cloud({"name": "Čiščenje"}, None)
    assert f == [(3, 2, "Čiščenje".encode())]


def test_modify_device_set_fields():
    f = p.device_fields_from_cloud({"reverse_flow": True})
    _, inner = _body(p.build_modify_device(H, MID, f, NOW), c.F_REQ_MODIFY_DEVICE)
    assert wire.get(inner, 1) == 1 and wire.get(inner, 99) == 2
    f = p.device_fields_from_cloud({"name": "ivent-test"})
    _, inner = _body(p.build_modify_device(H, MID, f, NOW), c.F_REQ_MODIFY_DEVICE)
    assert wire.get(inner, 3) == b"ivent-test" and wire.get(inner, 99) == 8


def test_action_beacon():
    packet, inner = _body(p.build_action(H, MID, c.ACTION_BEACON, NOW), c.F_REQ_ACTION)
    assert packet.msg_type == 4362 and inner == [(1, 0, 1)]


def test_unknown_enum_names_are_rejected():
    with pytest.raises(p.ProtocolError):
        p.remote_changes_from_cloud({"work_mode": "IVentBypass9"})
    with pytest.raises(p.ProtocolError):
        p.group_fields_from_cloud({"led_mode": "nope"}, None)


def test_response_error_decoding():
    body = wire.enc_varint_field(1, 0)  # NoError
    pkt = p.wrap(c.T_RESPONSE_EMPTY, H.encode(MID, NOW) + wire.enc_bytes_field(c.F_RES_EMPTY, body))
    packet = p.parse_packet(pkt)
    assert p.response_error(packet) == 0
    assert p.response_error(p.parse_packet(p.build_read_group(H, MID, 1, NOW))) is None


def test_garbage_is_not_a_packet():
    for bad in (b"", b"\xff\xff", wire.enc_varint_field(1, 5)):
        with pytest.raises(p.ProtocolError):
            p.parse_packet(bad)


def test_enum_tables_are_bijective():
    for fwd, rev in ((c.WORK_MODE, c.WORK_MODE_NUM), (c.SPECIAL_MODE, c.SPECIAL_MODE_NUM),
                     (c.LED_MODE, c.LED_MODE_NUM), (c.BUZZER_MODE, c.BUZZER_MODE_NUM)):
        assert {rev[v] for v in fwd.values()} == set(fwd)
