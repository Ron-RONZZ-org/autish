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

# feature enhancements

# bug fixes

## code quality issue: potential code duplication

- multiple autish commands involve markdown parsing, sqlite db management and user edition interface
  - fix potential code duplication !

## aliases

- short aliases of 1-3 letters for options is extremely important for user comfort
- add them where missing
  - e.g., `sistemo bash alias`
- Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo

- (autish-py3.12) rongzhou@libres:~/kodo/autish/AI-kuntekstoj$ sistemo bash aldoni --alias ess --function "encik serci -sk" --notes "encik"
[!] Alias 'ess' jam ekzistas
  - which is not true ! fix it.

# bug fixes

## `sistemo bash`

- (critical) bash alias do not work for `autish` commands in poetry virtual environment: must FIX !
- should be renamed `sistemo bash-alias` for clarity
- `forigi` need to take multiple UIDs

# bug fixes

1. bash alias still not working
```
(autish-py3.12) rongzhou@libres:~/kodo/autish/AI-kuntekstoj$ sistemo bash-alias ls
                             Bash-alias-oj                              
┏━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ UID ┃ Alias ┃ Funkcio (unuaj 50 ĉaroj) ┃ Notoj (unuaj 40 ĉaroj)      ┃
┡━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 8   │ ess   │ autish encik serci -sk   │ Encik search

(autish-py3.12) rongzhou@libres:~/kodo/autish$ sistemo install
[i] autish jam instalita ĉe /home/rongzhou/.local/bin/autish
(autish-py3.12) rongzhou@libres:~/kodo/autish$ ess
La commande « ess » n'a pas été trouvée, voulez-vous dire :
```

2. `disko sano` not working
```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ autish disko sano sda
Kontrolante sanon de /dev/sda...
(Bezonas sudo rajtojn)

Eraro: Ne povis legi SMART informojn.
```

# feature enhancements

- add commands to disko to manage partitions: shrink partition, create new, format
  - change summary and `j/N`confirmation for all system modifications
  - throw error on bad usage: e.g., formatting disk where the current OS is installed

# new: utility functions to enhance Linux system experience

## `rubo` working with system recycle bin

- `rubo forigi {path}*`
  - move specified files to recycle bin
  - alias: `rubo rm`
- `rubo ls`
  - list recycle bin contents
- `rubo serci {keyword}`
  - search in recycle bin
    - wildcard `*` support
  - `-R/--regex`: basic POSIX regex support
- `rubo restarigi {path}*`
  - restore files from recycle bin
  - alias: `rubo rs`

# Bug fixes

- commands should follow autish naming conventions: STRICT ESPERANTO KEYWORDs !
  - `disko shrink`> `disko srumpi`
  - `disko format`> `disko formati`
  - save old commands as alias for compatibility

# enhancements

- `serci`
  - should be centralised to a common helper function
  - fuzzy match enhancement: ignore spaces, punctuations etc. in match strategy
- system wide alias
   - add alias for all autish commands to `~/.autish_aliases`
     - filmeto="autish filmeto", etc.
