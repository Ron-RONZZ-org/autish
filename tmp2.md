# bug fixes
```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ autish disko sano sda
Kontrolante sanon de /dev/sda...
(Bezonas sudo rajtojn)

Eraro: Ne povis legi SMART informojn.
```

# feature enhancements

- add commands to disko to manage partitions: shrink partition, create new, format
  - change summary and `j/N`confirmation for all system modifications
  - throw error on bad usage: e.g., formatting disk where the current OS is installed

# new: utility functions to enhance Linux system experience

## `rubo` working with system recycle bin

- `rubo forigi {path}*`
  - move specified files to recycle bin
  - alias: `rubo rm`
- `rubo ls`
  - list recycle bin contents
- `rubo serci {keyword}`
  - search in recycle bin
    - wildcard `*` support
  - `-R/--regex`: basic POSIX regex support
- `rubo restarigi {path}*`
  - restore files from recycle bin
  - alias: `rubo rs`

