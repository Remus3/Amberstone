// Champ-select ADAPTATION request (RM-1211).
//
// 2026-04-25 cold-start champ-select coaching: once a champion is picked in
// ChampSelect, the dashboard surfaces the operator's historical adaptation
// data BEFORE the game starts. handleChampSelect (panels/champ_select.js)
// used to make that call itself, but fetchAdaptation is module-local to
// main.js and panels never import main.js, so since the Phase 3.1 ESM split
// the bare call threw a ReferenceError on every LCU envelope of a pick and
// cut main.js handleLcuEnvelope short. s162 moved four calls of the same
// class into handleLcuEnvelope and missed this one.
//
// So the request is built here, pure and DOM-free, and main.js
// handleLcuEnvelope makes the call (the s162 shape: orchestration lives where
// the cross-cutting functions are defined). Guarded tree-wide by
// tests/test_web_js_unimported_calls_s144q43.py; contract pinned by
// cs_adaptation.test.mjs.

// Queue id -> the DASHBOARD mode tag fetchAdaptation takes (sr / aram /
// arena), which it maps to the analyzer's mode itself (sr -> sr_ranked).
// ARAM-family = 450 (Classic) / 920 (Poro King) / 2400 (Mayhem); Arena =
// 1750 live (1700/1710 legacy); SR = 400 draft, 420/430/440 ranked/blind/
// flex, 830-850 co-op vs AI. Unknown queues fall back to aram, as before.
//
// The inline map this replaces (in the code since the initial commit) sent
// the ANALYZER name "sr_ranked" for every SR queue but 400; fetchAdaptation's
// own map has no "sr_ranked" key, so ranked SR fell through to "aram" and
// asked for ARAM adaptation data and ARAM trending. Measured by the headless
// test tests/snapshot_panels/test_champ_select_adaptation_fetch_s144q43.py.
const CS_ADAPT_MODE = {
  450: "aram", 920: "aram", 2400: "aram",
  1750: "arena", 1700: "arena", 1710: "arena",
  400: "sr", 420: "sr", 430: "sr", 440: "sr",
  830: "sr", 840: "sr", 850: "sr",
};

// Returns { champion, modeTag, enemies } for fetchAdaptation(champion,
// modeTag, enemies), or null when there is nothing to ask for: not in
// ChampSelect, no pick yet, the champion-name index not loaded, or the
// picked id unresolved. `champs` is the lib/items_index.js CHAMPS index
// ({ ready, byId }).
function csAdaptationRequest(lcu, champs) {
  if (!lcu || lcu.phase !== "ChampSelect") return null;
  const cs = lcu.champ_select || {};
  if (!cs.my_champion || cs.my_champion <= 0) return null;
  if (!champs || !champs.ready || !champs.byId) return null;
  const champion = champs.byId[String(cs.my_champion)];
  if (!champion) return null;
  const enemies = (cs.their_team || [])
    .map((p) => champs.byId[String(p && p.championId)])
    .filter(Boolean);
  return { champion, modeTag: CS_ADAPT_MODE[cs.queue_id] || "aram", enemies };
}

export { csAdaptationRequest, CS_ADAPT_MODE };
