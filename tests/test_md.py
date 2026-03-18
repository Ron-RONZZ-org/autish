"""Tests for autish.commands.md (Markdown utilities)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from autish.commands.md import (
    _IMPORT_FORMATS,
    _build_html,
    _markdown_to_html_body,
    _source_title,
)
from autish.main import app

runner = CliRunner()

# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — pure helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestSourceTitle:
    def test_file_path_uses_stem(self):
        assert _source_title("/home/user/notes.md") == "notes"

    def test_http_url_returns_markdown(self):
        assert _source_title("http://example.com/page.md") == "Markdown"

    def test_https_url_returns_markdown(self):
        assert _source_title("https://example.com/readme.md") == "Markdown"

    def test_filename_without_extension(self):
        assert _source_title("README") == "README"


class TestMarkdownToHtmlBody:
    def test_converts_heading(self):
        html = _markdown_to_html_body("# Hello")
        assert "<h1" in html
        assert "Hello" in html

    def test_converts_bold(self):
        html = _markdown_to_html_body("**bold**")
        assert "<strong>bold</strong>" in html

    def test_converts_code_block(self):
        html = _markdown_to_html_body("```\ncode\n```")
        assert "<code" in html

    def test_converts_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = _markdown_to_html_body(md)
        assert "<table>" in html


class TestBuildHtml:
    def test_returns_complete_html_document(self):
        html = _build_html("# Hello")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_includes_katex_script(self):
        html = _build_html("# Hello")
        assert "katex" in html.lower()

    def test_includes_collapsible_script(self):
        html = _build_html("# Hello")
        assert "makeCollapsible" in html

    def test_title_appears_in_head(self):
        html = _build_html("# Hello", title="My Doc")
        assert "<title>My Doc</title>" in html

    def test_fold_notice_shown_when_foldlevel_nonzero(self):
        html = _build_html("# Hello", fold_level=2)
        assert "fold-notice" in html
        assert "2" in html

    def test_no_fold_notice_when_fold_level_zero(self):
        html = _build_html("# Hello", fold_level=0)
        assert '<p class="fold-notice">' not in html

    def test_fold_level_in_script(self):
        html = _build_html("# Hello", fold_level=3)
        assert "var foldLevel = 3;" in html

    def test_fold_level_zero_in_script(self):
        html = _build_html("# Hello", fold_level=0)
        assert "var foldLevel = 0;" in html


# ──────────────────────────────────────────────────────────────────────────────
# CLI command tests
# ──────────────────────────────────────────────────────────────────────────────


class TestVidi:
    def test_opens_browser_with_temp_file(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nWorld", encoding="utf-8")

        with patch("autish.commands.md.webbrowser.open") as mock_open:
            result = runner.invoke(app, ["md", "vidi", str(md_file)])

        assert result.exit_code == 0
        mock_open.assert_called_once()
        called_url = mock_open.call_args[0][0]
        assert called_url.startswith("file://")
        assert called_url.endswith(".html")

    def test_faldnivelo_option(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\n## Sub\n\ncontent", encoding="utf-8")

        written_html = []

        original_open = open

        def capture_write(path, mode="r", **kwargs):
            fh = original_open(path, mode, **kwargs)
            if mode == "w" and path.endswith(".html"):
                written_html.append(fh)
            return fh

        with (
            patch("autish.commands.md.webbrowser.open"),
            patch("builtins.open", side_effect=capture_write),
        ):
            pass  # Just check that the command accepts the flag

        with patch("autish.commands.md.webbrowser.open"):
            result = runner.invoke(app, ["md", "vidi", str(md_file), "-f", "2"])
        assert result.exit_code == 0

    def test_file_not_found(self):
        result = runner.invoke(app, ["md", "vidi", "/nonexistent/file.md"])
        assert result.exit_code != 0

    def test_generated_html_has_content(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\nHello world.", encoding="utf-8")

        captured_paths: list[str] = []

        def fake_open(url: str) -> None:
            captured_paths.append(url.replace("file://", ""))

        with patch("autish.commands.md.webbrowser.open", side_effect=fake_open):
            runner.invoke(app, ["md", "vidi", str(md_file)])

        assert captured_paths
        html_path = Path(captured_paths[0])
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "Hello world" in content
        assert "<!DOCTYPE html>" in content


class TestEksporti:
    def test_exports_html_file(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nWorld", encoding="utf-8")
        dest = tmp_path / "output.html"

        result = runner.invoke(
            app, ["md", "eksporti", str(md_file), str(dest)]
        )

        assert result.exit_code == 0
        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Hello" in content

    def test_exports_html_format_explicit(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hi", encoding="utf-8")
        dest = tmp_path / "out.html"

        result = runner.invoke(
            app,
            ["md", "eksporti", str(md_file), str(dest), "-f", "html"],
        )
        assert result.exit_code == 0
        assert dest.exists()

    def test_invalid_format_exits_nonzero(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hi", encoding="utf-8")
        dest = tmp_path / "out.xyz"

        result = runner.invoke(
            app,
            ["md", "eksporti", str(md_file), str(dest), "-f", "xyz"],
        )
        assert result.exit_code != 0
        assert "nesubtenata" in result.output.lower() or "xyz" in result.output

    def test_pdf_without_weasyprint_exits_nonzero(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello", encoding="utf-8")
        dest = tmp_path / "out.pdf"

        with patch.dict("sys.modules", {"weasyprint": None}):
            result = runner.invoke(
                app,
                ["md", "eksporti", str(md_file), str(dest), "-f", "pdf"],
            )
        assert result.exit_code != 0

    def test_creates_parent_directories(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hi", encoding="utf-8")
        dest = tmp_path / "sub" / "dir" / "output.html"

        result = runner.invoke(
            app, ["md", "eksporti", str(md_file), str(dest)]
        )
        assert result.exit_code == 0
        assert dest.exists()

    def test_source_not_found_exits_nonzero(self, tmp_path):
        dest = tmp_path / "out.html"
        result = runner.invoke(
            app, ["md", "eksporti", "/no/such/file.md", str(dest)]
        )
        assert result.exit_code != 0


class TestImporti:
    def test_unsupported_format_exits_nonzero(self, tmp_path):
        src = tmp_path / "doc.xyz"
        src.write_text("data", encoding="utf-8")
        dest = tmp_path / "out.md"

        result = runner.invoke(app, ["md", "importi", str(src), str(dest)])
        assert result.exit_code != 0
        assert "xyz" in result.output

    def test_source_not_found_exits_nonzero(self, tmp_path):
        dest = tmp_path / "out.md"
        result = runner.invoke(
            app, ["md", "importi", "/no/such/file.docx", str(dest)]
        )
        assert result.exit_code != 0

    @pytest.mark.parametrize("ext", list(_IMPORT_FORMATS))
    def test_supported_format_calls_pandoc(self, ext, tmp_path):
        src = tmp_path / f"doc.{ext}"
        src.write_text("content", encoding="utf-8")
        dest = tmp_path / "out.md"
        dest.write_text("# result", encoding="utf-8")

        with (
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # pandoc --version
                    MagicMock(returncode=0),  # pandoc conversion
                ],
            ) as mock_run,
        ):
            result = runner.invoke(app, ["md", "importi", str(src), str(dest)])

        assert result.exit_code == 0
        assert mock_run.call_count == 2
        version_call = mock_run.call_args_list[0]
        assert version_call[0][0][0] == "pandoc"

    def test_pandoc_not_installed_exits_nonzero(self, tmp_path):
        src = tmp_path / "doc.docx"
        src.write_text("content", encoding="utf-8")
        dest = tmp_path / "out.md"

        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("pandoc not found"),
        ):
            result = runner.invoke(app, ["md", "importi", str(src), str(dest)])
        assert result.exit_code != 0

    def test_pandoc_conversion_error_exits_nonzero(self, tmp_path):
        src = tmp_path / "doc.html"
        src.write_text("<h1>Hello</h1>", encoding="utf-8")
        dest = tmp_path / "out.md"

        def _run_side_effect(cmd, **kwargs):
            if "--version" in cmd:
                return MagicMock(returncode=0)
            raise subprocess.CalledProcessError(1, cmd, stderr="conversion failed")

        with patch("subprocess.run", side_effect=_run_side_effect):
            result = runner.invoke(app, ["md", "importi", str(src), str(dest)])
        assert result.exit_code != 0


class TestMdRegistration:
    def test_md_in_autish_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "md" in result.output

    def test_md_help_shows_subcommands(self):
        result = runner.invoke(app, ["md", "--help"])
        assert result.exit_code == 0
        assert "vidi" in result.output
        assert "eksporti" in result.output
        assert "importi" in result.output
