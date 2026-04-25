"""Tests for bash alias management (sistemo bash alias commands)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.sistemo import app
from autish.services.bash_alias import BashAliasDB

runner = CliRunner()


class TestBashAliasDB:
    """Tests for BashAliasDB service layer."""

    def test_init_creates_database(self, tmp_path: Path) -> None:
        """Database file is created on initialization."""
        db_path = tmp_path / "test_aliases.db"
        BashAliasDB(db_path)
        assert db_path.exists()

    def test_init_creates_table(self, tmp_path: Path) -> None:
        """Database table is created with correct schema."""
        db_path = tmp_path / "test_aliases.db"
        BashAliasDB(db_path)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='bash_aliases'"
            )
            assert cursor.fetchone() is not None

    def test_add_alias_returns_uid(self, tmp_path: Path) -> None:
        """Adding an alias returns sequential UID."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        uid1 = db.add_alias("ll", "ls -lah", "List all files")
        assert uid1 == 1

        uid2 = db.add_alias("la", "ls -la", "List with hidden")
        assert uid2 == 2

    def test_add_alias_duplicate_raises(self, tmp_path: Path) -> None:
        """Adding duplicate alias name raises IntegrityError."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("ll", "ls -lah")
        with pytest.raises(sqlite3.IntegrityError):
            db.add_alias("ll", "ls -la")

    def test_get_alias_returns_object(self, tmp_path: Path) -> None:
        """Getting an alias returns BashAlias object."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        uid = db.add_alias("ll", "ls -lah", "List all")
        alias_obj = db.get_alias(uid)

        assert alias_obj is not None
        assert alias_obj.uid == uid
        assert alias_obj.alias == "ll"
        assert alias_obj.function == "ls -lah"
        assert alias_obj.notes == "List all"

    def test_get_alias_not_found_returns_none(self, tmp_path: Path) -> None:
        """Getting non-existent alias returns None."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        result = db.get_alias(999)
        assert result is None

    def test_list_aliases_sorted_by_created_at(self, tmp_path: Path) -> None:
        """Listing aliases sorts by created_at DESC by default."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("aa", "cmd1")
        db.add_alias("zz", "cmd2")
        db.add_alias("bb", "cmd3")

        aliases = db.list_aliases(sort_by="created_at", descending=True)
        assert len(aliases) == 3
        assert aliases[0].alias == "bb"  # Newest first
        assert aliases[2].alias == "aa"  # Oldest last

    def test_list_aliases_sorted_by_alias_name(self, tmp_path: Path) -> None:
        """Listing aliases can sort alphabetically."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("zz", "cmd1")
        db.add_alias("aa", "cmd2")
        db.add_alias("mm", "cmd3")

        aliases = db.list_aliases(sort_by="alias", descending=False)
        assert aliases[0].alias == "aa"
        assert aliases[1].alias == "mm"
        assert aliases[2].alias == "zz"

    def test_list_aliases_inversigi(self, tmp_path: Path) -> None:
        """Listing aliases can be inverted."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("aa", "cmd1")
        db.add_alias("zz", "cmd2")

        aliases = db.list_aliases(sort_by="created_at", descending=False)
        assert aliases[0].alias == "aa"  # Oldest first
        assert aliases[1].alias == "zz"  # Newest last

    def test_search_aliases_by_name(self, tmp_path: Path) -> None:
        """Searching aliases finds by name."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("ll", "ls -lah")
        db.add_alias("la", "ls -la")
        db.add_alias("grep", "grep --color=auto")

        results = db.search_aliases("ll")
        assert len(results) == 1
        assert results[0].alias == "ll"

    def test_search_aliases_by_function(self, tmp_path: Path) -> None:
        """Searching aliases finds by function."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("ll", "ls -lah")
        db.add_alias("la", "ls -la")

        results = db.search_aliases("ls")
        assert len(results) == 2

    def test_search_aliases_by_notes(self, tmp_path: Path) -> None:
        """Searching aliases finds by notes."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("ll", "ls -lah", "useful list command")
        db.add_alias("cat", "cat -n", "show file with numbers")

        results = db.search_aliases("useful")
        assert len(results) == 1
        assert results[0].alias == "ll"

    def test_update_alias(self, tmp_path: Path) -> None:
        """Updating an alias modifies stored data."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        uid = db.add_alias("ll", "ls -la")
        db.update_alias(uid, function="ls -lah")

        alias_obj = db.get_alias(uid)
        assert alias_obj.function == "ls -lah"
        assert alias_obj.alias == "ll"  # Unchanged

    def test_update_alias_not_found_returns_false(self, tmp_path: Path) -> None:
        """Updating non-existent alias returns False."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        result = db.update_alias(999, alias="new")
        assert result is False

    def test_delete_alias(self, tmp_path: Path) -> None:
        """Deleting an alias removes it from database."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        uid = db.add_alias("ll", "ls -lah")
        db.delete_alias(uid)

        result = db.get_alias(uid)
        assert result is None

    def test_delete_alias_not_found_returns_false(self, tmp_path: Path) -> None:
        """Deleting non-existent alias returns False."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        result = db.delete_alias(999)
        assert result is False

    def test_uid_never_recycled(self, tmp_path: Path) -> None:
        """Deleting an alias doesn't recycle its UID."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        uid1 = db.add_alias("ll", "ls -lah")
        db.delete_alias(uid1)

        uid2 = db.add_alias("la", "ls -la")
        assert uid2 == 2  # Not recycled

    def test_generate_shell_script(self, tmp_path: Path) -> None:
        """Shell script generation includes all aliases."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("ll", "ls -lah")
        db.add_alias("la", "ls -la")

        script = db.generate_shell_script()
        assert "#!/bin/bash" in script
        assert "alias ll='ls -lah'" in script
        assert "alias la='ls -la'" in script

    def test_sync_shell_config_creates_file(self, tmp_path: Path) -> None:
        """Syncing writes shell config file to disk."""
        db_path = tmp_path / "test_aliases.db"
        shell_path = tmp_path / ".autish_aliases"

        db = BashAliasDB(db_path)
        db.add_alias("ll", "ls -lah")

        # Mock Path.home() to use tmp_path
        import autish.services.bash_alias as bash_alias_module

        original_home = Path.home

        def mock_home() -> Path:
            return tmp_path

        try:
            bash_alias_module.Path.home = mock_home  # type: ignore
            result_path = db.sync_shell_config()
            assert result_path == tmp_path / ".autish_aliases"
            assert shell_path.exists()
        finally:
            bash_alias_module.Path.home = original_home  # type: ignore

    def test_shell_script_escapes_special_chars(self, tmp_path: Path) -> None:
        """Shell script properly escapes special characters."""
        db_path = tmp_path / "test_aliases.db"
        db = BashAliasDB(db_path)

        db.add_alias("quoted", "echo 'hello world'")

        script = db.generate_shell_script()
        assert "alias quoted='echo '\\''hello world'\\'''" in script


class TestBashAliasCommands:
    """Tests for CLI commands."""

    def test_sistemo_backward_compat_shows_info(self) -> None:
        """Running 'sistemo' without subcommand shows system info."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "OS" in result.stdout or "CPU" in result.stdout

    def test_bash_help_shows_all_subcommands(self) -> None:
        """bash-alias subcommand shows help for all alias commands."""
        result = runner.invoke(app, ["bash-alias", "--help"])
        assert result.exit_code == 0
        assert "aldoni" in result.stdout
        assert "modifi" in result.stdout
        assert "forigi" in result.stdout
        assert "vidi" in result.stdout
        assert "ls" in result.stdout
        assert "serci" in result.stdout

    def test_aldoni_requires_options(self) -> None:
        """aldoni requires --alias and --function options."""
        result = runner.invoke(app, ["bash-alias", "aldoni"])
        assert result.exit_code != 0
        # Error messages are in output for Typer
        assert "Missing option" in result.output or "--alias" in result.output

    def test_modifi_requires_uid(self) -> None:
        """modifi requires UID argument."""
        result = runner.invoke(app, ["bash-alias", "modifi"])
        assert result.exit_code != 0

    def test_forigi_requires_uid(self) -> None:
        """forigi requires UID argument."""
        result = runner.invoke(app, ["bash-alias", "forigi"])
        assert result.exit_code != 0

    def test_vidi_requires_uid(self) -> None:
        """vidi requires UID argument."""
        result = runner.invoke(app, ["bash-alias", "vidi"])
        assert result.exit_code != 0


class TestMarkdownLinkParser:
    """Tests for markdown link parser in utils."""

    def test_parse_encik_links(self) -> None:
        """Parser extracts encik links."""
        from autish.utils import parse_markdown_links

        text = "[ECHO IV](ec#12345678) is interesting"
        links = parse_markdown_links(text)

        assert len(links) == 1
        assert links[0].text == "ECHO IV"
        assert links[0].link_type == "encik"
        assert links[0].uuid == "12345678"

    def test_parse_vorto_links(self) -> None:
        """Parser extracts vorto links."""
        from autish.utils import parse_markdown_links

        text = "[verbo](vt#abcdef01) is a word type"
        links = parse_markdown_links(text)

        assert len(links) == 1
        assert links[0].text == "verbo"
        assert links[0].link_type == "vorto"
        assert links[0].uuid == "abcdef01"

    def test_parse_multiple_links(self) -> None:
        """Parser extracts multiple links."""
        from autish.utils import parse_markdown_links

        text = "[Entry](ec#11111111) and [word](vt#22222222)"
        links = parse_markdown_links(text)

        assert len(links) == 2
        assert links[0].link_type == "encik"
        assert links[1].link_type == "vorto"

    def test_parse_no_links_returns_empty(self) -> None:
        """Parser returns empty list when no links present."""
        from autish.utils import parse_markdown_links

        text = "This has no links"
        links = parse_markdown_links(text)

        assert len(links) == 0

    def test_parse_empty_text_returns_empty(self) -> None:
        """Parser handles empty text."""
        from autish.utils import parse_markdown_links

        links = parse_markdown_links("")
        assert len(links) == 0

    def test_parse_invalid_uuid_ignored(self) -> None:
        """Parser ignores invalid UUID lengths."""
        from autish.utils import parse_markdown_links

        text = "[Entry](ec#123) short UUID"
        links = parse_markdown_links(text)
        assert len(links) == 0

    def test_validate_link_targets_with_valid_uuids(self) -> None:
        """Validator filters to valid UUIDs."""
        from autish.utils import MarkdownLink, validate_link_targets

        links = [
            MarkdownLink(text="Entry1", link_type="encik", uuid="11111111"),
            MarkdownLink(text="Entry2", link_type="encik", uuid="99999999"),
        ]
        encik_uuids = {"11111111", "22222222"}

        valid = validate_link_targets(links, encik_uuids=encik_uuids)
        assert len(valid) == 1
        assert valid[0].uuid == "11111111"

    def test_validate_link_targets_without_validation_set(self) -> None:
        """Validator keeps all links when no validation set provided."""
        from autish.utils import MarkdownLink, validate_link_targets

        links = [
            MarkdownLink(text="Entry1", link_type="encik", uuid="11111111"),
            MarkdownLink(text="Entry2", link_type="encik", uuid="99999999"),
        ]

        valid = validate_link_targets(links)
        assert len(valid) == 2
