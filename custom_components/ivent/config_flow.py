import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from .const import DOMAIN, CONF_LOCATION_ID

class IVentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="i-Vent", data={
                CONF_API_KEY: user_input[CONF_API_KEY],
                CONF_LOCATION_ID: user_input[CONF_LOCATION_ID],
            })

        data_schema = vol.Schema({
            vol.Required(CONF_API_KEY): str,
            vol.Required(CONF_LOCATION_ID): int,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
