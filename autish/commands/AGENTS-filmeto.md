# AGENTS-filmeto.md — filmeto Command Agent Instructions

## Summary
Low-stimulation video CLI focused on YouTube, with download, search, and playlist management.

## Purpose and Expected Behavior
- Search videos: `serci` (YouTube search via yt-dlp).
- Download videos/audio: `elŝuti` (supports format selection, audio-only).
- Play videos: `ludi` (opens in browser or external player).
- Playlist management: `listo` sub-typer for playlist CRUD.
- Cache search results locally: `~/.local/share/autish/filmeto_cache.json`.
- Browser profile detection: auto-detect Firefox forks (Floorp, LibreWolf, etc.) for cookie-based auth.

## Constraints and Invariants
- Depends on `yt-dlp` for all YouTube operations.
- Cache file: `~/.local/share/autish/filmeto_cache.json`.
- Config file: `~/.local/share/autish/filmeto_agordo.json`.
- Search strategy file: `~/.local/share/autish/filmeto_search_strategy.json`.
- Browser fork map: `{"floorp": "firefox", "librewolf": "firefox", ...}`.
- Large file threshold: 500MB (`_LARGE_SIZE_BYTES`).

## Input/Output Expectations
- Subcommands: `serci`, `elŝuti`, `ludi`, `listo` (sub-typer)
- `listo` subcommands: `aldoni`, `vidi`, `forigi`, `serci`
- Key CLI Options:
  - `serci`: `<demando>` (search query), `-L`/`--limo` (result limit)
  - `elŝuti`: `<url>`, `-f`/`--formato` (format selection), `-a`/`--audio` (audio only)
  - `ludi`: `<url>` (video URL)
- Output: Rich tables for search results, progress for downloads
- Side Effects: File downloads, cache file writes, network I/O

## Documentation Reference
- `docs/man/filmeto.md`

## Domain-Specific Rules for Agents
- Always use `YoutubeDL` from `yt-dlp` for all operations; never call yt-dlp binary directly.
- Search results caching: store in `_CACHE_FILE`; use `_SEARCH_STRATEGY_FILE` for optimization.
- Browser cookie auth: detect profile via `_discover_firefox_style_profiles()`; pass to yt-dlp.
- Large file warning: check file size before download; warn if > `_LARGE_SIZE_BYTES`.
- CSV export: supports `_CSV_TRUE_VALUES`/`_CSV_FALSE_VALUES` for boolean parsing.
- When adding new video platforms, extend beyond YouTube (currently focused).
- Error handling: catch `DownloadError` from yt-dlp; display user-friendly messages.
