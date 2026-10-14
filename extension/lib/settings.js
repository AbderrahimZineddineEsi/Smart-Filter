// lib/settings.js
// Single source of truth for Smart-Filter extension settings, persisted in
// browser.storage.local. Shared by the background script, popup and options
// page. Contains NO API keys by default - the user enters their own.
"use strict";

var SmartSettings = (function () {
  const DEFAULTS = {
    enabled: true,
    provider: "jev", // "jev" | "gemini"
    serviceUrl: "http://127.0.0.1:8765",
    entries: [], // free-form blocked topics/words
    models: { jev: "typesafe/jev-1.13", gemini: "gemini-2.5-flash-lite" },
    keys: { jev: "", gemini: "" },
  };

  const PROVIDERS = ["jev", "gemini"];
  const PROVIDER_LABELS = { jev: "Jev (OpenRouter)", gemini: "Gemini" };

  function normalizeProvider(value) {
    const v = String(value || "").trim().toLowerCase();
    return PROVIDERS.indexOf(v) === -1 ? "jev" : v;
  }

  async function get() {
    const stored = await browser.storage.local.get(Object.keys(DEFAULTS));
    const out = {};
    for (const key of Object.keys(DEFAULTS)) {
      out[key] = stored[key] === undefined ? DEFAULTS[key] : stored[key];
    }
    out.provider = normalizeProvider(out.provider);
    out.models = Object.assign({}, DEFAULTS.models, out.models || {});
    out.keys = Object.assign({}, DEFAULTS.keys, out.keys || {});
    if (!Array.isArray(out.entries)) out.entries = [];
    if (typeof out.serviceUrl !== "string" || !out.serviceUrl) {
      out.serviceUrl = DEFAULTS.serviceUrl;
    }
    return out;
  }

  async function set(patch) {
    await browser.storage.local.set(patch);
  }

  // Builds the per-request options for the service from stored settings,
  // optionally overriding the provider (used by the "try a query" test boxes).
  function requestOptions(settings, providerOverride) {
    const provider = normalizeProvider(providerOverride || settings.provider);
    return {
      provider: provider,
      apiKey: (settings.keys && settings.keys[provider]) || "",
      model: (settings.models && settings.models[provider]) || "",
      entries: Array.isArray(settings.entries) ? settings.entries : [],
    };
  }

  return {
    DEFAULTS: DEFAULTS,
    PROVIDERS: PROVIDERS,
    PROVIDER_LABELS: PROVIDER_LABELS,
    normalizeProvider: normalizeProvider,
    requestOptions: requestOptions,
    get: get,
    set: set,
  };
})();
