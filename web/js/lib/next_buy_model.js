// web/js/lib/next_buy_model.js
//
// Pure model behind the NEXT BUY overlay widget (web/js/panels/next_buy.js) -
// the BACKLOG "Overlay HUD micro-lifts" gold + trinket rule lines. ZERO API,
// zero LLM: every value below is arithmetic over fields /api/state already
// carries. Pure (no DOM / fetch / module singletons) so it unit-tests under
// `node --test` and the panel stays a thin render - the same split as
// web/js/lib/item_value.js.
//
//   gold    - gold remaining to the NEXT Daemon-Slayer-recommended item. The
//             next item is the first liveclient.sr_items[] row with
//             next===true (dashboard/_liveclient.py:389-396, built from
//             item_advisor.resolve_build at :376). Gold is the activePlayer
//             currentGold surfaced at dashboard/_liveclient.py:148. Cost +
//             recipe are injected (web/js/lib/items_index.js ITEM_COSTS:14 /
//             ITEM_RECIPES:16 / _resolveItemId:32). Already-owned DIRECT
//             components are credited against the total - the same one-level
//             `from` walk componentProgress uses (items_index.js:189), not a
//             full recursive closure, so the figure is a truthful UNDER-credit
//             rather than a fabricated one.
//
//   trinket - the free yellow-trinket upgrade nudge. MIRRORS the server rule
//             core/build_planner/replan.py:684-689 (kind "upgrade_trinket",
//             3340 Stealth Ward -> 3363 Farsight Alteration, gated stage >=
//             mid) with the stage function core/build_planner/scoring.py:
//             106-123 and its constants :57-60. Nothing new is invented; this
//             is that server-side action rendered as a rule line, which no
//             surface did before. It is NOT a ward-cooldown cue: the Live
//             Client API exposes no cooldowns, which is exactly why the
//             w-trinket / Ward Cue widget was removed 2026-07-05
//             (overlay_layout.js:61). A pure inventory + clock rule cannot go
//             stale that way.
//
// ASCII only.

// Stage mirror - core/build_planner/scoring.py:57-60 + :106-123. The stage
// advances on EITHER the clock OR the completed-item count, whichever is
// further along. tests/test_next_buy_overlay.py pins these copies against the
// Python constants so drift fails CI.
export const NB_STAGE = {
  earlyClockS: 600,
  lateClockS: 1320,
  midOwned: 2,
  lateOwned: 4,
};
export const NB_STAGE_ORDER = { early: 0, mid: 1, late: 2 };

// Trinket mirror - core/build_planner/replan.py:72-73 + :371 + :684-689.
export const NB_TRINKET_FROM = ["stealth ward", "warding totem"];
export const NB_TRINKET_TO = "Farsight Alteration";
export const NB_TRINKET_MIN_STAGE = "mid";

// Every name the build view already treats as a non-sellable trinket
// (dashboard/_liveclient.py:383-385). Used so trinkets never count as
// completed items in the stage arithmetic.
export const NB_TRINKETS = new Set([
  "farsight alteration", "stealth ward", "oracle lens",
  "scrying orb", "warding totem",
]);

function _norm(s) {
  return String(s == null ? "" : s).trim().toLowerCase();
}

// Stage label for a game clock + completed-item count (scoring.stage_for).
export function stageFor(clockS, ownedCount) {
  const c = Number(clockS);
  const n = Number(ownedCount);
  const byClock = !Number.isFinite(c) || c < NB_STAGE.earlyClockS
    ? "early"
    : c < NB_STAGE.lateClockS ? "mid" : "late";
  const byOwned = !Number.isFinite(n) || n < NB_STAGE.midOwned
    ? "early"
    : n < NB_STAGE.lateOwned ? "mid" : "late";
  return NB_STAGE_ORDER[byClock] >= NB_STAGE_ORDER[byOwned] ? byClock : byOwned;
}

// Completed (non-trinket, non-blank) owned item count.
export function completedCount(ownedNames) {
  if (!Array.isArray(ownedNames)) return 0;
  let n = 0;
  for (const it of ownedNames) {
    const k = _norm(it);
    if (!k || NB_TRINKETS.has(k)) continue;
    n += 1;
  }
  return n;
}

// The first sr_items row flagged as the next recommendation, or "".
export function nextItemName(srItems) {
  if (!Array.isArray(srItems)) return "";
  for (const row of srItems) {
    if (!row || typeof row !== "object") continue;
    if (row.next === true && row.name) return String(row.name);
  }
  return "";
}

// Gold still needed for itemName, or null when the cost is unknown (the row
// then renders "-"; an unknown cost must NEVER render as 0g, which would read
// as "you can buy it now").
// deps = {costs, recipes, resolve} - the items_index singletons, injected.
export function goldRemaining(itemName, gold, ownedNames, deps) {
  const d = deps || {};
  const resolve = typeof d.resolve === "function" ? d.resolve : null;
  const costs = (d.costs && d.costs.byId) || null;
  if (!itemName || !resolve || !costs) return null;
  const g = Number(gold);
  if (!Number.isFinite(g) || g < 0) return null;
  const id = resolve(itemName);
  if (!id) return null;
  const total = Number(costs[String(id)]);
  if (!Number.isFinite(total) || total <= 0) return null;

  // Credit owned DIRECT components (one level, componentProgress idiom). Each
  // distinct component counts at most once.
  let credit = 0;
  const recipes = (d.recipes && d.recipes.byId) || null;
  const entry = recipes ? recipes[String(id)] : null;
  const from = (entry && Array.isArray(entry.from)) ? entry.from : [];
  if (from.length && Array.isArray(ownedNames)) {
    const ownedIds = new Set();
    for (const nm of ownedNames) {
      if (!nm) continue;
      const oid = resolve(nm);
      if (oid) ownedIds.add(String(oid));
    }
    const used = new Set();
    for (const c of from) {
      const cid = String(c);
      if (!ownedIds.has(cid) || used.has(cid)) continue;
      used.add(cid);
      const cv = Number(costs[cid]);
      if (Number.isFinite(cv) && cv > 0) credit += cv;
    }
  }
  return Math.max(0, Math.round(total - credit - g));
}

// The trinket upgrade target, or "" when the rule does not fire.
export function trinketNudge(ownedNames, clockS, ownedCount) {
  if (!Array.isArray(ownedNames)) return "";
  const has = ownedNames.some((n) => NB_TRINKET_FROM.includes(_norm(n)));
  if (!has) return "";
  const stg = stageFor(clockS, ownedCount);
  if (NB_STAGE_ORDER[stg] < NB_STAGE_ORDER[NB_TRINKET_MIN_STAGE]) return "";
  return NB_TRINKET_TO;
}

// Full widget model, or null when the widget must hide entirely (HONEST
// NO-DATA: no live game clock, no build path, or no gold reading).
export function computeNextBuy(lc, deps) {
  const block = lc && typeof lc === "object" ? lc : null;
  if (!block) return null;
  const gt = Number(block.game_time_s);
  if (!Number.isFinite(gt)) return null;
  const srItems = Array.isArray(block.sr_items) ? block.sr_items : null;
  if (!srItems || srItems.length === 0) return null;
  // Gold is activePlayer-only, so it can be absent (a spectator / relayed
  // frame). The null check MUST precede the numeric one - Number(null) is 0,
  // and an absent purse rendering as "you have 0g" is a fabricated reading.
  if (block.gold === null || block.gold === undefined) return null;
  const gold = Number(block.gold);
  if (!Number.isFinite(gold)) return null;

  const owned = Array.isArray(block.owned_items) ? block.owned_items : [];
  const item = nextItemName(srItems);
  return {
    item,
    remaining: item ? goldRemaining(item, gold, owned, deps) : null,
    trinket: trinketNudge(owned, gt, completedCount(owned)),
  };
}
