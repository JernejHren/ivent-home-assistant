from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][config_entry.entry_id]["client"]
    buttons = []

    for group in coordinator.data.get("groups", []):
        buttons.append(IVentBoostButton(coordinator, client, group))
        buttons.append(IVentOffButton(coordinator, client, group))

    async_add_entities(buttons)

class IVentBoostButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, client, group):
        super().__init__(coordinator)
        self._client = client
        self._group = group
        self._attr_name = f"Boost {group['name']}"
        self._attr_unique_id = f"ivent_boost_{group['id']}"

    async def async_press(self):
        await self._client.set_group_mode(self._group["id"], "IVentWorkAuto", "IVentSpecialBoost")

class IVentOffButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, client, group):
        super().__init__(coordinator)
        self._client = client
        self._group = group
        self._attr_name = f"Turn Off {group['name']}"
        self._attr_unique_id = f"ivent_off_{group['id']}"

    async def async_press(self):
        await self._client.set_group_mode(self._group["id"], "IVentWorkOff")
