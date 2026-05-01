"""Tests for autish.commands.vorto (Mia Vorto wordbook microapp)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

from rich.console import Group
from rich.text import Text
from typer.testing import CliRunner

from autish.commands.vorto import (
    _apply_french_ligatures,
    _detect_kategorio,
    _display_entry,
    _display_results,
    _entries_to_lines,
    _entry_to_lines,
    _find_entry,
    _fuzzy_text_matches,
    _normalize_oe,
    _normalize_tipo,
    _normalize_tono,
    _parse_etikedo,
    _render_entry_preview_html,
    _tui_save_modified,
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
        "tipo": "substantivo-neŭtra",
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
        assert _normalize_tipo("substantivo") == ["substantivo"]
        assert _normalize_tipo("substantivo-ina") == ["substantivo-ina"]
        assert _normalize_tipo("substantivo-vira") == ["substantivo-vira"]
        assert _normalize_tipo("substantivo-plurala") == ["substantivo-plurala"]
        assert _normalize_tipo("substantivo-ina-plurala") == ["substantivo-ina-plurala"]
        assert _normalize_tipo("substantivo-vira-plurala") == [
            "substantivo-vira-plurala"
        ]
        assert _normalize_tipo("refleksiva-verbo") == ["refleksiva-verbo"]

    def test_abbreviation_expanded(self):
        assert _normalize_tipo("su") == ["substantivo"]
        assert _normalize_tipo("sn") == ["substantivo-neŭtra"]
        assert _normalize_tipo("si") == ["substantivo-ina"]
        assert _normalize_tipo("sv") == ["substantivo-vira"]
        assert _normalize_tipo("sp") == ["substantivo-plurala"]
        assert _normalize_tipo("sip") == ["substantivo-ina-plurala"]
        assert _normalize_tipo("svp") == ["substantivo-vira-plurala"]
        assert _normalize_tipo("sui") == ["substantivo-ina"]
        assert _normalize_tipo("suv") == ["substantivo-vira"]
        assert _normalize_tipo("suf") == ["substantivo-ina"]
        assert _normalize_tipo("sum") == ["substantivo-vira"]
        assert _normalize_tipo("ve") == ["verbo"]
        assert _normalize_tipo("vt") == ["verbo-transitiva"]
        assert _normalize_tipo("vnt") == ["verbo-nerekta-transitiva"]
        assert _normalize_tipo("vn") == ["verbo-netransitiva"]
        assert _normalize_tipo("vr") == ["refleksiva-verbo"]
        assert _normalize_tipo("aj") == ["adjektivo"]
        assert _normalize_tipo("av") == ["adverbo"]
        assert _normalize_tipo("pa") == ["parola"]
        assert _normalize_tipo("sk") == ["skriba"]
        assert _normalize_tipo("ci") == ["citaĵo"]
        assert _normalize_tipo("pr") == ["proverbo"]
        assert _normalize_tipo("po") == ["poemo"]
        assert _normalize_tipo("ek") == ["ekzemplo"]

    def test_none_returns_none(self):
        assert _normalize_tipo(None) is None

    def test_unknown_returned_as_is(self):
        assert _normalize_tipo("custom") == ["custom"]

    def test_case_insensitive(self):
        assert _normalize_tipo("SU") == ["substantivo"]
        assert _normalize_tipo("SN") == ["substantivo-neŭtra"]
        assert _normalize_tipo("Verbo") == ["verbo"]

    def test_multiple_tipos_comma_separated(self):
        assert _normalize_tipo("aj,su") == ["adjektivo", "substantivo"]
        assert _normalize_tipo("vt, aj") == ["verbo-transitiva", "adjektivo"]

    def test_multiple_tipos_semicolon_separated(self):
        assert _normalize_tipo("aj;su") == ["adjektivo", "substantivo"]

    def test_no_duplicates_in_multiple_tipos(self):
        assert _normalize_tipo("aj,aj,su") == ["adjektivo", "substantivo"]


class TestNormalizeTono:
    def test_full_name_unchanged(self):
        assert _normalize_tono("neformala") == "neformala"
        assert _normalize_tono("formala") == "formala"
        assert _normalize_tono("ambaŭ") == "ambaŭ"

    def test_abbreviation_expanded(self):
        assert _normalize_tono("nf") == "neformala"
        assert _normalize_tono("fo") == "formala"
        assert _normalize_tono("am") == "ambaŭ"

    def test_legacy_aliases(self):
        # 'in' and 'informala' are kept for backwards compat → neformala
        assert _normalize_tono("in") == "neformala"
        assert _normalize_tono("informala") == "neformala"

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

    def test_vt_prefixed_uuid_prefix_match(self):
        assert _find_entry("vt#aaaaaaaa", self.entries) is self.entry

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
_CONFIRM = "autish.commands.vorto._confirm_esperante"
_MOVE_TO_RUBUJO = "autish.commands.vorto._move_to_rubujo"
_RECOVER_FROM_RUBUJO = "autish.commands.vorto._recover_from_rubujo"


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
        assert entry["tipo"] == ["substantivo"]
        assert entry["nivelo"] == 3.0
        assert "a greeting" in entry["difinoj"]

    def test_aldoni_teksto_accepts_escaped_newline(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", r"linio1\nlinio2"])
        assert result.exit_code == 0, result.output
        entry = mock_save.call_args[0][0][0]
        assert entry["teksto"] == "linio1\nlinio2"

    def test_aldoni_teksto_accepts_br_markup(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "linio1<br>linio2"])
        assert result.exit_code == 0, result.output
        entry = mock_save.call_args[0][0][0]
        assert entry["teksto"] == "linio1\nlinio2"

    def test_ligilo_short_alias_L(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app,
                ["vorto", "aldoni", "hello", "-L", SAMPLE_UUID2],
            )
        entry = mock_save.call_args[0][0][0]
        assert entry["ligiloj"] == [SAMPLE_UUID2]

    def test_aldoni_confirmation_shows_human_readable_ligilo_text(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="s'ingérer", ligiloj=[])
        with (
            patch(_LOAD, return_value=[linked]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            result = runner.invoke(
                app,
                ["vorto", "aldoni", "hello", "-L", SAMPLE_UUID2],
            )
        assert result.exit_code == 0, result.output
        assert "ligiloj: [s'ingérer]" in result.output
        assert SAMPLE_UUID2 not in result.output
        mock_save.assert_not_called()

    def test_aldoni_confirmation_truncates_long_ligilo_text(self):
        long_text = "x" * 40
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto=long_text, ligiloj=[])
        with (
            patch(_LOAD, return_value=[linked]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            result = runner.invoke(
                app,
                ["vorto", "aldoni", "hello", "-L", SAMPLE_UUID2],
            )
        assert result.exit_code == 0, result.output
        assert f"ligiloj: [{'x' * 27}...]" in result.output
        mock_save.assert_not_called()

    def test_difino_with_braced_uzo_syntax_is_split(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app,
                ["vorto", "aldoni", "hello", "-d", "saluto:{mi uzas tion}"],
            )
        entry = mock_save.call_args[0][0][0]
        assert entry["difinoj"] == ["saluto"]
        assert entry["uzoj"] == ["mi uzas tion"]

    def test_inline_markdown_link_in_difino_adds_ligilo(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="world", ligiloj=[])
        with (
            patch(_LOAD, return_value=[linked]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
            patch(
                "autish.commands.vorto._uuid_mod.uuid4",
                return_value=uuid.UUID(SAMPLE_UUID),
            ),
        ):
            runner.invoke(
                app,
                [
                    "vorto",
                    "aldoni",
                    "hello",
                    "-d",
                    "difino kun [world](#11111111)",
                ],
            )
        saved_entries = mock_save.call_args[0][0]
        entry_a = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID)
        assert SAMPLE_UUID2 in entry_a["ligiloj"]

    def test_inline_markdown_link_to_encik_ref_adds_canonical_ec_ligilo(self):
        encik_uuid = "4feb123f-aaaa-bbbb-cccc-ddddeeeeffff"
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
            patch(
                "autish.commands.vorto._find_encik_entry",
                return_value={"uuid": encik_uuid, "titolo": "Encik Nodo"},
            ),
        ):
            runner.invoke(
                app,
                [
                    "vorto",
                    "aldoni",
                    "hello",
                    "-d",
                    "difino kun [nodo](ec#4feb123f)",
                ],
            )
        entry = mock_save.call_args[0][0][0]
        assert f"ec#{encik_uuid}" in entry["ligiloj"]

    def test_inline_markdown_link_is_parsed_from_all_text_fields(self):
        encik_uuid = "4feb123f-aaaa-bbbb-cccc-ddddeeeeffff"
        cases = [
            ["vorto", "aldoni", "hello [nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "-d", "difino [nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "--temo", "temo [nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "--tono", "[nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "-A", "autoro [nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "-v", "verko [nodo](ec#4feb123f)"],
            ["vorto", "aldoni", "hello", "-e", "etikedo:[nodo](ec#4feb123f)"],
        ]
        for argv in cases:
            with (
                patch(_LOAD, return_value=[]),
                patch(_SAVE) as mock_save,
                patch(_LOAD_UNDO, return_value=[]),
                patch(_SAVE_UNDO),
                patch(_CONFIRM, return_value=True),
                patch(
                    "autish.commands.vorto._find_encik_entry",
                    return_value={"uuid": encik_uuid, "titolo": "Encik Nodo"},
                ),
            ):
                result = runner.invoke(app, argv)
            assert result.exit_code == 0, result.output
            entry = mock_save.call_args[0][0][0]
            assert f"ec#{encik_uuid}" in entry["ligiloj"]

    def test_ligilo_adds_reciprocal_link(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="world", ligiloj=[])
        with (
            patch(_LOAD, return_value=[linked]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
            patch(
                "autish.commands.vorto._uuid_mod.uuid4",
                return_value=uuid.UUID(SAMPLE_UUID),
            ),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello", "-L", SAMPLE_UUID2])
        saved_entries = mock_save.call_args[0][0]
        entry_a = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID)
        entry_b = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID2)
        assert entry_a["ligiloj"] == [SAMPLE_UUID2]
        assert entry_b["ligiloj"] == [SAMPLE_UUID]

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

    def test_aldoni_kopii_copies_short_uuid(self, monkeypatch):
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
            patch(
                "autish.commands.vorto._uuid_mod.uuid4",
                return_value=uuid.UUID(SAMPLE_UUID),
            ),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello", "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"] == "#aaaaaaaa"

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

    def test_difino_with_bang_character_is_stored_verbatim(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(
                app,
                ["vorto", "aldoni", "hello-bang", "-d", "!grave"],
                env={**os.environ, "HISTCONTROL": "ignoredups"},
            )
        assert result.exit_code == 0
        entry = mock_save.call_args[0][0][0]
        assert entry["difinoj"] == ["!grave"]

    def test_difino_double_colon_syntax_splits_example_with_bang(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "vorto",
                    "aldoni",
                    "defense",
                    "-d",
                    "ce qui permet::Ma seule defense sera la fuite !",
                ],
            )
        assert result.exit_code == 0
        entry = mock_save.call_args[0][0][0]
        assert entry["difinoj"] == ["ce qui permet"]
        assert entry["uzoj"] == ["Ma seule defense sera la fuite !"]


class TestVidi:
    def test_displays_entry(self):
        entry = _make_entry(autoro="Voltaire", verko="Candide:1759")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "aŭtoro: Voltaire" in result.output
        assert "verko: Candide:1759" in result.output
        assert "kreita:" not in result.output
        assert "modifita:" not in result.output

    def test_vidi_a_shows_timestamps(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID, "-a"])
        assert result.exit_code == 0
        assert "kreita:" in result.output

    def test_uuid_prefix_works(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "aaaaaaaa"])
        assert result.exit_code == 0

    def test_uuid_prefix_with_hash_works(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "#aaaaaaaa"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_vidi_teksto_option_alias_works(self):
        entry = _make_entry(teksto="saluton")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "-T", "saluton"])
        assert result.exit_code == 0, result.output
        assert "saluton" in result.output

    def test_vidi_kopii_copies_short_uuid(self, monkeypatch):
        entry = _make_entry()
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID, "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"] == "#aaaaaaaa"

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi", "notfound"])
        assert result.exit_code != 0

    def test_vidi_copy_without_ref_fails(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi", "--kopii"])
        assert result.exit_code != 0
        assert "postulas UUID" in (result.output + (result.stderr or ""))

    def test_vidi_html_without_ref_fails(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi", "--html"])
        assert result.exit_code != 0
        assert "postulas UUID" in (result.output + (result.stderr or ""))

    def test_vidi_html_conflicts_with_copy_options(self):
        entry = _make_entry()
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app, ["vorto", "vidi", SAMPLE_UUID, "--html", "--kopii"]
            )
        assert result.exit_code != 0
        assert "ne kongruas kun --html" in (result.output + (result.stderr or ""))

    def test_vidi_html_opens_entry_preview_in_browser(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(
                "autish.commands.vorto._open_entry_preview_file",
                return_value="/tmp/vorto-preview.html",
            ) as mock_open_preview,
        ):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID, "--html"])
        assert result.exit_code == 0, result.output
        assert "Malfermas en retumilo: /tmp/vorto-preview.html" in result.output
        mock_open_preview.assert_called_once_with(entry, [entry], montri_cxion=False)

    def test_display_entry_formats_linked_content_and_bold_definitions(self):
        linked = _make_entry(
            uuid=SAMPLE_UUID2,
            teksto="bonjour",
            difinoj=["a very long description that should be abbreviated for display"],
        )
        entry = _make_entry(ligiloj=[SAMPLE_UUID2], difinoj=["short def"])
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_entry(entry, [entry, linked])
        panel = mock_print.call_args[0][0]
        rendered = panel.renderable
        assert isinstance(rendered, Group)
        md = rendered.renderables[2]
        assert md.__class__.__name__ == "Markdown"
        assert "**short def**" in md.markup
        ligiloj_lines = [
            row
            for row in rendered.renderables
            if isinstance(row, Text) and row.plain.startswith("ligiloj:")
        ]
        assert ligiloj_lines
        assert "ligiloj: bonjour (#11111111)" in ligiloj_lines[0].plain
        assert "[bonjour](file://" not in ligiloj_lines[0].plain
        assert any("link " in str(span.style) for span in ligiloj_lines[0].spans)
        assert any(".html" in str(span.style) for span in ligiloj_lines[0].spans)

    def test_vidi_renders_ligiloj_without_raw_markdown(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(ligiloj=[SAMPLE_UUID2])
        with patch(_LOAD, return_value=[entry, linked]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID])
        assert result.exit_code == 0, result.output
        assert "ligiloj: bonjour (#11111111)" in result.output
        assert "[bonjour](file://" not in result.output

    def test_vidi_renders_internal_difino_links_without_raw_markdown(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(difinoj=["rilata al [bonjour](#11111111)"])
        with patch(_LOAD, return_value=[entry, linked]):
            result = runner.invoke(app, ["vorto", "vidi", SAMPLE_UUID])
        assert result.exit_code == 0, result.output
        assert "[bonjour](" not in result.output
        assert "bonjour" in result.output
        assert "(#11111111)" not in result.output

    def test_display_entry_renders_markdown_in_difino_and_uzo(self):
        entry = _make_entry(
            difinoj=["(de l'allemand _ambivalent_) qui présente une ambivalence"],
            uzoj=["_ekzemplo_ de uzo"],
        )
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_entry(entry, [entry])
        panel = mock_print.call_args[0][0]
        rendered = panel.renderable
        assert isinstance(rendered, Group)
        assert isinstance(rendered.renderables[0], Text)
        assert rendered.renderables[0].plain.endswith(f"#{SAMPLE_UUID[:8]}")
        assert rendered.renderables[0].spans[-1].style == "dim"
        md = rendered.renderables[2]
        assert md.__class__.__name__ == "Markdown"
        assert "en - vorto/substantivo-neŭtra" in md.markup
        assert (
            "**(de l'allemand _ambivalent_) "
            "qui présente une ambivalence**"
        ) in md.markup
        assert "*_ekzemplo_ de uzo*" in md.markup

    def test_display_entry_markdown_link_preview_supports_tipo_lists(self):
        linked = _make_entry(
            uuid=SAMPLE_UUID2,
            teksto="bonjour",
            tipo=["adjektivo"],
            difinoj=["difino de celo"],
        )
        entry = _make_entry(
            tipo=["substantivo-neŭtra"],
            difinoj=["rilata al [bonjour](#11111111)"],
        )
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_entry(entry, [entry, linked])
        panel = mock_print.call_args[0][0]
        md = panel.renderable.renderables[2]
        assert "file://" not in md.markup
        assert ".html)" in md.markup
        assert "(#11111111)" not in md.markup

    def test_display_results_renders_ligiloj_as_clickable_text_without_uuid(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(ligiloj=[SAMPLE_UUID2])
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_results([entry], all_entries=[entry, linked], numerate=True)
        table = mock_print.call_args[0][0]
        assert table.columns[0].header == "#"
        assert table.columns[-1].header == "Ligiloj"
        ligilo_cell = table.columns[-1]._cells[0]
        assert isinstance(ligilo_cell, Text)
        assert "bonjour" in ligilo_cell.plain
        assert "#11111111" not in ligilo_cell.plain
        assert any("link file://" in str(span.style) for span in ligilo_cell.spans)

    def test_display_results_renders_inline_teksto_links_without_uuid(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="frontalement")
        entry = _make_entry(
            teksto="Sa vie [frontalement](#11111111) ...",
            ligiloj=[],
        )
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_results([entry], all_entries=[entry, linked], numerate=False)
        table = mock_print.call_args[0][0]
        teksto_cell = table.columns[1]._cells[0]
        assert isinstance(teksto_cell, Text)
        assert "frontalement" in teksto_cell.plain
        assert "#11111111" not in teksto_cell.plain
        assert any("link file://" in str(span.style) for span in teksto_cell.spans)

    def test_display_entry_single_definition_is_not_numbered(self):
        entry = _make_entry(difinoj=["nur unu difino"], uzoj=["unu uzo"])
        with patch("autish.commands.vorto.console.print") as mock_print:
            _display_entry(entry, [entry])
        panel = mock_print.call_args[0][0]
        md = panel.renderable.renderables[2]
        assert "**nur unu difino**" in md.markup
        assert "**1. nur unu difino**" not in md.markup


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

    def test_modifi_semantika_kopii_copies_reference(self, monkeypatch):
        entry = _make_entry()
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(
                app,
                [
                    "vorto",
                    "modifi",
                    SAMPLE_UUID,
                    "--lingvo",
                    "eo",
                    "--semantika-kopii",
                ],
            )
        assert result.exit_code == 0, result.output
        assert copied["value"] == "[hello](#aaaaaaaa)"

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

    def test_ligilo_update_keeps_links_symmetric(self):
        entry_a = _make_entry(uuid=SAMPLE_UUID, ligiloj=[SAMPLE_UUID2])
        entry_b = _make_entry(uuid=SAMPLE_UUID2, teksto="b", ligiloj=[SAMPLE_UUID])
        entry_c = _make_entry(
            uuid="99999999-2222-3333-4444-555555555555",
            teksto="c",
            ligiloj=[],
        )
        with (
            patch(_LOAD, return_value=[entry_a, entry_b, entry_c]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app,
                [
                    "vorto",
                    "modifi",
                    SAMPLE_UUID,
                    "-L",
                    "99999999-2222-3333-4444-555555555555",
                ],
            )
        saved_entries = mock_save.call_args[0][0]
        saved_a = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID)
        saved_b = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID2)
        saved_c = next(
            e
            for e in saved_entries
            if e["uuid"] == "99999999-2222-3333-4444-555555555555"
        )
        assert saved_a["ligiloj"] == ["99999999-2222-3333-4444-555555555555"]
        assert SAMPLE_UUID not in saved_b["ligiloj"]
        assert SAMPLE_UUID in saved_c["ligiloj"]


class TestTuiSaveModified:
    def test_parses_inline_links_from_new_text_fields(self):
        encik_uuid = "4feb123f-aaaa-bbbb-cccc-ddddeeeeffff"
        old_entry = _make_entry(uuid=SAMPLE_UUID, ligiloj=[])
        entry = _make_entry(
            uuid=SAMPLE_UUID,
            ligiloj=[],
            autoro="Aŭtoro [nodo](ec#4feb123f)",
            verko="Verko [bonjour](#11111111)",
            uzoj=["uzo [bonjour](#11111111)"],
        )
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour", ligiloj=[])
        with (
            patch(_LOAD, return_value=[dict(old_entry), linked]),
            patch(_SAVE) as mock_save,
            patch(
                "autish.commands.vorto._find_encik_entry",
                return_value={"uuid": encik_uuid, "titolo": "Encik Nodo"},
            ),
            patch("autish.commands.vorto._push_undo"),
        ):
            _tui_save_modified(entry, old_entry)
        saved_entries = mock_save.call_args[0][0]
        saved = next(e for e in saved_entries if e["uuid"] == SAMPLE_UUID)
        assert SAMPLE_UUID2 in saved["ligiloj"]
        assert f"ec#{encik_uuid}" in saved["ligiloj"]


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

    def test_text_filter_ignores_accents_by_default(self):
        accented_entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="ĵurnalo", lingvo="eo", nivelo=1.0)
        ]
        with patch(_LOAD, return_value=accented_entries):
            result = runner.invoke(app, ["vorto", "serci", "jurnalo"])
        assert result.exit_code == 0, result.output
        assert "ĵurnalo" in result.output

    def test_single_result_displays_entry_directly(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "hello"])
        assert result.exit_code == 0
        assert "hello  #aaaaaaaa" in result.output
        assert "rezulto(j) trovita(j)" not in result.output
        assert "UUID" not in result.output

    def test_serci_kopii_requires_query(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "--kopii"])
        assert result.exit_code != 0
        assert "postulas serĉan demandon" in (result.output + (result.stderr or ""))

    def test_serci_rejects_both_copy_modes(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(
                app,
                ["vorto", "serci", "hello", "--kopii", "--semantika-kopii"],
            )
        assert result.exit_code != 0
        assert "Uzu nur unu el --kopii aŭ --semantika-kopii." in (
            result.output + (result.stderr or "")
        )

    def test_serci_kopii_copies_single_match(self, monkeypatch):
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "hello", "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"] == "#aaaaaaaa"

    def test_serci_semantika_kopii_copies_interactively_selected_match(
        self, monkeypatch
    ):
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(
                app,
                ["vorto", "serci", "o", "--semantika-kopii"],
                input="2\n",
            )
        assert result.exit_code == 0, result.output
        assert copied["value"] == "[saluton](#11111111)"
        assert "saluton  #11111111" in result.output

    def test_serci_semantika_kopii_strips_parenthesized_parts_in_title(
        self, monkeypatch
    ):
        copied: dict[str, str] = {}
        entries = [
            _make_entry(
                uuid=SAMPLE_UUID,
                teksto="Teorio (speciala) de lumo (malambiguigo)",
            )
        ]

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(
                app,
                ["vorto", "serci", "Teorio", "--semantika-kopii"],
            )
        assert result.exit_code == 0, result.output
        assert copied["value"] == "[Teorio de lumo](#aaaaaaaa)"

    def test_serci_copy_selection_view_is_numbered(self):
        with (
            patch(_LOAD, return_value=self.entries),
            patch("autish.commands.vorto._display_results") as mock_display_results,
        ):
            result = runner.invoke(
                app,
                ["vorto", "serci", "o", "--semantika-kopii"],
                input="\n",
            )
        assert result.exit_code == 0, result.output
        assert mock_display_results.call_args.kwargs.get("numerate") is True

    def test_serci_semantika_kopii_no_results_skips_prompt(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(
                app,
                ["vorto", "serci", "zzzzzzzzzzzz", "--semantika-kopii"],
            )
        assert result.exit_code == 0, result.output
        assert "Neniu rezulto trovita." in result.output
        assert "Elektu numeron por kopii" not in result.output

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

    def test_serci_default_limo_is_10(self):
        many = [
            _make_entry(uuid=str(uuid.uuid4()), teksto=f"match{i}")
            for i in range(25)
        ]
        with patch(_LOAD, return_value=many):
            result = runner.invoke(app, ["vorto", "serci", "match"])
        assert result.exit_code == 0
        assert "10 rezulto" in result.output

    def test_ligilo_search_default_one_hop(self):
        a = _make_entry(uuid=SAMPLE_UUID, teksto="a", ligiloj=[SAMPLE_UUID2])
        b = _make_entry(uuid=SAMPLE_UUID2, teksto="b", ligiloj=[SAMPLE_UUID])
        c = _make_entry(
            uuid="22222222-3333-4444-5555-666666666666",
            teksto="c",
            ligiloj=[SAMPLE_UUID2],
        )
        with patch(_LOAD, return_value=[a, b, c]):
            result = runner.invoke(app, ["vorto", "serci", "--ligilo", "aaaaaaaa"])
        assert result.exit_code == 0
        assert "b" in result.output
        assert "c" not in result.output

    def test_serci_copy_modes_reject_ligilo_search(self):
        a = _make_entry(uuid=SAMPLE_UUID, teksto="a", ligiloj=[SAMPLE_UUID2])
        b = _make_entry(uuid=SAMPLE_UUID2, teksto="b", ligiloj=[SAMPLE_UUID])
        with patch(_LOAD, return_value=[a, b]):
            result = runner.invoke(
                app,
                ["vorto", "serci", "a", "--ligilo", "aaaaaaaa", "--kopii"],
            )
        assert result.exit_code != 0
        assert "--kopii/--semantika-kopii ne kongruas kun --ligilo." in (
            result.output + (result.stderr or "")
        )

    def test_ligilo_search_multiple_hops_with_limo(self):
        a = _make_entry(uuid=SAMPLE_UUID, teksto="a", ligiloj=[SAMPLE_UUID2])
        b = _make_entry(uuid=SAMPLE_UUID2, teksto="b", ligiloj=[SAMPLE_UUID])
        c = _make_entry(
            uuid="22222222-3333-4444-5555-666666666666",
            teksto="c",
            ligiloj=[SAMPLE_UUID2],
        )
        with patch(_LOAD, return_value=[a, b, c]):
            result = runner.invoke(
                app, ["vorto", "serci", "--ligilo", "aaaaaaaa", "--limo", "2"]
            )
        assert result.exit_code == 0
        assert "b" in result.output
        assert "c" in result.output

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

    def test_fuzzy_fallback_enabled_by_default(self):
        entries = [_make_entry(teksto="saluton")]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "saluotn"])
        assert result.exit_code == 0
        assert "similajn kongruojn" in result.output
        assert "saluton" in result.output

    def test_preciza_flag_disables_fuzzy_fallback(self):
        entries = [_make_entry(teksto="saluton")]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "saluotn", "--preciza"])
        assert result.exit_code == 0
        assert "similajn kongruojn" not in result.output
        assert "0 rezulto" in result.output

    def test_autoro_filter(self):
        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello", autoro="Smith"),
            _make_entry(uuid=SAMPLE_UUID2, teksto="world", autoro="Jones"),
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "--autoro", "Smith"])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "world" not in result.output

    def test_autoro_filter_case_insensitive(self):
        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello", autoro="Smith"),
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "--autoro", "smith"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_verko_filter(self):
        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello", verko="Book:2020"),
            _make_entry(uuid=SAMPLE_UUID2, teksto="world", verko="Novel:2019"),
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "--verko", "Book"])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "world" not in result.output

    def test_verko_filter_partial_match(self):
        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="hello", verko="Book:2020"),
        ]
        with patch(_LOAD, return_value=entries):
            result = runner.invoke(app, ["vorto", "serci", "--verko", "2020"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_uuid_option_outputs_json_list(self):
        with patch(_LOAD, return_value=self.entries):
            result = runner.invoke(app, ["vorto", "serci", "--uuid"])
        assert result.exit_code == 0
        assert result.output.strip() == '["aaaaaaaa", "11111111"]'


class TestForigi:
    def test_deletes_entry(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_MOVE_TO_RUBUJO) as mock_move,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
        ):
            result = runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        assert result.exit_code == 0
        mock_move.assert_called_once_with(entry)

    def test_cancelled_keeps_entry(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_MOVE_TO_RUBUJO) as mock_move,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="n"),
        ):
            runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        mock_move.assert_not_called()

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "forigi", "notfound"])
        assert result.exit_code != 0

    def test_pushes_to_undo_stack(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_MOVE_TO_RUBUJO),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO) as mock_save_undo,
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
        ):
            runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        saved_stack = mock_save_undo.call_args[0][0]
        assert saved_stack[-1]["op"] == "forigi"
        assert saved_stack[-1]["uuid"] == SAMPLE_UUID

    def test_deletes_entry_with_hash_uuid_prefix(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_MOVE_TO_RUBUJO) as mock_move,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
        ):
            result = runner.invoke(app, ["vorto", "forigi", "#aaaaaaaa"])
        assert result.exit_code == 0
        mock_move.assert_called_once_with(entry)

    def test_warns_about_broken_ligilo_references(self):
        entry = _make_entry(uuid=SAMPLE_UUID, teksto="a")
        referencer = _make_entry(uuid=SAMPLE_UUID2, teksto="b", ligiloj=[SAMPLE_UUID])
        with (
            patch(_LOAD, return_value=[entry, referencer]),
            patch(_MOVE_TO_RUBUJO),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="n"),
        ):
            result = runner.invoke(app, ["vorto", "forigi", SAMPLE_UUID])
        assert result.exit_code == 0
        assert "Averto" in result.output
        assert "rompos referencojn" in result.output
        assert "ligilo" in result.output

    def test_forigi_supports_multiple_targets(self):
        a = _make_entry(uuid=SAMPLE_UUID, teksto="a")
        b = _make_entry(uuid=SAMPLE_UUID2, teksto="b")
        with (
            patch(_LOAD, return_value=[a, b]),
            patch(_MOVE_TO_RUBUJO) as mock_move,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
        ):
            result = runner.invoke(app, ["vorto", "forigi", "aaaaaaaa", "11111111"])
        assert result.exit_code == 0
        assert mock_move.call_count == 2
        assert "2 eniro(j)" in result.output

    def test_forigi_supports_json_list_target(self):
        a = _make_entry(uuid=SAMPLE_UUID, teksto="a")
        b = _make_entry(uuid=SAMPLE_UUID2, teksto="b")
        with (
            patch(_LOAD, return_value=[a, b]),
            patch(_MOVE_TO_RUBUJO) as mock_move,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
        ):
            result = runner.invoke(
                app, ["vorto", "forigi", '["11111111","aaaaaaaa"]']
            )
        assert result.exit_code == 0
        assert mock_move.call_count == 2


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
        stack = [{"op": "forigi", "uuid": SAMPLE_UUID}]
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=stack),
            patch(_SAVE_UNDO),
            patch(_RECOVER_FROM_RUBUJO, return_value=entry) as mock_recover,
        ):
            result = runner.invoke(app, ["vorto", "malfari"])
        assert result.exit_code == 0
        mock_recover.assert_called_once_with(SAMPLE_UUID)
        # _save_entries not called directly (recovery happens in _recover_from_rubujo)
        mock_save.assert_not_called()

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

    def test_vorto_serci_help_is_localized_in_esperanto(self, monkeypatch):
        monkeypatch.setenv("LANG", "eo_FR.UTF-8")
        result = runner.invoke(app, ["vorto", "serci", "--help"])
        assert result.exit_code == 0
        assert "Filter by language code." not in result.output
        assert "Filtri laŭ lingvokodo." in result.output
        assert "Disable fuzzy fallback matching." not in result.output
        assert "Malŝalti malklaran rezervan kongruigon." in result.output
        assert "Search the wordbank." not in result.output
        assert "Serĉi en la vortaro." in result.output

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

    def test_single_definition_not_numbered(self):
        entry = _make_entry(difinoj=["a greeting"])
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "    a greeting" in joined
        assert "1. a greeting" not in joined

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

    def test_tipo_list_is_rendered_without_type_error(self):
        entry = _make_entry(tipo=["adjektivo", "substantivo-neŭtra"])
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "vorto/adjektivo, substantivo-neŭtra" in joined

    def test_internal_markdown_links_are_rendered_as_plain_text(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(
            difinoj=["rilata al [bonjour](#11111111)"],
            uzoj=["uzo kun [bonjour](#11111111)"],
        )
        lines = _entry_to_lines(entry, all_entries=[entry, linked], montri_cxion=False)
        joined = "\n".join(lines)
        assert "[bonjour](" not in joined
        assert "bonjour" in joined
        assert "(#11111111)" not in joined

    def test_ligiloj_are_rendered_with_human_readable_labels(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(ligiloj=[SAMPLE_UUID2])
        lines = _entry_to_lines(entry, all_entries=[entry, linked], montri_cxion=False)
        joined = "\n".join(lines)
        assert "ligiloj:" in joined
        assert "bonjour (#11111111)" in joined


class TestEntryPreviewHtml:
    def test_default_preview_hides_timestamps(self):
        entry = _make_entry(modifita_je="2024-01-02T00:00:00+00:00")
        html = _render_entry_preview_html(entry, [entry], montri_cxion=False)
        assert "kreita" not in html
        assert "modifita" not in html

    def test_full_preview_shows_timestamps(self):
        entry = _make_entry(modifita_je="2024-01-02T00:00:00+00:00")
        html = _render_entry_preview_html(entry, [entry], montri_cxion=True)
        assert "kreita" in html
        assert "modifita" in html


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

    def test_ligiloj_column_uses_human_readable_labels(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="bonjour")
        entry = _make_entry(ligiloj=[SAMPLE_UUID2])
        lines = _entries_to_lines([entry], all_entries=[entry, linked])
        joined = "\n".join(lines)
        assert "Ligiloj" in lines[0]
        assert "bonjour" in joined
        assert "#11111111" not in joined

    def test_teksto_column_renders_inline_links_as_labels(self):
        linked = _make_entry(uuid=SAMPLE_UUID2, teksto="frontalement")
        entry = _make_entry(teksto="Sa vie [frontalement](#11111111) ...", ligiloj=[])
        lines = _entries_to_lines([entry], all_entries=[entry, linked])
        joined = "\n".join(lines)
        assert "frontalement" in joined
        assert "#11111111" not in joined


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

    def test_ctrl_w_deletes_previous_word_in_insert(self):
        ed = self._make_editor("saluton mondo")
        ed.handle_key(23)  # Ctrl+W
        assert ed.text == "saluton "

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

    def test_visual_delete_matches_selected_range(self):
        ed = self._make_editor("abcdef", insert=False)
        ed.pos = 1
        ed.handle_key(ord("v"))
        ed.handle_key(ord("l"))
        ed.handle_key(ord("l"))
        ed.handle_key(ord("d"))
        # Selected bcd (indices 1..3) should be removed, no extra character.
        assert ed.text == "aef"

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
        # Simulate 'g' followed by 'g' — _getch_unicode uses get_wch()
        stdscr.get_wch.return_value = ord("g")
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
        assert p._mode == "VISUAL_CHAR"

    def test_visual_line_mode(self):
        p = self._make_pager()
        p._normal_key(ord("V"), "V")
        assert p._mode == "VISUAL_LINE"

    def test_q_returns_back(self):
        p = self._make_pager()
        result = p._normal_key(ord("q"), "q")
        assert result == "back"

    def test_colon_q_alias_returns_back(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import Pager

        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        stdscr.get_wch.return_value = ord("q")
        pager = Pager(stdscr, ["line"], title="test")

        result = pager._normal_key(ord(":"), ":")

        assert result == "back"

    def test_x_in_results_selects_current_entry_for_delete(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import Pager

        entries = [
            _make_entry(uuid=SAMPLE_UUID, teksto="alpha"),
            _make_entry(uuid=SAMPLE_UUID2, teksto="beta"),
        ]
        lines = _entries_to_lines(entries)
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        pager = Pager(stdscr, lines, entries=entries, entry_line_offset=2)
        pager.row = 3  # second data row (after header + separator)

        result = pager._normal_key(ord("x"), "x")

        assert result == "delete_entry"
        assert pager.selected_entry is entries[1]

    def test_getch_unicode_decodes_ctrl_right_escape_sequence(self):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod

        stdscr = MagicMock()
        stdscr.get_wch.side_effect = [
            "\x1b",
            "[",
            "1",
            ";",
            "5",
            "C",
            tui_mod.curses.error(),
        ]

        key = tui_mod._getch_unicode(stdscr)

        assert key == tui_mod._CTRL_RIGHT

    def test_getch_unicode_decodes_ctrl_left_escape_sequence(self):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod

        stdscr = MagicMock()
        stdscr.get_wch.side_effect = [
            "\x1b",
            "[",
            "1",
            ";",
            "5",
            "D",
            tui_mod.curses.error(),
        ]

        key = tui_mod._getch_unicode(stdscr)

        assert key == tui_mod._CTRL_LEFT


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


class TestEksporti:
    def test_eksporti_full_json_still_supported(self, tmp_path):
        out_path = tmp_path / "vorto.json"
        with patch(_LOAD, return_value=[_make_entry()]):
            result = runner.invoke(app, ["vorto", "eksporti", str(out_path)])
        assert result.exit_code == 0, result.output
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert '"teksto": "hello"' in content

    def test_eksporti_single_entry_to_toml_by_uuid(self, tmp_path):
        out_path = tmp_path / "unuopa.toml"
        entry = _make_entry(teksto="saluton")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", SAMPLE_UUID, str(out_path)],
            )
        assert result.exit_code == 0, result.output
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert 'teksto = "saluton"' in content
        assert f'uuid = "{SAMPLE_UUID}"' in content

    def test_eksporti_single_entry_uses_selection_when_no_exact_match(
        self, tmp_path
    ):
        out_path = tmp_path / "fuzzy.toml"
        first = _make_entry(uuid=SAMPLE_UUID, teksto="saluton")
        second = _make_entry(uuid=SAMPLE_UUID2, teksto="salubrigi")
        with patch(_LOAD, return_value=[first, second]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", "salu", str(out_path)],
                input="2\n",
            )
        assert result.exit_code == 0, result.output
        content = out_path.read_text(encoding="utf-8")
        assert 'teksto = "salubrigi"' in content
        assert f'uuid = "{SAMPLE_UUID2}"' in content

    def test_eksporti_single_entry_directory_path_appends_default_filename(
        self, tmp_path
    ):
        entry = _make_entry(uuid=SAMPLE_UUID, teksto="tre longa teksto")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", SAMPLE_UUID, str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        exported = list(tmp_path.glob("*.toml"))
        assert exported
        content = exported[0].read_text(encoding="utf-8")
        assert f'uuid = "{SAMPLE_UUID}"' in content

    def test_eksporti_single_entry_omits_empty_etikedoj_table(self, tmp_path):
        out_path = tmp_path / "sen-etikedoj.toml"
        entry = _make_entry(uuid=SAMPLE_UUID, teksto="sen-etikedoj", etikedoj={})
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", SAMPLE_UUID, str(out_path)],
            )
        assert result.exit_code == 0, result.output
        content = out_path.read_text(encoding="utf-8")
        assert "[etikedoj]" not in content

    def test_eksporti_single_entry_default_filename_transliterates_accents(
        self, tmp_path
    ):
        entry = _make_entry(uuid=SAMPLE_UUID, teksto="façade système")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", SAMPLE_UUID, str(tmp_path)],
            )
        assert result.exit_code == 0, result.output
        exported = list(tmp_path.glob("*.toml"))
        assert exported
        assert "facade-systeme" in exported[0].name

    def test_eksporti_single_entry_keeps_utf8_text_human_readable(self, tmp_path):
        out_path = tmp_path / "utf8.toml"
        entry = _make_entry(
            uuid=SAMPLE_UUID,
            teksto="système",
            difinoj=["français façade"],
        )
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(
                app,
                ["vorto", "eksporti", SAMPLE_UUID, str(out_path)],
            )
        assert result.exit_code == 0, result.output
        content = out_path.read_text(encoding="utf-8")
        assert "système" in content
        assert "français façade" in content
        assert "\\u00" not in content


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

    def test_visual_render_highlights_only_selected_range(self):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod

        ed = self._make_editor("abcdef", insert=False)
        ed.mode = "VISUAL"
        ed.visual_start = 1
        ed.pos = 3
        win = MagicMock()

        ed.render(win, row=1, col=0, width=20, focused=True)

        calls = win.addstr.call_args_list
        assert calls
        # Base line render should stay readable instead of highlighting everything.
        assert calls[0].args[3] != tui_mod.curses.A_STANDOUT

        selected_cols = {
            c.args[1]
            for c in calls
            if len(c.args) >= 4
            and c.args[0] == 1
            and c.args[3] == tui_mod.curses.A_STANDOUT
        }
        assert {1, 2, 3}.issubset(selected_cols)


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

    def test_collect_parses_new_uzoj_autoro_verko_fields(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import FormEditor
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (40, 120)
        form = FormEditor(
            stdscr,
            title="Test",
            initial={
                "uzoj": ["uzo 1", "uzo 2"],
                "autoro": "Voltaire",
                "verko": "Candide:1759",
            },
        )
        values = form._collect()
        assert values["uzoj"] == ["uzo 1", "uzo 2"]
        assert values["autoro"] == "Voltaire"
        assert values["verko"] == "Candide:1759"


class TestVortoTuiModifi:
    def test_modifi_updates_uzoj_autoro_verko_fields(self):
        from unittest.mock import MagicMock, patch

        from autish.commands._vorto_tui import VortoTUI

        saved: dict[str, dict] = {}

        def _save_modified(entry: dict, old_entry: dict) -> None:
            saved["entry"] = dict(entry)
            saved["old"] = dict(old_entry)

        tui = VortoTUI(
            load_entries=lambda: [],
            save_new_entry=lambda _entry: None,
            save_modified_entry=_save_modified,
            delete_entry=lambda _entry: None,
            undo=lambda: "",
            render_entry=lambda _entry: [],
            render_results=lambda _entries: [],
            detect_kategorio=lambda _text: "vorto",
            normalize_tipo=lambda raw: [raw] if raw else None,
            normalize_tono=lambda raw: raw,
            parse_etikedo=lambda _items: {},
            find_entry=lambda _uid, _entries: None,
            now_iso=lambda: "2024-01-02T00:00:00+00:00",
            make_uuid=lambda: SAMPLE_UUID,
        )
        tui.stdscr = MagicMock()
        entry = _make_entry(uzoj=["malnova uzo"], autoro="Malnova", verko="Malnova")
        form_values = {
            "teksto": "hello",
            "lingvo": "en",
            "difinoj": ["nova difino"],
            "uzoj": ["nova uzo"],
            "tipo": "aj",
            "temo": "temo",
            "tono": "nf",
            "nivelo": 2.0,
            "autoro": "Voltaire",
            "verko": "Candide:1759",
            "etikedoj": {},
            "ligiloj": [],
        }
        with patch(
            "autish.commands._vorto_tui.FormEditor.run",
            return_value=form_values,
        ):
            tui._do_modifi_entry(entry)
        assert saved["entry"]["uzoj"] == ["nova uzo"]
        assert saved["entry"]["autoro"] == "Voltaire"
        assert saved["entry"]["verko"] == "Candide:1759"
        assert saved["old"]["uzoj"] == ["malnova uzo"]
        assert saved["old"]["autoro"] == "Malnova"


class TestVortoTuiWelcomeRendering:
    def test_draw_welcome_partial_redraw_only_updates_status_line(self):
        from unittest.mock import MagicMock

        from autish.commands._vorto_tui import VortoTUI

        tui = object.__new__(VortoTUI)
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        tui.stdscr = stdscr
        tui._mode = "COMMAND"
        tui._cmd_buf = "serci testo"
        tui._status_msg = ""

        tui._draw_welcome(full=False)

        stdscr.erase.assert_not_called()
        status_call = stdscr.addstr.call_args_list[-1]
        assert status_call.args[0] == 23
        assert ":serci testo" in status_call.args[2]

    def test_prompt_inline_uses_partial_redraw_while_typing(self, monkeypatch):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod
        from autish.commands._vorto_tui import VortoTUI

        tui = object.__new__(VortoTUI)
        stdscr = MagicMock()
        stdscr.getmaxyx.return_value = (24, 80)
        tui.stdscr = stdscr

        draw_calls: list[tuple[bool, bool]] = []

        def _fake_draw(*, full: bool = True, manage_cursor: bool = True) -> None:
            draw_calls.append((full, manage_cursor))

        tui._draw_welcome = _fake_draw  # type: ignore[assignment]
        keys = iter([ord("a"), ord("b"), ord("\n")])
        monkeypatch.setattr(tui_mod, "_getch_unicode", lambda _win: next(keys))
        monkeypatch.setattr(tui_mod.curses, "curs_set", lambda _value: None)

        assert tui._prompt_inline("Demando") == "ab"
        assert draw_calls[0] == (True, False)
        assert any(full is False and manage is False for full, manage in draw_calls[1:])


class TestVortoTuiSearchPager:
    def test_do_serci_starts_on_first_content_line(self, monkeypatch):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod
        from autish.commands._vorto_tui import VortoTUI

        entry = _make_entry(uuid=SAMPLE_UUID, teksto="alpha")
        observed_rows: list[int] = []

        def _fake_run(self) -> str:
            observed_rows.append(self.row)
            return "back"

        monkeypatch.setattr(tui_mod.Pager, "run", _fake_run)
        monkeypatch.setattr(tui_mod.curses, "curs_set", lambda _value: None)

        tui = VortoTUI(
            load_entries=lambda: [entry],
            save_new_entry=lambda _entry: None,
            save_modified_entry=lambda _entry, _old: None,
            delete_entry=lambda _entry: None,
            undo=lambda: "",
            render_entry=lambda _entry: [],
            render_results=lambda rows: _entries_to_lines(rows),
            detect_kategorio=lambda _text: "vorto",
            normalize_tipo=lambda raw: [raw] if raw else None,
            normalize_tono=lambda raw: raw,
            parse_etikedo=lambda _items: {},
            find_entry=lambda _uid, _entries: None,
            now_iso=lambda: "2024-01-01T00:00:00+00:00",
            make_uuid=lambda: SAMPLE_UUID2,
        )
        tui.stdscr = MagicMock()

        tui._do_serci("alpha")

        assert observed_rows
        assert observed_rows[0] == 2

    def test_do_serci_x_deletes_selected_entry_with_confirmation(self, monkeypatch):
        from unittest.mock import MagicMock

        import autish.commands._vorto_tui as tui_mod
        from autish.commands._vorto_tui import VortoTUI

        db_entries = [_make_entry(uuid=SAMPLE_UUID, teksto="alpha")]
        deleted: list[str] = []
        run_calls = {"count": 0}

        def _fake_run(self) -> str:
            if run_calls["count"] == 0:
                run_calls["count"] += 1
                self.selected_entry = self.entries[0] if self.entries else None
                return "delete_entry"
            return "back"

        def _delete(entry: dict) -> None:
            deleted.append(entry["uuid"])
            db_entries[:] = [e for e in db_entries if e["uuid"] != entry["uuid"]]

        monkeypatch.setattr(tui_mod.Pager, "run", _fake_run)
        monkeypatch.setattr(tui_mod.curses, "curs_set", lambda _value: None)

        tui = VortoTUI(
            load_entries=lambda: list(db_entries),
            save_new_entry=lambda _entry: None,
            save_modified_entry=lambda _entry, _old: None,
            delete_entry=_delete,
            undo=lambda: "",
            render_entry=lambda _entry: [],
            render_results=lambda rows: _entries_to_lines(rows),
            detect_kategorio=lambda _text: "vorto",
            normalize_tipo=lambda raw: [raw] if raw else None,
            normalize_tono=lambda raw: raw,
            parse_etikedo=lambda _items: {},
            find_entry=lambda _uid, _entries: None,
            now_iso=lambda: "2024-01-01T00:00:00+00:00",
            make_uuid=lambda: SAMPLE_UUID2,
        )
        tui.stdscr = MagicMock()
        tui._prompt_confirm = lambda _msg: True  # type: ignore[assignment]

        tui._do_serci("alpha")

        assert deleted == [SAMPLE_UUID]
        assert not db_entries


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

    def test_ctrl_right_jumps_to_next_word(self):
        import autish.commands._vorto_tui as tui_mod

        p = self._make_pager(["unu du tri"])
        p.char_pos = 0
        p._normal_key(tui_mod._CTRL_RIGHT, "")
        assert p.char_pos == 4

    def test_ctrl_left_jumps_to_previous_word(self):
        import autish.commands._vorto_tui as tui_mod

        p = self._make_pager(["unu du tri"])
        p.char_pos = 7
        p._normal_key(tui_mod._CTRL_LEFT, "")
        assert p.char_pos == 4

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


# ──────────────────────────────────────────────────────────────────────────────
# Rubujo (recycle bin) tests
# ──────────────────────────────────────────────────────────────────────────────

_LOAD_RUBUJO = "autish.commands.vorto._load_rubujo"
_MOVE_RUBUJO = "autish.commands.vorto._move_to_rubujo"
_RECOVER = "autish.commands.vorto._recover_from_rubujo"
_PERM_DELETE = "autish.commands.vorto._permanent_delete_from_rubujo"
_CLEANUP = "autish.commands.vorto._cleanup_old_rubujo"


def _make_rubujo_entry(**kwargs) -> dict:
    base = _make_entry(**kwargs)
    base["forigita_je"] = "2024-06-01T12:00:00+00:00"
    return base


class TestRubujoListi:
    def test_empty_bin_message(self):
        with (
            patch(_LOAD_RUBUJO, return_value=[]),
            patch(_CLEANUP, return_value=0),
        ):
            result = runner.invoke(app, ["vorto", "rubujo"])
        assert result.exit_code == 0
        assert "0 eniro" in result.output

    def test_shows_entry_in_bin(self):
        entry = _make_rubujo_entry()
        with (
            patch(_LOAD_RUBUJO, return_value=[entry]),
            patch(_CLEANUP, return_value=0),
        ):
            result = runner.invoke(app, ["vorto", "rubujo"])
        assert result.exit_code == 0
        assert "hello" in result.output


class TestRubujoReakiri:
    def test_recovers_entry(self):
        entry = _make_rubujo_entry()
        with (
            patch(_LOAD_RUBUJO, return_value=[entry]),
            patch(_RECOVER, return_value=entry) as mock_rec,
        ):
            result = runner.invoke(app, ["vorto", "rubujo", "reakiri", SAMPLE_UUID])
        assert result.exit_code == 0
        mock_rec.assert_called_once_with(SAMPLE_UUID)

    def test_not_found_exits_nonzero(self):
        with patch(_LOAD_RUBUJO, return_value=[]):
            result = runner.invoke(app, ["vorto", "rubujo", "reakiri", "notfound"])
        assert result.exit_code != 0


class TestRubujoForigi:
    def test_perm_deletes_with_confirm(self):
        entry = _make_rubujo_entry()
        with (
            patch(_LOAD_RUBUJO, return_value=[entry]),
            patch(_PERM_DELETE, return_value=True) as mock_del,
            patch("autish.commands.vorto.typer.prompt", return_value="y"),
        ):
            result = runner.invoke(
                app, ["vorto", "rubujo", "forigi", SAMPLE_UUID]
            )
        assert result.exit_code == 0
        mock_del.assert_called_once_with(SAMPLE_UUID)

    def test_cancelled_does_not_delete(self):
        entry = _make_rubujo_entry()
        with (
            patch(_LOAD_RUBUJO, return_value=[entry]),
            patch(_PERM_DELETE) as mock_del,
            patch("autish.commands.vorto.typer.prompt", return_value="N"),
        ):
            runner.invoke(app, ["vorto", "rubujo", "forigi", SAMPLE_UUID])
        mock_del.assert_not_called()

    def test_justa_flag_skips_confirm(self):
        entry = _make_rubujo_entry()
        with (
            patch(_LOAD_RUBUJO, return_value=[entry]),
            patch(_PERM_DELETE, return_value=True) as mock_del,
        ):
            result = runner.invoke(
                app,
                ["vorto", "rubujo", "forigi", "--justa", SAMPLE_UUID],
            )
        assert result.exit_code == 0
        mock_del.assert_called_once_with(SAMPLE_UUID)


class TestRubujoSubcommandVisible:
    def test_rubujo_in_vorto_help(self):
        result = runner.invoke(app, ["vorto", "--help"])
        assert result.exit_code == 0
        assert "rubujo" in result.output


# ──────────────────────────────────────────────────────────────────────────────
# New helper tests — French ligature normalization and OE folding
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyFrenchLigatures:
    def test_lowercase_oe_becomes_oe_ligature(self):
        assert _apply_french_ligatures("coeur") == "cœur"

    def test_uppercase_OE_becomes_OE_ligature(self):
        assert _apply_french_ligatures("OEUVRE") == "ŒUVRE"

    def test_mixed_case_Oe_followed_by_letter_becomes_ligature(self):
        assert _apply_french_ligatures("Oeuvre") == "Œuvre"

    def test_already_has_ligature_unchanged(self):
        assert _apply_french_ligatures("œuvre") == "œuvre"

    def test_no_oe_unchanged(self):
        assert _apply_french_ligatures("bonjour") == "bonjour"

    def test_multiple_occurrences(self):
        result = _apply_french_ligatures("coeur et poeme")
        assert result == "cœur et pœme"


class TestNormalizeOe:
    def test_ligature_folded_to_oe(self):
        assert _normalize_oe("œuvre") == "oeuvre"

    def test_uppercase_ligature_folded(self):
        assert _normalize_oe("Œuvre") == "OEuvre"

    def test_plain_oe_unchanged(self):
        assert _normalize_oe("oeuvre") == "oeuvre"

    def test_no_ligature_unchanged(self):
        assert _normalize_oe("bonjour") == "bonjour"


class TestFuzzyTextMatchesOeEquivalence:
    def test_oe_and_ligature_match(self):
        entry = _make_entry(teksto="œuvre")
        results = _fuzzy_text_matches([entry], "oeuvre")
        assert entry in results

    def test_ligature_and_oe_match(self):
        entry = _make_entry(teksto="oeuvre")
        results = _fuzzy_text_matches([entry], "œuvre")
        assert entry in results


# ──────────────────────────────────────────────────────────────────────────────
# Aldoni French ligature normalization
# ──────────────────────────────────────────────────────────────────────────────


class TestAldoniFrenchLigatures:
    def test_oe_in_teksto_normalized_when_fr(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "coeur", "-l", "fr"])
        saved = mock_save.call_args[0][0][0]
        assert saved["teksto"] == "cœur"

    def test_oe_in_difino_normalized_when_fr(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app,
                ["vorto", "aldoni", "cœur", "-l", "fr", "-d", "organe de poete"],
            )
        saved = mock_save.call_args[0][0][0]
        # "poete" → "pœte" (oe → œ in French)
        assert saved["difinoj"] == ["organe de pœte"]

    def test_non_fr_does_not_normalize(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "coeur", "-l", "en"])
        saved = mock_save.call_args[0][0][0]
        # English 'oe' should not be converted
        assert saved["teksto"] == "coeur"


# ──────────────────────────────────────────────────────────────────────────────
# Modifi French ligature normalization
# ──────────────────────────────────────────────────────────────────────────────


class TestModifiFrenchLigatures:
    def test_oe_in_teksto_normalized_when_lingvo_fr(self):
        entry = _make_entry(lingvo="fr", teksto="coeur")
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID, "--temo", "corps"])
        saved = mock_save.call_args[0][0][0]
        assert saved["teksto"] == "cœur"

    def test_oe_normalized_when_switching_to_fr(self):
        entry = _make_entry(lingvo="en", teksto="oeuvre")
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID, "-l", "fr"])
        saved = mock_save.call_args[0][0][0]
        assert saved["teksto"] == "œuvre"

    def test_oe_in_difinoj_normalized_when_fr(self):
        entry = _make_entry(lingvo="fr", difinoj=["poeme du coeur"])
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "modifi", SAMPLE_UUID, "--temo", "art"])
        saved = mock_save.call_args[0][0][0]
        # "poeme" → "pœme", "coeur" → "cœur"
        assert saved["difinoj"] == ["pœme du cœur"]


# ──────────────────────────────────────────────────────────────────────────────
# Vidi — closest match fallback
# ──────────────────────────────────────────────────────────────────────────────


class TestVidiClosestMatch:
    def test_single_fuzzy_match_shown_automatically(self):
        entry = _make_entry(teksto="hello")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "helo"])
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_multiple_fuzzy_matches_prompts_user(self):
        e1 = _make_entry(uuid=SAMPLE_UUID, teksto="hello")
        e2 = _make_entry(uuid=SAMPLE_UUID2, teksto="helli")
        with (
            patch(_LOAD, return_value=[e1, e2]),
            patch("autish.commands.vorto.typer.prompt", return_value="1"),
        ):
            result = runner.invoke(app, ["vorto", "vidi", "hellx"])
        assert result.exit_code == 0

    def test_fuzzy_matches_user_cancels(self):
        e1 = _make_entry(uuid=SAMPLE_UUID, teksto="hello")
        e2 = _make_entry(uuid=SAMPLE_UUID2, teksto="helli")
        with (
            patch(_LOAD, return_value=[e1, e2]),
            patch("autish.commands.vorto.typer.prompt", return_value=""),
        ):
            result = runner.invoke(app, ["vorto", "vidi", "hellx"])
        assert result.exit_code == 0
        assert "Nuligita" in result.output

    def test_no_fuzzy_match_exits_nonzero(self):
        with patch(_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "vidi", "zzzzzzzzz"])
        assert result.exit_code != 0

    def test_oe_and_ligature_interchangeable_in_vidi(self):
        entry = _make_entry(teksto="œuvre")
        with patch(_LOAD, return_value=[entry]):
            result = runner.invoke(app, ["vorto", "vidi", "oeuvre"])
        assert result.exit_code == 0
        assert "œuvre" in result.output


# ──────────────────────────────────────────────────────────────────────────────
# New fields: autoro and verko
# ──────────────────────────────────────────────────────────────────────────────


class TestAldoniautoroVerko:
    """Tests for --autoro/-A and --verko/-v options in aldoni."""

    def test_aldoni_saves_autoro(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app, ["vorto", "aldoni", "hello", "-A", "John Doe"]
            )
        saved = mock_save.call_args[0][0][0]
        assert saved["autoro"] == "John Doe"

    def test_aldoni_saves_verko(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app, ["vorto", "aldoni", "hello", "-v", "My Book:2023"]
            )
        saved = mock_save.call_args[0][0][0]
        assert saved["verko"] == "My Book:2023"

    def test_aldoni_without_autoro_verko_stores_none(self):
        with (
            patch(_LOAD, return_value=[]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello"])
        saved = mock_save.call_args[0][0][0]
        assert saved.get("autoro") is None
        assert saved.get("verko") is None

    def test_aldoni_long_flags_autoro_verko(self):
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
                    "--autoro",
                    "Jane Austen",
                    "--verko",
                    "Pride:1813",
                ],
            )
        saved = mock_save.call_args[0][0][0]
        assert saved["autoro"] == "Jane Austen"
        assert saved["verko"] == "Pride:1813"


class TestModifiAutoroVerko:
    """Tests for --autoro/-A and --verko/-v options in modifi."""

    def test_modifi_updates_autoro(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app, ["vorto", "modifi", SAMPLE_UUID, "-A", "New Author"]
            )
        saved = mock_save.call_args[0][0][0]
        assert saved["autoro"] == "New Author"

    def test_modifi_updates_verko(self):
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(
                app, ["vorto", "modifi", SAMPLE_UUID, "-v", "Hamlet:1603"]
            )
        saved = mock_save.call_args[0][0][0]
        assert saved["verko"] == "Hamlet:1603"

    def test_modifi_autoro_verko_count_in_opts(self):
        """modifi with only --autoro should update (not show help)."""
        entry = _make_entry()
        with (
            patch(_LOAD, return_value=[entry]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(
                app, ["vorto", "modifi", SAMPLE_UUID, "--autoro", "Alice"]
            )
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0][0]
        assert saved["autoro"] == "Alice"


# ──────────────────────────────────────────────────────────────────────────────
# No-duplicate teksto policy in aldoni
# ──────────────────────────────────────────────────────────────────────────────


class TestAldoniDuplicateTeksto:
    """Tests for the no-duplicate teksto policy in aldoni."""

    def test_duplicate_teksto_exact_asks_to_overwrite(self):
        existing = _make_entry(teksto="hello")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello"])
        # Should update existing entry, not add new one
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["uuid"] == SAMPLE_UUID

    def test_duplicate_teksto_case_insensitive_asks_to_overwrite(self):
        existing = _make_entry(teksto="Hello")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
            patch(_CONFIRM, return_value=True),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello"])
        assert result.exit_code == 0
        # Still only 1 entry
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1

    def test_duplicate_teksto_user_cancels_does_not_save(self):
        existing = _make_entry(teksto="hello")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=False),
        ):
            result = runner.invoke(app, ["vorto", "aldoni", "hello"])
        assert result.exit_code == 0
        mock_save.assert_not_called()

    def test_duplicate_teksto_overwrites_with_new_lingvo(self):
        existing = _make_entry(teksto="hello", lingvo="en")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello", "-l", "eo"])
        saved = mock_save.call_args[0][0]
        assert saved[0]["lingvo"] == "eo"

    def test_duplicate_teksto_overwrite_pushes_modifi_to_undo(self):
        existing = _make_entry(teksto="hello")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE),
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO) as mock_save_undo,
            patch("autish.commands.vorto.typer.prompt", return_value="j"),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "hello", "-l", "eo"])
        saved_stack = mock_save_undo.call_args[0][0]
        assert saved_stack[-1]["op"] == "modifi"
        assert saved_stack[-1]["old"]["lingvo"] == "en"

    def test_unique_teksto_adds_new_entry(self):
        existing = _make_entry(teksto="hello")
        with (
            patch(_LOAD, return_value=[existing]),
            patch(_SAVE) as mock_save,
            patch(_LOAD_UNDO, return_value=[]),
            patch(_SAVE_UNDO),
            patch(_CONFIRM, return_value=True),
        ):
            runner.invoke(app, ["vorto", "aldoni", "world"])
        saved = mock_save.call_args[0][0]
        assert len(saved) == 2


# ──────────────────────────────────────────────────────────────────────────────
# autoro/verko fields shown in entry display
# ──────────────────────────────────────────────────────────────────────────────


class TestEntryToLinesAutoroVerko:
    """Tests that autoro and verko are included in entry display lines."""

    def test_autoro_shown_when_present(self):
        entry = _make_entry(autoro="Voltaire")
        lines = _entry_to_lines(entry)
        assert any("Voltaire" in ln for ln in lines)

    def test_verko_shown_when_present(self):
        entry = _make_entry(verko="Candide:1759")
        lines = _entry_to_lines(entry)
        assert any("Candide:1759" in ln for ln in lines)

    def test_autoro_verko_absent_when_not_set(self):
        entry = _make_entry()
        lines = _entry_to_lines(entry)
        joined = "\n".join(lines)
        assert "aŭtoro:" not in joined
        assert "verko:" not in joined


# ──────────────────────────────────────────────────────────────────────────────
# Parametrized validation tests
# ──────────────────────────────────────────────────────────────────────────────


class TestTipoNormalization:
    """Parametrized tests for tipo (part of speech) normalization."""

    @pytest.mark.parametrize("input_tipo,expected", [
        ("subst", ["substantivo"]),
        ("adj", ["adjektivo"]),
        ("verb", ["verbo"]),
        ("adv", ["adverbo"]),
        ("konj", ["konjunkcio"]),
        ("prep", ["prepozicio"]),
        ("inter", ["interjekcio"]),
        ("sub", ["subordinaciant"]),
        ("subs", ["substantivo"]),
        ("subs.", ["substantivo"]),
    ])
    def test_tipo_normalization(self, input_tipo: str, expected: list[str]):
        """Test that tipo abbreviations are normalized to full forms."""
        result = _normalize_tipo(input_tipo)
        assert result == expected


class TestTonoNormalization:
    """Parametrized tests for tono (tone) normalization."""

    @pytest.mark.parametrize("input_tono,expected", [
        ("f", "fakula"),
        ("p", "poezia"),
        ("m", "meznombra"),
        ("sf", "sciencafakula"),
        ("sp", "sciencapoezia"),
    ])
    def test_tono_normalization(self, input_tono: str, expected: str):
        """Test that tono abbreviations are normalized."""
        result = _normalize_tono(input_tono)
        assert result == expected


class TestEtikedoParsing:
    """Parametrized tests for etikedo (label) parsing."""

    @pytest.mark.parametrize("raw,expected_key,expected_val", [
        ("koloro:ruĝa", "koloro", "ruĝa"),
        ("fak:matematiko", "fak", "matematiko"),
        ("nivelo:meza", "nivelo", "meza"),
        ("最简单的", "zh", "最简单的"),
    ])
    def test_etikedo_parsing(self, raw: str, expected_key: str, expected_val: str):
        """Test that etikedo strings are parsed into key:value pairs."""
        result = _parse_etikedo(raw)
        assert expected_key in result
        assert result[expected_key] == expected_val
