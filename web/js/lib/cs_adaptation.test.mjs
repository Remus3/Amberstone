// web/js/lib/cs_adaptation.test.mjs
//
// RM-1211. handleChampSelect (web/js/panels/champ_select.js) used to call
// fetchAdaptation itself, but fetchAdaptation is module-local to main.js, so
// the bare call threw a ReferenceError once a champion was picked and cut
// main.js handleLcuEnvelope short. The request is now built here (pure, no
// DOM) and main.js handleLcuEnvelope makes the call. These tests pin the
// request contract: the old inline code's guards, every SR queue sent as
// the "sr" tag (the old map sent "sr_ranked", which fetchAdaptation remapped
// to aram), enemies resolved by name with unknown ids dropped. Run with
// `node --test`.

import test from "node:test";
import assert from "node:assert";

import { csAdaptationRequest } from "./cs_adaptation.js";

const CHAMPS = { ready: true, byId: { "1": "Annie", "22": "Ashe", "51": "Caitlyn", "99": "Lux" } };

function lcuOf(cs, phase = "ChampSelect") {
  return { phase, champ_select: cs };
}

test("a picked champion yields the request with resolved enemies", () => {
  const req = csAdaptationRequest(lcuOf({
    my_champion: 22, queue_id: 450,
    their_team: [{ championId: 1 }, { championId: 7777 }, null, { championId: 99 }],
  }), CHAMPS);
  assert.deepStrictEqual(req, { champion: "Ashe", modeTag: "aram", enemies: ["Annie", "Lux"] });
});

// Every tag must be one fetchAdaptation's own map knows (main.js:
// sr / aram / arena / brawl / tft / client). The old inline map sent
// "sr_ranked" for ranked SR, which that map does not know, so ranked SR
// asked for ARAM data.
const FETCH_ADAPTATION_TAGS = new Set(["sr", "aram", "arena", "brawl", "tft", "client"]);

test("queue ids map to dashboard mode tags fetchAdaptation understands", () => {
  const cases = {
    450: "aram", 920: "aram", 2400: "aram",
    1750: "arena", 1700: "arena", 1710: "arena",
    400: "sr", 420: "sr", 430: "sr", 440: "sr",
    830: "sr", 840: "sr", 850: "sr",
    12345: "aram", undefined: "aram",
  };
  for (const [qid, want] of Object.entries(cases)) {
    const q = qid === "undefined" ? undefined : Number(qid);
    const req = csAdaptationRequest(lcuOf({ my_champion: 51, queue_id: q }), CHAMPS);
    assert.strictEqual(req.modeTag, want, `queue ${qid}`);
    assert.ok(FETCH_ADAPTATION_TAGS.has(req.modeTag), `queue ${qid} tag ${req.modeTag}`);
    assert.deepStrictEqual(req.enemies, [], `queue ${qid} enemies`);
  }
});

test("no request outside champ select, before a pick, or before names resolve", () => {
  const cs = { my_champion: 22, queue_id: 420 };
  assert.strictEqual(csAdaptationRequest(null, CHAMPS), null);
  assert.strictEqual(csAdaptationRequest(lcuOf(cs, "Lobby"), CHAMPS), null);
  assert.strictEqual(csAdaptationRequest({ phase: "ChampSelect" }, CHAMPS), null);
  assert.strictEqual(csAdaptationRequest(lcuOf({ ...cs, my_champion: 0 }), CHAMPS), null);
  assert.strictEqual(csAdaptationRequest(lcuOf({ ...cs, my_champion: -1 }), CHAMPS), null);
  assert.strictEqual(csAdaptationRequest(lcuOf(cs), { ready: false, byId: CHAMPS.byId }), null);
  assert.strictEqual(csAdaptationRequest(lcuOf({ ...cs, my_champion: 4242 }), CHAMPS), null);
  assert.strictEqual(csAdaptationRequest(lcuOf(cs), null), null);
});
