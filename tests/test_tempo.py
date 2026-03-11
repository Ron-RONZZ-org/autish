"""Tests for autish.commands.tempo."""

from __future__ import annotations

import datetime
import re

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def _is_iso(s: str) -> bool:
    """Return True if *s* looks like an ISO 8601 datetime string."""
    return bool(re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s))


class TestTempoDefault:
    def test_exits_zero(self):
        result = runner.invoke(app, ["tempo"])
        assert result.exit_code == 0

    def test_first_line_is_iso(self):
        result = runner.invoke(app, ["tempo"])
        lines = result.output.strip().splitlines()
        assert len(lines) >= 1
        assert _is_iso(lines[0]), f"Expected ISO datetime, got: {lines[0]!r}"

    def test_second_line_is_day_name(self):
        result = runner.invoke(app, ["tempo"])
        lines = result.output.strip().splitlines()
        assert len(lines) == 2
        # Day name should be a non-empty string (letters in any script, possibly
        # with locale-specific characters; must not be a bare number)
        day = lines[1].strip()
        assert day, "Day name must not be empty"
        assert re.search(r"\w", day), f"Day name has no word characters: {day!r}"


class TestTempoHorzono:
    def test_valid_positive_offset(self):
        result = runner.invoke(app, ["tempo", "--horzono", "9"])
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert _is_iso(lines[0])

    def test_valid_negative_offset(self):
        result = runner.invoke(app, ["tempo", "--horzono", "-5"])
        assert result.exit_code == 0
        assert _is_iso(result.output.strip().splitlines()[0])

    def test_boundary_minus_12(self):
        result = runner.invoke(app, ["tempo", "--horzono", "-12"])
        assert result.exit_code == 0

    def test_boundary_plus_14(self):
        result = runner.invoke(app, ["tempo", "--horzono", "14"])
        assert result.exit_code == 0

    def test_out_of_range_high(self):
        result = runner.invoke(app, ["tempo", "--horzono", "15"])
        assert result.exit_code != 0

    def test_out_of_range_low(self):
        result = runner.invoke(app, ["tempo", "--horzono", "-13"])
        assert result.exit_code != 0

    def test_non_numeric_value(self):
        result = runner.invoke(app, ["tempo", "--horzono", "abc"])
        assert result.exit_code != 0

    def test_utc_zero_produces_utc_time(self):
        # Truncate to whole seconds to match the ISO output precision
        before = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)
        result = runner.invoke(app, ["tempo", "--horzono", "0"])
        after = datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)
        assert result.exit_code == 0
        line = result.output.strip().splitlines()[0]
        # Parse the returned time and verify it's between before and after
        dt = datetime.datetime.fromisoformat(line)
        assert before <= dt <= after


class TestTempoAllOffsets:
    def test_all_offsets_flag_produces_27_lines(self):
        """There are 27 UTC offsets from -12 to +14 inclusive."""
        result = runner.invoke(app, ["tempo", "--horzono", ""])
        assert result.exit_code == 0
        lines = [ln for ln in result.output.strip().splitlines() if ln.strip()]
        assert len(lines) == 27

    def test_all_offsets_lines_contain_iso(self):
        result = runner.invoke(app, ["tempo", "--horzono", ""])
        assert result.exit_code == 0
        for line in result.output.strip().splitlines():
            # Each line has format: "UTC+N  <ISO datetime>"
            assert _is_iso(line.split()[-1]), f"Line missing ISO datetime: {line!r}"
