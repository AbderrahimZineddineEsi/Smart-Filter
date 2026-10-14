// background.js
// Intercepts search navigations and asks the local Smart-Filter service whether
// each query is allowed. Blocking uses webRequest's async "blocking" support
// (Firefox 52+): the listener returns a Promise<BlockingResponse>, so we can
// await the local HTTP call before the search page ever loads.
//
// The extension owns the policy (provider, model, API key, blocked entries);
// the server just runs the pipeline. See lib/settings.js for defaults.
//
// Fail-closed: if the service is down / times out / returns ERROR, the search
// is redirected to an error page instead of being allowed.
"use strict";

const state = Object.assign({}, SmartSettings.DEFAULTS);

function reloadSettings() {
  return SmartSettings.get().then((s) => {
    Object.assign(state, s);
    return s;
  });
}
reloadSettings();

browser.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  reloadSettings().then(() => SmartFilterClient.clearCache());
});

// --- Per-tab "last result" so the on-page pill can render after load --------
const tabResults = new Map();
const TAB_RESULT_TTL_MS = 15000;

function rememberTabResult(tabId, payload) {
  if (tabId === undefined || tabId === null || tabId < 0) return;
  tabResults.set(tabId, Object.assign({ ts: Date.now() }, payload));
}

function getTabResult(tabId) {
  if (tabId === undefined || tabId === null || tabId < 0) return null;
  const rec = tabResults.get(tabId);
  if (!rec) return null;
  if (Date.now() - rec.ts > TAB_RESULT_TTL_MS) {
    tabResults.delete(tabId);
    return null;
  }
  return rec;
}

browser.tabs.onRemoved.addListener((tabId) => tabResults.delete(tabId));

function pushIndicator(tabId, payload) {
  if (tabId === undefined || tabId === null || tabId < 0) return;
  browser.tabs
    .sendMessage(tabId, Object.assign({ type: "smart-filter" }, payload))
    .catch(() => {
      // No content script on this tab/page yet - the content script asks for
      // the stored result when it loads instead.
    });
}

function setBadge(tabId, text, color) {
  const id = tabId === undefined || tabId === null || tabId < 0 ? null : tabId;
  try {
    browser.action.setBadgeText({ tabId: id, text: text || "" });
    if (color) browser.action.setBadgeBackgroundColor({ tabId: id, color: color });
  } catch (err) {
    // tab closed mid-flight
  }
}

function clearBadgeLater(tabId) {
  setTimeout(() => {
    const rec = getTabResult(tabId);
    if (!rec || rec.status === "ALLOWED") setBadge(tabId, "", null);
  }, 6000);
}

function blockUrl(kind, search, reason, matched, original, result) {
  // kind: "blocked" (intentional) or "error" (fail-closed)
  const params = new URLSearchParams({
    kind: kind,
    q: search.query || "",
    reason: reason || "",
    matched: matched || "",
    retry: kind === "error" ? original || "" : "",
  });
  try {
    if (original) params.set("origin", new URL(original).origin);
  } catch (err) {
    // not a parseable URL - omit the origin
  }
  if (result) {
    if (result.provider) params.set("provider", result.provider);
    if (result.model) params.set("model", result.model);
    if (result.stage !== undefined && result.stage !== null) {
      params.set("stage", String(result.stage));
    }
    if (!params.get("matched") && result.matched_category) {
      params.set("matched", result.matched_category);
    }
    if (Array.isArray(result.matched_keywords) && result.matched_keywords.length) {
      params.set("keywords", result.matched_keywords.join(", "));
    }
  }
  return browser.runtime.getURL("blocked/blocked.html") + "?" + params.toString();
}

function currentOptions(providerOverride) {
  return SmartSettings.requestOptions(state, providerOverride);
}

// Returns a redirect URL when the search must not proceed, or null when allowed.
async function evaluateSearch(search, tabId, originalUrl) {
  const opts = currentOptions();
  setBadge(tabId, "\u2026", "#6366f1");
  pushIndicator(tabId, { state: "checking", provider: opts.provider });

  let result;
  try {
    result = await SmartFilterClient.classify(search.query, state.serviceUrl, opts);
  } catch (err) {
    const reason = "Client service unavailable: " + ((err && err.message) || err);
    rememberTabResult(tabId, { status: "ERROR", reason: reason, provider: opts.provider });
    setBadge(tabId, "?", "#e0a800");
    pushIndicator(tabId, { state: "error", provider: opts.provider, reason: reason });
    return blockUrl("error", search, reason, null, originalUrl, null);
  }

  if (result.status !== "ALLOWED") {
    const blocked = result.status === "BLOCKED";
    rememberTabResult(tabId, {
      status: result.status,
      reason: result.reason || "",
      provider: result.provider,
      model: result.model,
      stage: result.stage,
    });
    setBadge(tabId, blocked ? "!" : "?", blocked ? "#dc3545" : "#e0a800");
    pushIndicator(tabId, {
      state: blocked ? "blocked" : "error",
      provider: result.provider,
      model: result.model,
      stage: result.stage,
      reason: result.reason || "",
    });
    return blockUrl(
      blocked ? "blocked" : "error",
      search,
      result.reason,
      result.matched_category,
      originalUrl,
      result
    );
  }

  rememberTabResult(tabId, {
    status: "ALLOWED",
    provider: result.provider,
    model: result.model,
    stage: result.stage,
    reason: result.reason,
  });
  setBadge(tabId, "\u2713", "#28a745");
  clearBadgeLater(tabId);
  pushIndicator(tabId, {
    state: "allowed",
    provider: result.provider,
    model: result.model,
    stage: result.stage,
    reason: result.reason,
  });
  return null;
}

// --- Primary interception: blocks before the results page can load ----------
function onBeforeRequest(details) {
  if (!state.enabled) return {}; // disabled => let everything through
  const search = SmartSites.parseSearchUrl(details.url);
  if (!search) return {}; // ordinary navigation => untouched, synchronous
  return evaluateSearch(search, details.tabId, details.url).then(
    (redirect) => (redirect ? { redirectUrl: redirect } : {}),
    () =>
      evaluateSearchFallback(search, details.tabId, details.url)
  );
}

function evaluateSearchFallback(search, tabId, originalUrl) {
  // Only reachable if evaluateSearch itself threw unexpectedly.
  setBadge(tabId, "?", "#e0a800");
  pushIndicator(tabId, { state: "error", reason: "classification failed" });
  return { redirectUrl: blockUrl("error", search, "classification failed", null, originalUrl, null) };
}

browser.webRequest.onBeforeRequest.addListener(
  onBeforeRequest,
  { urls: ["<all_urls>"], types: ["main_frame"] },
  ["blocking"]
);

// --- SPA fallback -------------------------------------------------------------
// YouTube (and some sites) perform search via history.pushState: the URL
// changes with NO network request, so webRequest cannot intercept it. The
// closest reliable alternative is webNavigation.onHistoryStateUpdated, which
// fires after the URL bar changes; we then move the tab to the blocking page
// before results are rendered. This is best-effort, not pre-emptive.
browser.webNavigation.onHistoryStateUpdated.addListener(async (details) => {
  if (!state.enabled) return;
  if (details.frameId !== 0) return;
  const search = SmartSites.parseSearchUrl(details.url);
  if (!search) return;

  let redirect;
  try {
    redirect = await evaluateSearch(search, details.tabId, details.url);
  } catch (err) {
    redirect = blockUrl("error", search, "classification failed", null, details.url, null);
  }
  if (redirect) {
    try {
      await browser.tabs.update(details.tabId, { url: redirect });
    } catch (err) {
      // tab may have been closed mid-flight; nothing left to do
    }
  }
});

// --- Popup / options / content-script messaging -------------------------------
browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || typeof message.type !== "string") return undefined;

  switch (message.type) {
    case "get-state":
      return Promise.resolve({
        enabled: state.enabled,
        serviceUrl: state.serviceUrl,
        provider: state.provider,
        model: (state.models && state.models[state.provider]) || "",
      });

    case "set-enabled":
      state.enabled = !!message.value;
      return browser.storage.local.set({ enabled: state.enabled });

    case "set-service-url": {
      const url = String(message.value || "").trim().replace(/\/+$/, "");
      if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?$/i.test(url)) {
        return Promise.reject(new Error("service URL must be http://127.0.0.1:PORT"));
      }
      state.serviceUrl = url;
      SmartFilterClient.clearCache();
      return browser.storage.local.set({ serviceUrl: url });
    }

    case "test":
      return SmartFilterClient.health(state.serviceUrl).then(
        (h) => ({ ok: !!(h && h.ok), health: h, status: "connected" }),
        (err) => ({ ok: false, status: "error", error: String((err && err.message) || err) })
      );

    case "test-query": {
      const query = String(message.query || "").trim();
      if (!query) return Promise.resolve({ ok: false, error: "empty query" });
      const opts = currentOptions(message.provider);
      return SmartFilterClient.classify(query, state.serviceUrl, opts).then(
        (r) => ({ ok: true, result: r, provider: opts.provider, model: opts.model }),
        (err) => ({ ok: false, error: String((err && err.message) || err) })
      );
    }

    case "smart-filter:status": {
      const tabId = sender && sender.tab ? sender.tab.id : undefined;
      const rec = getTabResult(tabId);
      if (!rec) return Promise.resolve(null);
      return Promise.resolve({
        state: String(rec.status || "").toLowerCase(),
        provider: rec.provider,
        model: rec.model,
        stage: rec.stage,
        reason: rec.reason,
      });
    }

    case "clear-cache":
      SmartFilterClient.clearCache();
      return Promise.resolve({ ok: true });

    default:
      return undefined;
  }
});
