"""Tests for etikedo/todo/taglibro commands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def _seed_link_targets(encik_db: Path, vorto_db: Path) -> None:
    encik_db.parent.mkdir(parents=True, exist_ok=True)
    con_encik = sqlite3.connect(encik_db)
    con_encik.execute(
        """
        CREATE TABLE IF NOT EXISTS encik (
            uuid TEXT PRIMARY KEY,
            titolo TEXT NOT NULL,
            difinio TEXT NOT NULL DEFAULT ''
        )
        """
    )
    con_encik.execute(
        "INSERT OR REPLACE INTO encik (uuid, titolo, difinio) VALUES (?, ?, ?)",
        (
            "4feb123f-1111-2222-3333-444444444444",
            "Filozofio",
            "Difino",
        ),
    )
    con_encik.commit()
    con_encik.close()

    con_vorto = sqlite3.connect(vorto_db)
    con_vorto.execute(
        """
        CREATE TABLE IF NOT EXISTS vorto (
            uuid TEXT PRIMARY KEY,
            teksto TEXT NOT NULL
        )
        """
    )
    con_vorto.execute(
        "INSERT OR REPLACE INTO vorto (uuid, teksto) VALUES (?, ?)",
        (
            "8bf534dc-1111-2222-3333-444444444444",
            "s'ingérer",
        ),
    )
    con_vorto.commit()
    con_vorto.close()


def test_new_commands_registered_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "etikedo" in result.output
    assert "todo" in result.output
    assert "taglibro" in result.output


def test_etikedo_add_search_view_modify_delete(monkeypatch, tmp_path: Path):
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")
    _seed_link_targets(tmp_path / "encik.db", tmp_path / "vorto.db")

    add = runner.invoke(
        app,
        [
            "etikedo",
            "aldoni",
            "[Temo](ec#4feb123f) kaj [Vorto](vt#8bf534dc)",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Aldonis etikedo" in add.output

    search = runner.invoke(app, ["etikedo", "serci", "temo"])
    assert search.exit_code == 0
    assert "Temo (ec#4feb123f)" in search.output
    assert "Vorto (vt#8bf534dc)" in search.output

    view = runner.invoke(app, ["etikedo", "vidi", "temo"], input="1\n")
    assert view.exit_code == 0
    assert "uuid:" in view.output
    assert "teksto:" in view.output

    modify = runner.invoke(
        app,
        ["etikedo", "modifi", "temo", "[Nova](ec#4feb123f)"],
        input="1\n",
    )
    assert modify.exit_code == 0, modify.output
    assert "Modifis #" in modify.output

    remove = runner.invoke(app, ["etikedo", "forigi", "nova"], input="j\n")
    assert remove.exit_code == 0
    assert "Forigis etikedon" in remove.output


def test_todo_add_search_modify_view_delete(monkeypatch, tmp_path: Path):
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")
    _seed_link_targets(tmp_path / "encik.db", tmp_path / "vorto.db")

    label = runner.invoke(app, ["etikedo", "aldoni", "urgxa"])
    assert label.exit_code == 0

    add = runner.invoke(
        app,
        [
            "todo",
            "aldoni",
            "Plani [koncepton](ec#4feb123f)",
            "-p",
            "Vidi [ligitan vorton](vt#8bf534dc)",
            "-e",
            "urgxa",
            "-P",
            "min(20+2*D,70)",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Aldonis todo" in add.output

    search = runner.invoke(app, ["todo", "serci", "plani", "-P", "0,100"])
    assert search.exit_code == 0
    assert "Plani koncepton" in search.output
    assert "urgxa" in search.output

    view = runner.invoke(app, ["todo", "vidi", "plani"])
    assert view.exit_code == 0
    assert "titolo:" in view.output
    assert "priskribo:" in view.output

    modify = runner.invoke(
        app,
        ["todo", "modifi", "plani", "--stato", "farita", "--prioritato", "42"],
    )
    assert modify.exit_code == 0, modify.output
    assert "Modifis todo" in modify.output
    assert "stato: farita" in modify.output

    delete = runner.invoke(app, ["todo", "forigi", "plani"], input="j\n")
    assert delete.exit_code == 0
    assert "Forigis todo" in delete.output


def test_taglibro_add_search_modify_view_delete(monkeypatch, tmp_path: Path):
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")
    _seed_link_targets(tmp_path / "encik.db", tmp_path / "vorto.db")

    label = runner.invoke(app, ["etikedo", "aldoni", "persona"])
    assert label.exit_code == 0

    add = runner.invoke(
        app,
        [
            "taglibro",
            "aldoni",
            "Hodiaŭ [ideo](ec#4feb123f)",
            "-p",
            "Rimarko kun [vorto](vt#8bf534dc)",
            "-e",
            "persona",
            "-t",
            "20260421_0915",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Aldonis taglibran eniron" in add.output

    search = runner.invoke(app, ["taglibro", "serci", "hodiau"])
    assert search.exit_code == 0
    assert "Hodiaŭ ideo" in search.output
    assert "persona" in search.output

    view = runner.invoke(app, ["taglibro", "vidi", "hodiaŭ"])
    assert view.exit_code == 0
    assert "titolo:" in view.output
    assert "priskribo:" in view.output

    modify = runner.invoke(
        app,
        [
            "taglibro",
            "modifi",
            "hodiaŭ",
            "--titolo",
            "Nova titolo",
            "--tempo",
            "0422_1010",
        ],
    )
    assert modify.exit_code == 0, modify.output
    assert "Modifis taglibro-eniron" in modify.output
    assert "Nova titolo" in modify.output

    delete = runner.invoke(app, ["taglibro", "forigi", "nova titolo"], input="j\n")
    assert delete.exit_code == 0
    assert "Forigis taglibro-eniron" in delete.output


def test_todo_etikedo_validation_with_creation(monkeypatch, tmp_path: Path):
    """Test that todo aldoni --etikedo prompts to create missing etikedo."""
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")

    add_existing_label = runner.invoke(app, ["etikedo", "aldoni", "urgxa"])
    assert add_existing_label.exit_code == 0

    add_with_new_label = runner.invoke(
        app,
        ["todo", "aldoni", "Testo", "-e", "nova_etikedo"],
        input="j\n",
    )
    assert add_with_new_label.exit_code == 0, add_with_new_label.output
    assert "Aldonis etikedon" in add_with_new_label.output
    assert "Aldonis todo" in add_with_new_label.output

    add_reject_create = runner.invoke(
        app,
        ["todo", "aldoni", "Testo 2", "-e", "neakceptita"],
        input="N\n",
    )
    assert add_reject_create.exit_code == 1
    assert "Etikedo ne trovita" in add_reject_create.output


def test_todo_modifi_etikedo_with_creation(monkeypatch, tmp_path: Path):
    """Test that todo modifi --etikedo prompts to create missing etikedo."""
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")

    runner.invoke(app, ["etikedo", "aldoni", "existing"])
    add = runner.invoke(app, ["todo", "aldoni", "Testo", "-e", "existing"])
    assert add.exit_code == 0

    modifi_new = runner.invoke(
        app,
        ["todo", "modifi", "testo", "-e", "nova"],
        input="j\n",
    )
    assert modifi_new.exit_code == 0, modifi_new.output
    assert "Aldonis etikedon" in modifi_new.output
    assert "Modifis todo" in modifi_new.output

    view = runner.invoke(app, ["todo", "vidi", "testo"])
    assert view.exit_code == 0
    assert "nova" in view.output


def test_todo_semantic_link_auto_creates_etikedo(monkeypatch, tmp_path: Path):
    """Test that todo aldoni automatically creates etikedoj for semantic links."""
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")
    _seed_link_targets(tmp_path / "encik.db", tmp_path / "vorto.db")

    add = runner.invoke(
        app,
        [
            "todo",
            "aldoni",
            "Testo kun [Filosofio](ec#4feb123f)",
            "-p",
            "Priskribo kun [verbo](vt#8bf534dc)",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Aldonis todo" in add.output

    search_labels = runner.invoke(app, ["etikedo", "serci"])
    assert search_labels.exit_code == 0
    has_filosofio = (
        "Filosofio (ec#4feb123f)" in search_labels.output
        or "Filosofio" in search_labels.output
    )
    has_verbo = (
        "verbo (vt#8bf534dc)" in search_labels.output
        or "verbo" in search_labels.output
    )
    assert has_filosofio
    assert has_verbo


def test_todo_semantic_link_no_duplicate_etikedoj(monkeypatch, tmp_path: Path):
    """Test that same semantic link isn't duplicated across multiple todos."""
    import autish.commands._tasklib as tasklib

    monkeypatch.setattr(tasklib, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(tasklib, "_DB_FILE", tmp_path / "tasklibro.db")
    monkeypatch.setattr(tasklib, "_ENCIK_DB_FILE", tmp_path / "encik.db")
    monkeypatch.setattr(tasklib, "_VORTO_DB_FILE", tmp_path / "vorto.db")
    _seed_link_targets(tmp_path / "encik.db", tmp_path / "vorto.db")

    add1 = runner.invoke(
        app,
        ["todo", "aldoni", "Testo 1 kun [Filozofio](ec#4feb123f)"],
    )
    assert add1.exit_code == 0

    add2 = runner.invoke(
        app,
        ["todo", "aldoni", "Testo 2 kun [Filozofio](ec#4feb123f)"],
    )
    assert add2.exit_code == 0

    search_labels = runner.invoke(app, ["etikedo", "serci", "filozofio"])
    assert search_labels.exit_code == 0
    lines = search_labels.output.strip().split("\n")
    result_count = int(lines[0].split()[0])
    assert result_count == 1, f"Expected 1 etikedo, got {result_count}"
