# TODO — autish roadmap

## v0.0.1 — Debian-based Linux foundation

> **Goal:** a working CLI with the core commands listed below, installable via pip on Debian-based Linux.

---

### Project foundation

- [x] LICENSE
- [x] .gitignore (Python template)
- [x] README.md
- [x] CONTRIBUTING.md
- [x] TODO.md
- [x] .github/copilot-instructions.md
- [x] pyproject.toml (typer, rich, psutil dependencies; dev extras; entry point)
- [x] autish/ package skeleton (main.py + commands/)

---

### `tempo` — time command

**Syntax:** `autish tempo [-z/--horzono {number}]`

- [ ] Print current local time in **ISO 8601** format on line 1
- [ ] Print day of week in **system language** (`locale`) on line 2
- [ ] `-z`/`--horzono {number}` — accept UTC offset integer (-12 to +14)
  - [ ] If a valid number is given, display local time for that UTC offset
  - [ ] If the flag is given with no value, print time for **all** UTC offsets (-12 to +14)
  - [ ] Validate: reject offsets outside -12…+14 with a clear error message

**Decision needed:** output format for "all timezones" — table vs. plain list? *Proposal: plain list (one line per offset) to keep stimulation low.*

---

### `wifi` — Wi-Fi commands

> Uses `nmcli` (NetworkManager) under the hood (Debian/Ubuntu default).

**Subcommands:**

- [ ] `autish wifi ls`
  - [ ] List all saved + visible Wi-Fi SSIDs
  - [ ] Show currently connected network **first**
  - [ ] `autish wifi ls {wifi-name}` — show details for a specific network
    - [ ] `-p` flag — reveal the saved password (requires `sudo` or `nmcli --show-secrets`)
- [ ] `autish wifi konekti {wifi-name} [-p {password}] [-u {username}]`
  - [ ] Connect to named network; prompt for password if `-p` not given and network requires it
  - [ ] Support enterprise networks via `-u`/`--uzanto` (username)
- [ ] `autish wifi malkonekti`
  - [ ] Disconnect the active Wi-Fi connection
- [ ] `autish wifi forigi {wifi-name}`
  - [ ] Delete a saved network profile (with confirmation prompt)

**Decision needed:** how to handle multiple active connections? *Proposal: disconnect all active Wi-Fi interfaces by default.*

---

### `bluhdento` — Bluetooth commands

> Uses `bluetoothctl` (BlueZ) under the hood.

**Subcommands:**

- [ ] `autish bluhdento ls`
  - [ ] List paired Bluetooth devices
  - [ ] Show currently connected device(s) **first**
  - [ ] `autish bluhdento ls {MAC}` — show details for a device
- [ ] `autish bluhdento konekti {MAC}`
  - [ ] Connect a paired Bluetooth device by MAC address
- [ ] `autish bluhdento malkonekti [{MAC}]`
  - [ ] Disconnect a specific device, or **all** connected devices if no MAC given

**Decision needed:** device discovery / pairing flow — out of scope for v0.0.1? *Proposal: yes, defer pairing to v0.0.2; v0.0.1 only manages already-paired devices.*

---

### `sistemo` — system info

**Syntax:** `autish sistemo`

- [ ] OS name and version
- [ ] CPU model and current usage %
- [ ] RAM: total / used / free
- [ ] Storage: per-mount total / used / free
- [ ] Battery: level % and charging state (if applicable)
- [ ] Active network interface + IP address
- [ ] Bluetooth adapter state (on/off, connected devices count)

**Library:** `psutil` for CPU/RAM/storage/battery; `platform` for OS info.

---

### `kp` — clipboard copy

**Syntax:** `autish kp [{command}]`

- [ ] `autish kp {command}` — run `{command}`, print output normally, **also** copy to clipboard
- [ ] `autish kp` (no argument) — copy the output of the **last executed shell command** without re-running it
  - [ ] Implementation note: last command output is shell-dependent; investigate `$HISTFILE` + re-capture vs. shell integration approach

**Decision needed:** "last command output" capture strategy.
- Option A: Shell plugin/hook (most reliable but requires user to configure their shell)
- Option B: Store output in a temp file when `kp {command}` form is used; `kp` alone reads that file
- *Proposal: Option B for v0.0.1 — simple, no shell config needed. Option A as opt-in enhancement.*

**Library:** `pyperclip` (cross-platform clipboard; falls back gracefully when no display server is available).

---

### Inline help / incomplete command behaviour

- [ ] When a command is given without required arguments, show **usage hint inline** (not full --help dump)
- [ ] Typer's default `--help` behaviour should be preserved; inline hints are an *addition*

---

### Quality

- [ ] Tests for `tempo` command (ISO format, day-of-week locale, timezone offset validation)
- [ ] Tests for `kp` command (basic copy flow)
- [ ] CI: GitHub Actions workflow (lint + test on push/PR)
- [ ] Package published to PyPI (TestPyPI first)

---

## v0.0.2 — ideas (not committed)

- Bluetooth device discovery / pairing
- macOS support (replace `nmcli`/`bluetoothctl` with macOS equivalents)
- Shell hook for `kp` (Option A above)
- `--json` output flag for machine-readable output
- Man page generation

---

## Microapps

Interactive CLI programs that accomplish a particular task; accessible both
through the interactive UI and direct CLI subcommands.

### Productivity

#### Calendar
- [ ] view/navigate calendar months
- [ ] add/edit events

#### Todo list
- [ ] add/complete/delete tasks
- [ ] list with priority and due-date

### Communication

#### Email
- [ ] compose and send (SMTP)
- [ ] list/read inbox (IMAP)

### Learning

#### Wordbook — *Mia Vorto* (`vorto`)

- [x] Data model: UUID, teksto, lingvo, kategorio, tipo, temo, tono, nivelo, difinoj, etikedoj, ligiloj, kreita_je, modifita_je
- [x] Storage: `~/.local/share/autish/vorto.json`
- [x] Undo stack (up to 10): `~/.local/share/autish/vorto_undo.json`
- [x] Auto-detect kategorio from text (vorto / frazo / frazdaro)
- [x] Subcommand `aldoni` — add entry with all property options
- [x] Subcommand `vido` — view full entry detail
- [x] Subcommand `modifi` — modify any field; show help when no options given
- [x] Subcommand `serci` — full-text + filter search with limit/order/regex
- [x] Subcommand `forigi` — delete by UUID/prefix/text, with confirmation
- [x] Subcommand `malfari` — undo last operation (up to 10 chained)
- [x] Confirmation prompts for aldoni / modifi / forigi
- [x] Interactive mode — welcome screen + Neovim-style key navigation
- [x] Standalone `vorto` entry point in addition to `autish vorto`
- [ ] Review/recall mode (by date range, linked word, filter tag, max number)
- [ ] Field-level display filtering in `vido` (`-l/-t/--temo/...` flags)
- [ ] Link UI: navigate between related entries interactively
