// Player-GPI radar panel. Renders the operator's cross-game "GPI" profile as an
// eight-spoke radar (octagon) - one axis per play dimension (aggression /
// farming / vision / objectives / survival / tempo / versatility /
// consistency) scored 0..100 against the operator's own rolling baseline. A
// one-glance read on which dimensions the operator over- vs under-indexes,
// independent of any single game. Pure presentation over an existing backend
// aggregate; no compute lives here.
//
// Backend wire:
//   GET /api/player-profile?mode=<sr|aram>
//   Response: {
//     ok, mode, champion, n_games, window, min_games,
//     confidence: "high" | "low" | "insufficient",
//     axes: [{key, label, unit, scoring, higher_is_better,
//             score, recent_value, baseline_p50, sample_n}, ... 8 ...],
//     overall,
//     reference: {kind, label, n, min_games,
//                 axes: [{key, score}, ... 8 ...]} | null
//   }
//   reference is the target-profile polygon - the same 8 axes scored over the
//   operator's OWN winning games - drawn behind the recent-form polygon. Null
//   (too few wins) renders the shipped radar unchanged.
//   confidence == "insufficient" -> axes == [] and overall == null: the panel
//   renders an empty-state ("not enough games yet - N/min_games") rather than a
//   degenerate zero-area radar.
//   Route 503 / not-ok / network error -> a muted "profile unavailable" line
//   (never a raw error string - repo Error-Handling rule).
//
// Discipline mirrors ds_profile.js: pure ESM, ASCII only (no unicode glyphs /
// em-dashes / smart quotes), per-key cache + TTL, inflight guard, sig-dedup
// gate so an unchanged payload skips the innerHTML+SVG rebuild, and no DOM
// writes outside renderPlayerGpi(). The radar is SVG so the polygon scales
// crisply at the 1920x1080 baseline with no raster blur.

import { CHAMPS } from '../lib/items_index.js';

const _GPI_CACHE = Object.create(null);     // mode|champ -> response JSON
const _GPI_INFLIGHT = Object.create(null);
const _GPI_TS = Object.create(null);
const _GPI_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _GPI_TTL_MS = 5 * 60 * 1000;

const _DEFAULT_MOUNT = "player-gpi-panel";
const _MODES = ["sr", "aram"];

// Cache key: one profile per (mode, champion-filter). An empty champion is the
// all-games profile; keeping both in the key lets the drilldown selector switch
// champions without clobbering the all-games view. _mode() is hoisted below.
function _key(mode, champion) {
  const c = (champion == null || champion === "") ? "" : String(champion);
  return _mode(mode) + "|" + c;
}

// SVG geometry. The viewBox is wider than it is tall so the left/right axis
// labels (the longest words - CONSISTENCY / VERSATILITY / OBJECTIVES) have
// horizontal run-off room and do not clip at the box edge. The radar is
// centred in the box; the outer radius leaves a vertical+horizontal margin for
// the labels + score chips drawn just outside each vertex. Eight grid rings at
// 25/50/75/100 give a read-off scale.
const _VB_W = 280;
const _VB_H = 210;
const _CX = _VB_W / 2;         // 140
const _CY = _VB_H / 2;         // 105
const _R = 66;                 // outer radius (score 100) inside the viewBox
const _RINGS = [25, 50, 75, 100];

function _mode(mode) {
  const m = String(mode || "sr").toLowerCase();
  return _MODES.indexOf(m) >= 0 ? m : "sr";
}

// Clamp a score into 0..100 so a stray out-of-range value never pushes a
// vertex outside the grid. Non-numeric collapses to 0 (fail-soft).
function _clampScore(score) {
  const n = +score;
  if (!isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return n;
}

// Vertex on the octagon for axis index i of n, at radius-fraction frac (0..1).
// Angle starts at -90deg (straight up) and walks clockwise so axis 0 sits at
// twelve-o-clock - the conventional radar read.
function _vertex(i, n, frac) {
  const ang = (-Math.PI / 2) + (2 * Math.PI * i / n);
  const r = _R * frac;
  return [
    _round(_CX + r * Math.cos(ang)),
    _round(_CY + r * Math.sin(ang)),
  ];
}

function _round(x) {
  return Math.round(x * 100) / 100;
}

// Fetch + memoize for one mode. ``onLand`` re-render callback fires once the
// payload lands. A 503 / network error caches a synthetic not-ok envelope so
// the panel renders the muted unavailable line instead of spinning forever.
export function fetchPlayerProfile(mode, champion, onLand) {
  const key = _key(mode, champion);
  const fresh = _GPI_CACHE[key] && _GPI_TS[key]
                && (Date.now() - _GPI_TS[key]) < _GPI_TTL_MS;
  if (fresh || _GPI_INFLIGHT[key]) return;
  _GPI_INFLIGHT[key] = true;
  const params = { mode: _mode(mode) };
  if (champion != null && champion !== "") params.champion = String(champion);
  const qs = new URLSearchParams(params);
  fetch("/api/player-profile?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : { ok: false, reason: "unavailable" }))
    .then((data) => {
      _GPI_INFLIGHT[key] = false;
      _GPI_CACHE[key] = data || { ok: false, reason: "unavailable" };
      _GPI_TS[key] = Date.now();
      if (typeof onLand === "function") onLand();
    })
    .catch(() => {
      _GPI_INFLIGHT[key] = false;
      // Cache a not-ok envelope so render shows the muted line, not a spinner.
      _GPI_CACHE[key] = { ok: false, reason: "unavailable" };
      _GPI_TS[key] = Date.now();
      if (typeof onLand === "function") onLand();
    });
}

export function getCachedPlayerProfile(mode, champion) {
  return _GPI_CACHE[_key(mode, champion)] || null;
}

export function getPlayerProfileCacheCount() {
  return Object.keys(_GPI_CACHE).length;
}

// HTML-escape the small free-form strings the backend passes through (axis
// labels, mode). Defensive - mirrors the sibling panels before innerHTML.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Round a score for display (one decimal, trailing-zero trimmed).
function _fmtScore(score) {
  const n = _clampScore(score);
  return String(Math.round(n * 10) / 10);
}

// Pick a tier class from a 0..100 score so the polygon + overall chip tint
// reads strong / mid / weak at a glance. Thresholds match the operator's
// at-a-glance read: >=60 strong, >=40 mid, else weak.
function _scoreTier(score) {
  const n = _clampScore(score);
  if (n >= 60) return "gpi-tier-high";
  if (n >= 40) return "gpi-tier-med";
  return "gpi-tier-low";
}

// Signature for the sig-dedup gate. Anything that changes the rendered radar
// (mode, confidence, overall, or any axis key/score) changes the sig.
function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? "_" + payload.reason : "_empty";
  }
  if (payload.confidence === "insufficient") {
    return "_insufficient|" + (payload.n_games | 0) + "/" + (payload.min_games | 0);
  }
  const axes = Array.isArray(payload.axes) ? payload.axes : [];
  const body = axes
    .map((a) => (a.key || "") + ":" + _fmtScore(a.score))
    .join(",");
  // this_match participates in the sig. match_id inclusion is load-bearing:
  // a NEW game can post the same axis scores, and only the id flip forces the
  // repaint that clears a stale overlay (cache-staleness guard).
  const tm = payload.this_match;
  const tmSig = (tm && Array.isArray(tm.axes))
    ? (tm.match_id || "") + ":" + tm.axes
        .map((a) => a.key + "=" + (a.score == null ? "-" : a.score))
        .join(",")
    : "none";
  // The reference polygon participates too: it moves only when the operator's
  // winning-games profile moves, which is exactly a repaint-worthy change.
  const ref = payload.reference;
  const refSig = (ref && Array.isArray(ref.axes))
    ? (ref.n | 0) + ":" + ref.axes
        .map((a) => a.key + "=" + (a.score == null ? "-" : a.score))
        .join(",")
    : "none";
  return _mode(payload.mode) + "|" + _fmtScore(payload.overall) + "|" + body
       + "|tm:" + tmSig + "|ref:" + refSig;
}

// Build the grid rings (concentric octagons) + radial spokes as one SVG string.
function _gridSvg(n) {
  let out = "";
  for (const pct of _RINGS) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const [x, y] = _vertex(i, n, pct / 100);
      pts.push(x + "," + y);
    }
    out += '<polygon class="gpi-ring" points="' + pts.join(" ") + '" />';
  }
  for (let i = 0; i < n; i++) {
    const [x, y] = _vertex(i, n, 1);
    out += '<line class="gpi-spoke" x1="' + _CX + '" y1="' + _CY
         + '" x2="' + x + '" y2="' + y + '" />';
  }
  return out;
}

// Build the filled data polygon + per-vertex dots from the axis scores.
function _dataSvg(axes, tierCls) {
  const n = axes.length;
  const pts = [];
  let dots = "";
  for (let i = 0; i < n; i++) {
    const frac = _clampScore(axes[i] && axes[i].score) / 100;
    const [x, y] = _vertex(i, n, frac);
    pts.push(x + "," + y);
    dots += '<circle class="gpi-dot" cx="' + x + '" cy="' + y + '" r="1.6" />';
  }
  return '<polygon class="gpi-area ' + tierCls + '" points="'
       + pts.join(" ") + '" />' + dots;
}

// Overlay dots for the operator's LAST game on the same eight axes. Matched
// by axis KEY (not position) so a backend axis reorder cannot mis-plot a dot;
// axes with a null this-match score (versatility / consistency by contract)
// draw nothing. Returns "" when the payload carries no this_match block so
// the shipped radar renders byte-identical without it.
function _matchDotsSvg(axes, thisMatch) {
  if (!thisMatch || !Array.isArray(thisMatch.axes)) return "";
  const byKey = Object.create(null);
  for (const a of thisMatch.axes) {
    if (a && a.key != null) byKey[String(a.key)] = a;
  }
  const n = axes.length;
  let out = "";
  for (let i = 0; i < n; i++) {
    const key = axes[i] && axes[i].key;
    const entry = key == null ? null : byKey[String(key)];
    if (!entry || entry.score == null) continue;
    const [x, y] = _vertex(i, n, _clampScore(entry.score) / 100);
    out += '<circle class="gpi-match-dot" cx="' + x + '" cy="' + y
         + '" r="2.4" />';
  }
  return out;
}

// Target-profile reference polygon: the same eight axes scored over the
// operator's own WINNING games, drawn BEHIND the recent-form polygon so the
// gap between the two reads as "what my winning games look like vs now".
// Matched by axis KEY (not position) so a backend axis reorder cannot skew the
// shape. All-or-nothing: unless every axis resolves to a finite reference
// score the polygon is skipped entirely - a partial ring would read as a real
// shape while silently dropping vertices. Returns "" without a reference block
// so the shipped radar renders byte-identical without it.
function _refPolySvg(axes, reference) {
  if (!reference || !Array.isArray(reference.axes)) return "";
  const byKey = Object.create(null);
  for (const a of reference.axes) {
    if (a && a.key != null) byKey[String(a.key)] = a;
  }
  const n = axes.length;
  if (n < 3) return "";
  const pts = [];
  for (let i = 0; i < n; i++) {
    const key = axes[i] && axes[i].key;
    const entry = key == null ? null : byKey[String(key)];
    if (!entry || entry.score == null || !isFinite(+entry.score)) return "";
    const [x, y] = _vertex(i, n, _clampScore(entry.score) / 100);
    pts.push(x + "," + y);
  }
  return '<polygon class="gpi-ref-area" points="' + pts.join(" ") + '" />';
}

// One-line legend for the reference polygon, rendered only when the polygon
// actually draws. The count is the number of winning games behind the shape so
// the operator can weigh it (a 5-win reference is thinner than a 20-win one).
function _refLegend(reference) {
  if (!reference || !Array.isArray(reference.axes) || !reference.axes.length) {
    return "";
  }
  const label = reference.label ? String(reference.label) : "winning games";
  const n = reference.n | 0;
  const text = "reference - " + label + (n > 0 ? " (" + n + ")" : "");
  return '<div class="gpi-ref-legend">'
    + '<span class="gpi-ref-swatch"></span>'
    + '<span class="gpi-ref-text">' + _esc(text) + "</span>"
    + "</div>";
}

// Build the axis labels + per-vertex score chips placed just outside the outer
// ring. Label anchoring flips by horizontal position so text does not overrun
// the viewBox edge. These are SVG <text> nodes so they ride the same scale.
function _labelsSvg(axes) {
  const n = axes.length;
  let out = "";
  for (let i = 0; i < n; i++) {
    const ax = axes[i] || {};
    const [x, y] = _vertex(i, n, 1.18);
    const dx = x - _CX;
    let anchor = "middle";
    if (dx > 6) anchor = "start";
    else if (dx < -6) anchor = "end";
    const label = _esc(ax.label || ax.key || "");
    const score = _esc(_fmtScore(ax.score));
    out += '<text class="gpi-axis-label" x="' + x + '" y="' + y
         + '" text-anchor="' + anchor + '">' + label + "</text>";
    out += '<text class="gpi-axis-score" x="' + x + '" y="' + (y + 7)
         + '" text-anchor="' + anchor + '">' + score + "</text>";
  }
  return out;
}

// Build the mode toggle. Two buttons (SR / ARAM); the active mode is pressed.
// Each button is --hit-min tall (CSS) so the click target clears the floor.
function _toggleSvgless(activeMode) {
  const m = _mode(activeMode);
  let out = '<div class="gpi-modes" role="group" aria-label="profile mode">';
  for (const mode of _MODES) {
    const on = mode === m ? " gpi-mode-on" : "";
    out += '<button type="button" class="gpi-mode' + on
         + '" data-gpi-mode="' + mode + '"'
         + (mode === m ? ' aria-pressed="true"' : ' aria-pressed="false"')
         + ">" + mode.toUpperCase() + "</button>";
  }
  out += "</div>";
  return out;
}

// Resolve a champion id to its display name via the shared CHAMPS byId index
// (the same resolver champ_select.js uses); fall back to "cid:<n>" before the
// name table loads or for an unknown id.
function _champName(cid) {
  const nm = CHAMPS && CHAMPS.byId ? CHAMPS.byId[String(cid)] : "";
  return nm || ("cid:" + cid);
}

// Coarse relative age for the match legend ("3h ago"). Coarse on purpose -
// the read is "how recent was that game", not a precise timestamp.
function _relAge(ts) {
  const d = Date.now() - ts;
  if (!isFinite(d) || d < 60 * 1000) return "just now";
  const mins = Math.floor(d / 60000);
  if (mins < 60) return mins + "m ago";
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours + "h ago";
  return Math.floor(hours / 24) + "d ago";
}

// One-line legend for the this-match overlay, rendered under the caption ONLY
// when at least one axis actually drew a dot (an all-null this_match would
// otherwise advertise an invisible overlay). The age suffix requires a real
// epoch-ms timestamp (> 1e12) - seconds / null / garbage omit it fail-soft.
function _matchLegend(thisMatch) {
  if (!thisMatch || !Array.isArray(thisMatch.axes)) return "";
  const any = thisMatch.axes.some((a) => a && a.score != null);
  if (!any) return "";
  let text = "last game - " + _champName(thisMatch.champion_id);
  const ts = thisMatch.game_creation_ts;
  if (typeof ts === "number" && ts > 1e12) {
    text += " - " + _relAge(ts);
  }
  return '<div class="gpi-match-legend">'
    + '<span class="gpi-match-swatch"></span>'
    + '<span class="gpi-match-text">' + _esc(text) + "</span>"
    + "</div>";
}

// Champion drilldown <select>: an "All champions" default plus one option per
// played champ (name + game count), the active champion pre-selected. Populated
// from the payload's mode-wide champions[] pool so every option persists after
// a drilldown. activeChampion "" == the all-games view.
function _champSelect(champions, activeChampion) {
  const list = Array.isArray(champions) ? champions : [];
  const active = (activeChampion == null ? "" : String(activeChampion));
  let out = '<select class="gpi-champ-select" data-gpi-champ'
          + ' aria-label="filter profile by champion">';
  out += '<option value=""' + (active === "" ? " selected" : "")
       + ">All champions</option>";
  for (const c of list) {
    const cid = String(c && c.champion_id);
    const n = (c && c.n_games) | 0;
    out += '<option value="' + _esc(cid) + '"'
         + (cid === active ? " selected" : "") + ">"
         + _esc(_champName(cid)) + " (" + n + ")</option>";
  }
  out += "</select>";
  return out;
}

// Render the panel into ``blockEl``. ``payload`` is the backend response (may
// be null on cold-load -> hidden). ``activeMode`` drives the toggle highlight
// and is read back by the click handler the host wires via onModeChange.
export function renderPlayerGpi(blockEl, payload, activeMode, activeChampion) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_gpi_default";
  const mode = _mode(activeMode || (payload && payload.mode));
  const champ = (activeChampion == null ? "" : String(activeChampion));
  const sig = mode + "::" + champ + "::" + _signature(payload);
  if (_GPI_SIG[sigKey] === sig) return;
  _GPI_SIG[sigKey] = sig;

  // Cold load (no payload yet) keeps the panel hidden so it does not flash an
  // empty card before the first fetch lands.
  if (!payload) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const champs = (payload && Array.isArray(payload.champions))
    ? payload.champions : [];
  const head = '<div class="gpi-head">'
    + '<span class="gpi-head-title">GPI radar</span>'
    + '<div class="gpi-controls">'
    + _toggleSvgless(mode)
    + (champs.length ? _champSelect(champs, champ) : "")
    + "</div>"
    + "</div>";

  // Not-ok (503 / network) -> muted unavailable line, never a raw error.
  if (!payload.ok) {
    blockEl.innerHTML = head
      + '<div class="gpi-msg gpi-msg-dim">profile unavailable</div>';
    return;
  }

  // Insufficient sample -> empty-state with the games/min_games read.
  if (payload.confidence === "insufficient"
      || !Array.isArray(payload.axes) || payload.axes.length === 0) {
    const have = payload.n_games | 0;
    const need = payload.min_games | 0;
    blockEl.innerHTML = head
      + '<div class="gpi-msg">not enough games yet - '
      + have + "/" + need + "</div>";
    return;
  }

  const axes = payload.axes;
  const n = axes.length;
  const overall = _clampScore(payload.overall);
  const overallTier = _scoreTier(overall);

  const svg = '<svg class="gpi-radar" viewBox="0 0 ' + _VB_W + " " + _VB_H
    + '" preserveAspectRatio="xMidYMid meet" role="img"'
    + ' aria-label="eight-axis player profile radar">'
    + _gridSvg(n)
    + _refPolySvg(axes, payload.reference)
    + _dataSvg(axes, overallTier)
    + _matchDotsSvg(axes, payload.this_match)
    + _labelsSvg(axes)
    + "</svg>";

  const conf = _esc(String(payload.confidence || ""));
  const caption = '<div class="gpi-caption">'
    + '<span class="gpi-cap-mode">' + _esc(_mode(payload.mode).toUpperCase())
    + "</span>"
    + '<span class="gpi-cap-sep">-</span>'
    + '<span class="gpi-cap-games">' + (payload.n_games | 0) + " games</span>"
    + '<span class="gpi-cap-sep">-</span>'
    + '<span class="gpi-cap-window">last ' + (payload.window | 0) + "</span>"
    + '<span class="gpi-cap-sep">-</span>'
    + '<span class="gpi-cap-conf gpi-conf-' + conf + '">' + conf + "</span>"
    + "</div>";

  const overallBlock = '<div class="gpi-overall ' + overallTier + '">'
    + '<span class="gpi-overall-num">' + _fmtScore(overall) + "</span>"
    + '<span class="gpi-overall-lbl">overall</span>'
    + "</div>";

  // Weakest-axis improvement tip (static, no LLM). Rendered only when the
  // backend names a weakest axis; the axis label is surfaced as the lead chip.
  let tipBlock = "";
  if (payload.tip && payload.weakest_axis) {
    const wax = axes.find((a) => a.key === payload.weakest_axis);
    const waxLabel = wax ? wax.label : payload.weakest_axis;
    tipBlock = '<div class="gpi-tip">'
      + '<span class="gpi-tip-axis">' + _esc(String(waxLabel)) + "</span>"
      + '<span class="gpi-tip-text">' + _esc(String(payload.tip)) + "</span>"
      + "</div>";
  }

  blockEl.innerHTML = head
    + '<div class="gpi-body">'
    + '<div class="gpi-radar-wrap">' + svg + "</div>"
    + overallBlock
    + "</div>"
    + caption
    + _refLegend(payload.reference)
    + _matchLegend(payload.this_match)
    + tipBlock;
}

// Standalone entry point. Fetches the profile for ``mode`` and renders into the
// default mount (or ``blockId``). The host that owns the mode toggle wires a
// click handler onto [data-gpi-mode] and re-invokes this with the new mode.
export function showPlayerGpi(mode, blockId, champion) {
  const block = document.getElementById(blockId || _DEFAULT_MOUNT);
  if (!block) return;
  const m = _mode(mode);
  const c = (champion == null ? "" : String(champion));
  fetchPlayerProfile(m, c, () => renderPlayerGpi(
    block, getCachedPlayerProfile(m, c), m, c));
  renderPlayerGpi(block, getCachedPlayerProfile(m, c), m, c);
  _wireControls(block);
}

// Read the currently-active mode back from the rendered toggle so the champion
// change handler (which has no mode in scope) re-shows in the right mode.
function _activeMode(block) {
  const on = block && block.querySelector
    ? block.querySelector(".gpi-mode.gpi-mode-on[data-gpi-mode]") : null;
  return _mode(on ? on.getAttribute("data-gpi-mode") : "sr");
}

// Delegate-style wiring for the head controls. Idempotent: one click listener
// (mode toggle) + one change listener (champion drilldown) on the block, stamped
// so repeated showPlayerGpi calls do not stack handlers. Switching mode resets
// the champion filter (the champ pool is per-mode).
function _wireControls(block) {
  if (!block || block.dataset.gpiWired === "1") return;
  block.dataset.gpiWired = "1";
  block.addEventListener("click", (ev) => {
    const btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-gpi-mode]") : null;
    if (!btn) return;
    const next = _mode(btn.getAttribute("data-gpi-mode"));
    showPlayerGpi(next, block.id || _DEFAULT_MOUNT, "");
  });
  block.addEventListener("change", (ev) => {
    const sel = ev.target && ev.target.closest
      ? ev.target.closest("[data-gpi-champ]") : null;
    if (!sel) return;
    showPlayerGpi(_activeMode(block), block.id || _DEFAULT_MOUNT,
                  sel.value || "");
  });
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetPlayerGpi() {
  for (const k of Object.keys(_GPI_CACHE))    delete _GPI_CACHE[k];
  for (const k of Object.keys(_GPI_INFLIGHT)) delete _GPI_INFLIGHT[k];
  for (const k of Object.keys(_GPI_TS))       delete _GPI_TS[k];
  for (const k of Object.keys(_GPI_SIG))      delete _GPI_SIG[k];
}

export const __test = {
  _mode,
  _key,
  _clampScore,
  _vertex,
  _scoreTier,
  _signature,
  _fmtScore,
  _esc,
  _champName,
  _champSelect,
  _matchDotsSvg,
  _matchLegend,
  _refPolySvg,
  _refLegend,
  _GPI_TTL_MS,
  _R,
  _CX,
  _CY,
};
