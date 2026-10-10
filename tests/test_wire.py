import pytest

from custom_components.ivent.ivent_local import wire


def test_negative_varint_is_ten_bytes_and_roundtrips():
    enc = wire.enc_varint(-54)
    assert len(enc) == 10
    (f,) = wire.parse_fields(wire.enc_tag(3, 0) + enc)
    assert wire.to_signed64(f[2]) == -54


def test_roundtrip_all_wire_types():
    fields = [(1, 1, 0x0123456789ABCDEF), (2, 5, 0xDEADBEEF), (3, 0, 300), (4, 2, b"abc")]
    assert wire.parse_fields(wire.enc_fields(fields)) == fields


@pytest.mark.parametrize("bad", [b"\x0a\x05ab", b"\x08", b"\x09\x01\x02", b"\x0b"])
def test_malformed_raises(bad):
    with pytest.raises(wire.WireError):
        wire.parse_fields(bad)


def test_set_varint_replaces_or_adds_sorted():
    f = [(1, 0, 0), (5, 0, 1)]
    wire.set_varint(f, 5, 3)
    wire.set_varint(f, 3, 9)
    assert f == [(1, 0, 0), (3, 0, 9), (5, 0, 3)]
