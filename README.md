# Smart-Filter

**A local, two-stage search-query filter for Firefox.** Smart-Filter watches the
searches you run on Google, Bing, DuckDuckGo, YouTube and the address bar, and
sends each one to a small service running on your own machine. Queries in your
blocked topics never reach the results page — you get a clear, local "blocked"
page instead of search results.

Nothing is filtered inside the browser: the extension holds no policy and no AI
logic. It forwards the query plus your settings to a loopback-only Python
service that runs the real decision, so all keys and rules stay under your
control.

---

## What it does

When you search, the query is classified in **two stages**:

1. **Stage 1 — Local filter (no network).** Rule-based keyword matching plus
   fuzzy matching that catches misspellings, repeated characters and
   transpositions (e.g. `h4ckk`, `mangaa`, `p o r n`).
2. **Stage 2 — AI semantic filter.** A provider decides whether the query falls
   within the *semantic scope* of your configured categories — including
   synonyms, alternative terminology and sentence-level intent that plain
   keywords miss.

Stage 1 always runs first; if it blocks, Stage 2 is never called and the query
is **never sent anywhere**.

Each query ends as one of:

| Result | Meaning |
|--------|---------|
| **ALLOWED** | Search proceeds normally. |
| **BLOCKED** | The search is redirected to a local Smart-Filter page that explains why. |
| **ERROR** | The service/provider was unreachable or failed — the search is **fail-closed** (not allowed), with a Retry button. |

### Providers

| Provider | What it is | Auth |
|----------|------------|------|
| **Jev** (default) | TypeSafe AI's *System One* decision model, served through [OpenRouter](https://openrouter.ai/). You send a **state** (the query) and one typed **choice question** (your blocked categories + an explicit allow label); it returns the best label with a probability. | `Authorization: Bearer` (OpenRouter key, `sk-or-v1-…`) |
| **Gemini** | Google Gemini via `generateContent`, constrained to a `BLOCKED`/`ALLOWED` JSON enum. | `x-goog-api-key` |

Both providers share the same limits: **at most 23 entries** per call and **400
characters** per entry.

### Blocked entries are descriptions, not literal strings

An entry describes a *category or concept* to block, and the model interprets its
scope. Nothing is hardcoded — an empty list blocks nothing.

```text
explicit sexual content of any kind
manga and anime (including closely related formats such as manhwa and webtoons)
content that encourages wasting hours on endless entertainment instead of studying
```

The query is sent as untrusted **state** (data to classify, not instructions), so
it cannot override your rules.

---

## How it works

```
 Firefox tab                         extension/  (no classification logic)
┌───────────┐   search navigation    ┌──────────────────────────────────────┐
│ search box│ ─────────────────────► │ background.js                        │
└───────────┘                        │  webRequest.onBeforeRequest (blocking)│
                                     │  → awaits POST /classify             │
                                     └───────────────┬──────────────────────┘
                                         loopback only │ http://127.0.0.1:8765
                                     ┌───────────────▼──────────────────────┐
                                     │ smart_filter/ service               │
                                     │  Stage 1 local → Stage 2 AI          │
                                     │  → ALLOWED / BLOCKED / ERROR         │
                                     └──────────────────────────────────────┘
```

- **Interception:** the extension uses `webRequest.onBeforeRequest` with
  `"blocking"` and returns a Promise that resolves *after* classification, so the
  results page never loads for a blocked query.
- **YouTube SPA:** classic YouTube search uses `history.pushState`, which cannot
  be intercepted before load. A best-effort fallback
  (`webNavigation.onHistoryStateUpdated`) redirects right after the URL changes.
- **Caching:** identical queries (same provider/model/policy) within 10 s reuse
  the previous result.
- **No query logging:** the service suppresses request logging; queries only ever
  live in memory.

---

## Repository layout

| Path | Purpose |
|------|---------|
| `extension/` | The Firefox WebExtension (MV3). |
| `smart_filter/` | The Python package: local matcher, pipeline and provider clients. |
| `simple_server.py` | Dependency-free web console + the local service used by the extension. |
| `templates/index.html` | UI served by the web console. |
| `app.py` | Optional Flask variant of the web console (same endpoints). |
| `scripts/` | systemd user-service installers and helpers. |
| `pyproject.toml` | Package metadata and console entry point. |
| `.env.example` | Template for environment configuration. |

### Extension files

| Path | Purpose |
|------|---------|
| `extension/manifest.json` | MV3 manifest (add-on id `smart-filter@localhost`). |
| `extension/background.js` | Blocking listener, SPA fallback, badge, message bus. |
| `extension/lib/sites.js` | URL → `{engine, query}` extraction rules. |
| `extension/lib/settings.js` | Shared defaults + `browser.storage.local` helpers. |
| `extension/lib/service.js` | HTTP client for the Python service + short-lived cache. |
| `extension/content/indicator.js` | Floating status pill (shadow DOM) on search pages. |
| `extension/popup/` | Enable toggle, provider switch, connection test, quick query check. |
| `extension/options/` | Full settings page (keys, models, service URL, blocked topics). |
| `extension/blocked/` | Local BLOCKED / ERROR page (HTML + external JS). |
| `extension/icons/` | Shield-and-funnel mark (SVG + 16/32/48/128 PNG). |

---

## Quick start

Requirements: **Python 3.10+** and **Firefox**. The core has no third-party
dependencies (both providers are called over HTTPS with the standard library).

### 1. Install and configure the service

```bash
pip install -e ".[dotenv]"     # + python-dotenv for automatic .env loading
cp .env.example .env           # then fill in your values
```

Set at least one provider key in `.env`:

- `OPENROUTER_API_KEY` — for the **Jev** provider (create one at
  <https://openrouter.ai/settings/keys>, it starts with `sk-or-v1-`).
- `GEMINI_API_KEY` — for the **Gemini** provider
  (<https://aistudio.google.com/app/apikey>).

The `.env` file is git-ignored and never logged. You can also leave keys blank
here and enter them in the extension, which keeps them in the browser only.

### 2. Run the service

```bash
python3 -m smart_filter.service        # foreground, http://127.0.0.1:8765
```

Or install it as a user systemd unit (no sudo, loopback-bound, auto-starts):

```bash
bash scripts/install-service.sh
curl http://127.0.0.1:8765/health      # {"ok": true, ...}
```

### 3. Load the extension

1. Open `about:debugging#/runtime/this-firefox` in Firefox.
2. Click **Load Temporary Add-on…** and select `extension/manifest.json`.
3. Open the extension's **Settings** (gear icon in the popup) and add your
   provider key(s) and blocked topics.

Then search something you have blocked — you should land on the Smart-Filter
blocked page instead of results.

> Temporary loads disappear when Firefox restarts. Install/sign the extension to
> keep it permanently.

---

## Configuration (`.env`)

| Variable | Meaning | Default |
|----------|---------|---------|
| `SMART_FILTER_PROVIDER` | Default Stage-2 provider (`jev` or `gemini`) | `jev` |
| `OPENROUTER_API_KEY` | OpenRouter key for Jev (alias: `JEV_API_KEY`) | *(unset)* |
| `JEV_MODEL` | Jev model id | `typesafe/jev-1.13` |
| `JEV_TIMEOUT_MS` | Jev per-request timeout (ms) | `15000` |
| `JEV_MAX_RETRIES` | Jev retries for transient errors (429/500/502/503/504/524/529) | `2` |
| `JEV_ALLOW_MIN_PROBABILITY` | Minimum "allow" probability required to allow | *(unset)* |
| `JEV_USER_AGENT` | Custom User-Agent for Jev requests | browser signature |
| `GEMINI_API_KEY` | Gemini key | *(unset)* |
| `GEMINI_MODEL` | Gemini model id | `gemini-2.5-flash-lite` |
| `GEMINI_TIMEOUT_MS` / `GEMINI_MAX_RETRIES` | Gemini request tuning | `15000` / `2` |
| `SMART_FILTER_ENTRIES` | Default block policy (newline/comma separated) | *(empty)* |
| `SMART_FILTER_PORT` | Local service port | `8765` |
| `SMART_FILTER_ALLOWED_ORIGINS` | Allowed request origins | any `moz-extension://` |
| `SMART_FILTER_WEB_HOST` / `SMART_FILTER_WEB_PORT` | Web console bind/port | `127.0.0.1` / `8000` |

The extension and web console send the provider, key, model and block list **with
every request**, so keys entered in the UI win over the `.env` fallback and never
have to be written to disk.

---

## The Firefox extension

### Features

- **Settings page** — choose the provider (Jev/Gemini), enter each provider's API
  key and model, set the service URL, and manage blocked topics as free-form
  chips. Everything is stored in `browser.storage.local` and sent per request.
- **Popup** — enable/disable toggle, provider switch, connection test, and a
  one-off "check a query" box.
- **On-page indicator** — a floating pill (bottom-right) on supported search
  pages shows whether the current search is *checking*, *allowed* or *blocked*.
- **Toolbar badge** — `…` while checking, `✓` allowed, `!` blocked, `?` error.
- **Blocked page** — a local page that shows the query, the matched keyword or
  entry, the reason, and which provider/model decided, with **Go back** and
  (on errors) **Retry** buttons.

### Supported search engines

Google (many country domains), Bing, DuckDuckGo, YouTube, and the address bar
(when it searches one of those engines). Other sites are left untouched.

### Fail-closed by design

If the service is down, times out, or returns an error, the search is redirected
to the local error page with a Retry button — it is **never** silently allowed.

---

## Web console

A dependency-free UI for testing queries and editing your policy:

```bash
python3 simple_server.py        # http://127.0.0.1:8000
```

It serves `GET /health`, `GET /config` and `POST /classify`. Provider, key, model
and entries are kept in your browser and sent with each request; a blank key
falls back to the server's `.env`. A Flask variant with the same endpoints lives
in `app.py` (`pip install flask`, then `python3 app.py`).

---

## Python API

```python
from smart_filter import SmartFilter, Status

filter_ = SmartFilter()                       # reads settings from the environment

result = filter_.classify("best free porn sites")
assert result.status == Status.BLOCKED        # ALLOWED / BLOCKED / ERROR
print(result.stage, result.reason, result.matched_category)

# Per-request provider, key, model and policy override the environment:
result = filter_.classify(
    "naruto episode download",
    provider="gemini", api_key="...", model="gemini-2.5-flash-lite",
    entries=["anime", "manga"],
)

# The local stage is also usable on its own:
from smart_filter import KeywordMatcher
KeywordMatcher().is_blocked("h4ckk")          # True (fuzzy match)
```

If the provider key is missing, or the API times out / exhausts quota / returns
malformed output, the result is **ERROR** (fail closed) — never ALLOWED by
default.

---

## Privacy & security

- Queries blocked by Stage 1 never leave your machine.
- Only queries that reach Stage 2 are sent to the selected provider, and only the
  query text and your configured categories are transmitted.
- API keys entered in the extension/web console go only to the local service
  (loopback) and the chosen provider; they are never logged.
- Jev classifications are routed through OpenRouter (a third-party gateway) to
  the TypeSafe model. A stable `Idempotency-Key` is sent per request so a retry
  cannot produce a duplicate decision.
- The service binds to `127.0.0.1` only.

---

## Limitations

- Stage 2 needs a working provider key and internet access.
- Semantic output is model-dependent: it is validated into a typed label, but the
  model is not infallible.
- Up to 23 entries fit one decision call (each ≤ 400 characters); the local
  service accepts up to 64 entries per request.
- YouTube in-page search is best-effort (the redirect happens just after the URL
  changes).
- The extension requires the service to be running; otherwise every supported
  search shows the fail-closed error page until you start it or disable the
  extension.
- The extension targets **Firefox** (it relies on blocking `webRequest`, which
  Chrome's MV3 does not allow for regular extensions).

---

## License

MIT — see [LICENSE](LICENSE).
