"""Tests for autish.commands.retposto (Retpoŝto email microapp)."""

from __future__ import annotations

import curses
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from autish.commands._retposto_tui import (
    ComposePanel,
    LineEditor,
    MessageReader,
    RetpostoTUI,
)
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
    _reply_targets,
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
        ).encode()

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
        msg = _parse_imap_message(raw, konto_id=1, dosierujo_id=1)
        assert msg["in_reply_to"] == "<root@example.com>"
        assert "<mid@example.com>" in (msg["references_hdr"] or "")


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
        to_targets, cc_targets = _reply_targets(
            "me@example.com", msg, reply_all=True
        )
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


class TestCliAldoniKonton:
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
        assert panel_send.handle_key(ord("\n")) == "send"

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
        assert panel.handle_key(ord("\n")) == "draft"

    def test_unicode_character_can_be_typed(self):
        panel = ComposePanel(_FakeStdScr(), {})
        panel.handle_key(ord("ŝ"))
        assert panel.get_values()["al"] == "ŝ"

    def test_m_toggles_markdown_in_normal_mode(self):
        panel = ComposePanel(_FakeStdScr(), {"korpo": "text"})
        panel._current_field = len(panel._field_names()) - 1
        panel._body_lines[0].mode = "NORMAL"
        assert panel.markdown_enabled() is False
        panel.handle_key(ord("m"))
        assert panel.markdown_enabled() is True


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

        acc_id = _save_account({
            "nomo": "OldName",
            "retposto": "user@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {"nomo": "NewName"})
        accounts = _load_accounts()
        assert accounts[0]["nomo"] == "NewName"

    def test_update_imap_server(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account({
            "nomo": "Test",
            "retposto": "u@example.com",
            "imap_servilo": "old.imap.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {"imap_servilo": "new.imap.com"})
        accounts = _load_accounts()
        assert accounts[0]["imap_servilo"] == "new.imap.com"

    def test_update_invalid_column_raises(self, isolated_db):
        from autish.commands.retposto import _save_account, _update_account

        acc_id = _save_account({
            "nomo": "Test",
            "retposto": "u2@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        with pytest.raises(ValueError, match="Disallowed"):
            _update_account(acc_id, {"id": 99})

    def test_update_empty_fields_noop(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account({
            "nomo": "Unchanged",
            "retposto": "u3@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {})
        accounts = _load_accounts()
        assert accounts[0]["nomo"] == "Unchanged"


class TestSignatureColumn:
    def test_signature_default_null(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        _save_account({
            "nomo": "Test",
            "retposto": "sig@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        accounts = _load_accounts()
        assert accounts[0].get("subskribo") is None

    def test_set_and_retrieve_signature(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account({
            "nomo": "Sig",
            "retposto": "sig2@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {"subskribo": "/home/user/sig.txt"})
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] == "/home/user/sig.txt"

    def test_clear_signature(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _save_account,
            _update_account,
        )

        acc_id = _save_account({
            "nomo": "Sig3",
            "retposto": "sig3@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {"subskribo": "/some/path"})
        _update_account(acc_id, {"subskribo": None})
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] is None


class TestCliSubskribo:
    def test_view_no_signature(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account({
            "nomo": "Test",
            "retposto": "cli@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        result = runner.invoke(app, ["retposto", "subskribo", str(acc_id)])
        assert result.exit_code == 0
        assert "Neniu" in result.output

    def test_set_signature(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        acc_id = _save_account({
            "nomo": "Sig",
            "retposto": "clisig@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
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

        acc_id = _save_account({
            "nomo": "Sig4",
            "retposto": "clisig4@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _update_account(acc_id, {"subskribo": "/tmp/sig.txt"})
        result = runner.invoke(
            app, ["retposto", "subskribo", str(acc_id), "-f"]
        )
        assert result.exit_code == 0
        assert "forigita" in result.output.lower()
        accounts = _load_accounts()
        assert accounts[0]["subskribo"] is None


class TestCliNovdos:
    def test_create_folder(self, isolated_db):
        from autish.commands.retposto import _load_folders, _save_account

        acc_id = _save_account({
            "nomo": "Fld",
            "retposto": "fld@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
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

        acc_id = _save_account({
            "nomo": "Fld2",
            "retposto": "fld2@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
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
        assert "kontoj" in result.output.lower() or "kontoj" in (
            result.stderr or ""
        ).lower()


class TestCliListigiDosierujojn:
    def test_list_empty(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account({
            "nomo": "Lst",
            "retposto": "lst@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        result = runner.invoke(
            app, ["retposto", "listigi-dosierujojn", "-k", str(acc_id)]
        )
        assert result.exit_code == 0
        assert "neniuj" in result.output.lower()

    def test_list_with_folder(self, isolated_db):
        from autish.commands.retposto import _ensure_folder, _save_account

        acc_id = _save_account({
            "nomo": "Lst2",
            "retposto": "lst2@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
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

        acc_id = _save_account({
            "nomo": "Move",
            "retposto": "move@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        msg_id = _save_message({
            "konto_id": acc_id,
            "de": "a@b.com",
            "al": ["move@example.com"],
            "subjekto": "Test",
        })
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


class TestDeleteMessageBehavior:
    def test_non_permanent_delete_moves_message_to_trash_folder(self, isolated_db):
        from autish.commands.retposto import (
            _delete_message,
            _get_db,
            _save_account,
            _save_message,
        )

        acc_id = _save_account({
            "nomo": "Trash Test",
            "retposto": "trash@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        msg_id = _save_message({
            "konto_id": acc_id,
            "de": "a@b.com",
            "al": ["trash@example.com"],
            "subjekto": "Delete me",
        })

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


class TestAccountOrdering:
    def test_move_account_order_swaps_positions(self, isolated_db):
        from autish.commands.retposto import (
            _load_accounts,
            _move_account_order,
            _save_account,
        )

        id1 = _save_account({
            "nomo": "A",
            "retposto": "a@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        id2 = _save_account({
            "nomo": "B",
            "retposto": "b@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        before = [a["id"] for a in _load_accounts()]
        assert before == [id1, id2]
        moved = _move_account_order(id2, -1)
        assert moved is True
        after = [a["id"] for a in _load_accounts()]
        assert after == [id2, id1]

    def test_cli_reordigi_konton(self, isolated_db):
        from autish.commands.retposto import _save_account

        _save_account({
            "nomo": "A",
            "retposto": "aa@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        _save_account({
            "nomo": "B",
            "retposto": "bb@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
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


class TestCliFolderAndCopyParity:
    def test_cli_kopii_mesagon_and_rename_move_folder(self, isolated_db):
        from autish.commands.retposto import (
            _ensure_folder,
            _get_db,
            _save_account,
            _save_message,
        )

        acc_id = _save_account({
            "nomo": "Acct",
            "retposto": "acct@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        src = _ensure_folder(acc_id, "Inbox", "Inbox")
        dst = _ensure_folder(acc_id, "Archive", "Archive")
        msg_id = _save_message({
            "konto_id": acc_id,
            "dosierujo_id": src,
            "de": "a@b.com",
            "al": ["acct@example.com"],
            "subjekto": "Copy me",
        })
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


class TestCliGisdatigiKonton:
    def test_update_imap_server(self, isolated_db):
        from autish.commands.retposto import _load_accounts, _save_account

        acc_id = _save_account({
            "nomo": "Upd",
            "retposto": "upd@example.com",
            "imap_servilo": "old.imap.com",
            "smtp_servilo": "smtp.example.com",
        })
        result = runner.invoke(
            app,
            [
                "retposto", "ĝisdatigi-konton", str(acc_id),
                "--imap", "new.imap.com",
            ],
        )
        assert result.exit_code == 0
        assert "ĝisdatigita" in result.output.lower()
        accounts = _load_accounts()
        assert accounts[0]["imap_servilo"] == "new.imap.com"

    def test_no_change_specified(self, isolated_db):
        from autish.commands.retposto import _save_account

        acc_id = _save_account({
            "nomo": "NoChange",
            "retposto": "nc@example.com",
            "imap_servilo": "imap.example.com",
            "smtp_servilo": "smtp.example.com",
        })
        result = runner.invoke(
            app, ["retposto", "ĝisdatigi-konton", str(acc_id)]
        )
        assert result.exit_code == 0
        assert "neniu" in result.output.lower()

    def test_account_not_found(self, isolated_db):
        result = runner.invoke(
            app, ["retposto", "ĝisdatigi-konton", "9999", "--imap", "x.com"]
        )
        assert result.exit_code != 0


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
