"""Configuration and settings for the Smart-Filter pipeline.

Settings are read from environment variables (a local ``.env`` file is loaded
automatically when ``python-dotenv`` is installed). No API keys are ever baked
into source code. Keys can also be supplied per request by a client (the
extension settings UI or the web app); a request value always wins.

Environment variables:
- ``SMART_FILTER_PROVIDER``: default Stage-2 provider (``jev`` or ``gemini``).
- ``OPENROUTER_API_KEY`` (alias: ``JEV_API_KEY``) / ``GEMINI_API_KEY``: provider
  API keys (required for Stage 2). The Jev model is served through OpenRouter.
- ``JEV_MODEL`` (default ``typesafe/jev-1.13``) / ``GEMINI_MODEL``
  (default ``gemini-2.5-flash-lite``).
- ``JEV_TIMEOUT_MS`` / ``GEMINI_TIMEOUT_MS``: request timeout in milliseconds.
- ``JEV_MAX_RETRIES`` / ``GEMINI_MAX_RETRIES``: retries for transient failures.
- ``JEV_ALLOW_MIN_PROBABILITY``: optional minimum Jev allow-label probability.
- ``JEV_USER_AGENT``: optional custom User-Agent for the Jev request.
- ``SMART_FILTER_ENTRIES`` (alias: ``SANITY_CHECKER_KEYWORDS``): blocked entries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional

from .providers import DEFAULT_PROVIDER, SemanticError, normalize_provider

try:  # pragma: no cover - python-dotenv is an optional convenience
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

#: Default models per provider. The Jev model is served through OpenRouter.
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"

DEFAULT_TIMEOUT_MS = 15000
DEFAULT_MAX_RETRIES = 2


def _parse_env_file(path: Path) -> None:
    """Minimal .env parser used when python-dotenv is unavailable.

    Only sets variables that are not already present in the environment, so real
    environment variables always win. Handles ``KEY=VALUE``, ``#`` comments, and
    optional surrounding quotes.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_env_file() -> None:
    """Load a ``.env`` file (python-dotenv if present, else a minimal fallback)."""
    if load_dotenv is not None:  # pragma: no cover - depends on optional dep
        load_dotenv()
        return
    project_root = Path(__file__).resolve().parent.parent
    for candidate in (Path.cwd() / ".env", project_root / ".env"):
        if candidate.is_file():
            _parse_env_file(candidate)


def _split_entries(value: Optional[str]) -> List[str]:
    """Turn a newline/comma separated env value into a clean entry list."""
    if not value:
        return []
    parts = value.replace(",", "\n").split("\n")
    return [part.strip() for part in parts if part.strip()]


def _parse_probability(value: Optional[str]) -> Optional[float]:
    """Parse an optional 0..1 probability from env, ignoring invalid values."""
    if not value:
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return parsed if 0.0 <= parsed <= 1.0 else None


def _env_entries() -> List[str]:
    return _split_entries(
        os.environ.get("SMART_FILTER_ENTRIES")
        or os.environ.get("SANITY_CHECKER_KEYWORDS")
    )


@dataclass
class Settings:
    """Runtime settings for the filtering pipeline, including both providers."""

    provider: str = DEFAULT_PROVIDER
    # Active-provider credentials (defaults to the Jev values below).
    api_key: Optional[str] = None
    model: str = DEFAULT_JEV_MODEL
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_retries: int = DEFAULT_MAX_RETRIES
    allow_min_probability: Optional[float] = None
    user_agent: Optional[str] = None
    blocked_entries: List[str] = field(default_factory=list)
    # Gemini credentials / defaults.
    gemini_api_key: Optional[str] = None
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_timeout_ms: int = DEFAULT_TIMEOUT_MS
    gemini_max_retries: int = DEFAULT_MAX_RETRIES

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        """Build Settings from environment variables, applying ``overrides`` on top."""
        load_env_file()
        kwargs = {
            "provider": os.environ.get("SMART_FILTER_PROVIDER", DEFAULT_PROVIDER),
            # The Jev model runs on OpenRouter, so its key is an OpenRouter key;
            # JEV_API_KEY is accepted as a backwards-compatible alias.
            "api_key": (
                os.environ.get("OPENROUTER_API_KEY")
                or os.environ.get("JEV_API_KEY")
            ),
            "model": os.environ.get("JEV_MODEL", DEFAULT_JEV_MODEL),
            "timeout_ms": int(os.environ.get("JEV_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)),
            "max_retries": int(os.environ.get("JEV_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
            "allow_min_probability": _parse_probability(
                os.environ.get("JEV_ALLOW_MIN_PROBABILITY")
            ),
            "user_agent": os.environ.get("JEV_USER_AGENT") or None,
            "blocked_entries": _env_entries(),
            "gemini_api_key": os.environ.get("GEMINI_API_KEY") or None,
            "gemini_model": os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "gemini_timeout_ms": int(
                os.environ.get("GEMINI_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)
            ),
            "gemini_max_retries": int(
                os.environ.get("GEMINI_MAX_RETRIES", DEFAULT_MAX_RETRIES)
            ),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def provider_key(self, provider: Optional[str] = None) -> Optional[str]:
        """The configured key for ``provider`` (falls back to the active key)."""
        name = normalize_provider(provider or self.provider)
        if name == "gemini":
            return self.gemini_api_key or None
        return self.api_key or None

    def provider_configured(self, provider: Optional[str] = None) -> bool:
        key = self.provider_key(provider)
        return bool(key and key.strip())

    def for_provider(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        entries: Optional[List[str]] = None,
    ) -> "Settings":
        """Return a copy configured for one provider, with optional overrides.

        A per-request ``api_key``/``model`` wins over the stored defaults.
        """
        try:
            name = normalize_provider(provider or self.provider)
        except SemanticError:
            raise
        cfg = replace(self)
        cfg.provider = name
        if entries is not None:
            cfg.blocked_entries = [e.strip() for e in entries if e and e.strip()]
        if name == "gemini":
            cfg.api_key = (api_key or self.gemini_api_key or "").strip() or None
            cfg.model = model or self.gemini_model
            cfg.timeout_ms = self.gemini_timeout_ms
            cfg.max_retries = self.gemini_max_retries
        else:
            cfg.api_key = (api_key or self.api_key or "").strip() or None
            cfg.model = model or self.model
        return cfg
