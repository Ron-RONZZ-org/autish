# Bug fix

## `encik`

- `serci`: the relational search algorithms are not working correctly.

For example, I ran:
╭────────────────────── polusiĝo ──────────────────────╮
│   uuid:          34bebe8a                            │
│   lingvo:        eo                                  │
│   difino:                                            │
│     - apartigo de pozitivaj kaj negativaj elektraĵoj │
│     - ene de objekto aŭ sistemo                      │
│   superklaso:                                        │
│     fizika #27664112                                 │
╰──────────────────────────────────────────────────────╯
(autish-py3.12) rongzhou@libres:~/kodo/autish$ encik serci -p 34bebe8a
Neniu nodo trovita por '34bebe8a'.
While there are at least 3 other nodes with same parent class !

fix the search logics for
| --subklasoj    
│ --superklasoj   
│ --ligilo 
│ --semantiko
│ --al 
│ --paralela     

DEV: Ask for clarification if my instructions are unclear. Use mature modern packages with stable APIs, good resource efficiency and scalability. Correct wording/spellings to standard esperanto spellings !
 Test thoroughly, including for edge cases. Make SURE that you have valid, meaningful results as expected before coming back to me.
