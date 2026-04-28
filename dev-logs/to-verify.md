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

- `rubo`
  - converge `forigi` and `rm` in `rubo -h` into one line. `forigi|rm ...`
    - currently still 2 lines
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo: `-h` > `command | alias explanation`

- `encik|vorto|doc|kontakto serci`
  - ensure the search function is centralised as much as possible
  - fuzzy match enhancement in all search functions: ignore spaces, punctuations etc. in match strategy
  - e.g, `AI,` as search term should match for `AI` without problem and vice versa
    - currently `AI,` not matching for `AI` in `encik`
- `encik|vorto|doc|md vidi --html`
  - ensure everyone is using common helper function
- `doc vidi --markmap`
  - install markmap render dependencies locally for offline availability
- `sistemo install`
  - is using [y|N] confirmation
    - should be `j|N` for eo locale
  - still installing `man` instead of `doc` ?
```
rongzhou@libres:~/kodo/autish$ doc -h
Command 'doc' not found, but there are 16 similar ones.
rongzhou@libres:~/kodo/autish$ man -h
Usage: autish [OPTIONS] COMMAND [ARGS]...
Try 'autish -h' for help.
╭─ Error ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ No such command 'man'.
```

# Bug fixes

- critical: `encik aldoni` performance issue
  - this command now takes ~10s on average to run, which is completely inacceptable
  - must drastically improve performance !

- `encik -L` HTML relation graph rendering
  - all options are rendered as light grey text over white bg.
  - should be white text over dark page bg for lisibility
- persistant eo locale issue: [y/N] should be [j/N] !
