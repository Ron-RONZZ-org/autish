# AGENTS-usb.md — usb Command Agent Instructions

## Summary
USB device listing and bind/unbind controls via sysfs.

## Purpose and Expected Behavior
- List USB devices: `ls` (compact or detailed via `-a`).
- Bind USB device: `konekti <device>` (reattach driver via sysfs).
- Unbind USB device: `malkonekti <device>` (detach driver via sysfs).
- Device format: Bus:Device numbers (e.g., `001:002`).

## Constraints and Invariants
- Uses `lsusb` for device listing (usbutils package).
- Bind/unbind via sysfs: `/sys/bus/usb/drivers/.../bind` and `unbind`.
- Device resolution: parse `lsusb` output or accept `BUS:DEV` format directly.
- No persistent state; read-only queries and driver bind/unbind operations.
- Output via `echo_padded()` from `autish.utils`.

## Input/Output Expectations
- Subcommands: `ls`, `konekti`, `malkonekti`
- CLI Options:
  - `ls`: `-a`/`--auxa` (detailed output with driver info)
  - `konekti`: `<device>` (BUS:DEV format, required)
  - `malkonekti`: `<device>` (BUS:DEV format, required)
- Output: Device lists with bus, device, manufacturer, driver info
- Side Effects: USB driver bind/unbind (requires privileges)

## Documentation Reference
- `docs/man/usb.md`

## Domain-Specific Rules for Agents
- Always use `_run()` wrapper for `lsusb` calls; handle `FileNotFoundError`.
- Device token parsing: accept `BUS:DEV` format; validate with `_resolve_device_token()`.
- Sysfs path resolution: use `_sysfs_device_path()` to find device in `/sys/bus/usb/devices/`.
- Bind/unbind: write device ID (e.g., `1-2`) to sysfs bind/unbind files.
- Privilege errors: catch `PermissionError`; suggest sudo if needed.
- Do not add GUI/TUI components; keep CLI-only per global rules.
- Driver detection: parse `/sys/bus/usb/devices/.../driver` symlink.
