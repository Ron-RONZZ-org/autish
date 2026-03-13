"""Tests for autish.commands.vorto (Mia Vorto wordbook microapp)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from typer.testing import CliRunner

from autish.commands.vorto import (
    _detect_kategorio,
    _entries_to_lines,
    _entry_to_lines,
    _find_entry,
    _normalize_tipo,
    _normalize_tono,
    _parse_etikedo,
)
from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# Helper fixtures
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SAMPLE_UUID2 = "11111111-2222-3333-4444-555555555555"


def _make_entry(**kwargs) -> dict:
    defaults = {
        "uuid": SAMPLE_UUID,
        "teksto": "hello",
        "lingvo": "en",
        "kategorio": "vorto",
        "tipo": "substantivo",
        "temo": "salutations",
        "tono": "informala",
        "nivelo": 1.0,
        "difinoj": ["a greeting"],
        "etikedoj": {"origin": "germanic"},
        "ligiloj": [],
        "kreita_je": "2024-01-01T00:00:00+00:00",
        "modifita_je": "2024-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — pure helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectKategorio:
    def test_single_word_is_vorto(self):
        assert _detect_kategorio("hello") == "vorto"

    def test_multi_word_no_punctuation_is_frazo(self):
        assert _detect_kategorio("hello world") == "frazo"

    def test_phrase_with_period_is_frazdaro(self):
        assert _detect_kategorio("Hello world.") == "frazdaro"

    def test_phrase_with_question_mark_is_frazdaro(self):
        assert _detect_kategorio("How are you?") == "frazdaro"

    def test_phrase_with_exclamation_is_frazdaro(self):
        # A single word with punctuation stays "vorto"; only multi-word phrases
        # with end-punctuation become "frazdaro".
        assert _detect_kategorio("Hello world!") == "frazdaro"

    def test_phrase_with_semicolon_is_frazdaro(self):
        assert _detect_kategorio("hello; goodbye") == "frazdaro"

    def test_phrase_with_ellipsis_is_frazdaro(self):
        # single token → vorto; multi-word with ellipsis → frazdaro
        assert _detect_kategorio("well…") == "vorto"
        assert _detect_kategorio("well, you know…") == "frazdaro"


class TestNormalizeTipo:
    def test_full_name_unchanged(self):
        assert _normalize_tipo("substantivo") == "substantivo"

    def test_abbreviation_expanded(self):
        assert _normalize_tipo("su") == "substantivo"
        assert _normalize_tipo("ve") == "verbo"
        assert _normalize_tipo("aj") == "adjektivo"
        assert _normalize_tipo("av") == "adverbo"
        assert _normalize_tipo("pa") == "parola"
        assert _normalize_tipo("sk") == "skriba"
        assert _normalize_tipo("ci") == "citaĵo"
        assert _normalize_tipo("pr") == "proverbo"
        assert _normalize_tipo("po") == "poemo"
        assert _normalize_tipo("ek") == "ekzemplo"

    def test_none_returns_none(self):
        assert _normalize_tipo(None) is None

    def test_unknown_returned_as_is(self):
        assert _normalize_tipo("custom") == "custom"

    def test_case_insensitive(self):
        assert _normalize_tipo("SU") == "substantivo"
        assert _normalize_tipo("Verbo") == "verbo"


class TestNormalizeTono:
    def test_full_name_unchanged(self):
        assert _normalize_tono("informala") == "informala"
        assert _normalize_tono("formala") == "formala"
        assert _normalize_tono("ambaŭ") == "ambaŭ"

    def test_abbreviation_expanded(self):
        assert _normalize_tono("in") == "informala"
        assert _normalize_tono("fo") == "formala"
        assert _normalize_tono("am") == "ambaŭ"

    def test_none_returns_none(self):
        assert _normalize_tono(None) is None

    def test_unknown_returned_as_is(self):
        assert _normalize_tono("neutral") == "neutral"


class TestParseEtikedo:
    def test_key_value_pairs(self):
        result = _parse_etikedo(["origin:germanic", "register:formal"])
        assert result == {"origin": "germanic", "register": "formal"}

    def test_key_only(self):
        result = _parse_etikedo(["important"])
        assert result == {"important": ""}

    def test_empty_list(self):
        assert _parse_etikedo([]) == {}

    def test_none_returns_empty(self):
        assert _parse_etikedo(None) == {}

    def test_whitespace_stripped(self):
        result = _parse_etikedo([" key : value "])
        assert result == {"key": "value"}


class TestFindEntry:
    def setup_method(self):
        self.entry = _make_entry()
        self.entries = [self.entry]

    def test_exact_uuid_match(self):
        assert _find_entry(SAMPLE_UUID, self.entries) is self.entry

    def test_uuid_prefix_match(self):
        assert _find_entry("aaaaaaaa", self.entries) is self.entry

    def test_text_match_case_insensitive(self):
        assert _find_entry("HELLO", self.entries) is self.entry

    def test_not_found_returns_none(self):
        assert _find_entry("notfound", self.entries) is None

    def test_ambiguous_prefix_returns_none(self):
        e2 = _make_entry(uuid="aaaaaaaa-ffff-cccc-dddd-eeeeeeeeeeee", teksto="hi")
        result = _find_entry("aaaaaaaa", [self.entry, e2])
        assert result is None

    def test_ambiguous_text_returns_none(self):
        e2 = _make_entry(uuid=SAMPLE_UUID2, teksto="hello")
        result = _find_entry("hello", [self.entry, e2])
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# CLI command tests — all I/O is mocked to avoid touching the filesystem
# ──────────────────────────────────────────────────────────────────────────────

_LOAD = "autish.commands.vorto._load_entries"
_SAVE = "autish.commands.vorto._save_entries"
_LOAD_UNDO = "autish.commands.vorto._load_undo_stack"
_SAVE_UNDO = "autish.commands.vorto._save_undo_stack"
_CONFIRM = "autish.commands.vorto.typer.confirm"


class TestAldoni:
    def test_adds_entry_and_exits_zero(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello"])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["teksto"] == "hello"

    def test_auto_detects_kategorio_vorto(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello"])
        assert mock_save.call_args[0][0][0]["kategorio"] == "vorto"

    def test_auto_detects_kategorio_frazo(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello world"])
        assert mock_save.call_args[0][0][0]["kategorio"] == "frazo"

    def test_with_options(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app,
                [
                    "vorto",
                    "aldoni",
                    "hello",
                    "-l",
                    "en",
                    "-t",
                    "su",
                    "-n",
                    "3.0",
                    "-d",
                    "a greeting",
                ],
            )
        entry = mock_save.call_args[0][0][0]
        assert entry["lingvo"] == "en"
        assert entry["tipo"] == "substantivo"
        assert entry["nivelo"] == 3.0
        assert "a greeting" in entry["difinoj"]

    def test_cancelled_does_not_save(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello"])
        assert result.exit_code == 0
        mock_save.assert_not_called()

    def test_invalid_nivelo_exits_nonzero(self):
        result = runner.invoke(app, ["vorto", "aldoni", "hello", "-n", "11"])
        assert result.exit_code != 0

    def test_pushes_to_undo_stack(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO) as mock_save_undo,
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "test"])
        saved_stack = mock_save_undo.call_args[0][0]
        assert len(saved_stack) == 1
        assert saved_stack[0]["op"] == "aldoni"


class TestVidi:
    def test_displays_entry(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_uuid_prefix_works(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "aaaaaaaa"])
        assert result.exit_code == 0

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi", "notfound"])
        assert result.exit_code != 0


class TestModifi:
    def test_no_options_shows_help(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "Usage" in result.output or "modifi" in result.output.lower()

    def test_modifies_field(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(
                app, ["vorto", "modifi", SAMPLE_UUID, "-l", "eo"]
            )
        assert result.exit_code == 0
        updated = mock_save.call_args[0][0][0]
        assert updated["lingvo"] == "eo"

    def test_cancelled_does_not_save(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID, "-l", "eo"])
        mock_save.assert_not_called()

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(
                app, ["vorto", "modifi", "notfound", "-l", "eo"]
            )
        assert result.exit_code != 0

    def test_pushes_to_undo_stack(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO) as mock_save_undo,
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID, "-l", "eo"])
        saved_stack = mock_save_undo.call_args[0][0]
        assert saved_stack[-1]["op"] == "modifi"
        assert saved_stack[-1]["old"]["lingvo"] == "en"


class TestSerci:
    def setup_method(self):
        self.entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello", lingvo="en", nivelo=2.0),
            _make_entry(
                uuid=SAMPLE_UUID2,
                teksto="saluton",
                lingvo="eo",
                kategorio="vorto",
                tipo="verbo",
                nivelo=1.0,
            ),
        ]

    def test_no_filter_returns_all(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci"])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "saluton" in result.output

    def test_text_filter(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "hello"])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "saluton" not in result.output

    def test_lingvo_filter(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "-l", "eo"])
        assert result.exit_code == 0
        assert "saluton" in result.output
        assert "hello" not in result.output

    def test_regex_filter(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(
                app, ["vorto", "serci", "--regex", "^hel"]
            )
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "saluton" not in result.output

    def test_invalid_regex_exits_nonzero(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "--regex", "[invalid"])
        assert result.exit_code != 0

    def test_limo_limits_results(self):
        many = [
            _make_entry(uuid=str(uuid.uuid4()), teksto=f"word{i}")
            for i in range(10)
        ]
        with patch(_LOAD, return_value=many):
            result = runner.invoke(app, ["vorto", "serci", "--limo", "3"])
        assert result.exit_code == 0
        assert "3 rezulto" in result.output

    def test_nivelo_min_filter(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "--nivelo-min", "2"])
        assert "hello" in result.output
        assert "saluton" not in result.output

    def test_nivelo_max_filter(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "--nivelo-max", "1"])
        assert "saluton" in result.output
        assert "hello" not in result.output

    def test_ordo_dato_newest_first(self):
        old_entry = _make_entry(
            uuid=SAMPLE_UUID,
            teksto="alpha",
            kreita_je="2023-01-01T00:00:00+00:00",
            modifita_je="2023-01-01T00:00:00+00:00",
        )
        new_entry = _make_entry(
            uuid=SAMPLE_UUID2,
            teksto="beta",
            kreita_je="2024-06-01T00:00:00+00:00",
            modifita_je="2024-06-01T00:00:00+00:00",
        )
        with patch(_LOAD, return_value=[old_entry, new_entry]):
            result = runner.invoke(app, ["vorto", "serci", "-o", "dato"])
        assert result.exit_code == 0
        assert result.output.index("beta") < result.output.index("alpha")

    def test_empty_results_message(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "serci", "zzznomatch"])
        assert result.exit_code == 0
        assert "0 rezulto" in result.output


class TestForigi:
    def test_deletes_entry(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert len(saved) == 0

    def test_cancelled_keeps_entry(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        mock_save.assert_not_called()

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "forigi", "notfound"])
        assert result.exit_code != 0

    def test_pushes_to_undo_stack(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO) as mock_save_undo,
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        saved_stack = mock_save_undo.call_args[0][0]
        assert saved_stack[-1]["op"] == "forigi"


class TestMalfari:
    def test_undo_aldoni(self):
        entry = _make_entry()
        stack = [{"op": "aldoni", "uuid": SAMPLE_UUID}]
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=stack),
            patch(_SAVE_UNDO),
        ):
            result = runner.invoke(app, ["vorto", "malfari"])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert len(saved) == 0

    def test_undo_modifi(self):
        old_entry = _make_entry(lingvo="en")
        new_entry = _make_entry(lingvo="eo")
        stack = [{"op": "modifi", "old": old_entry}]
        with (
            patch(_LOAD, return_value=[new_entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=stack),
            patch(_SAVE_UNDO),
        ):
            result = runner.invoke(app, ["vorto", "malfari"])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert saved[0]["lingvo"] == "en"

    def test_undo_forigi(self):
        entry = _make_entry()
        stack = [{"op": "forigi", "entry": entry}]
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=stack),
            patch(_SAVE_UNDO),
        ):
            result = runner.invoke(app, ["vorto", "malfari"])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["teksto"] == "hello"

    def test_empty_stack_message(self):
        with patch(_LOAD_UNDO, return_value=[]):
            result = runner.invoke(app, ["vorto", "malfari"])
        assert result.exit_code == 0
        assert "Nenio" in result.output or "Nothing" in result.output

    def test_stack_shrinks_after_undo(self):
        entry = _make_entry()
        stack = [
            {"op": "aldoni", "uuid": SAMPLE_UUID},
            {"op": "aldoni", "uuid": SAMPLE_UUID2},
        ]
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=stack),
            patch(_SAVE_UNDO) as mock_save_undo,
        ):
            runner.invoke(app, ["vorto", "malfari"])
        saved_stack = mock_save_undo.call_args[0][0]
        assert len(saved_stack) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Registration tests
# ──────────────────────────────────────────────────────────────────────────────


class TestRegistration:
    def test_vorto_in_autish_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "vorto" in result.output

    def test_vorto_subcommands_visible(self):
        result = runner.invoke(app, ["vorto", "--help"])
        assert result.exit_code == 0
        for sub in ("aldoni", "vidi", "modifi", "serci", "forigi", "malfari"):
            assert sub in result.output

    def test_vorto_in_kp_subcommands(self):
        from autish.commands.kp import _AUTISH_SUBCOMMANDS

        assert "vorto" in _AUTISH_SUBCOMMANDS


# ──────────────────────────────────────────────────────────────────────────────
# TUI helper tests
# ──────────────────────────────────────────────────────────────────────────────


class TestEntryToLines:
    def test_basic_fields_present(self):
        entry = _make_entry()
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "hello" in joined
        assert "aaaaaaaa" in joined   # UUID prefix
        assert "en" in joined         # lingvo

    def test_definition_listed(self):
        entry = _make_entry(difinoj=["a greeting", "a salutation"])
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "a greeting" in joined
        assert "a salutation" in joined

    def test_empty_optional_fields_omitted(self):
        entry = _make_entry(temo=None, tono=None, nivelo=None, etikedoj={})
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "temo" not in joined
        assert "tono" not in joined
        assert "nivelo" not in joined

    def test_returns_list_of_strings(self):
        entry = _make_entry()
        lines = _entry_to_lines(entry)
        assert isinstance(lines, list)
        assert all(isinstance(ln, str) for ln in lines)


class TestEntriesToLines:
    def test_empty_list_gives_no_results_message(self):
        lines = _entries_to_lines([])
        assert any("Neniu" in ln or "No results" in ln for ln in lines)

    def test_header_row_present(self):
        entry = _make_entry()
        lines = _entries_to_lines([entry])
        joined = "\n".join(lines)
        assert "Teksto" in joined
        assert "Lingvo" in joined

    def test_entry_teksto_present(self):
        entry = _make_entry()
        lines = _entries_to_lines([entry])
        joined = "\n".join(lines)
        assert "hello" in joined

    def test_multiple_entries(self):
        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello"),
            _make_entry(uuid=SAMPLE_UUID2, teksto="saluton"),
        ]
        lines = _entries_to_lines(entries)
        joined = "\n".join(lines)
        assert "hello" in joined
        assert "saluton" in joined


class TestLineEditor:
    """Unit tests for the LineEditor Vim-style text editor."""

    def _make_editor(self, text: str = "", insert: bool = True):
        from autish.commands._vorto_tui import LineEditor
        return LineEditor(text, insert_on_start=insert)

    def test_initial_text(self):
        ed = self._make_editor("hello")
        assert ed.text == "hello"

    def test_insert_mode_typing(self):
        ed = self._make_editor("")
        for ch in "hello":
            ed.handle_key(ord(ch))
        assert ed.text == "hello"

    def test_backspace_in_insert(self):
        ed = self._make_editor("hello")
        ed.handle_key(127)  # backspace
        assert ed.text == "hell"

    def test_esc_switches_to_normal(self):
        ed = self._make_editor("hello")
        assert ed.mode == "INSERT"
        ed.handle_key(27)  # ESC
        assert ed.mode == "NORMAL"

    def test_normal_h_moves_left(self):
        ed = self._make_editor("hello", insert=False)
        ed.pos = 3
        ed.handle_key(ord("h"))
        assert ed.pos == 2

    def test_normal_l_moves_right(self):
        ed = self._make_editor("hello", insert=False)
        ed.pos = 0
        ed.handle_key(ord("l"))
        assert ed.pos == 1

    def test_normal_0_goes_to_start(self):
        ed = self._make_editor("hello", insert=False)
        ed.pos = 4
        ed.handle_key(ord("0"))
        assert ed.pos == 0

    def test_normal_dollar_goes_to_end(self):
        ed = self._make_editor("hello", insert=False)
        ed.pos = 0
        ed.handle_key(ord("$"))
        assert ed.pos == len("hello") - 1

    def test_normal_w_moves_to_next_word(self):
        ed = self._make_editor("hello world", insert=False)
        ed.pos = 0
        ed.handle_key(ord("w"))
        assert ed.pos == 6  # 'w' in 'world'

    def test_normal_x_deletes_char(self):
        ed = self._make_editor("hello", insert=False)
        ed.pos = 0
        ed.handle_key(ord("x"))
        assert ed.text == "ello"

    def test_dd_clears_field(self):
        ed = self._make_editor("hello world", insert=False)
        ed._pending_op = "d"
        ed._pending_count = 1
        ed._apply_pending(ord("d"), "d")
        assert ed.text == ""

    def test_yank_copies_to_register(self):
        ed = self._make_editor("hello", insert=False)
        ed._pending_op = "y"
        ed._pending_count = 1
        ed._apply_pending(ord("y"), "y")
        assert ed.register == "hello"

    def test_visual_mode_entered(self):
        ed = self._make_editor("hello", insert=False)
        ed.handle_key(ord("v"))
        assert ed.mode == "VISUAL"

    def test_enter_returns_done_in_insert(self):
        ed = self._make_editor("")
        result = ed.handle_key(ord("\n"))
        assert result == "done"

    def test_count_prefix_multiplies_motion(self):
        ed = self._make_editor("hello world foo", insert=False)
        ed.pos = 0
        # 2w should skip two words
        ed.handle_key(ord("2"))
        ed.handle_key(ord("w"))
        # Should be at 'foo' (index 12)
        assert ed.pos > 6


class TestPager:
    """Unit tests for the Pager navigation logic (no curses rendering)."""

    def _make_pager(self, lines=None):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import Pager
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.getch.return_value = ord("q")
        p = Pager(stdscr, lines or ["line1", "line2", "line3"], title="test")
        return p

    def test_initial_position(self):
        p = self._make_pager()
        assert p.row == 0

    def test_j_moves_down(self):
        p = self._make_pager(["l1", "l2", "l3"])
        p._normal_key(ord("j"), "j")
        assert p.row == 1

    def test_k_moves_up(self):
        p = self._make_pager(["l1", "l2", "l3"])
        p.row = 2
        p._normal_key(ord("k"), "k")
        assert p.row == 1

    def test_count_prefix_j(self):
        p = self._make_pager(["l1", "l2", "l3", "l4"])
        p._count_buf = "2"
        p._normal_key(ord("j"), "j")
        assert p.row == 2

    def test_G_goes_to_last_line(self):
        p = self._make_pager(["l1", "l2", "l3"])
        p._normal_key(ord("G"), "G")
        assert p.row == 2

    def test_gg_goes_to_first_line(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import Pager
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        # Simulate 'g' followed by 'g'
        stdscr.getch.return_value = ord("g")
        p = Pager(stdscr, ["l1", "l2", "l3"], title="test")
        p.row = 2
        p._normal_key(ord("g"), "g")
        assert p.row == 0

    def test_0_resets_col(self):
        p = self._make_pager()
        p.col = 10
        p._normal_key(ord("0"), "0")
        assert p.col == 0

    def test_search_finds_match(self):
        p = self._make_pager(["hello", "world", "hello again"])
        p.search_term = "hello"
        p._do_search()
        assert 0 in p.search_matches
        assert 2 in p.search_matches

    def test_next_match_advances(self):
        p = self._make_pager(["hello", "world", "hello again"])
        p.search_term = "hello"
        p._do_search()
        p.row = 0
        p._next_match(forward=True)
        assert p.row == 2

    def test_visual_mode(self):
        p = self._make_pager()
        p._normal_key(ord("v"), "v")
        assert p._mode == "VISUAL"

    def test_q_returns_back(self):
        p = self._make_pager()
        result = p._normal_key(ord("q"), "q")
        assert result == "back"


# ──────────────────────────────────────────────────────────────────────────────
# New functionality tests
# ──────────────────────────────────────────────────────────────────────────────


class TestVidiNoArg:
    """Tests for the new optional-argument vidi command."""

    def test_no_arg_shows_latest_50(self):
        entries = [
            _make_entry(
                uuid=str(uuid.uuid4()),
                teksto=f"word{i}",
                kreita_je=f"2024-0{(i % 9) + 1}-01T00:00:00+00:00",
                modifita_je=f"2024-0{(i % 9) + 1}-01T00:00:00+00:00",
            )
            for i in range(5)
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "vidi"])
        assert result.exit_code == 0
        assert "5 rezulto" in result.output

    def test_no_arg_inverse_flag(self):
        entries = [
            _make_entry(uuid=str(uuid.uuid4()), teksto=f"word{i}")
            for i in range(3)
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "vidi", "-i"])
        assert result.exit_code == 0

    def test_with_uuid_still_shows_single_entry(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_empty_db_no_arg(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi"])
        assert result.exit_code == 0
        assert "0 rezulto" in result.output


class TestHelpCommand:
    """Tests for the autish help command."""

    def test_help_command_exits_zero(self):
        result = runner.invoke(app, ["help"])
        assert result.exit_code == 0

    def test_help_command_shows_commands(self):
        result = runner.invoke(app, ["help"])
        assert "autish" in result.output.lower() or "Usage" in result.output


class TestLineEditorViewStart:
    """Tests for the fixed LineEditor horizontal scroll."""

    def _make_editor(self, text: str = "", insert: bool = True):
        from autish.commands._vorto_tui import LineEditor
        return LineEditor(text, insert_on_start=insert)

    def test_view_start_initialized_to_zero(self):
        ed = self._make_editor("hello")
        assert ed._view_start == 0

    def test_view_start_scrolls_when_cursor_beyond_width(self):
        """When the cursor is beyond the visible width, view_start should scroll."""
        from unittest.mock import MagicMock
        ed = self._make_editor("a" * 50)
        ed.pos = 40
        win = MagicMock()
        win.addstr = MagicMock()
        win.move = MagicMock()
        # width = 20, col = 5 (screen column)
        ed.render(win, row=1, col=5, width=20, focused=True)
        # After render with pos=40 and width=20, view_start should be >= 21
        assert ed._view_start >= 21

    def test_view_start_resets_when_cursor_before_view(self):
        from unittest.mock import MagicMock
        ed = self._make_editor("a" * 50)
        ed._view_start = 30  # scroll far right
        ed.pos = 5           # cursor is before the scrolled view
        win = MagicMock()
        ed.render(win, row=1, col=5, width=20, focused=True)
        # view_start should have moved back to 5 (at cursor)
        assert ed._view_start <= ed.pos


class TestFormEditorModeInit:
    """Tests that FormEditor initializes only the first field in INSERT mode."""

    def test_first_editor_starts_in_insert(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import FormEditor
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)
        form = FormEditor(stdscr, title="Test")
        assert form.editors[0].mode == "INSERT"

    def test_other_editors_start_in_normal(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import FormEditor
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)
        form = FormEditor(stdscr, title="Test")
        for ed in form.editors[1:]:
            assert ed.mode == "NORMAL"


class TestPagerCharCursor:
    """Tests for the Pager character cursor and new J/K navigation."""

    def _make_pager(self, lines=None):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import Pager
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.getch.return_value = ord("q")
        return Pager(
            stdscr,
            lines or ["hello world", "second line", "third"],
            title="t",
        )

    def test_char_pos_initialized_to_zero(self):
        p = self._make_pager()
        assert p.char_pos == 0

    def test_h_decrements_char_pos(self):
        p = self._make_pager()
        p.char_pos = 5
        p._normal_key(ord("h"), "h")
        assert p.char_pos == 4

    def test_l_increments_char_pos(self):
        p = self._make_pager()
        p.char_pos = 0
        p._normal_key(ord("l"), "l")
        assert p.char_pos == 1

    def test_l_clamps_at_line_end(self):
        p = self._make_pager(["abc"])
        p.char_pos = 2  # last char of "abc"
        p._normal_key(ord("l"), "l")
        assert p.char_pos == 2  # can't go past end

    def test_zero_resets_char_pos_and_col(self):
        p = self._make_pager()
        p.char_pos = 5
        p.col = 3
        p._normal_key(ord("0"), "0")
        assert p.char_pos == 0
        assert p.col == 0

    def test_dollar_sets_char_pos_to_last_char(self):
        p = self._make_pager(["hello"])
        p._normal_key(ord("$"), "$")
        assert p.char_pos == len("hello") - 1

    def test_J_moves_page_down(self):
        lines = [f"line{i}" for i in range(50)]
        p = self._make_pager(lines)
        p.row = 0
        p._normal_key(ord("J"), "J")
        assert p.row > 0

    def test_K_moves_page_up(self):
        lines = [f"line{i}" for i in range(50)]
        p = self._make_pager(lines)
        p.row = 25
        p._normal_key(ord("K"), "K")
        assert p.row < 25

    def test_yank_sets_status(self):
        p = self._make_pager(["hello world"])
        p._yank_status = ""
        p._yank(["hello world"])
        assert p._yank_status != ""
        assert "Yankita" in p._yank_status
