"""_retposto_tui.py — Curses-based full-screen TUI for Retpoŝto.

Architecture
────────────
  RetpostoTUI    Main controller. Owns curses stdscr. Manages panels and
                 dispatches key events to active panel.

Panels
──────
  FolderPanel    Left: account tree + folder list (hjkl navigation).
  MessagePanel   Centre: message list with sort/filter (hjkl, Enter).
  ReaderPanel    Right/full: message body pager (Vim navigation).
  ComposePanel   Overlay: compose/reply/forward form (INSERT mode).

Modes (RetpostoTUI level)
──────────────────────────
  FOLDER   Focus on folder panel
  LIST     Focus on message list
  READ     Focus on message reader (pager)
  COMPOSE  Compose overlay active
  COMMAND  Bottom-line :cmd
  SEARCH   Bottom-line /query
"""

from __future__ import annotations

import curses
import html as html_mod
import re
import sys
import termios
import textwrap
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime
from tempfile import NamedTemporaryFile
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Key constants (reuse _vorto_tui conventions)
# ──────────────────────────────────────────────────────────────────────────────

_ESC = 27
_ENTER = ord("\n")
_CR = ord("\r")
_CTRL_C = 3
_CTRL_D = 4
_CTRL_H = 8
_TAB = ord("\t")
_CTRL_R = 18
_CTRL_S = 19
_CTRL_F = 6   # page-down (like vim)
_CTRL_B = 2   # page-up   (like vim)

_CTRL_LEFT_KEYS = {443, 545, 548, 553, 554}
_CTRL_RIGHT_KEYS = {444, 560, 563, 558, 559, 569}
_CURSES_SLEFT = getattr(curses, "KEY_SLEFT", -1)
_CURSES_SRIGHT = getattr(curses, "KEY_SRIGHT", -1)
if _CURSES_SLEFT != -1:
    _CTRL_LEFT_KEYS.add(_CURSES_SLEFT)
if _CURSES_SRIGHT != -1:
    _CTRL_RIGHT_KEYS.add(_CURSES_SRIGHT)


def _safe_addstr(win: Any, row: int, col: int, text: str, attr: int = 0) -> None:
    """Wrapper around win.addstr that silently absorbs out-of-bounds errors."""
    try:
        win.addstr(row, col, text, attr)
    except curses.error:
        pass
    except UnicodeEncodeError:
        try:
            safe = text.encode("utf-8", errors="replace").decode(
                "utf-8", errors="replace"
            )
            win.addstr(row, col, safe, attr)
        except curses.error:
            pass


def _getch_unicode(win: Any) -> int:
    """Read one key using get_wch(), returning an int."""
    try:
        wch = win.get_wch()
    except curses.error:
        return -1
    if isinstance(wch, str):
        return ord(wch) if len(wch) == 1 else -1
    return wch


def _is_backspace(key: int) -> bool:
    return key in (curses.KEY_BACKSPACE, 127, _CTRL_H)


def _key_to_char(key: int) -> str:
    """Convert an integer key code to a Unicode character if possible."""
    if key <= 0:
        return ""
    if _is_ctrl_left(key) or _is_ctrl_right(key):
        return ""
    try:
        ch = chr(key)
    except ValueError:
        return ""
    if ch == "\x00":
        return ""
    return ch


def _is_ctrl_left(key: int) -> bool:
    return key in _CTRL_LEFT_KEYS


def _is_ctrl_right(key: int) -> bool:
    return key in _CTRL_RIGHT_KEYS


def _word_left(text: str, pos: int) -> int:
    i = max(0, min(pos, len(text)))
    while i > 0 and text[i - 1].isspace():
        i -= 1
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return i


def _word_right(text: str, pos: int) -> int:
    n = len(text)
    i = max(0, min(pos, n))
    while i < n and not text[i].isspace():
        i += 1
    while i < n and text[i].isspace():
        i += 1
    return i


# ──────────────────────────────────────────────────────────────────────────────
# Welcome / help text
# ──────────────────────────────────────────────────────────────────────────────

_WELCOME_LINES = [
    "",
    "             ✉  Retpoŝto",
    "",
    "          ┌──────────────────────────────────┐",
    "          │  a   aldoni konton               │",
    "          │  Tab ŝanĝi panelon               │",
    "          │  c   komponi mesaĝon             │",
    "          │  r   respondi                    │",
    "          │  p   preni poŝton (fetch)        │",
    "          │  h   helpo                       │",
    "          │  q   eliri                       │",
    "          └──────────────────────────────────┘",
    "",
]

_HELP_LINES = [
    "  Retpoŝto — Helpo",
    "  ─────────────────",
    "",
    "  NAVIGADO",
    "    Tab          Dosierujo → mesaĝ-listo",
    "    Shift+Tab    Mesaĝ-listo → dosierujoj",
    "    j/k  ↓/↑    Movi kursoron en aktiva panelo",
    "    h/l  ←/→    Movi kursoron / panorami tekston",
    "    gg / G       Salti al komenco / fino de listo",
    "    Enter        Malfermi elektitan elementon",
    "    Esc          Reen al NORMAL",
    "",
    "  MESAĜOJ",
    "    c            Komponi novan mesaĝon",
    "    r            Respondi al elektita mesaĝo",
    "    R            Respondi al ĉiuj ricevontoj",
    "    f            Plusendi (forward) elektitan mesaĝon",
    "    x            Forigi elektitan mesaĝon (rubujo)",
    "    X            Forigi definitive",
    "    d            Movi mesaĝon al dosierujo",
    "    y            Kopii mesaĝon al dosierujo",
    "    u            Restigi forigitan mesaĝon",
    "    s            Marki kiel spamon",
    "    S            Malfermi spam-panelon",
    "    *            Marki kun stelo (favorita)",
    "    1-9          Agordi prioritaton (1=malalta … 9=alta)",
    "    m/M          Movi konton supren/suben (en konta linio)",
    "    nl/ns        Krei lokan/servilan dosierujon",
    "    p            Preni novan poŝton (fetch)",
    "",
    "  SERĈO",
    "    /            Komenci serĉon en aktiva panelo",
    "    n / N        Sekva / antaŭa trovaĵo",
    "",
    "  KOMANDOJ  (komencu per :)",
    "    :h / :help   Montri helpon",
    "    :q           Eliri",
    "    :p           Preni poŝton",
    "    :konto       Montri kontojn",
    "    :kontakto    Montri kontaktojn",
    "    :bloki <adr> Bloki sendanton",
    "",
    "  KOMPONI",
    "    Tab          Salti al sekva kampo",
    "    Shift+Tab    Salti al antaŭa kampo",
    "    m            Ŝalti/malŝalti markdown-reĝimon",
    "    Ctrl+D / Esc Nuligi",
    "    Ctrl+S       Sendi mesaĝon",
    "",
    "  EKIRI:  q  aŭ  :q",
    "",
]

# ──────────────────────────────────────────────────────────────────────────────
# LineEditor — single-line vim-style text field (from _vorto_tui pattern)
# ──────────────────────────────────────────────────────────────────────────────


class LineEditor:
    """Minimal single-line vim-style editor for compose form fields."""

    def __init__(self, value: str = "", insert_mode: bool = True) -> None:
        self.chars: list[str] = list(value)
        self.pos: int = len(self.chars)
        self.mode: str = "INSERT" if insert_mode else "NORMAL"
        self._view_start: int = 0
        self._visual_anchor: int = self.pos

    @property
    def value(self) -> str:
        return "".join(self.chars)

    @value.setter
    def value(self, v: str) -> None:
        self.chars = list(v)
        self.pos = len(self.chars)

    def render(
        self, win: Any, row: int, col: int, width: int, focused: bool
    ) -> tuple[int, int] | None:
        """Draw the field content; return (row, col) cursor position if focused."""
        # Scroll view so cursor is always visible
        if self.pos < self._view_start:
            self._view_start = self.pos
        if self.pos >= self._view_start + width:
            self._view_start = self.pos - width + 1

        visible = "".join(self.chars)[self._view_start: self._view_start + width]
        if focused:
            if self.mode == "INSERT":
                attr = curses.A_UNDERLINE
            elif self.mode in ("VISUAL_CHAR", "VISUAL_LINE"):
                attr = curses.A_STANDOUT
            else:
                attr = curses.A_BOLD
        else:
            attr = curses.A_NORMAL
        _safe_addstr(win, row, col, visible.ljust(width)[:width], attr)

        if focused:
            cursor_col = col + self.pos - self._view_start
            cursor_col = min(cursor_col, col + width - 1)
            # Visual range highlight.
            if self.mode == "VISUAL_CHAR":
                s = min(self._visual_anchor, self.pos)
                e = max(self._visual_anchor, self.pos)
                for idx in range(s, e + 1):
                    vi = idx - self._view_start
                    if 0 <= vi < width:
                        char = visible[vi] if vi < len(visible.rstrip()) else " "
                        _safe_addstr(win, row, col + vi, char, curses.A_STANDOUT)
            elif self.mode == "VISUAL_LINE":
                _safe_addstr(
                    win, row, col, visible.ljust(width)[:width], curses.A_STANDOUT
                )

            # Cursor model:
            # - INSERT: static vertical bar
            # - NORMAL/VISUAL: highlighted current character
            if self.mode == "INSERT":
                bar_col = min(max(0, self.pos - self._view_start), width - 1)
                _safe_addstr(win, row, col + bar_col, "|", curses.A_BOLD)
            elif self.mode in ("NORMAL", "VISUAL_CHAR", "VISUAL_LINE"):
                char_in_view = self.pos - self._view_start
                if 0 <= char_in_view < width:
                    rstrip_len = len(visible.rstrip())
                    char = visible[char_in_view] if char_in_view < rstrip_len else " "
                    _safe_addstr(win, row, col + char_in_view, char, curses.A_STANDOUT)
            try:
                win.move(row, cursor_col)
            except curses.error:
                pass
            return (row, cursor_col)
        return None

    def handle_key(self, key: int) -> bool:
        """Handle a key press. Returns True if key was consumed."""
        ch = _key_to_char(key)
        if self.mode == "INSERT":
            if key in (_ENTER, _CR):
                return False  # let caller handle
            if _is_backspace(key):
                if self.pos > 0:
                    del self.chars[self.pos - 1]
                    self.pos -= 1
            elif _is_ctrl_left(key):
                self.pos = _word_left(self.value, self.pos)
            elif _is_ctrl_right(key):
                self.pos = _word_right(self.value, self.pos)
            elif key == curses.KEY_LEFT:
                self.pos = max(0, self.pos - 1)
            elif key == curses.KEY_RIGHT:
                self.pos = min(len(self.chars), self.pos + 1)
            elif key == curses.KEY_HOME:
                self.pos = 0
            elif key == curses.KEY_END:
                self.pos = len(self.chars)
            elif key == _ESC:
                self.mode = "NORMAL"
            elif ch and ch.isprintable():
                self.chars.insert(self.pos, ch)
                self.pos += 1
            return True
        if self.mode in ("VISUAL_CHAR", "VISUAL_LINE"):
            if key == _ESC:
                self.mode = "NORMAL"
                return True
            if ch == "i":
                self.mode = "INSERT"
                return True
            if ch == "v" and self.mode == "VISUAL_CHAR":
                self.mode = "NORMAL"
                return True
            if ch == "V" and self.mode == "VISUAL_LINE":
                self.mode = "NORMAL"
                return True
            if ch == "y":
                self.mode = "NORMAL"
                return True
            if ch == "d":
                start = min(self._visual_anchor, self.pos)
                end = max(self._visual_anchor, self.pos)
                if self.mode == "VISUAL_CHAR":
                    del self.chars[start:end + 1]
                    self.pos = min(start, len(self.chars))
                else:
                    self.chars = []
                    self.pos = 0
                self.mode = "NORMAL"
                return True
            if ch == "h" or key == curses.KEY_LEFT:
                self.pos = max(0, self.pos - 1)
            elif ch == "l" or key == curses.KEY_RIGHT:
                self.pos = min(len(self.chars), self.pos + 1)
            elif _is_ctrl_left(key) or ch == "b":
                self.pos = _word_left(self.value, self.pos)
            elif _is_ctrl_right(key) or ch == "w":
                self.pos = _word_right(self.value, self.pos)
            elif ch == "0":
                self.pos = 0
            elif ch == "$":
                self.pos = len(self.chars)
            return True
        else:  # NORMAL
            if ch == "i":
                self.mode = "INSERT"
            elif ch == "a":
                self.mode = "INSERT"
                self.pos = min(len(self.chars), self.pos + 1)
            elif ch == "A":
                self.mode = "INSERT"
                self.pos = len(self.chars)
            elif ch == "v":
                self.mode = "VISUAL_CHAR"
                self._visual_anchor = self.pos
            elif ch == "V":
                self.mode = "VISUAL_LINE"
                self._visual_anchor = self.pos
            elif ch == "h" or key == curses.KEY_LEFT:
                self.pos = max(0, self.pos - 1)
            elif ch == "l" or key == curses.KEY_RIGHT:
                self.pos = min(len(self.chars), self.pos + 1)
            elif _is_ctrl_left(key) or ch == "b":
                self.pos = _word_left(self.value, self.pos)
            elif _is_ctrl_right(key) or ch == "w":
                self.pos = _word_right(self.value, self.pos)
            elif ch == "0":
                self.pos = 0
            elif ch == "$":
                self.pos = len(self.chars)
            elif ch == "x" and self.chars:
                del self.chars[self.pos]
                self.pos = min(self.pos, max(0, len(self.chars) - 1))
            return True


# ──────────────────────────────────────────────────────────────────────────────
# ComposePanel — modal overlay for composing messages
# ──────────────────────────────────────────────────────────────────────────────

_COMPOSE_FIELDS = [
    ("al", "To (al)"),
    ("cc", "Cc"),
    ("bcc", "Bcc"),
    ("subjekto", "Subjekto"),
    ("korpo", "Korpo"),
]


class ComposePanel:
    """Overlay form for composing / replying / forwarding email."""

    def __init__(
        self,
        stdscr: Any,
        initial: dict[str, str] | None = None,
        contact_completer: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.stdscr = stdscr
        initial = initial or {}
        # Create line editors for each header field
        self._editors: dict[str, LineEditor] = {
            "al": LineEditor(initial.get("al", "")),
            "cc": LineEditor(initial.get("cc", "")),
            "bcc": LineEditor(initial.get("bcc", "")),
            "subjekto": LineEditor(initial.get("subjekto", "")),
        }
        # Korpo uses a multiline textarea (list of LineEditors)
        korpo_text = initial.get("korpo", "")
        self._body_lines: list[LineEditor] = [
            LineEditor(ln) for ln in (korpo_text.split("\n") or [""])
        ]
        if not self._body_lines:
            self._body_lines = [LineEditor("")]
        self._current_field: int = 0  # index into _COMPOSE_FIELDS
        self._body_row: int = 0
        self._completer = contact_completer
        self._status: str = (
            "Tab/Shift+Tab:kampo  v/V:VIDA  m:markdown  "
            ":wq sendi  :w skizo  :html antaŭvido  :q nuligi  Ctrl+S"
        )
        self._complete_list: list[str] = []
        self._complete_idx: int = -1
        self._dd_pending: bool = False
        self._body_scroll: int = 0
        self._mode: str = "FIELD"  # FIELD | CMD
        self._cmd_buf: str = ""
        self._markdown_enabled: bool = False

    def _field_names(self) -> list[str]:
        return [k for k, _ in _COMPOSE_FIELDS]

    def _is_body(self) -> bool:
        return self._current_field == len(_COMPOSE_FIELDS) - 1

    def _current_editor(self) -> LineEditor | None:
        if not self._is_body():
            name = _COMPOSE_FIELDS[self._current_field][0]
            return self._editors[name]
        return self._body_lines[self._body_row] if self._body_lines else None

    def get_values(self) -> dict[str, str]:
        return {
            "al": self._editors["al"].value,
            "cc": self._editors["cc"].value,
            "bcc": self._editors["bcc"].value,
            "subjekto": self._editors["subjekto"].value,
            "korpo": "\n".join(e.value for e in self._body_lines),
        }

    def draw(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        md_flag = " [MD]" if self._markdown_enabled else ""
        header = (
            f" ✉  Komponi{md_flag} — Ctrl+S:sendi  m:markdown  :w skizo  :q nuligi "
        )
        _safe_addstr(self.stdscr, 0, 0, header[:w - 1].ljust(w - 1), curses.A_REVERSE)

        label_w = 10
        sep = " │ "
        value_w = max(10, w - label_w - len(sep) - 1)

        focused_cursor: tuple[int, int] | None = None
        row_offset = 1

        # Header fields
        for i, (fname, fhint) in enumerate(_COMPOSE_FIELDS[:-1]):
            scr_row = row_offset + i
            if scr_row >= h - 4:
                break
            focused = i == self._current_field
            label_attr = curses.A_BOLD if focused else curses.A_DIM
            _safe_addstr(
                self.stdscr, scr_row, 0,
                fhint[:label_w].ljust(label_w), label_attr
            )
            _safe_addstr(self.stdscr, scr_row, label_w, sep, curses.A_DIM)
            cursor = self._editors[fname].render(
                self.stdscr, scr_row, label_w + len(sep), value_w, focused
            )
            if cursor:
                focused_cursor = cursor

        # Separator before body
        sep_row = row_offset + len(_COMPOSE_FIELDS) - 1
        if sep_row < h - 4:
            _safe_addstr(
                self.stdscr, sep_row, 0,
                ("─" * (w - 1))[:w - 1], curses.A_DIM
            )

        # Body area
        body_start_row = sep_row + 1
        body_height = h - body_start_row - 2
        body_focused = self._is_body()

        # Keep body_scroll so cursor line is visible
        if body_focused:
            if self._body_row < self._body_scroll:
                self._body_scroll = self._body_row
            elif self._body_row >= self._body_scroll + body_height:
                self._body_scroll = self._body_row - body_height + 1

        for bi in range(body_height):
            li = bi + self._body_scroll
            scr_row = body_start_row + bi
            if scr_row >= h - 2:
                break
            if li < len(self._body_lines):
                focused = body_focused and li == self._body_row
                cursor = self._body_lines[li].render(
                    self.stdscr, scr_row, 0, w - 1, focused
                )
                if cursor:
                    focused_cursor = cursor
            else:
                _safe_addstr(self.stdscr, scr_row, 0, " " * (w - 1))

        # Autocomplete hint
        if self._complete_list:
            hint = "  ".join(self._complete_list[:5])
            _safe_addstr(
                self.stdscr, h - 2, 0,
                hint[:w - 1].ljust(w - 1), curses.A_DIM
            )

        # Status bar — show command line or current editor mode
        if self._mode == "CMD":
            status_line = f":{self._cmd_buf}█"
        else:
            ed = self._current_editor()
            if ed is not None and ed.mode == "INSERT":
                mode_pfx = "-- INSERT --  "
            elif ed is not None and ed.mode == "NORMAL":
                mode_pfx = "-- NORMAL --  "
            else:
                mode_pfx = ""
            status_line = mode_pfx + self._status
        status_line = status_line[:w - 1].ljust(w - 1)
        _safe_addstr(
            self.stdscr, h - 1, 0,
            status_line, curses.A_REVERSE
        )

        if focused_cursor:
            try:
                self.stdscr.move(*focused_cursor)
            except curses.error:
                pass

        self.stdscr.refresh()

    def handle_key(self, key: int) -> str | None:
        """Returns 'send', 'cancel', or None to keep composing."""
        ch = _key_to_char(key)
        ed = self._current_editor()

        if self._mode == "CMD":
            return self._cmd_key(key, ch)

        # Global shortcuts
        if key == _CTRL_C or key == _CTRL_D:
            return "cancel"
        if key == _CTRL_S:
            return "send"

        # Enter command mode (vim-style) from NORMAL mode.
        if ch == ":" and ed is not None and ed.mode == "NORMAL":
            self._mode = "CMD"
            self._cmd_buf = ""
            return None

        # Esc should behave like vim: leave INSERT, do not cancel form.
        if key == _ESC:
            if ed is not None and ed.mode == "INSERT":
                ed.handle_key(key)
            else:
                self._status = "Uzu :wq por sendi aŭ :q por nuligi."
            self._complete_list = []
            self._dd_pending = False
            return None

        # Tab / Shift+Tab — next / previous field
        if key == _TAB:
            self._current_field = (self._current_field + 1) % len(_COMPOSE_FIELDS)
            self._complete_list = []
            return None
        if key == curses.KEY_BTAB:
            self._current_field = (self._current_field - 1) % len(_COMPOSE_FIELDS)
            self._complete_list = []
            return None
        if ch == "m" and ed is not None and ed.mode == "NORMAL":
            self._markdown_enabled = not self._markdown_enabled
            self._status = (
                "[✓] Markdown aktiva"
                if self._markdown_enabled
                else "[✓] Markdown malaktiva"
            )
            return None

        # Body multiline handling
        if self._is_body():
            return self._handle_body_key(key, ch)

        # Header field handling
        if ed is None:
            return None
        if ed.mode == "NORMAL":
            if ch == "j" or key == curses.KEY_DOWN:
                self._current_field = min(
                    len(_COMPOSE_FIELDS) - 1, self._current_field + 1
                )
                return None
            if ch == "k" or key == curses.KEY_UP:
                self._current_field = max(0, self._current_field - 1)
                return None
            if ch == "o":
                self._current_field = min(
                    len(_COMPOSE_FIELDS) - 1, self._current_field + 1
                )
                nxt = self._current_editor()
                if nxt is not None:
                    nxt.mode = "INSERT"
                    nxt.pos = len(nxt.chars)
                return None
            if ch == "O":
                self._current_field = max(0, self._current_field - 1)
                nxt = self._current_editor()
                if nxt is not None:
                    nxt.mode = "INSERT"
                    nxt.pos = len(nxt.chars)
                return None
        if key in (_ENTER, _CR):
            # Tab to next field
            self._current_field = (self._current_field + 1) % len(_COMPOSE_FIELDS)
            return None

        # Autocomplete for al/cc/bcc fields
        field_name = _COMPOSE_FIELDS[self._current_field][0]
        if field_name in ("al", "cc", "bcc") and self._completer:
            if ch and ch.isprintable():
                ed.handle_key(key)
                partial = ed.value.split(",")[-1].strip()
                if len(partial) >= 2:
                    self._complete_list = self._completer(partial)
                else:
                    self._complete_list = []
                return None
            if key == curses.KEY_DOWN and self._complete_list:
                self._complete_idx = (self._complete_idx + 1) % len(
                    self._complete_list
                )
                chosen = self._complete_list[self._complete_idx]
                parts = ed.value.split(",")
                parts[-1] = " " + chosen
                ed.value = ",".join(parts)
                return None

        ed.handle_key(key)
        return None

    def _cmd_key(self, key: int, ch: str) -> str | None:
        if key in (_ENTER, _CR):
            cmd = self._cmd_buf.strip()
            self._mode = "FIELD"
            self._cmd_buf = ""
            if cmd in ("wq", "send"):
                return "send"
            if cmd in ("w", "draft", "skizo"):
                return "draft"
            if cmd in ("html",):
                return "html_preview"
            if cmd in ("q", "q!", "quit", "cancel"):
                return "cancel"
            self._status = f"Nekonata komando: :{cmd} (uzu :wq, :w aŭ :q)"
            return None
        if _is_backspace(key):
            if self._cmd_buf:
                self._cmd_buf = self._cmd_buf[:-1]
            else:
                self._mode = "FIELD"
            return None
        if key == _ESC:
            self._mode = "FIELD"
            self._cmd_buf = ""
            return None
        if ch and ch.isprintable():
            self._cmd_buf += ch
        return None

    def markdown_enabled(self) -> bool:
        return self._markdown_enabled

    def _handle_body_key(self, key: int, ch: str) -> str | None:
        ed = self._body_lines[self._body_row]
        n_lines = len(self._body_lines)
        h, _ = self.stdscr.getmaxyx()
        body_page_h = max(1, h - len(_COMPOSE_FIELDS) - 3)

        if key in (_ENTER, _CR):
            if ed.mode == "INSERT":
                # Split line at cursor
                left = ed.chars[: ed.pos]
                right = ed.chars[ed.pos :]
                ed.chars = left
                ed.pos = len(left)
                new_line = LineEditor("".join(right))
                new_line.pos = 0
                self._body_lines.insert(self._body_row + 1, new_line)
                self._body_row += 1
            return None
        if _is_backspace(key) and ed.mode == "INSERT":
            if ed.pos == 0 and self._body_row > 0:
                # Merge with previous line
                prev = self._body_lines[self._body_row - 1]
                merge_pos = len(prev.chars)
                prev.chars.extend(ed.chars)
                prev.pos = merge_pos
                del self._body_lines[self._body_row]
                self._body_row -= 1
                return None

        if key == curses.KEY_UP and self._body_row > 0:
            self._dd_pending = False
            self._body_row -= 1
            return None
        if key == curses.KEY_DOWN and self._body_row < n_lines - 1:
            self._dd_pending = False
            self._body_row += 1
            return None
        if key == curses.KEY_PPAGE or key == _CTRL_B:
            self._dd_pending = False
            self._body_row = max(self._body_row - body_page_h, 0)
            return None
        if key == curses.KEY_NPAGE or key == _CTRL_F:
            self._dd_pending = False
            self._body_row = min(self._body_row + body_page_h, n_lines - 1)
            return None
        if ch == "j" and ed.mode == "NORMAL" and (
            self._body_row < n_lines - 1
        ):
            self._dd_pending = False
            self._body_row += 1
            return None
        if ch == "k" and ed.mode == "NORMAL" and self._body_row > 0:
            self._dd_pending = False
            self._body_row -= 1
            return None

        # Ctrl+→ cross-line: continue to next line when at end of current
        if _is_ctrl_right(key) and ed.mode == "INSERT":
            new_pos = _word_right(ed.value, ed.pos)
            if new_pos >= len(ed.value) and self._body_row < n_lines - 1:
                self._body_row += 1
                self._body_lines[self._body_row].pos = 0
                self._dd_pending = False
                return None

        # o/O: open new line below/above (NORMAL mode)
        if ch == "o" and ed.mode == "NORMAL":
            new_line = LineEditor("")
            new_line.mode = "INSERT"
            self._body_lines.insert(self._body_row + 1, new_line)
            self._body_row += 1
            self._dd_pending = False
            return None
        if ch == "O" and ed.mode == "NORMAL":
            new_line = LineEditor("")
            new_line.mode = "INSERT"
            self._body_lines.insert(self._body_row, new_line)
            self._dd_pending = False
            return None

        # dd: delete current line (NORMAL mode)
        if ch == "d" and ed.mode == "NORMAL":
            if self._dd_pending:
                if len(self._body_lines) > 1:
                    del self._body_lines[self._body_row]
                    self._body_row = min(self._body_row, len(self._body_lines) - 1)
                else:
                    self._body_lines[0].chars = []
                    self._body_lines[0].pos = 0
                self._dd_pending = False
            else:
                self._dd_pending = True
            return None

        self._dd_pending = False
        ed.handle_key(key)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# FolderPanel — left panel showing accounts and folders
# ──────────────────────────────────────────────────────────────────────────────


class FolderPanel:
    """Left panel: list of accounts and their folders."""

    def __init__(
        self,
        stdscr: Any,
        load_accounts: Callable[[], list[dict]],
        load_folders: Callable[[int], list[dict]],
    ) -> None:
        self.stdscr = stdscr
        self._load_accounts = load_accounts
        self._load_folders = load_folders
        self._cursor: int = 0
        self._scroll: int = 0
        self._items: list[dict] = []  # flat list of {type, label, acc_id, folder_id}
        self._refresh_items()

    def _refresh_items(self) -> None:
        self._items = []
        for acc_idx, acc in enumerate(self._load_accounts(), 1):
            self._items.append(
                {
                    "type": "account",
                    "label": f"{acc_idx}. {acc['retposto']}",
                    "acc_id": acc["id"],
                    "acc_num": acc_idx,
                    "folder_id": None,
                }
            )
            for fld in self._load_folders(acc["id"]):
                self._items.append(
                    {
                        "type": "folder",
                        "label": "  " + fld["nomo"],
                        "acc_id": acc["id"],
                        "acc_num": acc_idx,
                        "folder_id": fld["id"],
                    }
                )

    def selected(self) -> dict | None:
        if self._items:
            return self._items[min(self._cursor, len(self._items) - 1)]
        return None

    def draw(self, win: Any, focused: bool) -> None:
        h, w = win.getmaxyx()
        win.erase()
        title = "Dosierujoj"
        title_attr = curses.A_REVERSE if focused else curses.A_BOLD
        _safe_addstr(win, 0, 0, title[:w - 1].ljust(w - 1), title_attr)

        for i in range(h - 1):
            idx = i + self._scroll
            if idx >= len(self._items):
                break
            item = self._items[idx]
            is_cur = focused and idx == self._cursor
            if item["type"] == "account":
                attr = curses.A_BOLD | (curses.A_STANDOUT if is_cur else 0)
            else:
                attr = curses.A_STANDOUT if is_cur else curses.A_NORMAL
            _safe_addstr(win, i + 1, 0, item["label"][:w - 1].ljust(w - 1), attr)

        win.noutrefresh()

    def handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""
        n = len(self._items)
        if n == 0:
            return None
        h, _ = self.stdscr.getmaxyx()
        panel_h = max(1, h - 2)
        if ch == "j" or key == curses.KEY_DOWN:
            self._cursor = min(self._cursor + 1, n - 1)
        elif ch == "k" or key == curses.KEY_UP:
            self._cursor = max(self._cursor - 1, 0)
        elif key == curses.KEY_NPAGE or key == _CTRL_F:
            self._cursor = min(self._cursor + panel_h, n - 1)
        elif key == curses.KEY_PPAGE or key == _CTRL_B:
            self._cursor = max(self._cursor - panel_h, 0)
        elif ch == "g":
            self._cursor = 0
        elif ch == "G":
            self._cursor = n - 1
        elif key in (_ENTER, _CR):
            return "select"
        elif item := self.selected():
            if item["type"] == "account" and ch == "m":
                return "move_up"
            if item["type"] == "account" and ch == "M":
                return "move_down"
        elif ch == "R":
            self._refresh_items()
        # Adjust scroll
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        elif self._cursor >= self._scroll + panel_h:
            self._scroll = self._cursor - panel_h + 1
        return None


# ──────────────────────────────────────────────────────────────────────────────
# MessagePanel — centre panel showing message list
# ──────────────────────────────────────────────────────────────────────────────

_LIST_COLS = [
    ("!", 1),        # priority/flag
    ("De", 22),
    ("Subjekto", 40),
    ("Dato", 12),
]


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    return iso[:10]


def _fmt_priority(p: int | None) -> str:
    if p is None or p == 5:
        return " "
    if p <= 2:
        return "↑"
    if p >= 8:
        return "↓"
    return str(p)


class MessagePanel:
    """Centre panel: scrollable message list."""

    def __init__(
        self,
        stdscr: Any,
        load_messages: Callable[..., list[dict]],
    ) -> None:
        self.stdscr = stdscr
        self._load_messages = load_messages
        self._messages: list[dict] = []
        self._cursor: int = 0
        self._scroll: int = 0
        self._konto_id: int | None = None
        self._dosierujo_id: int | None = None
        self._spamo: bool = False
        self._forigita: bool = False
        self._search_query: str = ""
        self._all_messages: list[dict] = []

    def load(
        self,
        konto_id: int | None = None,
        dosierujo_id: int | None = None,
        spamo: bool = False,
        forigita: bool = False,
    ) -> None:
        self._konto_id = konto_id
        self._dosierujo_id = dosierujo_id
        self._spamo = spamo
        self._forigita = forigita
        self._all_messages = self._load_messages(
            konto_id=konto_id,
            dosierujo_id=dosierujo_id,
            spamo=spamo,
            forigita=forigita,
            coalesce_threads=True,
        )
        self._messages = list(self._all_messages)
        self._search_query = ""
        self._cursor = 0
        self._scroll = 0

    def selected(self) -> dict | None:
        if self._messages:
            return self._messages[min(self._cursor, len(self._messages) - 1)]
        return None

    def set_filtered_messages(self, messages: list[dict], query: str) -> None:
        self._messages = list(messages)
        self._search_query = query
        self._cursor = 0
        self._scroll = 0

    def reset_filter(self) -> None:
        self._messages = list(self._all_messages)
        self._search_query = ""
        self._cursor = 0
        self._scroll = 0

    def draw(self, win: Any, focused: bool) -> None:
        h, w = win.getmaxyx()
        win.erase()

        msgs = self._messages

        # Header
        header = f" {'!':1}  {'De':22}  {'Subjekto':40}  {'Dato':10}"
        title_attr = curses.A_REVERSE if focused else curses.A_BOLD
        _safe_addstr(win, 0, 0, header[:w - 1].ljust(w - 1), title_attr)

        for i in range(h - 2):
            idx = i + self._scroll
            if idx >= len(msgs):
                break
            msg = msgs[idx]
            is_cur = focused and idx == self._cursor
            unread = not msg.get("legita", False)
            stelo = msg.get("stelo", False)
            spamo = msg.get("spamo", False)

            flag = _fmt_priority(msg.get("prioritato"))
            if stelo:
                flag = "★"
            if spamo:
                flag = "⚠"

            sender = (msg.get("de") or "")[:22]
            subject = msg.get("subjekto") or ""
            thread_count = int(msg.get("_thread_count") or 1)
            if thread_count > 1:
                subject = f"[{thread_count}] {subject}"
            subject = subject[:40]
            date = _fmt_date(msg.get("ricevita_je"))

            line = f" {flag:1}  {sender:22}  {subject:40}  {date:10}"
            if is_cur:
                attr = curses.A_STANDOUT
            elif unread:
                attr = curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            _safe_addstr(win, i + 1, 0, line[:w - 1].ljust(w - 1), attr)

        # Count
        count_str = f" {len(msgs)} mesaĝo(j)"
        if self._search_query:
            count_str += f"  /{self._search_query}"
        _safe_addstr(win, h - 1, 0, count_str[:w - 1].ljust(w - 1), curses.A_DIM)

        win.noutrefresh()

    def handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""
        msgs = self._messages
        n = len(msgs)
        if n == 0:
            return None

        h, _ = self.stdscr.getmaxyx()
        panel_h = max(1, h - 3)

        if ch == "j" or key == curses.KEY_DOWN:
            self._cursor = min(self._cursor + 1, n - 1)
        elif ch == "k" or key == curses.KEY_UP:
            self._cursor = max(self._cursor - 1, 0)
        elif ch == "g":
            self._cursor = 0
        elif ch == "G":
            self._cursor = n - 1
        elif key == curses.KEY_HOME:
            self._cursor = 0
        elif key == curses.KEY_END:
            self._cursor = n - 1
        elif key in (_ENTER, _CR):
            return "open"
        elif ch == "J" or key == curses.KEY_NPAGE or key == _CTRL_F:
            self._cursor = min(self._cursor + panel_h, n - 1)
        elif ch == "K" or key == curses.KEY_PPAGE or key == _CTRL_B:
            self._cursor = max(self._cursor - panel_h, 0)

        # Adjust scroll
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        elif self._cursor >= self._scroll + panel_h:
            self._scroll = self._cursor - panel_h + 1
        return None


# ──────────────────────────────────────────────────────────────────────────────
# MessageReader — full-screen pager for a single message
# ──────────────────────────────────────────────────────────────────────────────


def _message_to_lines(msg: dict) -> list[str]:
    """Format a message dict into displayable lines."""
    lines: list[str] = []
    lines.append(f"  De:       {msg.get('de') or ''}")
    al = msg.get("al") or []
    lines.append(f"  Al:       {', '.join(al) if isinstance(al, list) else al}")
    cc = msg.get("cc") or []
    if cc:
        lines.append(f"  Cc:       {', '.join(cc) if isinstance(cc, list) else cc}")
    lines.append(f"  Subjekto: {msg.get('subjekto') or ''}")
    lines.append(f"  Dato:     {(msg.get('ricevita_je') or '')[:19]}")
    lines.append(f"  ID:       {msg.get('uuid', '')[:16]}")
    prio = msg.get("prioritato", 5)
    if prio != 5:
        lines.append(f"  Prioritato: {prio}")
    aldonajoj = msg.get("aldonajoj") or []
    if aldonajoj:
        lines.append(f"  Aldonaĵoj: {', '.join(aldonajoj)}")
    lines.append("  " + "─" * 60)
    lines.append("")

    body = msg.get("korpo") or ""
    for line in body.split("\n"):
        for wrapped in (textwrap.wrap(line, 76) if line.strip() else [""]):
            lines.append("  " + wrapped)

    return lines


class MessageReader:
    """Full-screen pager for a single message (vim-style navigation)."""

    def __init__(
        self, stdscr: Any, msg: dict, conversation: list[dict] | None = None
    ) -> None:
        self.stdscr = stdscr
        self.msg = msg
        self._lines = _message_to_lines(msg)
        self._row: int = 0
        self._view_row: int = 0
        self._col: int = 0       # horizontal scroll offset
        self._char_col: int = 0  # cursor column within line
        self._search_term: str = ""
        self._mode: str = "NORMAL"
        self._search_buf: str = ""
        self._cmd_buf: str = ""
        self._prev_ch: str = ""  # for gg detection
        self._action: str | None = None  # 'reply', 'forward', 'delete', etc.
        self._visual_mode: str = ""  # "", "char", "line"
        self._visual_anchor_row: int = 0
        self._visual_anchor_col: int = 0
        self._conversation: list[dict] = conversation or [msg]
        self._conversation.sort(
            key=lambda item: item.get("ricevita_je") or item.get("kreita_je") or ""
        )
        self._conv_row: int = next(
            (
                i
                for i, item in enumerate(self._conversation)
                if int(item.get("id", -1)) == int(msg.get("id", -2))
            ),
            0,
        )
        self._conv_view_row: int = 0
        self._pane_focus: str = "body"  # body | conv

    def draw(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        content_h = h - 2

        # Title
        subj = (self.msg.get("subjekto") or "")[:w - 4]
        _safe_addstr(self.stdscr, 0, 0, f" {subj} ".ljust(w - 1), curses.A_REVERSE)

        has_conv = len(self._conversation) > 1 and w >= 70
        conv_w = min(36, max(24, w // 3)) if has_conv else 0
        body_w = w - conv_w - 1 if has_conv else w

        # Auto-scroll so char_col is visible
        if self._char_col < self._col:
            self._col = self._char_col
        elif self._char_col >= self._col + body_w - 1:
            self._col = self._char_col - body_w + 2

        # Keep viewport stable; scroll only when cursor reaches edges.
        if self._row < self._view_row:
            self._view_row = self._row
        elif self._row >= self._view_row + content_h:
            self._view_row = self._row - content_h + 1

        # Content
        content_w = body_w - 1
        focused_cursor: tuple[int, int] | None = None
        for i in range(content_h):
            li = i + self._view_row
            scr_row = i + 1
            if li >= len(self._lines):
                break
            line = self._lines[li]
            visible = line[self._col: self._col + content_w]

            is_match = bool(
                self._search_term
                and self._search_term.lower() in line.lower()
            )
            if li == self._row and self._mode == "NORMAL":
                attr = curses.A_UNDERLINE
            elif self._visual_mode == "line" and self._is_visual_row(li):
                attr = curses.A_STANDOUT
            elif self._visual_mode == "char" and self._is_visual_row(li):
                attr = curses.A_NORMAL
            elif is_match:
                attr = curses.A_STANDOUT
            elif li < 8:  # header lines bold
                attr = curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            _safe_addstr(
                self.stdscr, scr_row, 0, visible[:content_w].ljust(content_w), attr
            )

            if self._visual_mode == "char" and self._is_visual_row(li):
                start_col, end_col = self._visual_bounds_for_row(li, len(line))
                if start_col <= end_col:
                    for ci in range(start_col, end_col + 1):
                        vx = ci - self._col
                        if 0 <= vx < content_w:
                            char = visible[vx] if vx < len(visible) else " "
                            _safe_addstr(
                                self.stdscr, scr_row, vx, char, curses.A_STANDOUT
                            )

            # Block cursor on current line
            if li == self._row and self._mode == "NORMAL":
                cx = self._char_col - self._col
                if 0 <= cx < content_w:
                    char = visible[cx] if cx < len(visible) else " "
                    _safe_addstr(self.stdscr, scr_row, cx, char, curses.A_STANDOUT)
                    focused_cursor = (scr_row, cx)

        if has_conv:
            divider_x = body_w - 1
            for row in range(h - 1):
                _safe_addstr(self.stdscr, row, divider_x, "│", curses.A_DIM)

            conv_x = body_w
            conv_h = content_h
            if self._conv_row < self._conv_view_row:
                self._conv_view_row = self._conv_row
            elif self._conv_row >= self._conv_view_row + conv_h:
                self._conv_view_row = self._conv_row - conv_h + 1

            conv_title = (
                " Konversacio "
                if self._pane_focus == "conv"
                else " Konversacio (Tab por fokusi) "
            )
            _safe_addstr(
                self.stdscr,
                0,
                conv_x,
                conv_title[:conv_w].ljust(conv_w),
                curses.A_REVERSE,
            )
            for i in range(conv_h):
                li = i + self._conv_view_row
                scr_row = i + 1
                if li >= len(self._conversation):
                    break
                item = self._conversation[li]
                prefix = "▶ " if li == self._conv_row else "  "
                subj = item.get("subjekto") or "(sen subjekto)"
                line = f"{prefix}{subj}"
                attr = (
                    curses.A_STANDOUT
                    if li == self._conv_row
                    else curses.A_NORMAL
                )
                _safe_addstr(
                    self.stdscr,
                    scr_row,
                    conv_x,
                    line[:conv_w].ljust(conv_w),
                    attr,
                )

        # Status bar
        if self._mode == "SEARCH":
            status = f"/{self._search_buf}█"
        elif self._mode == "COMMAND":
            status = f":{self._cmd_buf}█"
        else:
            if self._visual_mode == "char":
                mode_label = "[VISUAL-CHAR]"
            elif self._visual_mode == "line":
                mode_label = "[VISUAL-LINE]"
            else:
                mode_label = "[NORMAL]"
            status = (
                f"{mode_label}  j/k:↕  gg/G:⇕  h/l:↔  v/V:VIDA  Ctrl+←/→:vorto  "
                f"r:respondi  R:respondi-ciujn  f:plusendi  x:forigi  d:movi  "
                f"y:kopii  s:spamo  :HTML  :h/:help  Tab:fokuso  q:reen"
            )
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )

        if focused_cursor:
            try:
                self.stdscr.move(*focused_cursor)
            except curses.error:
                pass

        self.stdscr.noutrefresh()
        curses.doupdate()

    def run(self) -> str | None:
        """Run pager loop. Returns action string or None."""
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            while True:
                self.draw()
                key = _getch_unicode(self.stdscr)
                result = self._handle_key(key)
                if result is not None:
                    return result
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _clamp_char_col_to_line(self) -> None:
        cur_line = self._lines[self._row] if self._lines else ""
        self._char_col = min(self._char_col, max(0, len(cur_line) - 1))

    def _move_index(self, key: int, ch: str, current: int, total: int) -> int:
        if total <= 0:
            return 0
        h, _ = self.stdscr.getmaxyx()
        page_h = max(1, h - 2)
        if ch == "j" or key == curses.KEY_DOWN:
            return min(current + 1, total - 1)
        if ch == "k" or key == curses.KEY_UP:
            return max(current - 1, 0)
        if ch == "g" and self._prev_ch == "g":
            return 0
        if ch == "G":
            return total - 1
        if key == curses.KEY_HOME:
            return 0
        if key == curses.KEY_END:
            return total - 1
        if ch == "J" or key == curses.KEY_NPAGE or key == _CTRL_F:
            return min(current + page_h, total - 1)
        if ch == "K" or key == curses.KEY_PPAGE or key == _CTRL_B:
            return max(current - page_h, 0)
        return current

    def _handle_key(self, key: int) -> str | None:
        ch = _key_to_char(key)

        if self._mode == "SEARCH":
            return self._search_key(key, ch)
        if self._mode == "COMMAND":
            if key in (_ENTER, _CR):
                cmd = self._cmd_buf.strip().lower()
                self._mode = "NORMAL"
                self._cmd_buf = ""
                if cmd == "html":
                    return "html"
                if cmd in ("h", "help", "helpo"):
                    return "help"
                return None
            if _is_backspace(key):
                self._cmd_buf = self._cmd_buf[:-1]
                return None
            if key == _ESC:
                self._mode = "NORMAL"
                self._cmd_buf = ""
                return None
            if ch and ch.isprintable():
                self._cmd_buf += ch
            return None
        if key == _TAB and len(self._conversation) > 1:
            self._pane_focus = "conv" if self._pane_focus == "body" else "body"
            return None
        if self._pane_focus == "conv":
            if ch == "q" or key in (_CTRL_C, _CTRL_D):
                self._prev_ch = ""
                return "quit"
            if key == _ESC:
                self._pane_focus = "body"
                return None
            if ch == ":":
                self._mode = "COMMAND"
                self._cmd_buf = ""
                return None
            if key in (_ENTER, _CR):
                msg_id = self._conversation[self._conv_row].get("id")
                if msg_id is not None:
                    return f"open:{msg_id}"
                return None
            if ch == "h" or key == curses.KEY_LEFT:
                self._pane_focus = "body"
                return None
            moved = self._move_index(
                key, ch, self._conv_row, len(self._conversation)
            )
            if moved != self._conv_row:
                self._conv_row = moved
            self._prev_ch = ch
            return None

        count = 1

        n = len(self._lines)
        h, w = self.stdscr.getmaxyx()
        page_h = h - 2
        if n:
            self._row = min(self._row, n - 1)

        if ch == "q" or key in (_CTRL_C, _CTRL_D):
            self._prev_ch = ""
            return "quit"
        if key == _ESC:
            if self._visual_mode:
                self._visual_mode = ""
                return None
            self._prev_ch = ""
            return None
        if ch == "j" or key == curses.KEY_DOWN:
            self._row = min(self._row + count, max(0, n - 1))
            self._clamp_char_col_to_line()
        elif ch == "k" or key == curses.KEY_UP:
            self._row = max(self._row - count, 0)
            self._clamp_char_col_to_line()
        elif ch == "g":
            if self._prev_ch == "g":
                self._row = 0  # gg — go to top
                self._clamp_char_col_to_line()
            # else: wait for second 'g'
        elif ch == "G":
            self._row = max(0, n - 1)
            self._clamp_char_col_to_line()
        elif key == curses.KEY_HOME:
            self._row = 0
            self._clamp_char_col_to_line()
        elif key == curses.KEY_END:
            self._row = max(0, n - 1)
            self._clamp_char_col_to_line()
        elif ch == "J":
            self._row = min(self._row + page_h, max(0, n - 1))
            self._clamp_char_col_to_line()
        elif ch == "K":
            self._row = max(self._row - page_h, 0)
            self._clamp_char_col_to_line()
        elif key == curses.KEY_NPAGE or key == _CTRL_F:
            self._row = min(self._row + page_h, max(0, n - 1))
            self._clamp_char_col_to_line()
        elif key == curses.KEY_PPAGE or key == _CTRL_B:
            self._row = max(self._row - page_h, 0)
            self._clamp_char_col_to_line()
        elif ch == "h" or key == curses.KEY_LEFT:
            self._char_col = max(0, self._char_col - count)
        elif ch == "l" or key == curses.KEY_RIGHT:
            if len(self._conversation) > 1 and self._char_col == max(0, self._col):
                self._pane_focus = "conv"
            else:
                cur_line = self._lines[self._row] if self._lines else ""
                self._char_col = min(
                    self._char_col + count, max(0, len(cur_line) - 1)
                )
        elif _is_ctrl_left(key) or ch == "b":
            cur_line = self._lines[self._row] if self._lines else ""
            self._char_col = _word_left(cur_line, self._char_col)
        elif _is_ctrl_right(key) or ch == "w":
            cur_line = self._lines[self._row] if self._lines else ""
            new_col = _word_right(cur_line, self._char_col)
            if new_col >= len(cur_line) and self._row < n - 1:
                # wrap to the start of the next line
                self._row += 1
                self._char_col = 0
            else:
                self._char_col = new_col
        elif ch == "0":
            self._char_col = 0
        elif ch == "$":
            cur_line = self._lines[self._row] if self._lines else ""
            self._char_col = max(0, len(cur_line) - 1)
        elif ch == "v":
            if self._visual_mode == "char":
                self._visual_mode = ""
            else:
                self._visual_mode = "char"
                self._visual_anchor_row = self._row
                self._visual_anchor_col = self._char_col
        elif ch == "V":
            if self._visual_mode == "line":
                self._visual_mode = ""
            else:
                self._visual_mode = "line"
                self._visual_anchor_row = self._row
                self._visual_anchor_col = 0
        elif ch == "/":
            self._mode = "SEARCH"
            self._search_buf = ""
        elif ch == ":":
            self._mode = "COMMAND"
            self._cmd_buf = ""
        elif ch == "n" and self._search_term:
            self._search_next(1)
        elif ch == "N" and self._search_term:
            self._search_next(-1)
        elif ch == "r":
            self._prev_ch = ""
            return "reply"
        elif ch == "R":
            self._prev_ch = ""
            return "reply_all"
        elif ch == "f":
            self._prev_ch = ""
            return "forward"
        elif ch == "x" or key == curses.KEY_DC:
            self._prev_ch = ""
            return "delete"
        elif ch == "X":
            self._prev_ch = ""
            return "delete_perm"
        elif ch == "s":
            self._prev_ch = ""
            return "spam"
        elif ch == "*":
            self._prev_ch = ""
            return "star"
        elif ch and ch in "123456789":
            self._prev_ch = ""
            return f"priority:{ch}"
        elif ch == "d":
            self._prev_ch = ""
            return "move"
        elif ch == "y":
            self._prev_ch = ""
            return "copy"

        self._prev_ch = ch
        return None

    def _is_visual_row(self, row: int) -> bool:
        top = min(self._visual_anchor_row, self._row)
        bot = max(self._visual_anchor_row, self._row)
        return top <= row <= bot

    def _visual_bounds_for_row(self, row: int, line_len: int) -> tuple[int, int]:
        a_row, c_row = self._visual_anchor_row, self._row
        a_col, c_col = self._visual_anchor_col, self._char_col
        if a_row == c_row:
            return min(a_col, c_col), max(a_col, c_col)
        top = min(a_row, c_row)
        bottom = max(a_row, c_row)
        if row == top:
            if a_row == top:
                return a_col, max(0, line_len - 1)
            return c_col, max(0, line_len - 1)
        if row == bottom:
            return (0, c_col) if c_row == bottom else (0, a_col)
        return (0, max(0, line_len - 1))

    def _search_key(self, key: int, ch: str) -> str | None:
        if key in (_ENTER, _CR):
            self._search_term = self._search_buf
            self._mode = "NORMAL"
            self._search_next(1)
        elif _is_backspace(key):
            self._search_buf = self._search_buf[:-1]
            if not self._search_buf:
                self._mode = "NORMAL"
        elif key == _ESC:
            self._mode = "NORMAL"
            self._search_buf = ""
        elif ch and ch.isprintable():
            self._search_buf += ch
        return None

    def _search_next(self, direction: int) -> None:
        n = len(self._lines)
        if not n:
            return
        start = (self._row + direction) % n
        for i in range(n):
            idx = (start + i * direction) % n
            if self._search_term.lower() in self._lines[idx].lower():
                self._row = idx
                self._clamp_char_col_to_line()
                return


# ──────────────────────────────────────────────────────────────────────────────
# RetpostoTUI — main controller
# ──────────────────────────────────────────────────────────────────────────────


class RetpostoTUI:
    """Main TUI controller for the Retpoŝto email app."""

    def __init__(
        self,
        stdscr: Any,
        *,
        load_accounts: Callable[[], list[dict]],
        load_messages: Callable[..., list[dict]],
        load_folders: Callable[[int], list[dict]],
        fetch_account_mail: Callable[[dict, int], tuple[int, int]],
        send_message: Callable[..., bool],
        save_message: Callable[[dict], int],
        update_message_field: Callable[..., None],
        delete_message: Callable[[int, bool], None],
        load_contacts: Callable[[], list[dict]],
        find_contact: Callable[[str], list[dict]],
        upsert_contact: Callable[..., None],
        load_filters: Callable[[], list[dict]],
        add_spam_block: Callable[[str], None],
        is_spam: Callable[[str], bool],
        ensure_folder: Callable[..., int],
        copy_message: Callable[[int, int, int], int | None] | None = None,
        move_account_order: Callable[[int, int], bool] | None = None,
        rename_folder: Callable[[int, str], None] | None = None,
        move_folder: Callable[[int, int | None], None] | None = None,
        save_account: Callable[[dict], int] | None = None,
        set_password: Callable[[int, str], None] | None = None,
        load_spam_blocks: Callable[[], list[dict]] | None = None,
        remove_spam_block: Callable[[str], None] | None = None,
        update_account: Callable[[int, dict], None] | None = None,
        load_messages_spam: Callable[..., list[dict]] | None = None,
        load_conversation: Callable[[dict], list[dict]] | None = None,
    ) -> None:
        self.stdscr = stdscr
        self._load_accounts = load_accounts
        self._load_messages = load_messages
        self._load_folders = load_folders
        self._fetch_account_mail = fetch_account_mail
        self._send_message = send_message
        self._save_message = save_message
        self._update_message_field = update_message_field
        self._delete_message = delete_message
        self._load_contacts = load_contacts
        self._find_contact = find_contact
        self._upsert_contact = upsert_contact
        self._load_filters = load_filters
        self._add_spam_block = add_spam_block
        self._is_spam = is_spam
        self._ensure_folder = ensure_folder
        self._copy_message = copy_message
        self._move_account_order = move_account_order
        self._rename_folder = rename_folder
        self._move_folder = move_folder
        self._save_account = save_account
        self._set_password = set_password
        self._load_spam_blocks = load_spam_blocks
        self._remove_spam_block = remove_spam_block
        self._update_account = update_account
        self._load_messages_spam = load_messages_spam
        self._load_conversation = load_conversation

        # Panels
        self._folder_panel = FolderPanel(stdscr, load_accounts, load_folders)
        self._message_panel = MessagePanel(stdscr, load_messages)

        # Focus: 'folder', 'list'
        self._focus: str = "folder"
        self._mode: str = "NORMAL"
        self._cmd_buf: str = ""
        self._status_msg: str = ""
        self._status_deadline: float | None = None
        self._status_transient_value: str = ""

        # Layout proportions
        self._folder_w: int = 30
        self._fetching: bool = False
        self._last_folder_target: tuple[str, int] | None = None
        self._pending_prefix: str = ""

        # Initial load
        self._load_initial()

    def _load_initial(self) -> None:
        accounts = self._load_accounts()
        if accounts:
            acc = accounts[0]
            folders = self._load_folders(acc["id"])
            folder_id = folders[0]["id"] if folders else None
            self._message_panel.load(konto_id=acc["id"], dosierujo_id=folder_id)
        else:
            self._message_panel.load()

    def _set_status(self, message: str, *, transient: bool = False) -> None:
        self._status_msg = message
        if transient:
            self._status_transient_value = message
            self._status_deadline = time.monotonic() + 3.0
        else:
            self._status_deadline = None
            self._status_transient_value = ""

    def _current_status(self) -> str:
        if (
            self._status_deadline is not None
            and time.monotonic() >= self._status_deadline
            and self._status_msg == self._status_transient_value
        ):
            self._status_msg = ""
            self._status_deadline = None
            self._status_transient_value = ""
        return self._status_msg

    def run(self) -> None:
        """Main event loop."""
        old_termios: list[Any] | None = None
        fd = -1
        curses.curs_set(0)
        try:
            import locale
            locale.setlocale(locale.LC_ALL, "")
        except Exception:
            pass
        try:
            fd = sys.stdin.fileno()
            old_termios = termios.tcgetattr(fd)
            new_termios = termios.tcgetattr(fd)
            new_termios[0] = new_termios[0] & ~termios.IXON
            termios.tcsetattr(fd, termios.TCSANOW, new_termios)
        except Exception:
            old_termios = None

        # Half-second tick so transient status messages expire automatically
        self.stdscr.timeout(500)
        try:
            while True:
                self._draw()
                key = _getch_unicode(self.stdscr)
                if key == -1:
                    continue
                done = self._handle_key(key)
                if done:
                    break
        finally:
            if old_termios is not None and fd >= 0:
                try:
                    termios.tcsetattr(fd, termios.TCSANOW, old_termios)
                except Exception:
                    pass

    def _draw(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        if h < 10 or w < 40:
            _safe_addstr(
                self.stdscr, 0, 0, "Terminal too small (need 40x10)", curses.A_BOLD
            )
            self.stdscr.refresh()
            return

        # Check if we have accounts
        accounts = self._load_accounts()
        if not accounts:
            self._draw_welcome()
            return

        folder_w = min(self._folder_w, w // 3)
        list_w = w - folder_w

        # Create sub-windows
        try:
            folder_win = self.stdscr.derwin(h - 1, folder_w, 0, 0)
            list_win = self.stdscr.derwin(h - 1, list_w - 1, 0, folder_w)
        except curses.error:
            self._draw_welcome()
            return

        self._folder_panel.draw(folder_win, self._focus == "folder")
        self._message_panel.draw(list_win, self._focus == "list")

        # Vertical divider
        for row in range(h - 1):
            _safe_addstr(self.stdscr, row, folder_w - 1, "│", curses.A_DIM)

        # Global status bar
        if self._mode == "COMMAND":
            status = f":{self._cmd_buf}█"
        else:
            status = self._current_status() or self._default_status()
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )

        self.stdscr.noutrefresh()
        curses.doupdate()

    def _draw_welcome(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        # Centre the welcome art vertically (leave room for status bar)
        art_h = len(_WELCOME_LINES)
        top = max(0, (h - art_h - 2) // 2)

        for i, line in enumerate(_WELCOME_LINES):
            row = top + i
            if row >= h - 1:
                break
            col = max(0, (w - len(line)) // 2)
            _safe_addstr(self.stdscr, row, col, line[:w - 1], curses.A_DIM)

        if self._mode == "COMMAND":
            status = f":{self._cmd_buf}█"
        else:
            accounts = self._load_accounts()
            status = (
                self._current_status()
                or (
                    "NORMAL  a:aldoni-konton  h:helpo  q:eliri  |  : komando"
                    if not accounts
                    else "NORMAL  a h q  |  : komando  |  / serĉi"
                )
            )
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )
        self.stdscr.refresh()

    def _default_status(self) -> str:
        if self._focus == "folder":
            sel = self._folder_panel.selected() or {}
            if sel.get("type") == "account":
                return (
                    "j/k:↕  Enter:malfermi  Tab:mesaĝoj  m/M:movi-konton  "
                    "K:dosierujoj  nl/ns:krei-dosierujon  /:serĉi  "
                    ":h/:help  q:eliri"
                )
            return (
                "j/k:↕  Enter:malfermi  Tab:mesaĝoj  K:dosierujoj  "
                "nl/ns:krei-dosierujon  /:serĉi  :h/:help  q:eliri"
            )
        return (
            "j/k:↕  Enter:legi  Shift+Tab:kontoj  c/r/R/f:komponi  "
            "x:forigi  d:movi  y:kopii  s:spamo  S:spamo-listo  *:stelo  "
            "/:serĉi  :h/:help"
        )

    def _handle_key(self, key: int) -> bool:
        ch = chr(key) if 0 < key < 256 else ""

        if self._mode == "COMMAND":
            return self._cmd_key(key, ch)

        # Global keys
        if ch == "q" or key in (_CTRL_C, _CTRL_D):
            return True
        if key == _ESC:
            self._set_status("Premu q por eliri.", transient=True)
            return False
        if ch == ":":
            self._mode = "COMMAND"
            self._cmd_buf = ""
            return False
        if ch == "/":
            self._show_message_search_screen()
            return False
        if ch == "h":
            self._show_help()
            return False
        if ch == "a" and not self._load_accounts():
            self._action_aldoni_konton()
            return False
        if self._fetching and ch == "p":
            self._status_msg = "[!] Preno jam en progreso..."
            return False

        if key == _TAB and self._focus == "folder":
            self._focus = "list"
            self._status_msg = ""
            return False
        if key == curses.KEY_BTAB and self._focus == "list":
            self._focus = "folder"
            self._status_msg = ""
            return False

        if key == curses.KEY_RESIZE:
            return False

        if self._focus == "folder" and self._pending_prefix == "n":
            self._pending_prefix = ""
            if ch == "l":
                self._action_create_local_folder()
                return False
            if ch == "s":
                self._action_create_server_folder()
                return False

        if self._focus == "folder" and ch == "n":
            self._pending_prefix = "n"
            self._set_status("nl:loka dosierujo  ns:servila dosierujo", transient=True)
            return False

        # Global action keys
        if ch == "c" and self._focus == "list":
            self._compose_new()
            return False
        elif ch == "r" and self._focus == "list":
            self._compose_reply()
            return False
        elif ch == "R" and self._focus == "list":
            self._compose_reply_all()
            return False
        elif ch == "f" and self._focus == "list":
            self._compose_forward()
            return False
        elif ch == "x" and self._focus == "list":
            self._action_delete()
            return False
        elif ch == "X" and self._focus == "list":
            self._action_delete(permanent=True)
            return False
        elif ch == "s" and self._focus == "list":
            self._action_spam()
            return False
        elif ch == "S":
            self._show_spam_pane()
            return False
        elif ch == "K" and self._focus == "folder":
            self._show_folder_manager()
            return False
        elif ch == "*" and self._focus == "list":
            self._action_star()
            return False
        elif ch == "p":
            self._action_fetch()
            return False
        elif ch == "d" and self._focus == "list":
            self._action_move()
            return False
        elif ch == "y" and self._focus == "list":
            self._action_copy()
            return False
        elif ch and ch in "123456789" and self._focus == "list":
            self._action_priority(int(ch))
            return False

        # Panel-specific keys
        if self._focus == "folder":
            result = self._folder_panel.handle_key(key)
            if result == "select":
                sel = self._folder_panel.selected()
                if sel:
                    if sel["type"] == "account":
                        folders = self._load_folders(sel["acc_id"])
                        if folders:
                            self._message_panel.load(
                                konto_id=sel["acc_id"],
                                dosierujo_id=folders[0]["id"],
                            )
                            self._focus = "list"
                        return False
                    folder_label = (sel.get("label") or "").strip().lower()
                    spamo = folder_label in ("spam", "junk")
                    self._message_panel.load(
                        konto_id=sel["acc_id"],
                        dosierujo_id=sel["folder_id"],
                        spamo=spamo,
                    )
                    self._focus = "list"
            elif result == "move_up":
                self._move_selected_account(-1)
            elif result == "move_down":
                self._move_selected_account(1)
        else:
            # List panel keys
            result = self._message_panel.handle_key(key)
            if result == "open":
                self._open_message()
                return False

        return False

    def _cmd_key(self, key: int, ch: str) -> bool:
        if key in (_ENTER, _CR):
            cmd = self._cmd_buf.strip()
            self._mode = "NORMAL"
            self._cmd_buf = ""
            return self._exec_cmd(cmd)
        elif _is_backspace(key):
            if self._cmd_buf:
                self._cmd_buf = self._cmd_buf[:-1]
            else:
                self._mode = "NORMAL"
        elif key == _ESC:
            self._mode = "NORMAL"
            self._cmd_buf = ""
        elif ch and ch.isprintable():
            self._cmd_buf += ch
        return False

    def _exec_cmd(self, cmd: str) -> bool:
        if cmd in ("q", "eliru", "quit", "exit"):
            return True
        if cmd in ("h", "help", "helpo"):
            self._show_help()
        elif cmd == "p" or cmd.startswith("preni"):
            self._action_fetch()
        elif cmd == "c" or cmd == "komponi":
            self._compose_new()
        elif cmd in ("ra", "respondi-ciujn"):
            self._compose_reply_all()
        elif cmd == "konto" or cmd == "kontoj":
            self._show_accounts()
        elif cmd == "kontakto" or cmd.startswith("kontaktoj"):
            self._show_contacts()
        elif cmd == "spamo":
            self._show_spam_pane()
        elif cmd.startswith("bloki "):
            rule = cmd[6:].strip()
            self._add_spam_block(rule)
            self._status_msg = f"Blokita: {rule}"
        elif cmd.startswith("malbloki "):
            rule = cmd[9:].strip()
            if self._remove_spam_block is not None:
                self._remove_spam_block(rule)
                self._status_msg = f"Malblokita: {rule}"
            else:
                self._status_msg = f"Uzu CLI: retposto malbloki {rule}"
        elif cmd.startswith("novdos"):
            # :novdos FolderName
            parts = cmd.split(None, 1)
            if len(parts) < 2 or not parts[1].strip():
                self._status_msg = "Uzu: :novdos <nomo-de-dosierujo>"
            else:
                self._action_create_folder(parts[1].strip())
        elif cmd in ("nl", "kl"):
            self._action_create_local_folder()
        elif cmd in ("ns", "kf"):
            self._action_create_server_folder()
        else:
            self._status_msg = f"Nekonata komando: :{cmd}"
        return False

    # ── actions ──────────────────────────────────────────────────────────────

    def _open_message(self) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        # Mark as read
        if not msg.get("legita"):
            self._update_message_field(msg["id"], legita=1)
            msg["legita"] = 1

        while True:
            conversation = (
                self._load_conversation(msg) if self._load_conversation else [msg]
            )
            reader = MessageReader(self.stdscr, msg, conversation=conversation)
            result = reader.run()
            try:
                curses.curs_set(0)
            except curses.error:
                pass

            if result == "reply":
                if self._compose_reply(msg) == "cancel":
                    continue
            elif result == "reply_all":
                if self._compose_reply_all(msg) == "cancel":
                    continue
            elif result == "forward":
                if self._compose_forward(msg) == "cancel":
                    continue
            elif result == "delete":
                self._delete_message(msg["id"], False)
                self._set_status("Sendita al rubujo.", transient=True)
                self._refresh_list()
            elif result == "delete_perm":
                self._delete_message(msg["id"], True)
                self._set_status("Definitive forigita.", transient=True)
                self._refresh_list()
            elif result == "spam":
                self._mark_spam(msg)
            elif result == "star":
                self._toggle_star(msg)
            elif result == "move":
                self._action_move()
            elif result == "copy":
                self._action_copy()
            elif result == "html":
                self._open_message_html(msg)
            elif result == "help":
                self._show_help()
            elif result and result.startswith("open:"):
                target_id_text = result.split(":", 1)[1]
                if target_id_text.isdigit():
                    target_id = int(target_id_text)
                    next_msg = next(
                        (m for m in conversation if int(m.get("id", -1)) == target_id),
                        None,
                    )
                    if next_msg is not None:
                        msg = next_msg
                        continue
            elif result and result.startswith("priority:"):
                    p_str = result.split(":", 1)[1].strip()
                    if p_str and p_str.isdigit():
                        p = int(p_str)
                        self._update_message_field(msg["id"], prioritato=p)
                        self._set_status(f"Prioritato: {p}", transient=True)
                        self._refresh_list()
            return

    def _open_message_html(self, msg: dict) -> None:
        html = msg.get("html_korpo") or ""
        if not html:
            self._set_status("[!] Mesaĝo ne enhavas HTML-korpon.", transient=True)
            return
        with NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".html", delete=False
        ) as f:
            f.write(html)
            path = f.name
        webbrowser.open(f"file://{path}")
        self._set_status("[✓] Malfermis HTML en retumilo.", transient=True)

    def _open_compose_html_preview(
        self, values: dict[str, str], *, markdown_enabled: bool
    ) -> None:
        body = values.get("korpo") or ""
        html = ""
        if markdown_enabled:
            try:
                import mistune

                html = mistune.html(body)
            except ImportError:
                self._set_status("[!] Instalu `mistune` por markdown-antaŭvido.")
                return
        else:
            html = f"<pre>{html_mod.escape(body)}</pre>"
        subject = html_mod.escape(values.get("subjekto") or "(sen subjekto)")
        to_line = html_mod.escape(values.get("al") or "")
        page = (
            "<html><head><meta charset='utf-8'>"
            f"<title>{subject}</title></head><body>"
            f"<h2>{subject}</h2><p><b>Al:</b> {to_line}</p><hr>{html}</body></html>"
        )
        with NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".html", delete=False
        ) as f:
            f.write(page)
            path = f.name
        webbrowser.open(f"file://{path}")
        self._set_status("[✓] HTML-antaŭvido malfermita.", transient=True)

    def _compose_new(self) -> None:
        self._run_compose({})

    def _compose_reply(self, msg: dict | None = None) -> str:
        if msg is None:
            msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return "done"
        accounts = self._load_accounts()
        sig = self._load_signature(accounts[0]) if accounts else ""
        body_quote = "\n".join(
            "> " + line for line in (msg.get("korpo") or "").split("\n")
        )
        to_targets, _ = self._reply_targets(msg, reply_all=False)
        if not to_targets:
            self._set_status("[!] Ne eblas determini ricevonton por respondo.")
            return "done"
        refs = " ".join(
            x for x in [msg.get("references_hdr"), msg.get("message_id")] if x
        ).strip()
        return self._run_compose({
            "al": ", ".join(to_targets),
            "subjekto": "Re: " + (msg.get("subjekto") or ""),
            "korpo": f"\n--- Originala mesaĝo ---\n{body_quote}\n{sig}",
            "_in_reply_to": msg.get("message_id") or "",
            "_references_hdr": refs,
        })

    def _compose_reply_all(self, msg: dict | None = None) -> str:
        if msg is None:
            msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return "done"
        accounts = self._load_accounts()
        sig = self._load_signature(accounts[0]) if accounts else ""
        body_quote = "\n".join(
            "> " + line for line in (msg.get("korpo") or "").split("\n")
        )
        to_targets, cc_targets = self._reply_targets(msg, reply_all=True)
        if not to_targets:
            self._set_status("[!] Ne eblas determini ricevontojn por respondi-ciujn.")
            return "done"
        refs = " ".join(
            x for x in [msg.get("references_hdr"), msg.get("message_id")] if x
        ).strip()
        return self._run_compose(
            {
                "al": ", ".join(to_targets),
                "cc": ", ".join(cc_targets),
                "subjekto": "Re: " + (msg.get("subjekto") or ""),
                "korpo": f"\n--- Originala mesaĝo ---\n{body_quote}\n{sig}",
                "_in_reply_to": msg.get("message_id") or "",
                "_references_hdr": refs,
            }
        )

    def _reply_targets(
        self, msg: dict, *, reply_all: bool = False
    ) -> tuple[list[str], list[str]]:
        accounts = self._load_accounts()
        account = next(
            (acc for acc in accounts if int(acc["id"]) == int(msg.get("konto_id", -1))),
            accounts[0] if accounts else None,
        )
        me = ((account or {}).get("retposto") or "").strip().lower()
        sender = (msg.get("de") or "").strip().lower()
        to_list = [(x or "").strip().lower() for x in (msg.get("al") or []) if x]
        cc_list = [(x or "").strip().lower() for x in (msg.get("cc") or []) if x]

        if sender and sender != me:
            primary = sender
        else:
            primary = next((addr for addr in to_list if addr and addr != me), "")
        if not primary:
            return ([], [])
        if not reply_all:
            return ([primary], [])

        to_targets: list[str] = [primary]
        for addr in to_list:
            if addr and addr != me and addr not in to_targets:
                to_targets.append(addr)
        cc_targets: list[str] = []
        for addr in cc_list:
            if (
                addr
                and addr != me
                and addr not in to_targets
                and addr not in cc_targets
            ):
                cc_targets.append(addr)
        return (to_targets, cc_targets)

    def _compose_forward(self, msg: dict | None = None) -> str:
        if msg is None:
            msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return "done"
        body_fwd = "\n".join(
            "> " + line for line in (msg.get("korpo") or "").split("\n")
        )
        return self._run_compose({
            "subjekto": "Fwd: " + (msg.get("subjekto") or ""),
            "korpo": f"\n\n--- Plusendita mesaĝo ---\n{body_fwd}",
        })

    def _load_signature(self, acc: dict) -> str:
        """Load signature text for the given account (file path or URL)."""
        import urllib.request
        from pathlib import Path

        sig_src = acc.get("subskribo") or ""
        if not sig_src:
            return ""
        sig_src = sig_src.strip()
        try:
            if sig_src.startswith("https://"):
                with urllib.request.urlopen(sig_src, timeout=5) as resp:  # noqa: S310
                    return "\n\n-- \n" + resp.read().decode("utf-8", errors="replace")
            if sig_src.startswith("http://"):
                # HTTP (non-TLS) signatures are intentionally rejected for security.
                return ""
            p = Path(sig_src).expanduser()
            if p.exists():
                return "\n\n-- \n" + p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        return ""

    def _run_compose(self, initial: dict[str, str]) -> str:
        accounts = self._load_accounts()
        if not accounts:
            self._status_msg = "Neniuj kontoj. Uzu: retposto aldoni-konton"
            return "done"

        acc = accounts[0]

        # Prepend signature if configured
        if "korpo" not in initial or not initial.get("korpo", "").strip():
            sig = self._load_signature(acc)
            if sig:
                initial = {**initial, "korpo": (initial.get("korpo") or "") + sig}

        def _completer(partial: str) -> list[str]:
            return [
                c["retposto"] for c in self._find_contact(partial)
            ]

        panel = ComposePanel(self.stdscr, initial, _completer)
        sending = False
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            while True:
                panel.draw()
                key = _getch_unicode(self.stdscr)
                result = panel.handle_key(key)
                if result == "cancel":
                    self._set_status("Nuligita.", transient=True)
                    return "cancel"
                if result == "html_preview":
                    vals = panel.get_values()
                    self._open_compose_html_preview(
                        vals, markdown_enabled=panel.markdown_enabled()
                    )
                    continue
                if result == "draft":
                    vals = panel.get_values()
                    al_list = [a.strip() for a in vals["al"].split(",") if a.strip()]
                    cc_list = [a.strip() for a in vals["cc"].split(",") if a.strip()]
                    bcc_list = [a.strip() for a in vals["bcc"].split(",") if a.strip()]
                    folder_id = self._ensure_folder(acc["id"], "Malnetoj", "Drafts")
                    msg_id = self._save_message(
                        {
                            "konto_id": acc["id"],
                            "dosierujo_id": folder_id,
                            "de": acc.get("retposto") or "",
                            "al": al_list,
                            "cc": cc_list,
                            "bcc": bcc_list,
                            "subjekto": vals["subjekto"],
                            "korpo": vals["korpo"],
                            "legita": 1,
                            "stelo": 0,
                            "spamo": 0,
                            "forigita": 0,
                            "prioritato": 5,
                        }
                    )
                    self._set_status(
                        f"Konservita kiel skizo (id={msg_id}).",
                        transient=True,
                    )
                    self._folder_panel._refresh_items()
                    self._refresh_list()
                    return "done"
                if result == "send":
                    if sending:
                        panel._status = "[!] Sendado jam en progreso..."
                        continue
                    vals = panel.get_values()
                    al_list = [a.strip() for a in vals["al"].split(",") if a.strip()]
                    cc_list = [a.strip() for a in vals["cc"].split(",") if a.strip()]
                    bcc_list = [a.strip() for a in vals["bcc"].split(",") if a.strip()]
                    if not al_list:
                        panel._status = "[!] Aldonu ricevonton (campo 'Al')"
                        continue
                    if not vals["subjekto"]:
                        if not self._prompt_confirm_inline(
                            "Neniu subjekto. Ĉu sendi? (J/n)"
                        ):
                            continue
                    sending = True
                    panel._status = "Sendante..."
                    panel.draw()
                    html_korpo: str | None = None
                    if panel.markdown_enabled():
                        try:
                            import mistune

                            html_korpo = mistune.html(vals["korpo"])
                        except ImportError:
                            sending = False
                            panel._status = (
                                "[!] Instalu `mistune` por markdown-subteno."
                            )
                            continue
                    ok = self._send_message(
                        acc, al_list, vals["subjekto"],
                        vals["korpo"],
                        cc_list,
                        bcc_list,
                        html_korpo=html_korpo,
                        in_reply_to=(initial.get("_in_reply_to") or None),
                        references_hdr=(initial.get("_references_hdr") or None),
                    )
                    sending = False
                    if ok:
                        self._set_status(
                            f"Sendita al: {', '.join(al_list)}",
                            transient=True,
                        )
                    else:
                        self._status_msg = "[!] Eraro dum sendado."
                    return "done"
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _action_delete(self, permanent: bool = False) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        label = "definitive forigi" if permanent else "forigi"
        if self._prompt_confirm_inline(f"{label} ĉi tiun mesaĝon? (J/n)"):
            self._delete_message(msg["id"], permanent)
            self._set_status("Forigita.", transient=True)
            self._refresh_list()
        else:
            self._set_status("Nuligita.", transient=True)

    def _action_spam(self) -> None:
        msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return
        sender = msg.get("de") or ""
        if not self._prompt_confirm_inline(
            f"Marki kiel spamon kaj bloki '{sender}'? (J/n)"
        ):
            return
        self._add_spam_block(sender)
        self._update_message_field(msg["id"], spamo=1)
        msg["spamo"] = 1
        self._set_status(f"Blokita kiel spamo: {sender}", transient=True)
        self._refresh_list()

    def _mark_spam(self, msg: dict) -> None:
        sender = msg.get("de") or ""
        if not self._prompt_confirm_inline(
            f"Marki kiel spamon kaj bloki '{sender}'? (J/n)"
        ):
            return
        self._add_spam_block(sender)
        self._update_message_field(msg["id"], spamo=1)
        msg["spamo"] = 1
        self._set_status(f"Markita kiel spamo: {sender}", transient=True)
        self._refresh_list()

    def _toggle_star(self, msg: dict) -> None:
        new_val = 0 if msg.get("stelo") else 1
        self._update_message_field(msg["id"], stelo=new_val)
        msg["stelo"] = new_val
        self._set_status(
            "★ Markita." if new_val else "★ Malmarkita.",
            transient=True,
        )

    def _action_star(self) -> None:
        msg = self._message_panel.selected()
        if msg:
            self._toggle_star(msg)

    def _action_priority(self, p: int) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        self._update_message_field(msg["id"], prioritato=p)
        self._set_status(f"Prioritato: {p}", transient=True)
        self._refresh_list()

    def _action_move(self) -> None:
        self._action_move_or_copy(copy_mode=False)

    def _action_copy(self) -> None:
        self._action_move_or_copy(copy_mode=True)

    def _action_move_or_copy(self, copy_mode: bool) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        target = self._prompt_inline(
            "Kopii al dosierujo" if copy_mode else "Movi al dosierujo",
            suggestions=lambda part: self._folder_target_suggestions(
                part, int(msg["konto_id"])
            ),
            accept_first_suggestion=True,
        )
        if not target and self._last_folder_target is None:
            self._set_status("Nuligita.", transient=True)
            return
        folder_name, account_id = self._resolve_folder_target(
            target, int(msg["konto_id"])
        )
        if not folder_name:
            self._set_status("Nuligita.", transient=True)
            return
        prompt = (
            f"Kopii al '{folder_name}' (konto {account_id})? (J/n)"
            if copy_mode
            else f"Movi al '{folder_name}' (konto {account_id})? (J/n)"
        )
        if not self._prompt_confirm_inline(prompt):
            self._set_status("Nuligita.", transient=True)
            return
        folder_id = self._folder_id_by_name(account_id, folder_name)
        if folder_id is None:
            self._set_status(
                f"[!] Dosierujo ne trovita: {folder_name}",
                transient=True,
            )
            return
        if copy_mode:
            if self._copy_message is None:
                self._set_status("[!] Kopii ne subtenata.", transient=True)
                return
            _new_id = self._copy_message(int(msg["id"]), account_id, int(folder_id))
            self._set_status(f"Kopiita al: {folder_name}", transient=True)
        else:
            self._update_message_field(
                int(msg["id"]),
                dosierujo_id=int(folder_id),
                konto_id=account_id,
            )
            self._set_status(f"Movita al: {folder_name}", transient=True)
        self._last_folder_target = (folder_name, account_id)
        self._folder_panel._refresh_items()
        self._refresh_list()

    def _action_fetch(self) -> None:
        if self._fetching:
            self._status_msg = "[!] Preno jam en progreso..."
            return
        accounts = self._load_accounts()
        if not accounts:
            self._status_msg = "[!] Neniuj kontoj konfiguritaj."
            return
        self._fetching = True
        try:
            self._status_msg = "Prenante poŝton..."
            self._draw()
            total = 0
            for acc in accounts:
                f, _ = self._fetch_account_mail(acc, 100)
                total += f
            self._set_status(f"[✓] {total} nova(j) mesaĝo(j).", transient=True)
            self._folder_panel._refresh_items()
            self._refresh_list()
        finally:
            self._fetching = False

    def _move_selected_account(self, direction: int) -> None:
        if self._move_account_order is None:
            return
        sel = self._folder_panel.selected()
        if not sel or sel.get("type") != "account":
            return
        moved = self._move_account_order(int(sel["acc_id"]), direction)
        if moved:
            self._folder_panel._refresh_items()
            self._set_status("Konto-ordo ĝisdatigita.", transient=True)
        else:
            self._set_status("Ne eblas movi plu.", transient=True)

    def _folder_target_suggestions(
        self,
        partial: str,
        current_acc_id: int,
    ) -> list[str]:
        partial_low = partial.lower().strip()
        accs = self._load_accounts()
        acc_nums = {acc["id"]: idx for idx, acc in enumerate(accs, 1)}
        suggestions: list[str] = []
        if self._last_folder_target is not None:
            name, acc_id = self._last_folder_target
            num = acc_nums.get(acc_id, 1)
            suggestions.append(f"{name}/({num})")
        for acc in accs:
            folders = self._load_folders(acc["id"])
            for f in folders:
                name = (f.get("nomo") or "").strip()
                if not name:
                    continue
                full = name
                if acc["id"] != current_acc_id:
                    full = f"{name}/({acc_nums.get(acc['id'], 1)})"
                if partial_low and partial_low not in full.lower():
                    continue
                suggestions.append(full)
        uniq: list[str] = []
        seen: set[str] = set()
        for s in suggestions:
            if s not in seen:
                uniq.append(s)
                seen.add(s)
        return uniq[:6]

    def _folder_id_by_name(self, account_id: int, folder_name: str) -> int | None:
        for folder in self._load_folders(account_id):
            if (folder.get("nomo") or "") == folder_name:
                return int(folder["id"])
        return None

    def _resolve_folder_target(self, raw: str, default_acc_id: int) -> tuple[str, int]:
        value = (raw or "").strip()
        if not value and self._last_folder_target is not None:
            return self._last_folder_target
        if not value:
            return "", default_acc_id
        m = re.match(r"^(?P<name>.*?)/\((?P<num>\d+)\)\s*$", value)
        if not m:
            return value, default_acc_id
        name = (m.group("name") or "").strip()
        num = int(m.group("num"))
        accounts = self._load_accounts()
        if 1 <= num <= len(accounts):
            return name, int(accounts[num - 1]["id"])
        return name, default_acc_id

    def _show_message_search_screen(self) -> None:
        if self._focus != "list":
            self._set_status("Serĉo disponebla en mesaĝ-listo.", transient=True)
            return
        lines: list[str] = []
        buf = ""
        self.stdscr.timeout(-1)
        try:
            while True:
                h, w = self.stdscr.getmaxyx()
                self.stdscr.erase()
                _safe_addstr(
                    self.stdscr, 0, 0,
                    " Mesaĝ-serĉo (IMAP-stilo) ".ljust(w - 1), curses.A_REVERSE
                )
                examples = [
                    'FROM "alice@example.com"',
                    'SUBJECT "meeting"',
                    "SINCE 1-Jan-2024",
                    'BODY "invoice"',
                ]
                row = 1
                for ex in examples:
                    _safe_addstr(self.stdscr, row, 0, f"  {ex}"[:w - 1], curses.A_DIM)
                    row += 1
                row += 1
                for ln in lines[-max(0, h - row - 3):]:
                    _safe_addstr(
                        self.stdscr, row, 0, f"  {ln}"[:w - 1], curses.A_NORMAL
                    )
                    row += 1
                _safe_addstr(
                    self.stdscr,
                    row,
                    0,
                    f"> {buf}█"[:w - 1].ljust(w - 1),
                    curses.A_STANDOUT,
                )
                _safe_addstr(
                    self.stdscr, h - 1, 0,
                    (
                        " Enter:aldoni-linion  malplena Enter:apliki/reset  "
                        "Esc:q nuligi "
                    )[:w - 1].ljust(w - 1),
                    curses.A_REVERSE,
                )
                self.stdscr.refresh()
                key = _getch_unicode(self.stdscr)
                ch = chr(key) if 0 < key < 256 else ""
                if key in (_ESC, _CTRL_C, _CTRL_D):
                    return
                if key in (_ENTER, _CR):
                    text = buf.strip()
                    if not text:
                        self._apply_message_search(lines)
                        return
                    lines.append(text)
                    buf = ""
                    continue
                if _is_backspace(key):
                    buf = buf[:-1]
                    continue
                if ch and ch.isprintable():
                    buf += ch
        finally:
            self.stdscr.timeout(500)

    def _apply_message_search(self, lines: list[str]) -> None:
        clauses: list[tuple[str, str]] = []
        for raw in lines:
            m = re.match(r"^(FROM|SUBJECT|SINCE|BODY)\s+(.+)$", raw.strip(), re.I)
            if not m:
                continue
            field = m.group(1).upper()
            val = m.group(2).strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
            clauses.append((field, val))
        if not clauses:
            self._message_panel.reset_filter()
            self._set_status("Serĉo nuligita.", transient=True)
            return
        pool = list(self._message_panel._all_messages)
        for field, val in clauses:
            needle = val.lower()
            if field == "FROM":
                pool = [m for m in pool if needle in (m.get("de") or "").lower()]
            elif field == "SUBJECT":
                pool = [m for m in pool if needle in (m.get("subjekto") or "").lower()]
            elif field == "BODY":
                pool = [
                    m for m in pool
                    if needle in (m.get("korpo") or "").lower()
                    or needle in (m.get("html_korpo") or "").lower()
                ]
            elif field == "SINCE":
                try:
                    min_dt = datetime.strptime(val, "%d-%b-%Y").date()
                except ValueError:
                    continue
                filtered: list[dict] = []
                for m in pool:
                    stamp = (m.get("ricevita_je") or "")[:10]
                    try:
                        d = datetime.strptime(stamp, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if d >= min_dt:
                        filtered.append(m)
                pool = filtered
        query = " | ".join(f"{k} {v}" for k, v in clauses)
        self._message_panel.set_filtered_messages(pool, query)
        self._set_status(f"Serĉ-rezultoj: {len(pool)}", transient=True)
    def _action_aldoni_konton(self) -> None:
        """Add a new email account interactively from within the TUI."""
        if self._save_account is None or self._set_password is None:
            self._status_msg = "[!] Uzu: retposto aldoni-konton"
            return
        nomo = self._prompt_inline("Nomo (display name)")
        if not nomo:
            self._set_status("Nuligita.", transient=True)
            return
        retposto = self._prompt_inline("Retpoŝtadreso (email)")
        if not retposto:
            self._set_status("Nuligita.", transient=True)
            return
        imap = self._prompt_inline("IMAP servilo (ex: imap.example.com)")
        if not imap:
            self._set_status("Nuligita.", transient=True)
            return
        smtp = self._prompt_inline("SMTP servilo (ex: smtp.example.com)")
        if not smtp:
            self._set_status("Nuligita.", transient=True)
            return
        password = self._prompt_inline("Pasvorto", secret=True)
        if not password:
            self._set_status("Nuligita.", transient=True)
            return
        acc = {
            "nomo": nomo,
            "retposto": retposto.lower().strip(),
            "imap_servilo": imap.strip(),
            "imap_haveno": 993,
            "imap_ssl": True,
            "smtp_servilo": smtp.strip(),
            "smtp_haveno": 587,
            "smtp_tls": True,
            "uzantonomo": retposto.lower().strip(),
        }
        try:
            acc_id = self._save_account(acc)
            self._set_password(acc_id, password)
            self._status_msg = f"[✓] Konto aldonis: {retposto}"
            self._folder_panel._refresh_items()
            self._load_initial()
        except Exception as exc:
            self._status_msg = f"[!] Eraro: {exc}"

    def _action_create_folder(self, folder_name: str) -> None:
        """Create a new folder under the currently selected account."""
        sel = self._folder_panel.selected()
        if not sel:
            accounts = self._load_accounts()
            if not accounts:
                self._status_msg = "[!] Neniuj kontoj konfiguritaj."
                return
            acc_id = accounts[0]["id"]
        else:
            acc_id = sel["acc_id"]
        try:
            folder_id = self._ensure_folder(acc_id, folder_name, folder_name)
            self._set_status(
                f"[✓] Dosierujo kreita: {folder_name} (id={folder_id})",
                transient=True,
            )
            self._folder_panel._refresh_items()
        except Exception as exc:
            self._status_msg = f"[!] Eraro kreante dosierujon: {exc}"

    def _action_create_local_folder(self) -> None:
        folder_name = self._prompt_inline("Loka dosierujo")
        if not folder_name:
            self._set_status("Nuligita.", transient=True)
            return
        self._action_create_folder(folder_name)

    def _action_create_server_folder(self) -> None:
        accounts = self._load_accounts()
        if not accounts:
            self._status_msg = "[!] Neniuj kontoj konfiguritaj."
            return
        if len(accounts) == 1:
            target_acc = accounts[0]
        else:
            lines = [f"{i}. {acc['retposto']}" for i, acc in enumerate(accounts, 1)]
            msg = "Elektu konton por servila dosierujo:\n" + "\n".join(lines)
            self._run_pager_lines(msg.splitlines(), "Kont-elekto")
            pick = self._prompt_inline("Konta numero")
            if not pick.isdigit() or not (1 <= int(pick) <= len(accounts)):
                self._set_status("Nuligita.", transient=True)
                return
            target_acc = accounts[int(pick) - 1]
        folder_name = self._prompt_inline("Servila dosierujo")
        if not folder_name:
            self._set_status("Nuligita.", transient=True)
            return
        folder_id = self._ensure_folder(target_acc["id"], folder_name, folder_name)
        self._folder_panel._refresh_items()
        self._set_status(
            f"[✓] Servila dosierujo kreita: {folder_name} (id={folder_id})",
            transient=True,
        )

    def _refresh_list(self) -> None:
        sel = self._folder_panel.selected()
        if sel:
            if sel["type"] == "account":
                folders = self._load_folders(sel["acc_id"])
                if folders:
                    self._message_panel.load(
                        konto_id=sel["acc_id"],
                        dosierujo_id=folders[0]["id"],
                    )
            else:
                self._message_panel.load(
                    konto_id=sel["acc_id"],
                    dosierujo_id=sel["folder_id"],
                )

    # ── overlays (pager-based) ────────────────────────────────────────────────

    def _show_help(self) -> None:
        self._run_pager_lines(_HELP_LINES, "Helpo")

    def _show_accounts(self) -> None:
        accounts = self._load_accounts()
        if not accounts:
            lines = ["  Neniuj kontoj konfiguritaj."]
            self._run_pager_lines(lines, "Kontoj")
            return
        # Interactive account view with edit support
        self._show_account_management()

    def _show_account_management(self) -> None:
        """Interactive account list; 'e' edits selected account credentials."""
        cursor = 0
        while True:
            accounts = self._load_accounts()
            h, w = self.stdscr.getmaxyx()
            self.stdscr.erase()
            _safe_addstr(
                self.stdscr, 0, 0,
                " Kontoj — e:redakti  s:subskribo  q:reen ".ljust(w - 1),
                curses.A_REVERSE,
            )
            for i, acc in enumerate(accounts):
                is_cur = i == cursor
                sub = acc.get("subskribo") or ""
                sub_hint = f"  [{sub[:20]}]" if sub else ""
                line = (
                    f"  {i + 1:<3} {acc['retposto']:<30} "
                    f"{acc.get('imap_servilo', ''):<20} "
                    f"{acc.get('smtp_servilo', '')}{sub_hint}"
                )
                attr = curses.A_STANDOUT if is_cur else curses.A_NORMAL
                _safe_addstr(self.stdscr, i + 1, 0, line[:w - 1].ljust(w - 1), attr)
            _safe_addstr(
                self.stdscr, h - 1, 0,
                " j/k:↕  e:redakti  s:subskribo  q:reen ".ljust(w - 1),
                curses.A_REVERSE,
            )
            self.stdscr.refresh()
            if not accounts:
                break
            n = len(accounts)
            key = _getch_unicode(self.stdscr)
            if key == -1:
                continue
            ch = chr(key) if 0 < key < 256 else ""
            if ch == "q" or key in (_ESC, _CTRL_C, _CTRL_D):
                break
            if ch == "j" or key == curses.KEY_DOWN:
                cursor = min(cursor + 1, n - 1)
            elif ch == "k" or key == curses.KEY_UP:
                cursor = max(cursor - 1, 0)
            elif ch == "e":
                acc = accounts[cursor]
                self._edit_account(acc)
            elif ch == "s":
                acc = accounts[cursor]
                self._edit_account_signature(acc)

    def _edit_account(self, acc: dict) -> None:
        """Let the user update IMAP/SMTP credentials for an account."""
        if self._update_account is None:
            self._status_msg = "[!] Ĝisdatigi konton ne eblas: mankas subtenon."
            return
        fields = [
            ("nomo", "Nomo"),
            ("imap_servilo", "IMAP servilo"),
            ("imap_haveno", "IMAP haveno"),
            ("smtp_servilo", "SMTP servilo"),
            ("smtp_haveno", "SMTP haveno"),
        ]
        updates: dict[str, Any] = {}
        for key_name, label in fields:
            current = str(acc.get(key_name) or "")
            new_val = self._prompt_inline(f"{label} [{current}]")
            if new_val == "":
                continue  # keep existing
            updates[key_name] = new_val
        # Optionally update password
        new_pw = self._prompt_inline(
            "Nova pasvorto (lasu malplena por konservi)", secret=True
        )
        if updates:
            try:
                self._update_account(acc["id"], updates)
                self._status_msg = "[✓] Konto ĝisdatigita."
            except Exception as exc:
                self._status_msg = f"[!] Eraro: {exc}"
        if new_pw and self._set_password is not None:
            try:
                self._set_password(acc["id"], new_pw)
                self._status_msg = "[✓] Pasvorto ĝisdatigita."
            except Exception as exc:
                self._status_msg = f"[!] Eraro pasvorto: {exc}"

    def _edit_account_signature(self, acc: dict) -> None:
        """Set or clear the signature for an account."""
        if self._update_account is None:
            self._status_msg = "[!] Ĝisdatigi konton ne eblas: mankas subtenon."
            return
        current = acc.get("subskribo") or ""
        new_val = self._prompt_inline(
            f"Subskribo dosiero/URL [{current}] (lasu malplena por forigi)"
        )
        try:
            self._update_account(acc["id"], {"subskribo": new_val})
            if new_val:
                self._status_msg = f"[✓] Subskribo agordita: {new_val}"
            else:
                self._status_msg = "[✓] Subskribo forigita."
        except Exception as exc:
            self._status_msg = f"[!] Eraro: {exc}"

    def _show_spam_pane(self) -> None:
        """Show blocked senders and spam messages; allow restoring them."""
        cursor = 0
        section = 0  # 0=blocks, 1=spam messages

        while True:
            h, w = self.stdscr.getmaxyx()
            self.stdscr.erase()

            _safe_addstr(
                self.stdscr, 0, 0,
                (
                    " Spamo — Tab:sekcio  u:malbloki/restarigi  "
                    ":h/:help  q:reen "
                ).ljust(w - 1),
                curses.A_REVERSE,
            )

            blocks: list[dict] = []
            if self._load_spam_blocks is not None:
                blocks = self._load_spam_blocks()

            spam_msgs: list[dict] = []
            if self._load_messages_spam is not None:
                spam_msgs = self._load_messages_spam(spamo=True)
            else:
                spam_msgs = self._load_messages(spamo=True)

            # Layout: top half = blocks, bottom half = spam messages
            mid = (h - 2) // 2
            row = 1
            _safe_addstr(
                self.stdscr, row, 0,
                f" ── Blokitaj adresoj ({len(blocks)}) ".ljust(w - 1),
                curses.A_BOLD if section == 0 else curses.A_DIM,
            )
            row += 1
            for i, blk in enumerate(blocks):
                is_cur = section == 0 and i == cursor
                attr = curses.A_STANDOUT if is_cur else curses.A_NORMAL
                line = f"  {blk.get('regulo', '')}"
                added = blk.get("kreita_je", "")[:10]
                if added:
                    line += f"  ({added})"
                _safe_addstr(self.stdscr, row, 0, line[:w - 1].ljust(w - 1), attr)
                row += 1
                if row >= mid:
                    break

            row = mid + 1
            _safe_addstr(
                self.stdscr, mid, 0,
                f" ── Spamaj mesaĝoj ({len(spam_msgs)}) ".ljust(w - 1),
                curses.A_BOLD if section == 1 else curses.A_DIM,
            )
            for i, msg in enumerate(spam_msgs):
                is_cur = section == 1 and i == cursor
                attr = curses.A_STANDOUT if is_cur else curses.A_NORMAL
                sender = (msg.get("de") or "")[:25]
                subj = (msg.get("subjekto") or "")[:30]
                line = f"  {sender:<25}  {subj}"
                _safe_addstr(self.stdscr, row, 0, line[:w - 1].ljust(w - 1), attr)
                row += 1
                if row >= h - 1:
                    break

            _safe_addstr(
                self.stdscr, h - 1, 0,
                (
                    " j/k:↕  Tab:sekcio  u:malbloki/restarigi  "
                    ":h/:help  q:reen "
                ).ljust(w - 1),
                curses.A_REVERSE,
            )
            self.stdscr.refresh()

            key = _getch_unicode(self.stdscr)
            if key == -1:
                continue
            ch = chr(key) if 0 < key < 256 else ""

            if ch == "q" or key in (_ESC, _CTRL_C, _CTRL_D):
                break
            if ch == ":":
                cmd = self._prompt_inline("Komando")
                if cmd in ("h", "help", "helpo"):
                    self._show_help()
                continue
            if key == _TAB:
                section = 1 - section
                cursor = 0
            elif ch == "j" or key == curses.KEY_DOWN:
                n = len(blocks) if section == 0 else len(spam_msgs)
                cursor = min(cursor + 1, max(0, n - 1))
            elif ch == "k" or key == curses.KEY_UP:
                cursor = max(cursor - 1, 0)
            elif key == curses.KEY_NPAGE or key == _CTRL_F:
                n = len(blocks) if section == 0 else len(spam_msgs)
                cursor = min(cursor + (h // 4), max(0, n - 1))
            elif key == curses.KEY_PPAGE or key == _CTRL_B:
                cursor = max(cursor - (h // 4), 0)
            elif ch == "u":
                if section == 0:
                    # Unblock selected address
                    if blocks and cursor < len(blocks):
                        rule = blocks[cursor]["regulo"]
                        if self._remove_spam_block is not None:
                            self._remove_spam_block(rule)
                            self._set_status(f"Malblokita: {rule}", transient=True)
                            cursor = max(0, cursor - 1)
                        else:
                            self._status_msg = f"Uzu CLI: retposto malbloki {rule}"
                else:
                    # Restore spam message (un-spam)
                    if spam_msgs and cursor < len(spam_msgs):
                        msg = spam_msgs[cursor]
                        self._update_message_field(msg["id"], spamo=0)
                        self._set_status("Restarigita el spamo.", transient=True)
                        cursor = max(0, cursor - 1)

    def _show_folder_manager(self) -> None:
        """Ranger-style folder manager overlay."""
        if self._move_folder is None or self._rename_folder is None:
            self._status_msg = "[!] Dosierujo-administrado ne disponeblas."
            return
        pane = "accounts"
        account_idx = 0
        folder_cursor = 0
        selected_ids: set[int] = set()
        cut_ids: set[int] = set()
        visual_anchor: int | None = None

        while True:
            accounts = self._load_accounts()
            if not accounts:
                self._status_msg = "[!] Neniuj kontoj konfiguritaj."
                return
            account_idx = min(max(0, account_idx), len(accounts) - 1)
            acc = accounts[account_idx]
            folders = self._load_folders(int(acc["id"]))
            if folders:
                folder_cursor = min(max(0, folder_cursor), len(folders) - 1)
            else:
                folder_cursor = 0

            h, w = self.stdscr.getmaxyx()
            left_w = max(20, w // 4)
            mid_w = max(30, w // 2)
            right_w = max(20, w - left_w - mid_w)
            self.stdscr.erase()
            _safe_addstr(
                self.stdscr,
                0,
                0,
                " Dosierujoj (K) ".ljust(w - 1),
                curses.A_REVERSE,
            )
            # Left pane: accounts
            _safe_addstr(
                self.stdscr, 1, 0, " Kontoj ".ljust(left_w - 1), curses.A_BOLD
            )
            for i, a in enumerate(accounts[: max(0, h - 4)]):
                marker = ">" if i == account_idx else " "
                line = f"{marker} {i + 1}. {a['retposto']}"
                attr = (
                    curses.A_STANDOUT
                    if pane == "accounts" and i == account_idx
                    else 0
                )
                _safe_addstr(
                    self.stdscr,
                    2 + i,
                    0,
                    line[: left_w - 1].ljust(left_w - 1),
                    attr,
                )

            # Middle pane: folders
            _safe_addstr(
                self.stdscr,
                1,
                left_w,
                f" Dosierujoj — {acc['retposto']} ".ljust(mid_w - 1),
                curses.A_BOLD,
            )
            for i, f in enumerate(folders[: max(0, h - 4)]):
                fid = int(f["id"])
                selected = fid in selected_ids
                cut = fid in cut_ids
                prefix = "[x]" if cut else ("[*]" if selected else "[ ]")
                line = f"{prefix} {f.get('nomo') or ''}  (id={fid})"
                attr = (
                    curses.A_STANDOUT
                    if pane == "folders" and i == folder_cursor
                    else 0
                )
                _safe_addstr(
                    self.stdscr,
                    2 + i,
                    left_w,
                    line[: mid_w - 1].ljust(mid_w - 1),
                    attr,
                )

            # Right pane: help/preview
            help_lines = [
                "Ranger-stilo",
                "",
                "Tab:panelo  h/l:ŝanĝi panelon",
                "j/k aŭ ↑/↓:navigi",
                "SPACE:marki",
                "v ... v:intervalo",
                "r:renomi  d:tondi  p:alglui",
                "q:reen",
            ]
            if folders and pane == "folders":
                cur = folders[folder_cursor]
                help_lines += [
                    "",
                    f"Fokuso: {cur.get('nomo') or ''}",
                    f"id: {cur.get('id')}",
                ]
            col = left_w + mid_w
            _safe_addstr(
                self.stdscr,
                1,
                col,
                " Helpo ".ljust(right_w - 1),
                curses.A_BOLD,
            )
            for i, hl in enumerate(help_lines[: max(0, h - 4)]):
                _safe_addstr(
                    self.stdscr,
                    2 + i,
                    col,
                    hl[: right_w - 1].ljust(right_w - 1),
                    curses.A_DIM,
                )

            _safe_addstr(
                self.stdscr,
                h - 1,
                0,
                (
                    " Tab:h/l panelo  r:renomi  SPACE/v:elekti  "
                    "d:tondi  p:alglui  :h/:help  q:reen "
                )[:w - 1].ljust(w - 1),
                curses.A_REVERSE,
            )
            self.stdscr.refresh()

            key = _getch_unicode(self.stdscr)
            if key == -1:
                continue
            ch = chr(key) if 0 < key < 256 else ""
            if ch == "q" or key in (_CTRL_C, _CTRL_D):
                return
            if ch == ":":
                cmd = self._prompt_inline("Komando")
                if cmd in ("h", "help", "helpo"):
                    self._show_help()
                continue
            if key == _ESC:
                if selected_ids or cut_ids or visual_anchor is not None:
                    selected_ids.clear()
                    cut_ids.clear()
                    visual_anchor = None
                    self._set_status("Elekto nuligita.", transient=True)
                else:
                    self._set_status("Uzu q por eliri.", transient=True)
                continue
            if key == _TAB or ch in ("h", "l"):
                pane = "folders" if pane == "accounts" else "accounts"
                continue

            if pane == "accounts":
                if ch == "j" or key == curses.KEY_DOWN:
                    account_idx = min(account_idx + 1, len(accounts) - 1)
                elif ch == "k" or key == curses.KEY_UP:
                    account_idx = max(account_idx - 1, 0)
                continue

            if not folders:
                continue
            focused = folders[folder_cursor]
            focused_id = int(focused["id"])
            prev_cursor = folder_cursor
            if ch == "j" or key == curses.KEY_DOWN:
                folder_cursor = min(folder_cursor + 1, len(folders) - 1)
            elif ch == "k" or key == curses.KEY_UP:
                folder_cursor = max(folder_cursor - 1, 0)
            elif ch == " ":
                if focused_id in selected_ids:
                    selected_ids.remove(focused_id)
                else:
                    selected_ids.add(focused_id)
            elif ch == "v":
                if visual_anchor is None:
                    visual_anchor = folder_cursor
                    selected_ids.add(int(folders[folder_cursor]["id"]))
                else:
                    start = min(visual_anchor, folder_cursor)
                    end = max(visual_anchor, folder_cursor)
                    for i in range(start, end + 1):
                        selected_ids.add(int(folders[i]["id"]))
                    visual_anchor = None
            if visual_anchor is not None and folder_cursor != prev_cursor:
                start = min(prev_cursor, folder_cursor)
                end = max(prev_cursor, folder_cursor)
                for i in range(start, end + 1):
                    selected_ids.add(int(folders[i]["id"]))
            elif ch == "r":
                new_name = self._prompt_inline("Nova dosieruja nomo")
                if not new_name:
                    self._set_status("Nuligita.", transient=True)
                    continue
                if not self._prompt_confirm_inline(f"Renomi al '{new_name}'? (J/n)"):
                    self._set_status("Nuligita.", transient=True)
                    continue
                self._rename_folder(focused_id, new_name)
                self._set_status("Dosierujo renomita.", transient=True)
                self._folder_panel._refresh_items()
            elif ch == "d":
                targets = set(selected_ids) if selected_ids else {focused_id}
                if not self._prompt_confirm_inline(
                    f"Tondi {len(targets)} dosierujo(j)n? (J/n)"
                ):
                    self._set_status("Nuligita.", transient=True)
                    continue
                cut_ids = set(targets)
                self._set_status(
                    f"{len(cut_ids)} dosierujo(j) pretaj por alglui.",
                    transient=True,
                )
            elif ch == "p":
                if not cut_ids:
                    self._set_status("Nenio por alglui.", transient=True)
                    continue
                if not self._prompt_confirm_inline(
                    f"Alglui {len(cut_ids)} dosierujo(j)n sub "
                    f"'{focused.get('nomo')}'? (J/n)"
                ):
                    self._set_status("Nuligita.", transient=True)
                    continue
                for fid in list(cut_ids):
                    if fid == focused_id:
                        continue
                    self._move_folder(fid, focused_id)
                cut_ids.clear()
                selected_ids.clear()
                self._folder_panel._refresh_items()
                self._set_status("Dosierujoj algluitaj.", transient=True)

    def _show_contacts(self) -> None:
        contacts = self._load_contacts()
        if not contacts:
            lines = ["  Neniuj kontaktoj."]
        else:
            lines = ["  Nomo                           Retpoŝto", ""]
            for c in contacts:
                lines.append(
                    f"  {(c.get('nomo') or ''):<30}  {c['retposto']}"
                )
        self._run_pager_lines(lines, "Koresponda Listo")

    def _run_pager_lines(self, lines: list[str], title: str) -> None:
        """Show a simple scrollable pager for a list of text lines."""
        row = 0
        while True:
            h, w = self.stdscr.getmaxyx()
            page_h = max(1, h - 2)
            self.stdscr.erase()
            _safe_addstr(
                self.stdscr, 0, 0,
                f" {title} ".ljust(w - 1), curses.A_REVERSE
            )
            for i in range(h - 2):
                li = i + row
                if li >= len(lines):
                    break
                _safe_addstr(
                    self.stdscr, i + 1, 0,
                    lines[li][:w - 1], curses.A_NORMAL
                )
            _safe_addstr(
                self.stdscr, h - 1, 0,
                " j/k:↕  PgDn/PgUp:paĝo  q:reen ".ljust(w - 1), curses.A_REVERSE
            )
            self.stdscr.refresh()
            key = _getch_unicode(self.stdscr)
            if key == -1:
                continue
            ch = chr(key) if 0 < key < 256 else ""
            if ch == "q" or key in (_ESC, _CTRL_C, _CTRL_D):
                break
            if ch == "j" or key == curses.KEY_DOWN:
                row = min(row + 1, max(0, len(lines) - h + 2))
            elif ch == "k" or key == curses.KEY_UP:
                row = max(row - 1, 0)
            elif key == curses.KEY_NPAGE or key == _CTRL_F:
                row = min(row + page_h, max(0, len(lines) - h + 2))
            elif key == curses.KEY_PPAGE or key == _CTRL_B:
                row = max(row - page_h, 0)
            elif ch == "G":
                row = max(0, len(lines) - h + 2)
            elif ch == "g":
                row = 0

    # ── inline prompts ────────────────────────────────────────────────────────

    def _prompt_inline(
        self,
        prompt: str,
        secret: bool = False,
        suggestions: Callable[[str], list[str]] | None = None,
        accept_first_suggestion: bool = False,
    ) -> str:
        buf = ""
        self.stdscr.timeout(-1)
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            while True:
                self._draw()
                h, w = self.stdscr.getmaxyx()
                display = "*" * len(buf) if secret else buf
                line = f"{prompt}: {display}█"
                sugg: list[str] = []
                if suggestions is not None:
                    sugg = suggestions(buf.strip())
                    if sugg:
                        _safe_addstr(
                            self.stdscr,
                            max(0, h - 2),
                            0,
                            ("  " + "  ".join(sugg))[:w - 1].ljust(w - 1),
                            curses.A_DIM,
                        )
                _safe_addstr(
                    self.stdscr, h - 1, 0, line[:w - 1].ljust(w - 1), curses.A_REVERSE
                )
                self.stdscr.refresh()
                key = _getch_unicode(self.stdscr)
                ch = chr(key) if 0 < key < 256 else ""
                if key in (_ENTER, _CR):
                    if accept_first_suggestion and sugg:
                        return sugg[0].strip()
                    return buf.strip()
                if key == _ESC or key in (_CTRL_C, _CTRL_D):
                    return ""
                if _is_backspace(key):
                    buf = buf[:-1]
                elif ch and ch.isprintable():
                    buf += ch
        finally:
            self.stdscr.timeout(500)
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _prompt_confirm_inline(self, prompt: str) -> bool:
        h, w = self.stdscr.getmaxyx()
        _safe_addstr(
            self.stdscr, h - 1, 0, prompt[:w - 1].ljust(w - 1), curses.A_REVERSE
        )
        self.stdscr.refresh()
        self.stdscr.timeout(-1)
        try:
            default_yes = "(J/n)" in prompt or "(j/n)" in prompt
            while True:
                key = _getch_unicode(self.stdscr)
                if key == -1:
                    continue
                ch = chr(key) if 0 < key < 256 else ""
                if ch in ("j", "y", "Y"):
                    return True
                if key in (_ENTER, _CR):
                    return default_yes
                if ch in ("n", "N") or key in (_ESC, _CTRL_C, _CTRL_D):
                    return False
        finally:
            self.stdscr.timeout(500)
