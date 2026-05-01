"""Tests for autish.commands.encik (Encik knowledge-graph microapp)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.encik import (
    _contrast_accent_style,
    _entry_to_enc,
    _extract_markdown_ligilo_refs,
    _linked_graph_of,
    _merge_auto_ligilo_refs,
    _normalize_fonto_tipo,
    _normalize_uuid_list,
    _paralela_of,
    _parse_enc_file,
    _render_markdown_text,
    _render_relation_cli_link,
    _render_relation_html_link,
    _repair_latex_controls_in_math,
    _reverse_semantika_ligilo,
    _subklasoj_of,
    _superklasoj_of,
)
from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CHILD_UUID = "11111111-2222-3333-4444-555555555555"
GRANDCHILD_UUID = "66666666-7777-8888-9999-aaaaaaaaaaaa"
SIBLING_UUID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


@pytest.fixture(autouse=True)
def isolate_encik_config(tmp_path, monkeypatch):
    import autish.commands.encik as enc_mod

    # Patch config paths
    config_dir = tmp_path / ".config" / "autish"
    monkeypatch.setattr(enc_mod, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(enc_mod, "_ENCIK_CONFIG_FILE", config_dir / "encik.toml")
    monkeypatch.setattr(enc_mod, "_SEMANTIKA_CONFIG_DIR", config_dir / "semantika")
    enc_mod._invalidate_semantika_config_cache()


def _make_entry(**kwargs) -> dict:
    defaults: dict = {
        "uuid": SAMPLE_UUID,
        "titolo": "Test Node",
        "difinio": "A test definition.",
        "terminologio": {"eo": "Test Node"},
        "difinoj": {"eo": "A test definition."},
        "enhavo": "",
        "superklaso": [],
        "ligilo": [],
        "fonto": [],
        "citajo": [],
        "datumo": {},
        "semantika": [],
        "kreita_je": "2024-01-01T00:00:00+00:00",
        "modifita_je": "2024-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def _load_db_fixture(entries: list[dict], tmp_db: Path):
    """Write entries directly to a temp SQLite DB."""
    import sqlite3

    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS encik (
            uuid TEXT PRIMARY KEY,
            titolo TEXT NOT NULL,
            difinio TEXT NOT NULL DEFAULT '',
            terminologio TEXT NOT NULL DEFAULT '{}',
            difinoj TEXT NOT NULL DEFAULT '{}',
            enhavo TEXT NOT NULL DEFAULT '',
            superklaso TEXT NOT NULL DEFAULT '[]',
            ligilo TEXT NOT NULL DEFAULT '[]',
            fonto TEXT NOT NULL DEFAULT '[]',
            citajo TEXT NOT NULL DEFAULT '[]',
            datumo TEXT NOT NULL DEFAULT '{}',
            semantika TEXT NOT NULL DEFAULT '[]',
            kreita_je TEXT NOT NULL,
            modifita_je TEXT NOT NULL
        )"""
    )
    for e in entries:
        conn.execute(
            """INSERT OR REPLACE INTO encik
               (uuid, titolo, difinio, terminologio, difinoj, enhavo,
                superklaso, ligilo, fonto, citajo, datumo, semantika,
                kreita_je, modifita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                e["uuid"],
                e["titolo"],
                e.get("difinio", ""),
                json.dumps(e.get("terminologio", {"eo": e["titolo"]})),
                json.dumps(e.get("difinoj", {"eo": e.get("difinio", "")})),
                e.get("enhavo", ""),
                json.dumps(e.get("superklaso", [])),
                json.dumps(e.get("ligilo", [])),
                json.dumps(e.get("fonto", [])),
                json.dumps(e.get("citajo", [])),
                json.dumps(e.get("datumo", {})),
                json.dumps(e.get("semantika", [])),
                e["kreita_je"],
                e["modifita_je"],
            ),
        )
    conn.commit()
    conn.close()


def _load_vorto_db_fixture(entries: list[dict], tmp_db: Path) -> None:
    """Write minimal vorto entries directly to a temp SQLite DB."""
    import sqlite3

    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS vorto (
            uuid TEXT PRIMARY KEY,
            teksto TEXT NOT NULL
        )"""
    )
    for e in entries:
        conn.execute(
            "INSERT OR REPLACE INTO vorto (uuid, teksto) VALUES (?, ?)",
            (str(e.get("uuid") or ""), str(e.get("teksto") or "")),
        )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — pure helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestNormalizeUuidList:
    def test_keeps_unique_non_empty_items(self):
        raw = ["  uuid-a  ", "uuid-b", "", "uuid-a"]
        assert _normalize_uuid_list(raw) == ["uuid-a", "uuid-b"]

    def test_empty(self):
        assert _normalize_uuid_list([]) == []


class TestContrastAccentStyle:
    def test_uses_blue_on_light_background(self, monkeypatch):
        monkeypatch.setenv("COLORFGBG", "0;15")
        assert _contrast_accent_style() == "blue"

    def test_uses_bright_cyan_on_dark_background(self, monkeypatch):
        monkeypatch.setenv("COLORFGBG", "15;0")
        assert _contrast_accent_style() == "bright_cyan"


class TestSemanticDirection:
    def test_reverse_superclassof_is_subclassof(self):
        assert _reverse_semantika_ligilo("rdfs:superClassOf") == "rdfs:subClassOf"

    def test_reverse_wikidata_part_of_and_has_part(self):
        assert _reverse_semantika_ligilo("wdt:P361") == "wdt:P527"
        assert _reverse_semantika_ligilo("wdt:P527") == "wdt:P361"

    def test_reverse_known_directional_wikidata_without_inverse_returns_none(self):
        assert _reverse_semantika_ligilo("wdt:P50") is None
        assert _reverse_semantika_ligilo("wdt:P123") is None

    def test_reverse_symmetric_relations_stay_same(self):
        assert _reverse_semantika_ligilo("owl:disjointWith") == "owl:disjointWith"
        assert _reverse_semantika_ligilo("wdt:P26") == "wdt:P26"


class TestParseEncFile:
    def test_basic_parsing(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "My Concept"\n'
            'difinio.eo = "A nice definition."\n'
            "superklaso = []\nligilo = []\nfonto = []\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["titolo"] == "My Concept"
        assert parsed["difinio"] == "A nice definition."
        assert parsed["terminologio"]["eo"] == "My Concept"
        assert parsed["difinoj"]["eo"] == "A nice definition."
        assert parsed["superklaso"] == []
        assert parsed["ligilo"] == []
        assert parsed["fonto"] == []

    def test_parse_multi_locale_shorthand_assignments(self, tmp_path):
        enc = tmp_path / "multi_locale.enc"
        enc.write_text(
            'terminologio.(en,fr)="abc"\n'
            'difino.(en,fr)="abc"\n'
            "superklaso = []\nligilo = []\nfonto = []\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["terminologio"]["en"] == "abc"
        assert parsed["terminologio"]["fr"] == "abc"
        assert parsed["difinoj"]["en"] == "abc"
        assert parsed["difinoj"]["fr"] == "abc"

    def test_parse_multi_locale_shorthand_allows_bare_rhs(self, tmp_path):
        enc = tmp_path / "multi_locale_bare.enc"
        enc.write_text(
            "terminologio.(en,fr)=abc\n"
            "difino.(en,fr)=abc\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["terminologio"]["en"] == "abc"
        assert parsed["terminologio"]["fr"] == "abc"

    def test_multiline_difinio(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Topic\n\ndifinio = """\nLine one.\nLine two.\n"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["titolo"] == "Topic"
        assert "Line one." in parsed["difinio"]
        assert "Line two." in parsed["difinio"]

    def test_multiline_difinio_with_spacing_before_triple_quotes(self, tmp_path):
        enc = tmp_path / "test_spaces.enc"
        enc.write_text(
            'terminologio.eo = "Temo"\ndifinio.eo =   \n   """\nestas difinio\n"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["titolo"] == "Temo"
        assert parsed["difinio"] == "estas difinio"

    def test_superklaso_uuid_list(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Child"\ndifinio.eo = "Difino"\n'
            'superklaso = ["uuid-parent"]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["superklaso"] == ["uuid-parent"]

    def test_superklaso_legacy_uuid_first_pair(self, tmp_path):
        enc = tmp_path / "legacy-superklaso.enc"
        enc.write_text(
            'terminologio.eo = "Child"\n'
            'difinio.eo = "Difino"\n'
            'superklaso = [["#uuid-parent", "Gepatra klaso"]]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["superklaso"] == ["uuid-parent"]

    def test_source_list(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Book"\ndifinio.eo = "x"\n'
            "fonto = ["
            '{titolo = "Great Book", autoro = "A. Author", jaro = 2020, tipo = "lib"}'
            "]\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert len(parsed["fonto"]) == 1
        assert parsed["fonto"][0]["titolo"] == "Great Book"
        assert parsed["fonto"][0]["autoro"] == "A. Author"
        assert parsed["fonto"][0]["jaro"] == 2020
        assert parsed["fonto"][0]["tipo"] == "libroj"

    def test_source_list_accepts_english_fields(self, tmp_path):
        """Backward compatibility: accept English field names too."""
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Book"\ndifinio.eo = "x"\n'
            "fonto = ["
            '{title = "Great Book", author = "A. Author", year = 2020, type = "lib"}'
            "]\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert len(parsed["fonto"]) == 1
        # Should be normalized to Esperanto
        assert parsed["fonto"][0]["titolo"] == "Great Book"
        assert parsed["fonto"][0]["autoro"] == "A. Author"
        assert parsed["fonto"][0]["jaro"] == 2020
        assert parsed["fonto"][0]["tipo"] == "libroj"

    def test_source_list_accepts_lingvo_field(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Book"\ndifinio.eo = "x"\n'
            "fonto = ["
            '{titolo = "Great Book", autoro = "A. Author", '
            'jaro = 2020, tipo = "lib", lingvo = "fr"}'
            "]\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["fonto"][0]["lingvo"] == "fr"

    def test_source_list_invalid_lingvo_raises(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Book"\ndifinio.eo = "x"\n'
            'fonto = [{titolo = "Great Book", lingvo = "fra"}]\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="fonto.lingvo"):
            _parse_enc_file(enc)

    def test_fonto_jaro_must_be_integer(self, tmp_path):
        """Test that jaro must be a valid integer."""
        enc = tmp_path / "test.enc"
        enc.write_text(
            'terminologio.eo = "Book"\ndifinio.eo = "x"\n'
            'fonto = [{titolo = "Book", jaro = "not a number"}]\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Nevalida fonto.jaro"):
            _parse_enc_file(enc)

    def test_missing_title_raises(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text('difinio = "No title here."\n', encoding="utf-8")
        with pytest.raises(ValueError, match="almenaŭ unu lingvo"):
            _parse_enc_file(enc)

    def test_malformed_toml_raises(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text("# Title\ndifinio = [broken toml\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Malformed"):
            _parse_enc_file(enc)

    def test_malformed_toml_error_includes_line_and_hint(self, tmp_path):
        enc = tmp_path / "bad.enc"
        enc.write_text(
            'terminologio.eo = "RS232"\n'
            'difinio.eo = "Seria interfaco."\n'
            "fonto = [{year = 202x}]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc_info:
            _parse_enc_file(enc)
        msg = str(exc_info.value)
        assert "Malformed .enc file" in msg
        assert "Problema linio 3" in msg
        assert "^" in msg
        assert "Sugestoj:" in msg

    def test_unknown_enc_key_suggests_fix(self, tmp_path):
        enc = tmp_path / "bad_key.enc"
        enc.write_text(
            'terminolgio.eo = "RS232"\n'
            'terminologio.en = "RS232"\n'
            'difinio.en = "Serial line protocol."\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="nekonata kampo"):
            _parse_enc_file(enc)

    def test_multiline_string_after_equals_is_accepted(self, tmp_path):
        enc = tmp_path / "rs232.enc"
        enc.write_text(
            'terminologio.eo = "EIA RS-232"\n'
            'terminologio.fr = "EIA RS-232"\n'
            "difinio.fr =\n"
            '"""\n'
            "Norme série.\n"
            '"""\n'
            "difinio.eo =\n"
            '"""\n'
            "Normo serio.\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["terminologio"]["fr"] == "EIA RS-232"
        assert parsed["difinoj"]["fr"] == "Norme série."
        assert parsed["difinoj"]["eo"] == "Normo serio."

    def test_toml_titolo_overrides_comment(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Comment Title\ntitolo = "TOML Title"\ndifinio = ""\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="almenaŭ unu lingvo"):
            _parse_enc_file(enc)

    def test_requires_term_and_definition_in_same_language(self, tmp_path):
        enc = tmp_path / "bad.enc"
        enc.write_text(
            'terminologio.eo = "Temo"\n'
            'difinio.en = "Definition only in another language."\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="almenaŭ unu lingvo"):
            _parse_enc_file(enc)

    def test_extracts_free_text_block(self, tmp_path):
        enc = tmp_path / "enhavo.enc"
        enc.write_text(
            'terminologio.eo = "Temo"\n'
            'difinio.eo = "Difino"\n\n'
            '"""\n'
            "Tio estas **Markdown** kaj $x^2$.\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "Markdown" in parsed["enhavo"]

    def test_latex_backslash_in_text_field_parses(self, tmp_path):
        enc = tmp_path / "latex.enc"
        enc.write_text(
            'terminologio.eo = "AI disvolvigo"\n'
            'difino.eo = "- komputila potenco $\\uparrow$ $\\uparrow$: Moore Leĝo"\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "\\uparrow" in parsed["difinoj"]["eo"]

    def test_parse_citajo_and_datumo_json(self, tmp_path):
        enc = tmp_path / "data.enc"
        enc.write_text(
            'terminologio.eo = "Ekonomia datumo"\n'
            'difino.eo = "Kun citaĵoj kaj datumoj."\n'
            "citajo = ["
            '{teksto = "Laboro dignigas.", autoro = "Aŭtoro", '
            'verko = "Verko", jaro = "2010"}'
            "]\n"
            'datumo.senlaboreco = """\n'
            "{\n"
            '  "metriko": {"en": "Unemployment rate", "fr": "Taux de chômage"},\n'
            '  "meta": {"country": {"en": "France", "eo": "Francio"}},\n'
            '  "datumo": [["jaro", "valoro"], [2010, 9.3], [2011, 9.2]],\n'
            '  "etikedo": {"jaro": {"eo": "jaro"}, "valoro": {"eo": "valoro"}}\n'
            "}\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["citajo"][0]["autoro"] == "Aŭtoro"
        assert "senlaboreco" in parsed["datumo"]
        assert parsed["datumo"]["senlaboreco"]["datumo"][1][1] == 9.3

    def test_parse_semantika_block(self, tmp_path):
        enc = tmp_path / "semantika.enc"
        enc.write_text(
            'terminologio.eo = "Semantikaj datumoj"\n'
            'difino.eo = "Nodo kun semantikaj valoroj."\n'
            'semantika = """\n'
            "int wdt:P1082 890\n"
            "float wdt:P2046 1 000 000\n"
            "str wdt:P5191 philosophia\n"
            "bool wdt:P31 true\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["semantika"] == [
            {"tipo": "int", "arko": "wdt:P1082", "valoro": 890},
            {"tipo": "float", "arko": "wdt:P2046", "valoro": 1000000.0},
            {"tipo": "str", "arko": "wdt:P5191", "valoro": "philosophia"},
            {"tipo": "bool", "arko": "rdf:type", "valoro": True},
        ]

    def test_parse_semantika_invalid_type_raises(self, tmp_path):
        enc = tmp_path / "bad_semantika.enc"
        enc.write_text(
            'terminologio.eo = "Bad semantika"\n'
            'difino.eo = "x"\n'
            'semantika = """\n'
            "date wdt:P1082 890\n"
            '"""\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="tipo devas esti unu el"):
            _parse_enc_file(enc)

    def test_parse_semantika_scientific_notation_and_unit(self, tmp_path):
        enc = tmp_path / "semantika_scientific.enc"
        enc.write_text(
            'terminologio.eo = "Semantika SI"\n'
            'difino.eo = "x"\n'
            'semantika = """\n'
            "int wdt:P2046 1E6 #abcde\n"
            "float wdt:P1082 2,8E8\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["semantika"] == [
            {"tipo": "int", "arko": "wdt:P2046", "valoro": 1000000, "unuo": "abcde"},
            {"tipo": "float", "arko": "wdt:P1082", "valoro": 280000000.0},
        ]

    def test_parse_citajo_and_fonto_lingvo_csv(self, tmp_path):
        enc = tmp_path / "lingvo.enc"
        enc.write_text(
            'terminologio.eo = "Lingva eniro"\n'
            'difino.eo = "Difino."\n'
            'fonto = [{titolo = "Libro", lingvo = "eo,en"}]\n'
            'citajo = [{teksto = "Citaĵo", lingvo = "fr,eo"}]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["fonto"][0]["lingvo"] == "eo,en"
        assert parsed["citajo"][0]["lingvo"] == "fr,eo"

    def test_parse_citajo_invalid_lingvo_raises(self, tmp_path):
        enc = tmp_path / "bad_lingvo.enc"
        enc.write_text(
            'terminologio.eo = "Bad"\n'
            'difino.eo = "x"\n'
            'citajo = [{teksto = "Citaĵo", lingvo = "fr,eng"}]\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="citajo.lingvo"):
            _parse_enc_file(enc)

    def test_parse_ligilo_semantic_tuple_and_hash_uuid(self, tmp_path):
        enc = tmp_path / "semantic_ligilo.enc"
        enc.write_text(
            'terminologio.eo = "Semantikaj"\n'
            'difino.eo = "Difino"\n'
            'ligilo = [#abc12345, ["#def67890", rdf:type],\n'
            '          ["ghi11111", "owl:inverseOf"]]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "abc12345" in parsed["ligilo"]
        assert ["def67890", "rdf:type"] in parsed["ligilo"]
        assert ["ghi11111", "owl:inverseOf"] in parsed["ligilo"]

    def test_parse_ligilo_mixed_quoted_unquoted_gracefully(self, tmp_path):
        enc = tmp_path / "semantic_ligilo_mixed.enc"
        enc.write_text(
            'terminologio.eo = "Miksa"\n'
            'difino.eo = "Difino"\n'
            'ligilo=["663457fc",[c8ec7722,rdf:type]]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "663457fc" in parsed["ligilo"]
        assert ["c8ec7722", "rdf:type"] in parsed["ligilo"]

    def test_merge_auto_ligilo_preserves_existing_semantic_type(self):
        parsed = {
            "ligilo": [["c8ec7722", "rdf:type"]],
            "terminologio": {"eo": "A"},
            "difinoj": {"eo": "B"},
            "difinio": "",
            "enhavo": "",
            "datumo": {},
        }
        merged = _merge_auto_ligilo_refs(parsed)
        assert ["c8ec7722", "rdf:type"] in merged["ligilo"]

    def test_normalizes_markdown_in_difino(self, tmp_path):
        enc = tmp_path / "md.enc"
        enc.write_text(
            'terminologio.eo = "Temo"\n'
            'difino.eo = """\n'
            "## Titolo\n"
            "  - ero unu\n"
            "    - ero du\n"
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "## Titolo\n\n  - ero unu" in parsed["difinoj"]["eo"]
        assert "  - ero du" in parsed["difinoj"]["eo"]

    def test_recovers_common_latex_backslash_commands(self, tmp_path):
        enc = tmp_path / "latex.enc"
        enc.write_text(
            'terminologio.eo = "Reflekto"\ndifino.eo = "$$theta_1 = theta_2$$"\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "$$\\theta_1 = \\theta_2$$" in parsed["difinoj"]["eo"]

    def test_recovers_latex_from_consumed_t_and_f_escapes_in_math(self, tmp_path):
        enc = tmp_path / "latex_ctrl.enc"
        enc.write_text(
            'terminologio.eo = "KaTeX kontrola"\n'
            'difino.eo = "$$\\theta_1 = \\frac{1}{2}$$"\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "\\theta_1" in parsed["difinoj"]["eo"]
        assert "\\frac" in parsed["difinoj"]["eo"]

    def test_repairs_text_to_and_longleftrightarrow_in_math_runtime(self):
        raw = (
            "$$f \text{ diferenciabla en } x_0 "
            r"\;\Longleftrightarrow\; \lim_{h\to 0}\frac{1}{h}=0$$"
        )
        # Simulate consumed TOML escapes as they may already exist in persisted data.
        consumed = raw.replace("\\text", "\text").replace("\\to", "\to")
        repaired = _repair_latex_controls_in_math(consumed)
        assert r"\text{" in repaired
        assert r"\to 0" in repaired
        assert r"\Longleftrightarrow" in repaired

    def test_aldoni_auto_adds_ligilo_from_markdown_uuid_refs(self, tmp_path):
        import uuid as _uuid_mod

        suffix = _uuid_mod.uuid4().hex[:8]
        target_title = f"Celo-{suffix}"
        target = tmp_path / "target.enc"
        target.write_text(
            f'terminologio.eo = "{target_title}"\ndifino.eo = "Difino de celo."\n',
            encoding="utf-8",
        )
        add_target = runner.invoke(app, ["encik", "aldoni", str(target)])
        assert add_target.exit_code == 0, add_target.output

        import autish.commands.encik as enc_mod

        target_entry = enc_mod._find_by_title_exact(target_title)
        assert target_entry is not None
        source_title = f"Fonto-{suffix} [Celo](#{target_entry['uuid'][:8]})"
        source = tmp_path / "source.enc"
        source.write_text(
            f'terminologio.eo = "{source_title}"\n'
            'difino.eo = "Difino kun [ligo](#'
            f'{target_entry["uuid"][:8]})."\n',
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output
        source_entry = enc_mod._find_by_title_exact(source_title)
        assert source_entry is not None
        assert target_entry["uuid"] in (source_entry.get("ligilo") or [])

    def test_aldoni_auto_adds_vt_ligilo_from_semantika_markdown(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        db_path = tmp_path / "encik.db"
        vorto_db = tmp_path / "vorto.db"
        data_dir = tmp_path / ".local" / "share" / "autish"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_mod, "_VORTO_DB_FILE", vorto_db)
        # Also patch repo to use temp db
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: data_dir / "encik.db")
        vorto_uuid = "8bf534dc-1111-2222-3333-444444444444"
        _load_vorto_db_fixture([{"uuid": vorto_uuid, "teksto": "mot"}], vorto_db)

        source = tmp_path / "sem_vt.enc"
        source.write_text(
            'terminologio.eo = "Semantika VT"\n'
            'difino.eo = "Difino"\n'
            'semantika = """\n'
            "str wdt:P5191 [mot](vt#8bf534dc)\n"
            '"""\n',
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output
        source_entry = enc_mod._find_by_title_exact("Semantika VT")
        assert source_entry is not None
        assert f"vt#{vorto_uuid}" in (source_entry.get("ligilo") or [])


class TestUuidRefExtraction:
    def _setup_encik_db(self, tmp_path, monkeypatch):
        """Helper to set up temp database for uuid tests."""
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        data_dir = tmp_path / ".local" / "share" / "autish"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "encik.db"

        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: db_path)
        return db_path

    def test_extract_markdown_ligilo_refs_resolves_existing_full_uuid(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = self._setup_encik_db(tmp_path, monkeypatch)
        _load_db_fixture(
            [
                _make_entry(uuid=SAMPLE_UUID, titolo="A"),
                _make_entry(uuid=CHILD_UUID, titolo="B"),
            ],
            db_path,
        )
        refs = _extract_markdown_ligilo_refs(
            f"[A](#{SAMPLE_UUID[:8]}) [B](#{CHILD_UUID})"
        )
        uuids = {str(item.get("uuid")) for item in refs}
        assert SAMPLE_UUID in uuids
        assert CHILD_UUID in uuids

    def test_extract_markdown_ligilo_refs_with_semantics(self, tmp_path, monkeypatch):
        db_path = self._setup_encik_db(tmp_path, monkeypatch)
        _load_db_fixture([_make_entry(uuid=SAMPLE_UUID, titolo="A")], db_path)
        refs = _extract_markdown_ligilo_refs(f"[A](#{SAMPLE_UUID[:8]},rdfs:subClassOf)")
        assert refs[0]["uuid"] == SAMPLE_UUID
        assert refs[0]["tipo"] == "rdfs:subClassOf"

    def test_extract_markdown_ligilo_refs_resolves_vt_reference(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        data_dir = tmp_path / ".local" / "share" / "autish"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "encik.db"
        vorto_db = tmp_path / "vorto.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_mod, "_VORTO_DB_FILE", vorto_db)
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: db_path)
        _load_db_fixture([_make_entry(uuid=SAMPLE_UUID, titolo="A")], db_path)
        vorto_uuid = "8bf534dc-1111-2222-3333-444444444444"
        _load_vorto_db_fixture([{"uuid": vorto_uuid, "teksto": "mot"}], vorto_db)

        refs = _extract_markdown_ligilo_refs("[mot](vt#8bf534dc)")
        assert refs == [{"uuid": f"vt#{vorto_uuid}", "tipo": None}]

    def test_merge_auto_ligilo_refs_scans_semantika_and_nested_text(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        data_dir = tmp_path / ".local" / "share" / "autish"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "encik.db"
        vorto_db = tmp_path / "vorto.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_mod, "_VORTO_DB_FILE", vorto_db)
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: db_path)
        _load_db_fixture([_make_entry(uuid=SAMPLE_UUID, titolo="A")], db_path)
        vorto_uuid = "8bf534dc-1111-2222-3333-444444444444"
        _load_vorto_db_fixture([{"uuid": vorto_uuid, "teksto": "mot"}], vorto_db)

        parsed = {
            "ligilo": [],
            "terminologio": {"eo": "Nodo [A](#aaaaaaaa)"},
            "difinoj": {"eo": "Difino"},
            "difinio": "",
            "enhavo": "",
            "fonto": [{"noto": "Noto [mot](vt#8bf534dc)"}],
            "citajo": [{"teksto": "Citaĵo [mot](vt#8bf534dc)"}],
            "datumo": {},
            "semantika": [
                {"tipo": "str", "arko": "wdt:P5191", "valoro": "[mot](vt#8bf534dc)"}
            ],
        }
        merged = _merge_auto_ligilo_refs(parsed)
        assert SAMPLE_UUID in merged["ligilo"]
        assert f"vt#{vorto_uuid}" in merged["ligilo"]

    def test_linked_graph_collects_super_sub_and_ligilo(self, tmp_path, monkeypatch):
        db_path = self._setup_encik_db(tmp_path, monkeypatch)
        _load_db_fixture(
            [
                _make_entry(uuid=SAMPLE_UUID, titolo="Root"),
                _make_entry(uuid=CHILD_UUID, titolo="Child", superklaso=[SAMPLE_UUID]),
                _make_entry(
                    uuid=GRANDCHILD_UUID,
                    titolo="Leaf",
                    ligilo=[CHILD_UUID],
                ),
            ],
            db_path,
        )
        nodes, edges = _linked_graph_of(SAMPLE_UUID, max_depth=5)
        uuids = {n["uuid"] for n in nodes}
        assert SAMPLE_UUID in uuids
        assert CHILD_UUID in uuids
        assert GRANDCHILD_UUID in uuids
        edge_types = {(a, b, c) for (a, b, c, _t) in edges}
        assert (SAMPLE_UUID, CHILD_UUID, "subklaso") in edge_types
        assert (CHILD_UUID, GRANDCHILD_UUID, "ligilo") in edge_types or (
            GRANDCHILD_UUID,
            CHILD_UUID,
            "ligilo",
        ) in edge_types

    def test_linked_graph_keeps_semantic_edge_label(self, tmp_path, monkeypatch):
        db_path = self._setup_encik_db(tmp_path, monkeypatch)
        _load_db_fixture(
            [
                _make_entry(uuid=SAMPLE_UUID, titolo="Root"),
                _make_entry(
                    uuid=CHILD_UUID,
                    titolo="Child",
                    ligilo=[[SAMPLE_UUID, "rdf:type"]],
                ),
            ],
            db_path,
        )
        _nodes, edges = _linked_graph_of(CHILD_UUID, max_depth=2)
        assert any(
            src == CHILD_UUID
            and dst == SAMPLE_UUID
            and rel == "ligilo"
            and sem == "rdf:type"
            for src, dst, rel, sem in edges
        )
        assert not any(
            rel == "ligilo"
            and sem is None
            and {src, dst} == {CHILD_UUID, SAMPLE_UUID}
            for src, dst, rel, sem in edges
        )

    def test_linked_graph_hides_generic_if_semantic_exists_between_same_nodes(
        self, tmp_path, monkeypatch
    ):
        db_path = self._setup_encik_db(tmp_path, monkeypatch)
        _load_db_fixture(
            [
                _make_entry(
                    uuid=SAMPLE_UUID,
                    titolo="Root",
                    ligilo=[CHILD_UUID],
                ),
                _make_entry(
                    uuid=CHILD_UUID,
                    titolo="Child",
                    ligilo=[[SAMPLE_UUID, "rdf:type"]],
                ),
            ],
            db_path,
        )

        _nodes, edges = _linked_graph_of(SAMPLE_UUID, max_depth=2)
        assert any(
            rel == "ligilo"
            and _sem == "rdf:type"
            and {src, dst} == {SAMPLE_UUID, CHILD_UUID}
            for src, dst, rel, _sem in edges
        )
        assert not any(
            rel == "ligilo"
            and sem is None
            and {src, dst} == {SAMPLE_UUID, CHILD_UUID}
            for src, dst, rel, sem in edges
        )

    def test_preserves_nested_markdown_list_indentation_in_roundtrip(self, tmp_path):
        entry = _make_entry(
            titolo="Nested List",
            difinio="- abc\n  - efg",
            terminologio={"eo": "Nested List"},
            difinoj={"eo": "- abc\n  - efg"},
        )
        enc_text = _entry_to_enc(entry)
        enc_file = tmp_path / "nested.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["difinoj"]["eo"] == "- abc\n  - efg"

    def test_source_legacy_key_is_still_read_as_fonto(self, tmp_path):
        enc = tmp_path / "legacy.enc"
        enc.write_text(
            'terminologio.eo = "Legacy"\n'
            'difinio.eo = "Difino"\n'
            'source = [{title = "Old", type = "fil"}]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["fonto"][0]["tipo"] == "filmoj"
        assert parsed["fonto"][0]["titolo"] == "Old"

    def test_invalid_fonto_type_raises(self, tmp_path):
        enc = tmp_path / "bad_type.enc"
        enc.write_text(
            'terminologio.eo = "Type"\n'
            'difinio.eo = "Difino"\n'
            'fonto = [{titolo = "Book", tipo = "invalid"}]\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Nevalida fonto.type"):
            _parse_enc_file(enc)


class TestEntryToEnc:
    def test_round_trip(self, tmp_path):
        entry = _make_entry(
            titolo="Round Trip",
            difinio="Some definition.",
            terminologio={"eo": "Round Trip"},
            difinoj={"eo": "Some definition."},
            superklaso=["parent-uuid"],
        )
        enc_text = _entry_to_enc(entry)
        enc_file = tmp_path / "rt.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["titolo"] == "Round Trip"
        assert "Some definition." in parsed["difinio"]
        assert parsed["superklaso"] == ["parent-uuid"]

    def test_empty_fields(self, tmp_path):
        entry = _make_entry(
            titolo="Empty",
            difinio="",
            terminologio={"eo": "Empty"},
            difinoj={"eo": "Difino"},
        )
        enc_text = _entry_to_enc(entry)
        enc_file = tmp_path / "empty.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["titolo"] == "Empty"
        assert parsed["superklaso"] == []

    def test_writes_difino_key_and_decodes_literal_newlines(self, tmp_path):
        entry = _make_entry(
            titolo="RS232",
            difino="Linio 1\\n\\nLinio 2",
            terminologio={"eo": "RS232"},
            difinoj={"eo": "Linio 1\\n\\nLinio 2"},
        )
        enc_text = _entry_to_enc(entry)
        assert "difino.eo" in enc_text
        assert "difinio.eo" not in enc_text
        enc_file = tmp_path / "rs232.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["difinoj"]["eo"] == "Linio 1\n\nLinio 2"

    def test_round_trip_semantika_values(self, tmp_path):
        entry = _make_entry(
            titolo="Semantika Roundtrip",
            difinio="x",
            semantika=[
                {"tipo": "int", "arko": "wdt:P1082", "valoro": 890, "unuo": "abcde"},
                {"tipo": "float", "arko": "wdt:P2046", "valoro": 1000.5},
                {"tipo": "str", "arko": "wdt:P5191", "valoro": "philosophia"},
                {"tipo": "bool", "arko": "rdf:type", "valoro": True},
            ],
        )
        enc_text = _entry_to_enc(entry)
        assert "semantika = " in enc_text
        assert "#abcde" in enc_text
        enc_file = tmp_path / "semantika_roundtrip.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["semantika"] == [
            {"tipo": "int", "arko": "wdt:P1082", "valoro": 890, "unuo": "abcde"},
            {"tipo": "float", "arko": "wdt:P2046", "valoro": 1000.5},
            {"tipo": "str", "arko": "wdt:P5191", "valoro": "philosophia"},
            {"tipo": "bool", "arko": "rdf:type", "valoro": True},
        ]

    def test_display_ligilo_items_dedupes_resolved_prefix_and_full_uuid(self):
        import autish.commands.encik as enc_mod

        full_uuid = "11111111-2222-3333-4444-555555555555"
        original_find = enc_mod._find_by_uuid
        try:
            enc_mod._find_by_uuid = (  # type: ignore[method-assign]
                lambda ref: (
                    {"uuid": full_uuid, "titolo": "Lumradia modelo"}
                    if str(ref).startswith("11111111")
                    else None
                )
            )
            items = enc_mod._display_ligilo_items(
                [
                    ["11111111", "rdfs:subClassOf"],
                    [full_uuid, "rdfs:subClassOf"],
                ]
            )
            assert items == [{"uuid": full_uuid, "tipo": "rdfs:subClassOf"}]
        finally:
            enc_mod._find_by_uuid = original_find  # type: ignore[method-assign]

    def test_entry_to_enc_hides_auto_reverse_ligilo(self):
        entry = _make_entry(
            titolo="Hide Auto",
            difinio="x",
            ligilo=[["11111111-2222-3333-4444-555555555555", "rdf:hasInstance"]],
            datumo={
                "__autish_auto_reverse_ligilo__": [
                    ["11111111-2222-3333-4444-555555555555", "rdf:hasInstance"]
                ]
            },
        )
        enc_text = _entry_to_enc(entry)
        assert "rdf:hasInstance" not in enc_text
        assert "__autish_auto_reverse_ligilo__" not in enc_text


class TestFontoTipoNormalisation:
    def test_alias_and_full_type(self):
        assert _normalize_fonto_tipo("lib") == "libroj"
        assert _normalize_fonto_tipo("libroj") == "libroj"


# ──────────────────────────────────────────────────────────────────────────────
# Graph traversal tests (using a real temporary DB)
# ──────────────────────────────────────────────────────────────────────────────


class TestGraphTraversal:
    """Tests for subklasoj, superklasoj, paralela searches."""

    @pytest.fixture(autouse=True)
    def use_temp_db(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        data_dir = tmp_path / ".local" / "share" / "autish"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "encik.db"

        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: db_path)

        # Build a small taxonomy:
        # Animal (root) <- Mammal <- Dog
        #                         <- Cat (sibling of Dog)
        animal = _make_entry(
            uuid=SAMPLE_UUID,
            titolo="Animal",
            superklaso=[],
        )
        mammal = _make_entry(
            uuid=CHILD_UUID,
            titolo="Mammal",
            superklaso=[SAMPLE_UUID],
        )
        dog = _make_entry(
            uuid=GRANDCHILD_UUID,
            titolo="Dog",
            superklaso=[CHILD_UUID],
        )
        cat = _make_entry(
            uuid=SIBLING_UUID,
            titolo="Cat",
            superklaso=[CHILD_UUID],
        )
        _load_db_fixture([animal, mammal, dog, cat], db_path)

    def test_subklasoj_depth1(self):
        results = _subklasoj_of(SAMPLE_UUID, max_depth=1)
        titles = {e["titolo"] for e in results}
        assert "Mammal" in titles
        assert "Dog" not in titles

    def test_subklasoj_unlimited(self):
        results = _subklasoj_of(SAMPLE_UUID, max_depth=0)
        titles = {e["titolo"] for e in results}
        assert "Mammal" in titles
        assert "Dog" in titles
        assert "Cat" in titles

    def test_superklasoj_depth1(self):
        results = _superklasoj_of(GRANDCHILD_UUID, max_depth=1)
        titles = {e["titolo"] for e in results}
        assert "Mammal" in titles
        assert "Animal" not in titles

    def test_superklasoj_unlimited(self):
        results = _superklasoj_of(GRANDCHILD_UUID, max_depth=0)
        titles = {e["titolo"] for e in results}
        assert "Mammal" in titles
        assert "Animal" in titles

    def test_paralela(self):
        results = _paralela_of(GRANDCHILD_UUID, max_results=100)
        titles = {e["titolo"] for e in results}
        assert "Cat" in titles
        assert "Dog" not in titles

    def test_paralela_no_parent(self):
        results = _paralela_of(SAMPLE_UUID, max_results=100)
        assert results == []


# ──────────────────────────────────────────────────────────────────────────────
# CLI integration tests
# ──────────────────────────────────────────────────────────────────────────────


class TestEncikCLI:
    @pytest.fixture(autouse=True)
    def isolate_db(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod
        import autish.services.encik_repo as enc_repo

        # Use same path as tests expect: tmp_path / "encik.db"
        db_path = tmp_path / "encik.db"

        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(enc_repo, "get_db_path", lambda: db_path)

    def _make_enc_file(self, tmp_path: Path, titolo: str, difinio: str = "") -> Path:
        p = tmp_path / f"{titolo.replace(' ', '_')}.enc"
        difinio_json = json.dumps(difinio)
        p.write_text(
            f"terminologio.eo = {json.dumps(titolo)}\ndifinio.eo = {difinio_json}\n",
            encoding="utf-8",
        )
        return p

    def test_welcome_screen(self):
        result = runner.invoke(app, ["encik"])
        assert result.exit_code == 0
        assert "Encik" in result.output

    def test_agordi_writes_toml_file(self):
        result = runner.invoke(
            app,
            [
                "encik",
                "agordi",
                "--html",
                "1",
                "--scienca-nombro",
                "3",
                "--spaco",
                "2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Konservis encik montrado-agordon." in result.output
        import autish.commands.encik as enc_mod

        text = enc_mod._ENCIK_CONFIG_FILE.read_text(encoding="utf-8")
        assert "html = true" in text
        assert "scienca_nombro = 3" in text
        assert "spaco = 2" in text

    def test_vidi_uses_default_html_from_agordo(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "HTML Defaŭlto", "A")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        assert runner.invoke(app, ["encik", "agordi", "--html", "1"]).exit_code == 0

        opened: dict[str, str] = {}

        def _fake_open_html_document(html_doc: str) -> str:
            opened["html"] = html_doc
            return "/tmp/encik_test.html"

        monkeypatch.setattr(
            "autish.commands.encik._open_html_document", _fake_open_html_document
        )
        result = runner.invoke(app, ["encik", "vidi", "HTML Defaŭlto"])
        assert result.exit_code == 0, result.output
        assert "Malfermas en retumilo:" in result.output
        assert "html" in opened

    def test_aldoni_creates_entry(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "My Concept", "A definition here.")
        result = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert result.exit_code == 0, result.output
        assert "Aldonis" in result.output
        assert "My Concept" in result.output

    def test_aldoni_missing_file(self):
        result = runner.invoke(app, ["encik", "aldoni", "/nonexistent/file.enc"])
        assert result.exit_code != 0
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "ne trovita" in combined

    def test_aldoni_duplicate_no_overwrite(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "DupNode", "First.")
        runner.invoke(app, ["encik", "aldoni", str(enc)])
        enc2 = self._make_enc_file(tmp_path, "DupNode", "Second.")
        result = runner.invoke(app, ["encik", "aldoni", str(enc2)], input="n\n")
        assert "Nuligita" in result.output

    def test_aldoni_duplicate_overwrite(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "DupNode2", "First.")
        runner.invoke(app, ["encik", "aldoni", str(enc)])
        enc2 = self._make_enc_file(tmp_path, "DupNode2", "Updated definition.")
        result = runner.invoke(app, ["encik", "aldoni", str(enc2)], input="j\n")
        assert "Modifis" in result.output

    def test_serci_titolo_found(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "Philosophy", "Study of wisdom.")
        runner.invoke(app, ["encik", "aldoni", str(enc)])
        result = runner.invoke(app, ["encik", "serci", "Philo"])
        assert result.exit_code == 0
        assert "Philos" in result.output

    def test_serci_ignores_accents_by_default(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "Ĵurnalo", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        result = runner.invoke(app, ["encik", "serci", "Jurnalo"])
        assert result.exit_code == 0, result.output
        assert "Ĵurnalo" in result.output

    def test_serci_kopii_copies_uuid_for_single_match(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "SoloNode", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(app, ["encik", "serci", "SoloNode", "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"].startswith("#")
        assert len(copied["value"]) == 9

    def test_serci_kopii_copies_interactively_selected_match(
        self, tmp_path, monkeypatch
    ):
        a = self._make_enc_file(tmp_path, "AlphaNode", "Difino A")
        b = self._make_enc_file(tmp_path, "AlphaNode Plus", "Difino B")
        assert runner.invoke(app, ["encik", "aldoni", str(a)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(b)]).exit_code == 0

        import autish.commands.encik as enc_mod

        candidates = enc_mod._search_entries(
            "AlphaNode",
            full_text=False,
            max_results=5,
            prefer_newest=True,
            prefer_high_level=True,
        )
        assert len(candidates) >= 2
        chosen = candidates[1]
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "serci", "AlphaNode", "-k"],
            input="2\n",
        )
        assert result.exit_code == 0, result.output
        assert copied["value"] == f"#{str(chosen['uuid'])[:8]}"

    def test_serci_semantika_kopii_uses_locale_title_and_uuid(
        self, tmp_path, monkeypatch
    ):
        enc = tmp_path / "multi_locale.enc"
        enc.write_text(
            'terminologio.eo = "Loka Titolo"\n'
            'terminologio.en = "Local Title"\n'
            'difinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        import autish.commands.encik as enc_mod

        found = enc_mod._find_by_title_exact("Loka Titolo")
        assert found is not None
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setenv("LANG", "eo_FR.UTF-8")
        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "serci", "Loka", "--semantika-kopii"],
        )
        assert result.exit_code == 0, result.output
        assert copied["value"] == f"[Loka Titolo](#{found['uuid'][:8]})"

    def test_serci_semantika_kopii_strips_trailing_disambiguation_parentheses(
        self, tmp_path, monkeypatch
    ):
        enc = tmp_path / "disambiguation_copy.enc"
        enc.write_text(
            'terminologio.eo = "Rivero (malambiguigo)"\n'
            'difinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        import autish.commands.encik as enc_mod

        found = enc_mod._find_by_title_exact("Rivero (malambiguigo)")
        assert found is not None
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "serci", "Rivero (malambiguigo)", "--semantika-kopii"],
        )
        assert result.exit_code == 0, result.output
        assert copied["value"] == f"[Rivero](#{found['uuid'][:8]})"

    def test_serci_semantika_kopii_strips_parentheses_anywhere_in_title(
        self, tmp_path, monkeypatch
    ):
        enc = tmp_path / "middle_parentheses_copy.enc"
        enc.write_text(
            'terminologio.eo = "Teorio (speciala) de lumo"\n'
            'difinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        import autish.commands.encik as enc_mod

        found = enc_mod._find_by_title_exact("Teorio (speciala) de lumo")
        assert found is not None
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "serci", "Teorio", "--semantika-kopii"],
        )
        assert result.exit_code == 0, result.output
        assert copied["value"] == f"[Teorio de lumo](#{found['uuid'][:8]})"

    def test_serci_semantika_kopii_multiple_matches_uses_selected(
        self, tmp_path, monkeypatch
    ):
        a = self._make_enc_file(tmp_path, "Beta Node", "Difino A")
        b = self._make_enc_file(tmp_path, "Beta Node Plus", "Difino B")
        assert runner.invoke(app, ["encik", "aldoni", str(a)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(b)]).exit_code == 0

        import autish.commands.encik as enc_mod

        candidates = enc_mod._search_entries(
            "Beta Node",
            full_text=False,
            max_results=5,
            prefer_newest=True,
            prefer_high_level=True,
        )
        assert len(candidates) >= 2
        selected = candidates[1]
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "serci", "Beta Node", "--semantika-kopii"],
            input="2\n",
        )
        assert result.exit_code == 0, result.output
        expected_title = enc_mod._entry_user_locale_title(selected)
        assert copied["value"] == f"[{expected_title}](#{selected['uuid'][:8]})"

    def test_serci_copy_options_require_search_query(self):
        result = runner.invoke(app, ["encik", "serci", "--kopii"])
        assert result.exit_code != 0
        assert "postulas serĉan demandon" in (result.output + (result.stderr or ""))

    def test_aldoni_kopii_copies_uuid_of_added_node(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "CopyAdd", "Difino")
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(app, ["encik", "aldoni", str(enc), "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"].startswith("#")
        assert len(copied["value"]) == 9

    def test_aldoni_vidi_displays_entry(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "ViduPoste", "Posta difino")
        result = runner.invoke(app, ["encik", "aldoni", str(enc), "--vidi"])
        assert result.exit_code == 0, result.output
        assert 'Aldonis #' in result.output
        assert "ViduPoste" in result.output
        assert "difino:" in result.output

    def test_aldoni_html_opens_browser_view(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod

        enc = self._make_enc_file(tmp_path, "HtmlPost", "Html difino")
        opened: dict[str, str] = {}

        def _fake_open(doc: str) -> str:
            opened["html"] = doc
            return "/tmp/encik-post.html"

        monkeypatch.setattr(enc_mod, "_open_html_document", _fake_open)
        result = runner.invoke(app, ["encik", "aldoni", str(enc), "--html"])
        assert result.exit_code == 0, result.output
        assert "Malfermas en retumilo: /tmp/encik-post.html" in result.output
        assert "<html" in opened["html"].lower()

    def test_aldoni_html_and_kopii_are_compatible(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod

        enc = self._make_enc_file(tmp_path, "HtmlCopy", "Html+copy difino")
        opened: dict[str, str] = {}
        copied: dict[str, str] = {}

        def _fake_open(doc: str) -> str:
            opened["html"] = doc
            return "/tmp/encik-post-copy.html"

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr(enc_mod, "_open_html_document", _fake_open)
        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(app, ["encik", "aldoni", str(enc), "--html", "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"].startswith("#")
        assert "Kopiis UUID al tondujo" in result.output
        assert "Malfermas en retumilo: /tmp/encik-post-copy.html" in result.output
        assert "<html" in opened["html"].lower()

    def test_modifi_semantika_kopii_copies_reference(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "CopyMod", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(
            app,
            ["encik", "modifi", "CopyMod", "--titolo", "CopyMod2", "--semantika-kopii"],
        )
        assert result.exit_code == 0, result.output
        assert copied["value"].startswith("[CopyMod2](#")
        assert copied["value"].endswith(")")

    def test_modifi_removes_semantic_subclass_link_without_reappearing(self, tmp_path):
        parent = self._make_enc_file(tmp_path, "Historiisto", "Difino de historiisto")
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        parent_entry = enc_mod._find_by_title_exact("Historiisto")
        assert parent_entry is not None
        parent_short = str(parent_entry["uuid"])[:8]

        child = tmp_path / "esploristo.enc"
        child.write_text(
            'terminologio.eo = "Esploristo"\n'
            'difinio.eo = "Difino de esploristo"\n'
            f'ligilo = [["#{parent_short}", "rdfs:subClassOf"]]\n',
            encoding="utf-8",
        )
        add_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert add_child.exit_code == 0, add_child.output

        child_update = tmp_path / "esploristo_mod.enc"
        child_update.write_text(
            'terminologio.eo = "Esploristo"\n'
            'difinio.eo = "Ĝisdatigita difino"\n',
            encoding="utf-8",
        )
        mod = runner.invoke(
            app,
            ["encik", "modifi", "Esploristo", str(child_update)],
        )
        assert mod.exit_code == 0, mod.output

        updated_child = enc_mod._find_by_title_exact("Esploristo")
        updated_parent = enc_mod._find_by_title_exact("Historiisto")
        assert updated_child is not None
        assert updated_parent is not None

        child_links = {
            (
                str(item.get("uuid") or ""),
                enc_mod._normalize_semantika_ligilo(item.get("tipo")),
            )
            for item in enc_mod._display_ligilo_items(updated_child)
        }
        parent_links = {
            (
                str(item.get("uuid") or ""),
                enc_mod._normalize_semantika_ligilo(item.get("tipo")),
            )
            for item in enc_mod._display_ligilo_items(updated_parent)
        }
        assert (str(updated_parent["uuid"]), "rdfs:subClassOf") not in child_links
        assert (str(updated_child["uuid"]), "rdfs:hasSubClass") not in parent_links

    def test_vidi_kopii_copies_uuid_of_displayed_node(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "CopyView", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        copied: dict[str, str] = {}

        def _fake_copy(value: str) -> None:
            copied["value"] = value

        monkeypatch.setattr("pyperclip.copy", _fake_copy)
        result = runner.invoke(app, ["encik", "vidi", "CopyView", "--kopii"])
        assert result.exit_code == 0, result.output
        assert copied["value"].startswith("#")
        assert len(copied["value"]) == 9

    def test_serci_candidates_prefer_user_locale_title(self, tmp_path, monkeypatch):
        enc = tmp_path / "locale_title.enc"
        enc.write_text(
            'terminologio.eo = "programaro"\n'
            'terminologio.en = "software"\n'
            'difinio.eo = "aro de instrukcioj"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        monkeypatch.setenv("LANG", "eo_FR.UTF-8")
        result = runner.invoke(app, ["encik", "serci", "software"])
        assert result.exit_code == 0, result.output
        assert "programaro" in result.output

    def test_serci_lingvo_option_prioritizes_requested_language(self, tmp_path):
        enc = tmp_path / "locale_pref.enc"
        enc.write_text(
            'terminologio.eo = "programaro"\n'
            'terminologio.fr = "logiciel"\n'
            'terminologio.en = "software"\n'
            'difinio.eo = "aro de instrukcioj"\n'
            'difinio.fr = "ensemble d instructions"\n'
            'difinio.en = "set of instructions"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        result = runner.invoke(app, ["encik", "serci", "software", "--lingvo", "fr,en"])
        assert result.exit_code == 0, result.output
        assert "logiciel" in result.output
        assert "fr" in result.output

    def test_serci_single_result_keeps_entry_title_when_ligilo_present(self, tmp_path):
        parent = self._make_enc_file(tmp_path, "komputilo", "maŝino")
        r_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert r_parent.exit_code == 0, r_parent.output
        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("komputilo")
        assert p is not None

        child = tmp_path / "child.enc"
        child.write_text(
            'terminologio.eo = "programaro"\n'
            'difinio.eo = "- aro de instrukcioj\\n- kiuj direktas komputilon"\n'
            f'ligilo = "{p["uuid"][:8]}"\n',
            encoding="utf-8",
        )
        r_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert r_child.exit_code == 0, r_child.output

        result = runner.invoke(app, ["encik", "serci", "programa"])
        assert result.exit_code == 0, result.output
        assert "programaro" in result.output

    def test_serci_titolo_not_found(self, tmp_path):
        result = runner.invoke(app, ["encik", "serci", "NonExistentXYZ"])
        assert result.exit_code == 0
        assert "trovita" in result.output.lower()

    def test_serci_t_teksto_searches_full_text(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "Nomo", "speciala-teksto-xyz")
        runner.invoke(app, ["encik", "aldoni", str(enc)])
        result = runner.invoke(app, ["encik", "serci", "-t", "speciala-teksto-xyz"])
        assert result.exit_code == 0
        assert "Nomo" in result.output

    def test_serci_no_flags_shows_help(self):
        result = runner.invoke(app, ["encik", "serci"])
        assert result.exit_code == 0
        # Help text should contain the command name
        assert "serci" in result.output.lower() or "Usage" in result.output

    def test_eksporti_writes_single_entry_enc(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        entry = _make_entry(
            uuid="12345678-0000-0000-0000-000000000000",
            titolo="Eksporta Nodo",
            difinio="Nodo por eksporto.",
            terminologio={"eo": "Eksporta Nodo"},
            difinoj={"eo": "Nodo por eksporto."},
        )
        _load_db_fixture([entry], db_path)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        out_path = tmp_path / "nodo.enc"
        result = runner.invoke(
            app, ["encik", "eksporti", "Eksporta Nodo", str(out_path)]
        )

        assert result.exit_code == 0, result.output
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert 'terminologio.eo = "Eksporta Nodo"' in content
        assert 'difino.eo = "Nodo por eksporto."' in content

    def test_eksporti_prompts_selection_when_reference_is_ambiguous(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        first = _make_entry(
            uuid="aaaaaaaa-0000-0000-0000-000000000000",
            titolo="Suno A",
            difinio="Unua varianto.",
            terminologio={"eo": "Suno A"},
            difinoj={"eo": "Unua varianto."},
        )
        second = _make_entry(
            uuid="bbbbbbbb-0000-0000-0000-000000000000",
            titolo="Suno B",
            difinio="Dua varianto.",
            terminologio={"eo": "Suno B"},
            difinoj={"eo": "Dua varianto."},
        )
        _load_db_fixture([first, second], db_path)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        out_path = tmp_path / "suno.enc"
        result = runner.invoke(
            app,
            ["encik", "eksporti", "Suno", str(out_path)],
            input="2\n",
        )

        assert result.exit_code == 0, result.output
        content = out_path.read_text(encoding="utf-8")
        assert 'terminologio.eo = "Suno B"' in content

    def test_eksporti_directory_path_appends_default_filename(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        entry = _make_entry(
            uuid="cccccccc-0000-0000-0000-000000000000",
            titolo="Direktoro Nodo",
            difinio="Dosieruja eksporto.",
            terminologio={"eo": "Direktoro Nodo"},
            difinoj={"eo": "Dosieruja eksporto."},
        )
        _load_db_fixture([entry], db_path)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        result = runner.invoke(
            app,
            ["encik", "eksporti", "Direktoro Nodo", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output
        exported = [p for p in tmp_path.glob("*.enc") if p.name != "encik.db"]
        assert exported
        content = exported[0].read_text(encoding="utf-8")
        assert 'terminologio.eo = "Direktoro Nodo"' in content

    def test_eksporti_default_filename_transliterates_accents(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        entry = _make_entry(
            uuid="dddddddd-0000-0000-0000-000000000000",
            titolo="Système d'exploitation Linux",
            difinio="Difino",
            terminologio={"fr": "Système d'exploitation Linux"},
            difinoj={"fr": "Difino"},
        )
        _load_db_fixture([entry], db_path)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        result = runner.invoke(
            app,
            ["encik", "eksporti", "Système d'exploitation Linux", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output
        exported = [p for p in tmp_path.glob("*.enc") if p.name != "encik.db"]
        assert exported
        assert "systeme-d-exploitation-linux" in exported[0].name

    def test_eksporti_keeps_utf8_content_human_readable(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        entry = _make_entry(
            uuid="eeeeeeee-0000-0000-0000-000000000000",
            titolo="système d'exploitation Linux",
            difinio="système de base",
            terminologio={"fr": "système d'exploitation Linux"},
            difinoj={"fr": "système de base"},
        )
        _load_db_fixture([entry], db_path)
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        out_path = tmp_path / "utf8.enc"
        result = runner.invoke(
            app,
            ["encik", "eksporti", "système d'exploitation Linux", str(out_path)],
        )

        assert result.exit_code == 0, result.output
        content = out_path.read_text(encoding="utf-8")
        assert 'terminologio.fr = "système d\'exploitation Linux"' in content
        assert 'difino.fr = "système de base"' in content
        assert "\\u00" not in content

    def test_serci_subklasoj(self, tmp_path):
        # Animal -> Mammal
        parent_enc = tmp_path / "animal.enc"
        parent_enc.write_text(
            'terminologio.eo = "Animal"\ndifinio.eo = "Root"\n', encoding="utf-8"
        )
        r1 = runner.invoke(app, ["encik", "aldoni", str(parent_enc)])
        assert r1.exit_code == 0, r1.output

        # Get the UUID of Animal
        import autish.commands.encik as enc_mod

        animal = enc_mod._find_by_title_exact("Animal")
        assert animal is not None

        child_enc = tmp_path / "mammal.enc"
        child_enc.write_text(
            f'terminologio.eo = "Mammal"\ndifinio.eo = "Child"\n'
            f'superklaso = ["{animal["uuid"]}"]\n',
            encoding="utf-8",
        )
        r2 = runner.invoke(app, ["encik", "aldoni", str(child_enc)])
        assert r2.exit_code == 0, r2.output

        result = runner.invoke(app, ["encik", "serci", "-s", "Animal"])
        assert result.exit_code == 0, result.output
        assert "Mammal" in result.output

    def test_serci_superklasoj(self, tmp_path):
        parent_enc = tmp_path / "a.enc"
        parent_enc.write_text(
            'terminologio.eo = "Science"\ndifinio.eo = "Root"\n', encoding="utf-8"
        )
        runner.invoke(app, ["encik", "aldoni", str(parent_enc)])

        import autish.commands.encik as enc_mod

        science = enc_mod._find_by_title_exact("Science")
        assert science is not None

        child_enc = tmp_path / "b.enc"
        science_uuid = science["uuid"]
        child_enc.write_text(
            f'terminologio.eo = "Physics"\ndifinio.eo = "Child"\n'
            f'superklaso = ["{science_uuid}"]\n',
            encoding="utf-8",
        )
        runner.invoke(app, ["encik", "aldoni", str(child_enc)])

        result = runner.invoke(app, ["encik", "serci", "-S", "Physics"])
        assert result.exit_code == 0, result.output
        assert "Science" in result.output

    def test_serci_paralela_uses_positional_root_with_p_flag(self, tmp_path):
        parent = tmp_path / "animal.enc"
        parent.write_text(
            'terminologio.eo = "Animal"\ndifinio.eo = "Root"\n', encoding="utf-8"
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        root = enc_mod._find_by_title_exact("Animal")
        assert root is not None
        root_uuid_prefix = root["uuid"][:8]

        dog = tmp_path / "dog.enc"
        dog.write_text(
            'terminologio.eo = "Dog"\n'
            'difinio.eo = "A mammal."\n'
            f'superklaso = ["{root_uuid_prefix}"]\n',
            encoding="utf-8",
        )
        cat = tmp_path / "cat.enc"
        cat.write_text(
            'terminologio.eo = "Cat"\n'
            'difinio.eo = "Another mammal."\n'
            f'superklaso = ["{root_uuid_prefix}"]\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(dog)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(cat)]).exit_code == 0

        result = runner.invoke(app, ["encik", "serci", "-P", "Dog"])
        assert result.exit_code == 0, result.output
        assert "Paralela (Dog)" in result.output
        assert "Cat" in result.output

    def test_serci_paralela_without_root_errors(self):
        result = runner.invoke(app, ["encik", "serci", "-P"])
        assert result.exit_code != 0
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "mankas radika nodo" in combined

    def test_serci_semantiko_with_al_filters_target(self, tmp_path):
        class_uuid = "10000000-0000-0000-0000-000000000001"
        instance_uuid = "20000000-0000-0000-0000-000000000002"
        other_uuid = "30000000-0000-0000-0000-000000000003"
        _load_db_fixture(
            [
                _make_entry(uuid=class_uuid, titolo="Class"),
                _make_entry(
                    uuid=instance_uuid,
                    titolo="Instance",
                    ligilo=[[class_uuid, "rdf:type"]],
                ),
                _make_entry(uuid=other_uuid, titolo="Other"),
            ],
            tmp_path / "encik.db",
        )

        hit = runner.invoke(
            app,
            ["encik", "serci", "--semantiko", "rdf:type", "--al", "Class"],
        )
        assert hit.exit_code == 0, hit.output
        assert "Semantikaj ligiloj (rdf:type):" in hit.output
        assert "Instance" in hit.output
        assert "Class" in hit.output

        miss = runner.invoke(
            app,
            ["encik", "serci", "--semantiko", "rdf:type", "--al", "Other"],
        )
        assert miss.exit_code == 0, miss.output
        assert "Neniu semantika ligilo trovita." in miss.output

    def test_serci_semantiko_accepts_sm_alias_and_target_clause(self, tmp_path):
        class_uuid = "10000000-0000-0000-0000-000000000001"
        instance_uuid = "20000000-0000-0000-0000-000000000002"
        _load_db_fixture(
            [
                _make_entry(uuid=class_uuid, titolo="Class"),
                _make_entry(
                    uuid=instance_uuid,
                    titolo="Instance",
                    ligilo=[[class_uuid, "rdf:type"]],
                ),
            ],
            tmp_path / "encik.db",
        )

        result = runner.invoke(
            app,
            ["encik", "serci", "-sm", f"rdf:type #{class_uuid[:8]};"],
        )
        assert result.exit_code == 0, result.output
        assert "Semantikaj ligiloj (rdf:type):" in result.output
        assert "Instance" in result.output
        assert "Class" in result.output

    def test_serci_semantiko_supports_multiple_and_conditions(self, tmp_path):
        class_uuid = "10000000-0000-0000-0000-000000000001"
        whole_uuid = "30000000-0000-0000-0000-000000000003"
        inst_ok = "20000000-0000-0000-0000-000000000002"
        inst_partial = "40000000-0000-0000-0000-000000000004"
        _load_db_fixture(
            [
                _make_entry(uuid=class_uuid, titolo="Class"),
                _make_entry(uuid=whole_uuid, titolo="Whole"),
                _make_entry(
                    uuid=inst_ok,
                    titolo="Both",
                    ligilo=[[class_uuid, "rdf:type"], [whole_uuid, "wdt:P361"]],
                ),
                _make_entry(
                    uuid=inst_partial,
                    titolo="OnlyType",
                    ligilo=[[class_uuid, "rdf:type"]],
                ),
            ],
            tmp_path / "encik.db",
        )

        result = runner.invoke(
            app,
            [
                "encik",
                "serci",
                "--semantiko",
                f"rdf:type #{class_uuid[:8]}; wdt:P361 #{whole_uuid[:8]}",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Semantikaj ligiloj (AND-kondiĉoj):" in result.output
        assert "Both" in result.output
        assert "OnlyType" not in result.output

    def test_semantika_serci_text_and_range(self, tmp_path):
        _load_db_fixture(
            [
                _make_entry(
                    uuid="41000000-0000-0000-0000-000000000001",
                    titolo="Filozofo",
                    terminologio={"eo": "Filozofo"},
                    semantika=[
                        {
                            "tipo": "str",
                            "arko": "wdt:P5191",
                            "valoro": "historio de philosophia",
                        },
                        {
                            "tipo": "int",
                            "arko": "wdt:P1082",
                            "valoro": 890,
                            "unuo": "abcde",
                        },
                        {"tipo": "float", "arko": "wdt:P2046", "valoro": 1.5},
                    ],
                ),
                _make_entry(
                    uuid="42000000-0000-0000-0000-000000000002",
                    titolo="Astronomo",
                    terminologio={"eo": "Astronomo"},
                    semantika=[
                        {
                            "tipo": "str",
                            "arko": "wdt:P5191",
                            "valoro": "historio de astronomio",
                        },
                        {"tipo": "int", "arko": "wdt:P1082", "valoro": 3400},
                    ],
                ),
            ],
            tmp_path / "encik.db",
        )
        result = runner.invoke(
            app,
            [
                "encik",
                "semantika-serci",
                "wdt:P5191 *philosophia*; wdt:P1082 (0,1000)",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Filozofo" in result.output
        assert "Astronomo" not in result.output
        assert "#abcde" in result.output
        assert "SI" in result.output

    def test_semantika_serci_bool_value(self, tmp_path):
        _load_db_fixture(
            [
                _make_entry(
                    uuid="43000000-0000-0000-0000-000000000003",
                    titolo="Nodo Vera",
                    terminologio={"eo": "Nodo Vera"},
                    semantika=[{"tipo": "bool", "arko": "rdf:type", "valoro": True}],
                ),
                _make_entry(
                    uuid="44000000-0000-0000-0000-000000000004",
                    titolo="Nodo Malvera",
                    terminologio={"eo": "Nodo Malvera"},
                    semantika=[{"tipo": "bool", "arko": "rdf:type", "valoro": False}],
                ),
            ],
            tmp_path / "encik.db",
        )
        result = runner.invoke(app, ["encik", "semantika-serci", "wdt:P31 true"])
        assert result.exit_code == 0, result.output
        assert "Nodo Vera" in result.output
        assert "Nodo Malvera" not in result.output

    def test_encik_vidi_formats_semantika_as_priskribo_plus_valoro(self, tmp_path):
        _load_db_fixture(
            [
                _make_entry(
                    uuid="45000000-0000-0000-0000-000000000005",
                    titolo="Nodo Demografio",
                    terminologio={"eo": "Nodo Demografio"},
                    semantika=[{"tipo": "int", "arko": "wdt:P1082", "valoro": 890}],
                )
            ],
            tmp_path / "encik.db",
        )
        result = runner.invoke(app, ["encik", "vidi", "Nodo Demografio"])
        assert result.exit_code == 0, result.output
        assert "loĝantaro / populacio" in result.output
        assert "890" in result.output
        assert "wdt:P1082 890" not in result.output

    def test_semantika_serci_invalid_range_errors(self):
        result = runner.invoke(app, ["encik", "semantika-serci", "wdt:P1082 (1000,0)"])
        assert result.exit_code != 0
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "minimumo" in combined

    def test_semantika_subcommand_serci_finds_local_group_entries(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            lambda _prop_id, _langs: {
                "etikedo": "population",
                "priskribo": "Loĝantaro",
                "aliasoj": ["population", "p1082"],
            },
        )
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_search_properties",
            lambda _query, _langs: [],
        )
        add = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert add.exit_code == 0, add.output
        result = runner.invoke(app, ["encik", "semantika", "serci", "P1082"])
        assert result.exit_code == 0, result.output
        assert "demografio" in result.output
        assert "wdt:P1082" in result.output

    def test_semantika_aldoni_registers_new_group_subcommand(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            lambda _prop_id, _langs: {
                "etikedo": "population",
                "priskribo": "Loĝantaro",
                "aliasoj": ["population", "p1082"],
            },
        )
        add = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert add.exit_code == 0, add.output
        show_group = runner.invoke(app, ["encik", "semantika", "demografio"])
        assert show_group.exit_code == 0, show_group.output
        assert "wdt:P1082" in show_group.output

    def test_semantika_aldoni_duplicate_no_overwrite(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            lambda _prop_id, _langs: {
                "etikedo": "population",
                "priskribo": "Loĝantaro",
                "aliasoj": ["population", "p1082"],
            },
        )
        add = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert add.exit_code == 0, add.output
        deny = runner.invoke(
            app,
            [
                "encik",
                "semantika",
                "aldoni",
                "P1082",
                "demografio",
                "--priskribo",
                "Nova priskribo",
            ],
            input="n\n",
        )
        assert deny.exit_code == 0, deny.output
        merged = deny.output.lower() + (deny.stderr or "").lower()
        assert "jam ekzistas" in merged
        assert "nuligita" in merged
        show_group = runner.invoke(app, ["encik", "semantika", "demografio"])
        assert show_group.exit_code == 0, show_group.output
        assert "Loĝantaro" in show_group.output
        assert "Nova priskribo" not in show_group.output

    def test_semantika_aldoni_duplicate_overwrite(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            lambda _prop_id, _langs: {
                "etikedo": "population",
                "priskribo": "Loĝantaro",
                "aliasoj": ["population", "p1082"],
            },
        )
        add = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert add.exit_code == 0, add.output
        overwrite = runner.invoke(
            app,
            [
                "encik",
                "semantika",
                "aldoni",
                "P1082",
                "demografio",
                "--priskribo",
                "Nova priskribo",
                "--aliazoj",
                "p1082,populacio",
            ],
            input="j\n",
        )
        assert overwrite.exit_code == 0, overwrite.output
        assert "Anstataŭigis wdt:P1082" in overwrite.output
        show_group = runner.invoke(app, ["encik", "semantika", "demografio"])
        assert show_group.exit_code == 0, show_group.output
        assert "Nova priskribo" in show_group.output
        assert show_group.output.count("wdt:P1082") == 1

    def test_semantika_aldoni_offline_requires_priskribo(self, monkeypatch):
        def _offline(*_args, **_kwargs):
            raise RuntimeError("Wikidata API neatingebla")

        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            _offline,
        )
        result = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert result.exit_code != 0
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "offline fallback" in combined
        assert "--priskribo" in combined

    def test_semantika_aldoni_offline_accepts_manual_csv_fields(self, monkeypatch):
        def _offline(*_args, **_kwargs):
            raise RuntimeError("Wikidata API neatingebla")

        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            _offline,
        )
        result = runner.invoke(
            app,
            [
                "encik",
                "semantika",
                "aldoni",
                "P1082",
                "demografio",
                "--priskribo",
                "Loĝantaro",
                "--aliazoj",
                "p1082,population",
            ],
            input="j\n",
        )
        assert result.exit_code == 0, result.output
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "ne validigita kontraŭ wikidata" in combined

    def test_semantika_serci_shows_wikidata_results(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_search_properties",
            lambda _query, _langs: [
                {
                    "fonto": "wikidata",
                    "grupo": "-",
                    "ligilo": "wdt:P1082",
                    "priskribo": "population",
                    "aliasoj": ["p1082"],
                }
            ],
        )
        result = runner.invoke(app, ["encik", "semantika", "serci", "P1082"])
        assert result.exit_code == 0, result.output
        assert "wikidata" in result.output.lower()
        assert "wdt:P1082" in result.output

    def test_semantika_serci_languages_uses_profile_order_then_eo_en(
        self, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        monkeypatch.setattr(
            enc_mod,
            "_load_user_language_preferences",
            lambda: (["fr", "de"], False),
        )
        assert enc_mod._semantika_serci_languages(None) == ["fr", "de", "eo", "en"]

    def test_load_user_language_preferences_accepts_lingvo_csv(self, monkeypatch):
        import autish.commands.encik as enc_mod
        import autish.commands.uzanto as uz_mod

        monkeypatch.setattr(
            uz_mod,
            "_load_profile",
            lambda quiet=True: {"lingvo": "fr,de"},
        )
        langs, show_hint = enc_mod._load_user_language_preferences()
        assert langs == ["fr", "de"]
        assert show_hint is False

    def test_wikidata_property_metadata_falls_back_to_eo_then_en(self, monkeypatch):
        import autish.commands.encik as enc_mod

        captured: dict[str, str] = {}

        def _fake_api_get(params: dict[str, str], *, timeout: float = 5.0) -> dict:
            captured["languages"] = params.get("languages", "")
            return {
                "entities": {
                    "P1082": {
                        "labels": {
                            "fr": {"language": "fr", "value": "Population"},
                            "eo": {"language": "eo", "value": "Loĝantaro"},
                            "en": {"language": "en", "value": "Population"},
                        },
                        "descriptions": {
                            "eo": {"language": "eo", "value": "Esperanta priskribo"},
                            "en": {"language": "en", "value": "English description"},
                        },
                        "aliases": {
                            "eo": [
                                {"language": "eo", "value": "populacio"},
                            ],
                            "en": [
                                {"language": "en", "value": "population"},
                            ],
                        },
                    }
                }
            }

        monkeypatch.setattr(enc_mod, "_wikidata_api_get", _fake_api_get)
        meta = enc_mod._wikidata_property_metadata("P1082", ["fr", "de"])
        assert captured["languages"] == "fr|de|eo|en"
        assert meta["priskribo"] == "Esperanta priskribo"
        assert meta["aliasoj"][:2] == ["populacio", "population"]

    def test_wikidata_search_properties_prefers_localized_metadata(
        self, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        calls: list[str] = []

        def _fake_api_get(params: dict[str, str], *, timeout: float = 5.0) -> dict:
            calls.append(str(params.get("action") or ""))
            if params.get("action") == "wbsearchentities":
                return {
                    "search": [
                        {
                            "id": "P1082",
                            "label": "Population",
                            "description": "English default",
                            "match": {"text": "population"},
                        }
                    ]
                }
            if params.get("action") == "wbgetentities":
                assert params.get("languages") == "fr|de|eo|en"
                return {
                    "entities": {
                        "P1082": {
                            "labels": {
                                "fr": {"language": "fr", "value": "Population (FR)"},
                                "eo": {"language": "eo", "value": "Loĝantaro"},
                            },
                            "descriptions": {
                                "eo": {
                                    "language": "eo",
                                    "value": "Esperanta priskribo",
                                },
                                "en": {
                                    "language": "en",
                                    "value": "English description",
                                },
                            },
                            "aliases": {
                                "eo": [{"language": "eo", "value": "populacio"}],
                                "en": [{"language": "en", "value": "population"}],
                            },
                        }
                    }
                }
            raise AssertionError(f"Neatendita Wikidata ago: {params}")

        monkeypatch.setattr(enc_mod, "_wikidata_api_get", _fake_api_get)
        rows = enc_mod._wikidata_search_properties("population", ["fr", "de"])
        assert "wbgetentities" in calls
        assert len(rows) == 1
        assert rows[0]["etikedo"] == "Population (FR)"
        assert rows[0]["priskribo"] == "Esperanta priskribo"
        assert rows[0]["aliasoj"][0] == "populacio"

    def test_semantika_serci_offline_falls_back_to_local(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.encik._wikidata_property_metadata",
            lambda _prop_id, _langs: {
                "etikedo": "population",
                "priskribo": "Loĝantaro",
                "aliasoj": ["population", "p1082"],
            },
        )
        add = runner.invoke(
            app,
            ["encik", "semantika", "aldoni", "P1082", "demografio"],
            input="j\n",
        )
        assert add.exit_code == 0, add.output

        def _offline(*_args, **_kwargs):
            raise RuntimeError("Wikidata API neatingebla")

        monkeypatch.setattr(
            "autish.commands.encik._wikidata_search_properties",
            _offline,
        )
        result = runner.invoke(app, ["encik", "semantika", "serci", "P1082"])
        assert result.exit_code == 0, result.output
        combined = result.output.lower() + (result.stderr or "").lower()
        assert "fallback" in combined
        assert "demografio" in result.output

    def test_serci_subklasoj_accepts_hash_uuid_reference(self, tmp_path):
        parent = tmp_path / "physics.enc"
        parent.write_text(
            'terminologio.eo = "Physics"\ndifinio.eo = "Root node."\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        parent_entry = enc_mod._find_by_title_exact("Physics")
        assert parent_entry is not None
        parent_short = parent_entry["uuid"][:8]
        child = tmp_path / "quantum.enc"
        child.write_text(
            'terminologio.eo = "Quantum"\n'
            'difinio.eo = "Child node."\n'
            f'superklaso = ["#{parent_short}"]\n',
            encoding="utf-8",
        )
        add_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert add_child.exit_code == 0, add_child.output

        result = runner.invoke(
            app,
            ["encik", "serci", "--subklasoj", f"#{parent_short}"],
        )
        assert result.exit_code == 0, result.output
        assert "Quantum" in result.output

    def test_serci_ligilo_opens_html_graph(self, tmp_path, monkeypatch):
        import uuid as _uuid_mod

        suffix = _uuid_mod.uuid4().hex[:8]
        root_title = f"Root-{suffix}"
        child_title = f"Child-{suffix}"
        root = tmp_path / "root.enc"
        root.write_text(
            f'terminologio.eo = "{root_title}"\ndifinio.eo = "R"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(root)]).exit_code == 0
        import autish.commands.encik as enc_mod

        root_entry = enc_mod._find_by_title_exact(root_title)
        assert root_entry is not None
        child = tmp_path / "child.enc"
        child.write_text(
            f'terminologio.eo = "{child_title}"\n'
            'difino.eo = "C"\n'
            f'superklaso = ["{root_entry["uuid"][:8]}"]\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "serci", "--ligilo", root_title])
        assert result.exit_code == 0, result.output
        assert "Malfermas rilatan mapon" in result.output
        path = Path(opened["url"][7:])
        html = path.read_text(encoding="utf-8")
        assert "new vis.Network" in html
        assert root_title in html

    def test_serci_html_opens_search_graph(self, tmp_path, monkeypatch):
        root = tmp_path / "r.enc"
        root.write_text(
            'terminologio.eo = "Radiko"\ndifinio.eo = "Noda bazo."\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(root)]).exit_code == 0
        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "serci", "Radiko", "--html"])
        assert result.exit_code == 0, result.output
        assert "Malfermas serĉan mapon en retumilo" in result.output
        html = Path(opened["url"][7:]).read_text(encoding="utf-8")
        assert "new vis.Network" in html
        assert "Radiko" in html
        assert '"springLength": 95' in html
        assert "document.addEventListener('keydown'" in html
        assert "ev.ctrlKey" in html
        assert "['+','-','=','_']" in html
        assert "network.moveTo" in html

    def test_serci_html_graph_prefers_locale_titles_and_shows_semantic_labels(
        self, tmp_path, monkeypatch
    ):
        class_uuid = "90000000-0000-0000-0000-000000000001"
        instance_uuid = "90000000-0000-0000-0000-000000000002"
        _load_db_fixture(
            [
                _make_entry(
                    uuid=class_uuid,
                    titolo="Klaso",
                    terminologio={"eo": "Klaso", "en": "Class"},
                ),
                _make_entry(
                    uuid=instance_uuid,
                    titolo="Instanco",
                    terminologio={"eo": "Instanco", "en": "Instance"},
                    ligilo=[[class_uuid, "rdf:type"]],
                ),
            ],
            tmp_path / "encik.db",
        )

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(
            app,
            ["encik", "serci", "--semantiko", "rdf:type", "--html"],
        )
        assert result.exit_code == 0, result.output
        assert "Malfermas semantikan mapon en retumilo" in result.output
        html = Path(opened["url"][7:]).read_text(encoding="utf-8")
        assert "rdf:type" in html
        assert "Class" in html
        assert "Instance" in html

    def test_serci_preciza_disables_fuzzy_fallback(self, tmp_path):
        enc = tmp_path / "fuzzy.enc"
        enc.write_text(
            'terminologio.eo = "programaro"\ndifinio.eo = "aro de instrukcioj."\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        fuzzy = runner.invoke(app, ["encik", "serci", "programa"])
        assert fuzzy.exit_code == 0, fuzzy.output
        assert "programaro" in fuzzy.output

        precise = runner.invoke(app, ["encik", "serci", "--preciza", "programa"])
        assert precise.exit_code == 0, precise.output
        assert "Neniu nodo trovita por 'programa'." in precise.output

    def test_modifi_not_found(self):
        result = runner.invoke(app, ["encik", "modifi", "does-not-exist"])
        assert result.exit_code != 0

    def test_modifi_supports_hash_uuid(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "HashEdit", "Original.")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        import autish.commands.encik as enc_mod

        entry = enc_mod._find_by_title_exact("HashEdit")
        assert entry is not None

        def _fake_run(cmd, **kwargs):
            Path(cmd[1]).write_text(
                'terminologio.eo = "HashEdit"\ndifinio.eo = "Updated."\n',
                encoding="utf-8",
            )

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setattr(enc_mod.subprocess, "run", _fake_run)
        result = runner.invoke(app, ["encik", "modifi", f"#{entry['uuid'][:8]}"])
        assert result.exit_code == 0, result.output
        assert "Modifis" in result.output

    def test_modifi_invokes_editor(self, tmp_path, monkeypatch):
        """modifi should open $EDITOR on the temp .enc file and save changes."""
        # First add an entry
        enc = self._make_enc_file(tmp_path, "EditMe", "Original.")
        runner.invoke(app, ["encik", "aldoni", str(enc)])

        # Mock subprocess.run to write a modified .enc file
        def _fake_run(cmd, **kwargs):
            # cmd[1] is the temp file path
            Path(cmd[1]).write_text(
                'terminologio.eo = "EditMe"\ndifinio.eo = "Updated."\n',
                encoding="utf-8",
            )

            class _R:
                returncode = 0

            return _R()

        import autish.commands.encik as enc_mod

        monkeypatch.setattr(enc_mod.subprocess, "run", _fake_run)

        result = runner.invoke(app, ["encik", "modifi", "EditMe"])
        assert result.exit_code == 0, result.output
        assert "Modifis" in result.output

        # Verify DB was updated
        updated = enc_mod._find_by_title_exact("EditMe")
        assert updated is not None
        assert updated["difinio"] == "Updated."

    def test_modifi_accepts_replacement_enc_file(self, tmp_path):
        base = self._make_enc_file(tmp_path, "ReplaceMe", "Original.")
        add = runner.invoke(app, ["encik", "aldoni", str(base)])
        assert add.exit_code == 0, add.output

        replacement = tmp_path / "replacement.enc"
        replacement.write_text(
            'terminologio.eo = "ReplaceMe"\ndifinio.eo = "From file."\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["encik", "modifi", "ReplaceMe", str(replacement)])
        assert result.exit_code == 0, result.output
        assert "Modifis" in result.output

        import autish.commands.encik as enc_mod

        updated = enc_mod._find_by_title_exact("ReplaceMe")
        assert updated is not None
        assert updated["difinio"] == "From file."

    def test_modifi_supports_cli_field_updates(self, tmp_path):
        base = self._make_enc_file(tmp_path, "CliEdit", "Original.")
        add = runner.invoke(app, ["encik", "aldoni", str(base)])
        assert add.exit_code == 0, add.output

        result = runner.invoke(
            app,
            [
                "encik",
                "modifi",
                "CliEdit",
                "--terminologio",
                "fr:Bonjour",
                "--difino",
                "fr:Salut.",
                "--ligilo",
                "11111111-2222-3333-4444-555555555555:rdf:type",
            ],
        )
        assert result.exit_code == 0, result.output

        import autish.commands.encik as enc_mod

        updated = enc_mod._find_by_title_exact("CliEdit")
        assert updated is not None
        assert updated["terminologio"]["fr"] == "Bonjour"
        assert updated["difinoj"]["fr"] == "Salut."
        assert ["11111111-2222-3333-4444-555555555555", "rdf:type"] in (
            updated.get("ligilo") or []
        )

    def test_modifi_parse_error_preserves_invalid_file(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "BrokenEdit", "Original.")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        import autish.commands.encik as enc_mod

        entry = enc_mod._find_by_title_exact("BrokenEdit")
        assert entry is not None

        def _fake_run(cmd, **kwargs):
            Path(cmd[1]).write_text(
                'terminologio.eo = "BrokenEdit"\ndifinio.eo = [bad]\n',
                encoding="utf-8",
            )

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setattr(enc_mod.subprocess, "run", _fake_run)
        result = runner.invoke(app, ["encik", "modifi", "BrokenEdit"])
        assert result.exit_code != 0
        invalid_path = enc_mod._invalid_edit_path(entry["uuid"])
        assert invalid_path.exists()
        assert "encik modifi -- " in (result.output + (result.stderr or ""))

    def test_modifi_reuses_preserved_invalid_file(self, tmp_path, monkeypatch):
        enc = self._make_enc_file(tmp_path, "ResumeEdit", "Original.")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        import autish.commands.encik as enc_mod

        entry = enc_mod._find_by_title_exact("ResumeEdit")
        assert entry is not None
        invalid_path = enc_mod._invalid_edit_path(entry["uuid"])
        invalid_path.parent.mkdir(parents=True, exist_ok=True)
        invalid_path.write_text(
            'terminologio.eo = "ResumeEdit"\ndifinio.eo = "From preserved"\n',
            encoding="utf-8",
        )

        seen: dict[str, str] = {}

        def _fake_run(cmd, **kwargs):
            seen["text"] = Path(cmd[1]).read_text(encoding="utf-8")

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setattr(enc_mod.subprocess, "run", _fake_run)
        result = runner.invoke(app, ["encik", "modifi", "ResumeEdit"])
        assert result.exit_code == 0, result.output
        assert "From preserved" in seen["text"]

    def test_entry_to_enc_template_includes_tipo_hint(self):
        text = _entry_to_enc(_make_entry(titolo="Tipo Hint"))
        assert "Validaj tipoj:" in text

    def test_encik_vidi_supports_hash_uuid(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "Hash Node", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        import autish.commands.encik as enc_mod

        entry = enc_mod._find_by_title_exact("Hash Node")
        assert entry is not None
        result = runner.invoke(app, ["encik", "vidi", f"#{entry['uuid'][:8]}"])
        assert result.exit_code == 0, result.output
        assert "Hash Node" in result.output

    def test_encik_vidi_missing_ref_shows_hash_hint(self):
        result = runner.invoke(app, ["encik", "vidi"])
        assert result.exit_code != 0
        combined = result.output + (result.stderr or "")
        assert 'encik vidi "#' in combined

    def test_encik_vidi_with_lingvo_and_all(self, tmp_path):
        enc = tmp_path / "multi.enc"
        enc.write_text(
            'terminologio.eo = "Hundo"\n'
            'terminologio.en = "Dog"\n'
            'difinio.eo = "Besto"\n'
            'difinio.en = "Animal"\n'
            '"""\n'
            "Aldona enhavo.\n"
            '"""\n'
            'fonto = [{author = "A", year = "2020", type = "lib", title = "Libro"}]\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        result = runner.invoke(app, ["encik", "vidi", "Dog", "-l", "en", "-a"])
        assert result.exit_code == 0, result.output
        assert "Animal" in result.output
        assert "Aldona enhavo" in result.output
        assert "libroj" in result.output
        assert "difinoj:" not in result.output
        assert result.output.count("difino:") == 1

    def test_encik_vidi_ambiguous_prompts_up_to_five(self, tmp_path):
        for i in range(6):
            enc = tmp_path / f"n{i}.enc"
            enc.write_text(
                f'terminologio.eo = "Koncepto{i}"\n'
                f'terminologio.en = "Term common {i}"\n'
                'difinio.eo = "Difino"\n'
                'difinio.en = "Definition"\n',
                encoding="utf-8",
            )
            runner.invoke(app, ["encik", "aldoni", str(enc)])

        result = runner.invoke(app, ["encik", "vidi", "Term common"], input="1\n")
        assert result.exit_code == 0, result.output
        assert "Elektu numeron" in result.output

    def test_encik_vidi_html_opens_browser_with_rendered_table(
        self, tmp_path, monkeypatch
    ):
        enc = tmp_path / "html.enc"
        enc.write_text(
            'terminologio.eo = "Hundo"\ndifinio.eo = "**Besto**"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "Hundo", "--html"])
        assert result.exit_code == 0, result.output
        assert "Malfermas en retumilo:" in result.output
        assert opened["url"].startswith("file://")
        html_path = Path(opened["url"][7:])
        html_content = html_path.read_text(encoding="utf-8")
        assert "<table>" in html_content
        assert "<strong>Besto</strong>" in html_content

    def test_encik_vidi_html_markdown_internal_link_targets_entry(
        self, tmp_path, monkeypatch
    ):
        parent = tmp_path / "target.enc"
        parent.write_text(
            'terminologio.eo = "Celo"\ndifinio.eo = "Cela difino"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Celo")
        assert target is not None

        source = tmp_path / "source.enc"
        source.write_text(
            'terminologio.eo = "Fonto"\n'
            f'difinio.eo = "Vidu [Celo](#{target["uuid"][:8]}) nun."\n',
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "Fonto", "--html"])
        assert result.exit_code == 0, result.output
        html_path = Path(opened["url"][7:])
        html_content = html_path.read_text(encoding="utf-8")
        assert "Vidu" in html_content
        assert "file://" in html_content

    def test_encik_vidi_cli_renders_internal_markdown_link(self, tmp_path, monkeypatch):
        parent = tmp_path / "target_cli.enc"
        parent.write_text(
            'terminologio.eo = "Hugging Face"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Hugging Face")
        assert target is not None

        source = tmp_path / "source_cli.enc"
        source.write_text(
            'terminologio.eo = "Fonta nodo"\n'
            f'difinio.eo = "[Hugging Face](#{target["uuid"][:8]})"\n',
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output

        result = runner.invoke(app, ["encik", "vidi", "Fonta nodo"])
        assert result.exit_code == 0, result.output
        assert "Hugging Face" in result.output
        assert "[Hugging Face](#" not in result.output

        rendered = _render_markdown_text(f"[Hugging Face](#{target['uuid'][:8]})")
        assert "[link=file://" in rendered
        assert "[dim]#" not in rendered

    def test_encik_vidi_cli_renders_internal_semantic_markdown_link(self, tmp_path):
        parent = tmp_path / "target_cli_semantic.enc"
        parent.write_text(
            'terminologio.eo = "Semantika Nodo"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Semantika Nodo")
        assert target is not None
        rendered = _render_markdown_text(
            f"[Semantika Nodo](#{target['uuid'][:8]},rdfs:subClassOf)"
        )
        assert "[link=file://" in rendered
        assert "Semantika Nodo" in rendered
        assert "[dim]#" not in rendered

    def test_relation_helpers_render_clickable_links(self, tmp_path):
        parent = tmp_path / "target_relation.enc"
        parent.write_text(
            'terminologio.eo = "Nodo"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Nodo")
        assert target is not None
        cli = _render_relation_cli_link("Nodo", target["uuid"][:8])
        html = _render_relation_html_link("Nodo", target["uuid"][:8])
        assert "[link=file://" in cli
        assert '<a href="file://' in html

    def test_relation_html_link_does_not_duplicate_hash_fallback_label(self, tmp_path):
        orphan_ref = "86c80457"
        html = _render_relation_html_link(f"#{orphan_ref}", orphan_ref)
        assert html == f"#{orphan_ref}"

    def test_relation_html_link_normalizes_double_hash_label(self):
        html = _render_relation_html_link("##c8ec772", "c8ec7722")
        assert "##c8ec772" not in html

    def test_relation_html_link_makes_uuid_clickable(self, tmp_path):
        parent = tmp_path / "target_uuid_click.enc"
        parent.write_text(
            'terminologio.eo = "Nodo por UUID ligilo"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Nodo por UUID ligilo")
        assert target is not None
        html = _render_relation_html_link("Nodo por UUID ligilo", target["uuid"][:8])
        assert html.count("file://") >= 2

    def test_relation_html_link_nested_depth_does_not_use_self_anchor(self, tmp_path):
        parent = tmp_path / "target_no_anchor.enc"
        parent.write_text(
            'terminologio.eo = "Nodo sen ankro"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Nodo sen ankro")
        assert target is not None
        html = _render_relation_html_link(
            "Nodo sen ankro", target["uuid"][:8], link_depth=1
        )
        assert 'href="#' not in html
        assert f"#{target['uuid'][:8]}" in html

    def test_encik_vidi_orders_ligilo_by_semantics_then_name(self, tmp_path):
        import autish.commands.encik as enc_mod

        targets = [
            "Homo sapiens",
            "Biologio",
            "Inverse Link",
            "Disjoint Link",
            "projet de loi Devaquet",
            "Alia Alfa",
        ]
        uuids: dict[str, str] = {}
        for idx, title in enumerate(targets, 1):
            p = tmp_path / f"t{idx}.enc"
            p.write_text(
                f'terminologio.eo = "{title}"\ndifinio.eo = "Difino"\n',
                encoding="utf-8",
            )
            assert runner.invoke(app, ["encik", "aldoni", str(p)]).exit_code == 0
            e = enc_mod._find_by_title_exact(title)
            assert e is not None
            uuids[title] = str(e["uuid"])

        source = tmp_path / "source_sort.enc"
        source.write_text(
            'terminologio.eo = "Source"\n'
            'difinio.eo = "Difino"\n'
            f'superklaso = ["{uuids["Biologio"][:8]}"]\n'
            "ligilo = [\n"
            f'  ["{uuids["Homo sapiens"][:8]}", "rdf:type"],\n'
            f'  ["{uuids["Inverse Link"][:8]}", "owl:inverseOf"],\n'
            f'  ["{uuids["Disjoint Link"][:8]}", "owl:disjointWith"],\n'
            f'  "{uuids["projet de loi Devaquet"][:8]}",\n'
            f'  "{uuids["Alia Alfa"][:8]}"\n'
            "]\n",
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output

        out = runner.invoke(app, ["encik", "vidi", "Source", "-a"])
        assert out.exit_code == 0, out.output
        text = out.output
        i_type = text.find("rdf:type")
        i_inverse = text.find("owl:inverseOf")
        i_disjoint = text.find("owl:disjointWith")
        i_alpha = text.find("Alia Alfa")
        i_dev = text.rfind("Devaquet")
        assert -1 not in (i_type, i_inverse, i_disjoint, i_alpha, i_dev)
        assert i_type < i_inverse < i_disjoint < i_alpha < i_dev

    def test_encik_vidi_html_title_field_supports_markdown_link(
        self, tmp_path, monkeypatch
    ):
        parent = tmp_path / "target_title.enc"
        parent.write_text(
            'terminologio.eo = "Cela Titolo"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        target = enc_mod._find_by_title_exact("Cela Titolo")
        assert target is not None

        source = tmp_path / "source_title.enc"
        source.write_text(
            f'terminologio.eo = "[Ir al Celo](#{target["uuid"][:8]})"\n'
            'difinio.eo = "Difino."\n',
            encoding="utf-8",
        )
        add_source = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_source.exit_code == 0, add_source.output

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "[Ir al Celo]", "--html"])
        assert result.exit_code == 0, result.output
        html_path = Path(opened["url"][7:])
        html_content = html_path.read_text(encoding="utf-8")
        assert "<h1>" in html_content
        assert "file://" in html_content

    def test_encik_vidi_html_includes_katex_and_datumo(self, tmp_path, monkeypatch):
        source = tmp_path / "math_data.enc"
        source.write_text(
            'terminologio.eo = "Matematika nodo"\n'
            'difino.eo = "Formulo: $x^2$ kaj $$y = mx + b$$."\n'
            'datumo.ekz = """\n'
            '{"datumo":[["jaro","valoro"],[2010,1.2]],"meta":{"landoj":"Francio"}}\n'
            '"""\n',
            encoding="utf-8",
        )
        add_result = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add_result.exit_code == 0, add_result.output

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "Matematika nodo", "--html"])
        assert result.exit_code == 0, result.output
        html_path = Path(opened["url"][7:])
        html_content = html_path.read_text(encoding="utf-8")
        assert "katex" in html_content.lower()
        assert "renderMathInElement" in html_content
        assert "ekz" in html_content

    def test_aldoni_help_mentions_new_enc_syntax(self):
        result = runner.invoke(app, ["encik", "aldoni", "-h"])
        assert result.exit_code == 0
        assert "terminologio.xx" in result.output
        assert "fonto" in result.output
        assert "superklaso" in result.output
        assert "ligilo" in result.output
        assert "semantika" in result.output
        assert "# tiu ĉi estas komento" in result.output
        assert "Validaj fonto.tipo" in result.output
        assert "Semantikaj ligiloj" in result.output
        assert "Plena listo: encik semantika" in result.output

    def test_encik_vidi_renders_superklaso_as_rdfs_subclassof_ligilo(self, tmp_path):
        parent = tmp_path / "parent_super.enc"
        parent.write_text(
            'terminologio.eo = "Eŭkariotoj"\ndifinio.eo = "Patra klaso"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("Eŭkariotoj")
        assert p is not None

        child = tmp_path / "child_super.enc"
        child.write_text(
            'terminologio.eo = "Animalia"\n'
            'difinio.eo = "Regno"\n'
            f'superklaso = ["{p["uuid"][:8]}"]\n',
            encoding="utf-8",
        )
        add_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert add_child.exit_code == 0, add_child.output

        out = runner.invoke(app, ["encik", "vidi", "Animalia"])
        assert out.exit_code == 0, out.output
        assert "superklaso:" not in out.output
        assert "rdfs:subClassOf" in out.output
        assert "Eŭkariotoj" in out.output

        child_entry = enc_mod._find_by_title_exact("Animalia")
        assert child_entry is not None
        assert child_entry.get("superklaso") == []
        assert [p["uuid"], "rdfs:subClassOf"] in (child_entry.get("ligilo") or [])

    def test_encik_vidi_parses_legacy_superklaso_uuid_first_pair(self, tmp_path):
        parent = tmp_path / "parent_legacy_super.enc"
        parent.write_text(
            'terminologio.eo = "Patra klaso"\ndifinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("Patra klaso")
        assert p is not None
        child = tmp_path / "child_legacy_super.enc"
        child.write_text(
            'terminologio.eo = "Infana klaso"\n'
            'difinio.eo = "Difino"\n'
            f'superklaso = [["#{p["uuid"][:8]}", "Malnova etikedo"]]\n',
            encoding="utf-8",
        )
        add_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert add_child.exit_code == 0, add_child.output

        out = runner.invoke(app, ["encik", "vidi", "Infana klaso"])
        assert out.exit_code == 0, out.output
        assert "rdfs:subClassOf" in out.output
        assert "Patra klaso" in out.output

        child_entry = enc_mod._find_by_title_exact("Infana klaso")
        assert child_entry is not None
        assert [p["uuid"], "rdfs:subClassOf"] in (child_entry.get("ligilo") or [])

    def test_encik_vidi_displays_legacy_stored_superklaso_pairs(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)

        parent = _make_entry(
            uuid=SAMPLE_UUID,
            titolo="Hereda patro",
            terminologio={"eo": "Hereda patro"},
            difinoj={"eo": "Difino"},
            difinio="Difino",
        )
        child = _make_entry(
            uuid=CHILD_UUID,
            titolo="Hereda infano",
            terminologio={"eo": "Hereda infano"},
            difinoj={"eo": "Difino"},
            difinio="Difino",
            superklaso=[[f"#{SAMPLE_UUID[:8]}", "Malnova etikedo"]],
            ligilo=[],
        )
        _load_db_fixture([parent, child], db_path)

        out = runner.invoke(app, ["encik", "vidi", "Hereda infano"])
        assert out.exit_code == 0, out.output
        assert "rdfs:subClassOf" in out.output
        assert "Hereda patro" in out.output

    def test_encik_vidi_parent_shows_has_subclass_for_child(self, tmp_path):
        parent = tmp_path / "parent_has_sub.enc"
        parent.write_text(
            'terminologio.eo = "Animalia"\ndifinio.eo = "Regno"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0

        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("Animalia")
        assert p is not None
        child = tmp_path / "child_has_sub.enc"
        child.write_text(
            'terminologio.eo = "Vertebrata"\n'
            'difinio.eo = "Subklaso"\n'
            f'superklaso = ["{p["uuid"][:8]}"]\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0

        out = runner.invoke(app, ["encik", "vidi", "Animalia"])
        assert out.exit_code == 0, out.output
        assert "rdfs:hasSubClass" in out.output
        assert "Vertebrata" in out.output

    def test_modifi_superklaso_is_persisted_as_subclass_ligilo(self, tmp_path):
        import autish.commands.encik as enc_mod

        parent = tmp_path / "parent_mod.enc"
        parent.write_text(
            'terminologio.eo = "Gepatro"\ndifinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_mod.enc"
        child.write_text(
            'terminologio.eo = "Infano"\ndifinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0
        p = enc_mod._find_by_title_exact("Gepatro")
        c = enc_mod._find_by_title_exact("Infano")
        assert p is not None and c is not None

        mod = runner.invoke(
            app,
            ["encik", "modifi", c["uuid"][:8], "--superklaso", p["uuid"][:8]],
        )
        assert mod.exit_code == 0, mod.output
        c2 = enc_mod._find_by_title_exact("Infano")
        assert c2 is not None
        assert c2.get("superklaso") == []
        assert [p["uuid"], "rdfs:subClassOf"] in (c2.get("ligilo") or [])

    def test_encik_vidi_cli_falls_back_to_browser_for_katex_and_images(self, tmp_path):
        source = tmp_path / "math_img.enc"
        source.write_text(
            'terminologio.eo = "Luma leĝo"\n'
            'difino.eo = "$$\\\\theta_1 = \\\\theta_2$$\\n![](img.png)"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(source)])
        assert add.exit_code == 0, add.output
        out = runner.invoke(app, ["encik", "vidi", "Luma leĝo"])
        assert out.exit_code == 0, out.output
        assert "Malfermu en retumilo por KaTeX/bildoj" in out.output

    def test_encik_vidi_html_ligilo_label_strips_markdown_from_target_title(
        self, tmp_path, monkeypatch
    ):
        # First create the "lumo" entry that will be referenced
        lumo = tmp_path / "lumo.enc"
        lumo.write_text(
            'terminologio.eo = "lumo"\n'
            'difinio.eo = "Ekscitita lumpartiklo"\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["encik", "aldoni", str(lumo)])
        assert result.exit_code == 0, result.output
        
        # Extract the UUID of the lumo entry
        import autish.commands.encik as enc_mod
        lumo_entry = enc_mod._find_by_title_exact("lumo")
        assert lumo_entry is not None
        lumo_uuid = lumo_entry["uuid"][:8]
        
        # Now create the target entry that references lumo in its title
        target = tmp_path / "target_md_title.enc"
        target.write_text(
            f'terminologio.eo = "leĝo de reflekto por [lumo](#{lumo_uuid})"\n'
            'difinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(target)]).exit_code == 0

        t = enc_mod._find_by_title_exact(f"leĝo de reflekto por [lumo](#{lumo_uuid})")
        assert t is not None
        src = tmp_path / "source_md_title.enc"
        src.write_text(
            'terminologio.eo = "Fonta nodo html"\n'
            'difinio.eo = "Difino"\n'
            f'ligilo = ["{t["uuid"][:8]}"]\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(src)]).exit_code == 0
        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "Fonta nodo html", "--html"])
        assert result.exit_code == 0, result.output
        html = Path(opened["url"][7:]).read_text(encoding="utf-8")
        assert "leĝo de reflekto por lumo" in html
        assert "[lumo](" not in html

    def test_encik_vidi_ligilo_not_duplicated_when_superklaso_and_ligilo_overlap(
        self, tmp_path
    ):
        parent = tmp_path / "parent_dup.enc"
        parent.write_text(
            'terminologio.eo = "lumradia modelo"\ndifinio.eo = "Patra nodo"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0

        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("lumradia modelo")
        assert p is not None
        child = tmp_path / "child_dup.enc"
        child.write_text(
            'terminologio.eo = "leĝo de reflekto por lumo"\n'
            'difinio.eo = "Difino"\n'
            f'superklaso = ["{p["uuid"][:8]}"]\n'
            f'ligilo = [["{p["uuid"][:8]}", "rdfs:subClassOf"]]\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0
        out = runner.invoke(app, ["encik", "vidi", "leĝo de reflekto por lumo"])
        assert out.exit_code == 0, out.output
        assert out.output.count("rdfs:subClassOf") == 1

    def test_encik_vidi_combines_multiple_semantic_arcs_for_same_ligilo(
        self, tmp_path
    ):
        target = tmp_path / "target_multi_sem.enc"
        target.write_text(
            'terminologio.eo = "Sunsistemo"\ndifinio.eo = "Celo"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(target)]).exit_code == 0

        import autish.commands.encik as enc_mod

        t = enc_mod._find_by_title_exact("Sunsistemo")
        assert t is not None
        source = tmp_path / "source_multi_sem.enc"
        source.write_text(
            'terminologio.eo = "suno"\n'
            'difinio.eo = "Stelo"\n'
            "ligilo = [\n"
            f'  ["{t["uuid"][:8]}", "wdt:P361"],\n'
            f'  ["{t["uuid"][:8]}", "rdfs:subClassOf"]\n'
            "]\n",
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(source)]).exit_code == 0

        out = runner.invoke(app, ["encik", "vidi", "suno"])
        assert out.exit_code == 0, out.output
        assert out.output.count("Sunsistemo") == 1
        assert "rdfs:subClassOf" in out.output
        assert "wdt:P361" in out.output
        assert "rdfs:subClassOf, wdt:P361*" not in out.output

    def test_relation_helper_ambiguous_short_uuid_falls_back_without_bad_link(
        self, tmp_path
    ):
        # Build two entries sharing same 8-char prefix to force ambiguity.
        _load_db_fixture(
            [
                _make_entry(
                    uuid="12345678-0000-0000-0000-000000000001",
                    titolo="Nodo A",
                ),
                _make_entry(
                    uuid="12345678-0000-0000-0000-000000000002",
                    titolo="Nodo B",
                ),
            ],
            tmp_path / "encik.db",
        )
        rendered = _render_relation_cli_link("Celo", "12345678")
        assert "[link=file://" not in rendered
        assert "#12345678" in rendered

    def test_semantika_command_defaults_to_help(self):
        result = runner.invoke(app, ["encik", "semantika"])
        assert result.exit_code == 0, result.output
        assert "generala" in result.output
        assert "persono" in result.output
        assert "geografio" in result.output
        assert "abstrakta" in result.output

    def test_semantika_aliases_map_wikidata_to_rdf_rdfs(self):
        import autish.commands.encik as enc_mod

        assert enc_mod._normalize_semantika_ligilo("wdt:P31") == "rdf:type"
        assert enc_mod._normalize_semantika_ligilo("p31") == "rdf:type"
        assert enc_mod._normalize_semantika_ligilo("wdt:P279") == "rdfs:subClassOf"
        assert enc_mod._normalize_semantika_ligilo("p279") == "rdfs:subClassOf"

    def test_semantika_help_command_mentions_serci_and_ligilo_usage(self):
        result = runner.invoke(app, ["encik", "semantika", "-h"])
        assert result.exit_code == 0, result.output
        assert "encik serci --semantiko" in result.output
        assert "encik semantika <grupo>" in result.output
        assert "encik semantika serci" in result.output

    def test_semantika_generala_lists_core_rdf_and_rdfs(self):
        result = runner.invoke(app, ["encik", "semantika", "generala"])
        assert result.exit_code == 0, result.output
        assert "rdf:type" in result.output
        assert "rdfs:subClassOf" in result.output
        assert "wdt:P361" in result.output
        assert "wdt:P527" in result.output

    def test_semantika_persono_lists_person_related_links(self):
        result = runner.invoke(app, ["encik", "semantika", "persono"])
        assert result.exit_code == 0, result.output
        assert "wdt:P50" in result.output
        assert "wdt:P106" in result.output
        assert "wdt:P69" in result.output
        assert "wdt:P569" in result.output
        assert "wdt:P570" in result.output

    def test_semantika_geografio_lists_location_and_area_links(self):
        result = runner.invoke(app, ["encik", "semantika", "geografio"])
        assert result.exit_code == 0, result.output
        assert "wdt:P17" in result.output
        assert "wdt:P131" in result.output
        assert "wdt:P2046" in result.output
        assert "wdt:P1082" in result.output

    def test_semantika_abstrakta_lists_abstract_links(self):
        result = runner.invoke(app, ["encik", "semantika", "abstrakta"])
        assert result.exit_code == 0, result.output
        assert "wdt:P5191" in result.output
        assert "owl:inverseOf" in result.output

    def test_aldoni_bidirectional_ligilo(self, tmp_path):
        base_enc = tmp_path / "a.enc"
        base_enc.write_text(
            'terminologio.eo = "A"\ndifinio.eo = "Difino A"\n',
            encoding="utf-8",
        )
        r1 = runner.invoke(app, ["encik", "aldoni", str(base_enc)])
        assert r1.exit_code == 0, r1.output
        import autish.commands.encik as enc_mod

        a = enc_mod._find_by_title_exact("A")
        assert a is not None

        child_enc = tmp_path / "b.enc"
        child_enc.write_text(
            'terminologio.eo = "B"\n'
            'difinio.eo = "Difino B"\n'
            f'ligilo = "{a["uuid"][:8]}"\n',
            encoding="utf-8",
        )
        r2 = runner.invoke(app, ["encik", "aldoni", str(child_enc)])
        assert r2.exit_code == 0, r2.output

        a2 = enc_mod._find_by_title_exact("A")
        b2 = enc_mod._find_by_title_exact("B")
        assert a2 is not None and b2 is not None
        assert b2["uuid"] in (a2.get("ligilo") or [])

    def test_aldoni_bidirectional_semantic_reverse_links(self, tmp_path):
        base = tmp_path / "class.enc"
        base.write_text(
            'terminologio.eo = "Klaso"\ndifinio.eo = "A klaso"\n',
            encoding="utf-8",
        )
        r1 = runner.invoke(app, ["encik", "aldoni", str(base)])
        assert r1.exit_code == 0, r1.output
        import autish.commands.encik as enc_mod

        klas = enc_mod._find_by_title_exact("Klaso")
        assert klas is not None

        inst = tmp_path / "instance.enc"
        inst.write_text(
            'terminologio.eo = "Instanco"\n'
            'difinio.eo = "A instanco"\n'
            f'ligilo = [["{klas["uuid"][:8]}", "rdf:type"]]\n',
            encoding="utf-8",
        )
        r2 = runner.invoke(app, ["encik", "aldoni", str(inst)])
        assert r2.exit_code == 0, r2.output
        klas2 = enc_mod._find_by_title_exact("Klaso")
        inst2 = enc_mod._find_by_title_exact("Instanco")
        assert klas2 is not None and inst2 is not None
        assert [
            inst2["uuid"],
            "rdf:hasInstance",
        ] in (klas2.get("ligilo") or [])

    def test_modifi_editor_payload_hides_auto_reverse_ligilo(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        parent = tmp_path / "parent_editor.enc"
        parent.write_text(
            'terminologio.eo = "Patra"\ndifinio.eo = "Patro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_editor.enc"
        child.write_text(
            'terminologio.eo = "Filo"\ndifinio.eo = "Filo"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0
        p = enc_mod._find_by_title_exact("Patra")
        c = enc_mod._find_by_title_exact("Filo")
        assert p is not None and c is not None

        assert (
            runner.invoke(
                app,
                [
                    "encik",
                    "modifi",
                    c["uuid"][:8],
                    "--ligilo",
                    f"{p['uuid'][:8]}:rdf:type",
                ],
            ).exit_code
            == 0
        )

        captured: dict[str, str] = {}

        def _fake_run(cmd):
            edit_path = Path(cmd[1])
            captured["content"] = edit_path.read_text(encoding="utf-8")
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr("autish.commands.encik.subprocess.run", _fake_run)
        monkeypatch.setenv("EDITOR", "fake-editor")
        result = runner.invoke(app, ["encik", "modifi", p["uuid"][:8]])
        assert result.exit_code == 0, result.output
        assert "rdf:hasInstance" not in captured.get("content", "")
        assert "__autish_auto_reverse_ligilo__" not in captured.get("content", "")

    def test_semantic_conflict_gate_rejects_same_direction_pair(self, tmp_path):
        base = tmp_path / "a.enc"
        base.write_text(
            'terminologio.eo = "A"\ndifinio.eo = "A difino"\n',
            encoding="utf-8",
        )
        other = tmp_path / "b.enc"
        other.write_text(
            'terminologio.eo = "B"\ndifinio.eo = "B difino"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(base)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(other)]).exit_code == 0

        import autish.commands.encik as enc_mod

        a = enc_mod._find_by_title_exact("A")
        b = enc_mod._find_by_title_exact("B")
        assert a is not None and b is not None

        set_ab = runner.invoke(
            app,
            ["encik", "modifi", a["uuid"][:8], "--ligilo", f"{b['uuid'][:8]}:rdf:type"],
        )
        assert set_ab.exit_code == 0, set_ab.output

        conflict = runner.invoke(
            app,
            ["encik", "modifi", b["uuid"][:8], "--ligilo", f"{a['uuid'][:8]}:rdf:type"],
        )
        assert conflict.exit_code != 0
        assert "Semantika logika konflikto" in (
            conflict.output + (conflict.stderr or "")
        )
        assert "Sugesto" in (conflict.output + (conflict.stderr or ""))
        assert "encik semantika" in (conflict.output + (conflict.stderr or ""))

    def test_serci_semantiko_invalid_shows_semantika_hint(self):
        result = runner.invoke(app, ["encik", "serci", "--semantiko", "ne-konata"])
        assert result.exit_code != 0
        merged = result.output + (result.stderr or "")
        assert "Nevalida --semantiko valoro." in merged
        assert "encik semantika" in merged

    def test_serci_matches_phrase_with_explanatory_parentheses(self, tmp_path):
        _load_db_fixture(
            [
                _make_entry(
                    uuid="93000000-0000-0000-0000-000000000003",
                    titolo="AI (artefarita inteligenteco) modelo",
                    terminologio={"eo": "AI (artefarita inteligenteco) modelo"},
                )
            ],
            tmp_path / "encik.db",
        )
        result = runner.invoke(app, ["encik", "serci", "AI modelo"])
        assert result.exit_code == 0, result.output
        assert "Neniu nodo trovita" not in result.output
        assert "AI (artefarita inteligenteco) modelo" in result.output

    def test_serci_prioritizes_compact_match_over_extra_content(self, tmp_path):
        _load_db_fixture(
            [
                _make_entry(
                    uuid="91000000-0000-0000-0000-000000000001",
                    titolo="dosiero",
                    terminologio={"eo": "dosiero"},
                ),
                _make_entry(
                    uuid="92000000-0000-0000-0000-000000000002",
                    titolo="7z dosiero",
                    terminologio={"eo": "7z dosiero"},
                ),
            ],
            tmp_path / "encik.db",
        )
        result = runner.invoke(app, ["encik", "serci", "dosiero"], input="\n")
        assert result.exit_code == 0, result.output
        assert "dosiero" in result.output
        assert "7z dosiero" in result.output
        assert result.output.find("dosiero") < result.output.find("7z dosiero")

    def test_serci_default_limo_is_20(self, tmp_path):
        entries = []
        for idx in range(25):
            head = f"{idx + 1:08x}"
            entries.append(
                _make_entry(
                    uuid=f"{head}-0000-0000-0000-000000000000",
                    titolo=f"nodo-{idx:02d}",
                    terminologio={"eo": f"nodo-{idx:02d}"},
                )
            )
        _load_db_fixture(entries, tmp_path / "encik.db")
        result = runner.invoke(app, ["encik", "serci", "nodo"], input="\n")
        assert result.exit_code == 0, result.output
        hits = re.findall(r"\b[0-9a-f]{8}\b", result.output)
        assert len(hits) == 20

    def test_semantic_reconcile_repairs_existing_wrong_reverse(self, tmp_path):
        base = tmp_path / "base_repair.enc"
        base.write_text(
            'terminologio.eo = "Baza Klaso"\ndifinio.eo = "Klaso"\n',
            encoding="utf-8",
        )
        r1 = runner.invoke(app, ["encik", "aldoni", str(base)])
        assert r1.exit_code == 0, r1.output
        import autish.commands.encik as enc_mod

        b = enc_mod._find_by_title_exact("Baza Klaso")
        assert b is not None

        inst = tmp_path / "inst_repair.enc"
        inst.write_text(
            'terminologio.eo = "Instanco riparo"\n'
            'difinio.eo = "Instanco"\n'
            f'ligilo = [["{b["uuid"][:8]}", "rdf:type"]]\n',
            encoding="utf-8",
        )
        r2 = runner.invoke(app, ["encik", "aldoni", str(inst)])
        assert r2.exit_code == 0, r2.output
        i = enc_mod._find_by_title_exact("Instanco riparo")
        assert i is not None

        # Simulate previously wrong reverse relation persisted in DB.
        b_now = enc_mod._find_by_title_exact("Baza Klaso")
        assert b_now is not None
        wrong = enc_mod._normalize_ligilo_items(b_now.get("ligilo") or [])
        wrong = [
            x
            for x in wrong
            if not (
                str(x.get("uuid") or "") == i["uuid"]
                and x.get("tipo") == "rdf:hasInstance"
            )
        ]
        wrong.append({"uuid": i["uuid"], "tipo": "rdf:type"})
        b_now["ligilo"] = enc_mod._serialize_ligilo_items(wrong)
        enc_mod._update_entry(b_now)

        # Trigger reconciliation via a no-op modify.
        result = runner.invoke(app, ["encik", "modifi", i["uuid"][:8], "--enhavo", "x"])
        assert result.exit_code == 0, result.output

        b_after = enc_mod._find_by_title_exact("Baza Klaso")
        assert b_after is not None
        assert [i["uuid"], "rdf:hasInstance"] in (b_after.get("ligilo") or [])
        assert [i["uuid"], "rdf:type"] not in (b_after.get("ligilo") or [])

    def test_modifi_overwrite_keeps_managed_reverse_semantic_links(self, tmp_path):
        import autish.commands.encik as enc_mod

        parent = tmp_path / "parent_sem.enc"
        parent.write_text(
            'terminologio.eo = "serĉila agregilo"\ndifinio.eo = "tipo de programaro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_sem.enc"
        child.write_text(
            'terminologio.eo = "Spot"\ndifinio.eo = "serĉila agregilo"\nligilo = []\n',
            encoding="utf-8",
        )
        r1 = runner.invoke(app, ["encik", "aldoni", str(parent)])
        r2 = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert r1.exit_code == 0, r1.output
        assert r2.exit_code == 0, r2.output

        p = enc_mod._find_by_title_exact("serĉila agregilo")
        c = enc_mod._find_by_title_exact("Spot")
        assert p is not None and c is not None

        set_type = runner.invoke(
            app,
            [
                "encik",
                "modifi",
                c["uuid"][:8],
                "--ligilo",
                f"{p['uuid'][:8]}:rdf:type",
            ],
        )
        assert set_type.exit_code == 0, set_type.output

        p_after = enc_mod._find_by_title_exact("serĉila agregilo")
        assert p_after is not None
        assert [c["uuid"], "rdf:hasInstance"] in (p_after.get("ligilo") or [])

        overwrite_parent = tmp_path / "parent_sem_overwrite.enc"
        overwrite_parent.write_text(
            'terminologio.eo = "serĉila agregilo"\n'
            'difinio.eo = "ĝisdatigita difino"\n'
            "ligilo = []\n",
            encoding="utf-8",
        )
        mod_parent = runner.invoke(
            app, ["encik", "modifi", p["uuid"][:8], str(overwrite_parent)]
        )
        assert mod_parent.exit_code == 0, mod_parent.output

        p_final = enc_mod._find_by_title_exact("serĉila agregilo")
        assert p_final is not None
        assert [c["uuid"], "rdf:hasInstance"] in (p_final.get("ligilo") or [])

    def test_managed_reverse_links_removed_when_forward_link_deleted(self, tmp_path):
        import autish.commands.encik as enc_mod

        parent = tmp_path / "parent_del.enc"
        parent.write_text(
            'terminologio.eo = "Kategorio"\ndifinio.eo = "Patro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_del.enc"
        child.write_text(
            'terminologio.eo = "Elemento"\ndifinio.eo = "Filo"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0
        p = enc_mod._find_by_title_exact("Kategorio")
        c = enc_mod._find_by_title_exact("Elemento")
        assert p is not None and c is not None

        set_type = runner.invoke(
            app,
            ["encik", "modifi", c["uuid"][:8], "--ligilo", f"{p['uuid'][:8]}:rdf:type"],
        )
        assert set_type.exit_code == 0, set_type.output
        p_after = enc_mod._find_by_title_exact("Kategorio")
        assert p_after is not None
        assert [c["uuid"], "rdf:hasInstance"] in (p_after.get("ligilo") or [])

        clear = runner.invoke(app, ["encik", "modifi", c["uuid"][:8], "--ligilo", ""])
        assert clear.exit_code == 0, clear.output
        p_final = enc_mod._find_by_title_exact("Kategorio")
        assert p_final is not None
        assert [c["uuid"], "rdf:hasInstance"] not in (p_final.get("ligilo") or [])

    def test_aldoni_unquoted_ligilo_and_vidi_a_shows_it(self, tmp_path):
        base_enc = tmp_path / "x.enc"
        base_enc.write_text(
            'terminologio.eo = "X"\ndifinio.eo = "Difino X"\n',
            encoding="utf-8",
        )
        runner.invoke(app, ["encik", "aldoni", str(base_enc)])
        import autish.commands.encik as enc_mod

        x = enc_mod._find_by_title_exact("X")
        assert x is not None

        y_enc = tmp_path / "y.enc"
        y_enc.write_text(
            f'terminologio.eo = "Y"\ndifinio.eo = "Difino Y"\nligilo={x["uuid"][:8]}\n',
            encoding="utf-8",
        )
        r = runner.invoke(app, ["encik", "aldoni", str(y_enc)])
        assert r.exit_code == 0, r.output
        y = enc_mod._find_by_title_exact("Y")
        assert y is not None
        out = runner.invoke(app, ["encik", "vidi", "-a", y["uuid"][:8]])
        assert out.exit_code == 0, out.output
        assert "ligilo:" in out.output
        assert "X" in out.output

        x_after = enc_mod._find_by_title_exact("X")
        assert x_after is not None
        assert y["uuid"] in (x_after.get("ligilo") or [])

    def test_vidi_default_hides_timestamps(self, tmp_path):
        enc = tmp_path / "t.enc"
        enc.write_text(
            'terminologio.eo = "Tempo"\ndifinio.eo = "Difino"\n',
            encoding="utf-8",
        )
        runner.invoke(app, ["encik", "aldoni", str(enc)])
        import autish.commands.encik as enc_mod

        e = enc_mod._find_by_title_exact("Tempo")
        assert e is not None
        out = runner.invoke(app, ["encik", "vidi", e["uuid"][:8]])
        assert out.exit_code == 0
        assert "kreita_je" not in out.output
        assert "modifita_je" not in out.output

    def test_forigi_supports_hash_uuid(self, tmp_path):
        enc = self._make_enc_file(tmp_path, "ForigHash", "Difino")
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output
        import autish.commands.encik as enc_mod

        e = enc_mod._find_by_title_exact("ForigHash")
        assert e is not None
        out = runner.invoke(app, ["encik", "forigi", f"#{e['uuid'][:8]}", "--force"])
        assert out.exit_code == 0, out.output
        assert "Forigis" in out.output

    def test_forigi_warns_about_broken_references(self, tmp_path):
        parent = self._make_enc_file(tmp_path, "RefParent", "Difino")
        add_parent = runner.invoke(app, ["encik", "aldoni", str(parent)])
        assert add_parent.exit_code == 0, add_parent.output

        import autish.commands.encik as enc_mod

        p = enc_mod._find_by_title_exact("RefParent")
        assert p is not None
        child = tmp_path / "child.enc"
        child.write_text(
            'terminologio.eo = "RefChild"\n'
            'difinio.eo = "Difino"\n'
            f'superklaso = ["{p["uuid"]}"]\n',
            encoding="utf-8",
        )
        add_child = runner.invoke(app, ["encik", "aldoni", str(child)])
        assert add_child.exit_code == 0, add_child.output

        out = runner.invoke(app, ["encik", "forigi", p["uuid"][:8], "--force"])
        assert out.exit_code == 0, out.output
        assert "Averto" in out.output
        assert "rompos referencojn" in out.output
        assert "ligilo" in out.output or "superklaso" in out.output


# ──────────────────────────────────────────────────────────────────────────────
# vorto aldoni --difino help text test
# ──────────────────────────────────────────────────────────────────────────────


class TestVortoAldoniDifinoHelpText:
    """Verify that --difino help text includes the inline example syntax."""

    def test_difino_help_text_mentions_syntax(self):
        result = runner.invoke(app, ["vorto", "aldoni", "--help"])
        assert result.exit_code == 0
        assert "{definition}:*{example}*" in result.output


class TestEncikLs:
    """Test the encik ls command."""

    def test_ls_command_exists(self):
        """Test that encik ls command exists and runs."""
        result = runner.invoke(app, ["encik", "ls", "--help"])
        assert result.exit_code == 0
        assert "List encik entries" in result.output or "ls" in result.output

    def test_ls_pagination_option(self):
        """Test that pagination option is available."""
        result = runner.invoke(app, ["encik", "ls", "--help"])
        assert result.exit_code == 0
        assert "--pagho" in result.output or "-p" in result.output

    def test_ls_inversa_option(self):
        """Test that --inversa option is available."""
        result = runner.invoke(app, ["encik", "ls", "--help"])
        assert result.exit_code == 0
        assert "--inversa" in result.output or "-i" in result.output

    def test_ls_per_pagho_option(self):
        """Test that --per-pagho option is available."""
        result = runner.invoke(app, ["encik", "ls", "--help"])
        assert result.exit_code == 0
        assert "--per-pagho" in result.output
