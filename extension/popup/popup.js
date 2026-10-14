"use strict";

const dot = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const enabledEl = document.getElementById("enabled");
const providerSeg = document.getElementById("providerSeg");
const keyWarn = document.getElementById("keyWarn");
const testBtn = document.getElementById("testBtn");
const queryEl = document.getElementById("query");
const checkBtn = document.getElementById("checkBtn");
const resultEl = document.getElementById("result");
const gear = document.getElementById("gear");

let current = { provider: "jev" };

function send(type, extra) {
  return browser.runtime.sendMessage(Object.assign({ type: type }, extra || {}));
}

function setStatus(ok, text) {
  dot.className = "dot " + (ok ? "ok" : "bad");
  statusText.textContent = text;
}

function paintProvider(provider) {
  current.provider = SmartSettings.normalizeProvider(provider);
  for (const btn of providerSeg.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.provider === current.provider);
  }
}

async function refreshKeyWarning() {
  const s = await SmartSettings.get();
  const hasKey = s.keys && s.keys[current.provider];
  if (hasKey) {
    keyWarn.hidden = true;
  } else {
    keyWarn.hidden = false;
    keyWarn.textContent =
      "No " + (SmartSettings.PROVIDER_LABELS[current.provider] || current.provider) +
      " API key set \u2014 open Settings to add one.";
  }
}

async function refreshConnection() {
  statusText.textContent = "Checking\u2026";
  dot.className = "dot";
  try {
    const res = await send("test", {});
    if (res && res.ok) {
      const h = res.health || {};
      setStatus(true, "Connected" + (h.default_provider ? " \u00b7 " + h.default_provider : ""));
    } else {
      setStatus(false, "Unavailable \u2014 " + ((res && res.error) || "no service").slice(0, 46));
    }
  } catch (err) {
    setStatus(false, "Background error");
  }
}

function showResult(res) {
  resultEl.className = "result show";
  if (!res || !res.ok) {
    resultEl.classList.add("ERROR");
    resultEl.textContent = "Error: " + ((res && res.error) || "no response");
    return;
  }
  const r = res.result || {};
  resultEl.classList.add(r.status || "ERROR");
  const bits = [r.status || "?"];
  if (typeof r.stage === "number") bits.push("stage " + r.stage);
  if (r.provider) bits.push(r.provider);
  if (r.model) bits.push(r.model);
  if (typeof r.latency_ms === "number") bits.push(r.latency_ms + " ms");
  let text = bits.join(" \u00b7 ");
  if (r.reason) text += "\n" + r.reason;
  if (r.matched_category) text += "\nmatched: " + r.matched_category;
  resultEl.textContent = text;
}

(async () => {
  try {
    const s = await send("get-state", {});
    enabledEl.checked = !!s.enabled;
    paintProvider(s.provider);
  } catch (err) {
    paintProvider("jev");
  }
  await refreshKeyWarning();
  refreshConnection();
})();

enabledEl.addEventListener("change", () => {
  send("set-enabled", { value: enabledEl.checked });
});

providerSeg.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-provider]");
  if (!btn) return;
  paintProvider(btn.dataset.provider);
  await SmartSettings.set({ provider: current.provider });
  await refreshKeyWarning();
});

testBtn.addEventListener("click", refreshConnection);

checkBtn.addEventListener("click", async () => {
  const q = queryEl.value.trim();
  if (!q) return;
  checkBtn.disabled = true;
  checkBtn.textContent = "Checking\u2026";
  resultEl.className = "result";
  try {
    const res = await send("test-query", { query: q, provider: current.provider });
    showResult(res);
  } finally {
    checkBtn.disabled = false;
    checkBtn.textContent = "Check query";
  }
});

queryEl.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") checkBtn.click();
});

gear.addEventListener("click", () => {
  browser.runtime.openOptionsPage();
});
