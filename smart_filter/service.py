"""Localhost classification service for the Smart-Filter Firefox extension.

The extension cannot (and must not) classify or block in JavaScript - it sends
the extracted search query here over HTTP and applies the *existing* two-stage
pipeline (local matching, then Jev/Gemini). This service is deliberately tiny:

- Binds to ``127.0.0.1`` only. Never ``0.0.0.0``.
- Exposes only ``/health`` and ``/classify``.
- Never logs query text and never echoes provider API keys.
- Rejects browser/webpage origins; only ``moz-extension://`` origins (or
  non-browser clients such as curl) are served.

The client may choose the provider and supply its API key, model, and block list
with each request; anything omitted falls back to the process settings
(environment / ``.env``).

Run with:  python3 -m smart_filter.service
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, List, Optional
from urllib.parse import urlparse

from .pipeline import SmartFilter
from .providers import PROVIDERS

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_QUERY_CHARS = 512
MAX_ENTRIES_PER_REQUEST = 64
MAX_ENTRY_CHARS = 1000
_EXTENSION_ORIGIN_PREFIX = "moz-extension://"

_ALLOWED_METHODS = "GET, POST, OPTIONS"
_ALLOWED_HEADERS = "Content-Type"


class FilterServiceApp:
    """Holds the filter pipeline and access policy. Injected for tests."""

    def __init__(
        self,
        pipeline: Optional[SmartFilter] = None,
        allowed_origins: Optional[List[str]] = None,
        max_query_chars: int = MAX_QUERY_CHARS,
    ):
        self.pipeline = pipeline or SmartFilter()
        # Explicit allow-list wins when set; otherwise any moz-extension origin.
        self.allowed_origins = allowed_origins
        self.max_query_chars = max_query_chars

    def origin_allowed(self, origin: Optional[str]) -> bool:
        if not origin:
            return True  # non-browser client (curl, tests)
        if self.allowed_origins:
            return origin in self.allowed_origins
        return origin.startswith(_EXTENSION_ORIGIN_PREFIX)

    def configured_providers(self) -> dict:
        return {
            name: self.pipeline.settings.provider_configured(name)
            for name in PROVIDERS
        }

    def health(self) -> dict:
        configured = self.configured_providers()
        return {
            "ok": True,
            "service": "smart-filter",
            "providers": list(PROVIDERS),
            "default_provider": self.pipeline.settings.provider,
            "configured": configured,
            "api_configured": any(configured.values()),
            "model": self.pipeline.settings.model,
            "entries": len(self.pipeline.blocked_entries),
        }

    def classify(
        self,
        query: str,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        entries: Optional[List[str]] = None,
    ) -> dict:
        result = self.pipeline.classify(
            query, provider=provider, api_key=api_key, model=model, entries=entries
        )
        return {
            "status": result.status.value,
            "stage": result.stage,
            "reason": result.reason,
            "matched_keywords": result.matched_keywords,
            "matched_category": result.matched_category,
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
        }


class ServiceHandler(BaseHTTPRequestHandler):
    app: FilterServiceApp  # set per-server instance

    # Suppress all request logging so full search queries never reach logs.
    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        pass

    # -- plumbing -----------------------------------------------------------

    def _origin(self) -> Optional[str]:
        return self.headers.get("Origin")

    def _send(self, code: int, payload: dict, content_type: str = "application/json") -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._origin() or "*")
        self.send_header("Access-Control-Allow-Methods", _ALLOWED_METHODS)
        self.send_header("Access-Control-Allow-Headers", _ALLOWED_HEADERS)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if content_type == "application/json":
            self.wfile.write(body)

    def _app(self) -> FilterServiceApp:
        return self.app

    # -- HTTP methods -------------------------------------------------------

    def do_OPTIONS(self):  # CORS preflight from the extension popup/page
        origin = self._origin()
        if not self._app().origin_allowed(origin):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Methods", _ALLOWED_METHODS)
        self.send_header("Access-Control-Allow-Headers", _ALLOWED_HEADERS)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            if not self._app().origin_allowed(self._origin()):
                self._send(403, {"ok": False, "reason": "origin not allowed"})
                return
            self._send(200, self._app().health())
        else:
            self._send(404, {"ok": False, "reason": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/classify":
            self._send(404, {"ok": False, "reason": "not found"})
            return
        if not self._app().origin_allowed(self._origin()):
            self._send(403, {"ok": False, "reason": "origin not allowed"})
            return

        try:
            raw_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send(400, {"ok": False, "reason": "bad content length"})
            return
        if raw_length > 128 * 1024:
            self._send(413, {"ok": False, "reason": "payload too large"})
            return

        raw = self.rfile.read(raw_length)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"ok": False, "reason": "invalid JSON"})
            return

        if not isinstance(data, dict) or not isinstance(data.get("query"), str):
            self._send(400, {"ok": False, "reason": "expected JSON object with 'query' string"})
            return

        query = data["query"].strip()
        if not query:
            self._send(400, {"ok": False, "reason": "query must not be empty"})
            return
        if len(query) > self._app().max_query_chars:
            self._send(413, {"ok": False, "reason": "query too long"})
            return

        provider = data.get("provider")
        api_key = data.get("api_key")
        model = data.get("model")
        entries = data.get("entries")

        if provider is not None and not isinstance(provider, str):
            self._send(400, {"ok": False, "reason": "'provider' must be a string"})
            return
        if api_key is not None and not isinstance(api_key, str):
            self._send(400, {"ok": False, "reason": "'api_key' must be a string"})
            return
        if model is not None and not isinstance(model, str):
            self._send(400, {"ok": False, "reason": "'model' must be a string"})
            return
        if entries is not None:
            if not isinstance(entries, list) or not all(
                isinstance(e, str) for e in entries
            ):
                self._send(400, {"ok": False, "reason": "'entries' must be a list of strings"})
                return
            if len(entries) > MAX_ENTRIES_PER_REQUEST:
                self._send(413, {"ok": False, "reason": "too many entries"})
                return
            if any(len(e) > MAX_ENTRY_CHARS for e in entries):
                self._send(413, {"ok": False, "reason": "entry too long"})
                return

        try:
            self._send(
                200,
                self._app().classify(
                    query,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    entries=entries,
                ),
            )
        except Exception:  # noqa: BLE001 - classify must fail closed, never 500-allow
            self._send(500, {
                "status": "ERROR",
                "stage": None,
                "reason": "classification backend error; failing closed",
                "matched_keywords": [],
                "matched_category": None,
                "provider": provider,
                "model": model,
                "latency_ms": None,
            })


def build_app(
    pipeline: Optional[SmartFilter] = None,
    allowed_origins: Optional[List[str]] = None,
    max_query_chars: int = MAX_QUERY_CHARS,
) -> FilterServiceApp:
    """Build the service app. ``pipeline``/``allowed_origins`` are injected for tests."""
    if allowed_origins is None:
        raw = os.environ.get("SMART_FILTER_ALLOWED_ORIGINS") or os.environ.get(
            "SANITY_ALLOWED_ORIGINS", ""
        )
        allowed_origins = [o.strip() for o in raw.split(",") if o.strip()] or None
    return FilterServiceApp(
        pipeline=pipeline,
        allowed_origins=allowed_origins,
        max_query_chars=max_query_chars,
    )


def create_server(
    app: FilterServiceApp, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> ThreadingHTTPServer:
    """Create the HTTP server. Binds to ``host`` (default 127.0.0.1)."""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("smart-filter service must bind only to loopback (127.0.0.1)")
    handler = type("Handler", (ServiceHandler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    port = int(
        os.environ.get("SMART_FILTER_PORT")
        or os.environ.get("SANITY_SERVICE_PORT", DEFAULT_PORT)
    )
    app = build_app()
    server = create_server(app, host=DEFAULT_HOST, port=port)
    host, actual_port = server.server_address[:2]
    health = app.health()
    configured = ", ".join(
        f"{name}={'yes' if ok else 'no'}" for name, ok in health["configured"].items()
    )
    print(
        f"Smart-Filter service ready on http://{host}:{actual_port} "
        f"(default={health['default_provider']}, {configured}, "
        f"entries={health['entries']})",
        flush=True,
    )
    print("Cached .env key(s) apply; the extension can also send keys per request. "
          "Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
