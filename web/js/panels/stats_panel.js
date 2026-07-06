// web/js/panels/stats_panel.js
//
// Overlay-only "You vs benchmark" mini-panel (WP-A4b, operator 2026-06-28). A
// vertical two-column compare beside the native HUD: the live game ("You") next
// to the operator's OWN historical average for the selected role at the current
// game-time bracket ("Avg"). The benchmark side is a DESCRIPTIVE personal-corpus
// lens (your own baselines), never a meta / Riot / Claude number.
//
// Header  = a role <select> (the operator picks the lane to compare against) plus
//           the auto-derived game-time bracket label.
// Rows    = LVL / CS / TF / KDA. You cell = live ground truth; Bench cell = the
//           role x bracket average from GET /api/role-bracket-bench.
//
// TF (kill participation) has NO live producer in the Live Client API, so the You
// side renders an honest "-"; the benchmark column still shows the historical KP.
//
// The scaffold is built once; every tick updates the cell text IN PLACE (no
// innerHTML churn) so the panel never flickers. Benchmark fetches are cached per
// (role, bracket) with a TTL + inflight guard (mirrors champ_benchmarks.js) so a
// per-tick repaint never re-hits the route. A fetch error leaves the cells at "-"
// (degraded), never a raw error string (repo Error-Handling rule).

import { championTags } from "../lib/champion_tags.js";

const _BENCH_URL = "/api/role-bracket-bench";
const _ROLES = [["top", "Top"], ["jungle", "Jungle"], ["mid", "Mid"], ["bot", "Bot"], ["support", "Support"]];
const _ROWS = [["lvl", "LVL"], ["cs", "CS"], ["tf", "TF"], ["kda", "KDA"]];
const _TTL_MS = 5 * 60 * 1000;

// Game-time brackets over the live clock (seconds), mirroring the backend
// core.role_bracket_bench boundaries so "You" compares to same-length games:
// < 1500s (25:00) = early, < 2100s (35:00) = mid, else late.
const _BRACKET_EARLY_MAX_S = 1500;
const _BRACKET_MID_MAX_S = 2100;

let _role = "mid";        // seeded from the detected lane/class on first render; the selector overrides
let _roleUserSet = false; // true once the operator manually picks a role - stops auto-seeding
let _bracket = "mid";
let _lastLc = null;     // remembered so a selector change can repaint immediately
const _cache = Object.create(null);     // "role|bracket" -> response JSON
const _ts = Object.create(null);
const _inflight = Object.create(null);

function _bracketFor(secs) {
  const s = Number(secs) || 0;
  if (s <= 0) return "mid";
  if (s < _BRACKET_EARLY_MAX_S) return "early";
  if (s < _BRACKET_MID_MAX_S) return "mid";
  return "late";
}

// Live Client position (the operator's assigned SR lane) -> compare-role key.
const _POS_ROLE = { TOP: "top", JUNGLE: "jungle", MIDDLE: "mid", BOTTOM: "bot", UTILITY: "support" };
// Champion primary class -> compare-role key. The ARAM / no-lane fallback: with
// no assigned position, lean on the champion's class so Kai'Sa / Aphelios
// (Marksman) compare against BOT, not a hardcoded MID (operator 2026-07-06).
// Fuzzy by nature (a Fighter/Tank could be top or jungle) - it is only the
// starting default; the dropdown override always wins.
const _CLASS_ROLE = { Marksman: "bot", Support: "support", Mage: "mid", Assassin: "mid", Tank: "top", Fighter: "top" };

// Best-effort detect of the operator's role for the default compare: the SR
// assigned lane first (Live Client position on the is_active player), else the
// champion's class in a laneless mode (ARAM). Returns null when neither resolves
// (the caller then keeps the current default). tagsLookup is injectable for tests;
// it defaults to the async-lazy championTags cache.
function _detectRole(lc, tagsLookup) {
  if (!lc || typeof lc !== "object") return null;
  const lookup = typeof tagsLookup === "function" ? tagsLookup : championTags;
  const players = Array.isArray(lc.players) ? lc.players : [];
  const me = players.find((p) => p && p.is_active);
  const pos = me && typeof me.position === "string" ? me.position.toUpperCase() : "";
  if (_POS_ROLE[pos]) return _POS_ROLE[pos];
  const champ = lc.champion;
  if (champ) {
    const entry = lookup(champ);
    const cls = entry && (entry.primary || (Array.isArray(entry.tags) ? entry.tags[0] : null));
    if (cls && _CLASS_ROLE[cls]) return _CLASS_ROLE[cls];
  }
  return null;
}

// lc.kda is the "k/d/a" string; the benchmark is the (k+a)/max(d,1) ratio, so the
// You cell computes that same ratio for a like-for-like compare.
function _kdaRatio(kda) {
  const parts = String(kda == null ? "" : kda).split("/");
  if (parts.length !== 3) return null;
  const k = Number(parts[0]) || 0;
  const d = Number(parts[1]) || 0;
  const a = Number(parts[2]) || 0;
  return (k + a) / (d > 0 ? d : 1);
}

function _fmt(v) {
  if (v === null || v === undefined) return "-";
  const n = Number(v);
  if (!isFinite(n)) return "-";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function _ensureScaffold(mount) {
  if (mount.dataset.built === "1") return;
  mount.dataset.built = "1";
  const opts = _ROLES.map(
    ([v, lab]) => '<option value="' + v + '">' + lab + "</option>"
  ).join("");
  const rows = _ROWS.map(
    ([k, lab]) =>
      '<div class="sp-row" data-row="' + k + '">' +
        '<span class="sp-metric">' + lab + "</span>" +
        '<span class="sp-you" data-c="' + k + '">-</span>' +
        '<span class="sp-bench-cell" data-c="' + k + '">-</span>' +
      "</div>"
  ).join("");
  mount.innerHTML =
    '<div class="sp-selrow">' +
      '<select class="sp-role" aria-label="Compare role">' + opts + "</select>" +
      '<span class="sp-bracket">-</span>' +
    "</div>" +
    '<div class="sp-colhead">' +
      '<span class="sp-metric"></span>' +
      '<span class="sp-you">You</span>' +
      '<span class="sp-bench-cell">Avg</span>' +
    "</div>" +
    rows;
  const sel = mount.querySelector(".sp-role");
  if (sel) {
    sel.value = _role;
    sel.addEventListener("change", () => {
      _role = sel.value || "mid";
      _roleUserSet = true;   // an explicit operator pick wins - stop auto-seeding from detection
      renderStatsPanel(_lastLc);
    });
  }
  // The ARAM/no-lane fallback leans on the champion class, which loads async;
  // re-seed the compare role once that cache lands (until the operator picks).
  document.addEventListener("rc:champion-tags-ready", () => {
    if (!_roleUserSet && _lastLc) renderStatsPanel(_lastLc);
  });
}

function _setCell(mount, side, k, text) {
  const el = mount.querySelector("." + side + '[data-c="' + k + '"]');
  if (el) el.textContent = text;
}

function _paintBench(mount) {
  const data = _cache[_role + "|" + _bracket];
  const stats = (data && data.stats) || {};
  _ROWS.forEach(([k]) => {
    const cell = stats[k] || {};
    _setCell(mount, "sp-bench-cell", k, _fmt(cell.avg));
  });
}

function _fetchBench(mount) {
  // Reflect whatever is cached for the current (role, bracket) right now - on a
  // miss this blanks the bench cells to "-" so a stale column never lingers
  // after a role switch or a bracket roll.
  _paintBench(mount);
  const key = _role + "|" + _bracket;
  const now = Date.now();
  if (_cache[key] && _ts[key] && (now - _ts[key]) < _TTL_MS) return;
  if (_inflight[key]) return;
  _inflight[key] = true;
  const url =
    _BENCH_URL +
    "?role=" + encodeURIComponent(_role) +
    "&bracket=" + encodeURIComponent(_bracket);
  fetch(url, { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) return;     // leave cells at "-" (degraded)
      _cache[key] = data;
      _ts[key] = Date.now();
      if (_role + "|" + _bracket === key) _paintBench(mount);
    })
    .catch(() => {})       // never leak a raw error string; cells stay "-"
    .finally(() => { _inflight[key] = false; });
}

// Self-gated on the overlay shell + a live player block (hp_max present).
export function renderStatsPanel(lc) {
  const mount = document.getElementById("am-statspanel");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  // hp_max is the cheapest "are we actually in a game" gate (0 out of game).
  if (!lc || !Number(lc.hp_max)) {
    mount.hidden = true;
    return;
  }
  _lastLc = lc;
  // Default the compare role to the operator's DETECTED role (SR lane, else the
  // champion's class in ARAM) instead of a hardcoded MID - until they pick one.
  if (!_roleUserSet) {
    const detected = _detectRole(lc);
    if (detected) _role = detected;
  }
  _ensureScaffold(mount);
  // Keep the selector in sync when detection changed _role after the scaffold built.
  const roleSel = mount.querySelector(".sp-role");
  if (roleSel && roleSel.value !== _role) roleSel.value = _role;
  // Bracket follows the live clock so the benchmark is same-length games.
  _bracket = _bracketFor(lc.game_time_s);
  const bl = mount.querySelector(".sp-bracket");
  if (bl) bl.textContent = _bracket;
  // You side - live ground truth.
  _setCell(mount, "sp-you", "lvl", lc.level == null ? "-" : String(lc.level));
  _setCell(mount, "sp-you", "cs", lc.cs == null ? "-" : String(lc.cs));
  _setCell(mount, "sp-you", "tf", "-");     // no live KP producer (see header note)
  _setCell(mount, "sp-you", "kda", _fmt(_kdaRatio(lc.kda)));
  // Benchmark side - cached role x bracket averages.
  _fetchBench(mount);
  mount.hidden = false;
}

// Test seam: drop the built-scaffold flag so a fresh render rebuilds.
export function _resetStatsPanel() {
  _role = "mid";
  _roleUserSet = false;
  const mount = document.getElementById("am-statspanel");
  if (mount) {
    mount.dataset.built = "";
    mount.innerHTML = "";
  }
}

export const __test = { _detectRole, _POS_ROLE, _CLASS_ROLE };
