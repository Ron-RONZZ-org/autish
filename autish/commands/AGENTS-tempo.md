# AGENTS-tempo.md — tempo Command Agent Instructions

## Summary
Display current local time and day of week, with optional UTC offset selection.

## Purpose and Expected Behavior
- Show current local time in ISO 8601 format with day name.
- Support `--horzono` to display time at a specific UTC offset (-12 to +14).
- Support `-z/--chiuj-horzonoj` to print time for all UTC offsets.
- Default behavior: print system local time via `datetime.now().astimezone()`.

## Constraints and Invariants
- UTC offset range enforced: -12 ≤ horzono ≤ +14.
- No external dependencies beyond stdlib (`datetime`, `locale`).
- Output uses `echo_padded()` from `autish.utils`.
- No database or persistent state.

## Input/Output Expectations
- CLI Options:
  - `--horzono INTEGER`: UTC timezone offset (-12 to +14)
  - `-z/--chiuj-horzonoj`: Print all offsets
- Output: ISO 8601 timestamp + localized day name
- Side Effects: None (read-only)

## Documentation Reference
- `docs/man/tempo.md`

## Domain-Specific Rules for Agents
- Keep implementation minimal; no new dependencies.
- Day name localization uses system locale via `locale.setlocale(locale.LC_TIME, "")`.
- Timezone objects created inline via `datetime.timezone(datetime.timedelta(hours=offset))`.
- When modifying, preserve the invoke_without_command pattern for direct `autish tempo` usage.
