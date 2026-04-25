from __future__ import annotations

import json
from pathlib import Path

import pytest

from autish.services.providers.base import GenerationRequest
from autish.services.providers.huggingface import HuggingFaceProvider


class _FakeHeaders:
    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.headers = _FakeHeaders()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload.encode("utf-8")


def test_huggingface_provider_ignores_top_level_id(monkeypatch):
    import autish.services.providers.huggingface as hf_mod

    payload = {
        "id": "cb07d8795f4c62dd99f5822580af83df",
        "other": [{"k": "v"}, {"generated_text": "Hello from deep generated text"}],
    }

    def _fake_urlopen(request, timeout):
        return _FakeResponse(json.dumps(payload))

    monkeypatch.setattr(hf_mod.urllib.request, "urlopen", _fake_urlopen)
    provider = HuggingFaceProvider(model="foo", token="hf_test")
    text = provider.generate(GenerationRequest(prompt="x", max_new_tokens=10, temperature=0.1))
    assert text == "Hello from deep generated text"
