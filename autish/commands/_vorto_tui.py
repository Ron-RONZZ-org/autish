"""_vorto_tui.py — Curses-based full-screen TUI for Mia Vorto.

Architecture
────────────
  VortoTUI       Main controller; owns the curses stdscr, dispatches to sub-screens.
  Pager          Scrollable read-only viewer with Vim-style navigation.
  FormEditor     Table-style data-entry form; each row uses a LineEditor.
  LineEditor     Single-line Vim-style text editor (normal/insert/visual modes).

Modes (VortoTUI level)
──────────────────────
  NORMAL   Welcome screen; single-key actions a v m s f h q.
  COMMAND  Bottom-line :cmd — execute on Enter, backspace removes : to exit.
  SEARCH   Bottom-line /query — execute on Enter, backspace / to exit → serci.
"""

from __future__ import annotations

import curses
import locale
from collections.abc import Callable

# ──────────────────────────────────────────────────────────────────────────────
# Key constants
# ──────────────────────────────────────────────────────────────────────────────

_ESC = 27
_ENTER = ord("\n")
_CR = ord("\r")
_CTRL_C = 3
_CTRL_D = 4
_CTRL_H = 8   # legacy backspace in some terminals
_CTRL_R = 18  # Ctrl+R (redo / paste-register in insert)


def _is_backspace(key: int) -> bool:
    return key in (curses.KEY_BACKSPACE, 127, _CTRL_H)


# ──────────────────────────────────────────────────────────────────────────────
# LineEditor — single-line Vim-style text field
# ──────────────────────────────────────────────────────────────────────────────

class LineEditor:
    """Single-line Vim-style text editor embedded in the form.

    Modes: INSERT (default for form), NORMAL, VISUAL.
    Normal motions: h l w e b 0 $
    Normal operators: x  d{d w $ e b 0}  y{y w $ e}  c{w $ e}  r<char>  p P
    Visual: extend with h l w e b 0 $; y yank; d/x cut.
    Insert: type, Backspace, arrows, Ctrl+R+register for paste.
    """

    def __init__(self, text: str = "", insert_on_start: bool = True) -> None:
        self.buf: list[str] = list(text)
        self.pos: int = len(self.buf) if insert_on_start else 0
        self.mode: str = "INSERT" if insert_on_start else "NORMAL"
        self.register: str = ""
        self.visual_start: int = 0
        self._count_buf: str = ""
        self._pending_op: str | None = None
        self._pending_count: int = 1
        self._dirty: bool = False

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return "".join(self.buf)

    @text.setter
    def text(self, value: str) -> None:
        self.buf = list(value)
        self.pos = len(self.buf)
        self._dirty = False

    # ── cursor helpers ───────────────────────────────────────────────────────

    def _clamp(self) -> None:
        n = len(self.buf)
        if self.mode == "INSERT":
            self.pos = max(0, min(self.pos, n))
        else:
            self.pos = max(0, min(self.pos, n - 1)) if n else 0

    def _word_fwd(self, p: int) -> int:
        n = len(self.buf)
        if p >= n - 1:
            return max(0, n - 1)
        while p < n and not self.buf[p].isspace():
            p += 1
        while p < n and self.buf[p].isspace():
            p += 1
        return min(p, max(0, n - 1))

    def _word_end(self, p: int) -> int:
        n = len(self.buf)
        if p >= n - 1:
            return max(0, n - 1)
        if p < n - 1 and not self.buf[p].isspace():
            p += 1
        while p < n and self.buf[p].isspace():
            p += 1
        while p < n - 1 and not self.buf[p + 1].isspace():
            p += 1
        return p

    def _word_back(self, p: int) -> int:
        if p <= 0:
            return 0
        p -= 1
        while p > 0 and self.buf[p].isspace():
            p -= 1
        while p > 0 and not self.buf[p - 1].isspace():
            p -= 1
        return p

    def _visual_range(self) -> tuple[int, int]:
        return min(self.visual_start, self.pos), max(self.visual_start, self.pos) + 1

    # ── key dispatch ─────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> str | None:
        """Process one keypress.  Returns None=continue, 'done', 'cancel'."""
        ch = chr(key) if 0 < key < 256 else ""
        if self.mode == "INSERT":
            return self._insert(key, ch)
        if self.mode == "VISUAL":
            return self._visual(key, ch)
        return self._normal(key, ch)

    # ── insert mode ──────────────────────────────────────────────────────────

    def _insert(self, key: int, ch: str) -> str | None:
        if key == _ESC:
            self.mode = "NORMAL"
            self.pos = max(0, self.pos - 1)
            self._clamp()
        elif key in (_ENTER, _CR):
            return "done"
        elif _is_backspace(key):
            if self.pos > 0:
                del self.buf[self.pos - 1]
                self.pos -= 1
                self._dirty = True
        elif key == curses.KEY_DC:
            if self.pos < len(self.buf):
                del self.buf[self.pos]
                self._dirty = True
        elif key == curses.KEY_LEFT:
            self.pos = max(0, self.pos - 1)
        elif key == curses.KEY_RIGHT:
            self.pos = min(len(self.buf), self.pos + 1)
        elif key == curses.KEY_HOME:
            self.pos = 0
        elif key == curses.KEY_END:
            self.pos = len(self.buf)
        elif ch and ch.isprintable():
            self.buf.insert(self.pos, ch)
            self.pos += 1
            self._dirty = True
        return None

    # ── normal mode ──────────────────────────────────────────────────────────

    def _normal(self, key: int, ch: str) -> str | None:
        if self._pending_op:
            return self._apply_pending(key, ch)

        # Count accumulation (but '0' alone is a motion)
        if ch.isdigit() and (ch != "0" or self._count_buf):
            self._count_buf += ch
            return None

        count = int(self._count_buf) if self._count_buf else 1
        self._count_buf = ""

        # Mode switches
        if ch == "i":
            self.mode = "INSERT"
        elif ch == "a":
            self.mode = "INSERT"
            if self.buf:
                self.pos += 1
            self._clamp()
        elif ch == "I":
            self.mode = "INSERT"
            self.pos = 0
        elif ch == "A":
            self.mode = "INSERT"
            self.pos = len(self.buf)
        elif ch == "v":
            self.mode = "VISUAL"
            self.visual_start = self.pos

        # Motions
        elif ch == "h" or key == curses.KEY_LEFT:
            self.pos = max(0, self.pos - count)
        elif ch == "l" or key == curses.KEY_RIGHT:
            if self.buf:
                self.pos = min(max(0, len(self.buf) - 1), self.pos + count)
            else:
                self.pos = 0
        elif ch == "0" or key == curses.KEY_HOME:
            self.pos = 0
        elif ch == "$" or key == curses.KEY_END:
            self.pos = max(0, len(self.buf) - 1)
        elif ch == "w":
            for _ in range(count):
                self.pos = self._word_fwd(self.pos)
            self._clamp()
        elif ch == "e":
            for _ in range(count):
                self.pos = self._word_end(self.pos)
        elif ch == "b":
            for _ in range(count):
                self.pos = self._word_back(self.pos)

        # Single-char operators
        elif ch == "x":
            for _ in range(count):
                if self.buf and self.pos < len(self.buf):
                    del self.buf[self.pos]
            self._clamp()
            self._dirty = True
        elif ch == "~":
            if self.buf and self.pos < len(self.buf):
                c = self.buf[self.pos]
                self.buf[self.pos] = c.upper() if c.islower() else c.lower()
                self.pos = min(self.pos + 1, max(0, len(self.buf) - 1))
                self._dirty = True

        # Pending operators (d, y, c, r)
        elif ch in ("d", "y", "c"):
            self._pending_op = ch
            self._pending_count = count
        elif ch == "r":
            self._pending_op = "r"
            self._pending_count = count

        # Paste
        elif ch == "p":
            if self.register:
                for i, c in enumerate(self.register):
                    self.buf.insert(self.pos + 1 + i, c)
                self.pos += len(self.register)
                self._clamp()
                self._dirty = True
        elif ch == "P":
            if self.register:
                for i, c in enumerate(self.register):
                    self.buf.insert(self.pos + i, c)
                self._clamp()
                self._dirty = True

        self._clamp()
        return None

    def _apply_pending(self, key: int, ch: str) -> str | None:
        op = self._pending_op
        base_count = self._pending_count

        # Additional count after operator (e.g. d2w)
        if ch.isdigit() and ch != "0":
            self._count_buf += ch
            return None  # keep pending

        sub = int(self._count_buf) if self._count_buf else 1
        count = base_count * sub
        self._count_buf = ""
        self._pending_op = None
        self._pending_count = 1

        if op == "r":
            # replace current char with ch
            if ch and ch.isprintable() and self.buf and self.pos < len(self.buf):
                for _ in range(count):
                    if self.pos + _ < len(self.buf):
                        self.buf[self.pos + _] = ch
                self._dirty = True
            return None

        # Compute the affected range
        start, end = self._motion_range(op, ch, count)
        if start is None:
            return None

        if op in ("d", "c"):
            self.register = "".join(self.buf[start:end])
            del self.buf[start:end]
            self.pos = min(start, max(0, len(self.buf) - 1))
            self._dirty = True
            if op == "c":
                self.mode = "INSERT"
        elif op == "y":
            self.register = "".join(self.buf[start:end])
            try:
                import pyperclip  # noqa: PLC0415
                pyperclip.copy(self.register)
            except Exception:
                pass

        self._clamp()
        return None

    def _motion_range(
        self, op: str, ch: str, count: int
    ) -> tuple[int | None, int | None]:
        """Return (start, end) slice for the given motion key."""
        p = self.pos
        n = len(self.buf)

        if ch == "d" and op == "d":   # dd — whole field
            return 0, n
        if ch == "w":
            end = p
            for _ in range(count):
                end = self._word_fwd(end)
            return p, end
        if ch == "e":
            end = p
            for _ in range(count):
                end = self._word_end(end)
            return p, end + 1
        if ch == "b":
            start = p
            for _ in range(count):
                start = self._word_back(start)
            return start, p
        if ch == "$":
            return p, n
        if ch == "0":
            return 0, p
        if ch == "y" and op == "y":   # yy — whole field
            return 0, n
        return None, None

    # ── visual mode ──────────────────────────────────────────────────────────

    def _visual(self, key: int, ch: str) -> str | None:
        if key == _ESC or ch == "v":
            self.mode = "NORMAL"
        elif ch == "h" or key == curses.KEY_LEFT:
            self.pos = max(0, self.pos - 1)
        elif ch == "l" or key == curses.KEY_RIGHT:
            self.pos = min(max(0, len(self.buf) - 1), self.pos + 1) if self.buf else 0
        elif ch == "0" or key == curses.KEY_HOME:
            self.pos = 0
        elif ch == "$" or key == curses.KEY_END:
            self.pos = max(0, len(self.buf) - 1)
        elif ch == "w":
            self.pos = self._word_fwd(self.pos)
            self._clamp()
        elif ch == "e":
            self.pos = self._word_end(self.pos)
        elif ch == "b":
            self.pos = self._word_back(self.pos)
        elif ch == "y":
            s, e = self._visual_range()
            self.register = "".join(self.buf[s:e])
            try:
                import pyperclip  # noqa: PLC0415
                pyperclip.copy(self.register)
            except Exception:
                pass
            self.mode = "NORMAL"
        elif ch in ("d", "x"):
            s, e = self._visual_range()
            self.register = "".join(self.buf[s:e])
            del self.buf[s:e]
            self.pos = min(s, max(0, len(self.buf) - 1))
            self.mode = "NORMAL"
            self._dirty = True
        return None

    # ── rendering ────────────────────────────────────────────────────────────

    def render(
        self, win, row: int, col: int, width: int, focused: bool = False
    ) -> None:
        """Draw the field text at (row, col) inside *win*."""
        text = self.text
        # Scroll view horizontally to keep cursor visible
        if self.pos >= col + width:
            view_start = self.pos - width + 1
        elif self.pos < col:
            view_start = self.pos
        else:
            view_start = max(0, self.pos - width + 1) if self.pos >= width else 0

        displayed = text[view_start : view_start + width].ljust(width)[:width]

        if focused:
            attr = curses.A_UNDERLINE if self.mode == "INSERT" else (
                curses.A_STANDOUT if self.mode == "VISUAL" else curses.A_BOLD
            )
        else:
            attr = curses.A_NORMAL

        try:
            win.addstr(row, col, displayed, attr)
        except curses.error:
            pass

        if focused:
            cursor_col = col + min(self.pos - view_start, width - 1)
            try:
                win.move(row, cursor_col)
            except curses.error:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# FormEditor — table-style multi-field data entry
# ──────────────────────────────────────────────────────────────────────────────

_FORM_FIELDS = [
    ("teksto",     "Teksto (vorto/frazo)"),
    ("lingvo",     "Lingvo (eo/en/…)"),
    ("difinoj",    "Difino(j) — sep: ;"),
    ("tipo",       "Tipo (su/ve/aj/av/…)"),
    ("temo",       "Temo"),
    ("tono",       "Tono (in/fo/am)"),
    ("nivelo",     "Nivelo 1–10"),
    ("etikedoj",   "Etikedoj KEY:VAL …"),
    ("ligiloj",    "Ligiloj (UUID …)"),
]


class FormEditor:
    """Full-screen table-style form with per-field LineEditor.

    Returns a dict of field values on :wq, or None on :q / Esc.
    """

    def __init__(
        self, stdscr, title: str = "Aldoni", initial: dict | None = None
    ) -> None:
        self.stdscr = stdscr
        self.title = title
        self.current_row = 0
        # Build LineEditor for each field
        init = initial or {}

        def _init_val(key: str) -> str:
            v = init.get(key)
            if v is None:
                return ""
            if isinstance(v, list):
                return "; ".join(str(x) for x in v)
            if isinstance(v, dict):
                return " ".join(f"{k}:{val}" for k, val in v.items())
            return str(v)

        self.editors: list[LineEditor] = [
            LineEditor(_init_val(k), insert_on_start=True) for k, _ in _FORM_FIELDS
        ]
        self._cmd_buf: str = ""
        self._mode: str = "FIELD"  # FIELD | CMD
        self._status_msg: str = (
            "j/k: kurentaj kampoj  i/a: enmeti  :wq konservi  :q forĵeti  ^H helpo"
        )

    # ── run ─────────────────────────────────────────────────────────────────

    def run(self) -> dict | None:
        """Block until the user saves (:wq) or discards (:q).

        Returns values dict or None.
        """
        curses.curs_set(1)
        while True:
            self._render()
            key = self.stdscr.getch()
            result = self._handle_key(key)
            if result == "save":
                curses.curs_set(0)
                return self._collect()
            if result == "discard":
                curses.curs_set(0)
                return None

    # ── key handling ─────────────────────────────────────────────────────────

    def _handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""

        if self._mode == "CMD":
            return self._cmd_key(key, ch)

        # Global shortcuts (only in FIELD / NORMAL mode of current editor)
        editor = self.editors[self.current_row]

        # Enter cmd mode from any mode via ':'
        if ch == ":" and editor.mode == "NORMAL":
            self._mode = "CMD"
            self._cmd_buf = ""
            return None

        if key in (_CTRL_C, _CTRL_D):
            self._status_msg = "Uzu  :q  por forĵeti aŭ  :wq  por konservi."
            return None

        # Navigate between fields with j/k when field editor is in NORMAL mode
        if editor.mode == "NORMAL":
            if ch == "j" or key == curses.KEY_DOWN:
                self.current_row = min(len(self.editors) - 1, self.current_row + 1)
                return None
            if ch == "k" or key == curses.KEY_UP:
                self.current_row = max(0, self.current_row - 1)
                return None
            if key == _ESC:
                self._status_msg = "Uzu  :wq  por konservi aŭ  :q  por forĵeti."
                return None

        # Delegate keypress to the current field editor
        res = editor.handle_key(key)
        if res == "done":
            # Enter pressed in insert mode → move to next field
            self.current_row = min(len(self.editors) - 1, self.current_row + 1)
            self.editors[self.current_row].mode = "INSERT"
            self.editors[self.current_row].pos = len(self.editors[self.current_row].buf)

        return None

    def _cmd_key(self, key: int, ch: str) -> str | None:
        if key in (_ENTER, _CR):
            cmd = self._cmd_buf.strip()
            self._mode = "FIELD"
            self._cmd_buf = ""
            if cmd in ("wq", "w"):
                return "save"
            if cmd in ("q", "q!", "quit"):
                return "discard"
            self._status_msg = f"Nekonata komando: :{cmd}   (uzu :wq aŭ :q)"
        elif _is_backspace(key):
            if self._cmd_buf:
                self._cmd_buf = self._cmd_buf[:-1]
            else:
                self._mode = "FIELD"  # deleted the leading ':'
        elif key == _ESC:
            self._mode = "FIELD"
            self._cmd_buf = ""
        elif ch and ch.isprintable():
            self._cmd_buf += ch
        return None

    # ── collect results ──────────────────────────────────────────────────────

    def _collect(self) -> dict:
        vals: dict = {}
        for (key, _), editor in zip(_FORM_FIELDS, self.editors, strict=False):
            raw = editor.text.strip()
            if key == "difinoj":
                vals[key] = [s.strip() for s in raw.split(";") if s.strip()]
            elif key == "etikedoj":
                d: dict[str, str] = {}
                for item in raw.split():
                    k, _, v = item.partition(":")
                    d[k.strip()] = v.strip()
                vals[key] = d
            elif key == "ligiloj":
                vals[key] = [s.strip() for s in raw.split() if s.strip()]
            elif key == "nivelo":
                try:
                    vals[key] = float(raw) if raw else None
                except ValueError:
                    vals[key] = None
            else:
                vals[key] = raw or None
        return vals

    # ── rendering ────────────────────────────────────────────────────────────

    def _render(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # ── title bar ────────────────────────────────────────────────────
        title_line = f" {self.title} "[:w - 1].ljust(w - 1)
        try:
            self.stdscr.addstr(0, 0, title_line, curses.A_REVERSE)
        except curses.error:
            pass

        # ── table ────────────────────────────────────────────────────────
        label_w = 20
        sep = " │ "
        value_w = max(10, w - label_w - len(sep) - 1)

        # Top border
        border = "─" * label_w + "─┼─" + "─" * value_w
        try:
            self.stdscr.addstr(1, 0, border[:w - 1], curses.A_DIM)
        except curses.error:
            pass

        for i, ((_key, hint), editor) in enumerate(
            zip(_FORM_FIELDS, self.editors, strict=False)
        ):
            scr_row = 2 + i * 2
            if scr_row >= h - 3:
                break
            focused = i == self.current_row

            # Label
            label_text = hint[:label_w].ljust(label_w)
            label_attr = curses.A_BOLD if focused else curses.A_DIM
            try:
                self.stdscr.addstr(scr_row, 0, label_text, label_attr)
                self.stdscr.addstr(scr_row, label_w, sep, curses.A_DIM)
            except curses.error:
                pass

            # Value via LineEditor
            editor.render(self.stdscr, scr_row, label_w + len(sep), value_w, focused)

            # Row separator
            if scr_row + 1 < h - 3:
                try:
                    self.stdscr.addstr(scr_row + 1, 0, border[:w - 1], curses.A_DIM)
                except curses.error:
                    pass

        # ── status / command line ─────────────────────────────────────────
        if self._mode == "CMD":
            status = f":{self._cmd_buf}"
        else:
            ed = self.editors[self.current_row]
            mode_tag = f"[{ed.mode}]"
            status = f"{mode_tag}  {self._status_msg}"

        try:
            status_line = status[:w - 1].ljust(w - 1)
            self.stdscr.addstr(h - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        self.stdscr.refresh()


# ──────────────────────────────────────────────────────────────────────────────
# Pager — scrollable read-only viewer with Vim navigation
# ──────────────────────────────────────────────────────────────────────────────

class Pager:
    """Full-screen scrollable viewer with Vim-style navigation.

    Navigation: j k h l   with optional numeric count prefix.
    Jumps: gg G  {N}G
    Line edges: 0 $
    Search: /term  n N
    Visual: v  then y to yank, Esc/v to exit.
    Yank line: y (normal mode).
    Exit: q Esc.
    """

    _NUM_W = 5  # width of the line-number gutter  ("NNN  ")

    def __init__(self, stdscr, lines: list[str], title: str = "") -> None:
        self.stdscr = stdscr
        self.lines = lines or [""]
        self.title = title
        self.row = 0          # cursor line (absolute)
        self.col = 0          # horizontal scroll offset
        self.scroll_top = 0   # first visible line
        self._count_buf = ""
        self._mode = "NORMAL"   # NORMAL | SEARCH | VISUAL
        self.search_term = ""
        self.search_matches: list[int] = []
        self.search_match_idx = 0
        self._visual_start = 0
        self._status = ""

    # ── run ─────────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Block until exit.  Returns 'back' or 'quit'."""
        curses.curs_set(0)
        while True:
            self._render()
            result = self._handle_key(self.stdscr.getch())
            if result:
                return result

    # ── geometry ─────────────────────────────────────────────────────────────

    def _geom(self) -> tuple[int, int, int, int]:
        h, w = self.stdscr.getmaxyx()
        content_h = h - 2   # title bar + status bar
        content_w = w - self._NUM_W
        return h, w, content_h, content_w

    # ── rendering ────────────────────────────────────────────────────────────

    def _render(self) -> None:
        self.stdscr.erase()
        h, w, content_h, content_w = self._geom()

        # Clamp
        self.row = max(0, min(self.row, len(self.lines) - 1))

        # Adjust vertical scroll
        if self.row < self.scroll_top:
            self.scroll_top = self.row
        elif self.row >= self.scroll_top + content_h:
            self.scroll_top = self.row - content_h + 1

        # Title bar
        title = f" {self.title} "[:w - 1].ljust(w - 1)
        try:
            self.stdscr.addstr(0, 0, title, curses.A_REVERSE)
        except curses.error:
            pass

        # Content + line numbers
        for sr in range(content_h):
            li = self.scroll_top + sr
            scr_r = sr + 1
            if li >= len(self.lines):
                try:
                    self.stdscr.addstr(scr_r, 0, "~".ljust(self._NUM_W), curses.A_DIM)
                except curses.error:
                    pass
                continue

            # Relative line number
            rel = li - self.row
            if rel == 0:
                num_str = f"{li + 1:>{self._NUM_W - 1}} "
                num_attr = curses.A_BOLD
            else:
                num_str = f"{abs(rel):>{self._NUM_W - 1}} "
                num_attr = curses.A_DIM
            try:
                self.stdscr.addstr(scr_r, 0, num_str, num_attr)
            except curses.error:
                pass

            # Line content (with horizontal scroll)
            line = self.lines[li]
            visible = line[self.col : self.col + content_w]
            visible = visible.ljust(content_w)[:content_w]

            is_current = li == self.row
            in_visual = (
                self._mode == "VISUAL"
                and min(self._visual_start, self.row)
                <= li
                <= max(self._visual_start, self.row)
            )
            has_match = bool(
                self.search_term and self.search_term.lower() in line.lower()
            )

            if in_visual:
                attr = curses.A_STANDOUT
            elif is_current:
                attr = curses.A_UNDERLINE | curses.A_BOLD
            elif has_match:
                attr = curses.A_STANDOUT
            else:
                attr = curses.A_NORMAL

            try:
                self.stdscr.addstr(scr_r, self._NUM_W, visible, attr)
            except curses.error:
                pass

        # Status bar
        if self._mode == "SEARCH":
            status = f"/{self.search_term}█"
        elif self._mode == "VISUAL":
            status = "-- VISUAL --   y:yank   d:forigu   v/Esc: eliri elektan reĝimon"
        else:
            pfx = self._count_buf or ""
            status = (
                f"{pfx} [NORMAL]  "
                f"j/k:↕  h/l:↔  0/$:↔linio  gg/G:⇕  "
                f"/:serĉi  n/N:sekva  v:elekta  y:yank  q:reen"
            )

        try:
            status_line = status[:w - 1].ljust(w - 1)
            self.stdscr.addstr(h - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        self.stdscr.refresh()

    # ── key handling ─────────────────────────────────────────────────────────

    def _handle_key(self, key: int) -> str | None:
        ch = chr(key) if 0 < key < 256 else ""
        if self._mode == "SEARCH":
            return self._search_key(key, ch)
        if self._mode == "VISUAL":
            return self._visual_key(key, ch)
        return self._normal_key(key, ch)

    def _normal_key(self, key: int, ch: str) -> str | None:
        # Count accumulation
        if ch.isdigit() and (ch != "0" or self._count_buf):
            self._count_buf += ch
            return None

        count = int(self._count_buf) if self._count_buf else 1
        self._count_buf = ""

        h, w, content_h, content_w = self._geom()
        n = len(self.lines)

        if key == _ESC or ch == "q":
            return "back"
        if key in (_CTRL_C, _CTRL_D):
            return "quit"

        elif ch == "j" or key == curses.KEY_DOWN:
            self.row = min(n - 1, self.row + count)
        elif ch == "k" or key == curses.KEY_UP:
            self.row = max(0, self.row - count)
        elif ch == "h" or key == curses.KEY_LEFT:
            self.col = max(0, self.col - count)
        elif ch == "l" or key == curses.KEY_RIGHT:
            self.col += count
        elif ch == "0" or key == curses.KEY_HOME:
            self.col = 0
        elif ch == "$" or key == curses.KEY_END:
            max_len = max((len(ln) for ln in self.lines), default=0)
            self.col = max(0, max_len - content_w)

        elif ch == "G":
            if self._count_buf == "" and count == 1:
                # bare G → bottom
                self.row = n - 1
            else:
                # {N}G → go to line N (1-based)
                self.row = max(0, min(count - 1, n - 1))

        elif ch == "g":
            # Wait for second key to form 'gg'
            next_key = self.stdscr.getch()
            if chr(next_key) == "g":
                self.row = 0
                self.scroll_top = 0

        elif ch == "d":
            # d = scroll down half page (vi pager convention)
            self.row = min(n - 1, self.row + content_h // 2)
        elif key == curses.KEY_NPAGE:
            self.row = min(n - 1, self.row + content_h)
        elif key == curses.KEY_PPAGE:
            self.row = max(0, self.row - content_h)

        elif ch == "/":
            self._mode = "SEARCH"
            self.search_term = ""
        elif ch == "n":
            self._next_match(forward=True)
        elif ch == "N":
            self._next_match(forward=False)

        elif ch == "v":
            self._mode = "VISUAL"
            self._visual_start = self.row

        elif ch == "y":
            self._yank([self.lines[self.row]])

        return None

    def _search_key(self, key: int, ch: str) -> str | None:
        if key in (_ENTER, _CR):
            self._do_search()
            self._mode = "NORMAL"
            self._next_match(forward=True)
        elif key == _ESC:
            self.search_term = ""
            self._mode = "NORMAL"
        elif _is_backspace(key):
            if self.search_term:
                self.search_term = self.search_term[:-1]
            else:
                self._mode = "NORMAL"  # deleted leading '/'
        elif ch and ch.isprintable():
            self.search_term += ch
        return None

    def _visual_key(self, key: int, ch: str) -> str | None:
        if key == _ESC or ch == "v":
            self._mode = "NORMAL"
        elif ch == "j" or key == curses.KEY_DOWN:
            self.row = min(len(self.lines) - 1, self.row + 1)
        elif ch == "k" or key == curses.KEY_UP:
            self.row = max(0, self.row - 1)
        elif ch == "y":
            s = min(self._visual_start, self.row)
            e = max(self._visual_start, self.row)
            self._yank(self.lines[s : e + 1])
            self._mode = "NORMAL"
        elif ch == "q" or key == _ESC:
            return "back"
        return None

    def _do_search(self) -> None:
        if not self.search_term:
            self.search_matches = []
            return
        term = self.search_term.lower()
        self.search_matches = [
            i for i, ln in enumerate(self.lines) if term in ln.lower()
        ]

    def _next_match(self, forward: bool) -> None:
        if not self.search_matches:
            self._do_search()
        if not self.search_matches:
            return
        if forward:
            after = [m for m in self.search_matches if m > self.row]
            self.row = after[0] if after else self.search_matches[0]
        else:
            before = [m for m in self.search_matches if m < self.row]
            self.row = before[-1] if before else self.search_matches[-1]

    @staticmethod
    def _yank(lines: list[str]) -> None:
        text = "\n".join(lines)
        try:
            import pyperclip  # noqa: PLC0415
            pyperclip.copy(text)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# VortoTUI — main controller
# ──────────────────────────────────────────────────────────────────────────────

_VERSION = "0.0.1"

_WELCOME_LINES = [
    "",
    "             Mia Vorto  " + _VERSION,
    "",
    "          ┌─────────────────────────────┐",
    "          │  a   aldoni    (aldonu)      │",
    "          │  v   vidi      (vidi)        │",
    "          │  m   modifi    (modifi)      │",
    "          │  s   serĉi     (serĉu)       │",
    "          │  f   forigi    (forigu)      │",
    "          │  h   helpo     (helpo)       │",
    "          │  q   eliri     (eliru)       │",
    "          └─────────────────────────────┘",
    "",
    "   Unuan fojon?  Tajpu  :tuto  por gvida lernilo.",
    "   (First time?  Type  :tuto  for a tutorial.)",
    "",
]

_HELP_LINES = [
    "Mia Vorto — Helpo",
    "",
    "  Komandrando (:)",
    "  ──────────────────────────────────────────────────",
    "  :tuto                tutorialo",
    "  :serci <vorto>       serĉi en la vortaro",
    "  :aldoni <t> [opcioj] aldoni eniron",
    "  :q / :eliru          eliri",
    "",
    "  Komandoj (normala reĝimo)",
    "  ──────────────────────────────────────────────────",
    "  a  aldoni nova vorton",
    "  v  vidi eniron per UUID",
    "  m  modifi eniron",
    "  s  serĉi",
    "  f  forigi eniron",
    "  h  ĉi tiu helpo",
    "  q  eliri",
    "",
    "  Navigado en vidanto (PAGER)",
    "  ──────────────────────────────────────────────────",
    "  j / k          unu linion malsupren / supren",
    "  h / l          horizontale",
    "  0 / $          komenco / fino de linio",
    "  gg / G         unua / lasta linio",
    "  {N}j / {N}k    N linioj",
    "  / <vorto>      serĉi  (n sekva, N antaŭa)",
    "  v              elekta reĝimo",
    "  y              yanki (kopii al tondujo)",
    "  q / Esc        reen",
    "",
    "  Formularo (FORMO)",
    "  ──────────────────────────────────────────────────",
    "  j / k          ŝanĝi kampon",
    "  i / a          enmeti antaŭ / post kursoro",
    "  I / A          enmeti komence / fine",
    "  Esc            normala reĝimo",
    "  :wq            konservi kaj eliri",
    "  :q             forĵeti kaj eliri",
    "",
    "  En enmeta reĝimo:",
    "  h l w e b 0 $  moviĝoj",
    "  x              forigu literon",
    "  dw d$ dd       forigu vorton / ĝis fino / tuta kampo",
    "  yy yw          yanki linion / vorton",
    "  p / P          pasti post / antaŭ kursoro",
    "  v → y/d        elekta kopio / forigu",
    "",
    "  Premu q por fermi.",
]

_TUTORIAL_LINES = [
    "Tutorialo — Mia Vorto",
    "",
    "1.  Premu  a  por aldoni vian unuan vorton.",
    "    Ekzemplo CLI: vorto aldoni 'saluton' -l eo -t verbo",
    "",
    "2.  Premu  s  por serĉi ĉiujn viajn vortojn.",
    "",
    "3.  Premu  v  kaj entajpu UUID por vidi eniron.",
    "    (UUID estas la unuaj 8 signoj en la serĉ-rezulto.)",
    "",
    "4.  Premu  m  kaj UUID por modifi eniron.",
    "",
    "5.  Premu  f  kaj UUID por forigi eniron.",
    "",
    "6.  Uzu  :malfari  por malfari la lastan ŝanĝon.",
    "",
    "7.  En la pager-vidanto (post v / s):",
    "    j/k = supren/malsupren  v = elekta  y = yanki  q = reen",
    "",
    "8.  Premu  q  por eliri el ĉiu ekrano.",
]


class VortoTUI:
    """Full-screen Mia Vorto TUI.

    Instantiated by _interactive_mode(); call .run() to start.
    Callbacks (load_entries, save_entry, etc.) are injected by the caller
    so this module stays independent of the database layer.
    """

    def __init__(
        self,
        *,
        load_entries: Callable[[], list[dict]],
        save_new_entry: Callable[[dict], None],
        save_modified_entry: Callable[[dict, dict], None],
        delete_entry: Callable[[dict], None],
        undo: Callable[[], str],
        render_entry: Callable[[dict], list[str]],
        render_results: Callable[[list[dict]], list[str]],
        detect_kategorio: Callable[[str], str],
        normalize_tipo: Callable[[str | None], str | None],
        normalize_tono: Callable[[str | None], str | None],
        parse_etikedo: Callable[[list[str] | None], dict[str, str]],
        find_entry: Callable[[str, list[dict]], dict | None],
        now_iso: Callable[[], str],
        make_uuid: Callable[[], str],
    ) -> None:
        self._load_entries = load_entries
        self._save_new = save_new_entry
        self._save_modified = save_modified_entry
        self._delete_entry = delete_entry
        self._undo = undo
        self._render_entry = render_entry
        self._render_results = render_results
        self._detect_kategorio = detect_kategorio
        self._normalize_tipo = normalize_tipo
        self._normalize_tono = normalize_tono
        self._parse_etikedo = parse_etikedo
        self._find_entry = find_entry
        self._now_iso = now_iso
        self._make_uuid = make_uuid

    def run(self) -> None:
        locale.setlocale(locale.LC_ALL, "")
        curses.wrapper(self._main)

    # ── curses entry ─────────────────────────────────────────────────────────

    def _main(self, stdscr: curses._CursesWindow) -> None:  # type: ignore[name-defined]
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)

        self._mode = "NORMAL"   # NORMAL | COMMAND | SEARCH
        self._cmd_buf = ""
        self._status_msg = ""

        self._welcome_loop()

    # ── welcome loop ─────────────────────────────────────────────────────────

    def _welcome_loop(self) -> None:
        while True:
            self._draw_welcome()
            key = self.stdscr.getch()
            ch = chr(key) if 0 < key < 256 else ""

            if self._mode == "COMMAND":
                done = self._cmd_key(key, ch)
                if done:
                    break
            elif self._mode == "SEARCH":
                done = self._search_key(key, ch)
                if done:
                    break
            else:
                # Normal mode
                if ch in ("q",) or key in (_CTRL_C, _CTRL_D):
                    break
                elif ch == ":":
                    self._mode = "COMMAND"
                    self._cmd_buf = ""
                elif ch == "/":
                    self._mode = "SEARCH"
                    self._cmd_buf = ""
                elif ch == "a":
                    self._action_aldoni()
                elif ch == "v":
                    self._action_vidi()
                elif ch == "m":
                    self._action_modifi()
                elif ch == "s":
                    self._action_serci()
                elif ch == "f":
                    self._action_forigi()
                elif ch == "h":
                    self._run_pager(_HELP_LINES, title="Helpo")
                elif key == curses.KEY_RESIZE:
                    pass  # just redraw on next iteration

    # ── drawing ──────────────────────────────────────────────────────────────

    def _draw_welcome(self) -> None:
        stdscr = self.stdscr
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Centre the welcome art vertically
        art_h = len(_WELCOME_LINES)
        top = max(0, (h - art_h - 2) // 2)  # -2 for status bar

        for i, line in enumerate(_WELCOME_LINES):
            row = top + i
            if row >= h - 1:
                break
            col = max(0, (w - len(line)) // 2)
            try:
                stdscr.addstr(row, col, line[:w - 1], curses.A_DIM)
            except curses.error:
                pass

        # Status / cmd / search bar at very bottom
        if self._mode == "COMMAND":
            status = f":{self._cmd_buf}█"
        elif self._mode == "SEARCH":
            status = f"/{self._cmd_buf}█"
        else:
            status = (
                self._status_msg
                or "NORMAL  a v m s f h q  |  : komando  |  / serĉi"
            )

        try:
            status_line = status[:w - 1].ljust(w - 1)
            stdscr.addstr(h - 1, 0, status_line, curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

    # ── command mode ─────────────────────────────────────────────────────────

    def _cmd_key(self, key: int, ch: str) -> bool:
        """Returns True if the app should quit."""
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
        """Execute a colon command.  Returns True to quit."""
        if cmd in ("q", "eliru", "exit", "quit"):
            return True
        if cmd == "tuto":
            self._run_pager(_TUTORIAL_LINES, title="Tutorialo")
        elif cmd == "h" or cmd == "helpo":
            self._run_pager(_HELP_LINES, title="Helpo")
        elif cmd.startswith("serci") or cmd.startswith("serĉi"):
            query = cmd.split(None, 1)[1].strip() if " " in cmd else ""
            self._do_serci(query)
        elif cmd.startswith("aldoni "):
            # :aldoni <teksto> [-l lang] etc. — pass through as CLI args
            self._status_msg = "Uzu la a-ŝlosilon por aldoni per formularo."
        elif cmd.startswith("malfari"):
            msg = self._undo()
            self._status_msg = msg
        else:
            self._status_msg = f"Nekonata komando: :{cmd}"
        return False

    # ── search mode ──────────────────────────────────────────────────────────

    def _search_key(self, key: int, ch: str) -> bool:
        if key in (_ENTER, _CR):
            query = self._cmd_buf.strip()
            self._mode = "NORMAL"
            self._cmd_buf = ""
            self._do_serci(query)
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

    # ── actions ──────────────────────────────────────────────────────────────

    def _run_pager(self, lines: list[str], title: str = "") -> str:
        pager = Pager(self.stdscr, lines, title=title)
        result = pager.run()
        curses.curs_set(0)
        return result

    def _action_aldoni(self) -> None:
        form = FormEditor(self.stdscr, title="Aldoni — nova eniro")
        vals = form.run()
        if vals is None:
            self._status_msg = "Nuligita."
            return
        now = self._now_iso()
        entry: dict = {
            "uuid": self._make_uuid(),
            "teksto": vals.get("teksto") or "",
            "lingvo": vals.get("lingvo"),
            "kategorio": self._detect_kategorio(vals.get("teksto") or ""),
            "tipo": self._normalize_tipo(vals.get("tipo")),
            "temo": vals.get("temo"),
            "tono": self._normalize_tono(vals.get("tono")),
            "nivelo": vals.get("nivelo"),
            "difinoj": vals.get("difinoj") or [],
            "etikedoj": vals.get("etikedoj") or {},
            "ligiloj": vals.get("ligiloj") or [],
            "kreita_je": now,
            "modifita_je": now,
        }
        if not entry["teksto"]:
            self._status_msg = "Nuligita — teksto estas malplena."
            return
        self._save_new(entry)
        self._status_msg = f"Aldonis #{entry['uuid'][:8]}  \"{entry['teksto']}\""

    def _action_vidi(self) -> None:
        uid = self._prompt_uid("Vidi")
        if not uid:
            return
        entries = self._load_entries()
        entry = self._find_entry(uid, entries)
        if entry is None:
            self._status_msg = f"Ne trovita: {uid!r}"
            return
        lines = self._render_entry(entry)
        self._run_pager(lines, title=f"Vidi — {entry['teksto'][:40]}")

    def _action_modifi(self) -> None:
        uid = self._prompt_uid("Modifi")
        if not uid:
            return
        entries = self._load_entries()
        entry = self._find_entry(uid, entries)
        if entry is None:
            self._status_msg = f"Ne trovita: {uid!r}"
            return
        old_entry = dict(entry)

        # Pre-populate form with existing values
        initial: dict = {
            "teksto": entry.get("teksto") or "",
            "lingvo": entry.get("lingvo") or "",
            "difinoj": entry.get("difinoj") or [],
            "tipo": entry.get("tipo") or "",
            "temo": entry.get("temo") or "",
            "tono": entry.get("tono") or "",
            "nivelo": (
                str(entry.get("nivelo")) if entry.get("nivelo") is not None else ""
            ),
            "etikedoj": entry.get("etikedoj") or {},
            "ligiloj": entry.get("ligiloj") or [],
        }
        form = FormEditor(
            self.stdscr,
            title=f"Modifi — {entry['teksto'][:40]}",
            initial=initial,
        )
        vals = form.run()
        if vals is None:
            self._status_msg = "Nuligita."
            return

        _MODIFI_KEYS = (
            "teksto", "lingvo", "tipo", "temo", "tono",
            "difinoj", "etikedoj", "ligiloj",
        )
        for key in _MODIFI_KEYS:
            if vals.get(key) is not None:
                entry[key] = vals[key]
        if vals.get("teksto"):
            entry["kategorio"] = self._detect_kategorio(vals["teksto"])
        if vals.get("tipo") is not None:
            entry["tipo"] = self._normalize_tipo(vals["tipo"])
        if vals.get("tono") is not None:
            entry["tono"] = self._normalize_tono(vals["tono"])
        if vals.get("nivelo") is not None:
            entry["nivelo"] = vals["nivelo"]
        entry["modifita_je"] = self._now_iso()

        self._save_modified(entry, old_entry)
        self._status_msg = f"Modifis #{entry['uuid'][:8]}  \"{entry['teksto']}\""

    def _action_serci(self) -> None:
        query = self._prompt_inline("Serĉi")
        self._do_serci(query)

    def _do_serci(self, query: str) -> None:
        entries = self._load_entries()
        if query:
            low = query.lower()
            found = [e for e in entries if low in e["teksto"].lower()][:50]
        else:
            found = entries[:50]
        lines = self._render_results(found)
        title = f"Serĉi: {query!r}" if query else "Ĉiuj vortoj (maks 50)"
        self._status_msg = f"{len(found)} rezulto(j)."
        self._run_pager(lines, title=title)

    def _action_forigi(self) -> None:
        uid = self._prompt_uid("Forigi")
        if not uid:
            return
        entries = self._load_entries()
        entry = self._find_entry(uid, entries)
        if entry is None:
            self._status_msg = f"Ne trovita: {uid!r}"
            return
        # Show entry for confirmation
        lines = self._render_entry(entry) + [
            "",
            "ATENTU: ĉi tiu eniro estos forigita.",
            "  y  — daŭrigi (forigi)",
            "  n / q — nuligi",
        ]
        self._run_pager(lines, title="Forigi — konfirmo")
        # Ask for confirmation via bottom prompt
        confirmed = self._prompt_confirm(
            f"Forigi  #{entry['uuid'][:8]}  \"{entry['teksto']}\"? (y/n)"
        )
        if confirmed:
            self._delete_entry(entry)
            self._status_msg = f"Forigis #{entry['uuid'][:8]}  \"{entry['teksto']}\""
        else:
            self._status_msg = "Nuligita."

    # ── small prompts (single-line overlay at bottom) ─────────────────────────

    def _prompt_uid(self, action: str) -> str:
        return self._prompt_inline(f"{action} — UUID (aŭ prefikso)")

    def _prompt_inline(self, prompt: str) -> str:
        """Draw the welcome screen + a prompt at the bottom; return typed text."""
        buf = ""
        curses.curs_set(1)
        while True:
            self._draw_welcome()
            h, w = self.stdscr.getmaxyx()
            line = f"{prompt}: {buf}█"
            try:
                self.stdscr.addstr(
                    h - 1, 0, line[:w - 1].ljust(w - 1), curses.A_REVERSE
                )
                self.stdscr.refresh()
            except curses.error:
                pass
            key = self.stdscr.getch()
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

    def _prompt_confirm(self, prompt: str) -> bool:
        """Ask y/n at the bottom of the screen; returns True for 'y'."""
        while True:
            self._draw_welcome()
            h, w = self.stdscr.getmaxyx()
            try:
                line = f"{prompt}"[:w - 1].ljust(w - 1)
                self.stdscr.addstr(h - 1, 0, line, curses.A_REVERSE)
                self.stdscr.refresh()
            except curses.error:
                pass
            key = self.stdscr.getch()
            ch = chr(key) if 0 < key < 256 else ""
            if ch == "y":
                return True
            if ch in ("n", "q") or key in (_ESC, _CTRL_C, _CTRL_D):
                return False
