# sekurkopio(1)

## NAME

sekurkopio - Sekurkopio — sekurkopii kaj restaŭri ĉiujn autish-uzantajn datumojn.

## SYNOPSIS

```
autish sekurkopio [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Sekurkopio — sekurkopii kaj restaŭri ĉiujn autish-uzantajn datumojn.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `eksporti         Export all autish user data as an encrypted archive.`
- `importi          Restore autish user data from an encrypted archive.`
- `auto             Manage automatic periodic backups.`
- `daemon           Run automatic backup daemon.`
- `install-systemd  Generate and install systemd user service and timer for automatic backups.`
- `install-cron     Add a cron job for automatic backups.`
- `historio         Show a summary of the last 5 sekurkopio operations.`
- `reveni           Restore autish data from a specific auto backup.`


## OPTIONS

Run `autish sekurkopio --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish sekurkopio --help

# Show help for a specific subcommand
autish sekurkopio SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-sekurkopio(1)
