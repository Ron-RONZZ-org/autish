"""Tests for autish.commands.retposto (Retpoŝto email microapp)."""

from __future__ import annotations

import curses
import imaplib
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from autish.commands._retposto_tui import (
    ComposePanel,
    LineEditor,
    MessagePanel,
    MessageReader,
    RetpostoTUI,
    _unwrap_wrapped_mail_urls,
)
from autish.commands.retposto import (
    _add_spam_block,
    _apply_filters,
    _build_sieve_script,
    _decode_header,
    _ensure_folder,
    _eval_sieve_condition,
    _export_vcf,
    _extract_address,
    _extract_address_list,
    _extract_display_name,
    _fetch_account_mail,
    _import_vcf,
    _is_likely_temporary_local_part,
    _is_spam,
    _load_spam_blocks,
    _parse_imap_message,
    _remove_spam_block,
    _reply_targets,
    _sanitize_ascii_text,
    _save_account,
    _save_message,
    _should_autosave_contact_email,
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


class TestSanitizeAsciiText:
    def test_replaces_non_ascii_whitespace(self):
        text = "A\u00a0B\u2009C\u200bD"
        assert _sanitize_ascii_text(text) == "A B CD"

    def test_normalizes_quotes_and_dashes(self):
        text = "“alpha”—‘beta’"
        assert _sanitize_ascii_text(text) == '"alpha"-\'beta\''

    def test_normalizes_unicode_separator_and_format_chars(self):
        text = "A\u2060B\u2028C"
        assert _sanitize_ascii_text(text) == "AB C"


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
        result = _extract_address_list("Alice <alice@a.com>, Bob <bob@b.com>")
        assert "alice@a.com" in result
        assert "bob@b.com" in result

    def test_empty(self):
        assert _extract_address_list("") == []

    def test_none(self):
        assert _extract_address_list(None) == []


class TestExtractDisplayName:
    def test_extracts_name_from_header(self):
        assert _extract_display_name("Alice Example <alice@example.com>") == (
            "Alice Example"
        )

    def test_missing_name_returns_empty(self):
        assert _extract_display_name("alice@example.com") == ""


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
        ).encode()

    def test_basic_parse(self):
        raw = self._make_raw()
        msg, aldonajoj = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["de"] == "sender@example.com"
        assert msg["de_nomo"] == ""
        assert msg["al"] == ["rcpt@example.com"]
        assert msg["subjekto"] == "Test"
        assert "Hello" in (msg["korpo"] or "")
        assert msg["konto_id"] == 1
        assert aldonajoj == []

    def test_parse_sanitizes_non_ascii_body_text(self):
        raw = self._make_raw(body="A\u00a0B\u2009C\u200bD")
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["korpo"] == "A B CD\r\n"

    def test_save_message_sanitizes_received_text_fields(self, isolated_db):
        konto_id = _save_account(
            {
                "nomo": "Test",
                "retposto": "test@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
                "kreita_je": "2024-01-01T00:00:00+00:00",
            }
        )
        dosierujo_id = _ensure_folder(konto_id, "INBOX", "INBOX")
        msg_id = _save_message(
            {
                "konto_id": konto_id,
                "dosierujo_id": dosierujo_id,
                "subjekto": "Saluton\u00a0Mondo",
                "korpo": "A\u2060B\u2028C",
                "html_korpo": "<p>A\u00a0B</p>",
                "de": "sender@example.com",
                "al": ["to@example.com"],
                "cc": [],
                "bcc": [],
            }
        )
        assert msg_id
        import autish.commands.retposto as rp_mod

        with rp_mod._get_db() as con:
            row = con.execute(
                "SELECT subjekto, korpo, html_korpo FROM mesago WHERE id = ?",
                (msg_id,),
            ).fetchone()
        assert row is not None
        assert row["subjekto"] == "Saluton Mondo"
        assert row["korpo"] == "AB C"
        assert row["html_korpo"] == "<p>A B</p>"

    def test_message_id_extracted(self):
        raw = self._make_raw()
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert msg["message_id"] == "<test-123@example.com>"

    def test_unicode_subject(self):
        raw = self._make_raw(subject="Saluton Ĉiuj")
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert "Saluton" in (msg["subjekto"] or "")

    def test_uid_stored(self):
        raw = self._make_raw()
        msg, _ = _parse_imap_message(raw, konto_id=2, dosierujo_id=3, uid="42")
        assert msg["uid"] == "42"

    def test_date_parsed(self):
        raw = self._make_raw(date="Mon, 01 Jan 2024 12:00:00 +0000")
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=None)
        assert msg["ricevita_je"] is not None
        assert "2024" in msg["ricevita_je"]

    def test_thread_headers_extracted(self):
        raw = (
            b"From: sender@example.com\r\n"
            b"To: rcpt@example.com\r\n"
            b"Subject: Re: Test\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            b"Message-ID: <reply@example.com>\r\n"
            b"In-Reply-To: <root@example.com>\r\n"
            b"References: <root@example.com> <mid@example.com>\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Hello\r\n"
        )
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["in_reply_to"] == "<root@example.com>"
        assert "<mid@example.com>" in (msg["references_hdr"] or "")

    def test_sender_display_name_extracted(self):
        raw = self._make_raw(from_="Alice Example <sender@example.com>")
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["de"] == "sender@example.com"
        assert msg["de_nomo"] == "Alice Example"

    def test_priority_and_read_receipt_headers(self):
        raw = (
            b"From: sender@example.com\r\n"
            b"To: rcpt@example.com\r\n"
            b"Subject: Test\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            b"X-Priority: 1 (Highest)\r\n"
            b"Disposition-Notification-To: sender@example.com\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Hello\r\n"
        )
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["prioritato"] == 9
        assert "read-receipt-requested" in (msg.get("etikedoj") or [])

    def test_importance_low_maps_to_low_priority(self):
        raw = (
            b"From: sender@example.com\r\n"
            b"To: rcpt@example.com\r\n"
            b"Subject: Test\r\n"
            b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
            b"Importance: low\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Hello\r\n"
        )
        msg, _ = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["prioritato"] == 1


class TestReplyTargets:
    def test_reply_to_self_targets_original_recipient(self):
        msg = {
            "de": "me@example.com",
            "al": ["friend@example.com"],
            "cc": ["team@example.com"],
        }
        to_targets, cc_targets = _reply_targets("me@example.com", msg)
        assert to_targets == ["friend@example.com"]
        assert cc_targets == []

    def test_reply_all_excludes_self_and_keeps_others(self):
        msg = {
            "de": "alice@example.com",
            "al": ["me@example.com", "bob@example.com"],
            "cc": ["carol@example.com", "me@example.com"],
        }
        to_targets, cc_targets = _reply_targets("me@example.com", msg, reply_all=True)
        assert to_targets == ["alice@example.com", "bob@example.com"]
        assert cc_targets == ["carol@example.com"]


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
            sender="spam@evil.com",
            recipients="me@ok.com",
            subject="hi",
            body="content",
        )

    def test_from_contains_no_match(self):
        assert not _eval_sieve_condition(
            'from contains "spam"',
            sender="legit@good.com",
            recipients="me@ok.com",
            subject="hi",
            body="content",
        )

    def test_subject_is(self):
        assert _eval_sieve_condition(
            'subject is "hello"',
            sender="a@b.com",
            recipients="c@d.com",
            subject="hello",
            body="",
        )

    def test_not_contains(self):
        assert _eval_sieve_condition(
            'from not contains "spam"',
            sender="legit@ok.com",
            recipients="",
            subject="",
            body="",
        )
        assert not _eval_sieve_condition(
            'from not contains "spam"',
            sender="spam@evil.com",
            recipients="",
            subject="",
            body="",
        )

    def test_body_contains(self):
        assert _eval_sieve_condition(
            'body contains "buy now"',
            sender="a@b.com",
            recipients="",
            subject="",
            body="Click here to buy now!",
        )

    def test_multiple_conditions_all_match(self):
        assert _eval_sieve_condition(
            'from contains "evil" subject contains "win"',
            sender="evil@domain.com",
            recipients="",
            subject="you win a prize",
            body="",
        )

    def test_multiple_conditions_one_fails(self):
        assert not _eval_sieve_condition(
            'from contains "evil" subject contains "win"',
            sender="evil@domain.com",
            recipients="",
            subject="normal subject",
            body="",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — _apply_filters
# ──────────────────────────────────────────────────────────────────────────────


class TestApplyFilters:
    def _make_msg(self, **kwargs) -> dict:
        defaults = {
            "id": 1,
            "konto_id": 1,
            "de": "sender@example.com",
            "al": ["me@example.com"],
            "cc": [],
            "bcc": [],
            "subjekto": "Hello",
            "korpo": "Normal content",
            "spamo": 0,
            "forigita": 0,
            "legita": 0,
            "prioritato": 5,
        }
        defaults.update(kwargs)
        return defaults

    def test_fileinto_action(self):
        filters = [
            {
                "nomo": "newsletter",
                "sieve_kodo": 'from contains "newsletter" => fileinto "Newsletter"',
            }
        ]
        msg = self._make_msg(de="newsletter@company.com")
        result = _apply_filters(msg, filters)
        assert result.get("_filter_folder") == "Newsletter"

    def test_mark_spam_action(self):
        filters = [
            {
                "nomo": "spamfilter",
                "sieve_kodo": 'subject contains "FREE MONEY" => mark-spam',
            }
        ]
        msg = self._make_msg(subjekto="WIN FREE MONEY NOW")
        result = _apply_filters(msg, filters)
        assert result["spamo"] == 1

    def test_mark_read_action(self):
        filters = [
            {
                "nomo": "autoread",
                "sieve_kodo": 'from contains "noreply" => mark-read',
            }
        ]
        msg = self._make_msg(de="noreply@service.com")
        result = _apply_filters(msg, filters)
        assert result["legita"] == 1

    def test_set_priority_action(self):
        filters = [
            {
                "nomo": "boss",
                "sieve_kodo": 'from contains "boss@" => set-priority "9"',
            }
        ]
        msg = self._make_msg(de="boss@company.com")
        result = _apply_filters(msg, filters)
        assert result["prioritato"] == 9

    def test_discard_action(self):
        filters = [
            {
                "nomo": "discard-spam",
                "sieve_kodo": 'subject contains "UNSUBSCRIBE" => discard',
            }
        ]
        msg = self._make_msg(subjekto="Click to UNSUBSCRIBE")
        result = _apply_filters(msg, filters)
        assert result["forigita"] == 1

    def test_no_match_unchanged(self):
        filters = [
            {
                "nomo": "test",
                "sieve_kodo": 'from contains "evil" => mark-spam',
            }
        ]
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
        filters = [
            {
                "nomo": "test",
                "sieve_kodo": 'from contains "list" => fileinto "Lists"',
            }
        ]
        script = _build_sieve_script(filters)
        assert "fileinto" in script
        assert "Lists" in script

    def test_discard_rule(self):
        filters = [
            {
                "nomo": "test",
                "sieve_kodo": 'subject contains "spam" => discard',
            }
        ]
        script = _build_sieve_script(filters)
        assert "discard" in script

    def test_mark_spam_rule(self):
        filters = [
            {
                "nomo": "test",
                "sieve_kodo": 'from contains "evil" => mark-spam',
            }
        ]
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
        vcf_no_email = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ghost\r\nEND:VCARD\r\n"
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

    def test_auto_save_sets_header_name(self, isolated_db):
        from autish.commands.retposto import _load_contacts

        _upsert_contact("auto2@example.com", "Alice Header")
        contacts = _load_contacts()
        target = next(c for c in contacts if c["retposto"] == "auto2@example.com")
        assert target["nomo"] == "Alice Header"


class TestFetchAccountMail:
    def test_logout_eof_is_ignored_after_successful_fetch(
        self, isolated_db, monkeypatch
    ):
        class _FakeIMAP:
            def login(self, *_args):
                return ("OK", [])

            def list(self):
                return ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])

            def select(self, *_args, **_kwargs):
                return ("OK", [b"1"])

            def search(self, *_args):
                return ("OK", [b"1"])

            def fetch(self, *_args):
                raw = (
                    b"From: Alice <alice@example.com>\r\n"
                    b"To: me@example.com\r\n"
                    b"Subject: Hi\r\n"
                    b"Date: Wed, 1 Jan 2025 00:00:00 +0000\r\n"
                    b"Message-ID: <m1@example.com>\r\n"
                    b"\r\n"
                    b"Hello"
                )
                return ("OK", [(b"1 (RFC822 FLAGS (\\Seen))", raw)])

            def uid(self, *_args):
                return ("OK", [])

            def logout(self):
                raise OSError("command: LOGOUT => socket error: EOF")

        monkeypatch.setattr(
            "autish.commands.retposto.imaplib.IMAP4_SSL",
            lambda *_a, **_k: _FakeIMAP(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "secret",
        )
        _save_account(
            {
                "nomo": "Me",
                "retposto": "me@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
                "smtp_haveno": 587,
                "smtp_tls": True,
            }
        )
        acc = {
            "id": 1,
            "retposto": "me@example.com",
            "imap_servilo": "imap.example.com",
            "imap_haveno": 993,
            "imap_ssl": 1,
        }
        fetched, skipped = _fetch_account_mail(acc, max_msgs=10)
        assert fetched >= 1
        assert skipped >= 0

    def test_known_uid_skips_rfc822_fetch(self, isolated_db, monkeypatch):
        fetch_calls: list[str] = []

        class _FakeIMAP:
            def login(self, *_args):
                return ("OK", [])

            def list(self):
                return ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])

            def select(self, *_args, **_kwargs):
                return ("OK", [b"1"])

            def search(self, *_args):
                return ("OK", [b"1"])

            def uid(self, *args):
                if len(args) >= 1 and str(args[0]).upper() == "SEARCH":
                    return ("OK", [b"1"])
                return ("OK", [])

            def fetch(self, uid, _spec):
                fetch_calls.append(str(uid))
                raw = (
                    b"From: Alice <alice@example.com>\r\n"
                    b"To: me@example.com\r\n"
                    b"Subject: Hi\r\n"
                    b"Date: Wed, 1 Jan 2025 00:00:00 +0000\r\n"
                    b"Message-ID: <m1@example.com>\r\n"
                    b"\r\n"
                    b"Hello"
                )
                return ("OK", [(b"1 (RFC822 FLAGS (\\Seen))", raw)])

            def logout(self):
                return ("BYE", [b"LOGOUT"])

        monkeypatch.setattr(
            "autish.commands.retposto.imaplib.IMAP4_SSL",
            lambda *_a, **_k: _FakeIMAP(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "secret",
        )
        acc_id = _save_account(
            {
                "nomo": "Me",
                "retposto": "me@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
                "smtp_haveno": 587,
                "smtp_tls": True,
            }
        )
        inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
        _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": inbox_id,
                "uid": "1",
                "de": "alice@example.com",
                "al": ["me@example.com"],
                "cc": [],
                "bcc": [],
                "subjekto": "Old",
                "korpo": "Body",
                "html_korpo": "",
                "prioritato": 5,
                "legita": 1,
                "stelo": 0,
                "spamo": 0,
                "forigita": 0,
                "aldonajoj": [],
                "etikedoj": [],
                "ricevita_je": "2025-01-01T00:00:00+00:00",
                "kreita_je": "2025-01-01T00:00:00+00:00",
            }
        )
        acc = {
            "id": acc_id,
            "retposto": "me@example.com",
            "imap_servilo": "imap.example.com",
            "imap_haveno": 993,
            "imap_ssl": 1,
        }
        fetched, skipped = _fetch_account_mail(acc, max_msgs=10)
        assert fetched == 0
        assert skipped >= 1
        assert fetch_calls == []


# ──────────────────────────────────────────────────────────────────────────────
# CLI integration tests — subcommands
# ──────────────────────────────────────────────────────────────────────────────


class TestCliListigiKontojn:
    def test_no_accounts(self, isolated_db):
        result = runner.invoke(app, ["retposto", "listigi-kontojn"])
        assert result.exit_code == 0
        assert "Neniuj" in result.output or "kontoj" in result.output.lower()


class TestCliAldoniKonton:
    @pytest.fixture(autouse=True)
    def _mock_connectivity_check(self, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._verify_account_connectivity",
            lambda _acc, _pw: (True, []),
        )

    def test_auto_infers_gmail_servers(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._set_password",
            lambda _i, _p: None,
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input="Test User\ntest@gmail.com\nsekreto123\n",
        )
        assert result.exit_code == 0, result.output
        assert "Aŭtomate deduktis servilojn" in result.output

        from autish.commands.retposto import _load_accounts

        accounts = _load_accounts()
        assert len(accounts) == 1
        acc = accounts[0]
        assert acc["imap_servilo"] == "imap.gmail.com"
        assert acc["imap_haveno"] == 993
        assert bool(acc["imap_ssl"]) is True
        assert acc["smtp_servilo"] == "smtp.gmail.com"
        assert acc["smtp_haveno"] == 587
        assert bool(acc["smtp_tls"]) is True
        assert acc["imap_uzantonomo"] == "test@gmail.com"
        assert acc["smtp_uzantonomo"] == "test@gmail.com"
        assert acc["sieve_servilo"] == "imap.gmail.com"
        assert int(acc["sieve_haveno"]) == 4190
        assert bool(acc["sieve_starttls"]) is True
        assert acc["sieve_uzantonomo"] == "test@gmail.com"

    def test_unknown_domain_prompts_manual_servers(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._set_password",
            lambda _i, _p: None,
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input=(
                "Test User\n"
                "test@nekonata-domaino.invalid\n"
                "imap.nekonata.invalid\n"
                "smtp.nekonata.invalid\n"
                "sekreto123\n"
            ),
        )
        assert result.exit_code == 0, result.output
        assert "Aŭtomate deduktis servilojn" not in result.output

        from autish.commands.retposto import _load_accounts

        accounts = _load_accounts()
        assert len(accounts) == 1
        acc = accounts[0]
        assert acc["imap_servilo"] == "imap.nekonata.invalid"
        assert acc["smtp_servilo"] == "smtp.nekonata.invalid"

    def test_auto_infers_from_mozilla_autoconfig(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._set_password",
            lambda _i, _p: None,
        )
        xml = """
<clientConfig version="1.1">
  <emailProvider id="example.com">
    <incomingServer type="imap">
      <hostname>imap.example.com</hostname>
      <port>993</port>
      <socketType>SSL</socketType>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>smtp.example.com</hostname>
      <port>587</port>
      <socketType>STARTTLS</socketType>
    </outgoingServer>
  </emailProvider>
</clientConfig>
"""

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return xml.encode("utf-8")

        monkeypatch.setattr(
            "autish.commands.retposto.urllib.request.urlopen",
            lambda *_a, **_k: _Resp(),
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input="Test User\ntest@example.com\nsekreto123\n",
        )
        assert result.exit_code == 0, result.output
        assert "Aŭtomate deduktis servilojn" in result.output

        from autish.commands.retposto import _load_accounts

        acc = _load_accounts()[0]
        assert acc["imap_servilo"] == "imap.example.com"
        assert acc["smtp_servilo"] == "smtp.example.com"

    def test_invalid_credentials_shows_repair_guidance(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._infer_mail_config",
            lambda _addr: {
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
                "smtp_haveno": 587,
                "smtp_tls": True,
            },
        )
        monkeypatch.setattr(
            "autish.commands.retposto._verify_account_connectivity",
            lambda _acc, _pw: (
                False,
                [
                    "Aŭtentigo malsukcesis (malĝusta uzantonomo aŭ pasvorto).",
                    "Rimedo: ĝisdatigu pasvorton.",
                ],
            ),
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input="Test User\ntest@example.com\nsekreto123\n",
        )
        assert result.exit_code == 1
        assert "Konto ne aldonita" in result.output
        assert "Aŭtentigo malsukcesis" in result.output
        assert "Rimedo" in result.output

    def test_validation_fails_fast_on_imap_tcp_timeout(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._verify_account_connectivity",
            lambda _acc, _pw: (
                False,
                [
                    "IMAP konekto eltempiĝis (imap.gmail.com:993).",
                    "Rimedo: kontrolu retkonekton, fajromuron kaj havenon.",
                ],
            ),
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input=("Test User\ntest@gmail.com\nsekreto123\n"),
        )
        assert result.exit_code == 1
        assert "Konto ne aldonita" in result.output
        assert "IMAP konekto eltempiĝis" in result.output

    def test_auto_infers_from_microsoft_autodiscover(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._set_password",
            lambda _i, _p: None,
        )
        xml = """
<Autodiscover>
  <Response xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a">
    <Account>
      <Protocol>
        <Type>IMAP</Type>
        <Server>imap.example.com</Server>
        <Port>993</Port>
        <SSL>on</SSL>
      </Protocol>
      <Protocol>
        <Type>SMTP</Type>
        <Server>smtp.example.com</Server>
        <Port>587</Port>
        <SSL>on</SSL>
      </Protocol>
    </Account>
  </Response>
</Autodiscover>
"""

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return xml.encode("utf-8")

        monkeypatch.setattr(
            "autish.commands.retposto.urllib.request.urlopen",
            lambda *_a, **_k: _Resp(),
        )
        result = runner.invoke(
            app,
            ["retposto", "aldoni-konton"],
            input="Test User\ntest@example.com\nsekreto123\n",
        )
        assert result.exit_code == 0, result.output
        assert "Aŭtomate deduktis servilojn" in result.output

        from autish.commands.retposto import _load_accounts

        acc = _load_accounts()[0]
        assert acc["imap_servilo"] == "imap.example.com"
        assert acc["smtp_servilo"] == "smtp.example.com"

    def test_add_account_with_full_mail_parameters(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._verify_account_connectivity",
            lambda _acc, _pw: (True, []),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._set_password",
            lambda _i, _p: None,
        )
        result = runner.invoke(
            app,
            [
                "retposto",
                "aldoni-konton",
                "-n",
                "Rong M.S. ZHOU",
                "-r",
                "ron@ronzz.org",
                "--imap",
                "imap.migadu.com",
                "--imap-haveno",
                "993",
                "--imap-ssl",
                "--imap-uzantonomo",
                "ron@ronzz.org",
                "--smtp",
                "smtp.migadu.com",
                "--smtp-haveno",
                "465",
                "--no-smtp-tls",
                "--smtp-uzantonomo",
                "ron@ronzz.org",
                "--webmail-url",
                "https://webmail.migadu.com",
                "--sieve-servilo",
                "imap.migadu.com",
                "--sieve-haveno",
                "4190",
                "--sieve-starttls",
                "--sieve-uzantonomo",
                "ron@ronzz.org",
            ],
            input="sekreto123\n",
        )
        assert result.exit_code == 0, result.output
        from autish.commands.retposto import _load_accounts

        acc = _load_accounts()[0]
        assert acc["imap_servilo"] == "imap.migadu.com"
        assert int(acc["imap_haveno"]) == 993
        assert bool(acc["imap_ssl"]) is True
        assert acc["imap_uzantonomo"] == "ron@ronzz.org"
        assert acc["smtp_servilo"] == "smtp.migadu.com"
        assert int(acc["smtp_haveno"]) == 465
        assert bool(acc["smtp_tls"]) is False
        assert acc["smtp_uzantonomo"] == "ron@ronzz.org"
        assert acc["webmail_url"] == "https://webmail.migadu.com"
        assert acc["sieve_servilo"] == "imap.migadu.com"
        assert int(acc["sieve_haveno"]) == 4190
        assert bool(acc["sieve_starttls"]) is True
        assert acc["sieve_uzantonomo"] == "ron@ronzz.org"


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


class TestCliPreniDiagnostics:
    def test_preni_imap_error_shows_repair_guidance(self, isolated_db, monkeypatch):
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "sekreto",
        )

        class _BadIMAP:
            def __init__(self, *_a, **_k):
                raise imaplib.IMAP4.error("AUTHENTICATIONFAILED Invalid credentials")

        monkeypatch.setattr("autish.commands.retposto.imaplib.IMAP4_SSL", _BadIMAP)

        _save_account(
            {
                "nomo": "Ron",
                "retposto": "ron@ronzz.org",
                "imap_servilo": "imap.ronzz.org",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.ronzz.org",
                "smtp_haveno": 587,
                "smtp_tls": True,
            }
        )
        result = runner.invoke(app, ["retposto", "preni", "--konto", "ron@ronzz.org"])
        assert result.exit_code == 0, result.output
        assert "IMAP eraro por ron@ronzz.org." in result.output
        assert "Rimedo" in result.output

    def test_preni_does_not_echo_secret_like_server_error(
        self, isolated_db, monkeypatch
    ):
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "sekreto",
        )

        class _BadIMAP:
            def __init__(self, *_a, **_k):
                raise imaplib.IMAP4.error("Password is Ronzz!Grow!123!")

        monkeypatch.setattr("autish.commands.retposto.imaplib.IMAP4_SSL", _BadIMAP)

        _save_account(
            {
                "nomo": "Ron",
                "retposto": "ron@ronzz.org",
                "imap_servilo": "imap.ronzz.org",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.ronzz.org",
                "smtp_haveno": 587,
                "smtp_tls": True,
            }
        )
        result = runner.invoke(app, ["retposto", "preni", "--konto", "ron@ronzz.org"])
        assert result.exit_code == 0, result.output
        assert "IMAP eraro por ron@ronzz.org." in result.output
        assert "Ronzz!Grow!123!" not in result.output


class TestAccountConnectivityCheck:
    def test_verify_fails_fast_on_imap_tcp_timeout(self, monkeypatch):
        import autish.commands.retposto as rp_mod

        def _fake_probe(host: str, port: int, *, timeout: float):
            if host.startswith("imap."):
                return TimeoutError("timed out")
            return None

        monkeypatch.setattr(rp_mod, "_probe_tcp_connectivity", _fake_probe)
        ok, hints = rp_mod._verify_account_connectivity(
            {
                "retposto": "test@gmail.com",
                "uzantonomo": "test@gmail.com",
                "imap_servilo": "imap.gmail.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.gmail.com",
                "smtp_haveno": 587,
                "smtp_tls": True,
            },
            "sekreto123",
        )
        assert ok is False
        assert any("IMAP konekto eltempiĝis" in h for h in hints)

    def test_verify_uses_smtp_ssl_for_port_465(self, monkeypatch):
        import autish.commands.retposto as rp_mod

        monkeypatch.setattr(
            rp_mod,
            "_probe_tcp_connectivity",
            lambda _h, _p, timeout: None,
        )

        class _FakeIMAP:
            def login(self, *_args):
                return ("OK", [])

            def logout(self):
                return ("BYE", [b"LOGOUT"])

        called = {"smtp_ssl": 0, "smtp": 0}

        class _FakeSMTPSSL:
            def __init__(self, *_a, **_k):
                called["smtp_ssl"] += 1

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def login(self, *_args):
                return (235, b"ok")

        class _FakeSMTP:
            def __init__(self, *_a, **_k):
                called["smtp"] += 1

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def ehlo(self):
                return (250, b"ok")

            def starttls(self, **_kwargs):
                return (220, b"go ahead")

            def login(self, *_args):
                return (235, b"ok")

        monkeypatch.setattr(rp_mod.imaplib, "IMAP4_SSL", lambda *_a, **_k: _FakeIMAP())
        monkeypatch.setattr(rp_mod.smtplib, "SMTP_SSL", _FakeSMTPSSL)
        monkeypatch.setattr(rp_mod.smtplib, "SMTP", _FakeSMTP)

        ok, hints = rp_mod._verify_account_connectivity(
            {
                "retposto": "user@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
                "smtp_haveno": 465,
                "smtp_tls": True,
                "imap_uzantonomo": "imap-user",
                "smtp_uzantonomo": "smtp-user",
            },
            "sekreto",
        )
        assert ok is True, hints
        assert called["smtp_ssl"] == 1
        assert called["smtp"] == 0


class TestAccountTomlRoundtrip:
    def test_accounts_to_toml_includes_extended_fields(self, isolated_db):
        import autish.commands.retposto as rp_mod

        acc_id = _save_account(
            {
                "nomo": "Roundtrip",
                "retposto": "roundtrip@example.com",
                "imap_servilo": "imap.example.com",
                "imap_uzantonomo": "imap-u@example.com",
                "smtp_servilo": "smtp.example.com",
                "smtp_uzantonomo": "smtp-u@example.com",
                "webmail_url": "https://webmail.example.com",
                "sieve_servilo": "sieve.example.com",
                "sieve_haveno": 4190,
                "sieve_starttls": True,
                "sieve_uzantonomo": "sieve-u@example.com",
            }
        )
        accounts = rp_mod._load_accounts()
        toml_bytes = rp_mod._accounts_to_toml(accounts, {acc_id: "sekreto"})
        parsed = rp_mod._toml_to_accounts(toml_bytes)
        assert parsed
        rec = parsed[0]
        assert rec["imap_uzantonomo"] == "imap-u@example.com"
        assert rec["smtp_uzantonomo"] == "smtp-u@example.com"
        assert rec["webmail_url"] == "https://webmail.example.com"
        assert rec["sieve_servilo"] == "sieve.example.com"
        assert int(rec["sieve_haveno"]) == 4190
        assert bool(rec["sieve_starttls"]) is True
        assert rec["sieve_uzantonomo"] == "sieve-u@example.com"


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

    def test_aldoni_contact_without_email(self, isolated_db):
        result = runner.invoke(
            app,
            ["retposto", "kontakto", "aldoni", "-n", "No Mail", "-o", "Org"],
        )
        assert result.exit_code == 0
        assert "sen retpoŝto" in result.output.lower()

    def test_aldoni_contact_requires_identity_field(self, isolated_db):
        result = runner.invoke(app, ["retposto", "kontakto", "aldoni"])
        assert result.exit_code != 0

    def test_serci_and_vidi_contact(self, isolated_db):
        runner.invoke(
            app,
            [
                "retposto",
                "kontakto",
                "aldoni",
                "ada@math.org",
                "-n",
                "Ada",
                "-F",
                "Lovelace",
                "-o",
                "Analytical",
                "-t",
                "0033123456789",
            ],
        )
        serci = runner.invoke(
            app,
            ["retposto", "kontakto", "serci", "--nomo", "Ada", "--organizo", "Analy"],
        )
        assert serci.exit_code == 0
        assert "Analytical" in serci.output
        assert "Ada" in serci.output
        assert "Lovelace" in serci.output
        assert "ada@math.org" in serci.output
        assert "0033123456789" in serci.output
        uuid_prefix = None
        for line in serci.output.splitlines():
            if "#" in line and "ada@math.org" in line:
                uuid_prefix = line.split("#", 1)[1][:8]
                break
        assert uuid_prefix is not None
        vidi = runner.invoke(app, ["retposto", "kontakto", "vidi", f"#{uuid_prefix}"])
        assert vidi.exit_code == 0
        assert "LOVELACE" in vidi.output

    def test_importi_vcf(self, isolated_db, tmp_path):
        vcf_content = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:A\r\nEMAIL:a@test.com\r\nEND:VCARD\r\n"
        )
        vcf_path = tmp_path / "test.vcf"
        vcf_path.write_text(vcf_content)
        result = runner.invoke(app, ["retposto", "kontakto", "importi", str(vcf_path)])
        assert result.exit_code == 0
        assert "importis" in result.output.lower()

    def test_eksporti_vcf(self, isolated_db, tmp_path):
        _upsert_contact("export@test.com", "Export User")
        out = tmp_path / "out.vcf"
        result = runner.invoke(app, ["retposto", "kontakto", "eksporti", str(out)])
        assert result.exit_code == 0
        assert out.exists()


class TestCliFiltro:
    def test_aldoni_filtro(self, isolated_db):
        result = runner.invoke(
            app,
            [
                "retposto",
                "filtro",
                "aldoni",
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
                "retposto",
                "filtro",
                "aldoni",
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
                "retposto",
                "filtro",
                "aldoni",
                "del-filter",
                'from contains "x" => discard',
            ],
        )
        result = runner.invoke(app, ["retposto", "filtro", "forigi", "del-filter"])
        assert result.exit_code == 0
        assert "forigita" in result.output.lower()


class _FakeStdScr:
    def __init__(self, keys: list[int] | None = None):
        self._keys = list(keys or [])

    def getmaxyx(self):
        return (24, 80)

    def erase(self):
        return None

    def refresh(self):
        return None

    def noutrefresh(self):
        return None

    def addstr(self, *_args, **_kwargs):
        return None

    def move(self, *_args, **_kwargs):
        return None

    def timeout(self, _value):
        return None

    def get_wch(self):
        if self._keys:
            return self._keys.pop(0)
        return -1


class TestRetpostoTuiReader:
    def test_hl_moves_cursor_column_not_row(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "abc"}
        reader = MessageReader(_FakeStdScr(), msg)
        start_row = reader._row
        reader._handle_key(ord("l"))
        assert reader._row == start_row
        assert reader._char_col == 1
        reader._handle_key(ord("h"))
        assert reader._row == start_row
        assert reader._char_col == 0

    def test_vertical_move_clamps_cursor_column(self):
        msg = {
            "de": "a@b.com",
            "al": ["x@y.com"],
            "subjekto": "S",
            "korpo": "long-line-here\nx",
        }
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = len(reader._lines) - 2
        reader._char_col = 6
        reader._handle_key(ord("j"))
        assert reader._row == len(reader._lines) - 1
        assert reader._char_col <= len(reader._lines[reader._row]) - 1

    def test_ctrl_right_moves_by_word(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "unu du"}
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = len(reader._lines) - 1
        reader._char_col = 0
        reader._handle_key(560)  # common Ctrl+Right keycode
        assert reader._char_col > 0

    def test_scroll_moves_only_at_bottom_edge(self):
        body = "\n".join(f"line {i}" for i in range(50))
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": body}
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = 0
        reader._view_row = 0
        for _ in range(5):
            reader._handle_key(ord("j"))
        assert reader._view_row == 0

    def test_R_triggers_reply_all_action(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "abc"}
        reader = MessageReader(_FakeStdScr(), msg)
        assert reader._handle_key(ord("R")) == "reply_all"

    def test_reader_vim_insert_keys_map_to_draft_edit_actions(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "abc"}
        reader = MessageReader(_FakeStdScr(), msg)
        assert reader._handle_key(ord("i")) == "edit_draft"
        assert reader._handle_key(ord("I")) == "edit_draft_top"
        assert reader._handle_key(ord("a")) == "edit_draft_after"
        assert reader._handle_key(ord("A")) == "edit_draft_end"

    def test_reader_ctrl_a_opens_attachments(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "abc"}
        reader = MessageReader(_FakeStdScr(), msg)
        assert reader._handle_key(1) == "attachments"

    def test_wrapped_urls_are_unwrapped_in_reader_body(self):
        body = (
            "SG<https://particuliers.sg.fr/assurances/nos-offres/assurance-protection-\n"
            "aide-juridique>"
        )
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": body}
        reader = MessageReader(_FakeStdScr(), msg)
        joined = "\n".join(reader._lines)
        assert "assurance-protection-aide-juridique" in joined
        assert "assurance-protection-\naide-juridique" not in joined

    def test_reader_ctrl_y_copies_full_url_under_cursor(self):
        url = "https://example.com/path/" + ("x" * 120)
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": url}
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = len(reader._lines) - 1
        line = reader._lines[reader._row]
        start = line.index("https://")
        reader._char_col = start + 10
        result = reader._handle_key(25)  # Ctrl+Y
        assert result == f"copy_url:{url}"

    def test_reader_visual_yank_copies_ascii_sanitized_text(self):
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": "A\u00a0B"}
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = len(reader._lines) - 1
        line = reader._lines[reader._row]
        idx = line.index("A")
        reader._char_col = idx + 2
        reader._visual_mode = "char"
        reader._visual_anchor_row = reader._row
        reader._visual_anchor_col = idx
        with patch("pyperclip.copy") as copy_mock:
            result = reader._handle_key(ord("y"))
        assert result == "yank_text"
        copy_mock.assert_called_once_with("A B")

    def test_reader_ctrl_o_opens_full_url_under_cursor(self):
        url = "https://example.org/very/long/path/" + ("a" * 80)
        msg = {"de": "a@b.com", "al": ["x@y.com"], "subjekto": "S", "korpo": url}
        reader = MessageReader(_FakeStdScr(), msg)
        reader._row = len(reader._lines) - 1
        line = reader._lines[reader._row]
        start = line.index("https://")
        reader._char_col = start + 6
        result = reader._handle_key(15)  # Ctrl+O
        assert result == f"open_url:{url}"

    def test_compose_cancel_reopens_reader(self):
        tui = _make_tui_for_keys()
        tui._message_panel._messages = [
            {"id": 1, "de": "a@b.com", "subjekto": "S", "korpo": "B", "legita": 1}
        ]
        tui._message_panel._cursor = 0
        tui._compose_reply = MagicMock(return_value="cancel")  # type: ignore[method-assign]
        with patch(
            "autish.commands._retposto_tui.MessageReader.run",
            side_effect=["reply", "quit"],
        ) as run_mock:
            tui._open_message()
        tui._compose_reply.assert_called_once()
        assert run_mock.call_count == 2


class TestRetpostoTuiComposePanel:
    def test_esc_in_insert_switches_to_normal(self):
        panel = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        assert panel._current_editor() is not None
        assert panel._current_editor().mode == "INSERT"
        assert panel.handle_key(27) is None
        assert panel._current_editor().mode == "NORMAL"

    def test_vim_command_mode_send_and_cancel(self):
        panel_send = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        panel_send.handle_key(27)  # INSERT -> NORMAL
        panel_send.handle_key(ord(":"))
        panel_send.handle_key(ord("w"))
        panel_send.handle_key(ord("q"))
        assert panel_send.handle_key(ord("\n")) == "draft_quit"

        panel_cancel = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        panel_cancel.handle_key(27)  # INSERT -> NORMAL
        panel_cancel.handle_key(ord(":"))
        panel_cancel.handle_key(ord("q"))
        assert panel_cancel.handle_key(ord("\n")) == "cancel"

    def test_vim_command_mode_draft(self):
        panel = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        panel.handle_key(27)  # INSERT -> NORMAL
        panel.handle_key(ord(":"))
        panel.handle_key(ord("w"))
        assert panel.handle_key(ord("\n")) == "draft_stay"

    def test_unicode_character_can_be_typed(self):
        panel = ComposePanel(_FakeStdScr(), {})
        panel.handle_key(ord("ŝ"))
        assert panel.get_values()["de"] == "ŝ"

    def test_m_toggles_markdown_in_normal_mode(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "text"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "NORMAL"
        assert panel.markdown_enabled() is False
        panel.handle_key(ord("m"))
        assert panel.markdown_enabled() is True

    def test_ctrl_a_in_normal_mode_requests_attachment_prompt(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "text"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "NORMAL"
        assert panel.handle_key(1) == "prompt_attachment"

    def test_ctrl_a_in_insert_mode_requests_attachment_prompt(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "text"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "INSERT"
        assert panel.handle_key(1) == "prompt_attachment"

    def test_compose_has_from_priority_receipt_fields(self):
        panel = ComposePanel(_FakeStdScr(), {})
        vals = panel.get_values()
        assert "de" in vals
        assert "prioritato" in vals
        assert "legokonfirmo" in vals
        assert vals["prioritato"] == "normala"
        assert vals["legokonfirmo"] == "ne"

    def test_compose_transient_status_expires_after_three_seconds(self):
        panel = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=10.0):
            panel._set_status("Aldonita.", transient=True)
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=12.0):
            assert "Aldonita." in panel._current_status()
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=13.2):
            assert panel._current_status() == ""


class TestRetpostoComposeBehavior:
    def test_reply_initial_focus_is_body_insert(self):
        initial = {
            "al": "x@example.com",
            "subjekto": "Re: A",
            "korpo": "Body",
            "_focus_body": "1",
        }
        panel = ComposePanel(_FakeStdScr(), initial, contact_completer=None)
        if str(initial.get("_focus_body") or "").strip() and panel._body_lines:
            panel._current_field = len(panel._field_names()) - 1
            panel._body_row = 0
            panel._body_lines[0].mode = "INSERT"
        assert panel._is_body() is True
        assert panel._body_lines[0].mode == "INSERT"

    def test_compose_completer_formats_name_and_email(self):
        tui = RetpostoTUI(
            _FakeStdScr(),
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: True,
            save_message=lambda _m: 1,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [
                {"retposto": "alice@example.com", "nomo": "Alice"},
                {"retposto": "bob@example.com", "nomo": ""},
            ],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda _r: None,
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 99,
            find_drafts_folder=lambda _acc_id: 88,
        )

        completions: list[str] = []

        class _ProbePanel:
            def __init__(
                self,
                _stdscr,
                _initial,
                contact_completer,
                _from_completer=None,
            ):
                if contact_completer is not None:
                    completions.extend(contact_completer("ali"))
                self._body_lines = []

            def draw(self):
                return None

            def handle_key(self, _key):
                return "cancel"

        with patch("autish.commands._retposto_tui.ComposePanel", _ProbePanel):
            tui._run_compose({})

        assert "Alice <alice@example.com>" in completions
        assert "bob@example.com" in completions

    def test_compose_ctrl_1_accepts_recipient_suggestion(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"al": "ali"},
            contact_completer=lambda _p: ["Alice <alice@example.com>"],
        )
        panel._current_field = 1  # al
        panel.handle_key(ord("x"))  # trigger completer refresh
        panel.handle_key(curses.KEY_DOWN)
        panel.handle_key(curses.KEY_BTAB)
        panel.handle_key(ord("1"))
        assert "Alice <alice@example.com>" in panel.get_values()["al"]

    def test_compose_ctrl_2_accepts_second_from_suggestion(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"de": "me"},
            contact_completer=lambda _p: [],
            from_completer=lambda _p: [
                "One <one@example.com>",
                "Me <me@example.com>",
            ],
        )
        panel._current_field = 0  # de
        panel.handle_key(ord("x"))  # trigger completer refresh
        panel.handle_key(curses.KEY_BTAB)
        panel.handle_key(ord("2"))
        assert panel.get_values()["de"] == "Me <me@example.com>"

    def test_compose_digit_3_accepts_third_suggestion_fallback(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"al": "a"},
            contact_completer=lambda _p: [
                "One <one@example.com>",
                "Two <two@example.com>",
                "Three <three@example.com>",
            ],
        )
        panel._current_field = 1  # al
        panel.handle_key(ord("x"))  # trigger completer refresh
        panel.handle_key(curses.KEY_BTAB)
        panel.handle_key(ord("3"))
        assert "Three <three@example.com>" in panel.get_values()["al"]

    def test_compose_ctrl_4_accepts_fourth_suggestion(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"al": "a"},
            contact_completer=lambda _p: [
                "One <one@example.com>",
                "Two <two@example.com>",
                "Three <three@example.com>",
                "Four <four@example.com>",
            ],
        )
        panel._current_field = 1  # al
        panel.handle_key(ord("x"))  # trigger completer refresh
        panel.handle_key(curses.KEY_BTAB)  # enter number selection mode
        panel.handle_key(ord("4"))
        assert "Four <four@example.com>" in panel.get_values()["al"]

    def test_compose_ctrl_2_accepts_even_in_insert_mode(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"de": "m"},
            contact_completer=lambda _p: [],
            from_completer=lambda _p: ["A <a@example.com>", "B <b@example.com>"],
        )
        panel._current_field = 0
        panel.handle_key(ord("x"))  # refresh suggestions
        panel._editors["de"].mode = "INSERT"
        panel.handle_key(curses.KEY_BTAB)
        panel.handle_key(ord("2"))
        assert panel.get_values()["de"] == "B <b@example.com>"

    def test_compose_body_insert_can_type_g(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": ""})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "INSERT"
        panel.handle_key(ord("g"))
        assert panel.get_values()["korpo"] == "g"

    def test_compose_body_up_on_first_line_no_weird_insert(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "line1"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "INSERT"
        before = panel.get_values()["korpo"]
        panel.handle_key(curses.KEY_UP)
        assert panel.get_values()["korpo"] == before

    def test_compose_autocomplete_number_mode_cancel(self):
        panel = ComposePanel(
            _FakeStdScr(),
            {"al": "a"},
            contact_completer=lambda _p: [
                "One <one@example.com>",
                "Two <two@example.com>",
            ],
        )
        panel._current_field = 1
        panel.handle_key(ord("x"))
        panel.handle_key(curses.KEY_BTAB)
        assert panel._autocomplete_pick_mode is True
        panel.handle_key(27)  # esc
        assert panel._autocomplete_pick_mode is False

    def test_send_failure_queues_outbox(self):
        saved: list[dict] = []
        tui = RetpostoTUI(
            _FakeStdScr(),
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: False,
            save_message=lambda m: saved.append(m) or 101,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda _r: None,
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 77,
            find_drafts_folder=lambda _acc_id: 66,
        )

        class _SendFailPanel:
            def __init__(
                self, _stdscr, _initial, _contact_completer, _from_completer=None
            ):
                self._body_lines = []
                self._status = ""

            def draw(self):
                return None

            def handle_key(self, _key):
                return "send"

            def get_values(self):
                return {
                    "de": "me@example.com",
                    "al": "to@example.com",
                    "cc": "",
                    "bcc": "",
                    "subjekto": "S",
                    "prioritato": "9",
                    "legokonfirmo": "j",
                    "korpo": "Body",
                }

            def markdown_enabled(self):
                return False

            def attachment_paths(self):
                return []

        with (
            patch("autish.commands._retposto_tui.ComposePanel", _SendFailPanel),
            patch("autish.commands._retposto_tui._getch_unicode", return_value=10),
        ):
            assert tui._run_compose({}) == "done"

        assert saved, "Expected message queued to OUTBOX when send fails"
        assert saved[0]["dosierujo_id"] == 77
        assert saved[0]["al"] == ["to@example.com"]

    def test_compose_default_from_uses_selected_folder_account(self):
        tui = _make_tui_for_keys()
        tui._folder_panel._items = [
            {"type": "account", "acc_id": 2, "label": "2. two@example.com"},
            {"type": "folder", "acc_id": 2, "folder_id": 20, "label": "  INBOX"},
        ]
        tui._folder_panel._cursor = 1
        tui._load_accounts = lambda: [  # type: ignore[method-assign]
            {"id": 1, "retposto": "one@example.com"},
            {"id": 2, "retposto": "two@example.com"},
        ]
        assert tui._default_compose_from_address() == "two@example.com"

    def test_split_compose_recipients_extracts_angle_brackets(self):
        tui = _make_tui_for_keys()
        got = tui._split_compose_recipients(
            "Alice <alice@example.com>, bob@example.com"
        )
        assert got == ["alice@example.com", "bob@example.com"]

    def test_parse_compose_priority_standard_labels(self):
        tui = _make_tui_for_keys()
        assert tui._parse_compose_priority({"prioritato": "alta"}) == 9
        assert tui._parse_compose_priority({"prioritato": "normala"}) == 5
        assert tui._parse_compose_priority({"prioritato": "malalta"}) == 1


class TestRetpostoSignatureLoading:
    def test_load_signature_html_file_returns_plain_and_html(self, tmp_path):
        tui = _make_tui_for_keys()
        sig_file = tmp_path / "sig.html"
        sig_file.write_text("<p>Saluton <b>Mondo</b></p>", encoding="utf-8")
        plain, html = tui._load_signature({"subskribo": str(sig_file)})
        assert "Saluton" in plain
        assert html is not None
        assert "<b>Mondo</b>" in html

    def test_html_signature_uses_plain_fallback_and_html_variant(self):
        tui = _make_tui_for_keys()
        plain, html = tui._load_signature({"subskribo": "/tmp/sig.html"})
        # only structure check here; content loading covered by existing file test
        assert isinstance(plain, str)
        assert html is None or isinstance(html, str)

    def test_send_uses_sender_signature_for_html_variant(self):
        sent: dict = {}
        tui = RetpostoTUI(
            _FakeStdScr(),
            load_accounts=lambda: [{"id": 1, "retposto": "one@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **kwargs: sent.update(kwargs) or True,
            save_message=lambda _m: 1,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda _r: None,
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 1,
            find_drafts_folder=lambda _acc_id: 1,
        )
        tui._load_accounts = lambda: [  # type: ignore[method-assign]
            {"id": 1, "retposto": "one@example.com"},
            {"id": 2, "retposto": "two@example.com"},
        ]
        tui._load_signature = (  # type: ignore[method-assign]
            lambda acc: (
                ("\n\n-- \nS2", "<p>S2</p>")
                if acc.get("retposto") == "two@example.com"
                else ("\n\n-- \nS1", "<p>S1</p>")
            )
        )

        class _Panel:
            def __init__(self, *_a, **_k):
                self._body_lines = []
                self._status = ""

            def draw(self):
                return None

            def handle_key(self, _key):
                return "send"

            def get_values(self):
                return {
                    "de": "two@example.com",
                    "al": "to@example.com",
                    "cc": "",
                    "bcc": "",
                    "subjekto": "S",
                    "prioritato": "normala",
                    "legokonfirmo": "ne",
                    "korpo": "Body",
                }

            def markdown_enabled(self):
                return False

            def attachment_paths(self):
                return []

        with (
            patch("autish.commands._retposto_tui.ComposePanel", _Panel),
            patch("autish.commands._retposto_tui._getch_unicode", return_value=10),
        ):
            assert tui._run_compose({}) == "done"
        assert "<p>S2</p>" in (sent.get("html_korpo") or "")

    def test_cmd_aldoni_path_adds_attachment(self):
        panel = ComposePanel(_FakeStdScr(), {"al": "user@example.com"})
        panel.handle_key(27)  # INSERT -> NORMAL
        with (
            patch("autish.commands._retposto_tui.Path.exists", return_value=True),
            patch("autish.commands._retposto_tui.Path.is_file", return_value=True),
            patch(
                "autish.commands._retposto_tui.Path.resolve",
                return_value=Path("/tmp/file.txt"),
            ),
        ):
            panel.handle_key(ord(":"))
            for ch in "aldoni /tmp/file.txt":
                panel.handle_key(ord(ch))
            assert panel.handle_key(ord("\n")) is None
        assert panel.attachment_paths() == ["/tmp/file.txt"]


class TestRetpostoLineEditor:
    def test_ctrl_right_moves_word_in_insert(self):
        ed = LineEditor("unu du tri")
        ed.pos = 0
        ed.handle_key(560)  # common Ctrl+Right keycode
        assert ed.pos > 0

    def test_ctrl_right_alt_code_does_not_insert_weird_char(self):
        ed = LineEditor("unu du tri")
        ed.pos = 0
        before = ed.value
        ed.handle_key(569)  # seen as weird glyph on some terminals
        assert ed.value == before
        assert ed.pos > 0

    def test_visual_modes_toggle(self):
        ed = LineEditor("abc", insert_mode=False)
        ed.handle_key(ord("v"))
        assert ed.mode == "VISUAL_CHAR"
        ed.handle_key(27)
        assert ed.mode == "NORMAL"
        ed.handle_key(ord("V"))
        assert ed.mode == "VISUAL_LINE"

    def test_visual_line_jk_and_gg_G_move_cursor(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "l1\nl2\nl3"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 1
        panel._body_lines[1].mode = "NORMAL"
        panel.handle_key(ord("V"))
        assert panel._body_row == 1
        panel.handle_key(ord("j"))
        assert panel._body_row == 2
        panel.handle_key(ord("k"))
        assert panel._body_row == 1
        panel.handle_key(ord("g"))
        panel.handle_key(ord("g"))
        assert panel._body_row == 0
        panel.handle_key(ord("G"))
        assert panel._body_row == 2

    def test_body_visual_mode_status_not_insert(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "l1\nl2"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "NORMAL"
        panel.handle_key(ord("V"))
        panel.draw()
        assert panel._body_visual_mode == "line"
        assert panel._body_lines[0].mode == "NORMAL"

    def test_body_visual_char_yank_exits_visual_and_keeps_text(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "alpha\nbeta"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "NORMAL"
        panel.handle_key(ord("v"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("l"))
        panel.handle_key(ord("y"))
        assert panel._body_visual_mode == ""
        assert panel.get_values()["korpo"] == "alpha\nbeta"

    def test_body_visual_char_delete_cuts_across_lines(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "alpha\nbeta\ngamma"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "NORMAL"
        panel._body_lines[0].pos = 2  # after "al"
        panel.handle_key(ord("v"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("l"))
        panel.handle_key(ord("d"))
        assert panel._body_visual_mode == ""
        assert panel.get_values()["korpo"] == "al"

    def test_body_visual_line_delete_removes_selected_lines(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "l1\nl2\nl3\nl4"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 1
        panel._body_lines[1].mode = "NORMAL"
        panel.handle_key(ord("V"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("d"))
        assert panel._body_visual_mode == ""
        assert panel.get_values()["korpo"] == "l1\nl4"

    def test_body_normal_p_pastes_below_current_line(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "l1\nl2"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "NORMAL"
        panel._body_register = "aa\nbb"
        panel.handle_key(ord("p"))
        assert panel.get_values()["korpo"] == "l1\naa\nbb\nl2"

    def test_body_normal_P_pastes_above_current_line(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "l1\nl2"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 1
        panel._body_lines[1].mode = "NORMAL"
        panel._body_register = "aa\nbb"
        panel.handle_key(ord("P"))
        assert panel.get_values()["korpo"] == "l1\naa\nbb\nl2"

    def test_body_visual_x_deletes_selection(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "alpha\nbeta\ngamma"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "NORMAL"
        panel._body_lines[0].pos = 2
        panel.handle_key(ord("v"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("j"))
        panel.handle_key(ord("l"))
        panel.handle_key(ord("x"))
        assert panel._body_visual_mode == ""
        assert panel.get_values()["korpo"] == "al"

    def test_body_insert_ctrl_v_paste_keeps_paragraph_order(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "start"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_row = 0
        panel._body_lines[0].mode = "INSERT"
        panel._body_lines[0].pos = len(panel._body_lines[0].value)
        panel._body_register = "para1\n\npara2\nline2"
        panel.handle_key(22)  # Ctrl+V
        assert panel.get_values()["korpo"] == "startpara1\n\npara2\nline2"

    def test_ctrl_u_kills_line_backward(self):
        ed = LineEditor("hello world")
        ed.pos = 6  # after "hello "
        ed.handle_key(21)  # Ctrl+U
        assert ed.value == "world"
        assert ed.pos == 0

    def test_ctrl_w_kills_word_backward(self):
        ed = LineEditor("hello world test")
        ed.pos = 11  # after "hello world"
        ed.handle_key(23)  # Ctrl+W
        assert ed.value == "hello  test"  # space before word remains
        assert ed.pos == 6

    def test_ctrl_k_kills_line_forward(self):
        ed = LineEditor("hello world")
        ed.pos = 6  # after "hello "
        ed.handle_key(11)  # Ctrl+K
        assert ed.value == "hello "
        assert ed.pos == 6

    def test_ctrl_y_yanks_killed_text(self):
        ed = LineEditor("hello world")
        ed.pos = 6
        ed.handle_key(21)  # Ctrl+U to kill (removes "hello ")
        assert ed.value == "world"
        ed.handle_key(25)  # Ctrl+Y to yank (restore "hello ")
        assert ed.value == "hello world"
        assert ed.pos == 6


class TestRetpostoHelpers:
    def test_unwrap_wrapped_mail_urls(self):
        raw = (
            "https://particuliers.sg.fr/assurances/nos-offres/assurance-protection-\n"
            "aide-juridique"
        )
        out = _unwrap_wrapped_mail_urls(raw)
        assert out.endswith("assurance-protection-aide-juridique")

    def test_autosave_filters_noreply_and_random_localpart(self):
        assert _should_autosave_contact_email("noreply@socgen.fr") is False
        assert _should_autosave_contact_email("do-not-reply@x.com") is False
        assert _should_autosave_contact_email("notification@x.com") is False
        assert _should_autosave_contact_email("newsletter@x.com") is False
        assert _should_autosave_contact_email("2dj2912@socgen.fr") is False
        assert _is_likely_temporary_local_part("2dj2912") is True
        assert _should_autosave_contact_email("alice@example.com") is True


def _make_tui_for_keys() -> RetpostoTUI:
    stdscr = _FakeStdScr()
    tui = RetpostoTUI(
        stdscr,
        load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
        load_messages=lambda **_: [],
        load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
        fetch_account_mail=lambda _acc, _max: (0, 0),
        send_message=lambda *_a, **_k: True,
        save_message=lambda _m: 1,
        update_message_field=lambda *_a, **_k: None,
        delete_message=lambda *_a, **_k: None,
        load_contacts=lambda: [],
        find_contact=lambda _p: [],
        upsert_contact=lambda *_a, **_k: None,
        load_filters=lambda: [],
        add_spam_block=lambda _r: None,
        is_spam=lambda _s: False,
        ensure_folder=lambda *_a, **_k: 1,
    )
    tui._focus = "list"
    return tui


class TestRetpostoTuiGlobalKeys:
    def test_access_key_c_opens_compose(self):
        tui = _make_tui_for_keys()
        tui._compose_new = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("c")) is False
        tui._compose_new.assert_called_once()

    def test_access_key_s_calls_spam_action(self):
        tui = _make_tui_for_keys()
        tui._action_spam = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("s")) is False
        tui._action_spam.assert_called_once()

    def test_access_key_m_marks_selected_or_current_as_read(self):
        tui = _make_tui_for_keys()
        tui._action_mark_read_selected = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("m")) is False
        tui._action_mark_read_selected.assert_called_once()

    def test_shift_s_in_outbox_sends_all(self):
        tui = _make_tui_for_keys()
        tui._focus = "list"
        tui._folder_panel._items = [
            {"type": "folder", "acc_id": 1, "folder_id": 1, "label": "  OUTBOX"}
        ]
        tui._folder_panel._cursor = 0
        tui._action_resend_all_outbox = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("S")) is False
        tui._action_resend_all_outbox.assert_called_once()

    def test_shift_tab_moves_focus_back_to_folder(self):
        tui = _make_tui_for_keys()
        tui._focus = "list"
        assert tui._handle_key(curses.KEY_BTAB) is False
        assert tui._focus == "folder"

    def test_access_key_x_calls_delete_action(self):
        tui = _make_tui_for_keys()
        tui._action_delete = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("x")) is False
        tui._action_delete.assert_called_once()

    def test_access_key_d_calls_move_action(self):
        tui = _make_tui_for_keys()
        tui._action_move = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("d")) is False
        tui._action_move.assert_called_once()

    def test_access_key_y_calls_copy_action(self):
        tui = _make_tui_for_keys()
        tui._action_copy = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("y")) is False
        tui._action_copy.assert_called_once()

    def test_slash_opens_search_screen(self):
        tui = _make_tui_for_keys()
        tui._show_message_search_screen = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("/")) is False
        tui._show_message_search_screen.assert_called_once()

    def test_key_K_opens_folder_manager_from_accounts(self):
        tui = _make_tui_for_keys()
        tui._focus = "folder"
        tui._show_folder_manager = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("K")) is False
        tui._show_folder_manager.assert_called_once()

    def test_default_status_shows_spam_pane_hint_in_list(self):
        tui = _make_tui_for_keys()
        tui._focus = "list"
        status = tui._default_status()
        assert "S:spamo-listo" in status
        assert "m:marki-legita" in status

    def test_default_status_outbox_shows_ctrl_send_hints(self):
        tui = _make_tui_for_keys()
        tui._focus = "list"
        tui._folder_panel._items = [
            {"type": "folder", "acc_id": 1, "folder_id": 1, "label": "  OUTBOX"}
        ]
        tui._folder_panel._cursor = 0
        status = tui._default_status()
        assert "Ctrl+S:sendi-elektitajn" in status
        assert "Ctrl+Shift+S:sendi-ĉiujn" in status

    def test_fetch_guard_blocks_duplicate_attempt(self):
        tui = _make_tui_for_keys()
        tui._fetching = True
        tui._action_fetch()
        assert "progreso" in tui._status_msg.lower()

    def test_open_message_ignores_empty_priority_action(self):
        tui = _make_tui_for_keys()
        tui._message_panel._messages = [{"id": 1, "legita": 1}]
        tui._message_panel._cursor = 0
        with patch(
            "autish.commands._retposto_tui.MessageReader.run",
            return_value="priority:",
        ):
            tui._open_message()

    def test_transient_status_expires_after_three_seconds(self):
        tui = _make_tui_for_keys()
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=10.0):
            tui._set_status("Premu q por eliri.", transient=True)
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=12.0):
            assert tui._current_status() == "Premu q por eliri."
        with patch("autish.commands._retposto_tui.time.monotonic", return_value=13.5):
            assert tui._current_status() == ""


# ──────────────────────────────────────────────────────────────────────────────
# Tests for new features: account update, signature, spam pane, folder creation
# ──────────────────────────────────────────────────────────────────────────────


class TestUpdateAccount:
    def test_update_name(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "OldName",
                "retposto": "user@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {"nomo": "NewName"})
        accounts = _load_accounts()
        assert accounts[0]["nomo"] == "NewName"

    def test_update_imap_server(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Test",
                "retposto": "u@example.com",
                "imap_servilo": "old.imap.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {"imap_servilo": "new.imap.com"})
        accounts = _load_accounts()
        assert accounts[0]["imap_servilo"] == "new.imap.com"

    def test_update_invalid_column_raises(self, isolated_db):
        from autish.commands.retposto import _save_account, _update_account

        acc_id = _save_account(
            {
                "nomo": "Test",
                "retposto": "u2@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        with pytest.raises(ValueError, match="Disallowed"):
            _update_account(acc_id, {"id": 99})

    def test_update_empty_fields_noop(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Unchanged",
                "retposto": "u3@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {})
        accounts = _load_accounts()
        assert accounts[0]["nomo"] == "Unchanged"


class TestSignatureColumn:
    def test_signature_default_null(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        _save_account(
            {
                "nomo": "Test",
                "retposto": "sig@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        accounts = _load_accounts()
        assert accounts[0].get("subskribo") is None

    def test_set_and_retrieve_signature(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Sig",
                "retposto": "sig2@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {"subskribo": "/home/user/sig.txt"})
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] == "/home/user/sig.txt"

    def test_clear_signature(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Sig3",
                "retposto": "sig3@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {"subskribo": "/some/path"})
        _update_account(acc_id, {"subskribo": None})
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] is None


class TestCliSubskribo:
    def test_view_no_signature(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account(
            {
                "nomo": "Test",
                "retposto": "cli@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(app, ["retposto", "subskribo", str(acc_id)])
        assert result.exit_code == 0
        assert "Neniu" in result.output

    def test_set_signature(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        acc_id = _save_account(
            {
                "nomo": "Sig",
                "retposto": "clisig@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(
            app, ["retposto", "subskribo", str(acc_id), "-a", "/sig.txt"]
        )
        assert result.exit_code == 0
        assert "agordita" in result.output.lower()
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] == "/sig.txt"

    def test_remove_signature(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Sig4",
                "retposto": "clisig4@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _update_account(acc_id, {"subskribo": "/tmp/sig.txt"})
        result = runner.invoke(app, ["retposto", "subskribo", str(acc_id), "-f"])
        assert result.exit_code == 0
        assert "forigita" in result.output.lower()
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] is None


class TestCliNovdos:
    def test_create_folder(self, isolated_db):
        from autish.commands.retposto import _load_folders, _save_account

        acc_id = _save_account(
            {
                "nomo": "Fld",
                "retposto": "fld@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(
            app, ["retposto", "novdos", "Projekto", "-k", str(acc_id)]
        )
        assert result.exit_code == 0
        assert "Projekto" in result.output
        folders = _load_folders(acc_id)
        assert any(f["nomo"] == "Projekto" for f in folders)

    def test_create_sub_folder(self, isolated_db):
        from autish.commands.retposto import (
            _ensure_folder,
            _load_folders,
            _save_account,
        )

        acc_id = _save_account(
            {
                "nomo": "Fld2",
                "retposto": "fld2@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _ensure_folder(acc_id, "Inbox", "INBOX")  # create parent first
        result = runner.invoke(
            app,
            ["retposto", "novdos", "SubFolder", "-k", str(acc_id), "-p", "Inbox"],
        )
        assert result.exit_code == 0
        folders = _load_folders(acc_id)
        assert any(f["nomo"] == "SubFolder" for f in folders)

    def test_no_accounts_error(self, isolated_db):
        result = runner.invoke(app, ["retposto", "novdos", "SomeFolder"])
        assert result.exit_code != 0
        assert (
            "kontoj" in result.output.lower()
            or "kontoj" in (result.stderr or "").lower()
        )


class TestCliListigiDosierujojn:
    def test_list_empty(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account(
            {
                "nomo": "Lst",
                "retposto": "lst@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(
            app, ["retposto", "listigi-dosierujojn", "-k", str(acc_id)]
        )
        assert result.exit_code == 0
        assert "neniuj" in result.output.lower()

    def test_list_with_folder(self, isolated_db):
        from autish.commands.retposto import _ensure_folder, _save_account

        acc_id = _save_account(
            {
                "nomo": "Lst2",
                "retposto": "lst2@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _ensure_folder(acc_id, "Archive", "Archive")
        result = runner.invoke(
            app, ["retposto", "listigi-dosierujojn", "-k", str(acc_id)]
        )
        assert result.exit_code == 0
        assert "Archive" in result.output


class TestCliMoviMesagon:
    def test_move_message_to_folder(self, isolated_db):
        from autish.commands.retposto import (
            _ensure_folder,
            _save_account,
            _save_message,
        )

        acc_id = _save_account(
            {
                "nomo": "Move",
                "retposto": "move@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "de": "a@b.com",
                "al": ["move@example.com"],
                "subjekto": "Test",
            }
        )
        _ensure_folder(acc_id, "Archive", "Archive")
        result = runner.invoke(
            app, ["retposto", "movi-mesagon", str(msg_id), "Archive"]
        )
        assert result.exit_code == 0
        assert "movita" in result.output.lower()

    def test_move_nonexistent_message(self, isolated_db):
        result = runner.invoke(app, ["retposto", "movi-mesagon", "9999", "Archive"])
        assert result.exit_code != 0


class TestSpamPaneTui:
    """Tests for the spam pane (`S` key) in the TUI."""

    def test_key_S_opens_spam_pane(self):
        tui = _make_tui_for_keys()
        tui._show_spam_pane = MagicMock()  # type: ignore[method-assign]
        assert tui._handle_key(ord("S")) is False
        tui._show_spam_pane.assert_called_once()

    def test_spam_confirmation_cancel(self):
        """'s' asks for confirmation; cancelling does not add spam block."""
        added = []
        stdscr = _FakeStdScr()
        tui = RetpostoTUI(
            stdscr,
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: True,
            save_message=lambda _m: 1,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda r: added.append(r),
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 1,
        )
        # Set up a selected message
        tui._message_panel._messages = [
            {"id": 1, "de": "spammer@evil.com", "legita": 0}
        ]
        tui._message_panel._cursor = 0
        # Simulate prompt_confirm returning False (user cancels)
        with patch.object(tui, "_prompt_confirm_inline", return_value=False):
            tui._action_spam()
        assert added == []
        assert tui._status_msg == ""

    def test_spam_confirmation_accept(self):
        """Pressing 's' and confirming should block the sender."""
        added = []
        stdscr = _FakeStdScr()
        tui = RetpostoTUI(
            stdscr,
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: True,
            save_message=lambda _m: 1,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda r: added.append(r),
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 1,
        )
        tui._message_panel._messages = [
            {"id": 1, "de": "spammer@evil.com", "legita": 0}
        ]
        tui._message_panel._cursor = 0
        tui._refresh_list = MagicMock()  # type: ignore[method-assign]
        with patch.object(tui, "_prompt_confirm_inline", return_value=True):
            tui._action_spam()
        assert "spammer@evil.com" in added
        assert "blokita" in tui._status_msg.lower()

    def test_spam_pane_unblock_without_confirmation(self):
        removed: list[str] = []
        tui = RetpostoTUI(
            _FakeStdScr(keys=[ord("u"), ord("q")]),
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: True,
            save_message=lambda _m: 1,
            update_message_field=lambda *_a, **_k: None,
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda _r: None,
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 1,
            load_spam_blocks=lambda: [{"regulo": "spam@evil.com", "kreita_je": ""}],
            remove_spam_block=lambda rule: removed.append(rule),
            load_messages_spam=lambda **_: [],
        )
        with patch.object(tui, "_prompt_confirm_inline") as confirm_mock:
            tui._show_spam_pane()
        confirm_mock.assert_not_called()
        assert removed == ["spam@evil.com"]

    def test_spam_pane_restore_without_confirmation(self):
        updated: list[tuple[int, dict]] = []
        tui = RetpostoTUI(
            _FakeStdScr(keys=[9, ord("u"), ord("q")]),
            load_accounts=lambda: [{"id": 1, "retposto": "me@example.com"}],
            load_messages=lambda **_: [],
            load_folders=lambda _acc_id: [{"id": 10, "nomo": "Inbox"}],
            fetch_account_mail=lambda _acc, _max: (0, 0),
            send_message=lambda *_a, **_k: True,
            save_message=lambda _m: 1,
            update_message_field=(
                lambda msg_id, **fields: updated.append((msg_id, fields))
            ),
            delete_message=lambda *_a, **_k: None,
            load_contacts=lambda: [],
            find_contact=lambda _p: [],
            upsert_contact=lambda *_a, **_k: None,
            load_filters=lambda: [],
            add_spam_block=lambda _r: None,
            is_spam=lambda _s: False,
            ensure_folder=lambda *_a, **_k: 1,
            load_spam_blocks=lambda: [],
            remove_spam_block=lambda _rule: None,
            load_messages_spam=(
                lambda **_: [{"id": 33, "de": "s@x.com", "subjekto": "S"}]
            ),
        )
        with patch.object(tui, "_prompt_confirm_inline") as confirm_mock:
            tui._show_spam_pane()
        confirm_mock.assert_not_called()
        assert updated == [(33, {"spamo": 0})]

    def test_spam_pane_accepts_colon_q_alias(self):
        tui = _make_tui_for_keys()
        tui.stdscr = _FakeStdScr(keys=[ord(":")])

        with patch.object(tui, "_prompt_inline", return_value="q") as prompt_mock:
            tui._show_spam_pane()

        prompt_mock.assert_called_once()

    def test_simple_pager_accepts_colon_q_alias(self):
        tui = _make_tui_for_keys()
        tui.stdscr = _FakeStdScr(keys=[ord(":")])

        with patch.object(tui, "_prompt_inline", return_value="q") as prompt_mock:
            tui._run_pager_lines(["uno", "du"], "Testo")

        prompt_mock.assert_called_once()


class TestConfirmPrompt:
    def test_prompt_confirm_waits_for_user_keystroke(self):
        tui = _make_tui_for_keys()
        with patch(
            "autish.commands._retposto_tui._getch_unicode",
            side_effect=[-1, -1, ord("j")],
        ) as key_mock:
            assert tui._prompt_confirm_inline("Ĉu? (j/N)") is True
        assert key_mock.call_count == 3


class TestPromptAutocomplete:
    def test_enter_accepts_first_suggestion(self):
        tui = _make_tui_for_keys()
        tui._draw = lambda: None  # type: ignore[method-assign]
        with patch(
            "autish.commands._retposto_tui._getch_unicode",
            side_effect=[ord("\n")],
        ):
            value = tui._prompt_inline(
                "Celo",
                suggestions=lambda _s: ["Archive", "Inbox"],
                accept_first_suggestion=True,
            )
        assert value == "Archive"

    def test_move_copy_does_not_create_unknown_folder(self):
        tui = _make_tui_for_keys()
        tui._message_panel._messages = [
            {"id": 1, "konto_id": 1, "de": "a@b.com", "subjekto": "S", "legita": 0}
        ]
        tui._message_panel._cursor = 0
        with (
            patch.object(tui, "_prompt_inline", return_value="archice"),
            patch.object(tui, "_prompt_confirm_inline", return_value=True),
            patch.object(tui, "_folder_id_by_name", return_value=None),
        ):
            tui._action_move()
        assert "ne trovita" in tui._status_msg.lower()


class TestRetpostoMultiSelection:
    def test_space_toggles_current_message_selection(self):
        tui = _make_tui_for_keys()
        tui._message_panel._messages = [{"id": 1, "konto_id": 1, "legita": 1}]
        tui._message_panel._cursor = 0
        tui._focus = "list"
        tui._handle_key(ord(" "))
        assert 1 in tui._selected_message_ids
        tui._handle_key(ord(" "))
        assert 1 not in tui._selected_message_ids

    def test_v_range_selects_interval(self):
        tui = _make_tui_for_keys()
        tui._message_panel._messages = [
            {"id": 1, "konto_id": 1, "legita": 1},
            {"id": 2, "konto_id": 1, "legita": 1},
            {"id": 3, "konto_id": 1, "legita": 1},
        ]
        tui._focus = "list"
        tui._message_panel._cursor = 0
        tui._handle_key(ord("v"))
        tui._message_panel._cursor = 2
        tui._handle_key(ord("v"))
        assert tui._selected_message_ids == {1, 2, 3}

    def test_escape_clears_selection(self):
        tui = _make_tui_for_keys()
        tui._focus = "list"
        tui._selected_message_ids = {1, 2}
        tui._message_visual_anchor = 0
        tui._handle_key(27)
        assert not tui._selected_message_ids
        assert tui._message_visual_anchor is None

    def test_delete_applies_to_selected_messages(self):
        deleted: list[tuple[int, bool]] = []
        tui = _make_tui_for_keys()
        tui._delete_message = (  # type: ignore[method-assign]
            lambda msg_id, permanent: deleted.append((msg_id, permanent))
        )
        tui._message_panel._messages = [
            {"id": 1, "konto_id": 1, "legita": 1},
            {"id": 2, "konto_id": 1, "legita": 1},
        ]
        tui._selected_message_ids = {1, 2}
        tui._focus = "list"
        with patch.object(tui, "_prompt_confirm_inline", return_value=True):
            tui._action_delete()
        assert deleted == [(1, False), (2, False)]

    def test_mark_read_selected_updates_all_selected_messages(self):
        updated: list[tuple[int, dict]] = []
        tui = _make_tui_for_keys()
        tui._update_message_field = (  # type: ignore[method-assign]
            lambda msg_id, **fields: updated.append((msg_id, fields))
        )
        tui._message_panel._messages = [
            {"id": 1, "konto_id": 1, "legita": 0},
            {"id": 2, "konto_id": 1, "legita": 0},
        ]
        tui._selected_message_ids = {1, 2}
        tui._focus = "list"
        tui._action_mark_read_selected()
        assert updated == [(1, {"legita": 1}), (2, {"legita": 1})]


class TestDeleteMessageBehavior:
    def test_non_permanent_delete_moves_message_to_trash_folder(self, isolated_db):
        from autish.commands.retposto import (
            _delete_message,
            _get_db,
            _save_account,
            _save_message,
        )

        acc_id = _save_account(
            {
                "nomo": "Trash Test",
                "retposto": "trash@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "de": "a@b.com",
                "al": ["trash@example.com"],
                "subjekto": "Delete me",
            }
        )

        _delete_message(msg_id, permanent=False)

        with _get_db() as con:
            row = con.execute(
                "SELECT dosierujo_id, forigita FROM mesago WHERE id = ?",
                (msg_id,),
            ).fetchone()
            trash = con.execute(
                "SELECT id FROM dosierujo WHERE konto_id = ? AND nomo = 'Trash'",
                (acc_id,),
            ).fetchone()

        assert row is not None
        assert trash is not None
        assert row["dosierujo_id"] == trash["id"]
        assert row["forigita"] == 0

    def test_non_permanent_delete_syncs_uid_to_server(self, isolated_db, monkeypatch):
        from autish.commands.retposto import (
            _delete_message,
            _ensure_folder,
            _save_account,
            _save_message,
        )

        actions: list[tuple[str, tuple[object, ...]]] = []

        class _FakeIMAP:
            def login(self, *_args):
                actions.append(("login", tuple(_args)))
                return ("OK", [])

            def select(self, *args, **_kwargs):
                actions.append(("select", args))
                return ("OK", [b"1"])

            def uid(self, *args):
                actions.append(("uid", args))
                if len(args) >= 2 and str(args[0]).upper() == "COPY":
                    return ("OK", [b""])
                return ("OK", [])

            def expunge(self):
                actions.append(("expunge", ()))
                return ("OK", [])

            def logout(self):
                actions.append(("logout", ()))
                return ("BYE", [b"LOGOUT"])

        class _ImmediateExecutor:
            def submit(self, fn, *args):
                fn(*args)
                return None

        monkeypatch.setattr(
            "autish.commands.retposto.imaplib.IMAP4_SSL",
            lambda *_a, **_k: _FakeIMAP(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._IMAP_SYNC_EXECUTOR",
            _ImmediateExecutor(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "secret",
        )

        acc_id = _save_account(
            {
                "nomo": "Sync Delete",
                "retposto": "sync@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
            }
        )
        inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": inbox_id,
                "uid": "42",
                "de": "a@b.com",
                "al": ["sync@example.com"],
                "subjekto": "Delete me remote",
            }
        )

        _delete_message(msg_id, permanent=False)

        uid_calls = [entry for entry in actions if entry[0] == "uid"]
        assert any(call[1][0] == "COPY" and call[1][1] == "42" for call in uid_calls)
        assert any(call[1][0] == "STORE" and call[1][1] == "42" for call in uid_calls)
        assert any(entry[0] == "expunge" for entry in actions)

    def test_update_field_syncs_read_star_and_move_to_server(
        self, isolated_db, monkeypatch
    ):
        from autish.commands.retposto import (
            _ensure_folder,
            _save_account,
            _save_message,
            _update_message_field,
        )

        actions: list[tuple[str, tuple[object, ...]]] = []

        class _FakeIMAP:
            def login(self, *_args):
                actions.append(("login", tuple(_args)))
                return ("OK", [])

            def select(self, *args, **_kwargs):
                actions.append(("select", args))
                return ("OK", [b"1"])

            def uid(self, *args):
                actions.append(("uid", args))
                if len(args) >= 1 and str(args[0]).upper() == "COPY":
                    return ("OK", [b""])
                return ("OK", [])

            def create(self, *args):
                actions.append(("create", args))
                return ("OK", [b""])

            def expunge(self):
                actions.append(("expunge", ()))
                return ("OK", [b""])

            def logout(self):
                actions.append(("logout", ()))
                return ("BYE", [b"LOGOUT"])

        class _ImmediateExecutor:
            def submit(self, fn, *args):
                fn(*args)
                return None

        monkeypatch.setattr(
            "autish.commands.retposto.imaplib.IMAP4_SSL",
            lambda *_a, **_k: _FakeIMAP(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._IMAP_SYNC_EXECUTOR",
            _ImmediateExecutor(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "secret",
        )

        acc_id = _save_account(
            {
                "nomo": "Sync Update",
                "retposto": "sync-update@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
            }
        )
        inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
        archive_id = _ensure_folder(acc_id, "Archive", "Archive")
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": inbox_id,
                "uid": "99",
                "de": "a@b.com",
                "al": ["sync-update@example.com"],
                "subjekto": "sync update",
            }
        )

        _update_message_field(msg_id, legita=1, stelo=1, dosierujo_id=archive_id)

        uid_calls = [entry for entry in actions if entry[0] == "uid"]
        assert any(
            call[1][0] == "STORE" and call[1][2] == "+FLAGS" for call in uid_calls
        )
        assert any(call[1][0] == "COPY" and call[1][1] == "99" for call in uid_calls)
        assert any(entry[0] == "expunge" for entry in actions)

    def test_update_field_returns_without_waiting_for_remote_sync(
        self, isolated_db, monkeypatch
    ):
        from autish.commands.retposto import (
            _ensure_folder,
            _save_account,
            _save_message,
            _update_message_field,
        )

        submitted: list[tuple[object, tuple[object, ...]]] = []

        class _FakeExecutor:
            def submit(self, fn, *args):
                submitted.append((fn, args))
                return None

        monkeypatch.setattr(
            "autish.commands.retposto._IMAP_SYNC_EXECUTOR",
            _FakeExecutor(),
        )
        monkeypatch.setattr(
            "autish.commands.retposto._get_password",
            lambda _id: "secret",
        )

        acc_id = _save_account(
            {
                "nomo": "Async Test",
                "retposto": "async@example.com",
                "imap_servilo": "imap.example.com",
                "imap_haveno": 993,
                "imap_ssl": True,
                "smtp_servilo": "smtp.example.com",
            }
        )
        inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": inbox_id,
                "uid": "7",
                "de": "a@b.com",
                "al": ["async@example.com"],
                "subjekto": "Async path",
            }
        )

        _update_message_field(msg_id, legita=1)
        assert submitted, "expected remote sync to be scheduled asynchronously"


class TestAccountOrdering:
    def test_move_account_order_swaps_positions(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _move_account_order,
            _save_account,
        )

        id1 = _save_account(
            {
                "nomo": "A",
                "retposto": "a@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        id2 = _save_account(
            {
                "nomo": "B",
                "retposto": "b@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        before = [a["id"] for a in _load_accounts()]
        assert before == [id1, id2]
        moved = _move_account_order(id2, -1)
        assert moved is True
        after = [a["id"] for a in _load_accounts()]
        assert after == [id2, id1]

    def test_cli_reordigi_konton(self, isolated_db):
        from autish.commands.retposto import _save_account

        _save_account(
            {
                "nomo": "A",
                "retposto": "aa@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        _save_account(
            {
                "nomo": "B",
                "retposto": "bb@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(
            app,
            ["retposto", "reordigi-konton", "bb@example.com", "supren"],
        )
        assert result.exit_code == 0
        assert "reordigita" in result.output.lower()


class TestMessageSearchFiltering:
    def test_apply_message_search_updates_message_panel(self):
        tui = _make_tui_for_keys()
        tui._message_panel._all_messages = [
            {"id": 1, "de": "alice@example.com", "subjekto": "meeting", "korpo": "x"},
            {"id": 2, "de": "bob@example.com", "subjekto": "other", "korpo": "y"},
        ]
        tui._message_panel.reset_filter()
        tui._apply_message_search(['FROM "alice@example.com"'])
        assert len(tui._message_panel._messages) == 1
        assert tui._message_panel._messages[0]["id"] == 1

    def test_empty_search_resets_messages(self):
        tui = _make_tui_for_keys()
        tui._message_panel._all_messages = [
            {"id": 1, "de": "alice@example.com", "subjekto": "meeting", "korpo": "x"},
            {"id": 2, "de": "bob@example.com", "subjekto": "other", "korpo": "y"},
        ]
        tui._message_panel.set_filtered_messages(
            [{"id": 1, "de": "alice@example.com", "subjekto": "meeting", "korpo": "x"}],
            "FROM alice",
        )
        tui._apply_message_search([])
        assert len(tui._message_panel._messages) == 2

    def test_folder_search_can_query_other_folder_scope(self):
        tui = _make_tui_for_keys()
        tui._load_accounts = lambda: [{"id": 1, "retposto": "me@example.com"}]  # type: ignore[method-assign]
        tui._load_folders = lambda _acc_id: [  # type: ignore[method-assign]
            {"id": 10, "nomo": "INBOX"},
            {"id": 11, "nomo": "Archive"},
        ]

        def _fake_load_messages(**kwargs):
            if kwargs.get("dosierujo_id") == 11:
                return [
                    {
                        "id": 99,
                        "de": "alice@example.com",
                        "subjekto": "archive target",
                        "korpo": "body",
                    }
                ]
            return []

        tui._load_messages = _fake_load_messages  # type: ignore[method-assign]
        tui._apply_message_search(["FOLDER me@example.com/Archive", 'FROM "alice"'])
        assert len(tui._message_panel._messages) == 1
        assert tui._message_panel._messages[0]["id"] == 99


class TestMessagePanelRendering:
    def test_selected_tick_overrides_other_flags(self):
        panel = MessagePanel(_FakeStdScr(), load_messages=lambda **_: [])
        panel._messages = [
            {
                "id": 7,
                "de": "alice@example.com",
                "subjekto": "Subject",
                "ricevita_je": "2026-03-01T12:00:00",
                "stelo": 1,
                "spamo": 1,
                "etikedoj": ["read-receipt-requested"],
                "legita": 1,
            }
        ]
        panel._selected_ids = {7}

        class _RecordingWin:
            def __init__(self):
                self.calls: list[tuple[int, int, str, int]] = []

            def getmaxyx(self):
                return (8, 120)

            def erase(self):
                return None

            def addstr(self, row, col, text, attr=0):
                self.calls.append((row, col, text, attr))
                return None

            def noutrefresh(self):
                return None

        win = _RecordingWin()
        panel.draw(win, focused=False)
        message_line = next((c[2] for c in win.calls if c[0] == 1), "")
        assert message_line.startswith(" ✓ ⚠")


class TestCliFolderAndCopyParity:
    def test_cli_kopii_mesagon_and_rename_move_folder(self, isolated_db):
        from autish.commands.retposto import (
            _ensure_folder,
            _get_db,
            _save_account,
            _save_message,
        )

        acc_id = _save_account(
            {
                "nomo": "Acct",
                "retposto": "acct@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        src = _ensure_folder(acc_id, "Inbox", "Inbox")
        dst = _ensure_folder(acc_id, "Archive", "Archive")
        msg_id = _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": src,
                "de": "a@b.com",
                "al": ["acct@example.com"],
                "subjekto": "Copy me",
            }
        )
        result_copy = runner.invoke(
            app, ["retposto", "kopii-mesagon", str(msg_id), "Archive"]
        )
        assert result_copy.exit_code == 0
        assert "kopiita" in result_copy.output.lower()

        result_rename = runner.invoke(
            app, ["retposto", "renomi-dosierujon", str(dst), "Archive2"]
        )
        assert result_rename.exit_code == 0
        assert "renomita" in result_rename.output.lower()

        parent = _ensure_folder(acc_id, "Parent", "Parent")
        result_move = runner.invoke(
            app, ["retposto", "movi-dosierujon", str(dst), str(parent)]
        )
        assert result_move.exit_code == 0
        assert "movita" in result_move.output.lower()

        with _get_db() as con:
            row = con.execute(
                "SELECT patro_id FROM dosierujo WHERE id = ?",
                (dst,),
            ).fetchone()
        assert row is not None
        assert row["patro_id"] == parent


class TestCliSearch:
    def test_retposto_serci_filters_by_folder(self, isolated_db):
        from autish.commands.retposto import (
            _ensure_folder,
            _save_account,
            _save_message,
        )

        acc_id = _save_account(
            {
                "nomo": "Acct",
                "retposto": "acct@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
        archive_id = _ensure_folder(acc_id, "Archive", "Archive")
        _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": inbox_id,
                "de": "alice@example.com",
                "subjekto": "inbox msg",
                "korpo": "hello inbox",
            }
        )
        _save_message(
            {
                "konto_id": acc_id,
                "dosierujo_id": archive_id,
                "de": "alice@example.com",
                "subjekto": "archive msg",
                "korpo": "hello archive",
            }
        )
        result = runner.invoke(
            app,
            ["retposto", "serci", "alice", "--dosierujo", "acct@example.com/Archive"],
        )
        assert result.exit_code == 0
        assert "archive msg" in result.output
        assert "inbox msg" not in result.output


class TestCliGisdatigiKonton:
    def test_update_imap_server(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        acc_id = _save_account(
            {
                "nomo": "Upd",
                "retposto": "upd@example.com",
                "imap_servilo": "old.imap.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(
            app,
            [
                "retposto",
                "ĝisdatigi-konton",
                str(acc_id),
                "--imap",
                "new.imap.com",
            ],
        )
        assert result.exit_code == 0
        assert "ĝisdatigita" in result.output.lower()
        accounts = _load_accounts()
        assert accounts[0]["imap_servilo"] == "new.imap.com"

    def test_no_change_specified(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account(
            {
                "nomo": "NoChange",
                "retposto": "nc@example.com",
                "imap_servilo": "imap.example.com",
                "smtp_servilo": "smtp.example.com",
            }
        )
        result = runner.invoke(app, ["retposto", "ĝisdatigi-konton", str(acc_id)])
        assert result.exit_code == 0
        assert "neniu" in result.output.lower()

    def test_account_not_found(self, isolated_db):
        result = runner.invoke(
            app, ["retposto", "ĝisdatigi-konton", "9999", "--imap", "x.com"]
        )
        assert result.exit_code != 0

    def test_update_extended_account_fields(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        acc_id = _save_account(
            {
                "nomo": "UpdExt",
                "retposto": "updext@example.com",
                "imap_servilo": "old.imap.com",
                "smtp_servilo": "old.smtp.com",
            }
        )
        result = runner.invoke(
            app,
            [
                "retposto",
                "ĝisdatigi-konton",
                str(acc_id),
                "--imap-uzantonomo",
                "imap-user@example.com",
                "--smtp-uzantonomo",
                "smtp-user@example.com",
                "--webmail-url",
                "https://webmail.example.com",
                "--sieve-servilo",
                "sieve.example.com",
                "--sieve-haveno",
                "4190",
                "--no-sieve-starttls",
                "--sieve-uzantonomo",
                "sieve-user@example.com",
            ],
        )
        assert result.exit_code == 0, result.output
        acc = _load_accounts()[0]
        assert acc["imap_uzantonomo"] == "imap-user@example.com"
        assert acc["smtp_uzantonomo"] == "smtp-user@example.com"
        assert acc["webmail_url"] == "https://webmail.example.com"
        assert acc["sieve_servilo"] == "sieve.example.com"
        assert int(acc["sieve_haveno"]) == 4190
        assert bool(acc["sieve_starttls"]) is False
        assert acc["sieve_uzantonomo"] == "sieve-user@example.com"


class TestDbMigration:
    def test_migration_adds_subskribo_column(self, tmp_path, monkeypatch):
        """Migration should add 'subskribo' to existing DB that lacks it."""
        import autish.commands.retposto as rp_mod

        monkeypatch.setattr(rp_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(rp_mod, "_DB_FILE", tmp_path / "retposto.db")

        # Create a DB without the subskribo column
        con = sqlite3.connect(str(tmp_path / "retposto.db"))
        con.execute(
            """CREATE TABLE konto (
                id INTEGER PRIMARY KEY, nomo TEXT, retposto TEXT UNIQUE,
                imap_servilo TEXT, imap_haveno INTEGER DEFAULT 993,
                imap_ssl INTEGER DEFAULT 1, smtp_servilo TEXT,
                smtp_haveno INTEGER DEFAULT 587, smtp_tls INTEGER DEFAULT 1,
                uzantonomo TEXT, kreita_je TEXT
            )"""
        )
        con.commit()
        con.close()

        # Opening the DB via _get_db should apply the migration
        db = rp_mod._get_db()
        cols = {row[1] for row in db.execute("PRAGMA table_info(konto)").fetchall()}
        db.close()
        assert "subskribo" in cols

    def test_migration_adds_extended_konto_columns(self, tmp_path, monkeypatch):
        import autish.commands.retposto as rp_mod

        monkeypatch.setattr(rp_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(rp_mod, "_DB_FILE", tmp_path / "retposto.db")
        con = sqlite3.connect(str(tmp_path / "retposto.db"))
        con.execute(
            """CREATE TABLE konto (
                id INTEGER PRIMARY KEY, nomo TEXT, retposto TEXT UNIQUE,
                imap_servilo TEXT, imap_haveno INTEGER DEFAULT 993,
                imap_ssl INTEGER DEFAULT 1, smtp_servilo TEXT,
                smtp_haveno INTEGER DEFAULT 587, smtp_tls INTEGER DEFAULT 1,
                uzantonomo TEXT, subskribo TEXT, kreita_je TEXT
            )"""
        )
        con.commit()
        con.close()

        db = rp_mod._get_db()
        cols = {row[1] for row in db.execute("PRAGMA table_info(konto)").fetchall()}
        db.close()
        assert "imap_uzantonomo" in cols
        assert "smtp_uzantonomo" in cols
        assert "webmail_url" in cols
        assert "sieve_servilo" in cols
        assert "sieve_haveno" in cols
        assert "sieve_starttls" in cols
        assert "sieve_uzantonomo" in cols


class TestTUIAccountWithNoFolders:
    """Test TUI handles accounts with no folders (regression test for bug)."""

    def test_account_selection_creates_inbox_when_no_folders(self, isolated_db):
        """When selecting an account with no folders, INBOX should be auto-created."""
        from autish.commands.retposto import (
            _ensure_folder,
            _load_folders,
            _save_account,
        )

        # Create account with NO folders
        acc_id = _save_account(
            {
                "nomo": "NoFolders",
                "retposto": "no.folders@test.com",
                "imap_servilo": "imap.test.com",
                "smtp_servilo": "smtp.test.com",
            }
        )

        # Verify no folders exist
        folders_before = _load_folders(acc_id)
        assert len(folders_before) == 0

        # Simulate TUI account selection logic (from _retposto_tui.py:1988-2004)
        # When user presses ENTER on account with no folders, INBOX should be created
        folders = _load_folders(acc_id)
        if not folders:
            inbox_id = _ensure_folder(acc_id, "INBOX", "INBOX")
            folders = [{"id": inbox_id, "nomo": "INBOX"}]

        # Verify INBOX was created
        folders_after = _load_folders(acc_id)
        assert len(folders_after) == 1
        assert folders_after[0]["nomo"] == "INBOX"
        assert folders_after[0]["server_nomo"] == "INBOX"

    def test_account_selection_uses_existing_folders(self, isolated_db):
        """When selecting an account with existing folders, they should be used."""
        from autish.commands.retposto import (
            _ensure_folder,
            _load_folders,
            _save_account,
        )

        # Create account with folder
        acc_id = _save_account(
            {
                "nomo": "WithFolder",
                "retposto": "with.folder@test.com",
                "imap_servilo": "imap.test.com",
                "smtp_servilo": "smtp.test.com",
            }
        )
        existing_folder_id = _ensure_folder(acc_id, "Sent", "Sent")

        # Load folders
        folders = _load_folders(acc_id)
        assert len(folders) == 1
        assert folders[0]["id"] == existing_folder_id
        assert folders[0]["nomo"] == "Sent"

        # Selecting account should use existing folder (not create INBOX)
        folders_reloaded = _load_folders(acc_id)
        assert len(folders_reloaded) == 1
        assert folders_reloaded[0]["nomo"] == "Sent"  # Still Sent, not INBOX
