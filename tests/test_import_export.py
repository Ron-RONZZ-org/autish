"""Tests for the new import/export and sekurkopio features."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# _crypto helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self):
        from autish.commands._crypto import decrypt, encrypt

        plaintext = b"hello autish world"
        password = "TestPass1"
        encrypted = encrypt(plaintext, password)
        assert encrypted != plaintext
        assert decrypt(encrypted, password) == plaintext

    def test_wrong_password_raises(self):
        from autish.commands._crypto import decrypt, encrypt

        encrypted = encrypt(b"secret", "GoodPass1")
        with pytest.raises(ValueError):
            decrypt(encrypted, "WrongPass1")

    def test_is_encrypted_true(self):
        from autish.commands._crypto import encrypt, is_encrypted

        blob = encrypt(b"data", "TestPass1")
        assert is_encrypted(blob)

    def test_is_encrypted_false_for_plaintext(self):
        from autish.commands._crypto import is_encrypted

        assert not is_encrypted(b"plain text data here")

    def test_validate_strong_password_ok(self):
        from autish.commands._crypto import validate_strong_password

        assert validate_strong_password("Secure1pass") is None

    def test_validate_strong_password_too_short(self):
        from autish.commands._crypto import validate_strong_password

        assert validate_strong_password("Sh0rt") is not None

    def test_validate_strong_password_no_upper(self):
        from autish.commands._crypto import validate_strong_password

        assert validate_strong_password("nouppercase1") is not None

    def test_validate_strong_password_no_lower(self):
        from autish.commands._crypto import validate_strong_password

        assert validate_strong_password("NOLOWER123") is not None

    def test_validate_strong_password_no_digit(self):
        from autish.commands._crypto import validate_strong_password

        assert validate_strong_password("NoDigitHere") is not None


# ──────────────────────────────────────────────────────────────────────────────
# vorto eksporti / importi
# ──────────────────────────────────────────────────────────────────────────────

_SAMPLE_ENTRIES = [
    {
        "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "teksto": "hello",
        "lingvo": "en",
        "kategorio": "vorto",
        "tipo": None,
        "temo": None,
        "tono": None,
        "nivelo": None,
        "difinoj": ["a greeting"],
        "uzoj": [],
        "etikedoj": {},
        "ligiloj": [],
        "kreita_je": "2024-01-01T00:00:00+00:00",
        "modifita_je": "2024-01-01T00:00:00+00:00",
    }
]

_VORTO_LOAD = "autish.commands.vorto._load_entries"
_VORTO_SAVE = "autish.commands.vorto._save_entries"
_VORTO_CONFIRM = "autish.commands.vorto._confirm_esperante"
_VORTO_GET_DB = "autish.commands.vorto._get_db"


class TestVortoEksporti:
    def test_plaintext_export(self, tmp_path):
        out = tmp_path / "vorto.json"
        with patch(_VORTO_LOAD, return_value=_SAMPLE_ENTRIES):
            result = runner.invoke(app, ["vorto", "eksporti", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(out.read_bytes())
        assert len(data) == 1
        assert data[0]["teksto"] == "hello"

    def test_encrypted_export(self, tmp_path):
        out = tmp_path / "vorto.enc"
        with patch(_VORTO_LOAD, return_value=_SAMPLE_ENTRIES):
            result = runner.invoke(
                app, ["vorto", "eksporti", str(out), "-p", "TestPass1"]
            )
        assert result.exit_code == 0, result.output
        raw = out.read_bytes()
        # Must start with the AUTX magic bytes
        assert raw[:4] == b"AUTX"

    def test_empty_entries_still_works(self, tmp_path):
        out = tmp_path / "empty.json"
        with patch(_VORTO_LOAD, return_value=[]):
            result = runner.invoke(app, ["vorto", "eksporti", str(out)])
        assert result.exit_code == 0
        assert json.loads(out.read_bytes()) == []


class TestVortoImporti:
    def test_plaintext_import_merge(self, tmp_path):
        in_file = tmp_path / "vorto.json"
        in_file.write_bytes(json.dumps(_SAMPLE_ENTRIES).encode())
        with (
            patch(_VORTO_LOAD, return_value=[]),
            patch(_VORTO_SAVE) as mock_save,
        ):
            result = runner.invoke(app, ["vorto", "importi", str(in_file)])
        assert result.exit_code == 0, result.output
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["teksto"] == "hello"

    def test_encrypted_import(self, tmp_path):
        from autish.commands._crypto import encrypt

        payload = json.dumps(_SAMPLE_ENTRIES).encode("utf-8")
        enc = encrypt(payload, "TestPass1")
        in_file = tmp_path / "vorto.enc"
        in_file.write_bytes(enc)
        with (
            patch(_VORTO_LOAD, return_value=[]),
            patch(_VORTO_SAVE) as mock_save,
        ):
            result = runner.invoke(
                app, ["vorto", "importi", str(in_file), "-p", "TestPass1"]
            )
        assert result.exit_code == 0, result.output
        saved = mock_save.call_args[0][0]
        assert saved[0]["teksto"] == "hello"

    def test_wrong_password_fails(self, tmp_path):
        from autish.commands._crypto import encrypt

        payload = json.dumps(_SAMPLE_ENTRIES).encode("utf-8")
        enc = encrypt(payload, "TestPass1")
        in_file = tmp_path / "vorto.enc"
        in_file.write_bytes(enc)
        result = runner.invoke(
            app, ["vorto", "importi", str(in_file), "-p", "WrongPass1"]
        )
        assert result.exit_code != 0

    def test_import_skips_duplicates(self, tmp_path):
        in_file = tmp_path / "vorto.json"
        in_file.write_bytes(json.dumps(_SAMPLE_ENTRIES).encode())
        # Existing entries already contain the same UUID
        with (
            patch(_VORTO_LOAD, return_value=_SAMPLE_ENTRIES),
            patch(_VORTO_SAVE) as mock_save,
        ):
            result = runner.invoke(app, ["vorto", "importi", str(in_file)])
        assert result.exit_code == 0
        # No new entries should have been added
        saved = mock_save.call_args[0][0]
        assert len(saved) == len(_SAMPLE_ENTRIES)

    def test_missing_file_exits_nonzero(self, tmp_path):
        result = runner.invoke(
            app, ["vorto", "importi", str(tmp_path / "nonexistent.json")]
        )
        assert result.exit_code != 0

    def test_overwrite_mode(self, tmp_path):
        in_file = tmp_path / "vorto.json"
        in_file.write_bytes(json.dumps(_SAMPLE_ENTRIES).encode())
        mock_con = MagicMock()
        mock_con.__enter__ = lambda s: s
        mock_con.__exit__ = MagicMock(return_value=False)
        mock_con.execute = MagicMock()
        mock_con.commit = MagicMock()
        with (
            patch(_VORTO_LOAD, return_value=[]),
            patch(_VORTO_SAVE) as mock_save,
            patch(_VORTO_CONFIRM, return_value=True),
            patch(_VORTO_GET_DB, return_value=mock_con),
        ):
            result = runner.invoke(
                app, ["vorto", "importi", str(in_file), "--anstatauigi"]
            )
        assert result.exit_code == 0, result.output


# ──────────────────────────────────────────────────────────────────────────────
# retposto eksporti / importi
# ──────────────────────────────────────────────────────────────────────────────

_SAMPLE_ACCOUNTS = [
    {
        "id": 1,
        "ordo": 1,
        "nomo": "Test User",
        "retposto": "test@example.com",
        "imap_servilo": "imap.example.com",
        "imap_haveno": 993,
        "imap_ssl": 1,
        "smtp_servilo": "smtp.example.com",
        "smtp_haveno": 587,
        "smtp_tls": 1,
        "uzantonomo": "test@example.com",
        "subskribo": "",
        "kreita_je": "2024-01-01T00:00:00+00:00",
    }
]

_RET_LOAD_ACCS = "autish.commands.retposto._load_accounts"
_RET_SAVE_ACC = "autish.commands.retposto._save_account"
_RET_SET_PW = "autish.commands.retposto._set_password"
_RET_DEL_ACC = "autish.commands.retposto._delete_account"
_RET_CONFIRM = "autish.commands.retposto._confirm_esperante"


class TestRetpostoEksporti:
    def test_export_requires_strong_password(self, tmp_path):
        out = tmp_path / "kontoj.toml.enc"
        with patch(_RET_LOAD_ACCS, return_value=_SAMPLE_ACCOUNTS):
            result = runner.invoke(
                app,
                ["retposto", "eksporti", str(out), "-p", "weak"],
            )
        assert result.exit_code != 0
        assert "Pasvorto" in result.output or "pasvorto" in result.output.lower()

    def test_export_creates_encrypted_file(self, tmp_path):
        out = tmp_path / "kontoj.enc"
        with (
            patch(_RET_LOAD_ACCS, return_value=_SAMPLE_ACCOUNTS),
            patch(
                "autish.commands.retposto.keyring.get_password",
                return_value="secret",
            ),
        ):
            result = runner.invoke(
                app,
                ["retposto", "eksporti", str(out), "-p", "StrongPass1"],
            )
        assert result.exit_code == 0, result.output
        raw = out.read_bytes()
        assert raw[:4] == b"AUTX"

    def test_export_no_accounts_exits_nonzero(self, tmp_path):
        out = tmp_path / "empty.enc"
        with patch(_RET_LOAD_ACCS, return_value=[]):
            result = runner.invoke(
                app,
                ["retposto", "eksporti", str(out), "-p", "StrongPass1"],
            )
        assert result.exit_code != 0


class TestRetpostoImporti:
    def _make_export(self, tmp_path: Path, password: str = "StrongPass1") -> Path:
        """Create a valid encrypted retposto export."""
        from autish.commands._crypto import encrypt
        from autish.commands.retposto import _accounts_to_toml

        toml_bytes = _accounts_to_toml(_SAMPLE_ACCOUNTS, {1: "mailpassword"})
        enc = encrypt(toml_bytes, password)
        out = tmp_path / "kontoj.enc"
        out.write_bytes(enc)
        return out

    def test_import_adds_accounts(self, tmp_path):
        in_file = self._make_export(tmp_path)
        with (
            patch(_RET_SAVE_ACC, return_value=99) as mock_save,
            patch(_RET_SET_PW),
        ):
            result = runner.invoke(
                app,
                ["retposto", "importi", str(in_file), "-p", "StrongPass1"],
            )
        assert result.exit_code == 0, result.output
        assert mock_save.called

    def test_import_wrong_password_fails(self, tmp_path):
        in_file = self._make_export(tmp_path, password="StrongPass1")
        result = runner.invoke(
            app,
            ["retposto", "importi", str(in_file), "-p", "WrongPass2"],
        )
        assert result.exit_code != 0

    def test_import_unencrypted_file_rejected(self, tmp_path):
        in_file = tmp_path / "plain.toml"
        in_file.write_bytes(b"[kontoj]\n")
        result = runner.invoke(
            app,
            ["retposto", "importi", str(in_file), "-p", "StrongPass1"],
        )
        assert result.exit_code != 0

    def test_import_missing_file_exits_nonzero(self, tmp_path):
        result = runner.invoke(
            app,
            ["retposto", "importi", str(tmp_path / "ghost.enc"), "-p", "StrongPass1"],
        )
        assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────────────
# sekurkopio
# ──────────────────────────────────────────────────────────────────────────────


class TestSekurkopio:
    def test_eksporti_weak_password_rejected(self, tmp_path):
        out = tmp_path / "backup.7z"
        result = runner.invoke(
            app, ["sekurkopio", "eksporti", str(out), "-p", "weak"]
        )
        assert result.exit_code != 0

    def test_eksporti_bad_formato_rejected(self, tmp_path):
        out = tmp_path / "backup.bz2"
        result = runner.invoke(
            app, ["sekurkopio", "eksporti", str(out), "-p", "StrongPass1", "-f", "tar"]
        )
        assert result.exit_code != 0

    def test_eksporti_creates_7z_file(self, tmp_path):
        out = tmp_path / "backup.7z"
        with patch(
            "autish.commands.sekurkopio._collect_autish_data_files",
            return_value=[],
        ):
            result = runner.invoke(
                app, ["sekurkopio", "eksporti", str(out), "-p", "StrongPass1"]
            )
        # No files to archive → exits with error
        assert result.exit_code != 0

    def test_eksporti_zip_with_real_file(self, tmp_path):
        data_file = tmp_path / "vorto.db"
        data_file.write_bytes(b"SQLITE")
        out = tmp_path / "backup.zip"
        with patch(
            "autish.commands.sekurkopio._collect_autish_data_files",
            return_value=[data_file],
        ):
            with patch(
                "autish.commands.sekurkopio._push_history",
            ):
                result = runner.invoke(
                    app,
                    [
                        "sekurkopio",
                        "eksporti",
                        str(out),
                        "-p",
                        "StrongPass1",
                        "-f",
                        "zip",
                    ],
                )
        assert result.exit_code == 0, result.output
        # The file is an encrypted AUTX blob
        assert out.read_bytes()[:4] == b"AUTX"

    def test_historio_empty(self):
        with patch(
            "autish.commands.sekurkopio._load_history", return_value=[]
        ):
            result = runner.invoke(app, ["sekurkopio", "historio"])
        assert result.exit_code == 0
        assert "Neniu historio" in result.output

    def test_historio_shows_records(self):
        sample = [
            {
                "id": 1,
                "okazis_je": "2024-06-01T10:00:00+00:00",
                "ago": "eksporti",
                "detaloj": '{"dosiero": "/tmp/b.7z"}',
            }
        ]
        with patch("autish.commands.sekurkopio._load_history", return_value=sample):
            result = runner.invoke(app, ["sekurkopio", "historio"])
        assert result.exit_code == 0
        assert "eksporti" in result.output

    def test_importi_missing_file(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "sekurkopio",
                "importi",
                str(tmp_path / "nope.7z"),
                "-p",
                "StrongPass1",
            ],
        )
        assert result.exit_code != 0

    def test_importi_roundtrip_zip(self, tmp_path):
        """Export a zip and then import it back."""
        data_file = tmp_path / "vorto.db"
        data_file.write_bytes(b"SQLITE DB CONTENT")
        out = tmp_path / "backup.zip"
        dest_dir = tmp_path / "restored"
        dest_dir.mkdir()

        with patch(
            "autish.commands.sekurkopio._collect_autish_data_files",
            return_value=[data_file],
        ):
            with patch("autish.commands.sekurkopio._push_history"):
                result = runner.invoke(
                    app,
                    [
                        "sekurkopio",
                        "eksporti",
                        str(out),
                        "-p",
                        "StrongPass1",
                        "-f",
                        "zip",
                    ],
                )
        assert result.exit_code == 0, result.output

        # Now import it
        with patch(
            "autish.commands.sekurkopio._DATA_DIR", new=dest_dir
        ):
            with patch("autish.commands.sekurkopio._push_history"):
                result2 = runner.invoke(
                    app,
                    [
                        "sekurkopio",
                        "importi",
                        str(out),
                        "-p",
                        "StrongPass1",
                    ],
                )
        assert result2.exit_code == 0, result2.output


# ──────────────────────────────────────────────────────────────────────────────
# Direct entry points (pyproject.toml scripts)
# ──────────────────────────────────────────────────────────────────────────────


class TestDirectEntryPoints:
    """Verify that direct CLI apps are importable as Typer apps."""

    def test_retposto_app_is_typer(self):
        from autish.commands.retposto import app as ret_app

        assert ret_app is not None

    def test_bluetooth_app_is_typer(self):
        from autish.commands.bluetooth import app as bt_app

        assert bt_app is not None

    def test_wifi_app_is_typer(self):
        from autish.commands.wifi import app as wifi_app

        assert wifi_app is not None

    def test_sistemo_app_is_typer(self):
        from autish.commands.sistemo import app as sistemo_app

        assert sistemo_app is not None

    def test_tempo_app_is_typer(self):
        from autish.commands.tempo import app as tempo_app

        assert tempo_app is not None

    def test_sekurkopio_app_is_typer(self):
        from autish.commands.sekurkopio import app as skp_app

        assert skp_app is not None

    def test_sekurkopio_registered_in_main(self):
        """sekurkopio must be registered in the root autish app."""
        result = runner.invoke(app, ["--help"])
        assert "sekurkopio" in result.output
