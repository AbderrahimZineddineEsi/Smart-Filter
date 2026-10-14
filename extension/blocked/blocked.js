// blocked/blocked.js
// Renders the blocked / error page from the query-string parameters the
// background script attached. Kept in an external file because MV3 extension
// pages disallow inline scripts (default CSP: script-src 'self').
"use strict";

var p = new URLSearchParams(location.search);
var kind = p.get("kind") === "error" ? "error" : "blocked";
var q = p.get("q") || "";
var reason = p.get("reason") || "";
var matched = p.get("matched") || "";
var keywords = p.get("keywords") || "";
var provider = p.get("provider") || "";
var model = p.get("model") || "";
var stage = p.get("stage") || "";
var retry = p.get("retry") || "";
var origin = p.get("origin") || "";

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
}

document.getElementById("badge").textContent = kind === "error" ? "ERROR" : "BLOCKED";
document.getElementById("badge").classList.add(kind);
document.getElementById("headline").textContent =
    kind === "error" ? "Search not allowed right now" : "Search blocked";
document.getElementById("sub").textContent =
    kind === "error"
        ? "The Smart-Filter service could not verify this search, so it was not allowed (fail-safe mode)."
        : "This search matched a blocked topic, so the results page was not opened.";
document.getElementById("foot").textContent =
    kind === "error"
        ? "Start the service (python3 -m smart_filter.service) and click Retry, or use the extension popup to test the connection."
        : "To change what is blocked, open Smart-Filter settings and edit your blocked topics.";

if (q) {
    document.getElementById("queryLine").textContent = "Query: \"" + q + "\"";
}
var rows = [];
if (keywords) {
    rows.push('<span class="k">Matched keyword' + (keywords.indexOf(",") >= 0 ? "s" : "") + ':</span> ' + escapeHtml(keywords));
}
if (matched) rows.push('<span class="k">Matched entry:</span> ' + escapeHtml(matched));
if (reason) rows.push('<span class="k">Reason:</span> ' + escapeHtml(reason));
if (provider) {
    var via = escapeHtml(provider) + (model ? " (" + escapeHtml(model) + ")" : "");
    rows.push('<span class="k">Checked by:</span> ' + via + (stage ? " \u00b7 stage " + escapeHtml(stage) : ""));
}
if (rows.length) {
    document.getElementById("detail").innerHTML = rows.join("<br>");
}

function goHome() {
    location.replace(origin ? origin + "/" : "about:blank");
}

function goBack() {
    // The blocked page replaced the search navigation, so the previous
    // history entry (if any) is the page the user was on before. When
    // there is nowhere to return to, go to the engine home rather than
    // leaving a dead / blank page.
    if (window.history.length <= 1) {
        goHome();
        return;
    }
    try {
        if (browser.tabs && browser.tabs.getCurrent && browser.tabs.goBack) {
            browser.tabs
                .getCurrent()
                .then(function (tab) {
                    if (!tab || tab.id == null) throw new Error("no tab");
                    return browser.tabs.goBack(tab.id);
                })
                .catch(function () {
                    window.history.back();
                });
            return;
        }
    } catch (err) {
        // fall through
    }
    window.history.back();
}

document.getElementById("goBack").onclick = goBack;
if (retry) {
    document.getElementById("retry").hidden = false;
    document.getElementById("retry").onclick = function () { location.replace(retry); };
}
