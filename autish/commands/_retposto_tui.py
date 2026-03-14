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
import textwrap
from collections.abc import Callable
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


# ──────────────────────────────────────────────────────────────────────────────
# Welcome / help text
# ──────────────────────────────────────────────────────────────────────────────

_WELCOME_LINES = [
    "",
    "  ┌─────────────────────────────────────────┐",
    "  │          ✉  Retpoŝto  ✉                 │",
    "  │   TUI email for autish                  │",
    "  └─────────────────────────────────────────┘",
    "",
    "  [Tab]  ŝanĝi panelon   [c]  komponi    [r]  respondi",
    "  [p]    preni (fetch)   [/]  serĉi      [q]  eliri",
    "  [h]    helpo           [:]  komando",
    "",
]

_HELP_LINES = [
    "  Retpoŝto — Helpo",
    "  ─────────────────",
    "",
    "  NAVIGADO",
    "    Tab          Cikli inter paneloj (dosierujo → listo → leganto)",
    "    j/k  ↓/↑    Movi kursoron en aktiva panelo",
    "    h/l  ←/→    Movi kursoron / panorami tekston",
    "    gg / G       Salti al komenco / fino de listo",
    "    Enter        Malfermi elektitan elementon",
    "    Esc          Reen al NORMAL",
    "",
    "  MESAĜOJ",
    "    c            Komponi novan mesaĝon",
    "    r            Respondi al elektita mesaĝo",
    "    f            Plusendi (forward) elektitan mesaĝon",
    "    d            Forigi elektitan mesaĝon (rubujo)",
    "    D            Forigi definitive",
    "    u            Restigi forigitan mesaĝon",
    "    s            Marki kiel spamon",
    "    *            Marki kun stelo (favorita)",
    "    1-9          Agordi prioritaton (1=malalta … 9=alta)",
    "    m            Movi mesaĝon al dosierujo",
    "    p            Preni novan poŝton (fetch)",
    "",
    "  SERĈO",
    "    /            Komenci serĉon en aktiva panelo",
    "    n / N        Sekva / antaŭa trovaĵo",
    "",
    "  KOMANDOJ  (komencu per :)",
    "    :q           Eliri",
    "    :p           Preni poŝton",
    "    :konto       Montri kontojn",
    "    :kontakto    Montri kontaktojn",
    "    :bloki <adr> Bloki sendanton",
    "",
    "  KOMPONI",
    "    Tab          Salti al sekva kampo",
    "    Shift+Tab    Salti al antaŭa kampo",
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
        attr = curses.A_BOLD if focused else curses.A_NORMAL
        _safe_addstr(win, row, col, visible.ljust(width)[:width], attr)

        if focused and self.mode == "INSERT":
            cursor_col = col + self.pos - self._view_start
            return (row, min(cursor_col, col + width - 1))
        return None

    def handle_key(self, key: int) -> bool:
        """Handle a key press. Returns True if key was consumed."""
        ch = chr(key) if 0 < key < 256 else ""
        if self.mode == "INSERT":
            if key in (_ENTER, _CR):
                return False  # let caller handle
            if _is_backspace(key):
                if self.pos > 0:
                    del self.chars[self.pos - 1]
                    self.pos -= 1
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
        else:  # NORMAL
            if ch == "i":
                self.mode = "INSERT"
            elif ch == "a":
                self.mode = "INSERT"
                self.pos = min(len(self.chars), self.pos + 1)
            elif ch == "A":
                self.mode = "INSERT"
                self.pos = len(self.chars)
            elif ch == "h" or key == curses.KEY_LEFT:
                self.pos = max(0, self.pos - 1)
            elif ch == "l" or key == curses.KEY_RIGHT:
                self.pos = min(len(self.chars), self.pos + 1)
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
        self._status: str = "Ctrl+S:sendi  Esc:nuligi  Tab:sekva kampo"
        self._complete_list: list[str] = []
        self._complete_idx: int = -1

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

        header = " ✉  Komponi — Ctrl+S:sendi  Tab:sekva kampo  Esc:nuligi "
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

        for bi in range(body_height):
            li = bi  # simple, no scroll for now
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

        # Status bar
        _safe_addstr(
            self.stdscr, h - 1, 0,
            self._status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )

        if focused_cursor:
            try:
                self.stdscr.move(*focused_cursor)
            except curses.error:
                pass

        self.stdscr.refresh()

    def handle_key(self, key: int) -> str | None:
        """Returns 'send', 'cancel', or None to keep composing."""
        ch = chr(key) if 0 < key < 256 else ""

        # Global shortcuts
        if key == _CTRL_C or key == _CTRL_D:
            return "cancel"
        if key == _ESC:
            return "cancel"
        if key == 19:  # Ctrl+S
            return "send"

        # Tab / Shift+Tab — next / previous field
        if key == _TAB:
            self._current_field = (self._current_field + 1) % len(_COMPOSE_FIELDS)
            self._complete_list = []
            return None
        if key == curses.KEY_BTAB:
            self._current_field = (self._current_field - 1) % len(_COMPOSE_FIELDS)
            self._complete_list = []
            return None

        # Body multiline handling
        if self._is_body():
            return self._handle_body_key(key, ch)

        # Header field handling
        ed = self._current_editor()
        if ed is None:
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

    def _handle_body_key(self, key: int, ch: str) -> str | None:
        ed = self._body_lines[self._body_row]

        if key in (_ENTER, _CR):
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

        if _is_backspace(key) and ed.pos == 0 and self._body_row > 0:
            # Merge with previous line
            prev = self._body_lines[self._body_row - 1]
            merge_pos = len(prev.chars)
            prev.chars.extend(ed.chars)
            prev.pos = merge_pos
            del self._body_lines[self._body_row]
            self._body_row -= 1
            return None

        if key == curses.KEY_UP and self._body_row > 0:
            self._body_row -= 1
            return None
        if key == curses.KEY_DOWN and self._body_row < len(self._body_lines) - 1:
            self._body_row += 1
            return None
        if ch == "j" and ed.mode == "NORMAL" and (
            self._body_row < len(self._body_lines) - 1
        ):
            self._body_row += 1
            return None
        if ch == "k" and ed.mode == "NORMAL" and self._body_row > 0:
            self._body_row -= 1
            return None

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
        for acc in self._load_accounts():
            self._items.append(
                {"type": "account", "label": acc["retposto"],
                 "acc_id": acc["id"], "folder_id": None}
            )
            for fld in self._load_folders(acc["id"]):
                self._items.append(
                    {
                        "type": "folder",
                        "label": "  " + fld["nomo"],
                        "acc_id": acc["id"],
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
        if ch == "j" or key == curses.KEY_DOWN:
            self._cursor = min(self._cursor + 1, n - 1)
        elif ch == "k" or key == curses.KEY_UP:
            self._cursor = max(self._cursor - 1, 0)
        elif ch == "g":
            self._cursor = 0
        elif ch == "G":
            self._cursor = n - 1
        elif key in (_ENTER, _CR):
            return "select"
        elif ch == "R":
            self._refresh_items()
        # Adjust scroll
        h, _ = self.stdscr.getmaxyx()
        panel_h = h - 2  # rough
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
        self._search_term: str = ""

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
        self._messages = self._load_messages(
            konto_id=konto_id,
            dosierujo_id=dosierujo_id,
            spamo=spamo,
            forigita=forigita,
        )
        self._cursor = 0
        self._scroll = 0

    def selected(self) -> dict | None:
        if self._messages:
            return self._messages[min(self._cursor, len(self._messages) - 1)]
        return None

    def _visible_messages(self) -> list[dict]:
        if not self._search_term:
            return self._messages
        st = self._search_term.lower()
        return [
            m for m in self._messages
            if st in (m.get("subjekto") or "").lower()
            or st in (m.get("de") or "").lower()
        ]

    def draw(self, win: Any, focused: bool) -> None:
        h, w = win.getmaxyx()
        win.erase()

        msgs = self._visible_messages()

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
            subject = (msg.get("subjekto") or "")[:40]
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
        if self._search_term:
            count_str += f"  /{self._search_term}"
        _safe_addstr(win, h - 1, 0, count_str[:w - 1].ljust(w - 1), curses.A_DIM)

        win.noutrefresh()

    def handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""
        msgs = self._visible_messages()
        n = len(msgs)
        if n == 0:
            return None

        if ch == "j" or key == curses.KEY_DOWN:
            self._cursor = min(self._cursor + 1, n - 1)
        elif ch == "k" or key == curses.KEY_UP:
            self._cursor = max(self._cursor - 1, 0)
        elif ch == "g":
            self._cursor = 0
        elif ch == "G":
            self._cursor = n - 1
        elif key in (_ENTER, _CR):
            return "open"
        elif ch == "J":
            self._scroll = min(self._scroll + 10, max(0, n - 1))
            self._cursor = max(self._cursor, self._scroll)
        elif ch == "K":
            self._scroll = max(self._scroll - 10, 0)

        # Adjust scroll
        h, _ = self.stdscr.getmaxyx()
        panel_h = h - 3
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

    def __init__(self, stdscr: Any, msg: dict) -> None:
        self.stdscr = stdscr
        self.msg = msg
        self._lines = _message_to_lines(msg)
        self._row: int = 0
        self._col: int = 0
        self._search_term: str = ""
        self._mode: str = "NORMAL"
        self._search_buf: str = ""
        self._count_buf: str = ""
        self._prev_ch: str = ""  # for gg detection
        self._action: str | None = None  # 'reply', 'forward', 'delete', etc.

    def draw(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        content_h = h - 2

        # Title
        subj = (self.msg.get("subjekto") or "")[:w - 4]
        _safe_addstr(self.stdscr, 0, 0, f" {subj} ".ljust(w - 1), curses.A_REVERSE)

        # Content
        content_w = w - 1
        num_w = 4
        for i in range(content_h):
            li = i + self._row
            scr_row = i + 1
            if li >= len(self._lines):
                break
            line = self._lines[li]
            visible = line[self._col: self._col + content_w - num_w]

            is_match = bool(
                self._search_term
                and self._search_term.lower() in line.lower()
            )
            if li == self._row and self._mode == "NORMAL":
                attr = curses.A_UNDERLINE
            elif is_match:
                attr = curses.A_STANDOUT
            elif li < 8:  # header lines bold
                attr = curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            _safe_addstr(self.stdscr, scr_row, num_w, visible[:content_w - num_w], attr)

        # Status bar
        if self._mode == "SEARCH":
            status = f"/{self._search_buf}█"
        else:
            pfx = self._count_buf
            status = (
                f"{pfx} [NORMAL]  j/k:↕  gg/G:⇕  r:respondi  f:plusendi  "
                f"d:forigi  s:spamo  *:stelo  1-9:prioritato  q:reen"
            )
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )

        self.stdscr.refresh()

    def run(self) -> str | None:
        """Run pager loop. Returns action string or None."""
        while True:
            self.draw()
            key = _getch_unicode(self.stdscr)
            result = self._handle_key(key)
            if result is not None:
                return result

    def _handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""

        if self._mode == "SEARCH":
            return self._search_key(key, ch)

        # Count prefix
        if ch.isdigit() and ch != "0" and not self._count_buf:
            self._count_buf += ch
            return None
        if ch.isdigit() and self._count_buf:
            self._count_buf += ch
            return None

        count = int(self._count_buf) if self._count_buf else 1
        self._count_buf = ""

        n = len(self._lines)
        h, w = self.stdscr.getmaxyx()
        page_h = h - 2

        if ch == "q" or key in (_CTRL_C, _CTRL_D):
            self._prev_ch = ""
            return "quit"
        if key == _ESC:
            self._prev_ch = ""
            return None
        if ch == "j" or key == curses.KEY_DOWN:
            self._row = min(self._row + count, max(0, n - 1))
        elif ch == "k" or key == curses.KEY_UP:
            self._row = max(self._row - count, 0)
        elif ch == "g":
            if self._prev_ch == "g":
                self._row = 0  # gg — go to top
            # else: wait for second 'g'
        elif ch == "G":
            self._row = max(0, n - 1)
        elif ch == "J":
            self._row = min(self._row + page_h, max(0, n - 1))
        elif ch == "K":
            self._row = max(self._row - page_h, 0)
        elif ch == "h" or key == curses.KEY_LEFT:
            self._col = max(0, self._col - count)
        elif ch == "l" or key == curses.KEY_RIGHT:
            self._col += count
        elif ch == "0":
            self._col = 0
        elif ch == "$":
            max_len = max((len(ln) for ln in self._lines), default=0)
            self._col = max(0, max_len - w + 5)
        elif ch == "/":
            self._mode = "SEARCH"
            self._search_buf = ""
        elif ch == "n" and self._search_term:
            self._search_next(1)
        elif ch == "N" and self._search_term:
            self._search_next(-1)
        elif ch == "r":
            self._prev_ch = ""
            return "reply"
        elif ch == "f":
            self._prev_ch = ""
            return "forward"
        elif ch == "d" or key == curses.KEY_DC:
            self._prev_ch = ""
            return "delete"
        elif ch == "D":
            self._prev_ch = ""
            return "delete_perm"
        elif ch == "s":
            self._prev_ch = ""
            return "spam"
        elif ch == "*":
            self._prev_ch = ""
            return "star"
        elif ch in "123456789":
            self._prev_ch = ""
            return f"priority:{ch}"
        elif ch == "m":
            self._prev_ch = ""
            return "move"

        self._prev_ch = ch
        return None

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

        # Panels
        self._folder_panel = FolderPanel(stdscr, load_accounts, load_folders)
        self._message_panel = MessagePanel(stdscr, load_messages)

        # Focus: 'folder', 'list'
        self._focus: str = "folder"
        self._mode: str = "NORMAL"
        self._cmd_buf: str = ""
        self._status_msg: str = ""

        # Layout proportions
        self._folder_w: int = 30

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

    def run(self) -> None:
        """Main event loop."""
        curses.curs_set(0)
        try:
            import locale
            locale.setlocale(locale.LC_ALL, "")
        except Exception:
            pass

        while True:
            self._draw()
            key = _getch_unicode(self.stdscr)
            if key == -1:
                continue
            done = self._handle_key(key)
            if done:
                break

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
        elif self._mode == "SEARCH":
            status = f"/{self._cmd_buf}█"
        else:
            status = (
                self._status_msg
                or (
                    "Tab:paŝi  c:komponi  p:preni  r:respondi  "
                    "d:forigi  s:spamo  /:serĉi  h:helpo  q:eliri"
                )
            )
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )

        curses.doupdate()

    def _draw_welcome(self) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        for i, line in enumerate(_WELCOME_LINES):
            row = max(0, (h - len(_WELCOME_LINES)) // 2) + i
            if row >= h - 1:
                break
            col = max(0, (w - len(line)) // 2)
            _safe_addstr(self.stdscr, row, col, line[:w - 1], curses.A_DIM)

        if self._mode == "COMMAND":
            status = f":{self._cmd_buf}█"
        elif self._mode == "SEARCH":
            status = f"/{self._cmd_buf}█"
        else:
            status = (
                self._status_msg
                or "Neniuj kontoj. Uzu: retposto aldoni-konton  |  h:helpo  q:eliri"
            )
        _safe_addstr(
            self.stdscr, h - 1, 0, status[:w - 1].ljust(w - 1), curses.A_REVERSE
        )
        self.stdscr.refresh()

    def _handle_key(self, key: int) -> bool:
        ch = chr(key) if 0 < key < 256 else ""

        if self._mode == "COMMAND":
            return self._cmd_key(key, ch)
        if self._mode == "SEARCH":
            self._search_key(key, ch)
            return False

        # Global keys
        if ch == "q" or key in (_CTRL_C, _CTRL_D):
            return True
        if key == _ESC:
            self._status_msg = "Premu q por eliri."
            return False
        if ch == ":":
            self._mode = "COMMAND"
            self._cmd_buf = ""
            return False
        if ch == "/":
            self._mode = "SEARCH"
            self._cmd_buf = ""
            return False
        if ch == "h":
            self._show_help()
            return False

        if key == _TAB:
            self._focus = "list" if self._focus == "folder" else "folder"
            self._status_msg = ""
            return False

        if key == curses.KEY_RESIZE:
            return False

        # Panel-specific keys
        if self._focus == "folder":
            result = self._folder_panel.handle_key(key)
            if result == "select":
                sel = self._folder_panel.selected()
                if sel:
                    folder_label = (sel.get("label") or "").strip().lower()
                    spamo = folder_label in ("spam", "junk")
                    self._message_panel.load(
                        konto_id=sel["acc_id"],
                        dosierujo_id=sel["folder_id"],
                        spamo=spamo,
                    )
                    self._focus = "list"
        else:
            # List panel keys
            result = self._message_panel.handle_key(key)
            if result == "open":
                self._open_message()
                return False

            # Action keys in list mode
            if ch == "c":
                self._compose_new()
            elif ch == "r":
                self._compose_reply()
            elif ch == "f":
                self._compose_forward()
            elif ch == "d":
                self._action_delete()
            elif ch == "D":
                self._action_delete(permanent=True)
            elif ch == "s":
                self._action_spam()
            elif ch == "*":
                self._action_star()
            elif ch == "p":
                self._action_fetch()
            elif ch == "m":
                self._action_move()
            elif ch in "123456789":
                self._action_priority(int(ch))

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
        if cmd in ("h", "helpo"):
            self._show_help()
        elif cmd == "p" or cmd.startswith("preni"):
            self._action_fetch()
        elif cmd == "c" or cmd == "komponi":
            self._compose_new()
        elif cmd == "konto" or cmd == "kontoj":
            self._show_accounts()
        elif cmd == "kontakto" or cmd.startswith("kontaktoj"):
            self._show_contacts()
        elif cmd.startswith("bloki "):
            rule = cmd[6:].strip()
            self._add_spam_block(rule)
            self._status_msg = f"Blokita: {rule}"
        elif cmd.startswith("malbloki "):
            rule = cmd[9:].strip()
            # We'd need a remove_spam_block callback; for now show hint
            self._status_msg = f"Uzu CLI: retposto malbloki {rule}"
        else:
            self._status_msg = f"Nekonata komando: :{cmd}"
        return False

    def _search_key(self, key: int, ch: str) -> None:
        if key in (_ENTER, _CR):
            term = self._cmd_buf.strip()
            self._mode = "NORMAL"
            self._cmd_buf = ""
            self._message_panel._search_term = term
        elif _is_backspace(key):
            if self._cmd_buf:
                self._cmd_buf = self._cmd_buf[:-1]
            else:
                self._mode = "NORMAL"
                self._message_panel._search_term = ""
        elif key == _ESC:
            self._mode = "NORMAL"
            self._cmd_buf = ""
            self._message_panel._search_term = ""
        elif ch and ch.isprintable():
            self._cmd_buf += ch

    # ── actions ──────────────────────────────────────────────────────────────

    def _open_message(self) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        # Mark as read
        if not msg.get("legita"):
            self._update_message_field(msg["id"], legita=1)
            msg["legita"] = 1

        reader = MessageReader(self.stdscr, msg)
        result = reader.run()
        curses.curs_set(0)

        if result == "reply":
            self._compose_reply(msg)
        elif result == "forward":
            self._compose_forward(msg)
        elif result == "delete":
            self._delete_message(msg["id"], False)
            self._status_msg = "Sendita al rubujo."
            self._refresh_list()
        elif result == "delete_perm":
            self._delete_message(msg["id"], True)
            self._status_msg = "Definitive forigita."
            self._refresh_list()
        elif result == "spam":
            self._mark_spam(msg)
        elif result == "star":
            self._toggle_star(msg)
        elif result and result.startswith("priority:"):
            p = int(result.split(":")[1])
            self._update_message_field(msg["id"], prioritato=p)
            self._status_msg = f"Prioritato: {p}"
            self._refresh_list()

    def _compose_new(self) -> None:
        self._run_compose({})

    def _compose_reply(self, msg: dict | None = None) -> None:
        if msg is None:
            msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return
        body_quote = "\n".join(
            "> " + line for line in (msg.get("korpo") or "").split("\n")
        )
        self._run_compose({
            "al": msg.get("de") or "",
            "subjekto": "Re: " + (msg.get("subjekto") or ""),
            "korpo": f"\n\n--- Originala mesaĝo ---\n{body_quote}",
        })

    def _compose_forward(self, msg: dict | None = None) -> None:
        if msg is None:
            msg = self._message_panel.selected()
        if not msg:
            self._status_msg = "Neniu elektita mesaĝo."
            return
        body_fwd = "\n".join(
            "> " + line for line in (msg.get("korpo") or "").split("\n")
        )
        self._run_compose({
            "subjekto": "Fwd: " + (msg.get("subjekto") or ""),
            "korpo": f"\n\n--- Plusendita mesaĝo ---\n{body_fwd}",
        })

    def _run_compose(self, initial: dict[str, str]) -> None:
        accounts = self._load_accounts()
        if not accounts:
            self._status_msg = "Neniuj kontoj. Uzu: retposto aldoni-konton"
            return

        acc = accounts[0]

        def _completer(partial: str) -> list[str]:
            return [
                c["retposto"] for c in self._find_contact(partial)
            ]

        panel = ComposePanel(self.stdscr, initial, _completer)
        while True:
            panel.draw()
            key = _getch_unicode(self.stdscr)
            result = panel.handle_key(key)
            if result == "cancel":
                self._status_msg = "Nuligita."
                return
            if result == "send":
                vals = panel.get_values()
                al_list = [a.strip() for a in vals["al"].split(",") if a.strip()]
                cc_list = [a.strip() for a in vals["cc"].split(",") if a.strip()]
                bcc_list = [a.strip() for a in vals["bcc"].split(",") if a.strip()]
                if not al_list:
                    panel._status = "[!] Aldonu ricevonton (campo 'Al')"
                    continue
                if not vals["subjekto"]:
                    if not self._prompt_confirm_inline(
                        "Neniu subjekto. Ĉu sendi? (j/N)"
                    ):
                        continue
                ok = self._send_message(
                    acc, al_list, vals["subjekto"],
                    vals["korpo"], cc_list, bcc_list
                )
                if ok:
                    self._status_msg = f"Sendita al: {', '.join(al_list)}"
                else:
                    self._status_msg = "[!] Eraro dum sendado."
                return

    def _action_delete(self, permanent: bool = False) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        label = "definitive forigi" if permanent else "forigi"
        if self._prompt_confirm_inline(f"{label} ĉi tiun mesaĝon? (j/N)"):
            self._delete_message(msg["id"], permanent)
            self._status_msg = "Forigita."
            self._refresh_list()
        else:
            self._status_msg = "Nuligita."

    def _action_spam(self) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        sender = msg.get("de") or ""
        self._add_spam_block(sender)
        self._update_message_field(msg["id"], spamo=1)
        msg["spamo"] = 1
        self._status_msg = f"Blokita kiel spamo: {sender}"
        self._refresh_list()

    def _mark_spam(self, msg: dict) -> None:
        sender = msg.get("de") or ""
        self._add_spam_block(sender)
        self._update_message_field(msg["id"], spamo=1)
        self._status_msg = f"Markita kiel spamo: {sender}"
        self._refresh_list()

    def _toggle_star(self, msg: dict) -> None:
        new_val = 0 if msg.get("stelo") else 1
        self._update_message_field(msg["id"], stelo=new_val)
        msg["stelo"] = new_val
        self._status_msg = "★ Markita." if new_val else "★ Malmarkita."

    def _action_star(self) -> None:
        msg = self._message_panel.selected()
        if msg:
            self._toggle_star(msg)

    def _action_priority(self, p: int) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        self._update_message_field(msg["id"], prioritato=p)
        self._status_msg = f"Prioritato: {p}"
        self._refresh_list()

    def _action_move(self) -> None:
        msg = self._message_panel.selected()
        if not msg:
            return
        folder_name = self._prompt_inline("Movi al dosierujo")
        if not folder_name:
            self._status_msg = "Nuligita."
            return
        folder_id = self._ensure_folder(
            msg["konto_id"], folder_name, folder_name
        )
        self._update_message_field(msg["id"], dosierujo_id=folder_id)
        self._status_msg = f"Movita al: {folder_name}"
        self._folder_panel._refresh_items()
        self._refresh_list()

    def _action_fetch(self) -> None:
        accounts = self._load_accounts()
        if not accounts:
            self._status_msg = "[!] Neniuj kontoj konfiguritaj."
            return
        self._status_msg = "Prenante poŝton…"
        self._draw()
        total = 0
        for acc in accounts:
            f, _ = self._fetch_account_mail(acc, 100)
            total += f
        self._status_msg = f"[✓] {total} nova(j) mesaĝo(j)."
        self._folder_panel._refresh_items()
        self._refresh_list()

    def _refresh_list(self) -> None:
        sel = self._folder_panel.selected()
        if sel:
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
        else:
            lines = ["  ID  Retpoŝto                    IMAP                SMTP", ""]
            for a in accounts:
                lines.append(
                    f"  {a['id']:<3} {a['retposto']:<30} "
                    f"{a['imap_servilo']:<20} {a['smtp_servilo']}"
                )
        self._run_pager_lines(lines, "Kontoj")

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
                " j/k:↕  q:reen ".ljust(w - 1), curses.A_REVERSE
            )
            self.stdscr.refresh()
            key = _getch_unicode(self.stdscr)
            ch = chr(key) if 0 < key < 256 else ""
            if ch == "q" or key in (_ESC, _CTRL_C, _CTRL_D):
                break
            if ch == "j" or key == curses.KEY_DOWN:
                row = min(row + 1, max(0, len(lines) - h + 2))
            elif ch == "k" or key == curses.KEY_UP:
                row = max(row - 1, 0)
            elif ch == "G":
                row = max(0, len(lines) - h + 2)
            elif ch == "g":
                row = 0

    # ── inline prompts ────────────────────────────────────────────────────────

    def _prompt_inline(self, prompt: str) -> str:
        buf = ""
        curses.curs_set(1)
        while True:
            self._draw()
            h, w = self.stdscr.getmaxyx()
            line = f"{prompt}: {buf}█"
            _safe_addstr(
                self.stdscr, h - 1, 0, line[:w - 1].ljust(w - 1), curses.A_REVERSE
            )
            self.stdscr.refresh()
            key = _getch_unicode(self.stdscr)
            ch = chr(key) if 0 < key < 256 else ""
            if key in (_ENTER, _CR):
                curses.curs_set(0)
                return buf.strip()
            if key == _ESC or key in (_CTRL_C, _CTRL_D):
                curses.curs_set(0)
                return ""
            if _is_backspace(key):
                buf = buf[:-1]
            elif ch and ch.isprintable():
                buf += ch

    def _prompt_confirm_inline(self, prompt: str) -> bool:
        h, w = self.stdscr.getmaxyx()
        _safe_addstr(
            self.stdscr, h - 1, 0, prompt[:w - 1].ljust(w - 1), curses.A_REVERSE
        )
        self.stdscr.refresh()
        key = _getch_unicode(self.stdscr)
        ch = chr(key) if 0 < key < 256 else ""
        return ch in ("j", "y", "Y")
