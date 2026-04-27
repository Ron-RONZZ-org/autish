# disko(1)

## NAME

disko - Disko — administri stokajn aparatojn.

## SYNOPSIS

```
autish disko [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Disko — administri stokajn aparatojn.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `ls        List all connected storage devices.`
- `sano      Check disk health using SMART (requires sudo).`
- `munti     Mount a disk at the specified location.`
- `malmunti  Unmount one or more disks.`
- `particio  Administri particiojn`


## OPTIONS

Run `autish disko --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish disko --help

# Show help for a specific subcommand
autish disko SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-disko(1)
