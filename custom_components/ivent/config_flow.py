"""Konfiguracijski tok za i-Vent Smart Home."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from typing import Any, Dict

from .const import DOMAIN, CONF_LOCATION_ID
from .api import IVentApiClient, IVentApiClientError, IVentApiAuthError

class IVentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Obravnava konfiguracijski tok za i-Vent."""

    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Obravnava korak, kjer uporabnik vnese podatke."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            location_id = user_input[CONF_LOCATION_ID]

            await self.async_set_unique_id(location_id)
            self._abort_if_unique_id_configured()

            try:
                session = async_get_clientsession(self.hass)
                client = IVentApiClient(session, api_key, location_id)
                await client.async_get_info()
            except IVentApiAuthError:
                errors["base"] = "auth_error"
            except IVentApiClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"i-Vent Location {location_id}",
                    data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_LOCATION_ID): str,
            }),
            errors=errors,
            description_placeholders={
                "api_url": "https://cloud.i-vent.com/"
            }
        )
