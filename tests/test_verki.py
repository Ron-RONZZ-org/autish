"""Tests for autish.commands.verki and verki services/providers."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from typer.testing import CliRunner

from autish.main import app
from autish.services.providers.base import GenerationRequest, VerkiProviderError
from autish.services.providers.huggingface import HuggingFaceProvider
from autish.services.verki import VerkiRequest, VerkiService, VerkiServiceError

runner = CliRunner()


class _FakeProvider:
    def __init__(self, result: str) -> None:
        self.result = result
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> str:
        self.requests.append(request)
        return self.result


def test_verki_command_registered_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "verki" in result.output


def test_verki_app_is_typer():
    from autish.commands.verki import app as verki_app

    assert verki_app is not None


def test_verki_cli_without_instruction_shows_help():
    result = runner.invoke(app, ["verki", "generi"])
    assert result.exit_code == 1  # Missing required --instrukcio
    assert "--instrukcio" in result.output or "deviga" in result.output


def test_verki_cli_parses_options_and_files(monkeypatch, tmp_path: Path):
    import autish.commands.verki as mod

    source_path = tmp_path / "fonto.txt"
    source_path.write_text("Jen malnova teksto.", encoding="utf-8")
    style_path = tmp_path / "stilo.txt"
    style_path.write_text("Mi uzas mallongajn frazojn.", encoding="utf-8")
    context_path = tmp_path / "kunteksto.txt"
    context_path.write_text("Temo: semajna raporto.", encoding="utf-8")
    captured: dict[str, VerkiRequest] = {}

    class _FakeService:
        def verki(self, request: VerkiRequest) -> str:
            captured["request"] = request
            return "Nova teksto."

    monkeypatch.setattr(mod, "_build_verki_service", lambda **_kwargs: _FakeService())

    result = runner.invoke(
        app,
        [
            "verki",
            "generi",
            "--instrukcio",
            "Reskribu por pli klara stilo",
            "--teksto-dosiero",
            str(source_path),
            "--tono",
            "trankvila",
            "--longo",
            "mallonga",
            "--registro",
            "formala",
            "--stilo",
            "rekta",
            "--stilo-dosiero",
            str(style_path),
            "--kunteksto-dosiero",
            str(context_path),
            "--maksimumaj-tokenoj",
            "120",
            "--temperaturo",
            "0.3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Nova teksto." in result.output
    request = captured["request"]
    assert request.instrukcio == "Reskribu por pli klara stilo"
    assert request.fonta_teksto == "Jen malnova teksto."
    assert request.tono == "trankvila"
    assert request.longo == "mallonga"
    assert request.registro == "formala"
    assert request.stilo == "rekta"
    assert request.stilo_ekzemplo == "Mi uzas mallongajn frazojn."
    assert request.kunteksto == "Temo: semajna raporto."
    assert request.maksimumaj_tokenoj == 120
    assert request.temperaturo == 0.3


def test_verki_cli_rejects_conflicting_text_inputs(tmp_path: Path):
    source_path = tmp_path / "fonto.txt"
    source_path.write_text("abc", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "verki",
            "generi",
            "--instrukcio",
            "Reskribu tion",
            "--teksto",
            "Sama teksto",
            "--teksto-dosiero",
            str(source_path),
        ],
    )
    assert result.exit_code != 0
    assert "Uzu nur unu fonton por fonta teksto" in (
        result.output + (result.stderr or "")
    )


def test_verki_cli_missing_hf_token_shows_clear_error(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    import autish.commands.verki as mod
    monkeypatch.setattr(mod, "_load_profile", lambda quiet=True: {})
    result = runner.invoke(
        app, ["verki", "generi", "--instrukcio", "Kreu mallongan saluton"]
    )
    assert result.exit_code != 0
    assert "HF_TOKEN" in result.output


def test_verki_service_build_prompt_contains_controls():
    provider = _FakeProvider("Rezulto")
    service = VerkiService(provider=provider)
    request = VerkiRequest(
        instrukcio="Reskribu tekston",
        fonta_teksto="Malnova versio.",
        tono="trankvila",
        longo="mallonga",
        registro="duonformala",
        stilo="rekta",
        stilo_ekzemplo="Jen mia tipa vocho.",
        kunteksto="Celo: teama resumo.",
    )
    prompt = service.build_prompt(request)
    assert "Tasko: Reskribu tekston" in prompt
    assert "Tono: trankvila" in prompt
    assert "Longeco: mallonga" in prompt
    assert "Registro: duonformala" in prompt
    assert "Stilo: rekta" in prompt
    assert "Fonta teksto por reskribi" in prompt
    assert "Jen mia tipa vocho." in prompt
    assert "Celo: teama resumo." in prompt


def test_verki_service_build_prompt_contains_enc_constraints():
    provider = _FakeProvider("Rezulto")
    service = VerkiService(provider=provider)
    prompt = service.build_prompt(
        VerkiRequest(instrukcio="Generate .enc on 'ECHO IV'")
    )
    assert "Formato deviga por .enc" in prompt
    assert 'terminologio.eo="..."' in prompt
    assert "Ne uzu ``` kodbarilojn." in prompt


def test_verki_service_normalizes_enc_output():
    provider = _FakeProvider(
        "The user wants...\n"
        "```enc\n"
        'terminologio.eo="ECHO IV"\n'
        'terminologio.fr="ECHO IV"\n'
        'terminologio.en="ECHO IV"\n'
        'difino.eo="mallonga"\n'
        "```\n"
    )
    service = VerkiService(provider=provider)
    out = service.verki(VerkiRequest(instrukcio="Generate .enc on 'ECHO IV'"))
    assert out.startswith('terminologio.eo="ECHO IV"')
    assert "The user wants" not in out
    assert "```" not in out


def test_verki_service_retries_incomplete_enc_once():
    class _SequenceProvider:
        def __init__(self) -> None:
            self.requests: list[GenerationRequest] = []
            self.outputs = [
                '```enc\nterminologio.eo="ECHO IV"\n',
                (
                    'terminologio.eo="ECHO IV"\n'
                    'terminologio.fr="ECHO IV"\n'
                    'terminologio.en="ECHO IV"\n'
                    'difino.eo="mallonga"\n'
                ),
            ]

        def generate(self, request: GenerationRequest) -> str:
            self.requests.append(request)
            idx = min(len(self.requests) - 1, len(self.outputs) - 1)
            return self.outputs[idx]

    provider = _SequenceProvider()
    service = VerkiService(provider=provider)
    out = service.verki(
        VerkiRequest(instrukcio="Generate .enc on 'ECHO IV'", maksimumaj_tokenoj=512)
    )
    assert out.startswith('terminologio.eo="ECHO IV"')
    assert len(provider.requests) == 2
    assert provider.requests[1].max_new_tokens >= 1024


def test_verki_service_detects_token_only_difino_as_incomplete():
    class _SequenceProvider:
        def __init__(self) -> None:
            self.requests: list[GenerationRequest] = []
            self.outputs = [
                'terminologio.(eo,fr,en)="macOS"\ndifino.eo\n',
                (
                    'terminologio.(eo,fr,en)="macOS"\n'
                    'difino.eo="""\n'
                    "Mallonga difino.\n"
                    '"""\n'
                ),
            ]

        def generate(self, request: GenerationRequest) -> str:
            self.requests.append(request)
            idx = min(len(self.requests) - 1, len(self.outputs) - 1)
            return self.outputs[idx]

    provider = _SequenceProvider()
    service = VerkiService(provider=provider)
    out = service.verki(
        VerkiRequest(instrukcio="Generate .enc on 'macOS'", maksimumaj_tokenoj=256)
    )
    assert len(provider.requests) == 2
    assert 'difino.eo="""' in out


def test_verki_service_calls_provider_and_returns_clean_text():
    provider = _FakeProvider("   Finita teksto.   ")
    service = VerkiService(provider=provider)
    result = service.verki(
        VerkiRequest(
            instrukcio="Verku enkondukon",
            maksimumaj_tokenoj=77,
            temperaturo=0.2,
        )
    )
    assert result == "Finita teksto."
    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert sent.max_new_tokens == 77
    assert sent.temperature == 0.2
    assert "Tasko: Verku enkondukon" in sent.prompt


def test_verki_service_errors_for_empty_instruction():
    provider = _FakeProvider("text")
    service = VerkiService(provider=provider)
    with pytest.raises(VerkiServiceError, match="Instrukcio ne rajtas esti malplena"):
        service.verki(VerkiRequest(instrukcio="   "))


def test_verki_service_errors_for_empty_output():
    provider = _FakeProvider("   ")
    service = VerkiService(provider=provider)
    with pytest.raises(VerkiServiceError, match="malplenan tekston"):
        service.verki(VerkiRequest(instrukcio="Verku ion"))


def test_verki_service_wraps_provider_error():
    class _FailingProvider:
        def generate(self, request: GenerationRequest) -> str:
            raise VerkiProviderError("HTTP 500")

    service = VerkiService(provider=_FailingProvider())
    with pytest.raises(VerkiServiceError, match="HTTP 500"):
        service.verki(VerkiRequest(instrukcio="Verku ion"))


class _FakeHeaders:
    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.headers = _FakeHeaders()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload.encode("utf-8")


def test_huggingface_provider_sends_expected_request(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    seen: dict[str, object] = {}

    def _fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse('[{"generated_text":"  Saluton mondo.  "}]')

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _fake_urlopen)
    provider = HuggingFaceProvider(
        model="google/flan-t5-base",
        token="hf_test",
        timeout=9,
    )
    text = provider.generate(
        GenerationRequest(prompt="Kreu tekston", max_new_tokens=42, temperature=0.4)
    )
    assert text == "Saluton mondo."
    assert str(seen["url"]).endswith("/models/google/flan-t5-base")
    assert seen["auth"] == "Bearer hf_test"
    assert seen["timeout"] == 9
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["inputs"] == "Kreu tekston"
    assert body["parameters"]["max_new_tokens"] == 42
    assert body["parameters"]["temperature"] == 0.4


def test_huggingface_provider_handles_http_errors(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    def _failing_urlopen(_request, timeout):
        raise HTTPError(
            url="https://example.invalid",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"bad token"}'),
        )

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _failing_urlopen)
    provider = HuggingFaceProvider(model="google/flan-t5-base", token="hf_test")
    with pytest.raises(VerkiProviderError, match="401"):
        provider.generate(GenerationRequest(prompt="x"))


def test_huggingface_provider_fallback_router(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    calls = {"n": 0}

    def _sequential_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate HTML 404 response from a router/misconfigured endpoint
            raise HTTPError(
                url="https://router.huggingface.co/models/deepseek-ai/DeepSeek-R1",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=io.BytesIO(
                    b"<!DOCTYPE html><pre>Cannot POST /models/"
                    b"deepseek-ai/DeepSeek-R1</pre>"
                ),
            )
        # Second call returns an OpenAI-like chat response
        return _FakeResponse(
            json.dumps(
                {"choices": [{"message": {"content": "Fallback success"}}]}
            )
        )

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _sequential_urlopen)
    provider = HuggingFaceProvider(
        model="deepseek-ai/DeepSeek-R1",
        token="hf_test",
        timeout=5,
    )
    text = provider.generate(
        GenerationRequest(prompt="Hello", max_new_tokens=50, temperature=0.1)
    )
    assert text == "Fallback success"


def test_huggingface_provider_prefers_router_for_revision_model(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    seen = {}

    def _fake_urlopen(request, timeout):
        # capture the URL used
        seen["url"] = getattr(request, "full_url", str(request))
        return _FakeResponse(
            json.dumps({"choices": [{"message": {"content": "Router ok"}}]})
        )

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _fake_urlopen)
    provider = HuggingFaceProvider(
        model="deepseek-ai/DeepSeek-R1:hyperbolic",
        token="hf_test",
        timeout=5,
    )
    text = provider.generate(
        GenerationRequest(prompt="Hello", max_new_tokens=10, temperature=0.1)
    )
    assert text == "Router ok"
    assert "chat/completions" in seen["url"]


def test_huggingface_router_payload_requests_non_reasoning_output(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    captured_body: dict[str, object] = {}

    def _fake_urlopen(request, timeout):
        captured_body["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps({"choices": [{"message": {"content": "Final text"}}]})
        )

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _fake_urlopen)
    provider = HuggingFaceProvider(
        model="MiniMaxAI/MiniMax-M2.7:novita",
        token="hf_test",
        timeout=5,
    )
    text = provider.generate(
        GenerationRequest(prompt="Generate .enc", max_new_tokens=128, temperature=0.3)
    )
    assert text == "Final text"
    payload = captured_body["payload"]
    assert isinstance(payload, dict)
    assert payload.get("reasoning_effort") == "none"
    assert payload.get("response_format") == {"type": "text"}


def test_parse_generated_text_rejects_reasoning_only_response():
    import autish.services.providers.huggingface as hf_mod

    raw = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "The user wants me to ...",
                    },
                    "finish_reason": "length",
                }
            ]
        }
    )
    with pytest.raises(VerkiProviderError, match="neniu fina teksto"):
        hf_mod._parse_generated_text(raw)


def test_huggingface_provider_cloudflare_block(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    def _blocked_urlopen(request, timeout):
        raise HTTPError(
            url="https://router.huggingface.co/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(
                b'{"title":"Error 1010: Access denied","cloudflare_error":true}'
            ),
        )

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _blocked_urlopen)
    provider = HuggingFaceProvider(
        model="deepseek-ai/DeepSeek-R1:hyperbolic",
        token="hf_test",
        timeout=5,
    )
    with pytest.raises(VerkiProviderError, match="blocked access"):
        provider.generate(
            GenerationRequest(prompt="x", max_new_tokens=10, temperature=0.1)
        )


def test_verki_cli_exports_output_file(monkeypatch, tmp_path: Path):
    import autish.commands.verki as mod

    class _FakeService:
        def verki(self, request: VerkiRequest) -> str:
            return "Eksportita teksto."

    monkeypatch.setattr(mod, "_build_verki_service", lambda **_kwargs: _FakeService())
    out_file = tmp_path / "out.txt"
    result = runner.invoke(
        app,
        [
            "verki",
            "generi",
            "--instrukcio",
            "Eksportu",
            "--eksporti",
            str(out_file),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == "Eksportita teksto."
    assert "Eksportita teksto." in result.output


def test_verki_cli_copies_output_to_clipboard(monkeypatch):
    import autish.commands.verki as mod

    class _FakeService:
        def verki(self, request: VerkiRequest) -> str:
            return "Kopiita teksto."

    monkeypatch.setattr(mod, "_build_verki_service", lambda **_kwargs: _FakeService())
    captured = {}
    monkeypatch.setattr(mod, "_kp_copy", lambda text: captured.setdefault("text", text))
    result = runner.invoke(
        app,
        [
            "verki",
            "generi",
            "--instrukcio",
            "Kopi test",
            "--kopii",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("text") == "Kopiita teksto."
    assert "Kopiita teksto." in result.output
