import pytest
import copy

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ivent.const import DOMAIN, OPT_AUTO_REMOVE_STALE
from .conftest import MOCK_INFO_DATA, MOCK_SCHEDULES_DATA

async def test_stale_entries_survive_short_outage(
    hass: HomeAssistant,
    mock_config_entry,
    mock_api_client,
):
    """Ena osvežitev brez naprave/urnika ne sme brisati registrov (izpad, nepopoln odgovor)."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    
    # Initially we should have the service device + 1 group device + 1 node device
    devices = dr.async_entries_for_config_entry(device_registry, mock_config_entry.entry_id)
    assert len(devices) == 3

    # Ensure schedule entity is present initially
    schedule_uid = f"{mock_config_entry.entry_id}_schedule_101"
    assert entity_registry.async_get_entity_id("switch", DOMAIN, schedule_uid) is not None

    problem_uid = "AA:BB:CC:DD:EE:FF_problem"
    problem_entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, problem_uid
    )
    assert problem_entity_id is not None

    # Now we mutate API response to remove ONE device and the SCHEDULE.
    # The integration should not delete registry entries; that can break
    # user automations and is unsafe during startup/reconnect races.
    new_data = copy.deepcopy(MOCK_INFO_DATA)
    new_data["groups"][0]["devices"] = [] # Removing the device "Enota 1"
    mock_api_client.async_get_info.return_value = new_data
    mock_api_client.async_get_schedules.return_value = [] # Removed the schedule

    # Refresh coordinator
    coordinator = mock_config_entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Device registry entries are intentionally preserved.
    devices = dr.async_entries_for_config_entry(device_registry, mock_config_entry.entry_id)
    assert len(devices) == 3
    
    # Entity registry entries are intentionally preserved.
    assert entity_registry.async_get_entity_id("switch", DOMAIN, schedule_uid) is not None
    assert (
        entity_registry.async_get_entity_id("binary_sensor", DOMAIN, problem_uid)
        == problem_entity_id
    )

    problem_state = hass.states.get(problem_entity_id)
    assert problem_state is not None
    assert problem_state.state == "unavailable"


@pytest.fixture
def auto_remove(hass, mock_config_entry):
    """Vklopi opcijsko samodejno odstranjevanje (privzeto je izklopljeno)."""
    hass.config_entries.async_update_entry(mock_config_entry, options={OPT_AUTO_REMOVE_STALE: True})


def _info_without_device():
    data = copy.deepcopy(MOCK_INFO_DATA)
    data["groups"][0]["devices"] = []
    return data


async def _refresh(hass, coordinator, times):
    for _ in range(times):
        await coordinator.async_refresh()
        await hass.async_block_till_done()


async def test_stale_device_and_schedule_are_removed_after_repeated_absence(
    hass: HomeAssistant, mock_config_entry, mock_api_client, auto_remove
):
    from custom_components.ivent.coordinator import STALE_AFTER_UPDATES

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    schedule_uid = f"{mock_config_entry.entry_id}_schedule_101"
    other_schedule_uid = f"{mock_config_entry.entry_id}_schedule_102"
    assert ent_reg.async_get_entity_id("switch", DOMAIN, schedule_uid)

    mock_api_client.async_get_info.return_value = _info_without_device()
    schedules = copy.deepcopy(MOCK_SCHEDULES_DATA)
    schedules[0]["schedules"] = [schedules[0]["schedules"][1]]  # urnik 101 izbrisan
    mock_api_client.async_get_schedules.return_value = schedules
    coordinator = mock_config_entry.runtime_data.coordinator

    await _refresh(hass, coordinator, STALE_AFTER_UPDATES - 1)
    assert len(dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)) == 3
    assert ent_reg.async_get_entity_id("switch", DOMAIN, schedule_uid)

    await _refresh(hass, coordinator, 1)
    devices = dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)
    assert len(devices) == 2  # servisna naprava + skupina
    assert not any(("ivent", "AA:BB:CC:DD:EE:FF") in d.identifiers for d in devices)
    assert ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "AA:BB:CC:DD:EE:FF_problem") is None
    assert ent_reg.async_get_entity_id("switch", DOMAIN, schedule_uid) is None
    assert ent_reg.async_get_entity_id("switch", DOMAIN, other_schedule_uid) is not None


async def test_reappearance_counter_resets(hass: HomeAssistant, mock_config_entry, mock_api_client, auto_remove):
    from custom_components.ivent.coordinator import STALE_AFTER_UPDATES

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    dev_reg = dr.async_get(hass)
    coordinator = mock_config_entry.runtime_data.coordinator

    for _ in range(3):  # izginja, vrne se, izginja ... nikoli zaporedno dovolj dolgo
        mock_api_client.async_get_info.return_value = _info_without_device()
        await _refresh(hass, coordinator, STALE_AFTER_UPDATES - 1)
        mock_api_client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
        await _refresh(hass, coordinator, 1)
    assert len(dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)) == 3


async def test_empty_response_never_prunes(hass: HomeAssistant, mock_config_entry, mock_api_client, auto_remove):
    from custom_components.ivent.coordinator import STALE_AFTER_UPDATES

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    empty = copy.deepcopy(MOCK_INFO_DATA)
    empty["groups"] = []
    mock_api_client.async_get_info.return_value = empty
    await _refresh(hass, mock_config_entry.runtime_data.coordinator, STALE_AFTER_UPDATES + 2)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_config_entry.entry_id)
    assert len(devices) == 3


async def test_removed_device_reappearing_reloads_entry(
    hass: HomeAssistant, mock_config_entry, mock_api_client, auto_remove
):
    from custom_components.ivent.coordinator import STALE_AFTER_UPDATES

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data.coordinator
    mock_api_client.async_get_info.return_value = _info_without_device()
    await _refresh(hass, coordinator, STALE_AFTER_UPDATES)
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "AA:BB:CC:DD:EE:FF_problem") is None

    mock_api_client.async_get_info.return_value = copy.deepcopy(MOCK_INFO_DATA)
    await _refresh(hass, coordinator, 1)
    await hass.async_block_till_done()
    assert ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "AA:BB:CC:DD:EE:FF_problem") is not None


async def test_manual_device_removal_only_for_stale(hass: HomeAssistant, mock_config_entry, mock_api_client):
    from custom_components.ivent import async_remove_config_entry_device

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)
    # nobena trenutno prisotna naprava (servis, skupina, enota) se ne sme dati odstraniti
    for dev in devices:
        assert not await async_remove_config_entry_device(hass, mock_config_entry, dev)

    stale = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, "11:22:33:44:55:66")})
    assert await async_remove_config_entry_device(hass, mock_config_entry, stale)
    stale_group = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_999")})
    assert await async_remove_config_entry_device(hass, mock_config_entry, stale_group)


async def test_new_group_and_device_get_entities_on_every_platform(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """dynamic-devices: skupina in naprava, ki se pojavita po zagonu, dobita entitete."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    ent_reg = er.async_get(hass)
    before = len(er.async_entries_for_config_entry(ent_reg, mock_config_entry.entry_id))

    data = copy.deepcopy(MOCK_INFO_DATA)
    new_group = copy.deepcopy(data["groups"][0])
    new_group["id"] = 77
    new_group["name"] = "Spalnica"
    new_group["devices"][0].update(mac_address="11:22:33:44:55:66", device_name="Enota 2")
    data["groups"].append(new_group)
    mock_api_client.async_get_info.return_value = data
    await _refresh(hass, mock_config_entry.runtime_data.coordinator, 1)

    entries = er.async_entries_for_config_entry(ent_reg, mock_config_entry.entry_id)
    assert len(entries) > before
    new_uids = {e.unique_id for e in entries if "77" in e.unique_id or "11:22:33:44:55:66" in e.unique_id}
    domains = {e.domain for e in entries if e.unique_id in new_uids}
    assert {"fan", "select", "switch", "text", "button", "binary_sensor"} <= domains
    # nova skupina ima svoje naprave v registru
    dev_reg = dr.async_get(hass)
    ids = {i for d in dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)
           for _, i in d.identifiers}
    assert f"{mock_config_entry.entry_id}_77" in ids and "11:22:33:44:55:66" in ids


async def test_default_never_removes_but_allows_manual_delete(
    hass: HomeAssistant, mock_config_entry, mock_api_client
):
    """Privzeto se nič ne briše samodejno; nedosegljivo napravo uporabnik izbriše ročno."""
    from custom_components.ivent import async_remove_config_entry_device

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_api_client.async_get_info.return_value = _info_without_device()
    await _refresh(hass, mock_config_entry.runtime_data.coordinator, 10)

    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, mock_config_entry.entry_id)
    assert len(devices) == 3
    problem = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "AA:BB:CC:DD:EE:FF_problem")
    assert problem and hass.states.get(problem).state == "unavailable"

    unit = next(d for d in devices if (DOMAIN, "AA:BB:CC:DD:EE:FF") in d.identifiers)
    assert await async_remove_config_entry_device(hass, mock_config_entry, unit)
    dev_reg.async_remove_device(unit.id)
    assert ent_reg.async_get_entity_id("binary_sensor", DOMAIN, "AA:BB:CC:DD:EE:FF_problem") is None
