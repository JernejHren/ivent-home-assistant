#!/usr/bin/env python3
"""Anonimizira zajete i-Vent pakete za testne fixture-e (NE vsebuje pravih vrednosti).

Zamenja v binarnih paketih `locationId` (edina poverilnica lokalnega protokola)
in MAC naslove naprav v vseh kodiranjih, ki se pojavijo na zici:
  * fixed64 (6 bajtov LE + 2 ničli), varint (header.destination / source) in
  * ASCII niz "aa:bb:cc:dd:ee:ff" (deviceName).
Zamenjave so enake dolžine, zato ostane struktura paketa (dolžine polj) pravilna.

Primer:
  python tools/sanitize_capture.py --location-id 0x<LOCATION_ID> \
      --mac <aa:bb:cc:dd:ee:01> --mac <aa:bb:cc:dd:ee:02> \
      --out tests/ivent_local/fixtures \
      --read-responses out.json --push listen.jsonl listen2.jsonl listen4.jsonl \
      --cloud-info cmp.json
Prava MAC-a/locationId podaš le na ukazni vrstici; skripta ju nikoli ne zapiše.
"""
import argparse, json, struct, sys
from pathlib import Path

FAKE_LOC = 0x0123456789ABCDEF


def varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | 0x80 if v else b)
        if not v:
            return bytes(out)


def mac_int(s: str) -> int:
    return int.from_bytes(bytes(int(x, 16) for x in s.split(":")), "little")


def fake_mac(i: int) -> str:
    # zadnji bajt >= 0x40 -> enaka dolzina varinta kot pri pravih MAC-ih
    return f"98:cd:ac:00:00:{0x41 + i:02x}"


def build_pairs(loc: int, macs: list[str]):
    pairs = [(struct.pack("<Q", loc), struct.pack("<Q", FAKE_LOC))]
    for i, real in enumerate(macs):
        fake = fake_mac(i)
        ri, fi = mac_int(real), mac_int(fake)
        pairs += [
            (ri.to_bytes(6, "little"), fi.to_bytes(6, "little")),
            (varint(ri), varint(fi)),
            (real.encode(), fake.encode()),
        ]
    for a, b in pairs:
        assert len(a) == len(b), f"dolzina zamenjave se ne ujema: {a.hex()} / {b.hex()}"
    return pairs


def sanitize_bytes(data: bytes, pairs) -> bytes:
    for a, b in pairs:
        data = data.replace(a, b)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location-id", required=True)
    ap.add_argument("--mac", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--read-responses", help="out.json iz ivent_discovery_test.py --save")
    ap.add_argument("--push", nargs="*", default=[], help="JSONL iz ivent_listen_test.py --save")
    ap.add_argument("--cloud-info", help="cmp.json iz ivent_cloud_compare.py --save")
    a = ap.parse_args()
    loc = int(a.location_id, 16) if a.location_id.lower().startswith("0x") else int(a.location_id)
    macs = [m.lower() for m in a.mac]
    pairs = build_pairs(loc, macs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    san = lambda h: sanitize_bytes(bytes.fromhex(h), pairs).hex()

    if a.read_responses:
        src = json.load(open(a.read_responses, encoding="utf-8"))
        res = {}
        for k, v in src.items():
            key = k
            for i, m in enumerate(macs):
                key = key.replace(m, fake_mac(i))
            if "raw_hex" in v:
                res[key] = san(v["raw_hex"])
            elif "raw_hex_last_page" in v:
                res[key] = san(v["raw_hex_last_page"])
        json.dump(res, open(out / "read_responses.json", "w"), indent=1)
    if a.push:
        n = 0
        with open(out / "push_events.jsonl", "w") as f:
            for path in a.push:
                for line in open(path, encoding="utf-8"):
                    d = json.loads(line)
                    f.write(json.dumps({"t": d["t"], "src": d["src"], "type": d["type"],
                                        "hex": san(d["hex"])}) + "\n")
                    n += 1
    if a.cloud_info:
        text = json.dumps(json.load(open(a.cloud_info, encoding="utf-8"))["cloud"], indent=1)
        for i, m in enumerate(macs):
            text = text.replace(m, fake_mac(i))
        open(out / "cloud_info.json", "w").write(text)

    # samokontrola: nobena prava vrednost ne sme ostati v nobenem kodiranju
    leaks = []
    for p in out.iterdir():
        raw = p.read_bytes()
        txt = raw.decode("utf-8", "ignore")
        for real, enc in [(struct.pack("<Q", loc).hex(), "locationId")] + [
                (x, "mac-ascii") for x in macs] + [
                (mac_int(x).to_bytes(6, "little").hex(), "mac-fixed") for x in macs] + [
                (varint(mac_int(x)).hex(), "mac-varint") for x in macs]:
            if real in txt:
                leaks.append((p.name, enc))
    if leaks:
        sys.exit(f"[!] ostanki pravih vrednosti: {leaks}")
    print("[ok] fixture-i anonimizirani, brez ostankov")


if __name__ == "__main__":
    main()
