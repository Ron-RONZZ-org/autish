# vorto(1)

## NAME

vorto - Mia Vorto — persona vortaro-mikroapo.

## SYNOPSIS

```
autish vorto [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Mia Vorto — persona vortaro-mikroapo.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `aldoni    Add a new word, phrase, or sentence to the wordbank.`
- `vidi      View a wordbank entry, or list the latest 50 entries when called`
- `without argument.`
- `modifi    Modify a wordbank entry. Pass at least one option to update.`
- `serci     Serĉi en la vortaro. Sen filtriloj → listigi enirojn ĝis --limo.`
- `forigi    Move a wordbank entry to the recycle bin (with confirmation).`
- `malfari   Undo the last wordbank change (stackable up to 10 operations).`
- `eksporti  Eksporti ĉiujn enirojn (JSON) aŭ unu eniron (TOML).`
- `importi   Import wordbook entries from a JSON file (optionally encrypted).`
- `rubujo    Recycle bin — view, recover, or permanently delete trashed entries.`


## OPTIONS

Run `autish vorto --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish vorto --help

# Show help for a specific subcommand
autish vorto SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-vorto(1)
