// web/js/panels/panel_visibility.js
//
// RC2 E1 + QA slice B (2026-07-03): PER-MODE panel visibility gate.
//
// The original RC2 E1 gate had two contexts (in-game / out-game). The
// champ-select QA ruling (docs/qa/CHAMP_SELECT_QA_2026-07-03.md section C)
// replaces that with one context per live game mode plus out-of-game:
//
//   in-game-sr / in-game-aram / in-game-arena / in-game-tft / out-game
//
// so the operator can, e.g., hide the ARAM balance grid everywhere except
// ARAM, or run a minimal TFT layout without touching the SR one.
//
// Single served-as-.js module (no .mjs HTTP dependency, so it loads in the
// live dashboard with no server MIME change). Two layers in one file:
//
//   PURE CORE (no DOM, node:testable - panel_visibility.test.mjs imports it):
//     PANELS / CONTEXTS / TABS / contextForMode / normalizeTab /
//     defaultVisibility / readVisibility / serializeVisibility /
//     setPanelVisible / isPanelVisible.
//
//   DOM WRAPPER (browser glue, DOM touched only at call time):
//     applyPanelVisibility()           - read body[data-mode] -> context, then
//                                         show/hide every registered panel.
//     buildPanelVisibilitySettings()   - render the settings card: a
//                                         SR/ARAM/ARENA/TFT/OUT-OF-GAME tab
//                                         bar over a one-column checkbox grid.
//     initPanelVisibility()            - wire both at boot.
//
// Persistence: a single localStorage JSON string keyed by context then panel
// id (key unchanged from RC2 E1 so existing prefs survive):
//   { "in-game-sr": { "<id>": true|false, ... }, ..., "out-game": { ... } }
// MIGRATION: a legacy blob may still carry the old "in-game" context; its
// prefs are copied to every in-game-* context on read (one-way - the next
// write serializes only the five current contexts).
// Fail-OPEN everywhere: a missing / corrupt / partial blob, an unknown id, or
// a non-boolean value all resolve to VISIBLE - a bad pref must never strand a
// panel hidden. Hiding uses a dedicated data-pv-hidden attribute (NOT [hidden],
// which the per-panel renderers own) so we never fight a renderer.

// -- PURE CORE ----------------------------------------------------------------

// All operator-facing main-dashboard panels (web/index.html), expanded from
// the legacy 5 <main> sections to every togglable id'd block the QA ruling
// covers. id is the element id; label is the human name in the settings UI.
// A panel id absent from this registry is simply never hidden (fail-open).
const PANELS = Object.freeze([
  // the legacy 5 <main> game panels
  Object.freeze({ id: "minimap", label: "Map State" }),
  Object.freeze({ id: "right-now", label: "Right Now" }),
  Object.freeze({ id: "next", label: "Next" }),
  Object.freeze({ id: "item-build", label: "Item Build" }),
  Object.freeze({ id: "adaptation", label: "Adaptation" }),
  // main-surface feature blocks (each renderer-gated via [hidden]; the
  // pv gate layers on top without fighting the renderer)
  Object.freeze({ id: "coach-decisions", label: "Coach Decisions" }),
  Object.freeze({ id: "rn-lead", label: "Macro Lead" }),
  Object.freeze({ id: "rn-choices", label: "Coach Choices" }),
  Object.freeze({ id: "rn-callouts", label: "Callouts" }),
  Object.freeze({ id: "personal-context-section", label: "Personal Context" }),
  // session / post-game-review blocks
  Object.freeze({ id: "session-trend", label: "Session Summary" }),
  Object.freeze({ id: "lm-tc-table", label: "Team Context (Last Match)" }),
  Object.freeze({ id: "hpgr-tc-table", label: "Team Context (Archive)" }),
  // active-match view blocks (dashboard-rendered; overlay-only widgets like
  // am-obj-gauges / am-ward-cue are EXCLUDED - the overlay shell is exempt
  // from this gate entirely, so listing them would be dead checkboxes)
  Object.freeze({ id: "am-spike-curve", label: "Spike Curve" }),
  Object.freeze({ id: "am-spike-markers", label: "Spike Markers" }),
  Object.freeze({ id: "am-ward-heat", label: "Ward Heatmap" }),
  Object.freeze({ id: "aram-balance-panel", label: "ARAM Balance Grid" }),
]);

// Back-compat alias (pre-QA-B name; same frozen array).
const GAME_PANELS = PANELS;

const PANEL_IDS = Object.freeze(PANELS.map((p) => p.id));

// The five render contexts: one per live game mode + everything else.
const IN_GAME_CONTEXTS = Object.freeze([
  "in-game-sr",
  "in-game-aram",
  "in-game-arena",
  "in-game-tft",
]);
const CONTEXTS = Object.freeze([...IN_GAME_CONTEXTS, "out-game"]);

// The old 2-context model's live-match key; read-migrated, never written.
const LEGACY_IN_GAME_KEY = "in-game";

// Mode tag (body.dataset.mode) -> render context. brawl is retired from
// champ-select (s214) but the legacy backend still emits the tag; it inherits
// the SR prefs rather than getting a dead fifth tab.
const MODE_CONTEXTS = Object.freeze({
  sr: "in-game-sr",
  aram: "in-game-aram",
  arena: "in-game-arena",
  tft: "in-game-tft",
  brawl: "in-game-sr",
});

// Game-mode tags that mean a live match is in progress (kept for back-compat;
// mirrors the dashboard's own in-game gate, state.mode !== "client").
const GAME_MODE_TAGS = Object.freeze(new Set(Object.keys(MODE_CONTEXTS)));

// localStorage key for the persisted visibility blob (unchanged from RC2 E1).
const STORAGE_KEY = "rc-panel-visibility";

// sessionStorage key for the selected settings tab (per-session sticky).
const TAB_STORAGE_KEY = "rc-pv-tab";

// Settings-card tabs: one per context, in CONTEXTS order. ASCII labels only.
const TABS = Object.freeze([
  Object.freeze({ context: "in-game-sr", label: "SR" }),
  Object.freeze({ context: "in-game-aram", label: "ARAM" }),
  Object.freeze({ context: "in-game-arena", label: "ARENA" }),
  Object.freeze({ context: "in-game-tft", label: "TFT" }),
  Object.freeze({ context: "out-game", label: "OUT-OF-GAME" }),
]);

// Map a mode tag (body.dataset.mode) to a render context. Anything that is
// not a recognized game mode (client / lobby / "" / non-string) is out-game.
// hasOwnProperty guard: a tag like "constructor" must not walk the prototype.
function contextForMode(modeTag) {
  const m = typeof modeTag === "string" ? modeTag.trim().toLowerCase() : "";
  return Object.prototype.hasOwnProperty.call(MODE_CONTEXTS, m)
    ? MODE_CONTEXTS[m]
    : "out-game";
}

// Validate a stored tab value; junk falls back to the caller's context, and a
// junk fallback resolves to the SR tab. Never throws, never returns invalid.
function normalizeTab(raw, fallback) {
  const fb = CONTEXTS.includes(fallback) ? fallback : "in-game-sr";
  if (typeof raw !== "string") {
    return fb;
  }
  const t = raw.trim();
  return CONTEXTS.includes(t) ? t : fb;
}

// A fresh all-visible map: every panel visible in every context.
function defaultVisibility() {
  const out = {};
  for (const ctx of CONTEXTS) {
    out[ctx] = {};
    for (const id of PANEL_IDS) {
      out[ctx][id] = true;
    }
  }
  return out;
}

// Read one context sub-object's booleans into base[ctx] (fail-open: only a
// real boolean is honored; anything else keeps the default true).
function _foldContext(base, ctx, src) {
  if (!src || typeof src !== "object" || Array.isArray(src)) {
    return;
  }
  for (const id of PANEL_IDS) {
    if (src[id] === false) {
      base[ctx][id] = false;
    } else if (src[id] === true) {
      base[ctx][id] = true;
    }
  }
}

// Coerce whatever was parsed from a (possibly hand-edited / partial / legacy /
// garbage) blob into a complete, validated visibility map. Only known contexts
// + known panel ids survive; only a real boolean false hides a panel. A legacy
// "in-game" key is MIGRATED: its prefs seed every in-game-* context, then any
// explicit per-mode entries override. Always returns a full map.
function normalizeVisibility(parsed) {
  const base = defaultVisibility();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return base;
  }
  // migration first, so explicit per-mode prefs win below
  const legacy = parsed[LEGACY_IN_GAME_KEY];
  if (legacy && typeof legacy === "object" && !Array.isArray(legacy)) {
    for (const ctx of IN_GAME_CONTEXTS) {
      _foldContext(base, ctx, legacy);
    }
  }
  for (const ctx of CONTEXTS) {
    _foldContext(base, ctx, parsed[ctx]);
  }
  return base;
}

// Parse + normalize a stored blob string into a full visibility map. Never
// throws: bad JSON / wrong shape -> the all-visible default.
function readVisibility(blobStr) {
  if (typeof blobStr !== "string" || !blobStr.trim()) {
    return defaultVisibility();
  }
  let parsed = null;
  try {
    parsed = JSON.parse(blobStr);
  } catch (_e) {
    return defaultVisibility();
  }
  return normalizeVisibility(parsed);
}

// Serialize a visibility map back to a compact blob string (current contexts
// only - the legacy "in-game" key never survives a write).
function serializeVisibility(map) {
  return JSON.stringify(normalizeVisibility(map));
}

// Return a NEW blob string with one panel's visibility set in one context.
// Unknown context or panel id is a no-op (returns a normalized blob unchanged).
// Never throws; garbage prev blob starts from the all-visible default.
function setPanelVisible(prevBlobStr, context, panelId, visible) {
  const map = readVisibility(prevBlobStr);
  if (CONTEXTS.includes(context) && PANEL_IDS.includes(panelId)) {
    map[context][panelId] = visible === true;
  }
  return serializeVisibility(map);
}

// Resolve a single panel's visibility for a context out of a blob. Fail-open:
// an unknown context / panel id resolves to true (visible).
function isPanelVisible(blobStr, context, panelId) {
  const map = readVisibility(blobStr);
  if (!CONTEXTS.includes(context) || !PANEL_IDS.includes(panelId)) {
    return true;
  }
  return map[context][panelId] !== false;
}

// -- DOM WRAPPER (browser glue; DOM touched only at call time) -----------------

// Read the persisted blob string from localStorage (null-safe).
function _loadBlob() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch (_e) {
    return "";
  }
}

// Persist a blob string to localStorage (best-effort; never throws).
function _saveBlob(blobStr) {
  try {
    localStorage.setItem(STORAGE_KEY, blobStr);
  } catch (_e) {
    // private-mode / quota: the in-DOM state still applied this session.
  }
}

// Derive the current render context from the live mode tag on the body.
function _currentContext() {
  const mode =
    (document.body && document.body.dataset && document.body.dataset.mode) || "";
  return contextForMode(mode);
}

// Selected settings tab: sessionStorage-persisted, defaulting to the LIVE
// context so the operator lands on the tab that matches what is on screen.
function _loadTab() {
  let raw = null;
  try {
    raw = sessionStorage.getItem(TAB_STORAGE_KEY);
  } catch (_e) {
    raw = null;
  }
  return normalizeTab(raw, _currentContext());
}

function _saveTab(context) {
  try {
    sessionStorage.setItem(TAB_STORAGE_KEY, context);
  } catch (_e) {
    // best-effort; the in-DOM selection still applied this session.
  }
}

// Apply the persisted visibility for the CURRENT context to every registered
// panel. Hidden -> data-pv-hidden="1" (CSS sets display:none); visible ->
// attribute removed. The overlay shell (?overlay=1) is left entirely alone -
// overlay.css owns that surface's panel set, and the operator's
// full-dashboard prefs must not blank the compact HUD.
function applyPanelVisibility() {
  if (document.body && document.body.dataset.shell === "overlay") {
    return;
  }
  const blob = _loadBlob();
  const map = readVisibility(blob);
  const ctx = _currentContext();
  const ctxMap = map[ctx] || {};
  for (const panel of PANELS) {
    const elPanel = document.getElementById(panel.id);
    if (!elPanel) {
      continue;
    }
    if (ctxMap[panel.id] === false) {
      elPanel.dataset.pvHidden = "1";
    } else if (elPanel.dataset.pvHidden) {
      delete elPanel.dataset.pvHidden;
    }
  }
}

// Rebuild the per-context checkbox rows for the selected tab. Idempotent:
// wipes + refills the rows host only (tab bar + note are stable).
function _renderRows(host, context) {
  host.textContent = "";

  const headRow = document.createElement("div");
  headRow.className = "pv-row pv-row-head";
  const headName = document.createElement("span");
  headName.className = "pv-panel-name";
  headName.textContent = "Panel";
  headRow.appendChild(headName);
  const headCol = document.createElement("span");
  headCol.className = "pv-col-head";
  headCol.textContent = "Show";
  headRow.appendChild(headCol);
  host.appendChild(headRow);

  const map = readVisibility(_loadBlob());
  for (const panel of PANELS) {
    const row = document.createElement("div");
    row.className = "pv-row";

    const name = document.createElement("span");
    name.className = "pv-panel-name";
    name.textContent = panel.label;
    row.appendChild(name);

    const cell = document.createElement("label");
    cell.className = "pv-cell";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = (map[context] || {})[panel.id] !== false;
    cb.setAttribute("aria-label", `${panel.label} - ${context}`);
    cb.dataset.pvContext = context;
    cb.dataset.pvPanel = panel.id;
    cb.addEventListener("change", () => {
      const next = setPanelVisible(_loadBlob(), context, panel.id, cb.checked);
      _saveBlob(next);
      applyPanelVisibility();
    });
    cell.appendChild(cb);
    row.appendChild(cell);
    host.appendChild(row);
  }
}

// Paint tab selection state + re-render the rows for the picked tab.
function _selectTab(card, context) {
  const tabs = card.querySelectorAll(".pv-tab");
  for (const btn of tabs) {
    const on = btn.dataset.pvTab === context;
    btn.setAttribute("aria-selected", on ? "true" : "false");
    btn.tabIndex = on ? 0 : -1;
  }
  const host = card.querySelector(".pv-table");
  if (host) {
    _renderRows(host, context);
  }
}

// Build (idempotently) the "PANEL VISIBILITY" settings card: a
// SR / ARAM / ARENA / TFT / OUT-OF-GAME tab bar over a one-column checkbox
// grid for the selected context. Clicking a box persists + re-applies live.
// Mounts into #settings-body if present.
function buildPanelVisibilitySettings() {
  const host = document.getElementById("settings-body");
  if (!host || document.getElementById("panel-visibility-card")) {
    return;
  }
  const card = document.createElement("div");
  card.className = "settings-card";
  card.id = "panel-visibility-card";

  const head = document.createElement("div");
  head.className = "settings-card-head";
  head.textContent = "PANEL VISIBILITY";
  card.appendChild(head);

  const note = document.createElement("div");
  note.className = "pv-note";
  note.textContent =
    "Show or hide each dashboard panel, separately per game mode (SR / ARAM / ARENA / TFT) and for the client / lobby / post-game (OUT-OF-GAME).";
  card.appendChild(note);

  const tabBar = document.createElement("div");
  tabBar.className = "pv-tabs";
  tabBar.setAttribute("role", "tablist");
  tabBar.setAttribute("aria-label", "Panel visibility context");
  for (const tab of TABS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pv-tab";
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", "false");
    btn.textContent = tab.label;
    btn.dataset.pvTab = tab.context;
    btn.addEventListener("click", () => {
      _saveTab(tab.context);
      _selectTab(card, tab.context);
    });
    tabBar.appendChild(btn);
  }
  card.appendChild(tabBar);

  const table = document.createElement("div");
  table.className = "pv-table";
  card.appendChild(table);

  host.appendChild(card);
  _selectTab(card, _loadTab());
}

// One-time init: build the settings card and apply current prefs. The live
// re-apply path is setMode() in main.js calling applyPanelVisibility on each
// real mode change (the mode tag now resolves per-mode in-game-* contexts as
// matches start / end / switch queue).
function initPanelVisibility() {
  try {
    buildPanelVisibilitySettings();
    applyPanelVisibility();
  } catch (_e) {
    // visibility is a nicety; never let it break the dashboard boot.
  }
}

export {
  // pure core
  PANELS,
  GAME_PANELS,
  PANEL_IDS,
  CONTEXTS,
  IN_GAME_CONTEXTS,
  GAME_MODE_TAGS,
  STORAGE_KEY,
  TAB_STORAGE_KEY,
  TABS,
  contextForMode,
  normalizeTab,
  defaultVisibility,
  normalizeVisibility,
  readVisibility,
  serializeVisibility,
  setPanelVisible,
  isPanelVisible,
  // dom wrapper
  applyPanelVisibility,
  buildPanelVisibilitySettings,
  initPanelVisibility,
};
