"""i-Vent Smart Home integracija."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    config_validation as cv,
)
from homeassistant.exceptions import ServiceValidationError

from .api import IVentApiClient, IVentApiClientError
from .const import DOMAIN, PLATFORMS
from .coordinator import IVentCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nastavi i-Vent integracijo iz konfiguracijskega vnosa."""
    hass.data.setdefault(DOMAIN, {})

    client = IVentApiClient(
        session=async_get_clientsession(hass),
        api_key=entry.data["api_key"],
        location_id=entry.data["location_id"],
    )

    coordinator = IVentCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    # Ustvarimo glavno "servisno" napravo, na katero se vežejo vse ostale (via_device)
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="i-Vent",
        name="i-Vent System",
        model="Cloud Location",
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url="https://cloud.i-vent.com/",
    )

    @callback
    def _async_remove_stale_entries() -> None:
        """Odstrani zastarele naprave in entitete iz registrov HA.

        Poklicano ob vsaki uspešni posodobitvi koordinatorja.

        Strategija:
        - Naprave, ki jih API ne vrne več → async_remove_device.
          HA samodejno kaskadno odstrani vse entitete za tisto napravo.
        - Urniki (schedule), ki jih API ne vrne več → odstranimo entiteto
          neposredno iz entity_registry (ker so pritrjene na sistemsko napravo,
          ki nikoli ni odstranjena).
        """
        if not coordinator.last_update_success or coordinator.data is None:
            return

        data = coordinator.data

        # ── 1. Stale devices ───────────────────────────────────────────────
        active_device_identifiers = {
            (DOMAIN, entry.entry_id),
            *((DOMAIN, f"{entry.entry_id}_{gid}") for gid in data.group_ids),
            *((DOMAIN, mac) for mac in data.all_device_macs),
        }

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        for device_entry in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if not (device_entry.identifiers & active_device_identifiers):
                _LOGGER.info(
                    "Removing stale device from registry: %s", device_entry.name
                )
                # HA device removal only unlinks entities (sets device_id=None).
                # We must explicitly remove the entities to prevent unavailable ghosts.
                for entity_entry in er.async_entries_for_device(ent_reg, device_entry.id):
                    _LOGGER.info(
                        "Removing stale entity from registry: %s", entity_entry.entity_id
                    )
                    ent_reg.async_remove(entity_entry.entity_id)

                dev_reg.async_remove_device(device_entry.id)

        # ── 2. Stale schedule entities and orphaned ghost entities ─────────
        # Schedule switches are attached to the top-level "i-Vent System"
        # device, so removing that device is not an option.  We must detect
        # and remove orphaned schedule entities ourselves.
        active_schedule_unique_ids = {
            f"{entry.entry_id}_schedule_{sid}"
            for sid in data.schedules_by_id
        }

        for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            uid = entity_entry.unique_id

            # Orphaned entities (device_id is None) are ghost entities left behind
            # if a device was removed previously without explicitly removing its entities.
            if entity_entry.device_id is None:
                _LOGGER.info(
                    "Removing orphaned ghost entity from registry: %s", entity_entry.entity_id
                )
                ent_reg.async_remove(entity_entry.entity_id)
                continue

            # Only touch schedule entities belonging to this entry
            if (
                uid is not None
                and uid.startswith(f"{entry.entry_id}_schedule_")
                and uid not in active_schedule_unique_ids
            ):
                _LOGGER.info(
                    "Removing stale schedule entity from registry: %s", uid
                )
                ent_reg.async_remove(entity_entry.entity_id)

    entry.async_on_unload(coordinator.async_add_listener(_async_remove_stale_entries))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Servisi ---

    async def handle_create_group(call: ServiceCall) -> None:
        name = call.data.get("name")
        if not name or len(name.strip()) == 0:
            raise ServiceValidationError("Ime skupine ne sme biti prazno")
        try:
            await client.async_create_group(name)
        except IVentApiClientError as err:
            raise ServiceValidationError(f"Napaka pri ustvarjanju skupine: {err}") from err
        await coordinator.async_request_delayed_refresh()

    async def handle_delete_group(call: ServiceCall) -> None:
        group_id = call.data.get("group_id")
        if group_id is None:
            raise ServiceValidationError("Manjka ID skupine")
        try:
            await client.async_modify_group(group_id, {"delete": True})
        except IVentApiClientError as err:
            raise ServiceValidationError(f"Napaka pri brisanju skupine: {err}") from err
        await coordinator.async_request_delayed_refresh()

    async def handle_rename_group(call: ServiceCall) -> None:
        group_id = call.data.get("group_id")
        new_name = call.data.get("new_name")
        if group_id is None:
            raise ServiceValidationError("Manjka ID skupine")
        if not new_name or len(new_name.strip()) == 0:
            raise ServiceValidationError("Novo ime skupine ne sme biti prazno")
        try:
            await client.async_modify_group(group_id, {"name": new_name})
        except IVentApiClientError as err:
            raise ServiceValidationError(f"Napaka pri preimenovanju skupine: {err}") from err
        await coordinator.async_request_delayed_refresh()

    async def handle_rename_device(call: ServiceCall) -> None:
        device_mac = call.data.get("device_mac")
        new_name = call.data.get("new_name")
        if not device_mac:
            raise ServiceValidationError("Manjka MAC naprave")
        if not new_name or len(new_name.strip()) == 0:
            raise ServiceValidationError("Novo ime naprave ne sme biti prazno")
        try:
            await client.async_modify_device(device_mac, {"name": new_name})
        except IVentApiClientError as err:
            raise ServiceValidationError(f"Napaka pri preimenovanju naprave: {err}") from err
        await coordinator.async_request_delayed_refresh()

    async def handle_move_device(call: ServiceCall) -> None:
        device_mac = call.data.get("device_mac")
        group_id = call.data.get("group_id")
        if not device_mac:
            raise ServiceValidationError("Manjka MAC naprave")
        if group_id is None:
            raise ServiceValidationError("Manjka ciljna skupina")
        try:
            await client.async_modify_device(device_mac, {"group_id": group_id})
        except IVentApiClientError as err:
            raise ServiceValidationError(f"Napaka pri premikanju naprave: {err}") from err
        await coordinator.async_request_delayed_refresh()

    if not hass.services.has_service(DOMAIN, "create_group"):
        hass.services.async_register(
            DOMAIN, "create_group", handle_create_group,
            schema=vol.Schema({vol.Required("name"): cv.string}),
        )
    if not hass.services.has_service(DOMAIN, "delete_group"):
        hass.services.async_register(
            DOMAIN, "delete_group", handle_delete_group,
            schema=vol.Schema({vol.Required("group_id"): int}),
        )
    if not hass.services.has_service(DOMAIN, "rename_group"):
        hass.services.async_register(
            DOMAIN, "rename_group", handle_rename_group,
            schema=vol.Schema({
                vol.Required("group_id"): int,
                vol.Required("new_name"): cv.string,
            }),
        )
    if not hass.services.has_service(DOMAIN, "rename_device"):
        hass.services.async_register(
            DOMAIN, "rename_device", handle_rename_device,
            schema=vol.Schema({
                vol.Required("device_mac"): cv.string,
                vol.Required("new_name"): cv.string,
            }),
        )
    if not hass.services.has_service(DOMAIN, "move_device_to_group"):
        hass.services.async_register(
            DOMAIN, "move_device_to_group", handle_move_device,
            schema=vol.Schema({
                vol.Required("device_mac"): cv.string,
                vol.Required("group_id"): int,
            }),
        )

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        new_version = 2
        entry_id = config_entry.entry_id
        ent_reg = er.async_get(hass)

        for entity_entry in er.async_entries_for_config_entry(ent_reg, entry_id):
            old_uid = entity_entry.unique_id
            if not old_uid:
                continue

            # Migrate {mac}_problem and {mac}_alive to {entry_id}_{mac}_...
            if old_uid.endswith("_problem") or old_uid.endswith("_alive"):
                # If it doesn't already start with entry_id, migrate it
                if not old_uid.startswith(f"{entry_id}_"):
                    new_uid = f"{entry_id}_{old_uid}"
                    _LOGGER.info(
                        "Migrating entity %s unique_id from %s to %s",
                        entity_entry.entity_id,
                        old_uid,
                        new_uid,
                    )
                    ent_reg.async_update_entity(
                        entity_entry.entity_id, new_unique_id=new_uid
                    )

        hass.config_entries.async_update_entry(config_entry, version=new_version)

    _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Odstrani konfiguracijski vnos."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    task = coordinator._pending_refresh_task
    if task and not task.done():
        task.cancel()
    coordinator._pending_refresh_task = None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    if len(hass.data[DOMAIN]) == 0:
        for service in ("create_group", "delete_group", "rename_group",
                        "rename_device", "move_device_to_group"):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return bool(unload_ok)
