"""Tests for autish.commands.kalendaro."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def test_kalendaro_command_registered_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "kalendaro" in result.output


def test_kalendaro_add_and_list(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")

    add = runner.invoke(
        app,
        ["kalendaro", "aldoni", "file:///tmp/test.ics", "-u", "alice"],
    )
    assert add.exit_code == 0
    ls = runner.invoke(app, ["kalendaro", "ls-kalendaro"])
    assert ls.exit_code == 0
    assert "file:///tmp/test.ics" in ls.output


def test_kalendaro_import_ls_and_delete(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")

    ics = tmp_path / "ev.ics"
    ics.write_text(
        "\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:abc",
                "SUMMARY:Renkontigxo",
                "DTSTART:20260125T100000Z",
                "DTEND:20260125T110000Z",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        ),
        encoding="utf-8",
    )

    add = runner.invoke(app, ["kalendaro", "aldoni", "file:///tmp/local.ics"])
    assert add.exit_code == 0
    cal_id = add.output.split("#", 1)[1].strip()[:8]
    imp = runner.invoke(app, ["kalendaro", "importi", cal_id, str(ics)])
    assert imp.exit_code == 0
    assert "Importis 1" in imp.output

    ls = runner.invoke(app, ["kalendaro", "ls", "20260125"])
    assert ls.exit_code == 0
    assert "Renkontigxo" in ls.output

    # Grab event id from listing line and delete with confirmation.
    event_id = None
    for token in ls.output.replace("│", " ").split():
        if len(token) == 8 and all(c in "0123456789abcdef" for c in token.lower()):
            event_id = token
            break
    assert event_id
    delete = runner.invoke(app, ["kalendaro", "forigi", event_id], input="j\n")
    assert delete.exit_code == 0
    assert "Forigis 1" in delete.output


def test_kalendaro_date_parsing_short_forms(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")

    add = runner.invoke(app, ["kalendaro", "aldoni", "file:///tmp/local.ics"])
    assert add.exit_code == 0

    # Should accept DD and MMDD forms without crashing.
    a = runner.invoke(app, ["kalendaro", "ls", "12", "18"])
    b = runner.invoke(app, ["kalendaro", "ls", "0518"])
    assert a.exit_code == 0
    assert b.exit_code == 0


def test_kalendaro_aldoni_prevents_duplicate(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    first = runner.invoke(
        app, ["kalendaro", "aldoni", "file:///tmp/local.ics", "-u", "a"]
    )
    second = runner.invoke(
        app, ["kalendaro", "aldoni", "file:///tmp/local.ics", "-u", "a"]
    )
    assert first.exit_code == 0
    assert second.exit_code != 0
    assert "jam ekzistas" in second.output


def test_kalendaro_aldoni_remote_requires_username_password(
    monkeypatch, tmp_path: Path
):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    result = runner.invoke(app, ["kalendaro", "aldoni", "https://example.com/cal.ics"])
    assert result.exit_code != 0
    assert "bezonas --uzantnomo kaj --pasvorto" in result.output


def test_kalendaro_forigi_kalendaro_and_undo(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    add = runner.invoke(app, ["kalendaro", "aldoni", "file:///tmp/local.ics"])
    assert add.exit_code == 0
    cal_id = add.output.split("#", 1)[1].strip()[:8]
    delete = runner.invoke(app, ["kalendaro", "forigi-kalendaro", cal_id])
    assert delete.exit_code == 0
    ls = runner.invoke(app, ["kalendaro", "ls-kalendaro"])
    assert cal_id not in ls.output
    undo_ls = runner.invoke(app, ["kalendaro", "malfari", "ls"])
    assert undo_ls.exit_code == 0
    change_id = undo_ls.output.split()[0]
    undo = runner.invoke(app, ["kalendaro", "malfari", change_id])
    assert undo.exit_code == 0
    ls2 = runner.invoke(app, ["kalendaro", "ls-kalendaro"])
    assert cal_id in ls2.output


def test_kalendaro_forigi_kalendaro_without_uuid_deletes_all_with_confirmation(
    monkeypatch, tmp_path: Path
):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    assert (
        runner.invoke(app, ["kalendaro", "aldoni", "file:///tmp/a.ics"]).exit_code == 0
    )
    assert (
        runner.invoke(app, ["kalendaro", "aldoni", "file:///tmp/b.ics"]).exit_code == 0
    )
    delete_all = runner.invoke(app, ["kalendaro", "forigi-kalendaro"], input="j\n")
    assert delete_all.exit_code == 0, delete_all.output
    assert "Forigis 2 kalendaro(j)n" in delete_all.output
    ls = runner.invoke(app, ["kalendaro", "ls-kalendaro"])
    assert "file:///tmp/a.ics" not in ls.output
    assert "file:///tmp/b.ics" not in ls.output


def test_kalendaro_modifi_updates_credentials(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    secrets: dict[str, str] = {}

    monkeypatch.setattr(
        kal, "_set_password", lambda uid, pw: secrets.__setitem__(uid, pw)
    )
    monkeypatch.setattr(kal, "_get_password", lambda uid: secrets.get(uid, ""))
    monkeypatch.setattr(kal, "_start_sync_worker", lambda: None)

    add = runner.invoke(
        app, ["kalendaro", "aldoni", "file:///tmp/base.ics", "-u", "alice"]
    )
    assert add.exit_code == 0, add.output
    cal_id = add.output.split("#", 1)[1].strip()[:8]

    mod = runner.invoke(
        app,
        [
            "kalendaro",
            "modifi",
            cal_id,
            "--url",
            "file:///tmp/nova.ics",
            "--uzantnomo",
            "bob",
            "--pasvorto",
            "sekreta",
        ],
    )
    assert mod.exit_code == 0, mod.output
    con = kal._connect()
    try:
        row = con.execute(
            "SELECT uuid, url, username FROM calendars WHERE uuid LIKE ?",
            (cal_id + "%",),
        ).fetchone()
        assert row is not None
        assert str(row["url"]) == "file:///tmp/nova.ics"
        assert str(row["username"]) == "bob"
        assert secrets[str(row["uuid"])] == "sekreta"
    finally:
        con.close()


def test_kalendaro_sinkronigi_fetches_remote_events(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    monkeypatch.setattr(kal, "_start_sync_worker", lambda: None)
    secrets: dict[str, str] = {}
    monkeypatch.setattr(
        kal, "_set_password", lambda uid, pw: secrets.__setitem__(uid, pw)
    )
    monkeypatch.setattr(kal, "_get_password", lambda uid: secrets.get(uid, ""))

    calls = {"n": 0}

    def _fake_fetch(_url: str, _username: str, _password: str) -> list[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                "\n".join(
                    [
                        "BEGIN:VCALENDAR",
                        "VERSION:2.0",
                        "BEGIN:VEVENT",
                        "UID:one",
                        "SUMMARY:Unua Evento",
                        "DTSTART:20260412T100000Z",
                        "DTEND:20260412T110000Z",
                        "END:VEVENT",
                        "END:VCALENDAR",
                    ]
                )
            ]
        return [
            "\n".join(
                [
                    "BEGIN:VCALENDAR",
                    "VERSION:2.0",
                    "BEGIN:VEVENT",
                    "UID:two",
                    "SUMMARY:Dua Evento",
                    "DTSTART:20260412T120000Z",
                    "DTEND:20260412T130000Z",
                    "END:VEVENT",
                    "END:VCALENDAR",
                ]
            )
        ]

    monkeypatch.setattr(kal, "_fetch_remote_calendar_payloads", _fake_fetch)

    add = runner.invoke(
        app,
        [
            "kalendaro",
            "aldoni",
            "https://example.com/remote.php/dav/calendars/u/main/",
            "-u",
            "u",
            "-p",
            "sekreta",
        ],
    )
    assert add.exit_code == 0, add.output
    sync = runner.invoke(app, ["kalendaro", "sinkronigi"])
    assert sync.exit_code == 0, sync.output
    kal._sync_worker()
    ls = runner.invoke(app, ["kalendaro", "ls", "20260412"])
    assert ls.exit_code == 0, ls.output
    assert "Unua Evento" in ls.output
    assert "Dua Evento" in ls.output


def test_kalendaro_sinkronigi_handles_empty_queue(monkeypatch, tmp_path: Path):
    import autish.commands.kalendaro as kal

    monkeypatch.setattr(kal, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(kal, "_DB_FILE", tmp_path / "kalendaro.db")
    result = runner.invoke(app, ["kalendaro", "sinkronigi"])
    assert result.exit_code == 0
    assert "Nenio por sinkronigi" in result.output


def test_kalendaro_help_mentions_examples_and_values(monkeypatch):
    monkeypatch.setenv("LANG", "eo_FR.UTF-8")
    result = runner.invoke(app, ["kalendaro", "aldoni", "-h"])
    assert result.exit_code == 0
    assert "Ekz:" in result.output
    assert "--uzantnomo" in result.output
    assert "--pasvorto" in result.output


def test_kalendaro_ls_kalendaro_renders_clickable_full_link():
    import autish.commands.kalendaro as kal

    long_url = "https://example.com/" + ("x" * 80)
    rendered = kal._render_calendar_url(long_url)
    assert "[link=https://example.com/" in rendered
    assert "Ctrl+klako/kopio daŭre celas la plenan URL" in rendered
