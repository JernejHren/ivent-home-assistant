"""Lažna i-Vent lokacija (UDP), zgrajena iz anonimiziranih zajemov.

Posnema obnašanje, ugotovljeno na pravi napravi: odgovori z echo-jem messageId,
tip odgovora = zahteva | 0x8000 (branja) oziroma ResponseEmpty 33279 (pisanja),
naprava sama osveži workModeChangedAt / specialModeEndsAt, po spremembi stanja
Master 3x broadcasta tip 6. Napačen setFields ali napačen locationId = brez
(ustreznega) odgovora, tako da napake odjemalca postanejo vidne v testih.
"""
import asyncio
import socket
import struct
import time

from custom_components.ivent.ivent_local import const as c
from custom_components.ivent.ivent_local import convert as cv
from custom_components.ivent.ivent_local import protocol as p
from custom_components.ivent.ivent_local import wire

DURATION_KEY = {"IVentBoost": "boostTime", "IVentSnooze": "snoozeTime",
                "IVentNight1": "sleepModeDuration1", "IVentNight2": "sleepModeDuration2"}


def enc_remote(r):
    f = [(1, 0, c.SPECIAL_MODE_NUM[r["special_mode"]]), (2, 0, c.WORK_MODE_NUM[r["work_mode"]]),
         (3, 0, c.BYPASS_ROTATION_NUM[r["bypass_rotation"]]),
         (4, 0, c.REMOTE_WORK_MODE_NUM[r["remote_control_work_mode"]]),
         (5, 0, r["remote_control_speed"]), (6, 0, r["special_mode_ends_at"])]
    if r["work_mode_changed_at"]:
        f.append((7, 0, r["work_mode_changed_at"]))
    return wire.enc_fields(f)


def enc_profile(pr):
    return wire.enc_fields([(i, 0, pr[n]) for i, n in enumerate(c.GROUP_PROFILE_FIELDS, 1)])


def enc_master_group(g):
    return wire.enc_fields([
        (1, 5, g["id"]), (2, 2, g["name"].encode()), (3, 2, enc_remote(g["remote"])),
        (4, 2, enc_profile(g["profile"])), (5, 0, g["current_mode_duration_in"]),
        (6, 0, g["current_mode_duration_out"]), (7, 0, g["disable_schedule_until"])])


def enc_master_device(d):
    ip = struct.unpack("<I", socket.inet_aton(d["ip"]))[0]
    return wire.enc_fields([
        (1, 1, cv.mac_from_str(d["mac_address"])), (2, 5, d["group_id"]), (3, 0, d["rssi"]),
        (4, 0, int(d["alive"])), (6, 0, int(d["reverse_flow"])), (7, 2, d["device_name"].encode()),
        (10, 0, d["firmware_version"]), (11, 5, ip), (12, 0, d["status_esp"])])


class FakeLocation(asyncio.DatagramProtocol):
    def __init__(self, reads, cloud, location_id, master_mac):
        self.location_id = location_id
        self.master_mac = master_mac
        self.network_hash = 2434161996280914071
        self.requests = []          # (msg_type, forward, destination, addr)
        self.beacons = []
        self.drop_next = 0          # koliko naslednjih paketov ignorirati (izguba UDP)
        self.force_error = None     # ErrorCode za naslednji write
        self.ignore_direct = False  # ignoriraj forward=0 paketov za napravo (le Master)
        pk = p.parse_packet(reads["groups"])
        _, groups = cv.decode_masterlist(wire.get(pk.body, c.F_GROUPS[1]), devices=False)
        pk = p.parse_packet(reads["devices"])
        _, devices = cv.decode_masterlist(wire.get(pk.body, c.F_DEVICES[1]), devices=True)
        cg = {g["id"]: g for g in cloud["groups"]}
        self.groups = {}
        for g in groups:
            g["led_work_mode"] = cg[g["id"]]["led_work_mode"]
            g["buzzer_work_mode"] = cg[g["id"]]["buzzer_work_mode"]
            g["enable_schedule"] = cg[g["id"]]["enable_schedule"]
            self.groups[g["id"]] = g
        self.devices = []
        for d in devices:
            d["ip"] = "127.0.0.1"
            self.devices.append(d)
        self.transport = None

    # --- UDP ---------------------------------------------------------------
    def connection_made(self, transport):
        self.transport = transport

    @property
    def port(self):
        return self.transport.get_extra_info("sockname")[1]

    def _reply(self, addr, mid, msg_type, field, payload):
        hdr = (wire.enc_fixed64_field(1, self.location_id) + wire.enc_fixed32_field(2, mid)
               + wire.enc_varint_field(3, 0) + wire.enc_varint_field(4, self.master_mac)
               + wire.enc_varint_field(5, 0) + wire.enc_varint_field(6, int(time.time()))
               + wire.enc_varint_field(7, 1))
        self.transport.sendto(p.wrap(msg_type, hdr + wire.enc_bytes_field(field, payload)), addr)

    def _empty(self, addr, mid, err=0):
        err = self.force_error if self.force_error is not None else err
        self.force_error = None
        self._reply(addr, mid, c.T_RESPONSE_EMPTY, c.F_RES_EMPTY, wire.enc_varint_field(1, err))

    def datagram_received(self, data, addr):
        try:
            pk = p.parse_packet(data)
        except p.ProtocolError:
            return
        if pk.legacy or pk.location_id != self.location_id:
            return  # locationId je edina poverilnica
        fwd = wire.get(pk.body, 3, 0)
        dest = wire.get(pk.body, 5, 0)
        self.requests.append((pk.msg_type, fwd, dest, addr))
        if self.drop_next:
            self.drop_next -= 1
            return
        if self.ignore_direct and fwd == 0 and dest != self.master_mac:
            return
        h = getattr(self, f"_h_{pk.msg_type}", None)
        if h:
            h(pk, addr)

    # --- branja ------------------------------------------------------------
    def _h_279(self, pk, addr):
        self._reply(addr, pk.message_id, 279 | c.RESPONSE_FLAG, c.F_PING[1],
                    wire.enc_varint_field(1, self.network_hash))

    def _paged(self, pk, addr, req_field, res_field, items, enc, msg_type):
        req = wire.parse_fields(wire.get(pk.body, req_field, b""))
        off, lim = wire.get(req, 1, 0), wire.get(req, 2, 16)
        payload = wire.enc_varint_field(1, len(items)) + b"".join(
            wire.enc_bytes_field(2, enc(i)) for i in items[off:off + lim])
        self._reply(addr, pk.message_id, msg_type | c.RESPONSE_FLAG, res_field, payload)

    def _h_267(self, pk, addr):
        self._paged(pk, addr, 79, 80, list(self.groups.values()), enc_master_group, 267)

    def _h_268(self, pk, addr):
        self._paged(pk, addr, 81, 82, self.devices, enc_master_device, 268)

    def _h_275(self, pk, addr):
        gid = wire.get(wire.parse_fields(wire.get(pk.body, 89)), 1)
        g = self.groups.get(gid)
        if g is None:
            return self._empty(addr, pk.message_id, 2)
        f = [(2, 0, int(g["enable_schedule"])), (3, 2, g["name"].encode()),
             (4, 2, enc_remote(g["remote"])), (5, 0, c.LED_MODE_NUM[g["led_work_mode"]]),
             (6, 0, c.BUZZER_MODE_NUM[g["buzzer_work_mode"]]), (7, 2, enc_profile(g["profile"])),
             (9, 5, gid), (11, 0, g["current_mode_duration_in"]), (12, 0, g["current_mode_duration_out"])]
        self._reply(addr, pk.message_id, 275 | c.RESPONSE_FLAG, c.F_READ_GROUP[1], wire.enc_fields(f))

    # --- pisanje -----------------------------------------------------------
    @staticmethod
    def _mask_ok(fields):
        # setFields mora biti fixed64 in enak izračunani maski (kot generateSetFields)
        sets = [(w, v) for f, w, v in fields if f == 99]
        rest = [t for t in fields if t[0] != 99]
        return sets == [(1, p.compute_set_fields(rest))]

    def _h_4370(self, pk, addr):
        fields = wire.parse_fields(wire.get(pk.body, c.F_REQ_MODIFY_GROUP))
        if not self._mask_ok(fields) or wire.get(fields, 1) not in self.groups:
            return self._empty(addr, pk.message_id, 2)
        if self.force_error:
            return self._empty(addr, pk.message_id)
        gid = wire.get(fields, 1)
        g = self.groups[gid]
        if wire.get(fields, 2):
            del self.groups[gid]
        if 3 in {f for f, _, _ in fields}:
            g["name"] = wire.get(fields, 3).decode()
        if 6 in {f for f, _, _ in fields}:
            g["led_work_mode"] = c.LED_MODE[wire.get(fields, 6)]
        if 7 in {f for f, _, _ in fields}:
            g["buzzer_work_mode"] = c.BUZZER_MODE[wire.get(fields, 7)]
        changed = False
        raw = wire.get(fields, 8)
        if raw is not None:
            r = wire.parse_fields(raw)
            rem = g["remote"]
            rem["special_mode"] = c.SPECIAL_MODE[wire.get(r, 1, 0)]
            rem["work_mode"] = c.WORK_MODE[wire.get(r, 2, 0)]
            rem["bypass_rotation"] = c.BYPASS_ROTATION[wire.get(r, 3, 1)]
            rem["remote_control_work_mode"] = c.REMOTE_WORK_MODE[wire.get(r, 4, 1)]
            rem["remote_control_speed"] = wire.get(r, 5, 0)
            now = int(time.time())
            rem["work_mode_changed_at"] = now  # naprava osveži sama
            key = DURATION_KEY.get(rem["special_mode"])
            if key:
                rem["special_mode_ends_at"] = now + g["profile"][key]
            changed = True  # sicer ostane zastarela vrednost
        self.network_hash += 1
        self._empty(addr, pk.message_id)
        if changed:
            self.broadcast_remote(gid, addr)

    def _h_4358(self, pk, addr):
        fields = wire.parse_fields(wire.get(pk.body, c.F_REQ_MODIFY_DEVICE))
        mac = cv.mac_to_str(wire.get(pk.body, 5))
        dev = next((d for d in self.devices if d["mac_address"] == mac), None)
        if not self._mask_ok(fields) or dev is None:
            return self._empty(addr, pk.message_id, 2)
        for f, _, v in fields:
            if f == 1:
                dev["reverse_flow"] = bool(v)
            elif f == 2:
                dev["group_id"] = v
            elif f == 3:
                dev["device_name"] = v.decode()
        self.network_hash += 1
        self._empty(addr, pk.message_id)

    def _h_4362(self, pk, addr):
        action = wire.get(wire.parse_fields(wire.get(pk.body, c.F_REQ_ACTION)), 1)
        if action == c.ACTION_BEACON:
            self.beacons.append(cv.mac_to_str(wire.get(pk.body, 5)))
        self._empty(addr, pk.message_id)

    # --- broadcast ---------------------------------------------------------
    def _legacy(self, msg_type, field, payload):
        body = wire.enc_fixed64_field(1, self.location_id) + wire.enc_bytes_field(field, payload)
        return wire.enc_varint_field(1, msg_type) + wire.enc_varint_field(2, 1) + \
            wire.enc_bytes_field(3, body)

    def broadcast_remote(self, gid, addr, copies=3):
        payload = wire.enc_bytes_field(1, enc_remote(self.groups[gid]["remote"])) + \
            wire.enc_fixed32_field(2, gid)
        for _ in range(copies):
            self.transport.sendto(self._legacy(c.T_REMOTE_CONTROL, 5, payload), addr)

    def advertise(self, addr, ip="127.0.0.1", became=1790396130):
        mac = self.devices[0]["mac_address"]
        payload = (wire.enc_varint_field(1, became) + wire.enc_fixed64_field(2, cv.mac_from_str(mac))
                   + wire.enc_fixed32_field(3, struct.unpack("<I", socket.inet_aton(ip))[0]))
        self.transport.sendto(self._legacy(c.T_MASTER_ADVERTISE, 2, payload), addr)
