# kalendaro(1)

## NAME

kalendaro - Kalendaro — administri kalendarojn kaj eventojn.

## SYNOPSIS

```
autish kalendaro [SUBCOMMAND] [OPTIONS]...
```

## DESCRIPTION

Kalendaro — administri kalendarojn kaj eventojn.

For more information about autish, see autish(1).

## SUBCOMMANDS

- `aldoni            Aldoni foran aŭ lokan kalendaron, testi konfiguracion, kaj tuj provi komencan sinkronigon. Ekz:`
- `kalendaro aldoni https://cal.ex/k.ics -u alice --pasvorto sekret123`
- `modifi            Modifi kalendaran agordon laŭ UUID. Ekz: kalendaro modifi abcdef12 --uzantnomo alice --pasvorto`
- `novaSekreto123`
- `ls-kalendaro      Listigi kalendarojn (UUID + URL mallongigita por klareco). Ekz: kalendaro ls-kalendaro`
- `ls                Montri eventojn en datintervalo. Ekz: kalendaro ls 20260125 20260130 -k abcdef12`
- `vidi              Montri detalojn de unu aŭ pluraj eventoj. Ekz: kalendaro vidi a1b2c3d4`
- `importi           Importi ICS-dosierojn en kalendaron. Ekz: kalendaro importi abcdef12 /tmp/e1.ics /tmp/e2.ics`
- `eksporti          Eksporti eventojn laŭ UUID aŭ laŭ kalendaro+datoj. Ekz: kalendaro eksporti -k abcdef12 20260101`
- `20260131 -d /tmp/out.ics`
- `forigi            Forigi eventojn laŭ UUID. Ekz: kalendaro forigi a1b2c3d4 -a`
- `amase-forigi      Forigi eventojn en intervalo, opcie laŭ kalendaro. Ekz: kalendaro amase-forigi 20260101 20260131`
- `-k abcdef12`
- `malfari           Montri aŭ malfari ŝanĝojn. Ekz: kalendaro malfari ls ; kalendaro malfari 12ab34cd`
- `serci             Serĉi eventojn kun kombineblaj filtriloj. Ekz: kalendaro serci kunveno --dato-de 20260101`
- `--dato-gis 20260131 --kategorio laboro`
- `forigi-kalendaro  Forigi unu aŭ plurajn kalendarojn laŭ UUID, aŭ ĉion sen UUID (kun konfirmo). Ekz: kalendaro`
- `forigi-kalendaro abcdef12`
- `sinkronigi        Sinkronigi pendajn lokajn ŝanĝojn al foraj kalendaroj. Ekz: kalendaro sinkronigi -k abcdef12`


## OPTIONS

Run `autish kalendaro --help` to see all available options.

## EXAMPLES

```bash
# Show help for this command
autish kalendaro --help

# Show help for a specific subcommand
autish kalendaro SUBCOMMAND --help
```

## AUTHOR

Autish contributors

## SEE ALSO

autish(1), autish-kalendaro(1)
