// content/indicator.js
// Floating status pill (bottom-right) injected into supported search pages.
// It is purely informational: it reports what the background script already
// decided for the current tab. No query data is classified here.
"use strict";

(function () {
  if (window.__smartFilterPillLoaded) return;
  window.__smartFilterPillLoaded = true;

  const HIDE_ALLOWED_AFTER_MS = 6000;
  const RECOVER_AFTER_MS = 8000;
  let hideTimer = null;
  let recoverTimer = null;

  const host = document.createElement("div");
  host.style.cssText =
    "all:initial;position:fixed;right:18px;bottom:18px;z-index:2147483647;";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = [
    "<style>",
    ":host{all:initial;}",
    "*{box-sizing:border-box;}",
    ".pill{",
    "  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;",
    "  display:flex;align-items:center;gap:9px;",
    "  padding:8px 14px 8px 9px;border-radius:999px;",
    "  background:#ffffff;color:#1f2937;font-size:13px;font-weight:600;",
    "  box-shadow:0 6px 22px rgba(49,46,129,.28),0 1px 3px rgba(0,0,0,.12);",
    "  border:1px solid rgba(99,102,241,.18);",
    "  opacity:0;transform:translateY(10px) scale(.96);",
    "  transition:opacity .22s ease,transform .22s ease;",
    "  pointer-events:none;max-width:78vw;",
    "}",
    ".pill.show{opacity:1;transform:translateY(0) scale(1);}",
    ".icon{",
    "  width:24px;height:24px;border-radius:50%;flex:none;",
    "  display:flex;align-items:center;justify-content:center;color:#fff;",
    "  background:linear-gradient(135deg,#6366f1,#8b5cf6);font-size:14px;",
    "}",
    ".icon.ok{background:linear-gradient(135deg,#16a34a,#22c55e);}",
    ".icon.bad{background:linear-gradient(135deg,#dc2626,#ef4444);}",
    ".icon.warn{background:linear-gradient(135deg,#d97706,#f59e0b);}",
    ".text{display:flex;flex-direction:column;line-height:1.15;min-width:0;}",
    ".title{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
    ".meta{font-size:11px;font-weight:500;color:#6b7280;white-space:nowrap;}",
    ".spin{width:13px;height:13px;border-radius:50%;",
    "  border:2px solid rgba(255,255,255,.45);border-top-color:#fff;",
    "  animation:sfspin .7s linear infinite;}",
    "@keyframes sfspin{to{transform:rotate(360deg);}}",
    "@media (prefers-reduced-motion:reduce){.spin{animation-duration:1.6s;}}",
    "</style>",
    '<div class="pill" part="pill">',
    '  <span class="icon" id="icon"></span>',
    '  <span class="text"><span class="title" id="title"></span>',
    '  <span class="meta" id="meta"></span></span>',
    "</div>",
  ].join("");

  const pill = root.querySelector(".pill");
  const iconEl = root.querySelector("#icon");
  const titleEl = root.querySelector("#title");
  const metaEl = root.querySelector("#meta");

  function providerLabel(p) {
    if (!p) return "";
    return p.charAt(0).toUpperCase() + p.slice(1);
  }

  function render(state, info) {
    info = info || {};
    const provider = providerLabel(info.provider);
    if (state === "checking") {
      iconEl.className = "icon";
      iconEl.innerHTML = '<span class="spin"></span>';
      titleEl.textContent = "Checking search\u2026";
      metaEl.textContent = provider ? "Smart-Filter \u00b7 " + provider : "Smart-Filter";
    } else if (state === "allowed") {
      iconEl.className = "icon ok";
      iconEl.textContent = "\u2713";
      titleEl.textContent = "Search allowed";
      metaEl.textContent = provider ? "via " + provider : "Smart-Filter";
    } else if (state === "blocked") {
      iconEl.className = "icon bad";
      iconEl.textContent = "\u2715";
      titleEl.textContent = "Search blocked";
      metaEl.textContent = info.reason ? String(info.reason).slice(0, 60) : "Smart-Filter";
    } else if (state === "error") {
      iconEl.className = "icon warn";
      iconEl.textContent = "!";
      titleEl.textContent = "Couldn't verify";
      metaEl.textContent = "Fail-safe: not allowed";
    } else {
      return;
    }
    pill.classList.add("show");
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => pill.classList.remove("show"), HIDE_ALLOWED_AFTER_MS);
  }

  // If we're still on "checking" after a while (e.g. the final message was lost
  // when the page navigated), re-ask the background for the decision and settle
  // on it - or hide if there is none. Prevents a permanently stuck spinner.
  function recover() {
    browser.runtime.sendMessage({ type: "smart-filter:status" }).then(
      (res) => {
        if (res && res.state) show(res.state, res);
        else pill.classList.remove("show");
      },
      () => pill.classList.remove("show")
    );
  }

  function show(state, info) {
    clearTimeout(recoverTimer);
    render(state, info);
    if (state === "checking") {
      recoverTimer = setTimeout(recover, RECOVER_AFTER_MS);
    } else if (state === "allowed" || state === "blocked" || state === "error") {
      scheduleHide();
    }
  }

  function onMessage(message) {
    if (!message || message.type !== "smart-filter") return;
    clearTimeout(hideTimer);
    show(message.state, message);
  }

  browser.runtime.onMessage.addListener(onMessage);

  document.documentElement.appendChild(host);

  // Ask the background for the result it already decided for this tab (covers
  // the common case where the search page finishes loading after classification).
  try {
    browser.runtime.sendMessage({ type: "smart-filter:status" }).then(
      (res) => {
        if (res && res.state) show(res.state, res);
      },
      () => {}
    );
  } catch (err) {
    // background not reachable; pill stays hidden
  }
})();
