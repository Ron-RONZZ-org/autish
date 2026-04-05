"""Tests for autish.commands.encik (Encik knowledge-graph microapp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.encik import (
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
            kreita_je TEXT NOT NULL,
            modifita_je TEXT NOT NULL
        )"""
    )
    for e in entries:
        conn.execute(
            """INSERT OR REPLACE INTO encik
               (uuid, titolo, difinio, terminologio, difinoj, enhavo,
                superklaso, ligilo, fonto, citajo, datumo, kreita_je, modifita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                e["kreita_je"],
                e["modifita_je"],
            ),
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
            'terminologio.eo = "Temo"\n'
            "difinio.eo =   \n"
            '   """\n'
            "estas difinio\n"
            '"""\n',
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
            "{titolo = \"Great Book\", autoro = \"A. Author\", "
            "jaro = 2020, tipo = \"lib\", lingvo = \"fr\"}"
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
            '{\n'
            '  "metriko": {"en": "Unemployment rate", "fr": "Taux de chômage"},\n'
            '  "meta": {"country": {"en": "France", "eo": "Francio"}},\n'
            '  "datumo": [["jaro", "valoro"], [2010, 9.3], [2011, 9.2]],\n'
            '  "etikedo": {"jaro": {"eo": "jaro"}, "valoro": {"eo": "valoro"}}\n'
            '}\n'
            '"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["citajo"][0]["autoro"] == "Aŭtoro"
        assert "senlaboreco" in parsed["datumo"]
        assert parsed["datumo"]["senlaboreco"]["datumo"][1][1] == 9.3

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

    def test_aldoni_auto_adds_ligilo_from_markdown_uuid_refs(self, tmp_path):
        import uuid as _uuid_mod

        suffix = _uuid_mod.uuid4().hex[:8]
        target_title = f"Celo-{suffix}"
        target = tmp_path / "target.enc"
        target.write_text(
            f'terminologio.eo = "{target_title}"\n'
            'difino.eo = "Difino de celo."\n',
            encoding="utf-8",
        )
        add_target = runner.invoke(app, ["encik", "aldoni", str(target)])
        assert add_target.exit_code == 0, add_target.output

        import autish.commands.encik as enc_mod

        target_entry = enc_mod._find_by_title_exact(target_title)
        assert target_entry is not None
        source_title = f'Fonto-{suffix} [Celo](#{target_entry["uuid"][:8]})'
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


class TestUuidRefExtraction:
    def test_extract_markdown_ligilo_refs_resolves_existing_full_uuid(
        self, tmp_path, monkeypatch
    ):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
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
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
        _load_db_fixture([_make_entry(uuid=SAMPLE_UUID, titolo="A")], db_path)
        refs = _extract_markdown_ligilo_refs(
            f"[A](#{SAMPLE_UUID[:8]},rdfs:subClassOf)"
        )
        assert refs[0]["uuid"] == SAMPLE_UUID
        assert refs[0]["tipo"] == "rdfs:subClassOf"

    def test_linked_graph_collects_super_sub_and_ligilo(self, tmp_path, monkeypatch):
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
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
        import autish.commands.encik as enc_mod

        db_path = tmp_path / "encik.db"
        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)
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
        db_path = tmp_path / "encik.db"
        import autish.commands.encik as enc_mod

        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)

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
        db_path = tmp_path / "encik.db"
        import autish.commands.encik as enc_mod

        monkeypatch.setattr(enc_mod, "_DB_FILE", db_path)
        monkeypatch.setattr(enc_mod, "_DATA_DIR", tmp_path)

    def _make_enc_file(self, tmp_path: Path, titolo: str, difinio: str = "") -> Path:
        p = tmp_path / f"{titolo.replace(' ', '_')}.enc"
        difinio_json = json.dumps(difinio)
        p.write_text(
            f'terminologio.eo = {json.dumps(titolo)}\n'
            f"difinio.eo = {difinio_json}\n",
            encoding="utf-8",
        )
        return p

    def test_welcome_screen(self):
        result = runner.invoke(app, ["encik"])
        assert result.exit_code == 0
        assert "Encik" in result.output

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

        result = runner.invoke(app, ["encik", "serci", "-p", "Dog"])
        assert result.exit_code == 0, result.output
        assert "Paralela (Dog)" in result.output
        assert "Cat" in result.output

    def test_serci_paralela_without_root_errors(self):
        result = runner.invoke(app, ["encik", "serci", "-p"])
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

    def test_serci_subklasoj_accepts_hash_uuid_reference(self, tmp_path):
        parent = tmp_path / "physics.enc"
        parent.write_text(
            'terminologio.eo = "Physics"\n'
            'difinio.eo = "Root node."\n',
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
            f'terminologio.eo = "{root_title}"\n'
            'difinio.eo = "R"\n',
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

        monkeypatch.setattr("autish.commands.encik.webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "serci", "--ligilo", root_title])
        assert result.exit_code == 0, result.output
        assert "Malfermas rilatan mapon" in result.output
        path = Path(opened["url"][7:])
        html = path.read_text(encoding="utf-8")
        assert "vis.Network" in html
        assert root_title in html

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
            'terminologio.eo = "ReplaceMe"\n'
            'difinio.eo = "From file."\n',
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
        result = runner.invoke(app, ["encik", "vidi", "Dog", "-L", "en", "-a"])
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
            'terminologio.eo = "Hundo"\n'
            'difinio.eo = "**Besto**"\n',
            encoding="utf-8",
        )
        add = runner.invoke(app, ["encik", "aldoni", str(enc)])
        assert add.exit_code == 0, add.output

        opened: dict[str, str] = {}

        def _fake_open(url: str) -> bool:
            opened["url"] = url
            return True

        monkeypatch.setattr("autish.commands.encik.webbrowser.open", _fake_open)
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
            'terminologio.eo = "Celo"\n'
            'difinio.eo = "Cela difino"\n',
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

        monkeypatch.setattr("autish.commands.encik.webbrowser.open", _fake_open)
        result = runner.invoke(app, ["encik", "vidi", "Fonto", "--html"])
        assert result.exit_code == 0, result.output
        html_path = Path(opened["url"][7:])
        html_content = html_path.read_text(encoding="utf-8")
        assert "Vidu" in html_content
        assert "file://" in html_content

    def test_encik_vidi_cli_renders_internal_markdown_link(
        self, tmp_path, monkeypatch
    ):
        parent = tmp_path / "target_cli.enc"
        parent.write_text(
            'terminologio.eo = "Hugging Face"\n'
            'difinio.eo = "Celo"\n',
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
            'terminologio.eo = "Semantika Nodo"\n'
            'difinio.eo = "Celo"\n',
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
            'terminologio.eo = "Nodo"\n'
            'difinio.eo = "Celo"\n',
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

    def test_relation_html_link_does_not_duplicate_hash_fallback_label(
        self, tmp_path
    ):
        orphan_ref = "86c80457"
        html = _render_relation_html_link(f"#{orphan_ref}", orphan_ref)
        assert html == f"#{orphan_ref}"

    def test_relation_html_link_normalizes_double_hash_label(self):
        html = _render_relation_html_link("##c8ec772", "c8ec7722")
        assert "##c8ec772" not in html

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
                f'terminologio.eo = "{title}"\n'
                'difinio.eo = "Difino"\n',
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
            'terminologio.eo = "Cela Titolo"\n'
            'difinio.eo = "Celo"\n',
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

        monkeypatch.setattr("autish.commands.encik.webbrowser.open", _fake_open)
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

        monkeypatch.setattr("autish.commands.encik.webbrowser.open", _fake_open)
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
        assert "# tiu ĉi estas komento" in result.output
        assert "Validaj fonto.tipo" in result.output
        assert "Semantikaj ligiloj" in result.output

    def test_aldoni_bidirectional_ligilo(self, tmp_path):
        base_enc = tmp_path / "a.enc"
        base_enc.write_text(
            'terminologio.eo = "A"\n'
            'difinio.eo = "Difino A"\n',
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
            'terminologio.eo = "Klaso"\n'
            'difinio.eo = "A klaso"\n',
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
            'terminologio.eo = "Patra"\n'
            'difinio.eo = "Patro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_editor.enc"
        child.write_text(
            'terminologio.eo = "Filo"\n'
            'difinio.eo = "Filo"\n',
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
                    f'{p["uuid"][:8]}:rdf:type',
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
            'terminologio.eo = "A"\n'
            'difinio.eo = "A difino"\n',
            encoding="utf-8",
        )
        other = tmp_path / "b.enc"
        other.write_text(
            'terminologio.eo = "B"\n'
            'difinio.eo = "B difino"\n',
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
            ["encik", "modifi", a["uuid"][:8], "--ligilo", f'{b["uuid"][:8]}:rdf:type'],
        )
        assert set_ab.exit_code == 0, set_ab.output

        conflict = runner.invoke(
            app,
            ["encik", "modifi", b["uuid"][:8], "--ligilo", f'{a["uuid"][:8]}:rdf:type'],
        )
        assert conflict.exit_code != 0
        assert "Semantika logika konflikto" in (
            conflict.output + (conflict.stderr or "")
        )
        assert "Sugesto" in (conflict.output + (conflict.stderr or ""))

    def test_semantic_reconcile_repairs_existing_wrong_reverse(self, tmp_path):
        base = tmp_path / "base_repair.enc"
        base.write_text(
            'terminologio.eo = "Baza Klaso"\n'
            'difinio.eo = "Klaso"\n',
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
            'terminologio.eo = "serĉila agregilo"\n'
            'difinio.eo = "tipo de programaro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_sem.enc"
        child.write_text(
            'terminologio.eo = "Spot"\n'
            'difinio.eo = "serĉila agregilo"\n'
            'ligilo = []\n',
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
                f'{p["uuid"][:8]}:rdf:type',
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
            'ligilo = []\n',
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
            'terminologio.eo = "Kategorio"\n'
            'difinio.eo = "Patro"\n',
            encoding="utf-8",
        )
        child = tmp_path / "child_del.enc"
        child.write_text(
            'terminologio.eo = "Elemento"\n'
            'difinio.eo = "Filo"\n',
            encoding="utf-8",
        )
        assert runner.invoke(app, ["encik", "aldoni", str(parent)]).exit_code == 0
        assert runner.invoke(app, ["encik", "aldoni", str(child)]).exit_code == 0
        p = enc_mod._find_by_title_exact("Kategorio")
        c = enc_mod._find_by_title_exact("Elemento")
        assert p is not None and c is not None

        set_type = runner.invoke(
            app,
            ["encik", "modifi", c["uuid"][:8], "--ligilo", f'{p["uuid"][:8]}:rdf:type'],
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
            'terminologio.eo = "X"\n'
            'difinio.eo = "Difino X"\n',
            encoding="utf-8",
        )
        runner.invoke(app, ["encik", "aldoni", str(base_enc)])
        import autish.commands.encik as enc_mod
        x = enc_mod._find_by_title_exact("X")
        assert x is not None

        y_enc = tmp_path / "y.enc"
        y_enc.write_text(
            'terminologio.eo = "Y"\n'
            'difinio.eo = "Difino Y"\n'
            f'ligilo={x["uuid"][:8]}\n',
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
            'terminologio.eo = "Tempo"\n'
            'difinio.eo = "Difino"\n',
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
        out = runner.invoke(
            app, ["encik", "forigi", f"#{e['uuid'][:8]}", "--force"]
        )
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
        assert "superklaso" in out.output


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
