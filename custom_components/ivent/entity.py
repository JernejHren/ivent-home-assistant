"""Osnovni razredi za i-Vent entitete.

unique_id strategy
──────────────────
GROUP entities:   {entry_id}_{group.id}_{entity_key}
  → group.id is an immutable integer assigned by the i-Vent API.
  → Renaming a group does NOT change group.id, so no duplicate entities.

DEVICE entities:  {mac_address}_{entity_key}
  → MAC address is the hardware identifier — immutable by definition.
  → Renaming a device does NOT change its MAC, so no duplicate entities.

SCHEDULE entities: {entry_id}_schedule_{schedule_id}
  → schedule_id is assigned by the API and is stable.

DeviceInfo strategy
───────────────────
- Group devices:   identifiers={(DOMAIN, f"{entry_id}_{group_id}")}
                   via_device=(DOMAIN, entry_id)   ← the "i-Vent System" service device
- Physical devices: identifiers={(DOMAIN, mac_address)}
                    via_device=(DOMAIN, entry_id)
- Device **names** are NOT mutated after init — Home Assistant's device registry
  updates the name automatically when it sees the same identifiers with a new name
  on coordinator updates (via entity re-registration / DeviceInfo refresh).
"""
from __future__ import annotations

import asyncio
import copy
import logging
from time import monotonic
from typing import Any, Dict

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import ALL_GROUPS_ID, DOMAIN, API_MODE_WORK_OFF
from .coordinator import IVentCoordinator, IVentGroupData, IVentDeviceData
from .api import IVentScheduleItem

_LOGGER = logging.getLogger(__name__)

# Polja ModifyGroup, ki jih ima smisel razširiti iz skupine "vse naprave"
# na prave skupine. Preimenovanje in brisanje se nikoli ne razširita.
_FAN_OUT_KEYS = frozenset({"led_mode", "buzzer_mode", "remote_work_mode"})

_WORK_MODE_BY_REMOTE_SETTINGS = {
    ("Normal", 1): "IVentRecuperation1",
    ("Normal", 2): "IVentRecuperation2",
    ("Normal", 3): "IVentRecuperation3",
    ("Bypass", 1): "IVentBypass1",
    ("Bypass", 2): "IVentBypass2",
    ("Bypass", 3): "IVentBypass3",
}


class _GroupPayload(dict):  # type: ignore[type-arg]
    """Payload za modify_group, ki si zapomni, kaj je bilo dejansko spremenjeno.

    Za skupino "vse naprave" mora vsaka ciljna skupina dobiti SVOJE stanje
    z uporabljenimi spremembami, ne stanja skupine 1.
    """

    changes: Dict[str, Any]

    def __init__(self, data: Dict[str, Any], changes: Dict[str, Any]) -> None:
        super().__init__(data)
        self.changes = dict(changes)


class IVentBaseEntity(CoordinatorEntity[IVentCoordinator]):
    """Osnovni razred za vse i-Vent entitete z optimističnim stanjem."""

    _attr_has_entity_name: bool = True
    _attr_should_poll = False

    def __init__(self, coordinator: IVentCoordinator) -> None:
        """Inicializira osnovno entiteto."""
        super().__init__(coordinator)
        self._last_write_times: Dict[str, float] = {}
        self._assumed_state: Dict[str, Any] = {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Posodobi stanje entitete.

        Optimistično stanje se preverja na nivoju posameznih atributov
        v metodi _get_optimistic_attr.
        """
        self._refresh_device_info()
        self._update_state()
        self.async_write_ha_state()

    def _refresh_device_info(self) -> None:
        """Override v podrazredih za osvežitev DeviceInfo (npr. ime)."""

    def _update_state(self) -> None:
        """Override v podrazredih za posodobitev atributov iz koordinatorja."""

    def _get_optimistic_attr(self, key: str, actual_value: Any) -> Any:
        """Vrne predvideno stanje, če smo v oknu za preprečevanje odboja (revert)."""
        last_write = self._last_write_times.get(key, 0)
        if monotonic() - last_write < 2.0 and key in self._assumed_state:
            return self._assumed_state[key]
        return actual_value

    async def _async_handle_write(self, key: str, value: Any, coro: Any) -> None:
        """Helper za izvajanje zapisov z optimistično posodobitvijo."""
        self._assumed_state[key] = value
        self._last_write_times[key] = monotonic()
        self.async_write_ha_state()

        try:
            await coro
        except Exception:
            self._assumed_state.pop(key, None)
            self.async_write_ha_state()
            raise

    async def _async_handle_writes(self, updates: dict[str, Any], coro: Any) -> None:
        """Helper za izvajanje več zapisov z optimistično posodobitvijo."""
        previous_assumed_values: dict[str, Any] = {}
        previous_write_times: dict[str, float] = {}
        assumed_keys_present: dict[str, bool] = {}
        write_time_keys_present: dict[str, bool] = {}

        for key, value in updates.items():
            assumed_keys_present[key] = key in self._assumed_state
            write_time_keys_present[key] = key in self._last_write_times
            if assumed_keys_present[key]:
                previous_assumed_values[key] = self._assumed_state[key]
            if write_time_keys_present[key]:
                previous_write_times[key] = self._last_write_times[key]

            self._assumed_state[key] = value
            self._last_write_times[key] = monotonic()

        self.async_write_ha_state()

        try:
            await coro
        except Exception:
            for key in updates:
                if assumed_keys_present[key]:
                    self._assumed_state[key] = previous_assumed_values[key]
                else:
                    self._assumed_state.pop(key, None)

                if write_time_keys_present[key]:
                    self._last_write_times[key] = previous_write_times[key]
                else:
                    self._last_write_times.pop(key, None)

            self.async_write_ha_state()
            raise


class IVentGroupEntity(IVentBaseEntity):
    """Osnovni razred za entitete, ki so vezane na skupino (group).

    Identifiers use the API's immutable group.id (int), so renaming a group
    via the API (or HA service) will never create a duplicate HA entity.
    """

    _group_id: int

    def __init__(
        self,
        coordinator: IVentCoordinator,
        group_data: IVentGroupData,
    ) -> None:
        """Inicializira entiteto skupine."""
        super().__init__(coordinator)
        self._group_id = group_data.id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_{self._group_id}")},
            name=group_data.name,
            manufacturer="i-Vent",
            model="Ventilation Group",
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    # ------------------------------------------------------------------
    # Single property: always fresh from coordinator.data (no local copy)
    # ------------------------------------------------------------------

    @property
    def _group(self) -> IVentGroupData | None:
        """Return the current group data from coordinator (O(1) dict lookup)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.groups_by_id.get(self._group_id)  # type: ignore[no-any-return]

    @property
    def available(self) -> bool:
        """Vrne True samo, če je bil zadnji API klic uspešen in skupina obstaja."""
        return self.coordinator.last_update_success and self._group is not None

    def _prepare_payload(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Pripravi veljaven payload za pošiljanje na API.

        Reads ALWAYS from the coordinator's latest data, never from stale
        instance variables — so concurrent writes don't overwrite each other.
        """
        group = self._group
        if group is None:
            from homeassistant.exceptions import HomeAssistantError
            raise HomeAssistantError("Cannot prepare payload: group data is missing.")

        return _GroupPayload(
            {"remote_work_mode": self._merge_remote(group.remote, changes)},  # type: ignore[arg-type]
            changes,
        )

    @staticmethod
    def _merge_remote(remote: Dict[str, Any], changes: Dict[str, Any]) -> Dict[str, Any]:
        """Združi trenutno stanje remote z zahtevanimi spremembami."""
        base = {
            "work_mode": remote.get("work_mode", "IVentRecuperation1"),
            "special_mode": remote.get("special_mode", "IVentSpecialOff"),
            "remote_control_speed": remote.get("remote_control_speed", 1),
            "remote_control_work_mode": remote.get("remote_control_work_mode", "Normal"),
            "bypass_rotation": remote.get("bypass_rotation", "BypassForward"),
        }
        base.update(changes)

        speed = IVentGroupEntity._normalize_remote_control_speed(
            base.get("remote_control_speed", 1)
        )
        base["remote_control_speed"] = speed
        remote_control_work_mode = IVentGroupEntity._normalize_remote_control_work_mode(
            base.get("remote_control_work_mode")
        )
        base["remote_control_work_mode"] = remote_control_work_mode

        remote_settings_changed = (
            "remote_control_speed" in changes
            or "remote_control_work_mode" in changes
        )
        if remote_settings_changed and base.get("work_mode") != API_MODE_WORK_OFF:
            base["work_mode"] = IVentGroupEntity._work_mode_for_remote_settings(
                remote_control_work_mode, speed
            )
        return base

    @staticmethod
    def _normalize_remote_control_speed(value: Any) -> int:
        try:
            speed = int(value)
        except (TypeError, ValueError):
            return 1
        if speed < 1:
            return 1
        if speed > 3:
            return 3
        return speed

    @staticmethod
    def _normalize_remote_control_work_mode(value: Any) -> str:
        return "Bypass" if value == "Bypass" else "Normal"

    @staticmethod
    def _work_mode_for_remote_settings(remote_control_work_mode: Any, speed: int) -> str:
        mode = IVentGroupEntity._normalize_remote_control_work_mode(
            remote_control_work_mode
        )
        return _WORK_MODE_BY_REMOTE_SETTINGS[(mode, speed)]

    def _build_remote_settings_payload(
        self,
        remote_control_work_mode: str | None,
        remote_control_speed: int | None,
        *,
        keep_off: bool = False,
    ) -> Dict[str, Any]:
        """Build a synchronized remote_work_mode payload.

        The i-Vent API requires work_mode, remote_control_work_mode, and
        remote_control_speed to stay in sync when changing recuperation/bypass
        or speed. special_mode and bypass_rotation are preserved via
        _prepare_payload defaults.

        Args:
            remote_control_work_mode: Target ventilation mode (Normal/Bypass),
                or None to leave it unchanged (only with keep_off=True).
            remote_control_speed: Target fan speed (1-3), or None to leave it
                unchanged (only with keep_off=True).
            keep_off: When True, work_mode is derived from the merged state of
                each group and an OFF group stays OFF. Fields passed as None
                are not touched, which matters when the command is fanned out
                from the "all devices" group to groups in different states.
        """
        changes: Dict[str, Any] = {}
        if remote_control_work_mode is not None:
            changes["remote_control_work_mode"] = (
                self._normalize_remote_control_work_mode(remote_control_work_mode)
            )
        if remote_control_speed is not None:
            changes["remote_control_speed"] = self._normalize_remote_control_speed(
                remote_control_speed
            )
        if not keep_off:
            group = self._group
            vent_mode = changes.get(
                "remote_control_work_mode",
                group.remote_control_work_mode if group else "Normal",
            )
            speed = changes.get(
                "remote_control_speed",
                group.remote_control_speed if group else 1,
            )
            changes["work_mode"] = self._work_mode_for_remote_settings(
                self._normalize_remote_control_work_mode(vent_mode),
                self._normalize_remote_control_speed(speed),
            )
        return self._prepare_payload(changes)

    async def async_update_group(self, payload: Dict[str, Any]) -> None:
        """Spremeni podatke skupine preko API in osveži koordinatorja.

        Za rezervirano skupino "vse naprave" (id 1) oblak ukaza ne razširi
        na ostale skupine, zato ga tu ponovimo na vsaki skupini z napravami.
        """
        targets = self._fan_out_targets(payload)
        if targets is None:
            await self.coordinator.client.async_modify_group(self._group_id, payload)
            self._apply_successful_group_write(payload)
        else:
            await self._async_fan_out_group_write(payload, targets)
        await self.coordinator.async_request_delayed_refresh()

    def _fan_out_targets(self, payload: Dict[str, Any]) -> list[int] | None:
        """Vrne ID-je skupin za razširitev ali None, če razširitev ni potrebna."""
        if self._group_id != ALL_GROUPS_ID or self.coordinator.data is None:
            return None
        if not payload or not set(payload) <= _FAN_OUT_KEYS:
            return None
        targets = [
            gid
            for gid, group in self.coordinator.data.groups_by_id.items()
            if gid != ALL_GROUPS_ID and group.device_macs
        ]
        return targets or None

    async def _async_fan_out_group_write(
        self, payload: Dict[str, Any], targets: list[int]
    ) -> None:
        """Pošlje isti ukaz vsaki ciljni skupini (vsaka z lastnim remote stanjem).

        Skupina "vse naprave" sama je zapis best-effort: uradna aplikacija
        nanjo ne piše, vendar tako ostane prikaz njenih entitet usklajen.
        """
        data = self.coordinator.data
        assert data is not None
        changes = getattr(payload, "changes", None)

        writes: list[tuple[int, Dict[str, Any]]] = []
        for gid in [*targets, ALL_GROUPS_ID]:
            group = data.groups_by_id.get(gid)
            if (
                changes is not None
                and "remote_work_mode" in payload
                and group is not None
            ):
                target_payload = dict(payload)
                target_payload["remote_work_mode"] = self._merge_remote(
                    group.remote, changes  # type: ignore[arg-type]
                )
            else:
                target_payload = dict(payload)
            writes.append((gid, target_payload))

        results = await asyncio.gather(
            *(
                self.coordinator.client.async_modify_group(gid, body)
                for gid, body in writes
            ),
            return_exceptions=True,
        )

        errors: list[Exception] = []
        for (gid, body), result in zip(writes, results):
            if isinstance(result, Exception):
                _LOGGER.warning("Fan-out write to group %s failed: %s", gid, result)
                if gid != ALL_GROUPS_ID:
                    errors.append(result)
                continue
            self._apply_group_write(gid, body)
        self.coordinator.async_set_updated_data(data)

        if errors:
            raise errors[0]

    def _apply_successful_group_write(self, payload: Dict[str, Any]) -> None:
        if self._apply_group_write(self._group_id, payload) and self.coordinator.data:
            self.coordinator.async_set_updated_data(self.coordinator.data)

    def _apply_group_write(self, group_id: int, payload: Dict[str, Any]) -> bool:
        """Optimistično vnese uspešen zapis v podatke koordinatorja."""
        remote_payload = payload.get("remote_work_mode")
        if not isinstance(remote_payload, dict) or self.coordinator.data is None:
            return False
        group = self.coordinator.data.groups_by_id.get(group_id)
        if group is None:
            return False
        remote: Dict[str, Any] = group.raw.setdefault("remote", {})  # type: ignore[assignment,typeddict-item]
        remote.update(copy.deepcopy(remote_payload))
        return True

    def _refresh_device_info(self) -> None:
        group = self._group
        if group and self._attr_device_info:
            self._attr_device_info["name"] = group.name


class IVentDeviceEntity(IVentBaseEntity):
    """Osnovni razred za entitete, ki so vezane na fizično napravo (device).

    Identifiers use the device's MAC address — a hardware constant that
    never changes regardless of device renames or group moves.
    """

    _device_mac: str

    def __init__(
        self,
        coordinator: IVentCoordinator,
        device_data: IVentDeviceData,
    ) -> None:
        """Inicializira entiteto naprave."""
        super().__init__(coordinator)
        self._device_mac = device_data.mac_address

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
            name=device_data.device_name,
            manufacturer="i-Vent",
            model="Smart Ventilator",
            sw_version=device_data.firmware_version or None,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    # ------------------------------------------------------------------
    # Single property: always fresh from coordinator.data (no local copy)
    # ------------------------------------------------------------------

    @property
    def _device(self) -> IVentDeviceData | None:
        """Return the current device data from coordinator (O(1) dict lookup)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices_by_mac.get(self._device_mac)  # type: ignore[no-any-return]

    @property
    def available(self) -> bool:
        """Vrne True samo, če je bil zadnji API klic uspešen in naprava obstaja."""
        return self.coordinator.last_update_success and self._device is not None

    async def async_update_device(self, payload: Dict[str, Any]) -> None:
        """Spremeni podatke naprave preko API in osveži koordinatorja."""
        await self.coordinator.client.async_modify_device(self._device_mac, payload)
        await self.coordinator.async_request_delayed_refresh()

    def _refresh_device_info(self) -> None:
        device = self._device
        if device and self._attr_device_info:
            self._attr_device_info["name"] = device.device_name
            if device.firmware_version:
                self._attr_device_info["sw_version"] = device.firmware_version


class IVentScheduleEntity(IVentBaseEntity):
    """Osnovni razred za entitete, ki so vezane na urnik."""

    _schedule_id: int

    def __init__(
        self,
        coordinator: IVentCoordinator,
        schedule_data: IVentScheduleItem,
    ) -> None:
        """Inicializira entiteto urnika."""
        super().__init__(coordinator)
        self._schedule_id = schedule_data["meta"]["schedule_id"]
        # Urniki so vezani na glavno i-Vent lokacijo (service)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )

    @property
    def _schedule(self) -> IVentScheduleItem | None:
        """Return the current schedule from coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.schedules_by_id.get(self._schedule_id)  # type: ignore[no-any-return]

    @property
    def available(self) -> bool:
        """Vrne True samo, če urnik obstaja."""
        return self.coordinator.last_update_success and self._schedule is not None

    async def async_update_schedule_enabled(self, enabled: bool) -> None:
        """Posodobi stanje urnika (omogočeno/onemogočeno) preko API."""
        if self.coordinator.data is None:
            return
        current_schedules = copy.deepcopy(self.coordinator.data.raw_schedules)
        for schedule_group in current_schedules:
            for schedule in schedule_group.get("schedules", []):
                if schedule.get("meta", {}).get("schedule_id") == self._schedule_id:
                    schedule["header"]["schedule_item_enabled"] = enabled
                    await self.coordinator.client.async_modify_schedules(current_schedules)
                    await self.coordinator.async_request_delayed_refresh()
                    return

    def _update_state(self) -> None:
        """Override in subclasses to react to coordinator data changes."""
