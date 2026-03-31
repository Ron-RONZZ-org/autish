"""Tests for autish.commands.encik (Encik knowledge-graph microapp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.encik import (
    _entry_to_enc,
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
            kreita_je TEXT NOT NULL,
            modifita_je TEXT NOT NULL
        )"""
    )
    for e in entries:
        conn.execute(
            """INSERT OR REPLACE INTO encik
               (uuid, titolo, difinio, terminologio, difinoj, enhavo,
                superklaso, ligilo, fonto, kreita_je, modifita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
        assert "## Titolo\n\n- ero unu" in parsed["difinoj"]["eo"]

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
                "11111111-2222-3333-4444-555555555555",
            ],
        )
        assert result.exit_code == 0, result.output

        import autish.commands.encik as enc_mod

        updated = enc_mod._find_by_title_exact("CliEdit")
        assert updated is not None
        assert updated["terminologio"]["fr"] == "Bonjour"
        assert updated["difinoj"]["fr"] == "Salut."
        assert "11111111-2222-3333-4444-555555555555" in (updated.get("ligilo") or [])

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

    def test_aldoni_help_mentions_new_enc_syntax(self):
        result = runner.invoke(app, ["encik", "aldoni", "-h"])
        assert result.exit_code == 0
        assert "terminologio.xx" in result.output
        assert "fonto" in result.output
        assert "superklaso" in result.output
        assert "ligilo" in result.output

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
