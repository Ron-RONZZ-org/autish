# new commands

- `etikedo` manage labels for `todo` and `taglibro`
  - `etikedo aldoni TEXT`: add etikedo
   - markdown parsing
   - support to link to `encik` with `[](ec#)` and  `vorto`  with `[](vt#)`
   - automatic uuid assignment
  - `etikedo modifi {UUID} {nova-teksto}`
  - `etikedo forigi {UUID}|{teksto}`
  - `etikedo serci {teksto}`
    - `serci` fuzzy match logic and user selection similar to `encik`
  - `etikedo vidi {teksto}|{UUID}`
    - pass to `serci` automatically if no exact match
- `todo`
  - `aldoni {titolo-TEKSTO}` add todo task
    - `--priskribo/-p TEXT`
      - markdown parsing
      - support to link to `encik` with `[](ec#)` and  `vorto`  with `[](vt#)`
    - `--etikedo/-e {UUID}` : add labels
      - repeat flag for multiple (save this as default behaviour)
    - `--prioritato/-p INT`
      - recommended range (0,100), but other values accepted
      - accept also python formula for dynamic priority
        - variables: monato(30 tagoj): `M`, tago: `D`, horo: `H`, minuto `M`
        - example expressions:
          - `-p "min(20+2*D,70)"` > initial priority 20, with each day passed priority augment by 2 with cap of 70
          - `-p "30+5*(H-10)" > initial priority 30, since the 10th hour after creation priority augment by 5 every hour
  - `serci`: filter by every available field
    - priority: `--prioritato/-p MIN,MAX`
      - if single value parsed interpret as MIN
    - show everything if no argument parsed
  - `vidi {UUID}|{titolo}`
     - `serci` fuzzy match logic and user selection similar to `encik`
  - `modifi {UUID}|{titolo}`, `forigi {UUID}|{titolo}`
      - `serci` fuzzy match logic and user selection similar to `encik`
- `taglibro`: write entries based diary 
   - full markdown parsing in all TEXT fields
   - support to link to `encik` with `[](ec#)` and  `vorto`  with `[](vt#)`
  - `aldoni {titolo}`
    - `--etikedo/-e {UUID}`
    - `--priskribo/-p TEXT`
    - `--tempo/-t YYYYMMDD_HHMM`
      - by default NOW
      - partial date interpretation logic similar to in `kalendaro`
  - `modifi {UUID}`
  - `forigi {UUID}`
  - `vidi {UUID}`
  - `serci`: filter by every available field
   - fuzzy match logic and user selection similar to `encik`
- make these functions available as standalone commands

 - Markdown links in kontakto: Support [](ec#uuid) and [](vt#uuid) links in text fields
  - Requires: Parser for markdown links, UID validation across databases, display rendering
- move old `sistemo` function to `sistemo info`

# new: `sistemo bash alias`

- allowing adding autish managed bash alias
  - avoid raw `~/.bashrc` file editing
    - prevent accidental corruption
 - `aldoni alias:TEXT function:TEXT notes:TEXT`
  - Markdown style links in note: Support [](ec#uuid) to link to `encik` entries and [](vt#uuid) to link to `vorto` entries
   - each bash-alias is assigned a serial UID: 1,2,3,4...
   - which should NEVER be recycled
 - `modifi {UID}`
 - `forigi {UID}`
 - `vidi {UID}`
 - `ls`
   - show all alias in table: UID, alias, function, notes
   - if more than one full screen, show in a pager (like `less`)
   - default newest addition first
   - `--alfabeto/-al` alphabetic ranking
   - `--inversigi/-i` inverse order
 - `serci`
   - fuzzy text based match logic and user selection for `vidi` similar to `encik`

# new command: `autish man`

 - full markdown parsing in all TEXT fields
 - support to link to `encik` with `[](ec#)` and  `vorto`  with `[](vt#)`
- make this function available as standalone command
- `man` is similar to `encik`, but instead of managing `.enc` encyclopedia entries, `man` is for managing `.md` documentation
  - `man` is meant to supplement `encik`. For instance, if in `encik` there is an entry on `Poetry`, user can create one or more `man` entry linked to it
- the subcommand schema should be similar to `encik`, with adaptations to suit a `.md` file
 - `aldoni {md-file-path}`
   - `-L {encik UUID}`: specifies which `encik` concept the `md` manual is about
   - the link to the manual should also be displayed when user `vidi` the `encik` file in a new section called `manlibro(j)`
 - `modifi {UUID}`
 - `forigi {UUID}`
 - `vidi {UUID}`
    - the `encik` entry title (href) & UUID in user locale should be displayed 
 - `serci`: filter by every available field
   - fuzzy match logic and user selection similar to `encik`


- `serci`
  - fuzzy match enhancement: ignore spaces, punctuations etc. in match strategy
  - e.g, `AI,` as search term should match for `AI` without problem and vice versa

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

## bug fix

- `man`

  - rename `man` as `doc`
    - `man` is a common linux system command. having an autish command `man` causes conflict and confusion.

## enhancement

 - doc vidi --html display option
   - if no common `md` > `html` render function present, create one to be shared across `vorto,encik,doc,md`
   - add syntax highlighting for HTML output
 - doc vidi --markmap option (requires markmap integration)
   - create reusable helper function
 - Default less pager for doc vidi
