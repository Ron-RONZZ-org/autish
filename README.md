# autish

Cross-platform CLI software for essential tasks with minimum stimulation. Designed with neurodiversity in mind.

> compatibility note: as of now, Autish only works on Debian-based Linux. This project started with personal needs as a neurodiverse user. I use Linux Mint Cinnamon 22.1 personally, as I found the UI simple, soothing, and predictable. You should try it out. Autish may work on other linux distros. You need to test for yourself. If you are on Windows or Mac, you are out of luck.
---

## Goals

- **Minimum stimulation** — calm, predictable output with no unnecessary noise
- **Sensible defaults** — works well out of the box without memorising options
- **Neurodiversity-first** — clear, minimalist syntax; Esperanto keywords so non-English speakers can participate equally
- **Offline-first** — core functionality works without internet access
- **Scope** — v0.0.2 targets Debian-based Linux

---

## Commands (v0.0.2)

All keywords are in **Esperanto** to lower the barrier for non-English speakers.

| Command | Description |
|---|---|
| `autish tempo` | Current local time (ISO) and day of week |
| `autish tempo --horzono 9` | Show time for UTC+9 |
| `autish wifi ls` | List saved Wi-Fi connections |
| `autish wifi konekti "SSID" -p "password"` | Connect to Wi-Fi |
| `autish wifi forigi "SSID"` | Delete a saved Wi-Fi profile |
| `autish bluhdento ls` | List paired Bluetooth devices |
| `autish bluhdento konekti AA:BB:CC:DD:EE:FF` | Connect to Bluetooth device |
| `autish bluhdento malkonekti` | Disconnect Bluetooth |
| `autish sistemo` | System info (CPU, memory, disk, battery, network) |
| `autish sistemo install` | Install autish globally (add to PATH) |
| `autish kp [command]` | Run command and copy output to clipboard |
| `autish kp` | Copy last captured output again |
| `autish shelo` | Interactive shell with autish commands available |
| `autish vorto` | Personal word bank / dictionary |
| `autish vorto aldoni "word" -d "definition"` | Add word with definition |
| `autish vorto serci "keyword"` | Search word bank |
| `autish encik` | Personal encyclopedia / knowledge base |
| `autish encik aldoni "title" -d "content"` | Add encyclopedia entry |
| `autish encik serci "query"` | Search encyclopedia |
| `autish retposto` | Email client (IMAP) |
| `autish retposto ls` | List email folders |
| `autish kontakto` | Contact manager |
| `autish kontakto ls` | List contacts |
| `autish kontakto aldoni "name" -e "email"` | Add contact |
| `autish kalendaro` | Calendar / event manager |
| `autish kalendaro ls` | List events |
| `autish kalendaro aldoni "event" -d "2026-05-15"` | Add event |
| `autish todo` | Task / todo manager |
| `autish todo ls` | List tasks |
| `autish todo aldoni "task"` | Add task |
| `autish taglibro` | Notebook / journal |
| `autish taglibro ls` | List entries |
| `autish taglibro skribi "note"` | Add note |
| `autish sekurkopio` | Backup tool |
| `autish sekurkopio krei "backup_name"` | Create backup |
| `autish sekurkopio restaŭri "backup_name"` | Restore backup |
| `autish disko` | Disk usage analyzer |
| `autish usb` | USB device manager |
| `autish filmeto` | Video downloader (yt-dlp) |
| `autish filmeto elŝuti "URL"` | Download video |
| `autish etikedo` | Label / tag manager |
| `autish etikedo ls` | List labels |
| `autish md` | Markdown tools |
| `autish md vidi "file.md"` | Render Markdown to terminal |
| `autish doc` | Document viewer (PDF, DOCX, etc.) |
| `autish verki` | AI-assisted writing |
| `autish verki generi "prompt"` | Generate text with AI |
| `autish verki modelo` | List available AI models |
| `autish uzanto` | User profile management |
| `autish uzanto profilo` | Show current profile |
| `autish rubo ls` | List trash / recycle bin |
| `autish rubo vyidi` | Empty trash |

---

## Installation

> **Requirements:** Python 3.10+, Debian-based Linux (Ubuntu, Debian, Mint, …)

### Option A — Install from PyPI (recommended)

```bash
pip install --user autish
```

After installing with `--user`, the `autish` command is placed in `~/.local/bin/`. Add to PATH if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify:

```bash
autish --help
```

### Option B — Install with pipx (isolated)

```bash
pip install --user pipx
pipx ensurepath
pipx install autish
autish --help
```

### Option C — Development

```bash
git clone https://github.com/Ron-RONZZ-org/autish.git
cd autish
poetry install
poetry run autish --help
```

---

## Global Installation (for full functionality)

To use bash aliases and make `autish` available system-wide:

```bash
cd /path/to/autish
autish sistemo install           # ~/.local/bin (default)
# or
sudo autish sistemo install --sistema  # /usr/local/bin
```

---

## Documentation

Full command reference: [docs/man/INDEX.md](docs/man/INDEX.md)

Get help for any command:

```bash
autish vorto --help
autish retposto --help
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

---

## License

[GPL-3.0](LICENSE)
