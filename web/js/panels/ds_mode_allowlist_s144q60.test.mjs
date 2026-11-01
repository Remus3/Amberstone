// web/js/panels/ds_mode_allowlist_s144q60.test.mjs
//
// RM-1330: /api/ds-combo and /api/ds-knobs now answer 400 to a mode outside
// SR / ARAM / ARENA / BRAWL, and each panel fetch reads a non-ok reply as null,
// so a consumer that sends any other value loses its card. These tests pin that
// every consumer folds to the four accepted values first. Run with `node --test`.
//
// The combo card sent String(ctx.mode).toUpperCase(), and ctx.mode is state.mode,
// which also holds "classic" (an _AM_FEED_MODES member), "client", "tft", "jade"
// and "unsupported". Those all scored as SR before, so folding them to SR keeps
// the numbers the card already showed. /api/damage-mix and /api/spike-markers
// joined them later in RM-1330; the threat donut folds through _amThreatMode.
// ASCII only.

import test from "node:test";
import assert from "node:assert";

import { __test as am } from "./active_match.js";
import { __test as knobs } from "./ds_knobs.js";
import { __test as overlay } from "./overlay_ds_controls.js";

const ACCEPTED = new Set(["SR", "ARAM", "ARENA", "BRAWL"]);

test("combo mode: the four accepted modes pass through upper-cased", () => {
  assert.strictEqual(am._amDsComboMode({ mode: "sr" }), "SR");
  assert.strictEqual(am._amDsComboMode({ mode: "aram" }), "ARAM");
  assert.strictEqual(am._amDsComboMode({ mode: "Arena" }), "ARENA");
  assert.strictEqual(am._amDsComboMode({ mode: "BRAWL" }), "BRAWL");
});

test("combo mode: every other state.mode value folds to SR", () => {
  for (const mode of ["classic", "client", "tft", "jade", "unsupported", "-", "zzq"]) {
    assert.strictEqual(am._amDsComboMode({ mode }), "SR", mode);
  }
});

test("combo mode: a missing ctx or mode is SR", () => {
  assert.strictEqual(am._amDsComboMode(null), "SR");
  assert.strictEqual(am._amDsComboMode(undefined), "SR");
  assert.strictEqual(am._amDsComboMode({}), "SR");
  assert.strictEqual(am._amDsComboMode({ mode: "" }), "SR");
});

// The threat-row and spike-marker tests below run the real render path against
// stubs, so what they read is the URL the panel asks for. They need only these few
// DOM members.
class _StubEl {
  constructor() {
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {} };
    this.innerHTML = "";
    this.isConnected = true;
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); return child; }
  replaceChild(next, prev) { this.children[this.children.indexOf(prev)] = next; return prev; }
  setAttribute() {}
}

// Async because the donut's non-ok path draws its "?" tile after the fetch settles,
// and that draw needs the stub document too.
async function _withStubs(mount, run) {
  const urls = [];
  const saved = { document: globalThis.document, fetch: globalThis.fetch };
  globalThis.document = {
    createElement: () => new _StubEl(),
    createElementNS: () => new _StubEl(),
    getElementById: () => mount,
  };
  globalThis.fetch = (url) => {
    urls.push(String(url));
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  };
  try {
    run();
    await new Promise((resolve) => setImmediate(resolve));
  } finally {
    globalThis.document = saved.document;
    globalThis.fetch = saved.fetch;
  }
  return urls;
}

function _modeParam(url) {
  return new URL(url, "http://stub.invalid").searchParams.get("mode");
}

const _STATE_MODES = ["sr", "classic", "aram", "arena", "cherry", "brawl", "client",
                      "tft", "jade", "unsupported", "-", "zzq", "constructor",
                      "__proto__", "", null, undefined];

// The threats strip hands _threatRow String(ctx.mode).toUpperCase(), or "SR" when
// ctx.mode is empty; the donut draws a "?" tile for a non-ok reply.
test("threat row: the donut asks /api/damage-mix for the folded mode", async () => {
  const expected = { SR: "SR", CLASSIC: "SR", ARAM: "ARAM", ARENA: "ARENA",
                     CHERRY: "ARENA", BRAWL: "BRAWL", CLIENT: "SR", TFT: "SR",
                     JADE: "SR", UNSUPPORTED: "SR", ZZQ: "SR", CONSTRUCTOR: "SR",
                     __PROTO__: "SR" };
  const entries = Object.entries(expected);
  assert.strictEqual(entries.length, 13);
  for (const [sent, want] of entries) {
    const urls = await _withStubs(null, () => {
      am._threatRow({ rawChampionName: `Threat${sent}`, items: [{ itemID: 3031, slot: 0 }] },
                    sent, 11);
    });
    assert.strictEqual(urls.length, 1, sent);
    assert.ok(urls[0].startsWith("/api/damage-mix?"), urls[0]);
    assert.strictEqual(_modeParam(urls[0]), want, sent);
  }
});

test("threat mode: a missing mode is SR", () => {
  for (const m of [null, undefined, ""]) {
    assert.strictEqual(am._amThreatMode(m), "SR");
  }
});

test("spike markers: the strip only ever asks for an accepted mode", async () => {
  const asked = new Map();
  for (const [i, mode] of _STATE_MODES.entries()) {
    const mount = new _StubEl();
    const urls = await _withStubs(mount, () => {
      am._renderSpikeMarkersFromCtx({ mode }, { champion: `Spike${i}`, level: 8 }, []);
    });
    assert.ok(urls.length <= 1, String(mode));
    if (urls.length) {
      assert.ok(urls[0].startsWith("/api/spike-markers?"), urls[0]);
      asked.set(mode, _modeParam(urls[0]));
    }
  }
  // An empty map would pass the check below, so name what must be fetched.
  assert.deepStrictEqual([...asked.entries()], [
    ["sr", "SR"], ["classic", "SR"], ["aram", "ARAM"], ["arena", "ARENA"],
    ["cherry", "ARENA"], ["brawl", "BRAWL"],
  ]);
  for (const value of asked.values()) assert.ok(ACCEPTED.has(value), value);
});

test("knobs panel: every queue id maps to an accepted mode", () => {
  for (const q of [0, 400, 420, 430, 440, 450, 830, 840, 850, 920, 1090, 1700, 1710, 1750, 2400]) {
    assert.ok(ACCEPTED.has(knobs._modeForQueue(q)), String(q));
  }
});

test("overlay knobs: every rc mode string maps to an accepted mode", () => {
  for (const m of ["sr", "classic", "aram", "arena", "cherry", "brawl", "tft", "client", "", null]) {
    assert.ok(ACCEPTED.has(overlay._modeForCtx(m)), String(m));
  }
});
