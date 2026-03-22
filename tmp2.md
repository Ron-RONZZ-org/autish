COPILOT CLI
# Bug fixes

# Feature enhancements

- add a mark all as read functionality in CLI/TUI
- ensure that READ/UNREAD status is synchronised with server
  - in case of conflict, local first
- for consistent esperanto locale:
  - change `--inverse/-i` in `vorto vidi` to `--inversa/-i` 
  - where `-h/--help` is present, add `--helpo` as an alias

# New features

## `encik ls`

- list entries
  - default newest 10 entries
  - `-p {page number}`: list n-th page. `-p 2` return the 11th-20th newest by default, for example
  - `-i/--inversa`: list from oldest 

## `autish disko` CLI command

- functionalities
 - `ls`: list connected storage devices in a table
   - nomo(name)
   - tipo: subdisko(partition)/disko(disk)
   - loko(mountpoint)
   - grandeco(size)
   - spaco (available space)
   - dosiersistemo (file system)
   - RM (removable: 0/1)
   - RO (readonly: 0/1)
   - modelo (disk model)
 - `sano {nomo}`: wrapper for `smartctl` to test health of storage devices
  - by default, use `sudo smartctl -a` to get S.M.A.R.T info and return it in a more human readable format in Esperanto
 - `munti/malmunti {nomo} [-l/--loko {loko}]`: mount/dismount disk at given location
   - default to `$HOME/{disk label, name if no label}`
   - ask user confirmation before creating directory automatically for the mount point if non-existent
