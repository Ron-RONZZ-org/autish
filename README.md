# autish

Cross-platform CLI software for essential tasks with minimum stimulation. Designed with neurodiversity in mind.

---

## Goals

- **Minimum stimulation** — calm, predictable output with no unnecessary noise
- **Sensible defaults** — works well out of the box without memorising options
- **Neurodiversity-first** — clear, minimalist syntax; Esperanto keywords so non-English speakers can participate equally
- **Offline-first** — core functionality works without internet access
- **Humble scope** — v0.0.1 targets Debian-based Linux

---

## Commands (v0.0.1)

All keywords are in **Esperanto** to lower the barrier for non-English speakers.

| Command | Description |
|---|---|
| `autish tempo` | Print current local time (ISO) and day of week |
| `autish wifi ls` | List Wi-Fi connections |
| `autish wifi konekti` | Connect to a Wi-Fi network |
| `autish wifi malkonekti` | Disconnect from Wi-Fi |
| `autish wifi forigi` | Delete a saved Wi-Fi profile |
| `autish bluhdento ls` | List Bluetooth devices |
| `autish bluhdento konekti` | Connect a Bluetooth device |
| `autish bluhdento malkonekti` | Disconnect a Bluetooth device |
| `autish sistemo` | Print system information |
| `autish kp` | Copy last command output to clipboard |

---

## Installation

> Requires Python 3.10+ and a Debian-based Linux distribution.

```bash
pip install autish
```

Or, for development:

```bash
git clone https://github.com/Ron-RONZZ-org/autish.git
cd autish
pip install -e ".[dev]"
```

---

## Quick Start

```bash
# Show current time and day
autish tempo

# Show time for UTC+9
autish tempo --horzono 9

# List all timezones
autish tempo --horzono

# List Wi-Fi connections
autish wifi ls

# Connect to a network
autish wifi konekti "MyNetwork" -p "mypassword"

# Show system info
autish sistemo

# Copy last command output to clipboard
autish kp
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for style guide and development instructions.

---

## Roadmap

See [TODO.md](TODO.md) for the detailed implementation plan and roadmap.

---

## License

[GPL-3.0](LICENSE)
