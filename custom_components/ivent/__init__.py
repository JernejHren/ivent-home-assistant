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
from .coordinator import IVentConfigEntry, IVentCoordinator, IVentRuntimeData

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


async def _async_options_updated(hass: HomeAssistant, entry: IVentConfigEntry) -> None:
    """Starejši HA: ponovno naloži vnos, a samo ob spremembi nastavitev.

    Listener se sproži ob vsaki spremembi vnosa (tudi pri rekonfiguraciji, ki vnos
    sama ponovno naloži), zato primerjamo z nastavitvami ob zagonu.
    Na novejšem HA tega ne uporabljamo: OptionsFlowWithReload naloži vnos sam.
    """
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is not None and runtime_data.options == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: IVentConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Uporabnik lahko ročno odstrani samo napravo, ki je strežnik ne vrača več."""
    data = entry.runtime_data.coordinator.data
    if data is None:
        return False
    prefix = f"{entry.entry_id}_"
    for domain, ident in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if ident == entry.entry_id:
            return False  # servisna naprava
        if ident.startswith(prefix):
            rest = ident[len(prefix):]
            if rest.isdigit() and int(rest) in data.groups_by_id:
                return False
        elif ident in data.devices_by_mac:
            return False
    return True


def _service_error(key: str, **placeholders: str) -> ServiceValidationError:
    """Napaka servisa s prevedenim sporočilom (exceptions v translations)."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


async def async_setup_entry(hass: HomeAssistant, entry: IVentConfigEntry) -> bool:
    """Nastavi i-Vent integracijo iz konfiguracijskega vnosa."""
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

    entry.runtime_data = IVentRuntimeData(
        coordinator=coordinator,
        client=client,
        options=dict(entry.options),  # za _async_options_updated (star HA)
    )

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
            raise _service_error("group_name_empty")
        try:
            await client.async_create_group(name)
        except IVentApiClientError as err:
            raise _service_error("create_group_failed", error=str(err)) from err
        await coordinator.async_request_delayed_refresh()

    async def handle_delete_group(call: ServiceCall) -> None:
        group_id = call.data.get("group_id")
        if group_id is None:
            raise _service_error("group_id_missing")
        try:
            await client.async_modify_group(group_id, {"delete": True})
        except IVentApiClientError as err:
            raise _service_error("delete_group_failed", error=str(err)) from err
        await coordinator.async_request_delayed_refresh()

    async def handle_rename_group(call: ServiceCall) -> None:
        group_id = call.data.get("group_id")
        new_name = call.data.get("new_name")
        if group_id is None:
            raise _service_error("group_id_missing")
        if not new_name or len(new_name.strip()) == 0:
            raise _service_error("new_group_name_empty")
        try:
            await client.async_modify_group(group_id, {"name": new_name})
        except IVentApiClientError as err:
            raise _service_error("rename_group_failed", error=str(err)) from err
        await coordinator.async_request_delayed_refresh()

    async def handle_rename_device(call: ServiceCall) -> None:
        device_mac = call.data.get("device_mac")
        new_name = call.data.get("new_name")
        if not device_mac:
            raise _service_error("device_mac_missing")
        if not new_name or len(new_name.strip()) == 0:
            raise _service_error("new_device_name_empty")
        try:
            await client.async_modify_device(device_mac, {"name": new_name})
        except IVentApiClientError as err:
            raise _service_error("rename_device_failed", error=str(err)) from err
        await coordinator.async_request_delayed_refresh()

    async def handle_move_device(call: ServiceCall) -> None:
        device_mac = call.data.get("device_mac")
        group_id = call.data.get("group_id")
        if not device_mac:
            raise _service_error("device_mac_missing")
        if group_id is None:
            raise _service_error("target_group_missing")
        try:
            await client.async_modify_device(device_mac, {"group_id": group_id})
        except IVentApiClientError as err:
            raise _service_error("move_device_failed", error=str(err)) from err
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


async def async_unload_entry(hass: HomeAssistant, entry: IVentConfigEntry) -> bool:
    """Odstrani konfiguracijski vnos (tudi če setup ni dokončal priprave podatkov)."""
    runtime_data = getattr(entry, "runtime_data", None)
    coordinator = runtime_data.coordinator if runtime_data else None
    if coordinator is not None:
        task = coordinator._pending_refresh_task
        if task and not task.done():
            task.cancel()
        coordinator._pending_refresh_task = None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and coordinator is not None:
        await coordinator.async_stop_push()

    if unload_ok and not any(
        e.entry_id != entry.entry_id
        for e in hass.config_entries.async_loaded_entries(DOMAIN)
    ):
        for service in ("create_group", "delete_group", "rename_group",
                        "rename_device", "move_device_to_group"):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return bool(unload_ok)
