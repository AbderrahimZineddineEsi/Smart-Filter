#!/usr/bin/env python3
"""Optional Flask web console for the Smart-Filter pipeline.

The stdlib console (``python3 simple_server.py``) needs no dependencies and is
the recommended way to try things locally. This Flask variant exists for people
who prefer Flask; install it first with ``pip install flask``.

Endpoints match ``simple_server.py``: ``GET /health``, ``GET /config``,
``POST /classify``.
"""

from flask import Flask, jsonify, render_template, request

from smart_filter import SmartFilter
from smart_filter.config import DEFAULT_GEMINI_MODEL, DEFAULT_JEV_MODEL
from smart_filter.providers import PROVIDERS

app = Flask(__name__)
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify(_health())


@app.route("/config")
def config():
    settings = filter_.settings
    return jsonify({
        "default_provider": settings.provider,
        "providers": list(PROVIDERS),
        "models": {
            "jev": settings.model or DEFAULT_JEV_MODEL,
            "gemini": settings.gemini_model or DEFAULT_GEMINI_MODEL,
        },
        "entries": filter_.blocked_entries,
        "has_keys": {name: settings.provider_configured(name) for name in PROVIDERS},
    })


@app.route("/classify", methods=["POST"])
def classify():
    data = request.get_json(silent=True) or {}
    result = filter_.classify(
        data.get("query", ""),
        provider=data.get("provider"),
        api_key=data.get("api_key"),
        model=data.get("model"),
        entries=data.get("entries"),
    )
    return jsonify({
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
    })


if __name__ == "__main__":
    # Never run with debug=True in production.
    app.run(host="127.0.0.1", port=8000)
