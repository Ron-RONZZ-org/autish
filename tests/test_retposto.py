"""Tests for autish.commands.retposto (Retpoŝto email microapp)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from autish.commands.retposto import (
    _add_spam_block,
    _apply_filters,
    _build_sieve_script,
    _decode_header,
    _eval_sieve_condition,
    _export_vcf,
    _extract_address,
    _extract_address_list,
    _import_vcf,
    _is_spam,
    _load_spam_blocks,
    _parse_imap_message,
    _remove_spam_block,
    _upsert_contact,
)
from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures — isolated DB
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect retposto DB to a temp directory."""
    import autish.commands.retposto as rp_mod

    monkeypatch.setattr(rp_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(rp_mod, "_DB_FILE", tmp_path / "retposto.db")
    yield tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _decode_header
# ──────────────────────────────────────────────────────────────────────────────


class TestDecodeHeader:
    def test_plain_ascii(self):
        assert _decode_header("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        assert _decode_header(None) == ""

    def test_empty_returns_empty(self):
        assert _decode_header("") == ""

    def test_utf8_encoded(self):
        # RFC 2047 encoded UTF-8
        encoded = "=?utf-8?b?SGVsbG8gV29ybGQ=?="
        assert _decode_header(encoded) == "Hello World"

    def test_latin1_encoded(self):
        encoded = "=?iso-8859-1?q?caf=E9?="
        result = _decode_header(encoded)
        assert "caf" in result


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _extract_address / _extract_address_list
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractAddress:
    def test_angle_brackets(self):
        assert _extract_address("Alice <alice@example.com>") == "alice@example.com"

    def test_plain_address(self):
        assert _extract_address("bob@example.com") == "bob@example.com"

    def test_empty(self):
        assert _extract_address("") == ""

    def test_none(self):
        assert _extract_address(None) == ""

    def test_lowercase(self):
        assert _extract_address("User@EXAMPLE.COM") == "user@example.com"


class TestExtractAddressList:
    def test_single(self):
        assert _extract_address_list("alice@example.com") == ["alice@example.com"]

    def test_multiple_comma_separated(self):
        result = _extract_address_list("alice@a.com, bob@b.com")
        assert result == ["alice@a.com", "bob@b.com"]

    def test_with_display_names(self):
        result = _extract_address_list(
            "Alice <alice@a.com>, Bob <bob@b.com>"
        )
        assert "alice@a.com" in result
        assert "bob@b.com" in result

    def test_empty(self):
        assert _extract_address_list("") == []

    def test_none(self):
        assert _extract_address_list(None) == []


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _parse_imap_message
# ──────────────────────────────────────────────────────────────────────────────


class TestParseImapMessage:
    def _make_raw(
        self,
        subject="Test",
        from_="sender@example.com",
        to="rcpt@example.com",
        body="Hello",
        date="Mon, 01 Jan 2024 12:00:00 +0000",
    ) -> bytes:
        return (
            f"From: {from_}\r\n"
            f"To: {to}\r\n"
            f"Subject: {subject}\r\n"
            f"Date: {date}\r\n"
            f"Message-ID: <test-123@example.com>\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"\r\n"
            f"{body}\r\n"
        ).encode("utf-8")

    def test_basic_parse(self):
        raw = self._make_raw()
        msg = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["de"] == "sender@example.com"
        assert msg["al"] == ["rcpt@example.com"]
        assert msg["subjekto"] == "Test"
        assert "Hello" in (msg["korpo"] or "")
        assert msg["konto_id"] == 1

    def test_message_id_extracted(self):
        raw = self._make_raw()
        msg = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert msg["message_id"] == "<test-123@example.com>"

    def test_unicode_subject(self):
        raw = self._make_raw(subject="Saluton Ĉiuj")
        msg = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert "Saluton" in (msg["subjekto"] or "")

    def test_uid_stored(self):
        raw = self._make_raw()
        msg = _parse_imap_message(raw, konto_id=2, dosierujo_id=3, uid="42")
        assert msg["uid"] == "42"

    def test_date_parsed(self):
        raw = self._make_raw(date="Mon, 01 Jan 2024 12:00:00 +0000")
        msg = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert msg["ricevita_je"] is not None
        assert "2024" in msg["ricevita_je"]


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — spam blocking
# ──────────────────────────────────────────────────────────────────────────────


class TestSpamBlocking:
    def test_add_and_check(self, isolated_db):
        _add_spam_block("spam@evil.com")
        assert _is_spam("spam@evil.com")

    def test_domain_block(self, isolated_db):
        _add_spam_block("evil.com")
        assert _is_spam("any@evil.com")
        assert not _is_spam("good@safe.org")

    def test_remove_block(self, isolated_db):
        _add_spam_block("block@me.com")
        _remove_spam_block("block@me.com")
        assert not _is_spam("block@me.com")

    def test_not_spam_without_block(self, isolated_db):
        assert not _is_spam("legit@example.com")

    def test_case_insensitive(self, isolated_db):
        _add_spam_block("SPAM@EVIL.COM")
        assert _is_spam("SPAM@EVIL.COM")
        assert _is_spam("spam@evil.com")

    def test_load_spam_blocks(self, isolated_db):
        _add_spam_block("a@b.com")
        _add_spam_block("c@d.com")
        blocks = _load_spam_blocks()
        rules = [b["regulo"] for b in blocks]
        assert "a@b.com" in rules
        assert "c@d.com" in rules


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — Sieve condition evaluation
# ──────────────────────────────────────────────────────────────────────────────


class TestEvalSieveCondition:
    def test_from_contains(self):
        assert _eval_sieve_condition(
            'from contains "spam"',
            sender="spam@evil.com", recipients="me@ok.com",
            subject="hi", body="content"
        )

    def test_from_contains_no_match(self):
        assert not _eval_sieve_condition(
            'from contains "spam"',
            sender="legit@good.com", recipients="me@ok.com",
            subject="hi", body="content"
        )

    def test_subject_is(self):
        assert _eval_sieve_condition(
            'subject is "hello"',
            sender="a@b.com", recipients="c@d.com",
            subject="hello", body=""
        )

    def test_not_contains(self):
        assert _eval_sieve_condition(
            'from not contains "spam"',
            sender="legit@ok.com", recipients="",
            subject="", body=""
        )
        assert not _eval_sieve_condition(
            'from not contains "spam"',
            sender="spam@evil.com", recipients="",
            subject="", body=""
        )

    def test_body_contains(self):
        assert _eval_sieve_condition(
            'body contains "buy now"',
            sender="a@b.com", recipients="",
            subject="", body="Click here to buy now!"
        )

    def test_multiple_conditions_all_match(self):
        assert _eval_sieve_condition(
            'from contains "evil" subject contains "win"',
            sender="evil@domain.com", recipients="",
            subject="you win a prize", body=""
        )

    def test_multiple_conditions_one_fails(self):
        assert not _eval_sieve_condition(
            'from contains "evil" subject contains "win"',
            sender="evil@domain.com", recipients="",
            subject="normal subject", body=""
        )


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _apply_filters
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyFilters:
    def _make_msg(self, **kwargs) -> dict:
        defaults = {
            "id": 1, "konto_id": 1, "de": "sender@example.com",
            "al": ["me@example.com"], "cc": [], "bcc": [],
            "subjekto": "Hello", "korpo": "Normal content",
            "spamo": 0, "forigita": 0, "legita": 0, "prioritato": 5,
        }
        defaults.update(kwargs)
        return defaults

    def test_fileinto_action(self):
        filters = [{
            "nomo": "newsletter",
            "sieve_kodo": 'from contains "newsletter" => fileinto "Newsletter"',
        }]
        msg = self._make_msg(de="newsletter@company.com")
        result = _apply_filters(msg, filters)
        assert result.get("_filter_folder") == "Newsletter"

    def test_mark_spam_action(self):
        filters = [{
            "nomo": "spamfilter",
            "sieve_kodo": 'subject contains "FREE MONEY" => mark-spam',
        }]
        msg = self._make_msg(subjekto="WIN FREE MONEY NOW")
        result = _apply_filters(msg, filters)
        assert result["spamo"] == 1

    def test_mark_read_action(self):
        filters = [{
            "nomo": "autoread",
            "sieve_kodo": 'from contains "noreply" => mark-read',
        }]
        msg = self._make_msg(de="noreply@service.com")
        result = _apply_filters(msg, filters)
        assert result["legita"] == 1

    def test_set_priority_action(self):
        filters = [{
            "nomo": "boss",
            "sieve_kodo": 'from contains "boss@" => set-priority "9"',
        }]
        msg = self._make_msg(de="boss@company.com")
        result = _apply_filters(msg, filters)
        assert result["prioritato"] == 9

    def test_discard_action(self):
        filters = [{
            "nomo": "discard-spam",
            "sieve_kodo": 'subject contains "UNSUBSCRIBE" => discard',
        }]
        msg = self._make_msg(subjekto="Click to UNSUBSCRIBE")
        result = _apply_filters(msg, filters)
        assert result["forigita"] == 1

    def test_no_match_unchanged(self):
        filters = [{
            "nomo": "test",
            "sieve_kodo": 'from contains "evil" => mark-spam',
        }]
        msg = self._make_msg(de="good@person.com")
        result = _apply_filters(msg, filters)
        assert result["spamo"] == 0

    def test_bad_sieve_code_skipped(self):
        filters = [{"nomo": "bad", "sieve_kodo": "this is not valid"}]
        msg = self._make_msg()
        result = _apply_filters(msg, filters)
        assert result["spamo"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _build_sieve_script
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildSieveScript:
    def test_produces_require(self):
        script = _build_sieve_script([])
        assert "require" in script

    def test_fileinto_rule(self):
        filters = [{
            "nomo": "test",
            "sieve_kodo": 'from contains "list" => fileinto "Lists"',
        }]
        script = _build_sieve_script(filters)
        assert "fileinto" in script
        assert "Lists" in script

    def test_discard_rule(self):
        filters = [{
            "nomo": "test",
            "sieve_kodo": 'subject contains "spam" => discard',
        }]
        script = _build_sieve_script(filters)
        assert "discard" in script

    def test_mark_spam_rule(self):
        filters = [{
            "nomo": "test",
            "sieve_kodo": 'from contains "evil" => mark-spam',
        }]
        script = _build_sieve_script(filters)
        assert "Junk" in script or "addflag" in script

    def test_invalid_filter_skipped(self):
        filters = [{"nomo": "bad", "sieve_kodo": "no arrow here"}]
        script = _build_sieve_script(filters)
        # Should not crash; only produces require line
        assert "require" in script


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — VCF import / export
# ──────────────────────────────────────────────────────────────────────────────


class TestVcfImportExport:
    _SAMPLE_VCF = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "FN:Alice Example\r\n"
        "EMAIL:alice@example.com\r\n"
        "ORG:Acme Corp\r\n"
        "TEL:+1234567890\r\n"
        "END:VCARD\r\n"
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "FN:Bob Test\r\n"
        "EMAIL:bob@test.org\r\n"
        "END:VCARD\r\n"
    )

    def test_import_vcf(self, isolated_db, tmp_path):
        vcf_path = tmp_path / "contacts.vcf"
        vcf_path.write_text(self._SAMPLE_VCF, encoding="utf-8")
        count = _import_vcf(vcf_path)
        assert count == 2

    def test_import_creates_contacts(self, isolated_db, tmp_path):
        from autish.commands.retposto import _load_contacts

        vcf_path = tmp_path / "contacts.vcf"
        vcf_path.write_text(self._SAMPLE_VCF, encoding="utf-8")
        _import_vcf(vcf_path)
        contacts = _load_contacts()
        emails = [c["retposto"] for c in contacts]
        assert "alice@example.com" in emails
        assert "bob@test.org" in emails

    def test_export_vcf(self, isolated_db, tmp_path):
        _upsert_contact("carol@example.com", "Carol Smith", "TestOrg")
        _upsert_contact("dave@example.net", "Dave Jones")
        out_path = tmp_path / "out.vcf"
        count = _export_vcf(out_path)
        assert count == 2
        vcf_text = out_path.read_text(encoding="utf-8")
        assert "carol@example.com" in vcf_text
        assert "dave@example.net" in vcf_text

    def test_export_roundtrip(self, isolated_db, tmp_path):
        from autish.commands.retposto import _load_contacts

        _upsert_contact("eve@example.com", "Eve Original")
        out_path = tmp_path / "roundtrip.vcf"
        _export_vcf(out_path)

        # Clear contacts by reimporting
        _import_vcf(out_path)
        contacts = _load_contacts()
        assert any(c["retposto"] == "eve@example.com" for c in contacts)

    def test_import_missing_email_skipped(self, isolated_db, tmp_path):
        vcf_no_email = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Ghost\r\n"
            "END:VCARD\r\n"
        )
        vcf_path = tmp_path / "noemail.vcf"
        vcf_path.write_text(vcf_no_email, encoding="utf-8")
        count = _import_vcf(vcf_path)
        assert count == 0


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _upsert_contact
# ──────────────────────────────────────────────────────────────────────────────


class TestUpsertContact:
    def test_insert_new(self, isolated_db):
        from autish.commands.retposto import _load_contacts

        _upsert_contact("test@example.com", "Test User")
        contacts = _load_contacts()
        assert len(contacts) == 1
        assert contacts[0]["retposto"] == "test@example.com"
        assert contacts[0]["nomo"] == "Test User"

    def test_update_existing(self, isolated_db):
        from autish.commands.retposto import _load_contacts

        _upsert_contact("test@example.com", "Old Name")
        _upsert_contact("test@example.com", "New Name")
        contacts = _load_contacts()
        assert len(contacts) == 1
        assert contacts[0]["nomo"] == "New Name"

    def test_auto_save_no_name(self, isolated_db):
        from autish.commands.retposto import _load_contacts

        _upsert_contact("auto@example.com")
        contacts = _load_contacts()
        assert any(c["retposto"] == "auto@example.com" for c in contacts)


# ──────────────────────────────────────────────────────────────────────────────
# CLI integration tests — subcommands
# ──────────────────────────────────────────────────────────────────────────────


class TestCliListigiKontojn:
    def test_no_accounts(self, isolated_db):
        result = runner.invoke(app, ["retposto", "listigi-kontojn"])
        assert result.exit_code == 0
        assert "Neniuj" in result.output or "kontoj" in result.output.lower()


class TestCliBloki:
    def test_bloki_command(self, isolated_db):
        result = runner.invoke(app, ["retposto", "bloki", "spam@evil.com"])
        assert result.exit_code == 0
        assert "Blokita" in result.output

    def test_blok_listo(self, isolated_db):
        runner.invoke(app, ["retposto", "bloki", "spam@evil.com"])
        result = runner.invoke(app, ["retposto", "blok-listo"])
        assert result.exit_code == 0
        assert "spam@evil.com" in result.output

    def test_malbloki_command(self, isolated_db):
        runner.invoke(app, ["retposto", "bloki", "toremove@evil.com"])
        result = runner.invoke(app, ["retposto", "malbloki", "toremove@evil.com"])
        assert result.exit_code == 0
        assert "Malblokita" in result.output


class TestCliKontakto:
    def test_listigi_empty(self, isolated_db):
        result = runner.invoke(app, ["retposto", "kontakto", "listigi"])
        assert result.exit_code == 0

    def test_aldoni_contact(self, isolated_db):
        result = runner.invoke(
            app,
            ["retposto", "kontakto", "aldoni", "user@example.com", "-n", "Test User"],
        )
        assert result.exit_code == 0
        assert "savis" in result.output.lower() or "kontakto" in result.output.lower()

    def test_importi_vcf(self, isolated_db, tmp_path):
        vcf_content = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:A\r\nEMAIL:a@test.com\r\nEND:VCARD\r\n"
        )
        vcf_path = tmp_path / "test.vcf"
        vcf_path.write_text(vcf_content)
        result = runner.invoke(
            app, ["retposto", "kontakto", "importi", str(vcf_path)]
        )
        assert result.exit_code == 0
        assert "importis" in result.output.lower()

    def test_eksporti_vcf(self, isolated_db, tmp_path):
        _upsert_contact("export@test.com", "Export User")
        out = tmp_path / "out.vcf"
        result = runner.invoke(
            app, ["retposto", "kontakto", "eksporti", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()


class TestCliFiltro:
    def test_aldoni_filtro(self, isolated_db):
        result = runner.invoke(
            app,
            [
                "retposto", "filtro", "aldoni",
                "test-filter",
                'from contains "spam" => mark-spam',
            ],
        )
        assert result.exit_code == 0
        assert "savis" in result.output.lower()

    def test_listigi_filtroj(self, isolated_db):
        runner.invoke(
            app,
            [
                "retposto", "filtro", "aldoni",
                "myfilter",
                'subject contains "buy" => discard',
            ],
        )
        result = runner.invoke(app, ["retposto", "filtro", "listigi"])
        assert result.exit_code == 0
        assert "myfilter" in result.output

    def test_forigi_filtro(self, isolated_db):
        runner.invoke(
            app,
            [
                "retposto", "filtro", "aldoni",
                "del-filter",
                'from contains "x" => discard',
            ],
        )
        result = runner.invoke(app, ["retposto", "filtro", "forigi", "del-filter"])
        assert result.exit_code == 0
        assert "forigita" in result.output.lower()
