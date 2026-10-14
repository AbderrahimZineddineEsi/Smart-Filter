// lib/service.js
// Minimal client for the local Smart-Filter classification service.
// Each request carries the provider, that provider's API key, the model and the
// free-form blocked entries, so the extension - not the server - owns policy.
// A short-lived cache avoids sending the identical query twice (webRequest and
// the SPA fallback can both observe one navigation).
"use strict";

var SmartFilterClient = (function () {
  const DEFAULT_URL = "http://127.0.0.1:8765";
  const CACHE_TTL_MS = 10000;
  const DEFAULT_TIMEOUT_MS = 15000;
  const cache = new Map();
  const VALID_STATUS = new Set(["ALLOWED", "BLOCKED", "ERROR"]);

  function clearCache() {
    cache.clear();
  }

  function cacheKey(query, opts) {
    opts = opts || {};
    return [
      opts.provider || "",
      opts.model || "",
      (opts.entries || []).join("\u0001"),
      query,
    ].join("\u0002");
  }

  async function post(path, body, serviceUrl, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetch((serviceUrl || DEFAULT_URL) + path, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw new Error("service returned HTTP " + response.status);
    return response.json();
  }

  // Returns the structured classification {status, stage, reason, provider, ...}.
  // Throws when the service is unreachable / times out / is malformed.
  async function classify(query, serviceUrl, opts) {
    opts = opts || {};
    const key = cacheKey(query, opts);
    const hit = cache.get(key);
    if (hit && Date.now() - hit.ts < CACHE_TTL_MS) return hit.result;

    const body = { query: query };
    if (opts.provider) body.provider = opts.provider;
    if (opts.apiKey) body.api_key = opts.apiKey;
    if (opts.model) body.model = opts.model;
    if (Array.isArray(opts.entries)) body.entries = opts.entries;

    const data = await post(
      "/classify",
      body,
      serviceUrl,
      opts.timeoutMs || DEFAULT_TIMEOUT_MS
    );
    if (!data || !VALID_STATUS.has(String(data.status))) {
      throw new Error("malformed service response");
    }
    cache.set(key, { result: data, ts: Date.now() });
    return data;
  }

  async function health(serviceUrl, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs || 2000);
    let response;
    try {
      response = await fetch((serviceUrl || DEFAULT_URL) + "/health", {
        method: "GET",
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw new Error("service returned HTTP " + response.status);
    return response.json();
  }

  return { classify, health, clearCache, DEFAULT_URL };
})();
