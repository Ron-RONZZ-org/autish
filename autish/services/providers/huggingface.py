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

        # OpenAI-like chat/completion response
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                # prefer message.content, but handle some providers that include
                # alternative fields (e.g. reasoning_content) when outputs are
                # truncated (finish_reason == "length").
                message = first.get("message")
                # finish_reason may be on the choice or at top-level
                finish_reason = first.get("finish_reason") or payload.get("finish_reason")
                if isinstance(message, dict):
                    content = message.get("content")
                    reasoning = message.get("reasoning_content") or message.get("reasoning")
                    # If content exists and seems reasonable, use it, unless the
                    # choice was cut for length and an alternative reasoning field
                    # appears longer — prefer the longer reasoning content in that case.
                    if isinstance(content, str) and content.strip():
                        if (
                            isinstance(finish_reason, str)
                            and finish_reason == "length"
                            and isinstance(reasoning, str)
                            and len(reasoning.strip()) > len(content.strip())
                        ):
                            return reasoning.strip()
                        return content.strip()
                    # If no content but reasoning exists, use reasoning
                    if isinstance(reasoning, str) and reasoning.strip():
                        # Attempt to extract a content-like block (e.g. .enc file text)
                        try:
                            import re

                            # Look for likely start tokens used in .enc entries or definitions
                            m = re.search(r"(?i)(terminologio\.|terminology\.|difino\.|definition\.|termino\.)", reasoning)
                            if m:
                                return reasoning[m.start():].strip()
                        except Exception:
                            pass
                        # Fallback: return whole reasoning if no structured block found
                        return reasoning.strip()
                # fall back to text field
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()

        # Classic Hugging Face pipeline style
        direct_text = payload.get("generated_text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            generated = first.get("generated_text")
            if isinstance(generated, str) and generated.strip():
                return generated.strip()

    # As a last resort, search recursively for the most-likely text field while
    # avoiding short metadata fields like 'id' that can appear before the content.
    def _extract_first_string(o: Any) -> str | None:
        def _contains_likely_content(x: Any) -> bool:
            if isinstance(x, dict):
                for k in ("choices", "generated_text", "data", "outputs", "text", "message", "content", "result", "answer"):
                    if k in x:
                        return True
                for v in x.values():
                    if isinstance(v, (dict, list)) and _contains_likely_content(v):
                        return True
            if isinstance(x, list):
                for v in x:
                    if _contains_likely_content(v):
                        return True
            return False

        if isinstance(o, str):
            return o
        if isinstance(o, dict):
            # Prefer known semantic fields that commonly contain generated text
            for key in ("choices", "generated_text", "data", "outputs", "text", "message", "content", "result", "answer"):
                if key in o:
                    res = _extract_first_string(o[key])
                    if res:
                        return res
            ignore_keys = {"id", "object", "model", "type", "created", "name"}
            # First pass: recurse into dict/list values that likely contain generated text
            for k, v in o.items():
                if k in ignore_keys:
                    continue
                if isinstance(v, (dict, list)) and _contains_likely_content(v):
                    res = _extract_first_string(v)
                    if res:
                        return res
            # Second pass: recurse into lists even if they don't explicitly contain preferred keys
            for k, v in o.items():
                if k in ignore_keys:
                    continue
                if isinstance(v, list):
                    res = _extract_first_string(v)
                    if res:
                        return res
            # Final pass: return any string values (fallback)
            for k, v in o.items():
                if k in ignore_keys:
                    continue
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(o, list):
            # Prefer list elements that likely contain generated text
            for v in o:
                if _contains_likely_content(v):
                    res = _extract_first_string(v)
                    if res:
                        return res
            # Fallback: scan list items in order
            for v in o:
                res = _extract_first_string(v)
                if res:
                    return res
        return None

    fallback = _extract_first_string(payload)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()

    raise VerkiProviderError("Nekonata respondo-formo de Hugging Face.")


def _save_debug(path: str | None, url: str, status: int | None, headers: Any, body: str) -> None:
    """Save a debugging JSON file with basic meta and the raw body.

    The function is intentionally best-effort and will not raise on failure.
    Authorization headers are redacted before saving to avoid leaking tokens.
    """
    if not path:
        return
    try:
        hdrs = {}
        try:
            if hasattr(headers, "items"):
                hdrs = dict(headers.items())
            elif isinstance(headers, dict):
                hdrs = dict(headers)
            else:
                hdrs = {"raw": str(headers)}
        except Exception:
            hdrs = {"raw": str(headers)}
        # Redact Authorization header if present
        for k in list(hdrs.keys()):
            try:
                if k.lower() == "authorization":
                    hdrs[k] = "REDACTED"
            except Exception:
                continue
        meta = {"url": url, "status": status, "headers": hdrs, "body": body}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
    except Exception:
        # Best-effort only
        return


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
        # Preserve model name and api base for potential router fallback
        self._model_name = model_name
        self._api_base = api_base_url.rstrip('/')
        self._url = f"{self._api_base}/models/{model_name}"
        self._token = token.strip() if token else None
        self._timeout = timeout

    def generate(self, request: GenerationRequest) -> str:
        # Classic inference payload
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
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        def _try_router() -> str:
            router_candidates = [
                "https://router.huggingface.co/v1",
                f"{self._api_base}/v1",
            ]
            openai_payload = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": "Respondu nur per la fina teksto, sen klarigoj aŭ metakomento."},
                    {"role": "user", "content": request.prompt},
                ],
                "max_tokens": request.max_new_tokens,
                "temperature": request.temperature,
            }
            openai_body = json.dumps(openai_payload, ensure_ascii=False).encode("utf-8")
            openai_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self._token:
                openai_headers["Authorization"] = f"Bearer {self._token}"

            last_err: Exception | None = None
            for base in router_candidates:
                chat_url = f"{base.rstrip('/')}/chat/completions"
                try:
                    req = urllib.request.Request(
                        chat_url,
                        data=openai_body,
                        headers=openai_headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                        enc = resp.headers.get_content_charset() or "utf-8"
                        raw = resp.read().decode(enc, errors="replace")
                        # Save raw router response when debugging is enabled
                        if getattr(request, "debug_path", None):
                            try:
                                _save_debug(
                                    request.debug_path,
                                    chat_url,
                                    getattr(resp, "getcode", lambda: None)(),
                                    resp.headers,
                                    raw,
                                )
                            except Exception:
                                pass
                        return _parse_generated_text(raw)
                except urllib.error.HTTPError as exc:
                    # Read body to detect host-side blocking (Cloudflare, etc.)
                    detail = exc.read().decode("utf-8", errors="replace")
                    # Save router error detail when debugging
                    if getattr(request, "debug_path", None):
                        try:
                            _save_debug(
                                request.debug_path,
                                chat_url,
                                getattr(exc, "code", None),
                                getattr(exc, "headers", None),
                                detail,
                            )
                        except Exception:
                            pass
                    low = detail.lower()
                    if (
                        exc.code == 403
                        or "cloudflare" in low
                        or "error 1010" in low
                        or "browser_signature_banned" in low
                    ):
                        msg = _extract_error_message(detail) or detail
                        raise VerkiProviderError(
                            f"Hugging Face router blocked access ({exc.code}): {msg}"
                        ) from exc
                    last_err = exc
                    continue
                except urllib.error.URLError as exc:
                    last_err = exc
                    continue
                except VerkiProviderError as exc:
                    # Parsing or provider-level error; try next candidate
                    last_err = exc
                    continue
                except Exception as exc:
                    last_err = exc
                    continue

            if last_err is not None:
                msg = f"Router attempt failed: {last_err}"
                raise VerkiProviderError(msg) from last_err
            raise VerkiProviderError("Router attempt failed")

        # Prefer router for model revisions (model:revision)
        prefer_router = ":" in self._model_name
        if prefer_router:
            try:
                return _try_router()
            except VerkiProviderError as exc:
                # If router explicitly blocked access (Cloudflare or host-side ban),
                # re-raise so the user sees that error instead of falling back.
                msg = str(exc).lower()
                if any(k in msg for k in ("blocked access", "cloudflare", "error 1010", "browser_signature_banned")):
                    raise
                # Otherwise fall back to classic inference if router fails
                pass

        http_request = urllib.request.Request(
            self._url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self._timeout
            ) as response:
                encoding = response.headers.get_content_charset() or "utf-8"
                raw_json = response.read().decode(encoding, errors="replace")
                # Save raw model endpoint response when debugging is enabled
                if getattr(request, "debug_path", None):
                    try:
                        _save_debug(
                            request.debug_path,
                            self._url,
                            getattr(response, "getcode", lambda: None)(),
                            response.headers,
                            raw_json,
                        )
                    except Exception:
                        pass
                return _parse_generated_text(raw_json)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            # Save detail for debugging when enabled
            if getattr(request, "debug_path", None):
                try:
                    _save_debug(
                        request.debug_path,
                        self._url,
                        getattr(exc, "code", None),
                        getattr(exc, "headers", None),
                        detail,
                    )
                except Exception:
                    pass
            message = _extract_error_message(detail) or str(exc.reason)

            if (
                exc.code in (404, 405)
                or "<!DOCTYPE html>" in detail
                or "Cannot POST /models/" in detail
            ):
                try:
                    return _try_router()
                except VerkiProviderError:
                    err_msg = f"Hugging Face HTTP-eraro {exc.code}: {message}"
                    raise VerkiProviderError(err_msg) from exc

            err_msg = f"Hugging Face HTTP-eraro {exc.code}: {message}"
            raise VerkiProviderError(err_msg) from exc
        except urllib.error.URLError as exc:
            msg = f"Reta eraro ĉe Hugging Face: {exc.reason}"
            raise VerkiProviderError(msg) from exc

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
