"""Kontrola prevodov: izjeme, ikone in entitete se ujemajo s kodo."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "custom_components" / "ivent"
LANGS = ["en", "sl"]


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _used_exception_keys() -> set[str]:
    keys: set[str] = set()
    for f in ROOT.glob("*.py"):
        keys |= set(re.findall(r'_service_error\(\s*"([a-z_]+)"', f.read_text()))
        keys |= set(re.findall(r'translation_key="([a-z_]+)"', f.read_text()))
    return keys


@pytest.mark.parametrize("lang", LANGS)
def test_exception_translations_complete(lang: str) -> None:
    exceptions = _load(f"translations/{lang}.json")["exceptions"]
    used = _used_exception_keys()
    assert used, "pričakujemo vsaj en ključ izjeme"
    assert used <= set(exceptions), used - set(exceptions)


def test_icons_have_entity_translations() -> None:
    icons = _load("icons.json")["entity"]
    entity = _load("translations/en.json")["entity"]
    for platform, items in icons.items():
        assert set(items) <= set(entity[platform]), (platform, set(items) - set(entity[platform]))


async def test_service_error_has_translation(hass, mock_api_client) -> None:
    from custom_components.ivent import _service_error

    err = _service_error("create_group_failed", error="boom")
    assert err.translation_key == "create_group_failed"
    assert err.translation_placeholders == {"error": "boom"}
