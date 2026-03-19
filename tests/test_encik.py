"""Tests for autish.commands.encik (Encik knowledge-graph microapp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.encik import (
    _entry_to_enc,
    _normalise_pairs,
    _paralela_of,
    _parse_enc_file,
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
        "definio": "A test definition.",
        "superklaso": [],
        "ligilo": [],
        "source": [],
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
            definio TEXT NOT NULL DEFAULT '',
            superklaso TEXT NOT NULL DEFAULT '[]',
            ligilo TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '[]',
            kreita_je TEXT NOT NULL,
            modifita_je TEXT NOT NULL
        )"""
    )
    for e in entries:
        conn.execute(
            "INSERT OR REPLACE INTO encik VALUES (?,?,?,?,?,?,?,?)",
            (
                e["uuid"],
                e["titolo"],
                e.get("definio", ""),
                json.dumps(e.get("superklaso", [])),
                json.dumps(e.get("ligilo", [])),
                json.dumps(e.get("source", [])),
                e["kreita_je"],
                e["modifita_je"],
            ),
        )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — pure helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestNormalisePairs:
    def test_list_of_2_element_lists(self):
        raw = [["Cat", "uuid-cat"], ["Dog", "uuid-dog"]]
        assert _normalise_pairs(raw) == [["Cat", "uuid-cat"], ["Dog", "uuid-dog"]]

    def test_list_of_dicts(self):
        raw = [{"titolo": "Cat", "uuid": "uuid-cat"}]
        assert _normalise_pairs(raw) == [["Cat", "uuid-cat"]]

    def test_empty(self):
        assert _normalise_pairs([]) == []

    def test_partial_list_ignored(self):
        # Single-element lists are ignored (not valid pairs)
        assert _normalise_pairs([["OnlyTitle"]]) == []


class TestParseEncFile:
    def test_basic_parsing(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# My Concept\n\ndefinio = "A nice definition."\n\n'
            "superklaso = []\nligilo = []\nsource = []\n",
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["titolo"] == "My Concept"
        assert parsed["definio"] == "A nice definition."
        assert parsed["superklaso"] == []
        assert parsed["ligilo"] == []
        assert parsed["source"] == []

    def test_multiline_definio(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Topic\n\ndefinio = """\nLine one.\nLine two.\n"""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert "Line one." in parsed["definio"]
        assert "Line two." in parsed["definio"]

    def test_superklaso_pairs(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Child\n\ndefinio = ""\nsuperklaso = [["Parent","uuid-parent"]]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["superklaso"] == [["Parent", "uuid-parent"]]

    def test_source_list(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Book\n\ndefinio = ""\n'
            'source = [{title = "Great Book", author = "A. Author", year = "2020"}]\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert len(parsed["source"]) == 1
        assert parsed["source"][0]["title"] == "Great Book"
        assert parsed["source"][0]["author"] == "A. Author"

    def test_missing_title_raises(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text('definio = "No title here."\n', encoding="utf-8")
        with pytest.raises(ValueError, match="No title"):
            _parse_enc_file(enc)

    def test_malformed_toml_raises(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text("# Title\ndefinio = [broken toml\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Malformed"):
            _parse_enc_file(enc)

    def test_toml_titolo_overrides_comment(self, tmp_path):
        enc = tmp_path / "test.enc"
        enc.write_text(
            '# Comment Title\ntitolo = "TOML Title"\ndefinio = ""\n',
            encoding="utf-8",
        )
        parsed = _parse_enc_file(enc)
        assert parsed["titolo"] == "TOML Title"


class TestEntryToEnc:
    def test_round_trip(self, tmp_path):
        entry = _make_entry(
            titolo="Round Trip",
            definio="Some definition.",
            superklaso=[["Parent", "parent-uuid"]],
        )
        enc_text = _entry_to_enc(entry)
        enc_file = tmp_path / "rt.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["titolo"] == "Round Trip"
        assert "Some definition." in parsed["definio"]
        assert parsed["superklaso"] == [["Parent", "parent-uuid"]]

    def test_empty_fields(self, tmp_path):
        entry = _make_entry(titolo="Empty", definio="")
        enc_text = _entry_to_enc(entry)
        enc_file = tmp_path / "empty.enc"
        enc_file.write_text(enc_text, encoding="utf-8")
        parsed = _parse_enc_file(enc_file)
        assert parsed["titolo"] == "Empty"
        assert parsed["superklaso"] == []


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
            superklaso=[[animal["titolo"], SAMPLE_UUID]],
        )
        dog = _make_entry(
            uuid=GRANDCHILD_UUID,
            titolo="Dog",
            superklaso=[[mammal["titolo"], CHILD_UUID]],
        )
        cat = _make_entry(
            uuid=SIBLING_UUID,
            titolo="Cat",
            superklaso=[[mammal["titolo"], CHILD_UUID]],
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

    def _make_enc_file(self, tmp_path: Path, titolo: str, definio: str = "") -> Path:
        p = tmp_path / f"{titolo.replace(' ', '_')}.enc"
        definio_json = json.dumps(definio)
        p.write_text(
            f"# {titolo}\n\ndefinio = {definio_json}\n", encoding="utf-8"
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
        result = runner.invoke(app, ["encik", "serci", "-t", "Philo"])
        assert result.exit_code == 0
        assert "Philos" in result.output

    def test_serci_titolo_not_found(self, tmp_path):
        result = runner.invoke(app, ["encik", "serci", "-t", "NonExistentXYZ"])
        assert result.exit_code == 0
        assert "trovita" in result.output.lower()

    def test_serci_no_flags_shows_help(self):
        result = runner.invoke(app, ["encik", "serci"])
        assert result.exit_code == 0
        # Help text should contain the command name
        assert "serci" in result.output.lower() or "Usage" in result.output

    def test_serci_subklasoj(self, tmp_path):
        # Animal -> Mammal
        parent_enc = tmp_path / "animal.enc"
        parent_enc.write_text("# Animal\ndefinio = \"\"\n", encoding="utf-8")
        r1 = runner.invoke(app, ["encik", "aldoni", str(parent_enc)])
        assert r1.exit_code == 0, r1.output

        # Get the UUID of Animal
        import autish.commands.encik as enc_mod

        animal = enc_mod._find_by_title_exact("Animal")
        assert animal is not None

        child_enc = tmp_path / "mammal.enc"
        child_enc.write_text(
            f'# Mammal\ndefinio = ""\nsuperklaso = [["Animal", "{animal["uuid"]}"]]\n',
            encoding="utf-8",
        )
        r2 = runner.invoke(app, ["encik", "aldoni", str(child_enc)])
        assert r2.exit_code == 0, r2.output

        result = runner.invoke(app, ["encik", "serci", "-s", "Animal"])
        assert result.exit_code == 0, result.output
        assert "Mammal" in result.output

    def test_serci_superklasoj(self, tmp_path):
        parent_enc = tmp_path / "a.enc"
        parent_enc.write_text("# Science\ndefinio = \"\"\n", encoding="utf-8")
        runner.invoke(app, ["encik", "aldoni", str(parent_enc)])

        import autish.commands.encik as enc_mod

        science = enc_mod._find_by_title_exact("Science")
        assert science is not None

        child_enc = tmp_path / "b.enc"
        science_uuid = science["uuid"]
        child_enc.write_text(
            f'# Physics\ndefinio = ""\n'
            f'superklaso = [["Science", "{science_uuid}"]]\n',
            encoding="utf-8",
        )
        runner.invoke(app, ["encik", "aldoni", str(child_enc)])

        result = runner.invoke(app, ["encik", "serci", "-S", "Physics"])
        assert result.exit_code == 0, result.output
        assert "Science" in result.output

    def test_modifi_not_found(self):
        result = runner.invoke(app, ["encik", "modifi", "does-not-exist"])
        assert result.exit_code != 0

    def test_modifi_invokes_editor(self, tmp_path, monkeypatch):
        """modifi should open $EDITOR on the temp .enc file and save changes."""
        # First add an entry
        enc = self._make_enc_file(tmp_path, "EditMe", "Original.")
        runner.invoke(app, ["encik", "aldoni", str(enc)])

        # Mock subprocess.run to write a modified .enc file
        def _fake_run(cmd, **kwargs):
            # cmd[1] is the temp file path
            Path(cmd[1]).write_text(
                '# EditMe\ndefinio = "Updated."\n', encoding="utf-8"
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
        assert updated["definio"] == "Updated."


# ──────────────────────────────────────────────────────────────────────────────
# vorto aldoni --difino help text test
# ──────────────────────────────────────────────────────────────────────────────


class TestVortoAldoniDifinoHelpText:
    """Verify that --difino help text includes the inline example syntax."""

    def test_difino_help_text_mentions_syntax(self):
        result = runner.invoke(app, ["vorto", "aldoni", "--help"])
        assert result.exit_code == 0
        assert "{definition}:*{example}*" in result.output
