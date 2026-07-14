// web/js/lib/item_value.js
//
// R117 F1 - team item-value differential (the economy lens the live scoreboard
// hides). Enemy GOLD is activePlayer-only over the Live Client API, but
// allPlayers[].items is public for all 10, so summing each player's on-board
// item gold-worth (ITEM_COSTS) and diffing ally-team vs enemy-team is the one
// economy signal computable client-side. Pure (no DOM / fetch) so it unit-tests
// under `node --test` and the caller (map_state.renderItemValueDiff) stays a
// thin render. Fail-soft: any missing input yields null so the bar hides,
// preserving the pre-R117 dormant behavior. ASCII only.

// Resolve the active player's team from the liveclient roster. Mirrors
// active_match._resolveMyTeam - kept local to avoid a panel->panel import.
export function _resolveMyTeam(lc) {
  if (!lc || typeof lc !== "object") return null;
  const ap = lc.activePlayer || {};
  const me = ap.summonerName || ap.riotIdGameName || "";
  if (!me) return null;
  for (const pl of (lc.allPlayers || [])) {
    if (!pl || typeof pl !== "object") continue;
    const rid = pl.riotIdGameName || pl.summonerName || "";
    if (rid === me || me.startsWith(rid + "#") || rid === me.split("#", 1)[0]) {
      return pl.team || null;
    }
  }
  return null;
}

// Sum one player's on-board item value from ITEM_COSTS.byId. Unknown ids
// contribute 0 (a truthful undercount beats a fabricated total - the same
// discipline as active_match._amCompletedItemCount). Item id field is itemID
// with an itemId alias, coerced to a string (mirrors _extractBpEnemies).
export function _playerItemValue(pl, itemCosts) {
  if (!pl || !itemCosts || !itemCosts.byId) return 0;
  let v = 0;
  for (const it of (Array.isArray(pl.items) ? pl.items : [])) {
    const id = String((it && (it.itemID || it.itemId)) || "");
    if (!id) continue;
    const c = itemCosts.byId[id];
    if (typeof c === "number" && c > 0) v += c;
  }
  return v;
}

// Ally-team item value minus enemy-team item value. null (bar hides) when the
// roster / costs / active-player team cannot be resolved; a plain number
// otherwise. Positive = ally ahead on item gold-worth.
export function teamItemValueDiff(lc, itemCosts) {
  if (!lc || typeof lc !== "object") return null;
  if (!itemCosts || !itemCosts.ready || !itemCosts.byId) return null;
  const all = Array.isArray(lc.allPlayers) ? lc.allPlayers : [];
  if (all.length === 0) return null;
  const myTeam = _resolveMyTeam(lc);
  if (!myTeam) return null;
  let ally = 0;
  let enemy = 0;
  for (const pl of all) {
    if (!pl || typeof pl !== "object") continue;
    const v = _playerItemValue(pl, itemCosts);
    if (pl.team === myTeam) ally += v;
    else enemy += v;
  }
  return ally - enemy;
}
