"""Shared text-editing primitives for curses TUIs.

This module keeps core word-motion behavior synchronized across interactive apps.
"""

from __future__ import annotations


def word_left(text: str, pos: int) -> int:
    """Return the start index of the previous word from cursor position *pos*."""
    i = max(0, min(pos, len(text)))
    while i > 0 and text[i - 1].isspace():
        i -= 1
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return i


def word_right(text: str, pos: int) -> int:
    """Return the start index of the next word from cursor position *pos*."""
    n = len(text)
    i = max(0, min(pos, n))
    while i < n and not text[i].isspace():
        i += 1
    while i < n and text[i].isspace():
        i += 1
    return i
