COPILOT CLI
# Bug fixes

- The automatic reverse links are still showing up in user-facing `encik modifi`, risking potential conflictual manual overwrite.
  - Fix it !
- enforce logical error gate
  - if A hasInstance B, B cannot hasInstance A, etc.
  - in brief, if there are semantic logical conflicts, a clear error should be shown alongside correction suggestions.
