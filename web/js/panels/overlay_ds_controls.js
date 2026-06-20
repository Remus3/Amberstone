// In-overlay DS fight-model controls (HZ-D1 Phase 4,
// docs/ELECTRON_OVERLAY.md). Overlay-only sibling of the champ-select
// ds_knobs.js panel: mid-match the operator overrides enemy armor /
// enemy MR / gold cap / fight length and the DS build ranking re-ranks
// for that chosen fight model - the re-ranked rows list IS the "build
// reorder" surface. Mounts in #am-pane-ovds (web/index.html, inside
// .am-grid after the BUILD pane); the pane defaults to display:none on
// every surface (overlay_ds_controls.css) and only the
// body[data-shell="overlay"] chain in overlay.css section 4b shows it.
//
// Shares fetchDsKnobs / getCachedDsKnobs with ds_knobs.js - pure
// keyed-cache helpers over GET /api/ds-knobs (item 219C backend; the
// FOUR knobs map 1:1 onto existing rank_items args, zero backend
// change). The champ-select render fn is deliberately NOT imported: it
// carries that panel's singleton wiring (its module wired flag) which
// this surface must never poke.
//
// Inputs differ from champ-select: the live envelope carries a DISPLAY
// champion name (p.champion, e.g. "Tahm Kench"), not a numeric LCU id,
// so canonicalization goes display name -> DDragon slug ("TahmKench")
// against the CHAMPS.byId slug set with the same lowercase + strip
// normalization active_match.js uses for _SPK_NAME_TO_KEY. Mode is the
// lowercase rc mode string (ctx.mode), not a queue id.
//
// Discipline: pure ESM, ASCII only, GPU-light (no canvas, no
// animation), sig-dedup gate on the rows paint so the 1Hz state tick
// does not thrash the DOM, knob re-fetches debounced. Mirrors the
// ds_knobs.js patterns.

import { fetchDsKnobs, getCachedDsKnobs } from './ds_knobs.js';
import { CHAMPS, _resolveItemId } from '../lib/items_index.js';
import { readOverlaySettings, writeOverlaySettings, hydrateOverlaySettings, sendOverlayAction } from '../lib/overlay_settings.js';

const _OVDS_DEBOUNCE_MS = 350;
const _OVDS_ROW_CAP = 5;

// Lowercase rc mode string -> DS engine mode. Unknown modes fall back
// to SR (the engine's default resist curve) rather than hiding the pane.
const _OVDS_MODE_MAP = {
  sr: "SR", classic: "SR", aram: "ARAM",
  arena: "ARENA", cherry: "ARENA", brawl: "BRAWL",
};

// Per-champion operator knob overrides (null = auto / no-cap /
// no-reweight). Module-scope so a state tick never wipes a knob the
// operator just set mid-game.
const _OVDS_KNOBS = Object.create(null);  // champ -> {armor, mr, budget, fight_length}

// Memoized norm(slug) -> slug map over CHAMPS.byId values, keyed on
// CHAMPS.version so a patch-bump index reload rebuilds it.
const _OVDS_SLUGS = { ready: false, version: "", map: Object.create(null) };

let _ovdsSig = null;            // last painted knobs+rows signature
let _ovdsDebounceTimer = null;
// Latest envelope, so the debounced knob repaint re-renders with fresh
// level/items instead of the ones captured when the strip was wired.
const _OVDS_LAST = { p: null, ctx: null };

function _modeForCtx(mode) {
  return _OVDS_MODE_MAP[String(mode || "").toLowerCase()] || "SR";
}

function _norm(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
}

function _canonicalChamp(displayName) {
  if (!displayName) return "";
  if (!CHAMPS.byId || !Object.keys(CHAMPS.byId).length) return "";
  if (!_OVDS_SLUGS.ready || _OVDS_SLUGS.version !== CHAMPS.version) {
    _OVDS_SLUGS.map = Object.create(null);
    for (const slug of Object.values(CHAMPS.byId)) {
      if (slug) _OVDS_SLUGS.map[_norm(slug)] = slug;
    }
    _OVDS_SLUGS.version = CHAMPS.version;
    _OVDS_SLUGS.ready = true;
  }
  return _OVDS_SLUGS.map[_norm(displayName)] || "";
}

function _clampLevel(raw) {
  const n = parseInt(raw, 10) || 1;
  return Math.min(18, Math.max(1, n));
}

function _knobsFor(champ) {
  if (!_OVDS_KNOBS[champ]) {
    _OVDS_KNOBS[champ] = { armor: null, mr: null, budget: null, fight_length: null };
  }
  return _OVDS_KNOBS[champ];
}

function _numOrNull(raw) {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

// Signature over knobs + rows: knob edits and re-ranks repaint, an
// unchanged payload on the next state tick does not.
function _signature(payload, knobs) {
  const k = knobs || {};
  const head = [k.armor, k.mr, k.budget, k.fight_length]
    .map((v) => (v === null || v === undefined ? "" : v)).join("/");
  if (!payload || !payload.ok) {
    return head + "#" + (payload && payload.reason ? `_${payload.reason}` : "_empty");
  }
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  return head + "#" + (rows
    .map((r) => `${r.item_id}:${Math.round(+r.delta_dps || 0)}`)
    .join("|") || "_norows");
}

function _goldLabel(g) {
  const n = +g || 0;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

// HTML-escape free-form strings (item names) before innerHTML. Mirrors the
// local _esc pattern in ds_matchup.js / ds_knobs.js.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// The live coach payload carries item NAMES ("Mortal Reminder") while
// /api/ds-knobs accepts item IDS only (a name in the csv 503s the
// route - probed live 2026-06-10). Numeric strings pass through; names
// bridge via the shared items_index resolver; unresolved entries drop
// (a missing build slot only widens the candidate pool, never errors).
function _itemIds(raw) {
  const out = [];
  for (const entry of (Array.isArray(raw) ? raw : [])) {
    const s = String(entry || "").trim();
    if (!s) continue;
    if (/^\d+$/.test(s)) { out.push(s); continue; }
    const id = _resolveItemId(s);
    if (id) out.push(String(id));
  }
  return out;
}

function _rowsHtml(payload) {
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (!rows.length) {
    return `<div class="ovds-empty">no items rank under this fight model</div>`;
  }
  return rows.slice(0, _OVDS_ROW_CAP).map((r) => (
    `<div class="ovds-row">`
    + `<span class="ovds-item">${_esc(r.name || r.item_id || "")}</span>`
    + `<span class="ovds-delta">+${Math.round(+r.delta_dps || 0)}</span>`
    + `<span class="ovds-gold">${_goldLabel(r.gold)}g</span>`
    + `</div>`
  )).join("");
}

function _stripHtml(knobs, resolved) {
  // Override shown as the value; resolved auto value as the placeholder
  // so an untouched field reads "auto 80" (mirrors ds_knobs.js).
  const ra = resolved && resolved.target_armor != null ? ` ${resolved.target_armor}` : "";
  const rm = resolved && resolved.target_mr != null ? ` ${resolved.target_mr}` : "";
  const av = knobs.armor === null ? "" : knobs.armor;
  const mv = knobs.mr === null ? "" : knobs.mr;
  const bv = knobs.budget === null ? "" : knobs.budget;
  const fv = knobs.fight_length === null ? "" : knobs.fight_length;
  return (
    `<div class="ovds-strip">`
    + `<label class="ovds-knob"><span>Enemy armor</span>`
    + `<input type="number" id="ovds-armor" min="0" max="500" step="5"`
    + ` value="${av}" placeholder="auto${ra}"></label>`
    + `<label class="ovds-knob"><span>Enemy MR</span>`
    + `<input type="number" id="ovds-mr" min="0" max="500" step="5"`
    + ` value="${mv}" placeholder="auto${rm}"></label>`
    + `<label class="ovds-knob"><span>Gold cap</span>`
    + `<input type="number" id="ovds-budget" min="0" max="20000" step="250"`
    + ` value="${bv}" placeholder="none"></label>`
    + `<label class="ovds-knob"><span>Fight len (s)</span>`
    + `<input type="number" id="ovds-flen" min="0" max="120" step="0.5"`
    + ` value="${fv}" placeholder="auto"></label>`
    + `</div>`
    + `<div class="ovds-rows" id="ovds-rows"></div>`
  );
}

function _refreshPlaceholders(body, resolved, knobs) {
  const a = body.querySelector("#ovds-armor");
  const m = body.querySelector("#ovds-mr");
  if (a && knobs.armor === null && resolved.target_armor != null) {
    a.placeholder = `auto ${resolved.target_armor}`;
  }
  if (m && knobs.mr === null && resolved.target_mr != null) {
    m.placeholder = `auto ${resolved.target_mr}`;
  }
}

function _wireInputs(body, champ) {
  const onChange = () => {
    const knobs = _knobsFor(champ);
    const a = body.querySelector("#ovds-armor");
    const m = body.querySelector("#ovds-mr");
    const b = body.querySelector("#ovds-budget");
    const f = body.querySelector("#ovds-flen");
    knobs.armor = a ? _numOrNull(a.value) : null;
    knobs.mr = m ? _numOrNull(m.value) : null;
    knobs.budget = b ? _numOrNull(b.value) : null;
    knobs.fight_length = f ? _numOrNull(f.value) : null;
    if (_ovdsDebounceTimer) clearTimeout(_ovdsDebounceTimer);
    _ovdsDebounceTimer = setTimeout(() => {
      // Force a fresh rows paint after a knob change; re-render off the
      // LATEST envelope so the fetch carries current level/items, not
      // the ones captured when the strip was wired.
      _ovdsSig = null;
      renderOverlayDsControls(_OVDS_LAST.p || {}, _OVDS_LAST.ctx || {});
    }, _OVDS_DEBOUNCE_MS);
  };
  ["ovds-armor", "ovds-mr", "ovds-budget", "ovds-flen"].forEach((id) => {
    const el = body.querySelector("#" + id);
    if (el) el.addEventListener("input", onChange);
  });
}

// --- OVL1: overlay settings strip (pulse toggle + ACTIVE auto-revert sec) -----
// Mounted once at the top of the pane, independent of a resolved champion, so
// the operator can set them out of a fight model. Persisted via the shared
// helper (localStorage mirror + rc-shell IPC when inside the Electron shell).
function _settingsHtml() {
  return (
    `<div class="ovset" id="ovset">`
    + `<div class="ovset-cap">OVERLAY</div>`
    // RC2 3.4: keep the full dashboard window available in-game + pin it on top,
    // both toggleable WITHOUT a hotkey (writes mirror to the rc-shell over IPC).
    + `<label class="ovset-row ovset-toggle">`
    + `<input type="checkbox" id="ovset-keep">`
    + `<span>Keep dashboard</span></label>`
    + `<label class="ovset-row ovset-toggle">`
    + `<input type="checkbox" id="ovset-pin">`
    + `<span>Pin on top</span></label>`
    // RC2 4.3: on a single monitor, arrange the overlay + kept dashboard as
    // SEPARATED side-by-side windows so the dashboard is not under the HUD.
    + `<label class="ovset-row ovset-toggle">`
    + `<input type="checkbox" id="ovset-separate">`
    + `<span>Separate windows</span></label>`
    + `<label class="ovset-row ovset-toggle">`
    + `<input type="checkbox" id="ovset-pulse">`
    + `<span>Change pulse</span></label>`
    // RC2 4.2: click-through ZONES (hover an overlay control to interact without
    // the ACTIVE hotkey) + opacity (the HUD recedes into the game). Both
    // hotkey-free, mirror to the rc-shell over IPC.
    + `<label class="ovset-row ovset-toggle">`
    + `<input type="checkbox" id="ovset-zones">`
    + `<span>Hover to interact</span></label>`
    + `<label class="ovset-row ovset-range"><span>Opacity</span>`
    + `<input type="range" id="ovset-opacity" min="30" max="100" step="5"></label>`
    + `<label class="ovset-row ovset-num"><span>Auto-passive (s)</span>`
    + `<input type="number" id="ovset-revert" min="3" max="120" step="1" inputmode="numeric"></label>`
    // RC2 4.4: no-hotkey control of the overlay's last keyboard-only actions -
    // pick the panel set (was Alt+Shift+C cycle) + interact now (was Alt+Shift+A
    // passive<->active). Both fire one-way overlay ACTIONS at the rc-shell.
    + `<div class="ovset-row ovset-seg" id="ovset-panelset" role="group" aria-label="Panel set">`
    + `<button type="button" class="ovset-seg-btn" data-panelset="coach" aria-pressed="false">Coach</button>`
    + `<button type="button" class="ovset-seg-btn" data-panelset="build" aria-pressed="false">Build</button>`
    + `<button type="button" class="ovset-seg-btn" data-panelset="threat" aria-pressed="false">Threat</button>`
    + `</div>`
    + `<button type="button" class="ovset-row ovset-act" id="ovset-interact">Interact now</button>`
    // RC2 4.5: overlay + dashboard coexistence. Two on-screen buttons, both
    // one-way overlay ACTIONS (no persisted setting): Re-arrange re-separates
    // the overlay + kept dashboard on demand; Show dashboard raises the kept
    // dashboard forward beside the HUD. Neither hides the overlay, so there is
    // no stranding (unlike the Alt+Shift+O clear-both hotkey).
    + `<div class="ovset-row ovset-actpair">`
    + `<button type="button" class="ovset-act" id="ovset-rearrange">Re-arrange</button>`
    + `<button type="button" class="ovset-act" id="ovset-raise">Show dashboard</button>`
    + `</div>`
    + `</div>`
  );
}

// RC2 4.4: read the overlay's current panel set (the page was loaded at
// ?overlay=1&panelset=NAME; web/js/main.js stamps it on the body). Empty when on
// the default full subset (none of the 3 single sets) - then no segment is lit.
function _currentPanelset() {
  try {
    const ds = document.body && document.body.dataset ? document.body.dataset.panelset : "";
    if (ds) return ds;
    return new URLSearchParams(location.search).get("panelset") || "";
  } catch (_e) {
    return "";
  }
}

// Light the active panel-set segment (visual + aria-pressed) so the selector
// reflects the live overlay state without a shell round-trip.
function _markActivePanelset(body, active) {
  const seg = body.querySelector("#ovset-panelset");
  if (!seg) return;
  seg.querySelectorAll("[data-panelset]").forEach((b) => {
    const on = b.getAttribute("data-panelset") === active;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function _applySettingsToDom(body, s) {
  const keep = body.querySelector("#ovset-keep");
  const pin = body.querySelector("#ovset-pin");
  const separate = body.querySelector("#ovset-separate");
  const pulse = body.querySelector("#ovset-pulse");
  const zones = body.querySelector("#ovset-zones");
  const opacity = body.querySelector("#ovset-opacity");
  const rev = body.querySelector("#ovset-revert");
  // keepCompanion / companionAlwaysOnTop default ON, so an absent field reads as
  // checked (the dashboard-persist fix is the default state).
  if (keep) keep.checked = s.keepCompanion !== false;
  if (pin) pin.checked = s.companionAlwaysOnTop !== false;
  // RC2 4.3: separateWindows default ON (absent -> checked).
  if (separate) separate.checked = s.separateWindows !== false;
  if (pulse) pulse.checked = !!s.pulseNotify;
  // RC2 4.2: zones default ON (absent -> checked); opacity is a 30-100 percent
  // slider over the 0.3-1.0 setting. Do not clobber the slider while dragging.
  if (zones) zones.checked = s.clickThroughZones !== false;
  if (opacity && document.activeElement !== opacity) {
    const pct = Math.round((s.overlayOpacity == null ? 1 : s.overlayOpacity) * 100);
    opacity.value = String(pct);
  }
  // Do not clobber the seconds field while the operator is typing in it.
  if (rev && document.activeElement !== rev) rev.value = String(s.activeRevertSec);
}

function _wireSettings(body) {
  const keep = body.querySelector("#ovset-keep");
  const pin = body.querySelector("#ovset-pin");
  const pulse = body.querySelector("#ovset-pulse");
  const rev = body.querySelector("#ovset-revert");
  if (keep) {
    keep.addEventListener("change", () => {
      writeOverlaySettings({ keepCompanion: !!keep.checked });
    });
  }
  if (pin) {
    pin.addEventListener("change", () => {
      writeOverlaySettings({ companionAlwaysOnTop: !!pin.checked });
    });
  }
  const separate = body.querySelector("#ovset-separate");
  if (separate) {
    separate.addEventListener("change", () => {
      writeOverlaySettings({ separateWindows: !!separate.checked });
    });
  }
  if (pulse) {
    pulse.addEventListener("change", () => {
      writeOverlaySettings({ pulseNotify: !!pulse.checked });
    });
  }
  const zones = body.querySelector("#ovset-zones");
  if (zones) {
    zones.addEventListener("change", () => {
      writeOverlaySettings({ clickThroughZones: !!zones.checked });
    });
  }
  const opacity = body.querySelector("#ovset-opacity");
  if (opacity) {
    // input (live drag) writes the 0.3-1.0 setting from the 30-100 slider.
    opacity.addEventListener("input", () => {
      const pct = Number(opacity.value);
      if (Number.isFinite(pct)) writeOverlaySettings({ overlayOpacity: pct / 100 });
    });
  }
  if (rev) {
    rev.addEventListener("change", () => {
      const next = writeOverlaySettings({ activeRevertSec: rev.value });
      rev.value = String(next.activeRevertSec); // reflect the [3,120] clamp
    });
  }
  // RC2 4.4: panel-set selector (delegated click) + interact-now button. Both
  // fire one-way overlay ACTIONS; the shell validates + reloads the overlay /
  // flips click-through. A plain browser (no rcShell bridge) is a silent no-op.
  const seg = body.querySelector("#ovset-panelset");
  if (seg) {
    seg.addEventListener("click", (e) => {
      const btn = e.target && e.target.closest ? e.target.closest("[data-panelset]") : null;
      if (!btn) return;
      const ps = btn.getAttribute("data-panelset");
      sendOverlayAction({ action: "set-panel", panelSet: ps });
      _markActivePanelset(body, ps); // optimistic; the reload re-stamps it.
    });
  }
  const interact = body.querySelector("#ovset-interact");
  if (interact) {
    interact.addEventListener("click", () => {
      sendOverlayAction({ action: "set-active" });
    });
  }
  // RC2 4.5: coexistence actions - re-separate the windows / raise the kept
  // dashboard. One-way overlay ACTIONS; a plain browser (no rcShell) is a no-op.
  const rearrange = body.querySelector("#ovset-rearrange");
  if (rearrange) {
    rearrange.addEventListener("click", () => {
      sendOverlayAction({ action: "rearrange" });
    });
  }
  const raise = body.querySelector("#ovset-raise");
  if (raise) {
    raise.addEventListener("click", () => {
      sendOverlayAction({ action: "raise-companion" });
    });
  }
}

// Build the pane scaffold once: the settings strip + an empty knob-strip wrap.
// data-ovds-init guards the 1Hz tick from re-mounting (stacking settings
// handlers + wiping the knob strip).
function _ensureScaffold(body) {
  if (body.getAttribute("data-ovds-init") === "1") return;
  body.innerHTML = _settingsHtml() + `<div id="ovds-knobwrap"></div>`;
  body.setAttribute("data-ovds-init", "1");
  body.removeAttribute("data-ovds-champ"); // knob strip is (re)built below
  _wireSettings(body);
  _applySettingsToDom(body, readOverlaySettings());
  _markActivePanelset(body, _currentPanelset()); // RC2 4.4: reflect the live set
  // Hydrate from the rc-shell config (authoritative across launches), then
  // reflect into the controls. No-op / local-mirror in a plain browser.
  hydrateOverlaySettings().then((s) => _applySettingsToDom(body, s)).catch(() => {});
}

// Render the overlay fight-model pane from the per-mode coach payload p
// (p.champion display name, p.level, p.items) + ctx.mode (lowercase rc
// mode string). Hidden everywhere except the overlay shell with a
// resolved canonical champion.
export function renderOverlayDsControls(p, ctx) {
  const pane = document.getElementById("am-pane-ovds");
  if (!pane) return;
  // Gate 1: overlay-only surface. The normal 1920 dashboard never shows
  // this pane (its CSS base is display:none too - belt and braces).
  if (!document.body || document.body.dataset.shell !== "overlay") {
    pane.hidden = true;
    return;
  }
  p = p || {};
  ctx = ctx || {};
  _OVDS_LAST.p = p;
  _OVDS_LAST.ctx = ctx;

  const body = document.getElementById("ovds-body");
  if (!body) return;

  // OVL1: the overlay-settings strip mounts once and shows on the overlay shell
  // regardless of a resolved champion - the pane is visible for it. The
  // fight-model knob strip + rows only populate once a champion resolves.
  _ensureScaffold(body);
  pane.hidden = false;
  const knobwrap = body.querySelector("#ovds-knobwrap");

  // Gate 2: display name -> canonical DDragon slug. No champion yet (or CHAMPS
  // index still loading) -> keep just the settings strip; resolves on a later tick.
  const champ = _canonicalChamp(p.champion || "");
  if (!champ) {
    if (knobwrap) knobwrap.innerHTML = "";
    body.removeAttribute("data-ovds-champ");
    _ovdsSig = null;
    return;
  }
  const mode = _modeForCtx(ctx.mode);
  const level = _clampLevel(p.level);
  const items = _itemIds(p.items);
  const knobs = _knobsFor(champ);

  // Kick a (cached/deduped) fetch with the current knob state; the
  // onLand re-render paints the rows when the response arrives.
  fetchDsKnobs(champ, mode, items, knobs, level,
    () => renderOverlayDsControls(p, ctx));
  const payload = getCachedDsKnobs(champ, mode, items, knobs, level);

  // Build the knob strip once per champion (data-ovds-champ guard); re-wiring
  // every tick would stack input handlers. It mounts into #ovds-knobwrap so the
  // settings strip above it survives a champion change.
  if (body.getAttribute("data-ovds-champ") !== champ && knobwrap) {
    const resolved = payload && payload.knobs ? payload.knobs : null;
    knobwrap.innerHTML = _stripHtml(knobs, resolved);
    body.setAttribute("data-ovds-champ", champ);
    _wireInputs(body, champ);
    _ovdsSig = null;  // force first rows paint for this champion
  }

  const sig = _signature(payload, knobs);
  if (_ovdsSig === sig) return;
  _ovdsSig = sig;

  const rowsEl = body.querySelector("#ovds-rows");
  if (rowsEl) {
    if (payload && payload.ok) {
      rowsEl.innerHTML = _rowsHtml(payload);
    } else if (payload) {
      // Landed but unrankable (ok=false, e.g. reason=no_rows). Friendly
      // copy only - raw error strings never reach a coach panel.
      rowsEl.innerHTML = `<div class="ovds-empty">no items rank under this fight model</div>`;
    } else {
      rowsEl.innerHTML = `<div class="ovds-empty">resolving fight model...</div>`;
    }
  }
  if (payload && payload.knobs) _refreshPlaceholders(body, payload.knobs, knobs);
}

// Reset helper for tests (knob overrides + slug memo + sig + timer).
export function _resetOverlayDsControls() {
  for (const k of Object.keys(_OVDS_KNOBS)) delete _OVDS_KNOBS[k];
  _OVDS_SLUGS.ready = false;
  _OVDS_SLUGS.version = "";
  _OVDS_SLUGS.map = Object.create(null);
  _ovdsSig = null;
  if (_ovdsDebounceTimer) clearTimeout(_ovdsDebounceTimer);
  _ovdsDebounceTimer = null;
  _OVDS_LAST.p = null;
  _OVDS_LAST.ctx = null;
}

export const __test = {
  _modeForCtx,
  _canonicalChamp,
  _signature,
  _norm,
  _numOrNull,
  _clampLevel,
  _goldLabel,
  _itemIds,
};
