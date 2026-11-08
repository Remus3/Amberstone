// web/js/panels/active_match_live_champ_names.test.mjs
//
// S144-U-217: the in-game THREATS strip drew a row of EMPTY "?" circles in a
// live game (docs/qa/UI_UX_QUEUE_2026-07-21.md, In-game overlay: "DS panel
// THREATS row renders 5 (SR) / 12 (Arena) EMPTY placeholder circles").
//
// Root cause: the Live Client serves `rawChampionName` as a LOCALIZATION KEY,
// "game_character_displayname_Kaisa", not a champion id (measured live
// 2026-07-20 by the ARAM balance fix, web/js/panels/aram_balance.js
// _AB_RAW_PREFIX; core/focus_board_live.py _RAW_PREFIX strips the same
// prefix). _threatRow PREFERRED that field and only stripped
// non-alphanumerics, so it built
//   portrait  /img/champion/gamecharacterdisplaynameKaisa.png  (404, then the
//             CDN retry 404s and the portrait is hidden)
//   donut     /api/damage-mix?champ_id=gamecharacterdisplaynameKaisa  (the
//             route cannot resolve it, answers 400, the donut draws "?")
// for every enemy. The same field was preferred by _amDsSyntheticCs, so every
// live enemy resolved to championId 0 and was dropped from the relscore /
// matchup roster. The spike-curve and draft-elo strips read championName
// first, which misses "Wukong" (DDragon id MonkeyKing) and "Nunu & Willump"
// (Nunu), and those strips need all ten champions to draw at all.
//
// The existing tests never saw it because every fixture set rawChampionName
// equal to the canonical id ("Jinx"), never the live key form.
//
// CHAMPS is an exported mutable singleton, so the tests seed it directly.
// ASCII only. Run with `node --test`.

import test from "node:test";
import assert from "node:assert";

import { CHAMPS } from "../lib/items_index.js";
import { __test as am } from "./active_match.js";

// Real rows out of web/data/champions_index.json byId ({numericKeyString -> Slug}).
const BY_ID = {
  "222": "Jinx",
  "145": "Kaisa",
  "62": "MonkeyKing",
  "20": "Nunu",
  "36": "DrMundo",
  "412": "Thresh",
  "64": "LeeSin",
  "121": "Khazix",
  "157": "Yasuo",
  "25": "Morgana",
};

let _seedN = 0;
function seedChamps() {
  CHAMPS.byId = { ...BY_ID };
  CHAMPS.byName = {};
  for (const slug of Object.values(BY_ID)) {
    CHAMPS.byName[String(slug).toLowerCase().replace(/[^a-z0-9]/g, "")] = slug;
  }
  // A fresh version each seed so the _champNumericKey memo rebuilds.
  _seedN += 1;
  CHAMPS.version = `test-${_seedN}`;
  CHAMPS.ready = true;
}

// The live Live Client shape: display name + localization key.
function livePlayer(display, slug, team, extra) {
  return Object.assign({
    championName: display,
    rawChampionName: `game_character_displayname_${slug}`,
    team,
    items: [],
  }, extra || {});
}

test("live champ key: the localization-key form resolves to the numeric key", () => {
  seedChamps();
  assert.strictEqual(am._amLiveChampKey(livePlayer("Kai'Sa", "Kaisa", "CHAOS")), 145);
  assert.strictEqual(am._amLiveChampKey(livePlayer("Dr. Mundo", "DrMundo", "CHAOS")), 36);
});

test("live champ key: display names that differ from the DDragon id still resolve", () => {
  seedChamps();
  // championName alone misses these two; the stripped key carries the id.
  assert.strictEqual(am._champNumericKey("Wukong"), 0);
  assert.strictEqual(am._champNumericKey("Nunu & Willump"), 0);
  assert.strictEqual(am._amLiveChampKey(livePlayer("Wukong", "MonkeyKing", "CHAOS")), 62);
  assert.strictEqual(am._amLiveChampKey(livePlayer("Nunu & Willump", "Nunu", "CHAOS")), 20);
});

test("live champ key: the mock shape (raw == id) and a display-name-only row resolve", () => {
  seedChamps();
  assert.strictEqual(am._amLiveChampKey({ championName: "Jinx", rawChampionName: "Jinx" }), 222);
  assert.strictEqual(am._amLiveChampKey({ championName: "Lee Sin" }), 64);
  assert.strictEqual(am._amLiveChampKey({ rawChampionName: "game_character_displayname_Yasuo" }), 157);
});

test("live champ key: junk and unknown rows are 0, never a throw", () => {
  seedChamps();
  for (const pl of [null, undefined, 7, "Jinx", {}, { championName: "" },
                    { rawChampionName: "game_character_displayname_" },
                    { championName: "NotAChampion", rawChampionName: "game_character_displayname_Nope" },
                    { championName: 5, rawChampionName: {} }]) {
    assert.strictEqual(am._amLiveChampKey(pl), 0, JSON.stringify(pl));
  }
});

test("live champ slug: the DDragon id, from the index when loaded", () => {
  seedChamps();
  assert.strictEqual(am._amLiveChampSlug(livePlayer("Wukong", "MonkeyKing", "CHAOS")), "MonkeyKing");
  assert.strictEqual(am._amLiveChampSlug(livePlayer("Kai'Sa", "Kaisa", "CHAOS")), "Kaisa");
  assert.strictEqual(am._amLiveChampSlug({ championName: "Lee Sin" }), "LeeSin");
});

test("live champ slug: before the index loads, the stripped key, never the prefix", () => {
  CHAMPS.byId = {};
  CHAMPS.byName = {};
  CHAMPS.version = "empty-index";
  assert.strictEqual(am._amLiveChampSlug(livePlayer("Kai'Sa", "Kaisa", "CHAOS")), "Kaisa");
  assert.strictEqual(am._amLiveChampSlug({ championName: "Lee Sin" }), "LeeSin");
  assert.strictEqual(am._amLiveChampSlug({}), "");
  seedChamps();
});

// --- the THREATS row, through the real render path ------------------------

class _StubEl {
  constructor(tag) {
    this.tagName = tag || "";
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {} };
    this.isConnected = true;
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); return child; }
  replaceChild(next, prev) { this.children[this.children.indexOf(prev)] = next; return prev; }
  setAttribute() {}
}

async function threatRow(pl) {
  const urls = [];
  const saved = { document: globalThis.document, fetch: globalThis.fetch };
  globalThis.document = {
    createElement: (t) => new _StubEl(t),
    createElementNS: (_ns, t) => new _StubEl(t),
  };
  globalThis.fetch = (url) => {
    urls.push(String(url));
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  };
  let row;
  try {
    row = am._threatRow(pl, "SR", 11);
    await new Promise((resolve) => setImmediate(resolve));
  } finally {
    globalThis.document = saved.document;
    globalThis.fetch = saved.fetch;
  }
  return { row, urls };
}

test("threat row: a live enemy gets its own portrait and donut id, not the key", async () => {
  seedChamps();
  // Distinct item sets per case so the donut's in-flight / cache dedupe never
  // swallows a fetch.
  const cases = [
    [livePlayer("Kai'Sa", "Kaisa", "CHAOS", { items: [{ itemID: 6671, slot: 0 }] }), "Kaisa"],
    [livePlayer("Wukong", "MonkeyKing", "CHAOS", { items: [{ itemID: 3071, slot: 0 }] }), "MonkeyKing"],
    [livePlayer("Dr. Mundo", "DrMundo", "CHAOS", { items: [{ itemID: 3084, slot: 0 }] }), "DrMundo"],
  ];
  for (const [pl, want] of cases) {
    const { row, urls } = await threatRow(pl);
    const portrait = row.children[0];
    assert.ok(portrait.src.endsWith(`/img/champion/${want}.png`), portrait.src);
    assert.ok(!/displayname/i.test(portrait.src), portrait.src);
    // The tooltip names the champion the way the game does.
    assert.strictEqual(portrait.alt, pl.championName);
    assert.strictEqual(portrait.title, pl.championName);
    assert.strictEqual(urls.length, 1, want);
    const champId = new URL(urls[0], "http://stub.invalid").searchParams.get("champ_id");
    assert.strictEqual(champId, want);
  }
});

test("threat row: a row with no championName labels with the stripped key", async () => {
  seedChamps();
  const { row } = await threatRow({ rawChampionName: "game_character_displayname_Morgana",
                                    team: "CHAOS", items: [] });
  const portrait = row.children[0];
  assert.strictEqual(portrait.alt, "Morgana");
  assert.ok(portrait.src.endsWith("/img/champion/Morgana.png"), portrait.src);
});

// --- the relscore / matchup roster -----------------------------------------

test("synthetic cs: every live-shaped enemy reaches their_team with its key", () => {
  seedChamps();
  const lc = {
    activePlayer: { riotIdGameName: "SamplePlayer#Tag" },
    allPlayers: [
      Object.assign(livePlayer("Jinx", "Jinx", "ORDER"), { riotIdGameName: "SamplePlayer" }),
      Object.assign(livePlayer("Thresh", "Thresh", "ORDER"), { riotIdGameName: "AllyOne" }),
      Object.assign(livePlayer("Kai'Sa", "Kaisa", "CHAOS"), { riotIdGameName: "EnemyOne" }),
      Object.assign(livePlayer("Wukong", "MonkeyKing", "CHAOS"), { riotIdGameName: "EnemyTwo" }),
      Object.assign(livePlayer("Nunu & Willump", "Nunu", "CHAOS"), { riotIdGameName: "EnemyThree" }),
    ],
  };
  const cs = am._amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: lc });
  assert.ok(cs, "synthetic cs built");
  assert.deepStrictEqual(cs.their_team.map((e) => e.championId), [145, 62, 20]);
});
