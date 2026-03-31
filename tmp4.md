COPILOT CLI
# bug fixes

## retposto interactive mode

### `retposto`  email composition pane

- `ctrl+1` accepting 1st suggestion, but ctrl+2/3/4...` not accepting 2nd, 3rd, 4th ... autocompletion suggestions for From,to,cc,bcc!
 - since we already attempted multiple fixes and failed, try alternative strategy:
   - user press `ctrl+tab` to enter autocomplete suggestion selection mode, then input a number, enter to confirm

## `autish kontakto`

  - as previous requested, kontakto should support all standardized fields in `uzanto profilo`:
  ╭─ Options ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --nomo                      -N      TEXT  Set given name(s).                                                                                                          │
│ --familia-nomo              -F      TEXT  Set family name.                                                                                                            │
│ --naskig-dato               -d      TEXT  Set date of birth (YYYY-MM-DD).                                                                                             │
│ --naskig-loko                       TEXT  Set place of birth.                                                                                                         │
│ --lingvoj                   -L      TEXT  Set languages (comma-separated 2-letter codes, e.g. 'en,fr').                                                               │
│ --organizo                  -o      TEXT  Set organisation.                                                                                                           │
│ --organiza-identiga-numero          TEXT  Set organisation identifier.                                                                                                │
│ --telefonnumero                     TEXT  Repeat as numero:etikedo[:prima], e.g. 0033123456789:hejmo:prima                                                            │
│ --retposhtadreso                    TEXT  Repeat as adreso:etikedo[:prima], e.g. user@example.com:labora:prima                                                        │
│ --kampo                     -k      TEXT  Set a custom field as KEY:VALUE (repeatable).                                                                               │
in addition to the ones adapted to `kontakto` previously demanded.
- add `kontakto vidi {UUID}` and `kontakto serci` commands
  - where user can search by a combination of one or multiple fields like `nomo`, `organizo` or custom `kampo`...
    - add a fuzzy search mode since some names can be spelt multiple ways.
- Also, `kontakto` should be available as a standalone command just like others. Also update `.github/copilot-instructions.md` and your memory to reflect this default behaviour: new commands always accessible as standalone.
DEV: Ask for clarification if my instructions are unclear. Use mature modern packages with stable APIs, good resource efficiency and scalability. Correct wording/spellings to standard esperanto spellings !
 Test thoroughly, including for edge cases.
