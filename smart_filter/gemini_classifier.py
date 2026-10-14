"""Stage 2: Google Gemini semantic classification.

Gemini is used here as a *decision* backend, the same role Jev plays: the
search query (untrusted data) is sent together with the configured blocked
categories, and Gemini must return exactly one label - either a category or the
explicit ``__allow__`` label. Structured output (a JSON schema restricted to the
allowed labels) keeps the answer machine-readable and avoids free-form prose.

Fail-closed design: any timeout, auth/quota failure, safety block, malformed
response, or other API problem raises :class:`GeminiError`, which the pipeline
maps to an ERROR result (never ALLOWED).

API notes (https://ai.google.dev/api/generate-content):
- Endpoint ``POST .../v1beta/models/{model}:generateContent``.
- Auth: ``x-goog-api-key: <GEMINI_API_KEY>`` header, so the key never appears in
  the URL, logs, or tracebacks.
- ``generationConfig.responseMimeType`` + ``responseSchema`` request JSON output
  constrained to the label enum.
- Retry with backoff on ``429, 500, 502, 503, 504``; never retry
  ``400, 401, 403, 404``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .config import Settings
from .providers import (
    ALLOW_LABEL,
    RetryableSemanticError,
    SemanticError,
    SemanticVerdict,
    build_criteria,
    classifier_instructions,
    no_api_key_message,
    resolve_label,
    validate_entries,
)

_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_RETRYABLE_CODES = frozenset((429, 500, 502, 503, 504))
DEFAULT_USER_AGENT = "Smart-Filter/0.4 (+http://127.0.0.1)"

_urlopen = urllib.request.urlopen  # module-level so tests can patch/inject


class GeminiError(SemanticError):
    """Raised when Gemini cannot produce a reliable classification."""


class GeminiRetryableError(RetryableSemanticError):
    """Transient Gemini failure that may recover on retry."""


def endpoint_for(model: str) -> str:
    return _ENDPOINT_TEMPLATE.format(model=model or "gemini-2.5-flash-lite")


def build_payload(model: str, query: str, entries: List[str]) -> dict:
    """Build the Gemini ``generateContent`` request for ``query``.

    Raises :class:`GeminiError` when the policy cannot be represented within the
    uniform block-list limits.
    """
    try:
        entries = validate_entries(entries)
    except SemanticError as exc:
        raise GeminiError(str(exc)) from None

    criteria, label_to_entry = build_criteria(entries)
    labels = [ALLOW_LABEL] + list(label_to_entry.keys())
    label_lines = "\n".join(f"- {label}: {desc}" for label, desc in criteria.items())
    system = f"{classifier_instructions()}\n\nLABELS:\n{label_lines}"

    return {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"Search query to classify:\n{query}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {"choice": {"type": "string", "enum": labels}},
                "required": ["choice"],
            },
        },
    }


class GeminiClassifier:
    """Calls the Gemini API to semantically classify a search query."""

    def __init__(
        self,
        settings: Settings,
        transport: Optional[Callable[..., Any]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.settings = settings
        self._transport = transport or _urlopen
        self._sleep = sleep or time.sleep

    def classify(self, query: str) -> SemanticVerdict:
        """Classify ``query`` via Gemini. Raises :class:`GeminiError` on failure."""
        if not self.settings.has_api_key:
            raise GeminiError(no_api_key_message("gemini"))
        if not query or not query.strip():
            raise GeminiError("Empty query cannot be classified by Gemini")

        entries = validate_entries(self.settings.blocked_entries)
        payload = build_payload(self.settings.model, query.strip(), entries)
        _, label_map = build_criteria(entries)
        last_error: Optional[Exception] = None

        for attempt in range(self.settings.max_retries + 1):
            started = time.monotonic()
            try:
                data = self._post(payload)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return self._parse_response(data, label_map, elapsed_ms)
            except GeminiRetryableError as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                self._sleep(self._retry_delay(exc, attempt))
            except GeminiError:
                raise
            except SemanticError as exc:
                raise GeminiError(str(exc)) from None
            except Exception as exc:  # noqa: BLE001 - every failure must fail closed
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                self._sleep(self._retry_delay(GeminiRetryableError(str(exc), 0), attempt))

        raise GeminiError(
            f"Gemini classification failed: {last_error or 'unknown error'}"
        )

    def _post(self, payload: dict) -> dict:
        url = endpoint_for(self.settings.model)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Key travels in a header, never in the URL.
                "x-goog-api-key": self.settings.api_key or "",
                "User-Agent": self.settings.user_agent or DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        timeout = max(int(self.settings.timeout_ms), 1) / 1000.0
        try:
            with self._transport(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            retry_after = self._parse_retry_after(exc)
            message = f"Gemini returned HTTP {exc.code}"
            if exc.code in _RETRYABLE_CODES:
                raise GeminiRetryableError(message, exc.code, retry_after) from None
            raise GeminiError(message) from None
        except TimeoutError:
            raise GeminiError("Gemini request timeout") from None
        except urllib.error.URLError as exc:
            raise GeminiError(f"Gemini connection error: {exc.reason}") from None

        try:
            data = json.loads((raw or b"").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise GeminiError("Gemini response was not valid JSON") from None
        if not isinstance(data, dict):
            raise GeminiError("Gemini response JSON was not an object")
        if isinstance(data.get("error"), dict):
            raise GeminiError("Gemini returned an error envelope")
        return data

    @staticmethod
    def _parse_retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
        raw = exc.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            delay = float(str(raw).strip())
        except ValueError:
            return None
        return min(delay, 30.0) if delay > 0 else None

    @staticmethod
    def _retry_delay(exc: GeminiRetryableError, attempt: int) -> float:
        if exc.retry_after is not None:
            return exc.retry_after
        return float(1 << attempt)

    def _parse_response(
        self, data: dict, label_map: Dict[str, str], latency_ms: Optional[int] = None
    ) -> SemanticVerdict:
        """Validate and parse Gemini's answer. Fail-safe on malformed output."""
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise GeminiError(
                f"Gemini blocked the request ({feedback.get('blockReason')})"
            )

        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiError("Gemini response missing candidates")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise GeminiError("Gemini response candidate was malformed")
        content = candidate.get("content")
        if not isinstance(content, dict):
            finish = candidate.get("finishReason")
            raise GeminiError(
                f"Gemini returned no content (finishReason={finish or 'unknown'})"
            )
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise GeminiError("Gemini response had no parts")
        text = parts[0].get("text") if isinstance(parts[0], dict) else None
        if not isinstance(text, str) or not text.strip():
            raise GeminiError("Gemini response had no text")

        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            raise GeminiError("Gemini answer was not valid JSON") from None
        if not isinstance(parsed, dict):
            raise GeminiError("Gemini answer JSON was not an object")

        verdict = resolve_label(
            parsed.get("choice"),
            label_map,
            allow_min_probability=None,
        )
        verdict.provider = "gemini"
        verdict.model = self.settings.model
        verdict.latency_ms = latency_ms
        return verdict
