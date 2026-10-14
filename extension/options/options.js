"use strict";

const els = {
  enabled: document.getElementById("enabled"),
  serviceUrl: document.getElementById("serviceUrl"),
  providerSeg: document.getElementById("providerSeg"),
  keyJev: document.getElementById("keyJev"),
  modelJev: document.getElementById("modelJev"),
  keyGemini: document.getElementById("keyGemini"),
  modelGemini: document.getElementById("modelGemini"),
  tagJev: document.getElementById("tagJev"),
  tagGemini: document.getElementById("tagGemini"),
  boxJev: document.getElementById("boxJev"),
  boxGemini: document.getElementById("boxGemini"),
  chips: document.getElementById("chips"),
  entryInput: document.getElementById("entryInput"),
  addEntry: document.getElementById("addEntry"),
  testQuery: document.getElementById("testQuery"),
  testProvider: document.getElementById("testProvider"),
  testQueryBtn: document.getElementById("testQueryBtn"),
  testConnBtn: document.getElementById("testConnBtn"),
  testResult: document.getElementById("testResult"),
  saveBtn: document.getElementById("saveBtn"),
  saveStatus: document.getElementById("saveStatus"),
};

let entries = [];
let provider = "jev";

function send(type, extra) {
  return browser.runtime.sendMessage(Object.assign({ type: type }, extra || {}));
}

function setProvider(value) {
  provider = SmartSettings.normalizeProvider(value);
  for (const btn of els.providerSeg.querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.provider === provider);
  }
  els.boxJev.classList.toggle("active", provider === "jev");
  els.boxGemini.classList.toggle("active", provider === "gemini");
  els.tagJev.style.visibility = provider === "jev" ? "visible" : "hidden";
  els.tagGemini.style.visibility = provider === "gemini" ? "visible" : "hidden";
}

function renderChips() {
  els.chips.textContent = "";
  if (!entries.length) {
    const empty = document.createElement("span");
    empty.className = "chipsEmpty";
    empty.textContent = "No blocked topics yet \u2014 nothing will be blocked.";
    els.chips.appendChild(empty);
    return;
  }
  entries.forEach((entry, index) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    const label = document.createElement("span");
    label.textContent = entry;
    label.title = entry;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "\u00d7";
    remove.title = "Remove";
    remove.addEventListener("click", () => {
      entries.splice(index, 1);
      renderChips();
    });
    chip.appendChild(label);
    chip.appendChild(remove);
    els.chips.appendChild(chip);
  });
}

function addEntriesFromInput() {
  const raw = els.entryInput.value;
  if (!raw.trim()) return;
  const parts = raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  let added = 0;
  for (const part of parts) {
    const value = part.slice(0, 400);
    if (value && entries.indexOf(value) === -1) {
      entries.push(value);
      added++;
    }
  }
  els.entryInput.value = "";
  if (added) renderChips();
}

async function load() {
  const s = await SmartSettings.get();
  els.enabled.checked = !!s.enabled;
  els.serviceUrl.value = s.serviceUrl;
  els.keyJev.value = (s.keys && s.keys.jev) || "";
  els.keyGemini.value = (s.keys && s.keys.gemini) || "";
  els.modelJev.value = (s.models && s.models.jev) || SmartSettings.DEFAULTS.models.jev;
  els.modelGemini.value = (s.models && s.models.gemini) || SmartSettings.DEFAULTS.models.gemini;
  entries = Array.isArray(s.entries) ? s.entries.slice() : [];
  setProvider(s.provider);
  renderChips();
  els.testProvider.value = provider;
}

function flash(text) {
  els.saveStatus.textContent = text;
  setTimeout(() => {
    if (els.saveStatus.textContent === text) els.saveStatus.textContent = "";
  }, 2200);
}

async function save() {
  const url = els.serviceUrl.value.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?$/i.test(url)) {
    alert("Service URL must look like http://127.0.0.1:8765");
    return;
  }
  setProvider(provider);
  await SmartSettings.set({
    enabled: els.enabled.checked,
    serviceUrl: url,
    provider: provider,
    entries: entries,
    models: {
      jev: els.modelJev.value.trim() || SmartSettings.DEFAULTS.models.jev,
      gemini: els.modelGemini.value.trim() || SmartSettings.DEFAULTS.models.gemini,
    },
    keys: {
      jev: els.keyJev.value.trim(),
      gemini: els.keyGemini.value.trim(),
    },
  });
  try {
    await send("clear-cache", {});
  } catch (err) {
    // cache clearing is best-effort
  }
  flash("Saved \u2713");
}

function showTestResult(res) {
  els.testResult.className = "result show";
  if (!res || !res.ok) {
    els.testResult.classList.add("ERROR");
    els.testResult.textContent = "Error: " + ((res && res.error) || "no response");
    return;
  }
  const r = res.result || {};
  els.testResult.classList.add(r.status || "ERROR");
  const bits = [r.status || "?"];
  if (typeof r.stage === "number") bits.push("stage " + r.stage);
  if (r.provider) bits.push(r.provider);
  if (r.model) bits.push(r.model);
  if (typeof r.latency_ms === "number") bits.push(r.latency_ms + " ms");
  let text = bits.join(" \u00b7 ");
  if (r.reason) text += "\n" + r.reason;
  if (r.matched_category) text += "\nmatched: " + r.matched_category;
  els.testResult.textContent = text;
}

async function testConnection() {
  els.testConnBtn.disabled = true;
  els.testResult.className = "result show ERROR";
  els.testResult.textContent = "Testing\u2026";
  try {
    const res = await send("test", {});
    if (res && res.ok) {
      const h = res.health || {};
      els.testResult.className = "result show ALLOWED";
      els.testResult.textContent =
        "Connected to Smart-Filter service \u00b7 default: " +
        (h.default_provider || "?") +
        (h.providers ? " \u00b7 providers: " + h.providers.join(", ") : "");
    } else {
      els.testResult.className = "result show ERROR";
      els.testResult.textContent = "Unavailable: " + ((res && res.error) || "no service");
    }
  } finally {
    els.testConnBtn.disabled = false;
  }
}

async function testQuery() {
  const q = els.testQuery.value.trim();
  if (!q) return;
  els.testQueryBtn.disabled = true;
  els.testQueryBtn.textContent = "Checking\u2026";
  els.testResult.className = "result";
  try {
    const res = await send("test-query", { query: q, provider: els.testProvider.value });
    showTestResult(res);
  } finally {
    els.testQueryBtn.disabled = false;
    els.testQueryBtn.textContent = "Check query";
  }
}

els.providerSeg.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-provider]");
  if (btn) {
    setProvider(btn.dataset.provider);
    els.testProvider.value = provider;
  }
});

for (const btn of document.querySelectorAll("button[data-reveal]")) {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.reveal);
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    btn.textContent = showing ? "show" : "hide";
  });
}

els.addEntry.addEventListener("click", addEntriesFromInput);
els.entryInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    addEntriesFromInput();
  }
});

els.testQueryBtn.addEventListener("click", testQuery);
els.testConnBtn.addEventListener("click", testConnection);
els.saveBtn.addEventListener("click", save);
els.testQuery.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") testQuery();
});

load();
