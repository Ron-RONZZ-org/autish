"""Legacy local patch helper.

This script was used for one-off local edits during development sessions.
It is intentionally minimal and kept lint-clean so repository-wide Ruff checks
do not fail on temporary helper code.
"""

from __future__ import annotations


def main() -> None:
    """No-op entrypoint kept for backwards compatibility."""
    return


if __name__ == "__main__":
    main()
