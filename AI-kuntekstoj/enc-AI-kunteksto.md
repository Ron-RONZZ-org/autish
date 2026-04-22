## .enc syntax summary

`.enc` is a simple key-value text format for multilingual terminology entries.

## `terminologio`

An encik file always begin by specifying the terminology to be defined in the `.enc` file in one or more languages:

```enc
terminologio.eo = "..."
terminologio.fr = "..."
terminologio.en = "..."
```

if the terminology is identical in different languages (e.g., name of a person), an abbreviated syntax can be used:

```enc
terminologio.(eo,fr,en)="..."
```

## `difino`

- The term is defined in one or more languages with `difino.(lang-code)`
- If the definition is multiline, write it as a triple-quoted markdown block:

```enc
difino.eo = """
- first point
- second point
  - first sub-point
  - second sub-point
"""
```

Each line should focus on one point, and more complex points should be explained in detail in sub-points. In particular, for readability, refrain from inline enumeration like `A: a,b,and c`. Use instead a markdown list:

```enc
- A
  - a
  - b
  - c
```

For very long definitions, we may divide it into multiple sections. Each section should start with a second-level title `##`:

```enc
## One important aspect

- A
- B
  -a
  -b

## Another important aspect

- C
 -d
```

- If the definition is only one line, use a single quoted string:

```enc
difino.eo = "short definition"
```

Use Katex formulas to illustrate mathematical/scientific formulas in symbols as much as possible:

```enc
terminologio.eo = "elektrostatika stato"
terminologio.fr = "état électrostatique"
terminologio.en = "electrostatic state"
difino.eo = "$\vec{E_{interna}}=0$"
```

## Generating `.enc` file

- Keep formatting minimal and consistent
- Do not add extra explanation inside the `.enc` file
- use this template specific to our style:

```enc
terminologio.eo="..."
terminologio.fr="..."
terminologio.en="..."
difino.eo="""
...
"""
```
for long `difino`

and 

```enc
terminologio.eo="..."
terminologio.fr="..."
terminologio.en="..."
difino.eo="..."
```

if `difino` is one-line only.

## examples

for a person:

```enc
terminologio.(eo,fr,en)="Hans Christian Ørsted"
difino.eo="""
- Sciencisto
  - Ĝenerala Sekretario de la Reĝa Dana Scienca Societo
- Dana
- frato de la 3-a dana ĉefministro A.S. Ørsted"""
```

for an abstract concept:

```enc
terminologio.eo="sekundo (unuo)"
terminologio.fr="seconde (unité)"
terminologio.en="second (unit)"
difino.eo="""
- $(1\mathrm{s} = 9,192,631,770 \cdot \Delta t(\mathrm{Cs\text{-}133}))$
  - ($9 192 631 770 \cdot T_{text{la transiro inter du hiperfinaj niveloj de la baza stato de la cezia-133 atomo}}$)
- SI unuo por tempo
```

for a category of object:

```enc
terminologio.eo="mikroregilo"
terminologio.fr="microcontrôleur"
terminologio.en="microprocessor"
difino.eo="""
## malgranda komputila blato

- kiu enhavas
  - procesoron
  - memoron
    - RAM
    - EEPROM
  - I/O interfacojn
- por regado de sistemoj

## avantaĝo

- malalta kosto
- simpla efektivigo

## malavantaĝo

- malrapida"""
```



