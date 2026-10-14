// lib/sites.js
// Recognizes supported search endpoints and extracts the actual search query.
// Pure URL logic - no browser API - so it stays easy to read and audit.
"use strict";

var SmartSites = (function () {
  function stripWww(host) {
    return host.startsWith("www.") ? host.slice(4) : host;
  }

  function isGoogleHost(host) {
    host = stripWww(host);
    if (host === "google.com") return true;
    if (!host.startsWith("google.")) return false;
    // google.de, google.co.uk, google.com.au, google.co.in, google.com.br, ...
    const rest = host.slice("google.".length);
    return /^(?:com\.[a-z]{2,3}|co\.[a-z]{2}|net|org|[a-z]{2})$/.test(rest);
  }

  function isBingHost(host) {
    host = stripWww(host);
    return host === "bing.com" || /^bing\.[a-z]{2}$/.test(host);
  }

  function isDuckDuckGoHost(host) {
    const h = stripWww(host);
    return h === "duckduckgo.com" || h === "html.duckduckgo.com" || h === "lite.duckduckgo.com";
  }

  function isYouTubeHost(host) {
    const h = stripWww(host);
    return h === "youtube.com" || h === "m.youtube.com" || h === "music.youtube.com";
  }

  // Returns { engine: string, query: string } for a supported search URL,
  // or null when the URL is ordinary navigation / unsupported.
  function parseSearchUrl(urlString) {
    let url;
    try {
      url = new URL(urlString);
    } catch (err) {
      return null;
    }
    const host = url.hostname || "";

    if (isGoogleHost(host) && url.pathname.replace(/\/+$/, "") === "/search") {
      const q = url.searchParams.get("q");
      if (q) return { engine: "google", query: q.trim() };
      return null;
    }
    if (isBingHost(host) && url.pathname.replace(/\/+$/, "") === "/search") {
      const q = url.searchParams.get("q");
      if (q) return { engine: "bing", query: q.trim() };
      return null;
    }
    if (isDuckDuckGoHost(host) && /^\/(?:html\/|lite\/)?$/.test(url.pathname)) {
      const q = url.searchParams.get("q");
      if (q) return { engine: "duckduckgo", query: q.trim() };
      return null;
    }
    if (isYouTubeHost(host) && url.pathname === "/results") {
      const q = url.searchParams.get("search_query");
      if (q) return { engine: "youtube", query: q.trim() };
      return null;
    }
    return null;
  }

  return { parseSearchUrl: parseSearchUrl };
})();