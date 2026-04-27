# encik(1)

## NAME

encik - Encik — persona sci-mastruma mikroapo.

## SYNOPSIS

```
autish encik [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Encik — persona sci-mastruma mikroapo.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `agordi           Montri aŭ ŝanĝi encik montrado-agordon en ~/.config/autish/encik.toml.`
- `aldoni           Aldoni novan nodon el .enc dosiero.`
- `modifi           Modifi ekzistantan nodon per redaktilo, .enc dosiero, aŭ CLI-opcioj.`
- `vidi             Montri unu nodon laŭ UUID aŭ terminologio.`
- `eksporti         Eksporti unu encik-nodon al .enc dosiero.`
- `generi           Generi .enc tekston per AI por terminologio + difino kampoj.`
- `semantika-serci  Serĉi nodojn laŭ semantikaj datum-valoroj (AND inter kondiĉoj).`
- `serci            Serĉi nodojn. Por semantikaj ligiloj, vidu ankaŭ: encik semantika.`
- `ls               List encik entries with pagination.`
- `forigi           Delete one or more encik entries by UUID.`
- `semantika        Semantic link types for Encik knowledge graph.`
- `Organized by group in ~/.config/autish/semantika/*.csv (LIGILO, PRISKRIBO, ALIAZOJ columns).`


## OPTIONS

Run `autish encik --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish encik --help

# Show help for a specific subcommand
autish encik SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-encik(1)
