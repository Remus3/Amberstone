// web/js/panels/stats_panel.js
//
// Overlay-only "You vs rank average" mini-panel (overlay item 8, rework). A
// vertical two-column compare beside the native HUD: the live game ("You") next
// to a SELECTED rank-tier's average for the current mode + game-time bracket
// ("Avg"). Unlike the pre-rework personal-history lens, the benchmark side is a
// mode-specific rank-tier ESTIMATE (e.g. "an average Gold SR game") for
// self-improvement - so the provenance badge (source()) is load-bearing:
// coaching must never read the estimate as ground truth.
//
// The rank tier is picked in DS Settings (web/js/panels/overlay_ds_controls.js),
// NOT in this panel - the old in-panel role picker is retired and the compare-
// role override moved there too. This panel READS the shared setting
// (rc-pgr-rank-tier via lib/overlay_settings.js) and repaints on change.
//
// Header  = the auto-derived game-time bracket label + the provenance/tier badge.
// Rows    = mode-specific. SR + ARAM: LVL / CS / KDA / KP. Arena: LVL / KDA
//           (no CS), gated to "no benchmark" (there is no Arena seed yet).
//           You cell = live ground truth; Bench cell = the rank-tier average
//           from GET /api/rank-tier-bench. LVL has no bench producer (the seed
//           carries cs/kda/kp only), so its honest "-" is a reserved slot,
//           never a removed row (no reflow). KP is live on both sides since
//           2026-07-20 (dashboard/_liveclient.py emits kill_participation_pct
//           as a percent-suffixed string); it falls back to the same reserved
//           "-" when the producer omits the key (0 team kills).
//
// The scaffold is (re)built when the mode's row set changes; every tick updates
// the cell text IN PLACE (no innerHTML churn) so the panel never flickers.
// Benchmark fetches are cached per (tier, mode, bracket) with a TTL + inflight
// guard so a per-tick repaint never re-hits the route. A fetch error leaves the
// cells at "-" (degraded), never a raw error string (repo Error-Handling rule).

import { championTags } from "../lib/champion_tags.js";
import {
  readBenchmarkRankTier, readRoleOverride, PGR_RANK_KEY, RANK_TIER_EVENT,
} from "../lib/overlay_settings.js";

const _BENCH_URL = "/api/rank-tier-bench";
const _TTL_MS = 5 * 60 * 1000;

// Game-time brackets over the live clock (seconds), mirroring the backend
// core.rank_tier_bench / core.role_bracket_bench boundaries so "You" compares to
// same-length games: < 840s (14:00) = early, else mid. The old >= 35:00 long-game
// bucket is retired (overlay item 8 lock-step); 1500 stays the nominal mid label.
const _BRACKET_EARLY_MAX_S = 840;
const _BRACKET_MID_MAX_S = 1500;

// Mode-specific metric rows (keys) + labels. lvl/cs/kda/kp all have a live
// "You" value; cs/kda/kp have a rank-tier "Avg" value. lvl is You-only (no
// seed metric) and renders an honest "-" on the Avg side.
const _ROW_LABELS = { lvl: "LVL", cs: "CS", kda: "KDA", kp: "KP" };
const _ROWS_BY_MODE = {
  SR: ["lvl", "cs", "kda", "kp"],
  ARAM: ["lvl", "cs", "kda", "kp"],
  ARENA: ["lvl", "kda"],
};
// Metrics the seed can fill the benchmark column with (the route's stats keys).
const _BENCH_METRICS = { cs: 1, kda: 1, kp: 1 };
// Human tier labels for the provenance badge (mirrors the DS Settings options).
const _TIER_LABELS = {
  iron: "Iron", bronze: "Bronze", silver: "Silver", gold: "Gold",
  platinum: "Platinum", emerald: "Emerald", diamond: "Diamond",
  master: "Master", grandmaster: "Grandmaster", challenger: "Challenger",
};

// rc mode string (lowercase) -> rank-tier bench mode. Unknown/unset -> SR (the
// overlay is SR-centric); Arena has no seed so the route returns "no benchmark".
const _MODE_MAP = { sr: "SR", classic: "SR", aram: "ARAM", arena: "ARENA", cherry: "ARENA" };

let _role = "mid";        // seeded from the detected lane/class; the DS Settings override wins
let _roleUserSet = false; // true once the operator sets the role override in DS Settings
let _bracket = "mid";
let _lastLc = null;       // remembered so a settings change can repaint immediately
let _lastMode = "";       // last rc mode string threaded in
let _syncWired = false;   // one-time storage / custom-event listener guard
const _cache = Object.create(null);     // "tier|mode|bracket" -> response JSON
const _ts = Object.create(null);
const _inflight = Object.create(null);

function _benchMode(mode) {
  return _MODE_MAP[String(mode || "").toLowerCase()] || "SR";
}

function _bracketFor(secs) {
  const s = Number(secs) || 0;
  if (s <= 0) return "mid";
  if (s < _BRACKET_EARLY_MAX_S) return "early";
  if (s < _BRACKET_MID_MAX_S) return "mid";
  return "mid";     // >= 25:00 folds into mid (the retired long-game bucket)
}

// Live Client position (the operator's assigned SR lane) -> compare-role key.
const _POS_ROLE = { TOP: "top", JUNGLE: "jungle", MIDDLE: "mid", BOTTOM: "bot", UTILITY: "support" };
// Champion primary class -> compare-role key. The ARAM / no-lane fallback: with
// no assigned position, lean on the champion's class so Kai'Sa / Aphelios
// (Marksman) compare against BOT, not a hardcoded MID (operator 2026-07-06).
// Fuzzy by nature (a Fighter/Tank could be top or jungle) - it is only the
// starting default; the DS Settings role override always wins.
const _CLASS_ROLE = { Marksman: "bot", Support: "support", Mage: "mid", Assassin: "mid", Tank: "top", Fighter: "top" };

// Best-effort detect of the operator's role for the default compare: the SR
// assigned lane first (Live Client position on the is_active player), else the
// champion's class in a laneless mode (ARAM). Returns null when neither resolves
// (the caller then keeps the current default). tagsLookup is injectable for tests;
// it defaults to the async-lazy championTags cache. Retained across the rework
// (the rank-tier seed is laneless today, but the override + detection carry
// forward for per-role data + inform other overlay consumers).
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

// Live KP normalizer. The producer (dashboard/_liveclient.py) emits a STRING
// with a percent sign ("44%") while the benchmark side is a bare number in
// percent points (kp avg 58 from /api/rank-tier-bench), so strip the sign and
// hand _fmt a number for a like-for-like two-column compare. Returns null on
// an absent / empty / non-numeric value - _liveclient omits the key entirely
// at 0 team kills (KP is undefined there), and that honest "-" is correct.
function _kpPct(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().replace(/%$/, "").trim();
  if (!s) return null;
  const n = Number(s);
  return isFinite(n) ? n : null;
}

function _fmt(v) {
  if (v === null || v === undefined) return "-";
  const n = Number(v);
  if (!isFinite(n)) return "-";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

// (Re)build the row scaffold for a mode's metric set. Guarded on the mode key so
// a per-tick repaint of the SAME mode never churns the DOM; a mode whose row set
// differs (Arena drops CS) rebuilds once.
function _ensureScaffold(mount, benchMode) {
  if (mount.dataset.built === "1" && mount.dataset.spMode === benchMode) return;
  const keys = _ROWS_BY_MODE[benchMode] || _ROWS_BY_MODE.SR;
  const rows = keys.map(
    (k) =>
      '<div class="sp-row" data-row="' + k + '">' +
        '<span class="sp-metric">' + _ROW_LABELS[k] + "</span>" +
        '<span class="sp-you" data-c="' + k + '">-</span>' +
        '<span class="sp-bench-cell" data-c="' + k + '">-</span>' +
      "</div>"
  ).join("");
  mount.innerHTML =
    '<div class="sp-selrow">' +
      '<span class="sp-bracket">-</span>' +
      '<span class="sp-src">-</span>' +
    "</div>" +
    '<div class="sp-colhead">' +
      '<span class="sp-metric"></span>' +
      '<span class="sp-you">You</span>' +
      '<span class="sp-bench-cell">Avg</span>' +
    "</div>" +
    rows;
  mount.dataset.built = "1";
  mount.dataset.spMode = benchMode;
  // The ARAM/no-lane fallback leans on the champion class, which loads async;
  // re-seed the compare role once that cache lands (until the operator picks).
  if (mount.dataset.tagsWired !== "1") {
    mount.dataset.tagsWired = "1";
    document.addEventListener("rc:champion-tags-ready", () => {
      if (!_roleUserSet && _lastLc) renderStatsPanel(_lastLc, { mode: _lastMode });
    });
  }
}

// Repaint on a shared rank-tier change (DS Settings / PGR / desktop Settings).
// The custom event covers this window; the native storage event covers other
// windows of the origin (e.g. the companion picking a tier).
function _ensureSyncWiring() {
  if (_syncWired || typeof window === "undefined") return;
  _syncWired = true;
  try {
    window.addEventListener(RANK_TIER_EVENT, () => {
      if (_lastLc) renderStatsPanel(_lastLc, { mode: _lastMode });
    });
    window.addEventListener("storage", (e) => {
      if (e && e.key === PGR_RANK_KEY && _lastLc) renderStatsPanel(_lastLc, { mode: _lastMode });
    });
  } catch (_e) {
    // no window (node / test) - the panel still renders, just without live sync.
  }
}

function _setCell(mount, side, k, text) {
  const el = mount.querySelector("." + side + '[data-c="' + k + '"]');
  if (el) el.textContent = text;
}

// Paint the benchmark column from whatever is cached for (tier, mode, bracket)
// right now. A miss / off / no-seed blanks the bench cells to "-" so a stale
// column never lingers after a tier switch or a bracket roll (no reflow - the
// row set is fixed for the mode).
function _paintBench(mount, benchMode, tier) {
  const keys = _ROWS_BY_MODE[benchMode] || _ROWS_BY_MODE.SR;
  const data = tier ? _cache[tier + "|" + benchMode + "|" + _bracket] : null;
  const stats = (data && data.stats) || {};
  keys.forEach((k) => {
    if (!_BENCH_METRICS[k]) { _setCell(mount, "sp-bench-cell", k, "-"); return; }
    const cell = stats[k] || {};
    _setCell(mount, "sp-bench-cell", k, _fmt(cell.avg));
  });
  _paintBadge(mount, benchMode, tier, data);
}

// The bracket label + the provenance/tier badge. The badge is load-bearing: it
// tells the operator (and keeps coaching honest) that the numbers are an
// estimate, not measured - and names WHY the column is empty when it is.
function _paintBadge(mount, benchMode, tier, data) {
  const bl = mount.querySelector(".sp-bracket");
  if (bl) bl.textContent = _bracket;
  const sb = mount.querySelector(".sp-src");
  if (!sb) return;
  if (!tier) { sb.textContent = "set rank"; return; }
  const label = _TIER_LABELS[tier] || tier;
  // Arena (and any mode the seed does not cover) comes back mode:"" / n:0.
  if (benchMode === "ARENA" || (data && !data.mode)) { sb.textContent = "no benchmark"; return; }
  if (data && data.n === 0) { sb.textContent = label + " -"; return; }
  const prov = data && data.source === "live" ? "live avg" : "estimate";
  sb.textContent = label + " " + prov;
}

function _fetchBench(mount, benchMode, tier) {
  // Reflect whatever is cached right now (blanks to "-" on a miss).
  _paintBench(mount, benchMode, tier);
  // Off (no tier) or a mode with no seed (Arena) does not hit the route.
  if (!tier || benchMode === "ARENA") return;
  const key = tier + "|" + benchMode + "|" + _bracket;
  const now = Date.now();
  if (_cache[key] && _ts[key] && (now - _ts[key]) < _TTL_MS) return;
  if (_inflight[key]) return;
  _inflight[key] = true;
  const url =
    _BENCH_URL +
    "?tier=" + encodeURIComponent(tier) +
    "&mode=" + encodeURIComponent(benchMode) +
    "&bracket=" + encodeURIComponent(_bracket);
  fetch(url, { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) return;     // leave cells at "-" (degraded)
      _cache[key] = data;
      _ts[key] = Date.now();
      if (tier + "|" + benchMode + "|" + _bracket === key) _paintBench(mount, benchMode, tier);
    })
    .catch(() => {})       // never leak a raw error string; cells stay "-"
    .finally(() => { _inflight[key] = false; });
}

// Self-gated on the overlay shell + a live player block (hp_max present). opts
// carries the rc mode string (main.js threads it); body.dataset.mode is the
// fallback so a bare renderStatsPanel(lc) still resolves the mode.
export function renderStatsPanel(lc, opts) {
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
  _ensureSyncWiring();
  _lastLc = lc;
  const mode = (opts && opts.mode) || (document.body && document.body.dataset.mode) || "";
  _lastMode = mode;
  const benchMode = _benchMode(mode);
  // The DS Settings role override wins; else default the compare role to the
  // DETECTED role (SR lane, else the champion's class in ARAM). Retained for
  // per-role data + other consumers (the rank-tier seed is laneless today).
  const override = readRoleOverride();
  if (override) {
    _role = override;
    _roleUserSet = true;
  } else if (!_roleUserSet) {
    const detected = _detectRole(lc);
    if (detected) _role = detected;
  }
  _ensureScaffold(mount, benchMode);
  // Bracket follows the live clock so the benchmark is same-length games.
  _bracket = _bracketFor(lc.game_time_s);
  // You side - live ground truth for every row (lvl / cs / kda / kp). The KP
  // key is optional on the snapshot, so _kpPct -> _fmt keeps the honest "-"
  // when it is absent (Arena never asks: its row set is lvl/kda only).
  const keys = _ROWS_BY_MODE[benchMode] || _ROWS_BY_MODE.SR;
  if (keys.indexOf("lvl") >= 0) _setCell(mount, "sp-you", "lvl", lc.level == null ? "-" : String(lc.level));
  if (keys.indexOf("cs") >= 0) _setCell(mount, "sp-you", "cs", lc.cs == null ? "-" : String(lc.cs));
  if (keys.indexOf("kda") >= 0) _setCell(mount, "sp-you", "kda", _fmt(_kdaRatio(lc.kda)));
  if (keys.indexOf("kp") >= 0) _setCell(mount, "sp-you", "kp", _fmt(_kpPct(lc.kill_participation_pct)));
  // Benchmark side - cached rank-tier averages for the selected tier.
  const tier = readBenchmarkRankTier();
  _fetchBench(mount, benchMode, tier);
  mount.hidden = false;
}

// Test seam: drop the built-scaffold flag so a fresh render rebuilds.
export function _resetStatsPanel() {
  _role = "mid";
  _roleUserSet = false;
  const mount = document.getElementById("am-statspanel");
  if (mount) {
    mount.dataset.built = "";
    mount.dataset.spMode = "";
    mount.innerHTML = "";
  }
}

export const __test = { _detectRole, _POS_ROLE, _CLASS_ROLE, _benchMode, _bracketFor, _kpPct };
