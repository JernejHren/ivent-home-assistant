"""i-Vent Smart Home integracija."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    config_validation as cv,
)
from homeassistant.exceptions import ServiceValidationError

from .api import IVentApiClient, IVentApiClientError
from .backend import IVentBackend
from .config_flow import OPTIONS_AUTO_RELOAD
from .const import (
    CONF_LOCAL_HOST, CONF_LOCAL_MAC, CONF_LOCATION_ID, CONF_MODE, DOMAIN, MODE_CLOUD,
    MODE_HYBRID, MODE_LOCAL, OPT_INFO_FALLBACK, PLATFORMS,
)
from .local_backend import IVentHybridBackend, IVentLocalBackend
from .coordinator import IVentCoordinator

_LOGGER = logging.getLogger(__name__)


def _build_backend(hass: HomeAssistant, entry: ConfigEntry) -> IVentBackend:
    """Backend glede na izbrani način (vnosi brez ``mode`` so oblačni)."""
    mode = entry.data.get(CONF_MODE, MODE_CLOUD)

    def cloud() -> IVentApiClient:
        return IVentApiClient(
            session=async_get_clientsession(hass),
            api_key=entry.data["api_key"],
            location_id=entry.data[CONF_LOCATION_ID],
        )

    if mode == MODE_CLOUD:
        return cloud()

    local = IVentLocalBackend.create(
        # oblak sprejema u64 tudi predznačeno; lokalno vedno nepredznačeno
        location_id=int(entry.data[CONF_LOCATION_ID]) % (1 << 64),
        master_host=entry.data[CONF_LOCAL_HOST],
        master_mac=entry.data[CONF_LOCAL_MAC],
    )
    if mode == MODE_LOCAL:
        return local
    return IVentHybridBackend(
        local, cloud(), info_fallback=entry.options.get(OPT_INFO_FALLBACK, False))


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Starejši HA: ponovno naloži vnos, a samo ob spremembi nastavitev.

    Listener se sproži ob vsaki spremembi vnosa (tudi pri rekonfiguraciji, ki vnos
    sama ponovno naloži), zato primerjamo z nastavitvami ob zagonu.
    Na novejšem HA tega ne uporabljamo: OptionsFlowWithReload naloži vnos sam.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is not None and entry_data.get("options") == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nastavi i-Vent integracijo iz konfiguracijskega vnosa."""
    hass.data.setdefault(DOMAIN, {})

    mode = entry.data.get(CONF_MODE, MODE_CLOUD)
    if mode == MODE_CLOUD:
        _LOGGER.info("Setting up i-Vent in cloud mode")
    else:
        _LOGGER.info("Setting up i-Vent in %s mode (Master %s)", mode, entry.data[CONF_LOCAL_HOST])
    client = _build_backend(hass, entry)
    if not OPTIONS_AUTO_RELOAD:
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    coordinator = IVentCoordinator(hass, client, entry)
    await coordinator.async_start_push()  # no-op pri oblačnem odjemalcu
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_stop_push()
        raise

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "options": dict(entry.options),  # za primerjavo v _async_options_updated (star HA)
    }

    # Ustvarimo glavno "servisno" napravo, na katero se vežejo vse ostale (via_device)
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="i-Vent",
        name="i-Vent System",
        model={MODE_CLOUD: "Cloud Location", MODE_LOCAL: "Local Location",
               MODE_HYBRID: "Hybrid Location"}.get(entry.data.get(CONF_MODE, MODE_CLOUD),
                                                    "Cloud Location"),
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=(
            None if entry.data.get(CONF_MODE) == MODE_LOCAL else "https://cloud.i-vent.com/"),
    )

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

    if config_entry.version < 3:
        entry_id = config_entry.entry_id
        ent_reg = er.async_get(hass)

        for entity_entry in er.async_entries_for_config_entry(ent_reg, entry_id):
            old_uid = entity_entry.unique_id
            if not old_uid:
                continue

            new_uid = old_uid

            # Binary sensor device entities should use the same MAC-based
            # unique_id strategy as other device entities.
            if old_uid.startswith(f"{entry_id}_"):
                stripped_uid = old_uid[len(f"{entry_id}_"):]
                if (
                    stripped_uid.endswith("_problem")
                    or stripped_uid.endswith("_alive")
                    or stripped_uid.endswith("_filter")
                ):
                    new_uid = stripped_uid

            if new_uid != old_uid:
                _LOGGER.info(
                    "Migrating entity %s unique_id from %s to %s",
                    entity_entry.entity_id,
                    old_uid,
                    new_uid,
                )
                ent_reg.async_update_entity(
                    entity_entry.entity_id, new_unique_id=new_uid
                )

        hass.config_entries.async_update_entry(config_entry, version=3)

    if config_entry.version < 4:
        # v4: izbira načina delovanja; obstoječi vnosi so oblačni
        hass.config_entries.async_update_entry(
            config_entry, data={**config_entry.data, CONF_MODE: MODE_CLOUD}, version=4)

    _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Odstrani konfiguracijski vnos (tudi če setup ni dokončal priprave podatkov)."""
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id)
    coordinator = entry_data["coordinator"] if entry_data else None
    if coordinator is not None:
        task = coordinator._pending_refresh_task
        if task and not task.done():
            task.cancel()
        coordinator._pending_refresh_task = None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if coordinator is not None:
            await coordinator.async_stop_push()
        domain_data.pop(entry.entry_id, None)

    if len(domain_data) == 0:
        for service in ("create_group", "delete_group", "rename_group",
                        "rename_device", "move_device_to_group"):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return bool(unload_ok)
