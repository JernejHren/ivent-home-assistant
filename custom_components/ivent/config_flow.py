"""Konfiguracijski tok za i-Vent Smart Home (oblak, lokalno ali kombinirano)."""
from __future__ import annotations

import re
from typing import Any, Dict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE, ConfigEntry, ConfigEntryState, ConfigFlowResult, OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA >= 2025.8: samodejno ponovno nalaganje ob spremembi nastavitev
    from homeassistant.config_entries import OptionsFlowWithReload as _OptionsFlowBase
except ImportError:  # starejši HA: vnos ponovno naloži update listener v __init__.py
    _OptionsFlowBase = OptionsFlow  # type: ignore[misc,assignment]

OPTIONS_AUTO_RELOAD = _OptionsFlowBase is not OptionsFlow

from .api import (
    IVentApiAuthError, IVentApiClient, IVentApiClientError, IVentApiConnectionError,
)
from .const import (
    CONF_LOCAL_HOST, CONF_LOCAL_MAC, CONF_LOCATION_ID, CONF_MODE, DOMAIN, LOCAL_MODES,
    MODE_CLOUD, MODE_HYBRID, MODE_LOCAL, OPT_INFO_FALLBACK,
)
from .ivent_local.discovery import discover_master
from .local_backend import IVentLocalBackend

DISCOVERY_TIMEOUT = 8.0
_MAC_RE = re.compile(r"^([0-9a-f]{2})([:-])(?:[0-9a-f]{2}\2){4}[0-9a-f]{2}$", re.IGNORECASE)
_U64 = 1 << 64
# HTTP kode, ki pomenijo "endpoint /locations ne obstaja" (uradni API ga nima)
_NO_LOCATION_LIST_STATUSES = (404, 405, 501)


def _parse_location_id(value: Any) -> int | None:
    """'12117...' ali '0xa829...' -> u64 (podpira tudi predznačeno obliko iz oblaka)."""
    try:
        text = str(value).strip()
        number = int(text, 16) if text.lower().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return None
    return number % _U64


def _normalize_mac(value: str) -> str | None:
    value = value.strip()
    if not _MAC_RE.match(value):
        return None
    return value.lower().replace("-", ":")


class IVentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Obravnava konfiguracijski tok za i-Vent."""

    VERSION = 4

    def __init__(self) -> None:
        self._mode: str | None = None
        self._api_key: str | None = None
        self._location_id: str | None = None
        # hibrid brez ID-ja lokacije: določi ga lokalno odkrivanje, oblak se preveri po tem
        self._verify_cloud_after_local = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "IVentOptionsFlow":
        return IVentOptionsFlow()

    # ------------------------------------------------------------------
    # Izbira načina
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Prvi korak: izbira načina delovanja."""
        return self.async_show_menu(step_id="user",
                                    menu_options=[MODE_CLOUD, MODE_LOCAL, MODE_HYBRID])

    async def async_step_cloud(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        self._mode = MODE_CLOUD
        return await self._cloud_step("cloud", user_input)

    async def async_step_hybrid(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        self._mode = MODE_HYBRID
        return await self._cloud_step("hybrid", user_input)

    # ------------------------------------------------------------------
    # Oblak (API ključ, lokacije)
    # ------------------------------------------------------------------

    async def _cloud_step(self, step_id: str, user_input: Dict[str, Any] | None) -> ConfigFlowResult:
        """Vnos API ključa in ID-ja lokacije; pri hibridu nadaljuje z lokalnim korakom.

        Uradni API seznama lokacij nima (ključ velja za eno lokacijo), zato je ID lokacije
        obvezen. Edina izjema je kombinirani način: tam ga lahko določi lokalno odkrivanje
        Masterja (ID je v oblaku in lokalno enak).
        """
        errors: Dict[str, str] = {}
        reconfigure = self.source == SOURCE_RECONFIGURE

        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY]
            location_id = (user_input.get(CONF_LOCATION_ID) or "").strip()
            if not location_id:
                if self._mode == MODE_HYBRID and not reconfigure:
                    self._verify_cloud_after_local = True
                    return await self.async_step_local()
                errors["base"] = "location_id_required"
            else:
                try:
                    client = IVentApiClient(async_get_clientsession(self.hass), self._api_key,
                                            location_id)
                    await client.async_get_info()  # preveri ključ in lokacijo
                    return await self._cloud_done(location_id)
                except IVentApiAuthError:
                    errors["base"] = "auth_error"
                except IVentApiClientError:
                    errors["base"] = "cannot_connect"
                except AbortFlow:
                    raise
                except Exception:  # noqa: BLE001 - vsaka druga napaka = ni povezave
                    errors["base"] = "cannot_connect"

        return self._cloud_form(step_id, errors, reconfigure)

    def _cloud_form(self, step_id: str, errors: Dict[str, str], reconfigure: bool) -> ConfigFlowResult:
        if reconfigure:
            entry = self._get_reconfigure_entry()
            schema = vol.Schema({
                vol.Required(CONF_API_KEY, default=entry.data.get(CONF_API_KEY, "")): str,
                vol.Required(CONF_LOCATION_ID, default=entry.data.get(CONF_LOCATION_ID, "")): str,
            })
        else:
            location_key = (vol.Optional(CONF_LOCATION_ID) if self._mode == MODE_HYBRID
                            else vol.Required(CONF_LOCATION_ID))
            schema = vol.Schema({vol.Required(CONF_API_KEY): str, location_key: str})
        return self.async_show_form(
            step_id=step_id, data_schema=schema, errors=errors,
            description_placeholders={"api_url": "https://cloud.i-vent.com/"},
        )

    async def _cloud_done(self, location_id: str) -> ConfigFlowResult:
        self._location_id = location_id
        if self._mode == MODE_HYBRID:
            return await self.async_step_local()
        return await self._finish({
            CONF_MODE: MODE_CLOUD,
            CONF_API_KEY: self._api_key,
            CONF_LOCATION_ID: location_id,
        })

    # ------------------------------------------------------------------
    # Lokalno (Master: IP, MAC, locationId)
    # ------------------------------------------------------------------

    def _other_local_entry_exists(self) -> bool:
        """En socket na gostitelja (izvorni port 1028): samo ena lokalna lokacija."""
        own = self._get_reconfigure_entry().entry_id if self.source == SOURCE_RECONFIGURE else None
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == own or entry.data.get(CONF_MODE) not in LOCAL_MODES:
                continue
            if self._location_id is not None and entry.unique_id == self._location_id:
                continue  # ista lokacija: _finish javi already_configured
            return True
        return False

    async def async_step_local(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Lokalni Master: IP/MAC/locationId; manjkajoče odkrije s poslušanjem broadcasta."""
        if self._mode is None:
            self._mode = MODE_LOCAL
        if self._other_local_entry_exists():
            return self.async_abort(reason="single_local_entry")

        errors: Dict[str, str] = {}
        entry = self._get_reconfigure_entry() if self.source == SOURCE_RECONFIGURE else None
        defaults = entry.data if entry is not None else {}
        ask_location = self._location_id is None

        if user_input is not None:
            error, data = await self._resolve_local(user_input)
            if error is None and data is not None:
                return await self._finish(data)
            errors["base"] = error or "cannot_connect_local"

        fields: Dict[Any, Any] = {
            vol.Optional(CONF_LOCAL_HOST, default=defaults.get(CONF_LOCAL_HOST, "")): str,
            vol.Optional(CONF_LOCAL_MAC, default=defaults.get(CONF_LOCAL_MAC, "")): str,
        }
        if ask_location:
            fields[vol.Optional(CONF_LOCATION_ID, default="")] = str
        return self.async_show_form(step_id="local", data_schema=vol.Schema(fields), errors=errors)

    async def _resolve_local(self, user_input: Dict[str, Any]) -> tuple[str | None, Dict[str, Any] | None]:
        """Dopolni manjkajoče (odkrivanje), preveri vnos in povezavo. -> (napaka, podatki)."""
        host = (user_input.get(CONF_LOCAL_HOST) or "").strip()
        mac_raw = (user_input.get(CONF_LOCAL_MAC) or "").strip()
        mac = _normalize_mac(mac_raw) if mac_raw else None
        if mac_raw and mac is None:
            return "invalid_mac", None

        known = self._location_id if self._location_id is not None else user_input.get(CONF_LOCATION_ID)
        location = _parse_location_id(known) if known else None
        if known and location is None:
            return "invalid_location_id", None

        if not (host and mac and location is not None):
            try:
                found = await discover_master(timeout=DISCOVERY_TIMEOUT, host=host or None)
            except OSError:
                return "port_in_use", None
            if found is None:
                return "discovery_failed", None
            host = host or found.ip
            mac = mac or found.mac
            if location is None:
                location = found.location_id
            elif location != found.location_id:
                return "location_mismatch", None

        error = await self._validate_local(host, mac, location)
        if error:
            return error, None
        if self._verify_cloud_after_local:
            error = await self._verify_cloud(str(location))
            if error:
                return error, None

        data: Dict[str, Any] = {
            CONF_MODE: self._mode,
            CONF_LOCATION_ID: self._location_id if self._location_id is not None else str(location),
            CONF_LOCAL_HOST: host,
            CONF_LOCAL_MAC: mac,
        }
        if self._mode == MODE_HYBRID:
            data[CONF_API_KEY] = self._api_key
        return None, data

    async def _verify_cloud(self, location_id: str) -> str | None:
        """Hibrid brez ročnega ID-ja: preveri API ključ za lokalno odkrito lokacijo."""
        try:
            client = IVentApiClient(async_get_clientsession(self.hass), self._api_key or "", location_id)
            await client.async_get_info()
        except IVentApiAuthError:
            return "auth_error"
        except Exception:  # noqa: BLE001
            return "cannot_connect"
        self._location_id = location_id
        return None

    async def _validate_local(self, host: str, mac: str, location: int) -> str | None:
        """Ping Masterja z začasnim socketom (izvorni port 1028)."""
        entry = self._get_reconfigure_entry() if self.source == SOURCE_RECONFIGURE else None
        unloaded = False
        if (entry is not None and entry.state is ConfigEntryState.LOADED
                and entry.data.get(CONF_MODE) in LOCAL_MODES):
            # delujoč vnos drži socket na 1028: odgovori bi lahko šli njemu
            unloaded = await self.hass.config_entries.async_unload(entry.entry_id)

        backend = IVentLocalBackend.create(location_id=location, master_host=host, master_mac=mac)
        error: str | None = None
        try:
            await backend.async_start()
            await backend.async_ping()
        except OSError:
            error = "port_in_use"
        except IVentApiConnectionError:
            error = "cannot_connect_local"
        except IVentApiClientError:
            error = "cannot_connect_local"
        finally:
            await backend.async_stop()
        if error and unloaded and entry is not None:
            await self.hass.config_entries.async_setup(entry.entry_id)
        return error

    # ------------------------------------------------------------------
    # Zaključek
    # ------------------------------------------------------------------

    async def _finish(self, data: Dict[str, Any]) -> ConfigFlowResult:
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=data)
        location_id = data[CONF_LOCATION_ID]
        await self.async_set_unique_id(location_id)
        self._abort_if_unique_id_configured()
        # naslov brez ID-ja lokacije (v lokalnem načinu je to poverilnica)
        label = {MODE_CLOUD: "Cloud", MODE_LOCAL: "Local", MODE_HYBRID: "Hybrid"}[data[CONF_MODE]]
        return self.async_create_entry(title=f"i-Vent {label}", data=data)

    # ------------------------------------------------------------------
    # Reauth (samo oblak) in rekonfiguracija
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                client = IVentApiClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_API_KEY],
                    self._get_reauth_entry().data[CONF_LOCATION_ID],
                )
                await client.async_get_info()
            except IVentApiAuthError:
                errors["base"] = "auth_error"
            except IVentApiClientError:
                errors["base"] = "cannot_connect"
            except AbortFlow:
                raise
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: user_input[CONF_API_KEY]})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rekonfiguracija: izbira načina (lahko tudi preklop), nato ustrezni koraki."""
        entry = self._get_reconfigure_entry()
        self._location_id = entry.data.get(CONF_LOCATION_ID)
        self._api_key = entry.data.get(CONF_API_KEY)
        return self.async_show_menu(step_id="reconfigure",
                                    menu_options=[MODE_CLOUD, MODE_LOCAL, MODE_HYBRID])


class IVentOptionsFlow(_OptionsFlowBase):
    """Nastavitve: rezerva stanja iz oblaka (samo kombinirani način)."""

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_MODE) != MODE_HYBRID:
            return self.async_abort(reason="no_options")
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(OPT_INFO_FALLBACK, False)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Optional(OPT_INFO_FALLBACK, default=current): bool}),
        )
