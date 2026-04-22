"""Hugging Face provider implementation for verki."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from autish.services.providers.base import (
    GenerationRequest,
    TextGenerationProvider,
    VerkiProviderError,
)


def _extract_error_message(raw: str) -> str | None:
    raw_text = raw.strip()
    if not raw_text:
        return None
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text
    if isinstance(payload, dict):
        detail = payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return raw_text


def _parse_generated_text(raw_json: str) -> str:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise VerkiProviderError("Nevalida JSON-respondo de Hugging Face.") from exc

    if isinstance(payload, dict):
        error_detail = payload.get("error")
        if isinstance(error_detail, str) and error_detail.strip():
            raise VerkiProviderError(f"Hugging Face eraro: {error_detail.strip()}")
        direct_text = payload.get("generated_text")
        if isinstance(direct_text, str):
            return direct_text.strip()

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            generated = first.get("generated_text")
            if isinstance(generated, str):
                return generated.strip()

    raise VerkiProviderError("Nekonata respondo-formo de Hugging Face.")


class HuggingFaceProvider(TextGenerationProvider):
    """Minimal Hugging Face Inference API client."""

    def __init__(
        self,
        *,
        model: str,
        token: str | None,
        timeout: float = 45.0,
        api_base_url: str = "https://api-inference.huggingface.co",
    ) -> None:
        model_name = model.strip()
        if not model_name:
            raise ValueError("Modelo ne rajtas esti malplena.")
        self._url = f"{api_base_url.rstrip('/')}/models/{model_name}"
        self._token = token.strip() if token else None
        self._timeout = timeout

    def generate(self, request: GenerationRequest) -> str:
        payload: dict[str, Any] = {
            "inputs": request.prompt,
            "parameters": {
                "max_new_tokens": request.max_new_tokens,
                "temperature": request.temperature,
                "return_full_text": False,
            },
            "options": {"wait_for_model": True},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        http_request = urllib.request.Request(
            self._url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self._timeout
            ) as response:
                encoding = response.headers.get_content_charset() or "utf-8"
                raw_json = response.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = _extract_error_message(detail) or str(exc.reason)
            raise VerkiProviderError(
                f"Hugging Face HTTP-eraro {exc.code}: {message}"
            ) from exc
        except urllib.error.URLError as exc:
            raise VerkiProviderError(
                f"Reta eraro ĉe Hugging Face: {exc.reason}"
            ) from exc

        return _parse_generated_text(raw_json)

    def list_models(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        """List available models from Hugging Face Hub (sorted by downloads)."""
        # Use model search API to get popular models
        api_base = "https://huggingface.co/api/models"
        params = [f"sort=downloads&direction=-1&limit={min(limit, 100)}"]
        if query:
            params.append(f"search={urllib.parse.quote(query)}")
        url = f"{api_base}?{'&'.join(params)}"

        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        http_request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(
                http_request, timeout=self._timeout
            ) as response:
                encoding = response.headers.get_content_charset() or "utf-8"
                raw_json = response.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = _extract_error_message(detail) or str(exc.reason)
            raise VerkiProviderError(
                f"Hugging Face HTTP-eraro {exc.code}: {message}"
            ) from exc
        except urllib.error.URLError as exc:
            raise VerkiProviderError(
                f"Reta eraro ĉe Hugging Face: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise VerkiProviderError(
                "Nevalida JSON-respondo de Hugging Face."
            ) from exc

        if not isinstance(data, list):
            raise VerkiProviderError("Nekonata respondo-formo de Hugging Face.")

        model_ids = []
        for item in data[:limit]:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    model_ids.append(model_id.strip())
        return model_ids
