// DS vs Enemy Comp panel (2026-05-17, OVERNIGHT RUN-1 follow-up; plan §6b B+C).
//
// Renders the contextual, match-specific DS-backed item BUILD ORDER from
// POST /api/build-order (core/build_order.py plan_build_order). Surface:
//   (B) the champ-select merged build section's ordered-sequence strip
//       (#csv-builds-seq) - mode-agnostic (sr/aram/arena). champ_select.js
//       consumes fetchBuildOrder/getCachedBuildOrder directly and renders
//       the strip itself (QA 2026-07-03 B6+B7 merge; the standalone
//       buildOrderCardHtml card was superseded and deleted, LEDGER 765).
//   ((C), the in-game #ds-pill glance via buildOrderPill(state), was
//       removed 2026-07-04 with header row 2.)
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

// Test/diagnostic helper - clears caches + collapses the card so the next
// render fetches + writes unconditionally.
export function _resetBuildOrder() {
  for (const k of Object.keys(_BO_CACHE)) delete _BO_CACHE[k];
  for (const k of Object.keys(_BO_INFLIGHT)) delete _BO_INFLIGHT[k];
}
