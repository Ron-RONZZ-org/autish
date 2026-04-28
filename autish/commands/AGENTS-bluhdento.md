# AGENTS-bluhdento.md — bluetooth Command Agent Instructions

## Summary
Bluetooth device management via BlueZ (`bluetoothctl`).

## Purpose and Expected Behavior
- List paired Bluetooth devices, with connected devices first.
- Connect to a paired device by MAC address (`konekti`).
- Disconnect a device or all devices (`malkonekti`).
- Auto-detect adapter power state; attempt `rfkill unblock bluetooth` if needed.

## Constraints and Invariants
- Depends on `bluetoothctl` (BlueZ); Debian/Ubuntu default.
- All subprocess calls wrapped via `_run()` and `_bluetoothctl()` helpers.
- Adapter power state checked via `_bluetooth_powered()`; best-effort unblock via `_try_unblock_bluetooth()`.
- No persistent state; read-only queries and connection management.

## Input/Output Expectations
- Subcommands: `ls`, `konekti`, `malkonekti`
- CLI Options:
  - `ls`: `[mac]` (optional MAC address filter)
  - `konekti`: `<mac>` (device MAC, required)
  - `malkonekti`: `[mac]` (optional; disconnects all if omitted)
- Output: Device lists with connection status, MAC addresses
- Side Effects: Bluetooth connection state changes

## Documentation Reference
- `docs/man/bluhdento.md`

## Domain-Specific Rules for Agents
- Always use `_bluetoothctl()` wrapper for bluetoothctl calls.
- MAC address format validation: 6 octets (XX:XX:XX:XX:XX:XX).
- `_bluetooth_powered()` parses `bluetoothctl show` output for "Powered:" line.
- Connection attempts include retry/delay logic; preserve existing timeout patterns.
- Do not add GUI/TUI components; keep CLI-only per global rules.
