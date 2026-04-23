# bug fixes

- still more random entries in format `Fonto-xxxxx [Celo](#xxxx)` in encik
 18   1ad64a05    Fonto-9c4410a5 [Celo](#87bc66ca)
 19   8d05bbe8    Fonto-90090c7d [Celo](#757cdc32)
 20   a30e8004    Fonto-4fec3c28 [Celo](#f75b34c5)
... (at least 50)
 - investigate origin, fix up to prevent new generation, and remove existing.

## feature enhancement

## `kontakto aldoni`

```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ kontakto aldoni -o "Metz à Vélo" -N "Maison du Vélo" -p "3 AVE LECLERC DE HAUTECLOCQUE FR-57000 METZ" -k "ASSO LOI-FR-1908" -r info@metzavelo.fr -t 0033355809291
[!] Atendita formato: valoro:etikedo[:prima]
```

- should instead automatically assume to be prima if only one retposto/telefonnumero parsed.

- in all text fields, full markdown parsing and support linking to `encik` with `[](ec#)` and  `vorto`  with `[](vt#)`

- duplicate handling: should not be (j/N), but (a/k/N): anstataŭigi, krei nova, nuligi


## `encik aldoni`

- As the number of entries increase, the time it takes for `aldoni` to run is also increasing. Can we enhance user experience by reducing processing time ?
