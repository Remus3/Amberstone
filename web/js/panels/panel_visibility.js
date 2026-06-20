// web/js/panels/panel_visibility.js
//
// RC2 E1: per-panel visibility gate (separate IN-GAME vs OUT-OF-GAME toggles).
//
// Single served-as-.js module (no .mjs HTTP dependency, so it loads in the live
// dashboard with no server MIME change). Two layers in one file:
//
//   PURE CORE (no DOM, node:testable - panel_visibility.test.mjs imports it):
//     GAME_PANELS / CONTEXTS / contextForMode / defaultVisibility /
//     readVisibility / serializeVisibility / setPanelVisible / isPanelVisible.
//
//   DOM WRAPPER (browser glue, DOM touched only at call time):
//     applyPanelVisibility()           - read body[data-mode] -> context, then
//                                         show/hide the five game panels.
//     buildPanelVisibilitySettings()   - render the settings-card matrix.
//     initPanelVisibility()            - wire both at boot.
//
// Persistence: a single localStorage JSON string keyed by context then panel id
//   { "in-game": { "<id>": true|false, ... }, "out-game": { ... } }
// Fail-OPEN everywhere: a missing / corrupt / partial blob, an unknown id, or a
// non-boolean value all resolve to VISIBLE - a bad pref must never strand a
// panel hidden. Hiding uses a dedicated data-pv-hidden attribute (NOT [hidden],
// which the per-panel renderers own) so we never fight a renderer.

// ── PURE CORE ───────────────────────────────────────────────────────────────

// The five in-game dashboard panels (web/index.html <main> sections). id is the
// section element id; label is the human name shown in the settings UI.
const GAME_PANELS = Object.freeze([
  Object.freeze({ id: "minimap", label: "Map State" }),
  Object.freeze({ id: "right-now", label: "Right Now" }),
  Object.freeze({ id: "next", label: "Next" }),
  Object.freeze({ id: "item-build", label: "Item Build" }),
  Object.freeze({ id: "adaptation", label: "Adaptation" }),
]);

const PANEL_IDS = Object.freeze(GAME_PANELS.map((p) => p.id));

// The two render contexts. in-game = a live match; out-game = everything else.
const CONTEXTS = Object.freeze(["in-game", "out-game"]);

// Game-mode tags (body.dataset.mode) that mean a live match is in progress.
// Mirrors the dashboard's own in-game gate (state.mode !== "client").
const GAME_MODE_TAGS = Object.freeze(
  new Set(["sr", "aram", "arena", "tft", "brawl"])
);

// localStorage key for the persisted visibility blob.
const STORAGE_KEY = "rc-panel-visibility";

// Map a mode tag (body.dataset.mode) to a render context. Anything that is not
// a recognized game mode (client / lobby / "" / non-string) is out-game.
function contextForMode(modeTag) {
  const m = typeof modeTag === "string" ? modeTag.trim().toLowerCase() : "";
  return GAME_MODE_TAGS.has(m) ? "in-game" : "out-game";
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

// Coerce whatever was parsed from a (possibly hand-edited / partial / garbage)
// blob into a complete, validated visibility map. Only known contexts + known
// panel ids survive; only a real boolean false hides a panel (everything else
// is visible). Always returns a full map (every context + every panel present).
function normalizeVisibility(parsed) {
  const base = defaultVisibility();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return base;
  }
  for (const ctx of CONTEXTS) {
    const src = parsed[ctx];
    if (!src || typeof src !== "object" || Array.isArray(src)) {
      continue;
    }
    for (const id of PANEL_IDS) {
      // Only an explicit boolean false hides; any other value stays visible.
      if (src[id] === false) {
        base[ctx][id] = false;
      } else if (src[id] === true) {
        base[ctx][id] = true;
      }
    }
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

// Serialize a visibility map back to a compact blob string.
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

// ── DOM WRAPPER (browser glue; DOM touched only at call time) ────────────────

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

// Apply the persisted visibility for the CURRENT context to every game panel.
// Hidden -> data-pv-hidden="1" (CSS sets display:none); visible -> attribute
// removed. The overlay shell (?overlay=1) is left entirely alone - overlay.css
// owns that surface's panel set, and the operator's full-dashboard prefs must
// not blank the compact HUD.
function applyPanelVisibility() {
  if (document.body && document.body.dataset.shell === "overlay") {
    return;
  }
  const blob = _loadBlob();
  const map = readVisibility(blob);
  const ctx = _currentContext();
  const ctxMap = map[ctx] || {};
  for (const panel of GAME_PANELS) {
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

// Build (idempotently) the "PANEL VISIBILITY" settings card: a small matrix with
// each panel on a row and two checkboxes (In-game / Out-of-game). Clicking a box
// persists + re-applies live. Mounts into #settings-body if present.
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
    "Show or hide each in-game dashboard panel, separately for when a match is live (In-game) vs the client / lobby / post-game (Out-of-game).";
  card.appendChild(note);

  const table = document.createElement("div");
  table.className = "pv-table";

  // Column header row.
  const headRow = document.createElement("div");
  headRow.className = "pv-row pv-row-head";
  const blank = document.createElement("span");
  blank.className = "pv-panel-name";
  blank.textContent = "Panel";
  headRow.appendChild(blank);
  for (const ctx of CONTEXTS) {
    const c = document.createElement("span");
    c.className = "pv-col-head";
    c.textContent = ctx === "in-game" ? "In-game" : "Out-of-game";
    headRow.appendChild(c);
  }
  table.appendChild(headRow);

  const map = readVisibility(_loadBlob());

  for (const panel of GAME_PANELS) {
    const row = document.createElement("div");
    row.className = "pv-row";

    const name = document.createElement("span");
    name.className = "pv-panel-name";
    name.textContent = panel.label;
    row.appendChild(name);

    for (const ctx of CONTEXTS) {
      const cell = document.createElement("label");
      cell.className = "pv-cell";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = (map[ctx] || {})[panel.id] !== false;
      cb.setAttribute("aria-label", `${panel.label} - ${ctx}`);
      cb.dataset.pvContext = ctx;
      cb.dataset.pvPanel = panel.id;
      cb.addEventListener("change", () => {
        const next = setPanelVisible(_loadBlob(), ctx, panel.id, cb.checked);
        _saveBlob(next);
        applyPanelVisibility();
      });
      cell.appendChild(cb);
      row.appendChild(cell);
    }
    table.appendChild(row);
  }

  card.appendChild(table);
  host.appendChild(card);
}

// One-time init: build the settings card, apply current prefs, and re-apply on
// every state tick (the mode tag flips in-game <-> out-game as matches start /
// end). setMode() in main.js also calls applyPanelVisibility on each real mode
// change; the listener here is a belt-and-suspenders re-apply if that event is
// ever wired to dispatch.
function initPanelVisibility() {
  try {
    buildPanelVisibilitySettings();
    applyPanelVisibility();
    window.addEventListener("rc:state-tick", applyPanelVisibility);
  } catch (_e) {
    // visibility is a nicety; never let it break the dashboard boot.
  }
}

export {
  // pure core
  GAME_PANELS,
  PANEL_IDS,
  CONTEXTS,
  GAME_MODE_TAGS,
  STORAGE_KEY,
  contextForMode,
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
