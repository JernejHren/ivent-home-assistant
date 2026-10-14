"""Testi abstrakcije IVentBackend."""
from unittest.mock import MagicMock

from custom_components.ivent.api import IVentApiClient
from custom_components.ivent.backend import IVentBackend


def test_cloud_client_satisfies_backend_protocol():
    """Oblačni odjemalec izpolnjuje IVentBackend (brez spremembe obnašanja)."""
    client = IVentApiClient(MagicMock(), "key", "123")
    assert isinstance(client, IVentBackend)


def test_incomplete_object_is_not_a_backend():
    class Partial:
        async def async_get_info(self):  # manjkajo ostale metode
            return {"groups": []}

    assert not isinstance(Partial(), IVentBackend)
