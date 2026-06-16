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
//     overall
//   }
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

const _GPI_CACHE = Object.create(null);     // mode -> response JSON
const _GPI_INFLIGHT = Object.create(null);
const _GPI_TS = Object.create(null);
const _GPI_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _GPI_TTL_MS = 5 * 60 * 1000;

const _DEFAULT_MOUNT = "player-gpi-panel";
const _MODES = ["sr", "aram"];

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
export function fetchPlayerProfile(mode, onLand) {
  const key = _mode(mode);
  const fresh = _GPI_CACHE[key] && _GPI_TS[key]
                && (Date.now() - _GPI_TS[key]) < _GPI_TTL_MS;
  if (fresh || _GPI_INFLIGHT[key]) return;
  _GPI_INFLIGHT[key] = true;
  const qs = new URLSearchParams({ mode: key });
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

export function getCachedPlayerProfile(mode) {
  return _GPI_CACHE[_mode(mode)] || null;
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
  return _mode(payload.mode) + "|" + _fmtScore(payload.overall) + "|" + body;
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

// Render the panel into ``blockEl``. ``payload`` is the backend response (may
// be null on cold-load -> hidden). ``activeMode`` drives the toggle highlight
// and is read back by the click handler the host wires via onModeChange.
export function renderPlayerGpi(blockEl, payload, activeMode) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_gpi_default";
  const mode = _mode(activeMode || (payload && payload.mode));
  const sig = mode + "::" + _signature(payload);
  if (_GPI_SIG[sigKey] === sig) return;
  _GPI_SIG[sigKey] = sig;

  // Cold load (no payload yet) keeps the panel hidden so it does not flash an
  // empty card before the first fetch lands.
  if (!payload) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const head = '<div class="gpi-head">'
    + '<span class="gpi-head-title">GPI radar</span>'
    + _toggleSvgless(mode)
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
    + _dataSvg(axes, overallTier)
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
    + tipBlock;
}

// Standalone entry point. Fetches the profile for ``mode`` and renders into the
// default mount (or ``blockId``). The host that owns the mode toggle wires a
// click handler onto [data-gpi-mode] and re-invokes this with the new mode.
export function showPlayerGpi(mode, blockId) {
  const block = document.getElementById(blockId || _DEFAULT_MOUNT);
  if (!block) return;
  const m = _mode(mode);
  fetchPlayerProfile(m, () => renderPlayerGpi(
    block, getCachedPlayerProfile(m), m));
  renderPlayerGpi(block, getCachedPlayerProfile(m), m);
  _wireModeToggle(block);
}

// Delegate-style click wiring for the mode toggle. Idempotent: a single
// listener on the block re-reads the clicked [data-gpi-mode] and re-shows. The
// listener is stamped so repeated showPlayerGpi calls do not stack handlers.
function _wireModeToggle(block) {
  if (!block || block.dataset.gpiWired === "1") return;
  block.dataset.gpiWired = "1";
  block.addEventListener("click", (ev) => {
    const btn = ev.target && ev.target.closest
      ? ev.target.closest("[data-gpi-mode]") : null;
    if (!btn) return;
    const next = _mode(btn.getAttribute("data-gpi-mode"));
    showPlayerGpi(next, block.id || _DEFAULT_MOUNT);
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
  _clampScore,
  _vertex,
  _scoreTier,
  _signature,
  _fmtScore,
  _esc,
  _GPI_TTL_MS,
  _R,
  _CX,
  _CY,
};
