# Changelog

## 0.3.0-rc.1 (manifest: `0.3.0rc1`)

**Local control (release candidate; includes everything from beta 1).** Three selectable modes — cloud only, local only, combined — chosen when adding the integration and changeable later via *Reconfigure* (entities are not duplicated).

### Added
- **Local mode** over UDP port 1028 (Location Master): instant state via push, rare polling (120 s) as a safety net, Master auto-discovery or manual IP/MAC/location ID.
- **Combined mode**: state and commands local; cloud for schedules, new groups and as write fallback when the Master is unreachable. Optional *cloud state when Master unreachable*.
- Backend abstraction (`IVentBackend`) and standalone `ivent_local` library (codec, transport, client) with a fake-device test harness.
- Diagnostics redact the location ID and Master MAC; `tools/sanitize_capture.py` for anonymising captures.
- **Automatic Master follow**: when another unit becomes Location Master, the integration switches to it after 2 consecutive adverts (only after it answers; new IP/MAC saved in the entry; retry after 60 s if unreachable). No reconfiguration needed.
- **Connection mode** diagnostic sensor on the "i-Vent System" device (cloud only / local only / combined).
- **Buttons** (local/combined only): *Find device* (Beacon, verified on real hardware incl. the Master unit; on the Master unit itself the command is sent directly because the Master ignores a forwarded command addressed to itself) and *Reset filter alarm* (FilterCleaned, verified on real hardware).
- `docs/local-testing-checklist.md`.

### Changed
- Config entry version 4 (existing entries migrate to `mode=cloud`). **Downgrading to ≤0.2.6 is not possible without removing the entry.**
- Cloud only: location ID is now **required** (the API has no location listing). Hybrid: optional, obtained by local discovery.
- Entry titles: "i-Vent Cloud / Local / Hybrid" (the location ID is no longer in the title).
- `iot_class` is now `local_push` (cloud-only mode still polls every 60 s).
- Uses `via_device_id` and `OptionsFlowWithReload` on current Home Assistant (no deprecation warnings on 2026.x).

### Quality
- `ConfigEntry.runtime_data` instead of `hass.data`; `icons.json`; translated exceptions; diagnostic sensors (RSSI, timestamps) disabled by default for new installs; strict mypy clean; removal instructions in README; test coverage 96 %.

### Devices
- Groups, devices and schedules that the server no longer reports stay in Home Assistant as unavailable and can be deleted by hand from the device page (active ones cannot be deleted).
- Optional setting *Automatically remove …* (off by default, all modes): removes them after 3 consecutive successful updates without them. An empty response or a failed update never removes anything. Removal also deletes their entities, so a group that returns gets new entities.
- Switching to local-only mode leaves the (unavailable) schedule switches until deleted by hand or auto-removal is on.

### Fixed
- Group "iVent" (all devices) works in local mode (verified on a real installation): the command is repeated on every group with devices.
- (from 0.2.6) Group "iVent" (id 1, all devices) now repeats the command on every group with devices.

### Known limitations
- Cloud only: changes made in the official app appear in HA after up to ~60 s (polling, interval not configurable).
- Local: no schedules, no group creation; deleting a group and moving a device between groups are untested; one local location per Home Assistant.
