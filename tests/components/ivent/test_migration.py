"""Migracija vnosa in listener za spremembo nastavitev (starejši HA)."""
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ivent import _async_options_updated, async_migrate_entry
from custom_components.ivent.const import CONF_MODE, DOMAIN, MODE_CLOUD


async def test_migrate_v2_to_v4(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={"api_key": "k", "location_id": "1"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_AA:BB:CC:DD:EE:FF_problem", config_entry=entry)
    keep = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_1_work_mode_changed_at", config_entry=entry)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 4
    assert entry.data[CONF_MODE] == MODE_CLOUD
    assert registry.async_get(old.entity_id).unique_id == "AA:BB:CC:DD:EE:FF_problem"
    assert registry.async_get(keep.entity_id).unique_id == f"{entry.entry_id}_1_work_mode_changed_at"


async def test_migrate_current_version_is_noop(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, version=4, data={CONF_MODE: MODE_CLOUD})
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 4


async def test_options_listener_reloads_only_on_change(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, options={"info_fallback": True})
    entry.add_to_hass(hass)
    entry.runtime_data = MagicMock(options={"info_fallback": True})
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await _async_options_updated(hass, entry)
        reload.assert_not_awaited()
        entry.runtime_data = MagicMock(options={"info_fallback": False})
        await _async_options_updated(hass, entry)
        reload.assert_awaited_once_with(entry.entry_id)
