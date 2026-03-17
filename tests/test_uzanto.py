"""Tests for autish.commands.uzanto (user profile & master password)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers & fixtures
# ──────────────────────────────────────────────────────────────────────────────

_NO_MASTER = "autish.commands.uzanto._get_master_password"
_SET_MASTER = "autish.commands.uzanto._set_master_password"


@pytest.fixture()
def isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect uzanto profile files to a temp directory."""
    import autish.commands.uzanto as uz_mod

    monkeypatch.setattr(uz_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(uz_mod, "_PROFILE_FILE", tmp_path / "uzanto_profilo.toml")
    monkeypatch.setattr(uz_mod, "_PROFILE_ENC_FILE", tmp_path / "uzanto_profilo.enc")
    yield tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# profilo vidi — empty profile
# ──────────────────────────────────────────────────────────────────────────────


class TestProfiloVidi:
    def test_empty_profile(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "profilo", "vidi"])
        assert result.exit_code == 0
        assert "Neniu" in result.output

    def test_show_all_fields(self, isolated_profile):
        import autish.commands.uzanto as uz_mod

        (isolated_profile / "uzanto_profilo.toml").write_text(
            'nomo = "Alice"\nfamilia_nomo = "Smith"\norganizo = "ACME"\n',
            encoding="utf-8",
        )
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "profilo", "vidi"])
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "Smith" in result.output

    def test_show_single_flag(self, isolated_profile):
        (isolated_profile / "uzanto_profilo.toml").write_text(
            'nomo = "Bob"\norganizo = "Corp"\n',
            encoding="utf-8",
        )
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "profilo", "vidi", "-N"])
        assert result.exit_code == 0
        assert "Bob" in result.output
        # organizo should NOT appear when only -N is requested
        assert "Corp" not in result.output

    def test_show_custom_field(self, isolated_profile):
        (isolated_profile / "uzanto_profilo.toml").write_text(
            '[kampoj]\ntwitter = "@alice"\n',
            encoding="utf-8",
        )
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "profilo", "vidi", "-k", "twitter"])
        assert result.exit_code == 0
        assert "@alice" in result.output

    def test_missing_custom_field_exits_nonzero(self, isolated_profile):
        (isolated_profile / "uzanto_profilo.toml").write_text(
            'nomo = "Alice"\n', encoding="utf-8"
        )
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "profilo", "vidi", "-k", "nonexist"])
        assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────────────
# profilo modifi
# ──────────────────────────────────────────────────────────────────────────────


class TestProfiloModifi:
    def test_set_nomo(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-N", "Alice"]
            )
        assert result.exit_code == 0
        profile_file = isolated_profile / "uzanto_profilo.toml"
        assert profile_file.exists()
        content = profile_file.read_text(encoding="utf-8")
        assert "Alice" in content

    def test_set_lingvoj(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-L", "en,fr"]
            )
        assert result.exit_code == 0
        content = (isolated_profile / "uzanto_profilo.toml").read_text(encoding="utf-8")
        assert "en" in content
        assert "fr" in content

    def test_set_custom_field(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                ["uzanto", "profilo", "modifi", "-k", "twitter:@bob"],
            )
        assert result.exit_code == 0
        content = (isolated_profile / "uzanto_profilo.toml").read_text(encoding="utf-8")
        assert "@bob" in content

    def test_invalid_date_format(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-d", "01/01/1990"]
            )
        assert result.exit_code != 0

    def test_valid_date_format(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-d", "1990-06-15"]
            )
        assert result.exit_code == 0

    def test_invalid_custom_field_format(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-k", "NOCORONVALUE"]
            )
        assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────────────
# profilo eksporti / importi
# ──────────────────────────────────────────────────────────────────────────────


class TestProfiloEksportiImporti:
    def _write_plain_profile(self, dir_path: Path, content: str) -> None:
        (dir_path / "uzanto_profilo.toml").write_text(content, encoding="utf-8")

    def test_export_encrypted(self, isolated_profile, tmp_path):
        self._write_plain_profile(isolated_profile, 'nomo = "Alice"\n')
        out = tmp_path / "profilo.enc"
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                ["uzanto", "profilo", "eksporti", str(out), "-p", "SecurePass1"],
            )
        assert result.exit_code == 0, result.output
        raw = out.read_bytes()
        assert raw[:4] == b"AUTX"

    def test_export_no_profile_exits_nonzero(self, isolated_profile, tmp_path):
        out = tmp_path / "profilo.enc"
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                ["uzanto", "profilo", "eksporti", str(out), "-p", "SecurePass1"],
            )
        assert result.exit_code != 0

    def test_export_weak_password_exits_nonzero(self, isolated_profile, tmp_path):
        self._write_plain_profile(isolated_profile, 'nomo = "Alice"\n')
        out = tmp_path / "profilo.enc"
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                ["uzanto", "profilo", "eksporti", str(out), "-p", "weak"],
            )
        assert result.exit_code != 0

    def test_roundtrip_export_import(self, isolated_profile, tmp_path):
        self._write_plain_profile(
            isolated_profile,
            'nomo = "Alice"\norganizo = "ACME"\n',
        )
        out = tmp_path / "profilo.enc"
        with patch(_NO_MASTER, return_value=None):
            runner.invoke(
                app,
                ["uzanto", "profilo", "eksporti", str(out), "-p", "SecurePass1"],
            )

        # Remove profile so import creates fresh
        (isolated_profile / "uzanto_profilo.toml").unlink()

        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                [
                    "uzanto",
                    "profilo",
                    "importi",
                    str(out),
                    "-p",
                    "SecurePass1",
                    "-A",
                ],
            )
        assert result.exit_code == 0, result.output
        content = (isolated_profile / "uzanto_profilo.toml").read_text(encoding="utf-8")
        assert "Alice" in content

    def test_import_wrong_password_fails(self, isolated_profile, tmp_path):
        from autish.commands._crypto import encrypt

        blob = encrypt(b'nomo = "Bob"\n', "RightPass1")
        enc_file = tmp_path / "profilo.enc"
        enc_file.write_bytes(blob)

        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                [
                    "uzanto",
                    "profilo",
                    "importi",
                    str(enc_file),
                    "-p",
                    "WrongPass1",
                    "-A",
                ],
            )
        assert result.exit_code != 0

    def test_import_missing_file(self, isolated_profile, tmp_path):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(
                app,
                [
                    "uzanto",
                    "profilo",
                    "importi",
                    str(tmp_path / "ghost.enc"),
                    "-p",
                    "SomePass1",
                ],
            )
        assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────────────
# Profile encryption at rest (master password integration)
# ──────────────────────────────────────────────────────────────────────────────


class TestProfileEncryption:
    def test_profile_saved_encrypted_when_master_set(self, isolated_profile):
        """When master password is set, profile is saved as .enc file."""
        import autish.commands.uzanto as uz_mod

        with patch(_NO_MASTER, return_value="MasterPass1"):
            runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-N", "Alice"]
            )
        # The .enc file should exist; the plain TOML should not
        assert (isolated_profile / "uzanto_profilo.enc").exists()
        assert not (isolated_profile / "uzanto_profilo.toml").exists()

    def test_profile_saved_plain_when_no_master(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            runner.invoke(
                app, ["uzanto", "profilo", "modifi", "-N", "Bob"]
            )
        assert (isolated_profile / "uzanto_profilo.toml").exists()
        assert not (isolated_profile / "uzanto_profilo.enc").exists()


# ──────────────────────────────────────────────────────────────────────────────
# uzanto pasvorto
# ──────────────────────────────────────────────────────────────────────────────


class TestUzantoPasvorto:
    def test_set_new_password(self, isolated_profile):
        with (
            patch(_NO_MASTER, return_value=None),
            patch(_SET_MASTER) as mock_set,
            patch("autish.commands.uzanto._re_encrypt_profile"),
        ):
            result = runner.invoke(
                app,
                ["uzanto", "pasvorto"],
                input="NewMasterP1\nNewMasterP1\n",
            )
        assert result.exit_code == 0, result.output
        mock_set.assert_called_once_with("NewMasterP1")

    def test_weak_password_rejected(self, isolated_profile):
        with (
            patch(_NO_MASTER, return_value=None),
            patch("autish.commands.uzanto._re_encrypt_profile"),
        ):
            result = runner.invoke(
                app,
                ["uzanto", "pasvorto"],
                input="weak\nweak\n",
            )
        assert result.exit_code != 0

    def test_forigi_no_master_set(self, isolated_profile):
        with patch(_NO_MASTER, return_value=None):
            result = runner.invoke(app, ["uzanto", "pasvorto", "--forigi"])
        assert result.exit_code != 0

    def test_forigi_with_confirmation(self, isolated_profile):
        with (
            patch(_NO_MASTER, return_value="OldMaster1"),
            patch("autish.commands.uzanto._delete_master_password") as mock_del,
            patch("autish.commands.uzanto._re_encrypt_profile"),
        ):
            result = runner.invoke(
                app,
                ["uzanto", "pasvorto", "--forigi"],
                input="konfirmi\n",
            )
        assert result.exit_code == 0, result.output
        mock_del.assert_called_once()

    def test_forigi_wrong_confirmation(self, isolated_profile):
        with (
            patch(_NO_MASTER, return_value="OldMaster1"),
            patch("autish.commands.uzanto._delete_master_password") as mock_del,
            patch("autish.commands.uzanto._re_encrypt_profile"),
        ):
            result = runner.invoke(
                app,
                ["uzanto", "pasvorto", "--forigi"],
                input="ne\n",
            )
        assert result.exit_code == 0
        mock_del.assert_not_called()
        assert "Nuligita" in result.output
