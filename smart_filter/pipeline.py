"""Two-stage filtering pipeline and the public filter interface.

Flow for every query:
1. Stage 1 (local): rule-based + fuzzy matching. A hit blocks the query
   immediately and no Stage-2 provider is called.
2. Stage 2 (semantic): the selected provider (Jev or Gemini) decides whether
   the query falls within the scope of the configured entries. Any provider
   failure yields an ERROR result so a real integration fails closed instead of
   silently allowing content.

The provider and its credentials may be supplied per call (the extension/web
settings UI send them with each request); anything omitted falls back to the
process settings (environment / ``.env``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from .config import Settings
from .gemini_classifier import GeminiClassifier
from .jev_classifier import JevClassifier
from .matcher import KeywordMatcher
from .providers import (
    SemanticError,
    no_api_key_message,
    normalize_provider,
    provider_label,
)


class Status(Enum):
    """Clear three-way classification outcome."""

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class ClassificationResult:
    """Outcome of classifying a query through the two-stage pipeline."""

    status: Status
    query: str
    stage: Optional[int] = None
    reason: str = ""
    matched_keywords: List[str] = field(default_factory=list)
    matched_category: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None

    @property
    def is_allowed(self) -> bool:
        return self.status is Status.ALLOWED

    @property
    def is_blocked(self) -> bool:
        return self.status is Status.BLOCKED

    @property
    def is_error(self) -> bool:
        return self.status is Status.ERROR


class SmartFilter:
    """Public entry point for the two-stage query filter.

    Usage::

        from smart_filter import SmartFilter

        filter = SmartFilter()  # reads Settings.from_env()
        result = filter.classify("how to hack a website")
        result.status  # Status.BLOCKED / ALLOWED / ERROR

        # per-request provider + credentials (as the extension sends them)
        result = filter.classify(
            "some query", provider="gemini", api_key="...", entries=[...]
        )
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        jev_client: Any = None,
        gemini_client: Any = None,
    ):
        self.settings = settings or Settings.from_env()
        self._jev_client = jev_client
        self._gemini_client = gemini_client

    # -- dynamic entry management -------------------------------------------

    @property
    def blocked_entries(self) -> List[str]:
        return list(self.settings.blocked_entries)

    def set_blocked_entries(self, entries: List[str]) -> None:
        """Replace the blocked entries used when a request does not supply any."""
        self.settings.blocked_entries = [e.strip() for e in entries if e and e.strip()]

    def add_blocked_entry(self, entry: str) -> None:
        if entry and entry.strip():
            self.settings.blocked_entries.append(entry.strip())

    def reset_blocked_entries_to_env(self) -> None:
        """Reload blocked entries from the environment."""
        self.set_blocked_entries(Settings.from_env().blocked_entries)

    # -- classification -----------------------------------------------------

    def _classifier(self, settings: Settings):
        if settings.provider == "gemini":
            return GeminiClassifier(settings, transport=self._gemini_client)
        return JevClassifier(settings, transport=self._jev_client)

    def classify(
        self,
        query: str,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        entries: Optional[List[str]] = None,
    ) -> ClassificationResult:
        """Classify a query through Stage 1 (local) then Stage 2 (provider)."""
        query = (query or "").strip()
        if not query:
            return ClassificationResult(status=Status.ALLOWED, query="", reason="Empty query")

        if entries is None:
            active_entries = list(self.settings.blocked_entries)
        else:
            active_entries = [
                e.strip() for e in entries if isinstance(e, str) and e.strip()
            ]

        # An empty policy has nothing to enforce: allow rather than fail closed.
        if not active_entries:
            return ClassificationResult(
                status=Status.ALLOWED,
                query=query,
                reason="No blocked entries configured",
            )

        # Stage 1: local rule + fuzzy matching (no network). Always runs first.
        local = KeywordMatcher(blocked_keywords=active_entries).classify(query)
        if local.is_blocked:
            return ClassificationResult(
                status=Status.BLOCKED,
                query=query,
                stage=1,
                reason=local.reason or "Blocked by local keyword filter",
                matched_keywords=list(local.matched_keywords),
            )

        # Resolve the Stage-2 provider (unknown provider fails closed).
        try:
            name = normalize_provider(provider or self.settings.provider)
        except SemanticError as exc:
            return ClassificationResult(
                status=Status.ERROR,
                query=query,
                stage=2,
                reason=f"Semantic classification failed; failing closed: {exc}",
            )

        try:
            cfg = self.settings.for_provider(
                name, api_key=api_key, model=model, entries=active_entries
            )
        except SemanticError as exc:
            return ClassificationResult(
                status=Status.ERROR,
                query=query,
                stage=2,
                reason=f"Semantic classification failed; failing closed: {exc}",
                provider=name,
            )

        if not cfg.has_api_key:
            return ClassificationResult(
                status=Status.ERROR,
                query=query,
                stage=2,
                reason=(
                    "Semantic classification failed; failing closed: "
                    + no_api_key_message(name)
                ),
                provider=name,
                model=cfg.model,
            )

        # Stage 2: provider semantic filter. Fail closed on any problem.
        try:
            verdict = self._classifier(cfg).classify(query)
        except SemanticError as exc:
            return ClassificationResult(
                status=Status.ERROR,
                query=query,
                stage=2,
                reason=f"Semantic classification failed; failing closed: {exc}",
                provider=name,
                model=cfg.model,
            )

        status = Status.BLOCKED if verdict.blocked else Status.ALLOWED
        default_reason = (
            f"Blocked by {provider_label(name)} semantic filter"
            if verdict.blocked
            else f"Not blocked by {provider_label(name)} semantic filter"
        )
        return ClassificationResult(
            status=status,
            query=query,
            stage=2,
            reason=verdict.reason or default_reason,
            matched_category=verdict.matched_category,
            provider=verdict.provider or name,
            model=verdict.model or cfg.model,
            latency_ms=verdict.latency_ms,
        )

    # -- helpers ------------------------------------------------------------

    def is_blocked(self, query: str) -> bool:
        return self.classify(query).status is Status.BLOCKED

    def is_allowed(self, query: str) -> bool:
        return self.classify(query).status is Status.ALLOWED
