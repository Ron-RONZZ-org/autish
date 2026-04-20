# feature enhancements

- add alias `-T` for `--teksto` in `vorto vidi`
# bug fix 

- `vorto` interactive mode
  - typing in the command bar STILL occasionally causes the bar to blink. Fix it !

- `vorto serci -sk` results display:

```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ vorto serci -sk munir
Neniu preciza rezulto; montrante similajn kongruojn.
0 rezulto(j) trovita(j).
Neniu rezulto trovita. (No results found.)
Elektu numeron por kopii (aŭ Enter por nuligi) []: 
```

If no result, should not show selection menu !


