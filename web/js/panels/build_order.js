// DS vs Enemy Comp panel (2026-05-17, OVERNIGHT RUN-1 follow-up; plan §6b B+C).
//
// Renders the contextual, match-specific DS-backed item BUILD ORDER from
// POST /api/build-order (core/build_order.py plan_build_order). Two
// surfaces:
//   (B) the champ-select merged build section's ordered-sequence strip
//       (#csv-builds-seq) - mode-agnostic (sr/aram/arena). champ_select.js
//       consumes fetchBuildOrder/getCachedBuildOrder directly and renders
//       the strip itself (QA 2026-07-03 B6+B7 merge; the standalone
//       buildOrderCardHtml card was superseded and deleted, LEDGER 765).
//   (C) the in-game #ds-pill glance - buildOrderPill(state) returns the
//       next-2-in-order + a full-order rich tooltip; item_build.js (which
//       owns #ds-pill) consumes it and falls back to its top-pick render
//       when this returns null.
//
// Cost discipline: the route is N sequential engine calls (opt-in / NOT
// per-tick - see the plan + archetype_dispatch.with_build_order). A build
// order is a full-game plan, not a per-level snapshot, so we cache per
// (champion|dsMode|archetype) at a FIXED planning level. Net = exactly one
// fetch per champ+mode+arch per session - mirrors champ_select.js's
// _csvFetchDsBuilds caching discipline (presence-guarded, inflight-gated).
//
// The hard no-double rule (never two items sharing a unique passive) is
// engine-authoritative - the route already enforces it; this module only
// renders `unique_passive_safe` + any per-slot excluded_family signal.

const BO_PLAN_LEVEL = 13; // full-build planning level (matches the plan's curl example)
const BO_SLOTS = 7; // operator 2026-05-31 (#7): lane quest reward funds a 7th item

const _BO_CACHE = Object.create(null); // key -> route JSON
const _BO_INFLIGHT = Object.create(null); // key -> true while fetching

// item 213 (2026-05-28): the cache key now includes a sorted enemy-comp
// signature so the DS-vs-enemy-comp build LIVE-UPDATES when an enemy
// locks / swaps during champ-select. The backend's _resolve_ds_target_stats
// reads the `enemies` body field to derive target armor / MR / HP, so a
// changed enemy comp legitimately re-ranks the ordered build.
function _enemySig(enemies) {
  if (!Array.isArray(enemies) || !enemies.length) return "";
  return enemies.map((e) => String(e || "")).filter(Boolean).sort().join(",");
}

function _boKey(champion, dsMode, archetype, enemies) {
  return `${champion}|${dsMode}|${archetype || ""}|${_enemySig(enemies)}`;
}

// Escape for both text nodes and attribute values (data-tt-html / title).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _deltaTxt(o) {
  const unit = o.unit || "dps";
  const d = Math.round(o.delta || 0);
  return (d >= 0 ? "+" : "") + d + unit;
}

// Fire the build-order route once per (champion, dsMode, archetype). The
// onLand callback re-renders the consuming view (champ-select passes
// _csvScheduleRender; in-game the next item_build tick picks up the cache,
// so null is fine there).
// QA 2026-07-03 slice A (B6+B7): exported so champ_select.js can drive the
// merged build section's ordered-sequence strip off the same data path.
export function fetchBuildOrder(champion, dsMode, archetype, onLand, enemies) {
  if (!champion || !dsMode) return;
  const key = _boKey(champion, dsMode, archetype, enemies);
  if (_BO_CACHE[key] || _BO_INFLIGHT[key]) return;
  _BO_INFLIGHT[key] = true;
  const body = {
    champion,
    mode: dsMode,
    level: BO_PLAN_LEVEL,
    items: [],
    slots: BO_SLOTS,
  };
  if (archetype) body.archetype = archetype;
  // item 213: live enemy comp -> backend target-stat resolution.
  if (Array.isArray(enemies) && enemies.length) {
    body.enemies = enemies.map((e) => String(e || "")).filter(Boolean);
  }
  fetch("/api/build-order", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _BO_INFLIGHT[key] = false;
      if (data && data.ok && Array.isArray(data.order) && data.order.length) {
        _BO_CACHE[key] = data;
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => {
      _BO_INFLIGHT[key] = false;
    });
}

export function getCachedBuildOrder(champion, dsMode, archetype, enemies) {
  return _BO_CACHE[_boKey(champion, dsMode, archetype, enemies)] || null;
}

// ── (C) in-game #ds-pill glance ───────────────────────────────────────

// Returns { html, tt } for the pill, or null when not applicable (not
// in-game, no champion, or order not cached yet). item_build.js owns
// #ds-pill; on null it falls back to its existing top-pick render.
export function buildOrderPill(stateObj) {
  if (!stateObj) return null;
  const champ =
    stateObj.champion ||
    (stateObj.coach && stateObj.coach.champion) ||
    "";
  if (!champ || champ === "-") return null;
  // In-game we don't have the CS queue id; map from mode flags. Default
  // SR (the route is still valid; the card (B) is the mode-correct
  // planned-build surface - this pill is the glance companion).
  let dsMode = "SR";
  if (stateObj.aram_mode) dsMode = "ARAM";
  else if (stateObj.arena_mode) dsMode = "ARENA";
  const archetype = ""; // backend auto-resolves via core.archetype_picks
  const data = getCachedBuildOrder(champ, dsMode, archetype);
  if (!data) {
    fetchBuildOrder(champ, dsMode, archetype, null);
    return null;
  }
  const order = Array.isArray(data.order) ? data.order : [];
  if (!order.length) return null;
  // Advance the cursor past items already owned (client-side; v1 plans
  // from empty - live re-derivation is the plan's Phase 4).
  const owned = Array.isArray(stateObj.owned_item_ids)
    ? stateObj.owned_item_ids.map((x) => String(x))
    : [];
  const remaining = order.filter((o) => owned.indexOf(String(o.item_id)) < 0);
  const next2 = (remaining.length ? remaining : order).slice(0, 2);
  const html = `▸ ${next2.map((o) => _esc(o.item_name)).join(" → ")}`;
  const full = order
    .map(
      (o) =>
        `${o.slot}. ${_esc(o.item_name)} (${_esc(_deltaTxt(o))}, ${o.gold || 0}g)`,
    )
    .join("<br>");
  const tt = `Build order${
    data.unique_passive_safe ? " · no-double ✓" : ""
  }:<br>${full}`;
  return { html, tt };
}

// Test/diagnostic helper - clears caches + collapses the card so the next
// render fetches + writes unconditionally (mirrors _resetArchetypeNudgeSig).
export function _resetBuildOrder() {
  for (const k of Object.keys(_BO_CACHE)) delete _BO_CACHE[k];
  for (const k of Object.keys(_BO_INFLIGHT)) delete _BO_INFLIGHT[k];
}
