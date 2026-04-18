COPILOT CLI

# feature enhancement

- unify option alias
  - `-L` for `--ligilo`, `-l` for `--lingvo` and `-lo` for `--limo`
    - everywhere in autish
    - Update `copilot-instructions.md` and your memory to save this behaviour as default in this repo
- add `-l/--lingvo {comma-separated LANGCODEs}` option in `encik serci ` to display results in the specified language(s) if possible, in order of preference of specification
- `vorto` interactive mode
  - add markdown parsing for rich text display
  - `vidi` display should imitate CLI output
    - ligilo displayed by default in human readable format

# feature enhancement

## `vorto serci`

- options `-k/--kopii` and `-sk/--semantika-kopii` like in `encik serci`
  - currently, after user selection in case of multiple results, the copied entry is not displayed, but it should be, just like in `encik`.

## `vorto vidi -H/--html` 
  - add the open in html option similar to `encik vidi`
  - which should be the same module used to open a `ligilo` clicked on in `vorto vidi` command return
  - `ligiloj`: `'8cf59aaf-5e95-405a-93ec-eb82a586ee59'` > `s'ingérer`
    - the content displayed in html should all be human readable and well formatted, `just like in classic `vorto vidi`
         - if `-a` not passed, do not show creation or modification time

## `vorto` interactive mode

- should be updated to include the newer functions that are implemented in CLI but not yet TUI
  - modifi: 
    - new fields such as `autoro`, `verko`, and `uzo`
    - markdown/semantic links parsing
