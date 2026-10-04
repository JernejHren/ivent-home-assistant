"""Testi razširitve (fan-out) ukazov iz rezervirane skupine 1 "iVent"."""
import copy

import pytest
import custom_components.ivent  # noqa: F401  (zagotovi uvoz paketa za patch v fixture)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import MOCK_INFO_DATA


def _device(mac: str, name: str) -> dict:
    return {
        "mac_address": mac,
        "device_name": name,
        "rssi": -60,
        "firmware_version": 204070000,
        "alive": True,
        "status_esp": 0,
        "reverse_flow": False,
    }


def _group(gid, name, devices, work_mode, speed, rc_mode):
    return {
        "id": gid,
        "name": name,
        "led_work_mode": "LedOffMode",
        "buzzer_work_mode": "BuzzerOffMode",
        "remote": {
            "work_mode": work_mode,
            "special_mode": "IVentSpecialOff",
            "remote_control_speed": speed,
            "remote_control_work_mode": rc_mode,
            "bypass_rotation": "BypassForward",
            "work_mode_changed_at": 1700000000,
            "special_mode_ends_at": 0,
        },
        "devices": devices,
    }


@pytest.fixture
def three_groups(mock_api_client):
    """Skupina 1 brez naprav + Dnevna (Bypass2) + Tilen (Recuperation1)."""
    mock_api_client.async_get_info.return_value = {
        "groups": [
            _group(1, "iVent", [], "IVentRecuperation1", 1, "Normal"),
            _group(2, "Dnevna", [_device("AA:00:00:00:00:01", "d1")], "IVentBypass2", 2, "Bypass"),
            _group(3, "Tilen", [_device("AA:00:00:00:00:02", "d2")], "IVentRecuperation1", 1, "Normal"),
        ]
    }
    return mock_api_client


def _entity_id(hass, entry, gid, suffix, domain):
    reg = er.async_get(hass)
    return reg.async_get_entity_id(domain, "ivent", f"{entry.entry_id}_{gid}_{suffix}")


async def _setup(hass, entry):
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _calls(client):
    return {c.args[0]: c.args[1] for c in client.async_modify_group.call_args_list}


async def test_boost_on_all_group_fans_out(hass: HomeAssistant, mock_config_entry, three_groups):
    """Boost na skupini 1 gre na obe pravi skupini, vsaka obdrži svojo hitrost."""
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 1, "iventboost", "switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": ent}, blocking=True)

    calls = _calls(three_groups)
    assert set(calls) == {1, 2, 3}
    assert calls[2]["remote_work_mode"]["special_mode"] == "IVentBoost"
    assert calls[3]["remote_work_mode"]["special_mode"] == "IVentBoost"
    # osnovno stanje vsake skupine ostane (Boost je overlay)
    assert calls[2]["remote_work_mode"]["work_mode"] == "IVentBypass2"
    assert calls[2]["remote_work_mode"]["remote_control_speed"] == 2
    assert calls[3]["remote_work_mode"]["work_mode"] == "IVentRecuperation1"
    assert calls[3]["remote_work_mode"]["remote_control_speed"] == 1


async def test_led_on_all_group_fans_out(hass: HomeAssistant, mock_config_entry, three_groups):
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 1, "led", "switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": ent}, blocking=True)
    calls = _calls(three_groups)
    assert calls[2] == {"led_mode": "LedOnMode"}
    assert calls[3] == {"led_mode": "LedOnMode"}


async def test_speed_on_all_group_keeps_each_groups_off_state(
    hass: HomeAssistant, mock_config_entry, three_groups
):
    """Nastavitev hitrosti na skupini 1 ne vklopi izklopljene skupine."""
    info = three_groups.async_get_info.return_value
    info["groups"][2]["remote"]["work_mode"] = "IVentWorkOff"
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 1, "speed", "select")
    # neposredno prek entitete, neodvisno od oznak v UI
    entity = next(
        e for e in hass.data["entity_components"]["select"].entities if e.entity_id == ent
    )
    await entity.async_select_option(entity.options[-1])
    calls = _calls(three_groups)
    assert calls[2]["remote_work_mode"]["remote_control_speed"] == 3
    assert calls[2]["remote_work_mode"]["work_mode"] == "IVentBypass3"
    assert calls[3]["remote_work_mode"]["work_mode"] == "IVentWorkOff"


async def test_partial_failure_raises_but_other_group_written(
    hass: HomeAssistant, mock_config_entry, three_groups
):
    from custom_components.ivent.api import IVentApiClientError
    from homeassistant.exceptions import HomeAssistantError

    async def _side(gid, payload):
        if gid == 3:
            raise IVentApiClientError("boom")

    three_groups.async_modify_group.side_effect = _side
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 1, "led", "switch")
    with pytest.raises((IVentApiClientError, HomeAssistantError)):
        await hass.services.async_call("switch", "turn_on", {"entity_id": ent}, blocking=True)
    assert 2 in _calls(three_groups)


async def test_real_group_does_not_fan_out(hass: HomeAssistant, mock_config_entry, three_groups):
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 2, "led", "switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": ent}, blocking=True)
    assert set(_calls(three_groups)) == {2}


async def test_group1_with_devices_is_a_normal_group(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Če je v skupini 1 edina skupina (kot v osnovnih testih), ni razširitve."""
    mock_api_client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
    await _setup(hass, mock_config_entry)
    ent = _entity_id(hass, mock_config_entry, 1, "led", "switch")
    await hass.services.async_call("switch", "turn_off", {"entity_id": ent}, blocking=True)
    assert mock_api_client.async_modify_group.call_count == 1
    mock_api_client.async_modify_group.assert_called_with(1, {"led_mode": "LedOffMode"})


REQUIRED_REMOTE_KEYS = {
    "special_mode", "work_mode", "bypass_rotation",
    "remote_control_work_mode", "remote_control_speed",
}  # RemoteControlMessageTypeWrite.required v openapi.json


async def test_every_remote_payload_is_complete(
    hass: HomeAssistant, mock_config_entry, three_groups
):
    """Vsak poslan remote_work_mode vsebuje vseh 5 obveznih polj (tudi pri fan-outu)."""
    await _setup(hass, mock_config_entry)
    boost = _entity_id(hass, mock_config_entry, 1, "iventboost", "switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": boost}, blocking=True)
    speed = _entity_id(hass, mock_config_entry, 1, "speed", "select")
    entity = next(e for e in hass.data["entity_components"]["select"].entities if e.entity_id == speed)
    await entity.async_select_option(entity.options[-1])
    mode = _entity_id(hass, mock_config_entry, 2, "ventilation_mode", "select")
    entity = next(e for e in hass.data["entity_components"]["select"].entities if e.entity_id == mode)
    await entity.async_select_option(entity.options[0])

    sent = [c.args[1] for c in three_groups.async_modify_group.call_args_list
            if "remote_work_mode" in c.args[1]]
    assert len(sent) >= 7
    for payload in sent:
        assert REQUIRED_REMOTE_KEYS <= set(payload["remote_work_mode"])
