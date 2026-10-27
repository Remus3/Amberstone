// web/js/panels/lobby_duo_synergy.test.mjs
//
// RM-881 (b) (QA23, lobby re-fire of duo synergy). Before this module NO web
// code called /api/duo-synergy (`git grep duo-synergy -- web/js` had 0 hits;
// the champ-select duo grid was removed by item 213). These tests drive the
// lobby controller with a MOCK fetch and the page's own ui_mock fixture
// (web/data/ui_mock/duo_synergy.json) and pin the contract: the fetch fires
// when the party size reaches 2, not while solo, not on every 2 s refresh,
// and again after the party drops back to solo and re-forms. The
// RC_DUO_SYNERGY_LIVE kill switch is server-side and is not touched here.
// Run with `node --test`.

import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

import {
  createLobbyDuoSynergy, duoSynergyQuery, lobbyDuoSynergyHtml, __test,
} from "./lobby_duo_synergy.js";

const FIXTURE = JSON.parse(readFileSync(
  new URL("../../data/ui_mock/duo_synergy.json", import.meta.url), "utf8"));

function lobbyOf(size, firstPref) {
  const lobby = { party_size: size, members: [] };
  for (let i = 0; i < size; i++) lobby.members.push({ is_self: i === 0 });
  if (firstPref !== undefined) {
    lobby.local_member = {
      is_self: true,
      position_preferences: { first_preference: firstPref,
                              second_preference: "FILL" },
    };
  }
  return lobby;
}

function mockFetch(payload, opts = {}) {
  const calls = [];
  const impl = (url) => {
    calls.push(String(url));
    if (opts.reject) return Promise.reject(new Error("boom: raw error"));
    return Promise.resolve({
      ok: opts.status === undefined || opts.status < 400,
      status: opts.status || 200,
      json: () => Promise.resolve(payload),
    });
  };
  return { impl, calls };
}

test("duoSynergyQuery: solo, empty or missing lobby -> no request", () => {
  assert.strictEqual(duoSynergyQuery(null), null);
  assert.strictEqual(duoSynergyQuery({}), null);
  assert.strictEqual(duoSynergyQuery(lobbyOf(1, "BOTTOM")), null);
  assert.strictEqual(duoSynergyQuery({ party_size: 0 }), null);
});

test("duoSynergyQuery: party of 2 or more -> /api/duo-synergy with my_role", () => {
  const q = duoSynergyQuery(lobbyOf(2, "BOTTOM"));
  assert.ok(q.startsWith("/api/duo-synergy?"), q);
  assert.match(q, /my_role=bot/);
  assert.match(q, /top_n=4/);
  assert.match(duoSynergyQuery(lobbyOf(2, "UTILITY")), /my_role=sup/);
  assert.match(duoSynergyQuery(lobbyOf(3, "MIDDLE")), /my_role=bot/);
  // No local member forwarded yet: the route's own default role.
  assert.match(duoSynergyQuery(lobbyOf(5)), /my_role=bot/);
});

test("duoSynergyQuery: party size falls back to the members list length", () => {
  const lobby = { members: [{ is_self: true }, { is_self: false }] };
  assert.match(duoSynergyQuery(lobby), /^\/api\/duo-synergy\?/);
});

test("controller: no fetch while solo, one fetch when the party reaches 2", async () => {
  const f = mockFetch(FIXTURE);
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl });
  assert.strictEqual(ctl.update(lobbyOf(1, "BOTTOM")), null);
  assert.strictEqual(f.calls.length, 0);
  const p = ctl.update(lobbyOf(2, "BOTTOM"));
  assert.ok(p && typeof p.then === "function", "party of 2 must fire");
  await p;
  assert.strictEqual(f.calls.length, 1);
  assert.match(f.calls[0], /^\/api\/duo-synergy\?.*my_role=bot/);
  assert.strictEqual(ctl.state().status, "ready");
  assert.deepStrictEqual(ctl.state().payload.top_row, FIXTURE.top_row);
});

test("controller: the 2 s lobby refresh does not re-fire for the same party", async () => {
  const f = mockFetch(FIXTURE);
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl });
  await ctl.update(lobbyOf(2, "BOTTOM"));
  for (let i = 0; i < 5; i++) assert.strictEqual(ctl.update(lobbyOf(2, "BOTTOM")), null);
  // Growing 2 -> 3 is the same "party reached 2" episode.
  assert.strictEqual(ctl.update(lobbyOf(3, "BOTTOM")), null);
  assert.strictEqual(f.calls.length, 1);
});

test("controller: re-fires after the party drops to solo and re-forms", async () => {
  const f = mockFetch(FIXTURE);
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl });
  await ctl.update(lobbyOf(2, "BOTTOM"));
  assert.strictEqual(ctl.update(lobbyOf(1, "BOTTOM")), null);
  assert.strictEqual(ctl.state().status, "idle");
  await ctl.update(lobbyOf(2, "BOTTOM"));
  assert.strictEqual(f.calls.length, 2);
});

test("controller: a changed lane preference re-fires with the new role", async () => {
  const f = mockFetch(FIXTURE);
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl });
  await ctl.update(lobbyOf(2, "BOTTOM"));
  await ctl.update(lobbyOf(2, "UTILITY"));
  assert.strictEqual(f.calls.length, 2);
  assert.match(f.calls[1], /my_role=sup/);
});

test("controller: a non-SR queue (ARAM / Arena) never fetches bot + support picks", async () => {
  const f = mockFetch(FIXTURE);
  const srOnly = (qid) => qid === 420;
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl, isDuoQueue: srOnly });
  const aram = Object.assign(lobbyOf(2, "BOTTOM"), { queue_id: 450 });
  const unknown = Object.assign(lobbyOf(2, "BOTTOM"), { queue_id: 0 });
  assert.strictEqual(ctl.update(aram), null);
  assert.strictEqual(ctl.update(unknown), null);
  assert.strictEqual(f.calls.length, 0);
  assert.strictEqual(ctl.state().status, "idle");
  // The same party moving to a ranked SR queue fires.
  await ctl.update(Object.assign(lobbyOf(2, "BOTTOM"), { queue_id: 420 }));
  assert.strictEqual(f.calls.length, 1);
  // And back to ARAM hides the block again.
  assert.strictEqual(ctl.update(aram), null);
  assert.strictEqual(ctl.state().status, "idle");
});

test("duoSynergyQuery: the queue predicate gates the request", () => {
  const lobby = Object.assign(lobbyOf(2, "BOTTOM"), { queue_id: 1750 });
  assert.strictEqual(duoSynergyQuery(lobby, (q) => q === 420), null);
  assert.match(duoSynergyQuery(lobby), /^\/api\/duo-synergy\?/);
});

test("controller: ui_mock reads the page's own fixture, not the live route", async () => {
  const f = mockFetch(FIXTURE);
  const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl, isMock: () => true });
  await ctl.update(lobbyOf(2, "BOTTOM"));
  assert.deepStrictEqual(f.calls, ["/data/ui_mock/duo_synergy.json"]);
  assert.strictEqual(ctl.state().status, "ready");
});

test("controller: a rejected fetch, a 500 or ok:false degrade, never throw", async () => {
  for (const f of [mockFetch(null, { reject: true }),
                   mockFetch({ ok: false, error: "internal error" }, { status: 500 }),
                   mockFetch({ ok: false })]) {
    const ctl = createLobbyDuoSynergy({ fetchImpl: f.impl });
    await ctl.update(lobbyOf(2, "BOTTOM"));
    assert.strictEqual(ctl.state().status, "error");
    const html = lobbyDuoSynergyHtml(ctl.state(), () => "");
    assert.match(html, /duo picks unavailable/);
    assert.doesNotMatch(html, /boom|internal error/);
  }
});

test("controller: onChange fires on loading and on landing", async () => {
  const f = mockFetch(FIXTURE);
  const seen = [];
  const ctl = createLobbyDuoSynergy({
    fetchImpl: f.impl, onChange: (s) => seen.push(s.status) });
  await ctl.update(lobbyOf(2, "BOTTOM"));
  assert.deepStrictEqual(seen, ["loading", "ready"]);
});

test("controller: a stale response from a dissolved party is dropped", async () => {
  let resolveFirst;
  const calls = [];
  const impl = (url) => {
    calls.push(url);
    return new Promise((r) => { resolveFirst = r; });
  };
  const ctl = createLobbyDuoSynergy({ fetchImpl: impl });
  const p = ctl.update(lobbyOf(2, "BOTTOM"));
  ctl.update(lobbyOf(1, "BOTTOM"));
  // The request is issued on a microtask; let it reach the mock first.
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(calls.length, 1);
  resolveFirst({ ok: true, status: 200, json: () => Promise.resolve(FIXTURE) });
  await p;
  assert.strictEqual(ctl.state().status, "idle");
});

test("lobbyDuoSynergyHtml: idle -> empty string (block stays hidden)", () => {
  assert.strictEqual(lobbyDuoSynergyHtml({ status: "idle" }, () => ""), "");
  assert.strictEqual(lobbyDuoSynergyHtml(null, () => ""), "");
});

test("lobbyDuoSynergyHtml: loading names the state", () => {
  assert.match(lobbyDuoSynergyHtml({ status: "loading" }, () => ""),
               /loading duo picks/);
});

test("lobbyDuoSynergyHtml: ready renders BOT and SUPPORT rows from the fixture", () => {
  const html = lobbyDuoSynergyHtml(
    { status: "ready", payload: FIXTURE },
    (name) => `/icons/${name}.png`);
  assert.match(html, /lv-duosyn-row-bot/);
  assert.match(html, /lv-duosyn-row-sup/);
  for (const cell of FIXTURE.top_row.concat(FIXTURE.bottom_row)) {
    assert.ok(html.includes(cell.champ), `missing ${cell.champ}`);
  }
  // Win rate shown as a percentage of the cell's smoothed rate.
  assert.match(html, /54\.7%/);
  // No upstream source string on the UI (item 213 (C) removed it).
  assert.doesNotMatch(html, /101\.qq|qq\.com/i);
  assert.ok(!/[^\x00-\x7f]/.test(html), "ASCII only");
});

test("lobbyDuoSynergyHtml: escapes champion names and drops a missing icon", () => {
  const payload = { ok: true, top_row: [{ champ: "<img src=x onerror=1>",
                                          smoothed_rate: 0.5 }],
                    bottom_row: [] };
  const html = lobbyDuoSynergyHtml({ status: "ready", payload }, () => "");
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x onerror=1&gt;/);
});

test("lobbyDuoSynergyHtml: ready with no rows says so instead of an empty block", () => {
  const html = lobbyDuoSynergyHtml(
    { status: "ready", payload: { ok: true, top_row: [], bottom_row: [] } },
    () => "");
  assert.match(html, /no duo picks yet/);
});

test("__test exposes the role mapping", () => {
  assert.strictEqual(__test.roleForPref("UTILITY"), "sup");
  assert.strictEqual(__test.roleForPref("BOTTOM"), "bot");
  assert.strictEqual(__test.roleForPref("JUNGLE"), "bot");
  assert.strictEqual(__test.roleForPref(undefined), "bot");
});
