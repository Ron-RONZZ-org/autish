# etikedo(1)

## NAME

etikedo - Etikedo — administri etikedojn por todo kaj taglibro.

## SYNOPSIS

```
autish etikedo [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Etikedo — administri etikedojn por todo kaj taglibro.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `aldoni  Aldoni novan etikedon kun aŭtomata UUID.`
- `modifi  Modifi ekzistantan etikedon.`
- `forigi  Forigi etikedon laŭ UUID aŭ teksto.`
- `serci   Serĉi etikedojn per teksto (kun fuzzy fallback).`
- `vidi    Montri unu etikedon; se ne ekzakta, uzi serĉan elekton.`


## OPTIONS

Run `autish etikedo --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish etikedo --help

# Show help for a specific subcommand
autish etikedo SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-etikedo(1)
