#!/usr/bin/env python3
"""Smart-Filter web console (stdlib only - no Flask required).

A small local UI for exercising the two-stage pipeline and editing the block
policy. It serves a single page plus three JSON endpoints:

- ``GET  /health``   -> service/provider status
- ``GET  /config``   -> current defaults (provider, models, entries, key presence)
- ``POST /classify`` -> run one query through the pipeline

The page keeps the provider, API key, model and entries in the browser and sends
them with each request, mirroring how the extension works. Anything omitted
falls back to the process settings (environment / ``.env``).

Run with:  python3 simple_server.py
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from smart_filter import SmartFilter, Status
from smart_filter.config import DEFAULT_GEMINI_MODEL, DEFAULT_JEV_MODEL
from smart_filter.providers import PROVIDERS

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_QUERY_CHARS = 512
MAX_ENTRIES_PER_REQUEST = 64
MAX_ENTRY_CHARS = 1000

_INDEX_FILE = Path(__file__).resolve().parent / "templates" / "index.html"

filter_ = SmartFilter()


def _health() -> dict:
    settings = filter_.settings
    configured = {name: settings.provider_configured(name) for name in PROVIDERS}
    return {
        "ok": True,
        "service": "smart-filter",
        "providers": list(PROVIDERS),
        "default_provider": settings.provider,
        "configured": configured,
        "api_configured": any(configured.values()),
        "model": settings.model,
        "entries": len(filter_.blocked_entries),
    }


def _config() -> dict:
    settings = filter_.settings
    return {
        "default_provider": settings.provider,
        "providers": list(PROVIDERS),
        "models": {
            "jev": settings.model or DEFAULT_JEV_MODEL,
            "gemini": settings.gemini_model or DEFAULT_GEMINI_MODEL,
        },
        "entries": filter_.blocked_entries,
        "has_keys": {
            name: settings.provider_configured(name) for name in PROVIDERS
        },
    }


def _classify(data: dict) -> dict:
    query = data.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "query must be a non-empty string"}
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        return {"error": "query too long"}

    provider = data.get("provider")
    api_key = data.get("api_key")
    model = data.get("model")
    entries = data.get("entries")

    if provider is not None and not isinstance(provider, str):
        return {"error": "'provider' must be a string"}
    if api_key is not None and not isinstance(api_key, str):
        return {"error": "'api_key' must be a string"}
    if model is not None and not isinstance(model, str):
        return {"error": "'model' must be a string"}
    if entries is not None:
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            return {"error": "'entries' must be a list of strings"}
        if len(entries) > MAX_ENTRIES_PER_REQUEST:
            return {"error": "too many entries"}
        if any(len(e) > MAX_ENTRY_CHARS for e in entries):
            return {"error": "entry too long"}

    result = filter_.classify(
        query,
        provider=provider,
        api_key=api_key,
        model=model,
        entries=entries,
    )
    return {
        "status": result.status.value,
        "stage": result.stage,
        "query": result.query,
        "reason": result.reason,
        "matched_keywords": result.matched_keywords,
        "matched_category": result.matched_category,
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "is_allowed": result.is_allowed,
        "is_blocked": result.is_blocked,
        "is_error": result.is_error,
    }


class Handler(BaseHTTPRequestHandler):
    index_html: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if length > 128 * 1024:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = self.index_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/health":
            self._send(200, _health())
        elif path == "/config":
            self._send(200, _config())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/classify":
            self._send(404, {"error": "not found"})
            return
        data = self._read_json()
        if data is None:
            self._send(400, {"error": "invalid JSON body"})
            return
        try:
            self._send(200, _classify(data))
        except Exception:  # noqa: BLE001 - fail closed, never 500-allow
            self._send(
                500,
                {
                    "status": Status.ERROR.value,
                    "stage": None,
                    "reason": "classification backend error; failing closed",
                    "matched_keywords": [],
                    "matched_category": None,
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "latency_ms": None,
                },
            )


def _load_index() -> str:
    try:
        return _INDEX_FILE.read_text(encoding="utf-8")
    except OSError:
        return "<!doctype html><title>Smart-Filter</title><h1>index.html missing</h1>"


def main() -> None:
    host = os.environ.get("SMART_FILTER_WEB_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SMART_FILTER_WEB_PORT", DEFAULT_PORT))

    handler = type("BoundHandler", (Handler,), {"index_html": _load_index()})
    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    health = _health()
    print(
        f"Smart-Filter web console on http://{actual_host}:{actual_port} "
        f"(default={health['default_provider']}, entries={health['entries']})",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
