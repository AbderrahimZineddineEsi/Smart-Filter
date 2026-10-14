"""Stage 2: Jev semantic classification (TypeSafe decision model via OpenRouter).

Jev is a *decision* model, not a chat model: one request sends a ``state``
(the search query, treated as untrusted data) plus one "choice" question whose
labels are the configured blocked categories and an explicit allow label. Jev
answers with the single best label plus a calibrated probability distribution,
so the result maps directly onto the existing BLOCKED / ALLOWED outcomes.

The model is reached through OpenRouter's System One API (the same request /
response shapes TypeSafe's own SDK uses), so an ordinary OpenRouter API key
authenticates and bills the call.

Fail-closed design: any timeout, auth/quota failure, malformed response, or
other API problem raises :class:`JevError`, which the pipeline maps to an ERROR
result (never ALLOWED).

Documented contract (verified against
https://openrouter.ai/docs/guides/community/typesafe-sdk on 2026-10-14):
- Endpoint ``POST https://openrouter.ai/api/v1/systemone``.
- Auth: ``Authorization: Bearer <OPENROUTER_API_KEY>`` header. The key never
  appears in the URL, logs, or error messages.
- Model ``typesafe/jev-1.13`` (the bare ``jev-1.13`` is also accepted and
  mapped server-side); ``~typesafe/jev-latest`` tracks the newest release.
- ``Idempotency-Key`` header so a retried request cannot double-bill.
- Retry with backoff on ``429, 500, 502, 503, 504, 524, 529``; honour
  ``Retry-After`` on ``429``. Do not retry ``400, 401, 402, 403, 404, 413, 422``.
- ``choice`` questions: ``criteria`` is an OBJECT of label -> description.
  Limits: descriptions <= 400 chars, instructions <= 1000 chars.
- Answer shape for a choice: ``{type, choice, probabilities, confidence}``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from .config import DEFAULT_JEV_MODEL, Settings
from .providers import (
    ALLOW_LABEL,
    MAX_INSTRUCTION_CHARS,
    RetryableSemanticError,
    SemanticError,
    SemanticVerdict,
    build_criteria,
    classifier_instructions,
    no_api_key_message,
    resolve_label,
    validate_entries,
)

_ENDPOINT = "https://openrouter.ai/api/v1/systemone"
_RETRYABLE_CODES = frozenset((429, 500, 502, 503, 504, 524, 529))

#: OpenRouter does not require a browser User-Agent; this one is kept so
#: requests are identifiable and overridable via JEV_USER_AGENT.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
)

_RETRY_AFTER_MAX = 30.0

_urlopen = urllib.request.urlopen  # module-level so tests can patch/inject


class JevError(SemanticError):
    """Raised when Jev cannot produce a reliable classification."""


class JevRetryableError(RetryableSemanticError):
    """Transient Jev failure (429/500/502/503/504/524/529) recoverable on retry."""


#: Backwards-compatible alias - the provider-neutral verdict carries the result.
JevVerdict = SemanticVerdict


def build_payload(model: str, query: str, entries: List[str]) -> dict:
    """Build the Jev decision request for ``query`` against ``entries``.

    Entries are semantic descriptions of categories to block. Raises
    :class:`JevError` when the policy cannot be represented faithfully within
    Jev's documented limits rather than silently truncating it.
    """
    try:
        entries = validate_entries(entries)
    except SemanticError as exc:
        raise JevError(str(exc)) from None

    criteria, _ = build_criteria(entries)
    instructions = classifier_instructions()
    if len(instructions) > MAX_INSTRUCTION_CHARS:  # pragma: no cover - static guard
        raise JevError("Jev classifier instruction exceeds the 1000-char limit")

    return {
        "model": model or DEFAULT_JEV_MODEL,
        "state": query,
        "questions": {
            "classification": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }


class JevClassifier:
    """Calls the Jev decision API to semantically classify a search query.

    Uses only the standard library. Auth goes in a header so the API key never
    reaches URLs, logs, or tracebacks.
    """

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
        """Classify ``query`` via Jev. Raises :class:`JevError` on any failure."""
        if not self.settings.has_api_key:
            raise JevError(no_api_key_message("jev"))
        if not query or not query.strip():
            raise JevError("Empty query cannot be classified by Jev")

        payload = build_payload(
            self.settings.model, query.strip(), self.settings.blocked_entries
        )
        idempotency_key = uuid.uuid4().hex
        last_error: Optional[Exception] = None

        for attempt in range(self.settings.max_retries + 1):
            started = time.monotonic()
            try:
                data = self._post(payload, idempotency_key)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return self._parse_response(data, payload, elapsed_ms)
            except JevRetryableError as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                self._sleep(self._retry_delay(exc, attempt))
            except JevError:
                raise
            except SemanticError as exc:
                raise JevError(str(exc)) from None
            except Exception as exc:  # noqa: BLE001 - every failure must fail closed
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                self._sleep(self._retry_delay(JevRetryableError(str(exc), 0), attempt))

        raise JevError(
            f"Jev classification failed: {last_error or 'unknown error'}"
        )

    def _post(self, payload: dict, idempotency_key: str) -> dict:
        api_key = self.settings.api_key or ""
        request = urllib.request.Request(
            _ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Key travels in a header, never in the URL, so it cannot leak
                # into logs, error messages, or tracebacks.
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
                "User-Agent": self.settings.user_agent or DEFAULT_USER_AGENT,
                # Optional OpenRouter attribution headers (safe to send).
                "HTTP-Referer": "http://127.0.0.1",
                "X-Title": "Smart-Filter",
            },
            method="POST",
        )
        timeout = max(int(self.settings.timeout_ms), 1) / 1000.0
        try:
            with self._transport(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            retry_after = self._parse_retry_after(exc)
            message = f"Jev returned HTTP {exc.code}"
            if exc.code in _RETRYABLE_CODES:
                raise JevRetryableError(message, exc.code, retry_after) from None
            raise JevError(message) from None
        except TimeoutError:
            raise JevError("Jev request timeout") from None
        except urllib.error.URLError as exc:
            raise JevError(f"Jev connection error: {exc.reason}") from None

        try:
            data = json.loads((raw or b"").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise JevError("Jev response was not valid JSON") from None
        if not isinstance(data, dict):
            raise JevError("Jev response JSON was not an object")
        if isinstance(data.get("error"), dict):
            raise JevError("Jev returned an error envelope")
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
        return min(delay, _RETRY_AFTER_MAX) if delay > 0 else None

    @staticmethod
    def _retry_delay(exc: JevRetryableError, attempt: int) -> float:
        if exc.retry_after is not None:
            return exc.retry_after
        return float(1 << attempt)  # 1s, 2s, 4s, ... capped by max_retries

    def _parse_response(
        self, data: dict, payload: dict, latency_ms: Optional[int] = None
    ) -> SemanticVerdict:
        """Validate and parse Jev's answer. Fail-safe on malformed output."""
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise JevError("Jev response missing 'answers'")
        answer = answers.get("classification")
        if not isinstance(answer, dict):
            raise JevError("Jev response missing the 'classification' answer")
        if answer.get("type") != "choice":
            raise JevError("Jev 'classification' answer was not a choice")

        label = answer.get("choice")
        if not isinstance(label, str) or not label:
            raise JevError("Jev response missing the chosen label")

        criteria = payload["questions"]["classification"]["criteria"]
        label_to_entry = {
            key: value for key, value in criteria.items() if key != ALLOW_LABEL
        }
        probabilities = answer.get("probabilities")
        allow_probability = (
            probabilities.get(ALLOW_LABEL) if isinstance(probabilities, dict) else None
        )
        verdict = resolve_label(
            label,
            label_to_entry,
            allow_probability=allow_probability,
            allow_min_probability=(
                self.settings.allow_min_probability if label == ALLOW_LABEL else None
            ),
        )
        verdict.provider = "jev"
        verdict.model = self.settings.model
        # OpenRouter's System One response has no latency_ms; fall back to the
        # locally measured round-trip time.
        latency = data.get("latency_ms")
        verdict.latency_ms = (
            int(latency) if isinstance(latency, (int, float)) else latency_ms
        )
        return verdict
