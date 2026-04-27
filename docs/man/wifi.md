# wifi(1)

## NAME

wifi - Komandoj por administri Wi-Fi.

## SYNOPSIS

```
autish wifi [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Komandoj por administri Wi-Fi.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `ls          List Wi-Fi connections, with the active one first.`
- `restarti    Restart Wi-Fi/network stack for recovery from connectivity issues.`
- `konekti     Connect to a Wi-Fi network.`
- `malkonekti  Disconnect from the active Wi-Fi connection.`
- `forigi      Delete a saved Wi-Fi network profile.`


## OPTIONS

Run `autish wifi --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish wifi --help

# Show help for a specific subcommand
autish wifi SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-wifi(1)
