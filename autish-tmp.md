À TESTER
# Feature improvements

## register direct commands

- e.g., `retposto` works as `autish retposto` once autish installed
- `bluhdento` as `autish bluhdento`
- ...

## portability

- vorto: add `vorto importi/eksporti` CLI commands to import/export all entries as one file for backup/transfer
  - eksporti
    - non-sensitive data, so optional password encryption `--pasvorto /-p {password}` 
  - importi
    - `--pasvorto/-p` to give password, if not specified but encrypted export ask interactively
- retposto: add `retposto importi/eksporti` CLI commands to import/export all email configs as one `toml`file for portability
  - eksporti
    - since password is sensitive data, requires password encryption `--pasvorto /-p {password}`, if not specifed ask interactively
    - enforce strong password policy (8 char, minimum 1 upper case letter, 1 lower case letter and 1 number)
  - importi
    - `--pasvorto/-p` to give password, if not specified but encrypted export ask interactively

## data security & backup : `autish sekurkopio`

- `eksporti {path/url}`: export all `autish` user data as a `.7z` (default) or `zip file` `--formato/-f zip`
  - since password is sensitive data, requires password encryption `--pasvorto /-p {password}`, if not specifed ask interactively
  - enforce strong password policy (8 char, minimum 1 upper case letter, 1 lower case letter and 1 number)
- `importi {path/url}`: restore user data from exports
  - `--pasvorto/-p` to give password, if not specified but encrypted export ask interactively
  - `--anstatauigi/-A` overwrite existing, default is add to existing
    - special caution: ask user to type the word `anstataŭigi` to confirm
      - accept `anstatauigi` without accent
- `auto {path}`: automatically backup all user data to an encrypted `.aut` file
  - `--intervalo/-i {minutes}` default 60
  - create folder if not existing
  - `--nombro/-n {max number of copies}: keep at most latest n copies
  - display backup strategy summaries for J/n confirmation
  - if user calls simply `auto`
    - existing backup strategy: show summary
    - if `--nombro/-n` or `--intervalo/-i` passed, J/n modification confirmation
    - if no backup strategy, asks whether user would like to create on interactively (J/n)
- safe guarding
  - ask for user confirmation (j/N) before any irreversible/hardly reversible changes
  - `historio`: save a record of last 5 changes
    -  without argument: show a summary of last 5 changes
    - `malfari {number of operations}` to undo last changes
        - my proposed method : copy on write, i.e. create a copy before irreversible/hardly reversible changes
        - more efficient ideas ?
        - again user (j/N) confirmation, with changes to be undone summarised


