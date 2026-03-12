"""Tests for autish.commands.vorto (Mia Vorto wordbook microapp)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from typer.testing import CliRunner

from autish.commands.vorto import (
    _detect_kategorio,
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


class TestVido:
    def test_displays_entry(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vido", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_uuid_prefix_works(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vido", "aaaaaaaa"])
        assert result.exit_code == 0

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vido", "notfound"])
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
        for sub in ("aldoni", "vido", "modifi", "serci", "forigi", "malfari"):
            assert sub in result.output

    def test_vorto_in_kp_subcommands(self):
        from autish.commands.kp import _AUTISH_SUBCOMMANDS

        assert "vorto" in _AUTISH_SUBCOMMANDS
