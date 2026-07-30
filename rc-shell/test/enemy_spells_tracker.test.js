// rc-shell/test/enemy_spells_tracker.test.js
//
// The enemy summoner-spell tap-tracker math (web/js/panels/enemy_spells.js). The
// API has no live spell cooldown, so the tracker is MANUAL: a tap records "used
// now" and the chip counts down the base CD; a second tap clears it. This pins
// the base-CD table + the toggle/remaining round-trip. Zero-dep: a localStorage
// stub on globalThis, then a dynamic import of the ES module.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const url = require("url");

let mod;
test.before(async () => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  const abs = path.join(__dirname, "..", "..", "web", "js", "panels", "enemy_spells.js");
  mod = await import(url.pathToFileURL(abs).href);
});

test("base CD table: Flash 300, Ignite 180, Smite 90", () => {
  const cd = mod._esInternals.SPELL_CD;
  assert.strictEqual(cd.Flash, 300);
  assert.strictEqual(cd.Ignite, 180);
  assert.strictEqual(cd.Smite, 90);
});

test("toggle starts the base-CD countdown; a second toggle clears it", () => {
  const I = mod._esInternals;
  I._load("game-a");
  assert.strictEqual(I._remaining("Zed", "0", "Flash"), null, "UP before any tap");
  I._toggle("Zed", "0");
  const rem = I._remaining("Zed", "0", "Flash");
  assert.ok(rem > 290 && rem <= 300, "Flash counts down ~300s after a tap, got " + rem);
  I._toggle("Zed", "0"); // mis-tap correction
  assert.strictEqual(I._remaining("Zed", "0", "Flash"), null, "second tap returns it to UP");
});

test("per-slot independence: tapping one spell does not touch the other", () => {
  const I = mod._esInternals;
  I._load("game-b");
  I._toggle("Lux", "0"); // Flash slot
  assert.ok(I._remaining("Lux", "0", "Flash") > 0, "slot 0 counting");
  assert.strictEqual(I._remaining("Lux", "1", "Barrier"), null, "slot 1 still UP");
});

test("unknown spell (no CD entry) -> sticky burned marker, cleared only by a re-tap", () => {
  const I = mod._esInternals;
  I._load("game-c");
  I._toggle("Yuumi", "0");
  // This case asserted null until 2026-07-30, which pinned the exact defect
  // aaa505ed fixed: at cd=0 the old code computed ceil(t + 0 - now) <= 0, took
  // the expiry branch, and DELETED the entry the operator had just tapped, so
  // an unrecognised spell name made the tap a silent no-op (RM-05 round-2).
  // Infinity is the deliberate contract: a "burned" marker with no countdown,
  // so a future Riot rename or a non-English locale degrades VISIBLY.
  const rem = I._remaining("Yuumi", "0", "Mystery");
  assert.strictEqual(rem, Infinity, "unknown spell marks USED, not UP");
  assert.ok(!Number.isFinite(rem), "must not fake a finite countdown");
  // Stickiness is the half that actually regressed: _updateTimers re-reads
  // every chip each tick, so the marker has to survive repeated reads.
  assert.strictEqual(I._remaining("Yuumi", "0", "Mystery"), Infinity, "survives re-read");
  I._toggle("Yuumi", "0");
  assert.strictEqual(I._remaining("Yuumi", "0", "Mystery"), null, "re-tap returns it to UP");
});

test("game-scoped: a new game_id starts a fresh tracker (no stale timers)", () => {
  const I = mod._esInternals;
  I._load("game-d");
  I._toggle("Zed", "0");
  assert.ok(I._remaining("Zed", "0", "Flash") > 0, "counting in game-d");
  I._load("game-e"); // new game
  assert.strictEqual(I._remaining("Zed", "0", "Flash"), null, "fresh in game-e");
});
