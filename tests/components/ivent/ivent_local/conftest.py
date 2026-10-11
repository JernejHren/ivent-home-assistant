import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
FAKE_LOC = 0x0123456789ABCDEF
FAKE_MACS = ["98:cd:ac:00:00:41", "98:cd:ac:00:00:42", "98:cd:ac:00:00:43"]


@pytest.fixture(scope="session")
def reads():
    return {k: bytes.fromhex(v) for k, v in json.load(open(FIX / "read_responses.json")).items()}


@pytest.fixture(scope="session")
def events():
    return [json.loads(line) for line in open(FIX / "push_events.jsonl")]


@pytest.fixture(scope="session")
def cloud_info():
    return json.load(open(FIX / "cloud_info.json"))


import pytest_asyncio  # noqa: E402

from .fake_device import FakeLocation  # noqa: E402
from custom_components.ivent.ivent_local import convert as _cv  # noqa: E402
from custom_components.ivent.ivent_local.client import IVentLocalClient  # noqa: E402
from custom_components.ivent.ivent_local.transport import UdpTransport  # noqa: E402


@pytest_asyncio.fixture
async def lab(socket_enabled, reads, cloud_info):
    """Lažna lokacija + odjemalec (en socket) na lokalnem naslovu."""
    import asyncio
    loop = asyncio.get_running_loop()
    master_mac = _cv.mac_from_str(FAKE_MACS[0])
    fake = FakeLocation(reads, cloud_info, FAKE_LOC, master_mac)
    await loop.create_datagram_endpoint(lambda: fake, local_addr=("127.0.0.1", 0))
    transport = UdpTransport(bind_host="127.0.0.1", bind_port=0, port=fake.port,
                             timeout=0.3, retries=2)
    await transport.start()
    client = IVentLocalClient(transport, location_id=FAKE_LOC, master_host="127.0.0.1",
                              master_mac=master_mac)

    class Lab:
        pass

    lab = Lab()
    lab.fake, lab.transport, lab.client = fake, transport, client
    yield lab
    await transport.stop()
    fake.transport.close()
