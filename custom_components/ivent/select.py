"""Podpora za i-Vent izbirnike."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IVentCoordinator, IVentGroupData, IVentDeviceData
from .entity import IVentGroupEntity, IVentDeviceEntity

# --- Ventilation mode maps ---
VENTILATION_MODE_NORMAL = "Normal"
VENTILATION_MODE_BYPASS = "Bypass"
HA_MODE_RECUPERATION = "Rekuperacija"
HA_MODE_BYPASS = "Prezračevanje (Bypass)"
API_TO_HA_MODE_MAP = {VENTILATION_MODE_NORMAL: HA_MODE_RECUPERATION, VENTILATION_MODE_BYPASS: HA_MODE_BYPASS}
HA_TO_API_MODE_MAP = {v: k for k, v in API_TO_HA_MODE_MAP.items()}

# --- Speed maps ---
SPEED_MAP = {"Stopnja 1": 1, "Stopnja 2": 2, "Stopnja 3": 3}
SPEED_MAP_REV = {v: k for k, v in SPEED_MAP.items()}

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavi select entitete iz konfiguracijskega vnosa."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: IVentCoordinator = data["coordinator"]

    added_entities: set[str] = set()

    def _add_new_entities() -> None:
        if coordinator.data is None:
            return
            
        new_entities: list[SelectEntity] = []

        entry_id = coordinator.config_entry.entry_id

        for group in coordinator.data.groups_by_id.values():
            uid_mode = f"{entry_id}_{group.id}_ventilation_mode"
            if uid_mode not in added_entities:
                added_entities.add(uid_mode)
                new_entities.append(IVentVentilationModeSelect(coordinator, group))

            uid_speed = f"{entry_id}_{group.id}_speed"
            if uid_speed not in added_entities:
                added_entities.add(uid_speed)
                new_entities.append(IVentSpeedSelect(coordinator, group))

        for device in coordinator.data.devices_by_mac.values():
            uid_move = f"{device.mac_address}_move_to_group"
            if uid_move not in added_entities:
                added_entities.add(uid_move)
                new_entities.append(IVentMoveDeviceSelect(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


# ---------------------------------------------------------------------------
# Group selects — both use IVentGroupEntity._group (O(1))
# ---------------------------------------------------------------------------

class IVentVentilationModeSelect(IVentGroupEntity, SelectEntity):
    """Predstavlja izbirnik načina prezračevanja (Rekuperacija/Bypass)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_ventilation_mode"
        self._attr_translation_key = "ventilation_mode"
        self._attr_options = list(HA_TO_API_MODE_MAP.keys())
        self._update_state()

    def _update_state(self) -> None:
        group = self._group
        actual = API_TO_HA_MODE_MAP.get(group.remote_control_work_mode) if group else None
        self._attr_current_option = self._get_optimistic_attr("current_option", actual)

    @property
    def current_option(self) -> str | None:
        group = self._group
        actual = API_TO_HA_MODE_MAP.get(group.remote_control_work_mode) if group else None
        return self._get_optimistic_attr("current_option", actual)  # type: ignore[no-any-return]

    async def async_select_option(self, option: str) -> None:
        api_mode = HA_TO_API_MODE_MAP.get(option)
        if not api_mode:
            return
        group = self._group
        if group is None:
            return
        payload = self._build_remote_settings_payload(
            api_mode,
            group.remote_control_speed,
            keep_off=True,
        )
        await self._async_handle_write("current_option", option, self.async_update_group(payload))


class IVentSpeedSelect(IVentGroupEntity, SelectEntity):
    """Predstavlja izbirnik za hitrost ventilatorja."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:fan-speed-2"

    def __init__(self, coordinator: IVentCoordinator, group_data: IVentGroupData) -> None:
        super().__init__(coordinator, group_data)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._group_id}_speed"
        self._attr_translation_key = "speed"
        self._attr_options = list(SPEED_MAP.keys())
        self._update_state()

    def _update_state(self) -> None:
        group = self._group
        actual = SPEED_MAP_REV.get(group.remote_control_speed) if group else None
        self._attr_current_option = self._get_optimistic_attr("current_option", actual)

    @property
    def current_option(self) -> str | None:
        group = self._group
        actual = SPEED_MAP_REV.get(group.remote_control_speed) if group else None
        return self._get_optimistic_attr("current_option", actual)  # type: ignore[no-any-return]

    async def async_select_option(self, option: str) -> None:
        speed = SPEED_MAP.get(option)
        if speed is None:
            return
        group = self._group
        if group is None:
            return
        payload = self._build_remote_settings_payload(
            group.remote_control_work_mode,
            speed,
            keep_off=True,
        )
        await self._async_handle_write("current_option", option, self.async_update_group(payload))


# ---------------------------------------------------------------------------
# Device select — uses IVentDeviceEntity base (stable MAC-based identity)
# ---------------------------------------------------------------------------

class IVentMoveDeviceSelect(IVentDeviceEntity, SelectEntity):
    """Predstavlja izbirnik za premik enote v drugo skupino.

    unique_id: {mac_address}_move_to_group  (stable — MAC never changes)
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:arrow-right-bold-box-outline"

    def __init__(
        self,
        coordinator: IVentCoordinator,
        device_data: IVentDeviceData,
    ) -> None:
        super().__init__(coordinator, device_data)
        self._attr_unique_id = f"{self._device_mac}_move_to_group"
        self._attr_translation_key = "move_device"
        self._update_options()

    def _update_options(self) -> None:
        """Refresh group options from coordinator (no nested loops)."""
        if self.coordinator.data is None:
            self._groups_map: dict[str, int] = {}
            self._attr_options = []
            return
        self._groups_map = {
            g.name: gid
            for gid, g in self.coordinator.data.groups_by_id.items()
            if g.name
        }
        self._attr_options = list(self._groups_map.keys())
        device = self._device
        if device:
            current_group = self.coordinator.data.groups_by_id.get(device.group_id)
            self._attr_current_option = current_group.name if current_group else None

    def _update_state(self) -> None:
        self._update_options()

    def _refresh_device_info(self) -> None:
        """Refresh group options from coordinator."""
        self._update_state()

    async def async_select_option(self, option: str) -> None:
        target_group_id = self._groups_map.get(option)
        if not target_group_id:
            return
        await self._async_handle_write("current_option", option, self.async_update_device({"group_id": target_group_id}))

