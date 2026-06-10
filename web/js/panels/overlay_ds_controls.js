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
    + `<span class="ovds-item">${String(r.name || r.item_id || "")}</span>`
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
  // Gate 2: display name -> canonical DDragon slug. No champion yet, or
  // CHAMPS index still loading -> stay hidden; resolves on a later tick.
  const champ = _canonicalChamp(p.champion || "");
  if (!champ) {
    pane.hidden = true;
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

  const body = document.getElementById("ovds-body");
  if (!body) return;

  // Build the knob strip once per champion (data-ovds-champ guard);
  // re-wiring every tick would stack input handlers.
  if (body.getAttribute("data-ovds-champ") !== champ) {
    const resolved = payload && payload.knobs ? payload.knobs : null;
    body.innerHTML = _stripHtml(knobs, resolved);
    body.setAttribute("data-ovds-champ", champ);
    _wireInputs(body, champ);
    _ovdsSig = null;  // force first rows paint for this champion
  }
  pane.hidden = false;

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
