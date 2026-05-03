"""Konfiguracijski tok za i-Vent Smart Home."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_API_KEY
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from typing import Any, Dict

from .const import DOMAIN, CONF_LOCATION_ID
from .api import IVentApiClient, IVentApiClientError, IVentApiAuthError, IVentLocation

class IVentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Obravnava konfiguracijski tok za i-Vent."""

    VERSION = 2

    def __init__(self) -> None:
        """Inicializira tok."""
        self._api_key: str | None = None
        self._locations: list[IVentLocation] = []

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Prvi korak: vnos API ključa in odkritje lokacij."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY]
            
            try:
                session = async_get_clientsession(self.hass)
                client = IVentApiClient(session, self._api_key)
                self._locations = await client.async_get_locations()
                
                if not self._locations:
                    errors["base"] = "no_locations"
                else:
                    if len(self._locations) == 1:
                        location = self._locations[0]
                        return await self._create_entry_for_location(
                            location["id"], location.get("name", "Default")
                        )
                    return await self.async_step_location()

            except IVentApiAuthError:
                errors["base"] = "auth_error"
            except IVentApiClientError:
                errors["base"] = "cannot_connect"
            except AbortFlow:
                raise
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
            description_placeholders={"api_url": "https://cloud.i-vent.com/"}
        )

    async def async_step_location(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Drugi korak: izbira lokacije (če jih je več)."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            location_id = user_input[CONF_LOCATION_ID]
            # Poiščemo polno ime za naslov vnosa
            location_name = next(
                (l["name"] for l in self._locations if l["id"] == location_id),
                location_id
            )
            return await self._create_entry_for_location(location_id, location_name)

        location_options = {l["id"]: l.get("name", l["id"]) for l in self._locations}

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema({
                vol.Required(CONF_LOCATION_ID): vol.In(location_options),
            }),
            errors=errors
        )

    async def _create_entry_for_location(self, location_id: str, location_name: str) -> ConfigFlowResult:
        """Pomožna metoda za ustvarjanje vnosa."""
        await self.async_set_unique_id(location_id)
        self._abort_if_unique_id_configured()
        
        return self.async_create_entry(
            title=f"i-Vent: {location_name}",
            data={
                CONF_API_KEY: self._api_key,
                CONF_LOCATION_ID: location_id,
            }
        )

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> ConfigFlowResult:
        """Sproži reautentikacijo."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Obravnava potrditev reautentikacije."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                client = IVentApiClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_API_KEY],
                    self._get_reauth_entry().data[CONF_LOCATION_ID]
                )
                await client.async_get_info()
            except IVentApiAuthError:
                errors['base'] = 'auth_error'
            except IVentApiClientError:
                errors['base'] = 'cannot_connect'
            except AbortFlow:
                raise
            except Exception:
                errors['base'] = 'cannot_connect'
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id='reauth_confirm',
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors
        )

    async def async_step_reconfigure(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rekonfiguracija obstoječe integracije."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                client = IVentApiClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_API_KEY],
                    user_input[CONF_LOCATION_ID],
                )
                await client.async_get_info()
            except IVentApiAuthError:
                errors['base'] = 'auth_error'
            except IVentApiClientError:
                errors['base'] = 'cannot_connect'
            except AbortFlow:
                raise
            except Exception:
                errors['base'] = 'cannot_connect'
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates=user_input
                )
        
        entry = self._get_reconfigure_entry()
        current_api_key = entry.data.get(CONF_API_KEY, "")
        current_location_id = entry.data.get(CONF_LOCATION_ID, "")

        return self.async_show_form(
            step_id='reconfigure',
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY, default=current_api_key): str,
                vol.Required(CONF_LOCATION_ID, default=current_location_id): str,
            }),
            errors=errors
        )
