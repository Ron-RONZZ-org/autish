- `serci`
  - fuzzy match enhancement: ignore spaces, punctuations etc. in match strategy
  - e.g, `AI,` as search term should match for `AI` without problem and vice versa

- `man`
  - `man` > `doc`
    - `man` is a common linux system command. Should not overwrite.
  - `vidi`
    - new options
      - `--html/-h`: open in default browser
      - `--markmap/-mm`: open as [markmap](https://markmap.js.org/docs/packages--markmap-autoloader)
    - change default: open in `less` pager
  - entry title shown in linked `encik` file should be href opening in default browser

- `encik|man vidi --html`
  - should add code syntax highlighting

- `rubo`
  - `ls` saying `rikirejon estas malplena.` while there are many files in system `trash:///`
    - `rubo` should use system recycle bin
  - converge lines of `forigi` and `rm` in `rubo -h` into one line. `forigi|rm ...`
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo: `-h` > `command | alias explanation`

- `disko` bug

```
rongzhou@libres:~/kodo/autish/dev-logs$ disko ls
┏━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━┳━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Nomo   ┃ Tipo     ┃ Loko      ┃ Grandeco ┃   Spaco ┃ Dosiersistemo ┃ RM ┃ RO ┃ Modelo                 ┃
┡━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━╇━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ sda    │ disko    │           │  238.5GB │         │               │ 0  │ 0  │ Micron 1100 SATA 256GB │
│   sda1 │ subdisko │ /boot/efi │  512.0MB │ 504.8MB │ vfat          │ 0  │ 0  │                        │
│   sda2 │ subdisko │ /         │  238.0GB │ 174.1GB │ ext4          │ 0  │ 0  │                        │
└────────┴──────────┴───────────┴──────────┴─────────┴───────────────┴────┴────┴────────────────────────┘
rongzhou@libres:~/kodo/autish/dev-logs$ disko sano sda1
Kontrolante sanon de /dev/sda1...

[sudo] pasvorto por rongzhou:          
Eraro: Nescio dum legado de SMART-informoj.

rongzhou@libres:~/kodo/autish/dev-logs$ disko sano sda
Kontrolante sanon de /dev/sda...

Eraro: Nescio dum legado de SMART-informoj.

rongzhou@libres:~/kodo/autish/dev-logs$ disko sano sda2
Kontrolante sanon de /dev/sda2...

Eraro: Nescio dum legado de SMART-informoj.
```
