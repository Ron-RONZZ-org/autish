from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner
from yt_dlp.utils import DownloadError

from autish.main import app

runner = CliRunner()


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, query, download=False):
        if "playlist" in str(query):
            return {
                "entries": [
                    {
                        "_type": "playlist",
                        "id": "pl1",
                        "title": "Playlist One",
                        "uploader": "Canal",
                        "url": "https://www.youtube.com/playlist?list=PL1",
                    }
                ]
            }
        if str(query).startswith("ytsearch"):
            return {
                "entries": [
                    {
                        "id": "vid1",
                        "title": "Test one",
                        "description": "long desc",
                        "uploader": "Canal",
                        "upload_date": "20260301",
                        "view_count": 10,
                        "channel_follower_count": 5,
                        "webpage_url": "https://www.youtube.com/watch?v=vid1",
                    }
                ]
            }
        return {"id": "vid1", "title": "Test one", "filesize_approx": 1024}

    def prepare_filename(self, item):
        title = str(item.get("title") or "video")
        ext = str(item.get("ext") or "mp4")
        vid = str(item.get("id") or "vid")
        outtmpl = str(self.opts.get("outtmpl") or "%(title)s [%(id)s].%(ext)s")
        rendered = outtmpl.replace("%(title).80s", title).replace("%(title)s", title)
        rendered = rendered.replace("%(id)s", vid).replace("%(ext)s", ext)
        return rendered


def test_serci_outputs_table_and_saves_cache(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    result = runner.invoke(app, ["filmeto", "serci", "Test", "-a"])
    assert result.exit_code == 0, result.output
    assert "Test one" in result.output
    cache = json.loads((tmp_path / "filmeto_cache.json").read_text(encoding="utf-8"))
    assert len(cache) == 1
    assert "2026-03-01" in result.output


def test_serci_limo_limits_results(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    class _ManyYDL(_FakeYDL):
        def extract_info(self, query, download=False):
            if str(query).startswith("ytsearch"):
                entries = []
                for idx in range(6):
                    entries.append({
                        "id": f"vid{idx}",
                        "title": f"Test {idx}",
                        "description": "desc",
                        "uploader": "Canal",
                        "upload_date": "20260301",
                        "webpage_url": f"https://www.youtube.com/watch?v=vid{idx}",
                    })
                return {"entries": entries}
            return super().extract_info(query, download=download)

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _ManyYDL)
    result = runner.invoke(app, ["filmeto", "serci", "Test", "-l", "3"])
    assert result.exit_code == 0, result.output
    assert "Test 0" in result.output
    assert "Test 1" in result.output
    assert "Test 2" in result.output
    assert "Test 4" not in result.output


def test_serci_filters_by_priskribo_and_fonto(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    class _FilterYDL(_FakeYDL):
        def extract_info(self, query, download=False):
            if str(query).startswith("ytsearch"):
                return {
                    "entries": [
                        {
                            "id": "good",
                            "title": "Search title",
                            "description": "deep matching description",
                            "uploader": "Alpha Channel",
                            "upload_date": "20260301",
                            "webpage_url": "https://www.youtube.com/watch?v=good",
                        },
                        {
                            "id": "bad",
                            "title": "Other",
                            "description": "irrelevant",
                            "uploader": "Beta",
                            "upload_date": "20260301",
                            "webpage_url": "https://www.youtube.com/watch?v=bad",
                        },
                    ]
                }
            return super().extract_info(query, download=download)

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FilterYDL)
    result = runner.invoke(
        app,
        [
            "filmeto",
            "serci",
            "Search",
            "--priskribo",
            "matching",
            "--fonto",
            "alpha",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Search title" in result.output
    assert "Other" not in result.output


def test_serci_fuzzy_title_match(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    result = runner.invoke(app, ["filmeto", "serci", "tst one"])
    assert result.exit_code == 0, result.output
    assert "Test one" in result.output


def test_serci_regex_match(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    result = runner.invoke(app, ["filmeto", "serci", "^Test.*", "--regex"])
    assert result.exit_code == 0, result.output
    assert "Test one" in result.output


def test_serci_invalid_regex_fails(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    result = runner.invoke(app, ["filmeto", "serci", "([", "--regex"])
    assert result.exit_code != 0
    assert "Nevalida regex-esprimo" in (result.output + (result.stderr or ""))


def test_serci_playlist_option_shows_playlist_table(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    result = runner.invoke(app, ["filmeto", "serci", "Test", "--playlistoj", "-l", "3"])
    assert result.exit_code == 0, result.output
    assert "Playlistoj" in result.output
    assert "Playlist One" in result.output


def test_elsuti_warns_for_large_download_and_can_cancel(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "YoutubeDL", _FakeYDL)
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "10:00",
                "author": "Kanalo",
                "size_bytes": 600 * 1024 * 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )
    result = runner.invoke(app, ["filmeto", "elsuti", uid], input="n\n")
    assert result.exit_code == 0
    assert "Nuligita." in result.output


def test_vidi_downloads_and_opens(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )

    downloaded = tmp_path / "video.mp4"
    downloaded.write_bytes(b"x")
    monkeypatch.setattr(mod, "_run_download", lambda *_a, **_k: [downloaded])
    with patch("autish.commands.filmeto.subprocess.run") as mocked_run:
        result = runner.invoke(app, ["filmeto", "vidi", uid])
    assert result.exit_code == 0, result.output
    mocked_run.assert_called_once()


def test_vidi_playlist_shows_table(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "pl123456"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/playlist?list=PLX"}),
        encoding="utf-8",
    )

    class _PlaylistYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, query, download=False):
            return {
                "entries": [
                    {"id": "v1", "title": "Video 1", "uploader": "A"},
                    {"id": "v2", "title": "Video 2", "uploader": "B"},
                ]
            }

    monkeypatch.setattr(mod, "YoutubeDL", _PlaylistYDL)
    result = runner.invoke(app, ["filmeto", "vidi", uid])
    assert result.exit_code == 0, result.output
    assert "Playlisto" in result.output
    assert "Video 1" in result.output


def test_elsuti_supports_target_folder_option(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "downloads"
    called: dict[str, str] = {}

    def _fake_run_download(_targets, output_dir, *_a, **_k):
        called["dir"] = str(output_dir)
        return []

    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )
    monkeypatch.setattr(mod, "_run_download", _fake_run_download)
    result = runner.invoke(
        app,
        ["filmeto", "elsuti", uid, "--vojo", str(out_dir)],
        input="j\nj\n",
    )
    assert result.exit_code == 0, result.output
    assert called["dir"] == str(out_dir.resolve())


def test_elsuti_full_output_path_strips_extension(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    target_file = tmp_path / "movie.mp4"
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )

    def _fake_run_download(_targets, output_dir, _fmt, **kwargs):
        captured["dir"] = str(output_dir)
        captured["tmpl"] = str(kwargs.get("outtmpl_name"))
        return []

    monkeypatch.setattr(mod, "_run_download", _fake_run_download)
    result = runner.invoke(
        app, ["filmeto", "elsuti", uid, "--vojo", str(target_file)], input="j\n"
    )
    assert result.exit_code == 0, result.output
    assert captured["dir"] == str(tmp_path.resolve())
    assert captured["tmpl"].startswith("movie.")
    assert captured["tmpl"].endswith(".%(ext)s")


def test_elsuti_passes_subtitles_options(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )

    def _fake_run_download(_targets, _output_dir, _fmt, **kwargs):
        captured["subs"] = str(kwargs.get("subtitles"))
        return []

    monkeypatch.setattr(mod, "_run_download", _fake_run_download)
    result = runner.invoke(
        app,
        ["filmeto", "elsuti", uid, "--subtitoloj", "eo,en"],
        input="j\n",
    )
    assert result.exit_code == 0, result.output
    assert captured["subs"] == "eo,en"


def test_filmeto_agordi_sets_default_folder(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "filmeto_agordo.json")
    target = tmp_path / "myvideos"
    result = runner.invoke(
        app,
        ["filmeto", "agordi", "--vojo", str(target)],
        input="j\n",
    )
    assert result.exit_code == 0, result.output
    assert target.exists()
    cfg = json.loads((tmp_path / "filmeto_agordo.json").read_text(encoding="utf-8"))
    assert cfg["defauxlta_vojo"] == str(target.resolve())


def test_filmeto_agordi_defaults_to_downloads_when_not_set(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    fake_home = tmp_path / "home"
    (fake_home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(mod.Path, "home", lambda: fake_home)
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "filmeto_agordo.json")
    result = runner.invoke(app, ["filmeto", "agordi"])
    assert result.exit_code == 0, result.output
    assert "Downloads" in result.output


def test_elsuti_uses_default_folder_from_agordo(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "filmeto_agordo.json")
    default_dir = tmp_path / "stored"
    default_dir.mkdir()
    (tmp_path / "filmeto_agordo.json").write_text(
        json.dumps({"defauxlta_vojo": str(default_dir)}),
        encoding="utf-8",
    )
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    called: dict[str, str] = {}
    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )
    def _fake_download(_targets, output_dir, *_a, **_k):
        called["dir"] = str(output_dir)
        return []

    monkeypatch.setattr(mod, "_run_download", _fake_download)
    result = runner.invoke(app, ["filmeto", "elsuti", uid], input="j\n")
    assert result.exit_code == 0, result.output
    assert called["dir"] == str(default_dir.resolve())


def test_elsuti_relative_vojo_uses_agordi_default_base(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "filmeto_agordo.json")
    default_dir = tmp_path / "stored"
    default_dir.mkdir()
    (tmp_path / "filmeto_agordo.json").write_text(
        json.dumps({"defauxlta_vojo": str(default_dir)}),
        encoding="utf-8",
    )
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/watch?v=vid1"}),
        encoding="utf-8",
    )
    called: dict[str, str] = {}
    monkeypatch.setattr(
        mod,
        "_collect_download_plan",
        lambda *_a, **_k: [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ],
    )

    def _fake_download(_targets, output_dir, *_a, **_k):
        called["dir"] = str(output_dir)
        return []

    monkeypatch.setattr(mod, "_run_download", _fake_download)
    result = runner.invoke(
        app, ["filmeto", "elsuti", uid, "--vojo", "sub"], input="j\nj\n"
    )
    assert result.exit_code == 0, result.output
    assert called["dir"] == str((default_dir / "sub").resolve())


def test_auto_js_runtimes_detects_node(monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(
        mod.shutil,
        "which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    runtimes = mod._auto_js_runtimes()
    assert runtimes is not None
    assert runtimes.get("node", {}).get("path") == "/usr/bin/node"


def test_extract_entries_retry_on_requested_format(monkeypatch):
    import autish.commands.filmeto as mod

    class _FmtYDL:
        calls = []

        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            _FmtYDL.calls.append(dict(self.opts))
            if self.opts.get("extract_flat") is False:
                raise DownloadError("Requested format is not available")
            return {"entries": [{"id": "ok", "title": "ok", "availability": "public"}]}

    monkeypatch.setattr(mod, "YoutubeDL", _FmtYDL)
    entries = mod._extract_entries_for_search("abc", limo=2)
    assert entries
    assert any(call.get("extract_flat") is True for call in _FmtYDL.calls)


def test_elsuti_passes_playlist_limo(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "filmeto_cache.json")
    uid = "abc12345"
    (tmp_path / "filmeto_cache.json").write_text(
        json.dumps({uid: "https://www.youtube.com/playlist?list=PLX"}),
        encoding="utf-8",
    )
    called: dict[str, int] = {}

    def _fake_plan(_targets, _fmt, **kwargs):
        called["limo"] = int(kwargs.get("playlist_limo") or 0)
        return [
            {
                "title": "Video 1",
                "duration": "01:00",
                "author": "Kanalo",
                "size_bytes": 1024,
                "raw": {"title": "Video 1", "id": "vid1", "ext": "mp4"},
            }
        ]

    monkeypatch.setattr(mod, "_collect_download_plan", _fake_plan)
    monkeypatch.setattr(mod, "_run_download", lambda *_a, **_k: [])
    result = runner.invoke(app, ["filmeto", "elsuti", uid, "-l", "2"], input="j\n")
    assert result.exit_code == 0, result.output
    assert called["limo"] == 2


def test_serci_bot_error_shows_cookie_hint(monkeypatch):
    from yt_dlp.utils import DownloadError

    import autish.commands.filmeto as mod

    def _boom(*_a, **_k):
        raise DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(mod, "_extract_entries_for_search", _boom)
    result = runner.invoke(app, ["filmeto", "serci", "abc"])
    assert result.exit_code != 0
    assert "--kuketoj" in (result.output + (result.stderr or ""))


def test_cookies_from_browser_supports_floorp_alias():
    import autish.commands.filmeto as mod

    assert mod._cookies_from_browser_arg("floorp") == ("firefox",)


def test_cookies_from_browser_supports_profile_syntax():
    import autish.commands.filmeto as mod

    assert mod._cookies_from_browser_arg("floorp:/tmp/profile") == (
        "firefox",
        "/tmp/profile",
        None,
        None,
    )


def test_extract_entries_filters_unavailable(monkeypatch):
    import autish.commands.filmeto as mod

    class _FilterYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            return {
                "entries": [
                    {"id": "a", "title": "ok", "availability": "public"},
                    {"id": "b", "title": "bad", "availability": "unavailable"},
                ]
            }

    monkeypatch.setattr(mod, "YoutubeDL", _FilterYDL)
    entries = mod._extract_entries_for_search("x", limo=5)
    assert len(entries) == 1
    assert entries[0]["id"] == "a"


def test_serci_when_all_unavailable_shows_profile_help(monkeypatch):
    import autish.commands.filmeto as mod

    class _UnavailableYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            return {
                "entries": [
                    {"id": "a", "title": "nope", "availability": "unavailable"},
                ]
            }

    monkeypatch.setattr(mod, "YoutubeDL", _UnavailableYDL)
    result = runner.invoke(
        app,
        ["filmeto", "serci", "abc", "--kuketoj-de-retumilo", "floorp"],
    )
    assert result.exit_code != 0
    output = result.output + (result.stderr or "")
    assert ".floorp" in output
    assert "floorp:/plena/vojo/al/profilo" in output


def test_kuketoj_helpo_command_outputs_cli_steps():
    result = runner.invoke(app, ["filmeto", "kuketoj-helpo"])
    assert result.exit_code == 0
    assert "yt-dlp --cookies-from-browser floorp" in result.output
    assert "--kuketoj /tmp/youtube.cookies.txt" in result.output
    assert "find ~/.floorp -maxdepth 3 -name cookies.sqlite" in result.output
    assert "nodejs" in result.output


def test_extract_entries_retries_with_nocheckcertificate_on_ssl(monkeypatch):
    import autish.commands.filmeto as mod

    class _RetryYDL:
        calls = []

        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            _RetryYDL.calls.append(dict(self.opts))
            if not self.opts.get("nocheckcertificate"):
                raise DownloadError(
                    "certificate verify failed: Hostname mismatch "
                    "(CERTIFICATE_VERIFY_FAILED)"
                )
            return {"entries": [{"id": "ok", "title": "ok", "availability": "public"}]}

    monkeypatch.setattr(mod, "YoutubeDL", _RetryYDL)
    entries = mod._extract_entries_for_search("abc", limo=2)
    assert entries
    assert any(call.get("nocheckcertificate") for call in _RetryYDL.calls)


def test_cookie_browser_candidates_discovers_floorp_profiles(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    fake_home = tmp_path / "home"
    profile = fake_home / ".floorp" / "abc.default-default"
    profile.mkdir(parents=True)
    (profile / "cookies.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr(mod.Path, "home", lambda: fake_home)
    candidates = mod._cookie_browser_candidates("floorp")
    assert ("firefox",) in candidates
    assert ("firefox", str(profile), None, None) in candidates


def test_cookie_browser_candidates_with_explicit_profile_adds_fallbacks(
    tmp_path, monkeypatch
):
    import autish.commands.filmeto as mod

    fake_home = tmp_path / "home"
    profile = fake_home / ".floorp" / "abc.default-default"
    profile.mkdir(parents=True)
    (profile / "cookies.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr(mod.Path, "home", lambda: fake_home)
    candidates = mod._cookie_browser_candidates("floorp:/tmp/specific")
    assert ("firefox", "/tmp/specific", None, None) in candidates
    assert ("firefox", str(profile), None, None) in candidates
    assert None in candidates


def test_extract_entries_prefers_cached_strategy(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_SEARCH_STRATEGY_FILE", tmp_path / "strategy.json")
    mod._save_search_strategy({"opts": {"quiet": True, "extract_flat": True}})

    class _CachedYDL:
        calls = []

        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _query, download=False):
            _CachedYDL.calls.append(dict(self.opts))
            return {"entries": [{"id": "ok", "title": "ok", "availability": "public"}]}

    monkeypatch.setattr(mod, "YoutubeDL", _CachedYDL)
    entries = mod._extract_entries_for_search("x", limo=3)
    assert entries
    assert _CachedYDL.calls[0].get("extract_flat") is True


def test_save_search_strategy_handles_non_json_types(tmp_path, monkeypatch):
    import autish.commands.filmeto as mod

    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "_SEARCH_STRATEGY_FILE", tmp_path / "strategy.json")
    mod._save_search_strategy({"opts": {"x": {1, 2, 3}}})
    loaded = json.loads((tmp_path / "strategy.json").read_text(encoding="utf-8"))
    assert sorted(loaded["opts"]["x"]) == [1, 2, 3]


def test_pick_closest_format_selector_prefers_nearest_height():
    import autish.commands.filmeto as mod

    info = {
        "formats": [
            {"format_id": "18", "height": 360},
            {"format_id": "22", "height": 720},
            {"format_id": "37", "height": 1080},
        ]
    }
    selector = mod._pick_closest_format_selector(
        info,
        difino=700,
        sonkvalito=None,
        audio=False,
        filmeto=False,
    )
    assert selector == "22"
