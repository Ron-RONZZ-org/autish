COPILOT CLI
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
