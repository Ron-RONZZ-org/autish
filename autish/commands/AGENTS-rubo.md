# AGENTS-rubo.md — rubo Command Agent Instructions

## Summary
Linux recycle bin (rubujo) management — move files to trash, recover, or permanently delete.

## Purpose and Expected Behavior
- Move files to recycle bin: `forigi` (alias: `rm`).
- Recover trashed files: `rehavi` (from recycle bin).
- Permanently delete: `deforigi` (purge from recycle bin).
- List trash contents: `listigi` (or invoke without subcommand).
- Search in trash: `serci`.
- Uses XDG-compliant trash location (`~/.local/share/Trash/` or XDG dir).

## Constraints and Invariants
- Uses `autish.services.recycle_bin.RecycleBinDB` for trash operations.
- `RecycleBinDB` handles XDG trash spec compliance.
- `TrashItem` dataclass for trash entry representation.
- File operations: move (trash), restore (to original path), delete (purge).
- Size formatting: bytes → human-readable (B, KB, MB, GB, TB).

## Input/Output Expectations
- Subcommands: `forigi`/`rm`, `rehavi`, `deforigi`, `listigi`, `serci`
- Key CLI Options:
  - `forigi`: `paths...` (files/dirs to trash, required), `-d`/`--definitive` (bypass trash)
  - `rehavi`: `<uuid>` (trash item UUID, required)
  - `deforigi`: `<uuid>` (trash item UUID, required)
  - `serci`: `[teksto]` (search term, optional)
- Output: Rich tables for trash listing, status messages for operations
- Side Effects: File system changes (move, restore, delete)

## Documentation Reference
- `docs/man/rubo.md`

## Domain-Specific Rules for Agents
- Always use `RecycleBinDB` from `autish.services.recycle_bin`; do not implement trash logic directly.
- Definitive delete (`-d`): bypasses trash, permanently deletes; confirm with user.
- Restore (`rehavi`): restore to original path; handle conflicts (file already exists).
- Trash location: respect XDG spec; use `$XDG_DATA_HOME` if set, else `~/.local/share/Trash/`.
- Size formatting: use `_format_size()` helper.
- Hidden files: show/hide with appropriate filtering option.
