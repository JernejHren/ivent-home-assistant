"""Koordinator podatkov za i-Vent integracijo."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    IVentApiClient,
    IVentApiAuthError,
    IVentApiConnectionError,
    IVentApiClientError,
    IVentGroup,
    IVentDevice,
    IVentScheduleGroup,
    IVentRemote,
    IVentScheduleItem,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)


# ---------------------------------------------------------------------------
# Normalized internal data model
# ---------------------------------------------------------------------------

@dataclass
class IVentGroupData:
    """Normalized group data used by all group-based entities."""

    raw: IVentGroup

    # --- convenience accessors (no dict drilling in entities) ---
    @property
    def id(self) -> int:
        return self.raw["id"]

    @property
    def name(self) -> str:
        return self.raw["name"]

    @property
    def led_work_mode(self) -> str:
        return self.raw["led_work_mode"]

    @property
    def buzzer_work_mode(self) -> str:
        return self.raw["buzzer_work_mode"]

    @property
    def remote(self) -> IVentRemote:
        return self.raw.get("remote") or {
            "work_mode": "",
            "special_mode": "",
            "remote_control_speed": 1,
            "remote_control_work_mode": "Normal",
            "bypass_rotation": "BypassForward",
            "work_mode_changed_at": 0,
            "special_mode_ends_at": 0,
        }

    @property
    def work_mode(self) -> str:
        return self.remote.get("work_mode", "")

    @property
    def special_mode(self) -> str:
        return self.remote.get("special_mode", "")

    @property
    def remote_control_speed(self) -> int:
        return self.remote.get("remote_control_speed", 1)

    @property
    def remote_control_work_mode(self) -> str:
        return self.remote.get("remote_control_work_mode", "Normal")

    @property
    def bypass_rotation(self) -> str:
        return self.remote.get("bypass_rotation", "BypassForward")

    @property
    def work_mode_changed_at(self) -> datetime | None:
        ts = self.remote.get("work_mode_changed_at")
        if not ts or ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def special_mode_ends_at(self) -> datetime | None:
        ts = self.remote.get("special_mode_ends_at")
        if not ts or ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @property
    def device_macs(self) -> List[str]:
        return [d["mac_address"] for d in self.raw.get("devices", [])]


@dataclass
class IVentDeviceData:
    """Normalized device (physical unit) data."""

    raw: IVentDevice

    @property
    def mac_address(self) -> str:
        return self.raw["mac_address"]

    @property
    def device_name(self) -> str:
        return self.raw["device_name"]

    @property
    def rssi(self) -> int:
        return self.raw.get("rssi", 0)

    @property
    def firmware_version(self) -> str:
        firmware_version = self.raw.get("firmware_version", "")
        if firmware_version is None:
            return ""
        return str(firmware_version)

    @property
    def alive(self) -> bool:
        return self.raw.get("alive", False)

    @property
    def status_esp(self) -> int:
        return self.raw.get("status_esp", 0)

    @property
    def diagnostic_flags(self) -> int | None:
        return self.raw.get("diagnostic_flags")

    @property
    def reverse_flow(self) -> bool:
        return self.raw.get("reverse_flow", False)

    # Which group this device currently belongs to (set during normalization)
    group_id: int = 0


@dataclass
class IVentData:
    """
    Single normalized data model that is stored in coordinator.data.

    Example structure:
    {
      groups_by_id: {
        42: IVentGroupData(raw={id: 42, name: "Living room", ...}),
        43: IVentGroupData(raw={id: 43, name: "Bedroom", ...}),
      },
      devices_by_mac: {
        "AA:BB:CC:DD:EE:FF": IVentDeviceData(raw={...}, group_id=42),
      },
      schedules_by_id: {
        1: {"meta": {...}, "repeat": {...}, "header": {...}},
      },
      # Raw lists preserved for iteration / stale-device cleanup
      group_ids: [42, 43],
      all_device_macs: ["AA:BB:CC:DD:EE:FF"],
      raw_schedules: [{"name": "Default", "schedules": [...]}],
    }
    """

    # O(1) entity lookups
    groups_by_id: Dict[int, IVentGroupData] = field(default_factory=dict)
    devices_by_mac: Dict[str, IVentDeviceData] = field(default_factory=dict)
    schedules_by_id: Dict[int, IVentScheduleItem] = field(default_factory=dict)

    # Ordered lists for iteration (entity discovery, stale-device cleanup)
    group_ids: List[int] = field(default_factory=list)
    all_device_macs: List[str] = field(default_factory=list)
    raw_schedules: List[IVentScheduleGroup] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class IVentCoordinator(DataUpdateCoordinator[IVentData]):
    """Manages a single periodic fetch and exposes normalized IVentData."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: IVentApiClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"ivent_{entry.entry_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.config_entry = entry
        self._pending_refresh_task: asyncio.Task | None = None

    async def async_request_delayed_refresh(self, delay: float = 2.0) -> None:
        """Zahteva osvežitev podatkov s kratkim zamikom.

        Uporabno po zapisovanju na API, ki potrebuje čas za osvežitev
        notranjega stanja (read-after-write consistency issue).
        """

        if self._pending_refresh_task:
            self._pending_refresh_task.cancel()

        async def _delayed_refresh() -> None:
            try:
                await asyncio.sleep(delay)
                await self.async_request_refresh()
            except asyncio.CancelledError:
                # Expected when a newer write schedules another delayed refresh.
                return

        self._pending_refresh_task = self.hass.async_create_task(_delayed_refresh())

    # ------------------------------------------------------------------
    # Single update method — ONE place that calls the API
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> IVentData:
        """
        Fetch all data in one coordinator update cycle.

        Strategy:
          - info (groups + devices) is CRITICAL — failure raises UpdateFailed,
            which marks all entities unavailable.
          - schedules are NON-CRITICAL — on failure we preserve the last known
            value so schedule switches stay functional.
        """
        # ---------- info (critical) ----------
        try:
            info = await self.client.async_get_info()
        except IVentApiAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication error fetching info: {err}"
            ) from err
        except IVentApiConnectionError as err:
            raise UpdateFailed(
                f"Connection error fetching info: {err}"
            ) from err
        except IVentApiClientError as err:
            raise UpdateFailed(f"API error fetching info: {err}") from err

        # ---------- schedules (non-critical) ----------
        raw_schedules: List[IVentScheduleGroup]
        try:
            raw_schedules = await self.client.async_get_schedules()
        except IVentApiAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication error fetching schedules: {err}"
            ) from err
        except IVentApiClientError as err:
            # We explicitly swallow network and API errors (including IVentApiConnectionError)
            # here because schedules are considered a non-critical feature.
            # Failing the entire coordinator update would incorrectly mark all primary
            # ventilation devices as unavailable just because the schedule API endpoint failed.
            _LOGGER.warning(
                "Failed to fetch schedules, preserving last known value: %s", err
            )
            # Preserve previous schedules so no schedule entity breaks
            raw_schedules = (
                self.data.raw_schedules if self.data is not None else []
            )

        return _normalize(info.get("groups", []), raw_schedules)


# ---------------------------------------------------------------------------
# Normalization helper — pure function, easy to unit-test
# ---------------------------------------------------------------------------

def _normalize(
    raw_groups: List[IVentGroup],
    raw_schedules: List[IVentScheduleGroup],
) -> IVentData:
    """
    Convert raw API lists into the indexed IVentData model.

    All entity-level coordinator updates simply do:
        group = coordinator.data.groups_by_id.get(self._group_id)
    instead of nested loops.
    """
    groups_by_id: Dict[int, IVentGroupData] = {}
    devices_by_mac: Dict[str, IVentDeviceData] = {}
    group_ids: List[int] = []
    all_device_macs: List[str] = []

    for raw_group in raw_groups:
        gid = raw_group.get("id")
        if gid is None:
            _LOGGER.warning("Skipping group with missing id: %s", raw_group)
            continue

        group_data = IVentGroupData(raw=raw_group)
        groups_by_id[gid] = group_data
        group_ids.append(gid)

        for raw_device in raw_group.get("devices", []):
            mac = raw_device.get("mac_address")
            if not mac:
                _LOGGER.warning("Skipping device with missing mac in group %s", gid)
                continue
            device_data = IVentDeviceData(raw=raw_device, group_id=gid)
            devices_by_mac[mac] = device_data
            all_device_macs.append(mac)

    # Index schedules for O(1) lookup
    schedules_by_id: Dict[int, IVentScheduleItem] = {}
    for schedule_group in raw_schedules:
        for schedule in schedule_group.get("schedules", []):
            sid = schedule.get("meta", {}).get("schedule_id")
            if sid is not None:
                schedules_by_id[sid] = schedule

    return IVentData(
        groups_by_id=groups_by_id,
        devices_by_mac=devices_by_mac,
        schedules_by_id=schedules_by_id,
        group_ids=group_ids,
        all_device_macs=all_device_macs,
        raw_schedules=raw_schedules,
    )
