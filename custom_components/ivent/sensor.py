from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    sensors = []
    for group in coordinator.data.get("groups", []):
        sensors.append(IVentGroupSensor(coordinator, group))
    async_add_entities(sensors)

class IVentGroupSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, group):
        super().__init__(coordinator)
        self._attr_name = f"i-Vent {group['name']}"
        self._attr_unique_id = f"ivent_group_{group['id']}"
        self._group = group

    @property
    def native_value(self):
        return self._group.get("state", {}).get("mode", {}).get("work_mode", "Unknown")
