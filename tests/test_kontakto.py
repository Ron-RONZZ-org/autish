"""Tests for autish.commands.kontakto."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


@pytest.fixture()
def isolated_retposto_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import autish.commands.retposto as rp_mod

    monkeypatch.setattr(rp_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(rp_mod, "_DB_FILE", tmp_path / "retposto.db")
    rp_mod._get_db().close()
    return tmp_path


class TestKontaktoFlow:
    def test_add_list_modify_delete_undo(self, isolated_retposto_db):
        r1 = runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "alice@example.com",
                "-n",
                "Alice",
                "-k",
                "amiko",
                "-K",
                "0",
            ],
        )
        assert r1.exit_code == 0

        list1 = runner.invoke(app, ["kontakto", "listigi"])
        assert list1.exit_code == 0
        assert "alice@example.com" in list1.output

        uuid_prefix = None
        for line in list1.output.splitlines():
            if "alice@example.com" in line and "#" in line:
                uuid_prefix = line.split("#", 1)[1][:8]
                break
        assert uuid_prefix is not None

        with patch("autish.commands.retposto._confirm_esperante", return_value=True):
            r2 = runner.invoke(
                app,
                ["kontakto", "modifi", f"#{uuid_prefix}", "-K", "1", "-k", "laboro"],
            )
        assert r2.exit_code == 0

        list2 = runner.invoke(app, ["kontakto", "listigi"])
        assert "1" in list2.output
        assert "laboro" in list2.output

        with patch("autish.commands.retposto._confirm_esperante", return_value=True):
            r3 = runner.invoke(app, ["kontakto", "forigi", f"#{uuid_prefix}"])
        assert r3.exit_code == 0

        list3 = runner.invoke(app, ["kontakto", "listigi"])
        assert "alice@example.com" not in list3.output

        r4 = runner.invoke(app, ["kontakto", "malfari"])
        assert r4.exit_code == 0
        list4 = runner.invoke(app, ["kontakto", "listigi"])
        assert "alice@example.com" in list4.output

    def test_category_management(self, isolated_retposto_db):
        r1 = runner.invoke(app, ["kontakto", "kategorio", "aldoni", "familio"])
        assert r1.exit_code == 0
        r2 = runner.invoke(app, ["kontakto", "kategorio", "listigi"])
        assert r2.exit_code == 0
        assert "familio" in r2.output
        r3 = runner.invoke(app, ["kontakto", "kategorio", "forigi", "familio"])
        assert r3.exit_code == 0

    def test_kontakto_supports_standard_profile_fields(self, isolated_retposto_db):
        r1 = runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "person@example.com",
                "-n",
                "Ada",
                "-F",
                "Lovelace",
                "-d",
                "18151210",
                "--naskig-loko",
                "London",
                "-l",
                "en,fr",
                "-o",
                "Analytical",
                "--organiza-identiga-numero",
                "ORG-42",
                "--telefonnumero",
                "0033123456789:hejmo:prima",
                "-r",
                "person@example.com:labora:prima",
                "-p",
                "10 Downing Street",
                "-k",
                "fako:matematiko",
            ],
        )
        assert r1.exit_code == 0
        list_out = runner.invoke(app, ["kontakto", "listigi"])
        assert "person@example.com" in list_out.output
        uuid_prefix = None
        for line in list_out.output.splitlines():
            if "person@example.com" in line and "#" in line:
                uuid_prefix = line.split("#", 1)[1][:8]
                break
        assert uuid_prefix is not None
        vidi = runner.invoke(app, ["kontakto", "vidi", f"#{uuid_prefix}"])
        assert vidi.exit_code == 0
        assert "Ada" in vidi.output
        assert "LOVELACE" in vidi.output
        assert "ORG-42" in vidi.output
        assert "matematiko" in vidi.output
        assert "10 Downing Street" in vidi.output

    def test_kontakto_aldoni_allows_missing_email(self, isolated_retposto_db):
        res = runner.invoke(
            app, ["kontakto", "aldoni", "-n", "No Mail", "-o", "Org"]
        )
        assert res.exit_code == 0
        assert "Saviĝis kontakto" in res.output
        out = runner.invoke(app, ["kontakto", "serci", "--nomo", "No Mail"])
        assert "1" in out.output

    def test_kontakto_naskig_dato_accepts_yyyymmdd(self, isolated_retposto_db):
        res = runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "date@example.com",
                "-n",
                "Date",
                "-d",
                "20260131",
            ],
        )
        assert res.exit_code == 0
        search = runner.invoke(
            app, ["kontakto", "serci", "--nomo", "Date", "--naskig-dato", "20260131"]
        )
        assert search.exit_code == 0
        assert "date@example.com" in search.output

    def test_kontakto_naskig_dato_rejects_dashed_format(self, isolated_retposto_db):
        res = runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "date2@example.com",
                "-n",
                "Date2",
                "-d",
                "2026-01-31",
            ],
        )
        assert res.exit_code != 0
        assert "YYYYMMDD" in (res.output + (res.stderr or ""))

    def test_kontakto_vidi_missing_identifier_shows_hash_hint(
        self, isolated_retposto_db
    ):
        res = runner.invoke(app, ["kontakto", "vidi"])
        assert res.exit_code != 0
        output = res.output + (res.stderr or "")
        assert "Mankas identigilo" in output
        assert 'kontakto vidi "#' in output

    def test_kontakto_aldoni_requires_identity_fields(self, isolated_retposto_db):
        res = runner.invoke(app, ["kontakto", "aldoni", "mail@example.com"])
        assert res.exit_code != 0

    def test_kontakto_modifi_updates_konfirmita_without_email(
        self, isolated_retposto_db
    ):
        add = runner.invoke(app, ["kontakto", "aldoni", "-n", "Only Name", "-o", "Org"])
        assert add.exit_code == 0
        listing = runner.invoke(app, ["kontakto", "listigi"])
        uuid_prefix = None
        for line in listing.output.splitlines():
            if "Only Name" in line and "#" in line:
                uuid_prefix = line.split("#", 1)[1][:8]
                break
        assert uuid_prefix is not None
        mod = runner.invoke(app, ["kontakto", "modifi", f"#{uuid_prefix}", "-K", "0"])
        assert mod.exit_code == 0
        vidi = runner.invoke(app, ["kontakto", "vidi", f"#{uuid_prefix}"])
        assert "konfirmita" in vidi.output
        assert "0" in vidi.output

    def test_kontakto_aldoni_duplicate_prompts_update_existing(
        self, isolated_retposto_db
    ):
        runner.invoke(
            app,
            ["kontakto", "aldoni", "first@example.com", "-n", "Ada", "-F", "Lovelace"],
        )
        with patch("autish.commands.retposto._confirm_esperante", return_value=True):
            res = runner.invoke(
                app,
                [
                    "kontakto",
                    "aldoni",
                    "second@example.com",
                    "-n",
                    "Ada",
                    "-F",
                    "Lovelace",
                ],
            )
        assert res.exit_code == 0
        list_out = runner.invoke(app, ["kontakto", "serci", "--nomo", "Ada"])
        # Updated existing entry instead of creating a second duplicate.
        assert "second@example.com" in list_out.output
        assert "first@example.com" not in list_out.output

    def test_kontakto_aldoni_duplicate_can_create_new(self, isolated_retposto_db):
        runner.invoke(
            app,
            ["kontakto", "aldoni", "first@example.com", "-n", "Ada", "-F", "Lovelace"],
        )
        with patch("autish.commands.retposto._confirm_esperante", return_value=False):
            res = runner.invoke(
                app,
                [
                    "kontakto",
                    "aldoni",
                    "second@example.com",
                    "-n",
                    "Ada",
                    "-F",
                    "Lovelace",
                ],
            )
        assert res.exit_code == 0
        out = runner.invoke(app, ["kontakto", "serci", "--nomo", "Ada"])
        assert "first@example.com" in out.output
        assert "second@example.com" in out.output

    def test_kontakto_serci_exact_and_fuzzy(self, isolated_retposto_db):
        runner.invoke(app, ["kontakto", "aldoni", "alice@example.com", "-n", "Alice"])
        runner.invoke(app, ["kontakto", "aldoni", "alyce@example.com", "-n", "Alyce"])
        exact = runner.invoke(app, ["kontakto", "serci", "alice"])
        assert exact.exit_code == 0
        assert "alice@example.com" in exact.output
        fuzzy = runner.invoke(app, ["kontakto", "serci", "alise", "-f"])
        assert fuzzy.exit_code == 0
        assert "alice@example.com" in fuzzy.output

    def test_kontakto_serci_supports_combined_field_filters(self, isolated_retposto_db):
        runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "ada@math.org",
                "-n",
                "Ada",
                "-F",
                "Lovelace",
                "-o",
                "Analytical",
                "-l",
                "en,fr",
                "-k",
                "esploro",
                "-c",
                "rolo:programisto",
                "-K",
                "1",
            ],
        )
        runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "grace@navy.mil",
                "-n",
                "Grace",
                "-F",
                "Hopper",
                "-o",
                "Navy",
                "-l",
                "en",
                "-k",
                "laboro",
                "-c",
                "rolo:admiralo",
                "-K",
                "0",
            ],
        )
        res = runner.invoke(
            app,
            [
                "kontakto",
                "serci",
                "--nomo",
                "Ada",
                "--familia-nomo",
                "Lovelace",
                "--organizo",
                "Analytical",
                "--lingvo",
                "en",
                "--kategorio",
                "esploro",
                "--kampo",
                "rolo:programisto",
                "--konfirmita",
                "1",
            ],
        )
        assert res.exit_code == 0
        assert "ada@math.org" in res.output
        assert "grace@navy.mil" not in res.output
        assert "Organizo" in res.output
        assert "Familia-nomo" in res.output
        assert "UUID" in res.output

    def test_kontakto_serci_fuzzy_applies_to_filtered_email_field(
        self, isolated_retposto_db
    ):
        runner.invoke(app, ["kontakto", "aldoni", "hello@ronzz.org", "-n", "Hello"])
        res = runner.invoke(
            app,
            ["kontakto", "serci", "--retpostadreso", "hallo", "--fuzzy"],
        )
        assert res.exit_code == 0
        assert "hello@ronzz.org" in res.output

    def test_kontakto_serci_includes_manually_added_retposhtadreso(
        self, isolated_retposto_db
    ):
        add = runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "-n",
                "Manual Mail",
                "-o",
                "Org",
                "-r",
                "manual@example.com:labora:prima",
            ],
        )
        assert add.exit_code == 0, add.output

        by_query = runner.invoke(app, ["kontakto", "serci", "manual@example.com"])
        assert by_query.exit_code == 0, by_query.output
        assert "manual@example.com" in by_query.output

        by_filter = runner.invoke(
            app,
            ["kontakto", "serci", "--retpostadreso", "manual@example.com"],
        )
        assert by_filter.exit_code == 0, by_filter.output
        assert "manual@example.com" in by_filter.output

    def test_kontakto_serci_filters_by_postadreso(self, isolated_retposto_db):
        runner.invoke(
            app,
            [
                "kontakto",
                "aldoni",
                "post@example.com",
                "-n",
                "Post",
                "-p",
                "Rue de Metz",
            ],
        )
        res = runner.invoke(app, ["kontakto", "serci", "--postadreso", "Metz"])
        assert res.exit_code == 0
        assert "post@example.com" in res.output

    def test_kontakto_serci_requires_query_or_filter(self, isolated_retposto_db):
        res = runner.invoke(app, ["kontakto", "serci"])
        assert res.exit_code != 0

    def test_kontakto_regex_search_and_bulk_modify(self, isolated_retposto_db):
        runner.invoke(app, ["kontakto", "aldoni", "alpha@example.com", "-n", "Alpha"])
        runner.invoke(app, ["kontakto", "aldoni", "beta@example.com", "-n", "Beta"])
        rx = runner.invoke(app, ["kontakto", "serci", "alp.*@example\\.com", "-R"])
        assert rx.exit_code == 0
        assert "alpha@example.com" in rx.output
        with patch("autish.commands.retposto._confirm_esperante", return_value=True):
            mod = runner.invoke(
                app,
                [
                    "kontakto",
                    "modifi",
                    "-R",
                    ".*@example\\.com",
                    "-K",
                    "1",
                ],
            )
        assert mod.exit_code == 0
        out = runner.invoke(app, ["kontakto", "listigi"])
        assert "alpha@example.com" in out.output
        assert "beta@example.com" in out.output
        assert "1" in out.output

    def test_kontakto_bulk_delete_with_regex(self, isolated_retposto_db):
        runner.invoke(app, ["kontakto", "aldoni", "one@example.com", "-n", "One"])
        runner.invoke(app, ["kontakto", "aldoni", "two@example.com", "-n", "Two"])
        with patch("autish.commands.retposto._confirm_esperante", return_value=True):
            res = runner.invoke(
                app,
                ["kontakto", "forigi", "-R", ".*@example\\.com"],
            )
        assert res.exit_code == 0
        out = runner.invoke(app, ["kontakto", "listigi"])
        assert "one@example.com" not in out.output
        assert "two@example.com" not in out.output

    def test_kontakto_purigi_supports_exclusion_selection(self, isolated_retposto_db):
        runner.invoke(
            app, ["kontakto", "aldoni", "newsletter@example.com", "-n", "Auto"]
        )
        runner.invoke(
            app, ["kontakto", "aldoni", "notification@example.com", "-n", "Notif"]
        )
        purigi = runner.invoke(app, ["kontakto", "purigi"], input="! 2\n")
        assert purigi.exit_code == 0
        out = runner.invoke(app, ["kontakto", "listigi"])
        # We excluded action 2, so one automated address should remain.
        assert (
            "newsletter@example.com" in out.output
            or "notification@example.com" in out.output
        )
