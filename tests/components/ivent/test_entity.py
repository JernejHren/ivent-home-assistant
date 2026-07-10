from custom_components.ivent.entity import IVentGroupEntity
from custom_components.ivent.coordinator import IVentGroupData
from custom_components.ivent.const import API_MODE_WORK_OFF
from unittest.mock import MagicMock
import copy

from tests.components.ivent.conftest import MOCK_INFO_DATA


def _make_group_entity(remote_overrides: dict | None = None) -> IVentGroupEntity:
    """Create an IVentGroupEntity with mocked coordinator data."""
    coordinator = MagicMock()
    coordinator.config_entry.entry_id = "test-entry"
    group_raw = copy.deepcopy(MOCK_INFO_DATA["groups"][0])
    if remote_overrides:
        group_raw["remote"].update(remote_overrides)
    group_data = IVentGroupData(raw=group_raw)
    coordinator.data = MagicMock()
    coordinator.data.groups_by_id = {group_data.id: group_data}
    return IVentGroupEntity(coordinator, group_data)


def test_remote_control_work_mode_defaults_to_normal() -> None:
    """Test only exact Bypass maps to Bypass; everything else defaults to Normal."""
    assert IVentGroupEntity._normalize_remote_control_work_mode("Bypass") == "Bypass"
    assert IVentGroupEntity._normalize_remote_control_work_mode("Normal") == "Normal"
    assert IVentGroupEntity._normalize_remote_control_work_mode(None) == "Normal"
    assert IVentGroupEntity._normalize_remote_control_work_mode("Unknown") == "Normal"


def test_work_mode_for_remote_settings_uses_documented_modes() -> None:
    """Test remote mode and speed map to documented i-Vent work modes."""
    assert IVentGroupEntity._work_mode_for_remote_settings("Normal", 3) == "IVentRecuperation3"
    assert IVentGroupEntity._work_mode_for_remote_settings("Bypass", 2) == "IVentBypass2"
    assert IVentGroupEntity._work_mode_for_remote_settings("Unknown", 1) == "IVentRecuperation1"


def test_build_remote_settings_payload_syncs_all_fields_when_on() -> None:
    """Test ventilation mode changes keep work_mode, mode, and speed in sync."""
    entity = _make_group_entity({
        "work_mode": "IVentBypass2",
        "remote_control_work_mode": "Bypass",
        "remote_control_speed": 2,
    })
    payload = entity._build_remote_settings_payload("Normal", 2, keep_off=True)
    remote = payload["remote_work_mode"]
    assert remote["work_mode"] == "IVentRecuperation2"
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2
    assert remote["special_mode"] == "IVentSpecialOff"
    assert remote["bypass_rotation"] == "BypassForward"


def test_build_remote_settings_payload_preserves_off_state() -> None:
    """Test mode changes while off keep work_mode at IVentWorkOff."""
    entity = _make_group_entity({
        "work_mode": API_MODE_WORK_OFF,
        "remote_control_work_mode": "Bypass",
        "remote_control_speed": 2,
    })
    payload = entity._build_remote_settings_payload("Normal", 2, keep_off=True)
    remote = payload["remote_work_mode"]
    assert remote["work_mode"] == API_MODE_WORK_OFF
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2


def test_build_remote_settings_payload_calculates_work_mode_when_turning_on() -> None:
    """Test fan turn-on path calculates work_mode even when currently off."""
    entity = _make_group_entity({
        "work_mode": API_MODE_WORK_OFF,
        "remote_control_work_mode": "Normal",
        "remote_control_speed": 2,
    })
    payload = entity._build_remote_settings_payload("Normal", 2, keep_off=False)
    remote = payload["remote_work_mode"]
    assert remote["work_mode"] == "IVentRecuperation2"
    assert remote["remote_control_work_mode"] == "Normal"
    assert remote["remote_control_speed"] == 2