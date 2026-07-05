// Presentational player-snapshot card (spec docs/superpowers/specs/
// 2026-07-04-player-snapshot-card-design.md). Pure render, no fetch,
// idempotent. Host-agnostic: it takes a model, it does not know its surface
// (v1 host is the rc-shell companion; the model contract stays portable).
//
// Model contract (assembled by dashboard/routes_player_snapshot.py and, in a
// later task, a PGR client-side adapter over /api/last-match +
// /api/post-game-rubric):
//   {
//     header: { name, rank_tier, rank_lp, level,
//               streak: {kind:"win"|"loss", n}|null,
//               champion_id|null, result:"win"|"loss"|null },
//     dial: { value: 0..100, band: "good"|"ok"|"poor", label },
//     minis: [ {key, value, provenance} ],           // KDA, Win-Rate, K-P
//     bars: [ {key, label, score: 0..100, provenance} ],  // 4 composites
//     tags: [ {label, tone: "strong"|"neutral"|"weak"} ], // exactly 3
//     profile_ref: { mode, window|match_id },
//     confidence: "high"|"low"|"insufficient",
//     sample_n,
//     empty: bool
//   }
//
// Discipline mirrors player_gpi.js / duration_winrate.js: ESM, ASCII only, no
// hardcoded hex (tokens.css custom properties only), no DOM writes outside
// renderPlayerSnapshot(), idempotent via a stashed JSON signature.

const _BAND_VAR = { good: "--signal-good", ok: "--signal-warn", poor: "--signal-bad" };
const _TONE_VAR = { strong: "--signal-good", neutral: "--signal-warn", weak: "--signal-bad" };

// SVG dial geometry - a single arc gauge (270deg sweep, gap at the bottom) so
// the 0..100 value reads as a fill fraction. viewBox stays small + square;
// stroke-width is an SVG user-unit (not a CSS px, so the --fs floor does not
// apply - the same documented exception as player_gpi.js's radar strokes).
const _DIAL_VB = 120;
const _DIAL_CX = _DIAL_VB / 2;
const _DIAL_CY = _DIAL_VB / 2;
const _DIAL_R = 48;
const _DIAL_SWEEP = 270;         // degrees of the visible arc
const _DIAL_START = 135;         // degrees; 0 = 3 o'clock, clockwise

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _clamp01to100(v) {
  const n = +v;
  if (!isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return n;
}

function _polar(cx, cy, r, deg) {
  const rad = (deg - 90) * Math.PI / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

// Build one SVG <path> arc from startDeg to endDeg (both measured from the
// dial's own _DIAL_START reference, clockwise). Used for both the dim track
// (full sweep) and the filled value arc (fraction of the sweep).
function _arcPath(cx, cy, r, startDeg, endDeg) {
  const s = _DIAL_START + startDeg;
  const e = _DIAL_START + endDeg;
  const [x1, y1] = _polar(cx, cy, r, s);
  const [x2, y2] = _polar(cx, cy, r, e);
  const large = (endDeg - startDeg) > 180 ? 1 : 0;
  return "M " + x1.toFixed(2) + " " + y1.toFixed(2)
       + " A " + r + " " + r + " 0 " + large + " 1 "
       + x2.toFixed(2) + " " + y2.toFixed(2);
}

function _bandVar(band) {
  return _BAND_VAR[band] || _BAND_VAR.poor;
}

function _toneVar(tone) {
  return _TONE_VAR[tone] || _TONE_VAR.neutral;
}

function _dialHtml(dial) {
  const d = dial || {};
  const value = _clamp01to100(d.value);
  const band = (d.band === "good" || d.band === "ok" || d.band === "poor") ? d.band : "poor";
  const colorVar = "var(" + _bandVar(band) + ")";
  const frac = value / 100;
  const track = _arcPath(_DIAL_CX, _DIAL_CY, _DIAL_R, 0, _DIAL_SWEEP);
  const fill = frac > 0
    ? _arcPath(_DIAL_CX, _DIAL_CY, _DIAL_R, 0, _DIAL_SWEEP * frac)
    : "";
  const label = _esc(d.label || "");
  return (
    '<div class="ps-dial" data-band="' + band + '">' +
      '<svg class="ps-dial-svg" viewBox="0 0 ' + _DIAL_VB + " " + _DIAL_VB + '" ' +
        'preserveAspectRatio="xMidYMid meet" role="img" aria-label="rating dial">' +
        '<path class="ps-dial-track" d="' + track + '"></path>' +
        (fill ? '<path class="ps-dial-fill" d="' + fill + '" style="stroke:' + colorVar + '"></path>' : '') +
      "</svg>" +
      '<div class="ps-dial-center">' +
        '<span class="ps-dial-value" style="color:' + colorVar + '">' + Math.round(value) + "</span>" +
        '<span class="ps-dial-label">' + label + "</span>" +
      "</div>" +
    "</div>"
  );
}

function _miniHtml(mini) {
  const m = mini || {};
  const key = _esc(m.key || "");
  const value = _esc(m.value == null ? "-" : m.value);
  const prov = m.provenance === "inferred" ? " ps-inferred" : "";
  return (
    '<div class="ps-mini' + prov + '" data-key="' + key + '">' +
      '<span class="ps-mini-value">' + value + "</span>" +
      '<span class="ps-mini-key">' + key.toUpperCase() + "</span>" +
    "</div>"
  );
}

function _minisHtml(minis) {
  const list = Array.isArray(minis) ? minis : [];
  return '<div class="ps-minis">' + list.map(_miniHtml).join("") + "</div>";
}

function _barHtml(bar) {
  const b = bar || {};
  const key = _esc(b.key || "");
  const label = _esc(b.label || key.toUpperCase());
  const score = _clamp01to100(b.score);
  const prov = b.provenance === "inferred" ? " ps-inferred" : "";
  return (
    '<div class="ps-bar' + prov + '" data-key="' + key + '">' +
      '<span class="ps-bar-label">' + label + "</span>" +
      '<div class="ps-bar-track">' +
        '<div class="ps-bar-fill" style="width:' + score + '%"></div>' +
      "</div>" +
      '<span class="ps-bar-value">' + Math.round(score) + "</span>" +
    "</div>"
  );
}

function _barsHtml(bars) {
  const list = Array.isArray(bars) ? bars : [];
  return '<div class="ps-bars">' + list.map(_barHtml).join("") + "</div>";
}

function _tagHtml(tag) {
  const t = tag || {};
  const tone = (t.tone === "strong" || t.tone === "neutral" || t.tone === "weak") ? t.tone : "neutral";
  const colorVar = "var(" + _toneVar(tone) + ")";
  const label = _esc(t.label || "");
  return (
    '<span class="ps-tag" data-tone="' + tone + '" style="color:' + colorVar +
      ";border-color:" + colorVar + '">' + label + "</span>"
  );
}

function _tagsHtml(tags) {
  const list = Array.isArray(tags) ? tags : [];
  return '<div class="ps-tags">' + list.map(_tagHtml).join("") + "</div>";
}

// Streak chip - "3W" / "2L" in the header, or nothing when there is no streak
// yet (a brand-new/empty window). Mirrors the win/loss signal color.
function _streakHtml(streak) {
  if (!streak || !streak.kind || !streak.n) return "";
  const win = streak.kind === "win";
  const colorVar = "var(" + (win ? _BAND_VAR.good : _BAND_VAR.poor) + ")";
  const suffix = win ? "W" : "L";
  return '<span class="ps-streak" style="color:' + colorVar + '">'
       + (streak.n | 0) + suffix + "</span>";
}

function _resultHtml(result) {
  if (result !== "win" && result !== "loss") return "";
  const win = result === "win";
  const colorVar = "var(" + (win ? _BAND_VAR.good : _BAND_VAR.poor) + ")";
  return '<span class="ps-result" style="color:' + colorVar + '">'
       + (win ? "VICTORY" : "DEFEAT") + "</span>";
}

function _headerHtml(header) {
  const h = header || {};
  const name = _esc(h.name || "");
  const rankTier = _esc(h.rank_tier || "");
  const rankLp = (h.rank_lp == null) ? "" : (" " + (h.rank_lp | 0) + " LP");
  const level = (h.level == null) ? "" : ('<span class="ps-level">Lv ' + (h.level | 0) + "</span>");
  const rankText = rankTier ? (rankTier + rankLp) : "";
  return (
    '<div class="ps-header">' +
      '<div class="ps-header-id">' +
        (name ? ('<span class="ps-name">' + name + "</span>") : "") +
        (rankText ? ('<span class="ps-rank">' + _esc(rankText) + "</span>") : "") +
        level +
      "</div>" +
      '<div class="ps-header-flags">' +
        _resultHtml(h.result) +
        _streakHtml(h.streak) +
      "</div>" +
    "</div>"
  );
}

function _viewProfileHtml(profileRef) {
  const ref = profileRef || {};
  const mode = _esc(ref.mode || "");
  const win = _esc(ref.window || "");
  const matchId = _esc(ref.match_id == null ? "" : ref.match_id);
  return (
    '<button type="button" class="ps-viewprofile" ' +
      'data-mode="' + mode + '" data-window="' + win + '" data-match-id="' + matchId + '">' +
      "View Profile" +
    "</button>"
  );
}

function _emptyHtml(m) {
  // Reserved-height card + "-" sentinel; no reflow (feedback_no_reflow_on_data_absence).
  const dial = (m && m.dial) || {};
  const msg = dial.label ? dial.label : "No data";
  return '<div class="ps-empty">'
       + '<span class="ps-sentinel">-</span>'
       + '<span class="ps-empty-msg">' + _esc(msg) + "</span></div>";
}

/**
 * Render the player-snapshot card into ``el`` from the normalized ``model``.
 * Pure - no fetch, no timers. Idempotent: an unchanged model (by JSON
 * signature) early-returns without touching the DOM (mirrors
 * duration_winrate.js's stashed-sig pattern).
 */
export function renderPlayerSnapshot(el, model) {
  if (!el || !model) return;
  const sig = JSON.stringify(model);
  if (el.dataset.sig === sig) return;      // idempotent
  el.dataset.sig = sig;
  el.classList.add("player-snapshot");
  el.setAttribute("data-testid", "player-snapshot");
  if (model.empty) {
    el.classList.add("ps-is-empty");
    el.innerHTML = _emptyHtml(model);
    return;
  }
  el.classList.remove("ps-is-empty");
  el.innerHTML =
    _headerHtml(model.header) +
    _dialHtml(model.dial) +
    _minisHtml(model.minis) +
    _barsHtml(model.bars) +
    _tagsHtml(model.tags) +
    _viewProfileHtml(model.profile_ref);
}

export const __test = {
  _clamp01to100,
  _bandVar,
  _toneVar,
  _arcPath,
  _esc,
};
