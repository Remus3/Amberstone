// web/js/panels/enemy_spells_abbr.test.mjs
//
// Regression guard for the enemy-spell chip compact label (2026-06-29). Run with
// `node --test`.
//
// The chip used to render the full displayName + state ("Flash UP" / "Unleashed
// Teleport 142s"), which overran the narrow chip and clipped to "Fla..."/"Unl..."
// (operator-reported, unreadable). _abbr maps each spell to a 2-letter tag that
// always fits; the full name moves to the chip title (hover). These pin the map +
// the unknown-spell fallback.

import test from "node:test";
import assert from "node:assert";

import { _esInternals } from "./enemy_spells.js";

const { _abbr } = _esInternals;

test("standard summoner spells map to their 2-letter tag", () => {
  assert.strictEqual(_abbr("Flash"), "FL");
  assert.strictEqual(_abbr("Teleport"), "TP");
  assert.strictEqual(_abbr("Ignite"), "IG");
  assert.strictEqual(_abbr("Smite"), "SM");
  assert.strictEqual(_abbr("Heal"), "HL");
});

test("Unleashed Teleport collapses to TP (was the 'Unl...' clip)", () => {
  assert.strictEqual(_abbr("Unleashed Teleport"), "TP");
});

test("an unknown spell falls back to its first two letters, uppercased", () => {
  assert.strictEqual(_abbr("Primal Howl"), "PR");
  assert.strictEqual(_abbr("mystery"), "MY");
});

test("every tag is short enough to never need an ellipsis (<= 2 chars)", () => {
  for (const name of Object.keys(_esInternals.SPELL_ABBR)) {
    assert.ok(_abbr(name).length <= 2, `${name} -> ${_abbr(name)} too long`);
  }
});

test("garbage / empty input never throws and yields a printable tag", () => {
  assert.strictEqual(_abbr(""), "?");
  assert.strictEqual(_abbr(null), "?");
  assert.strictEqual(_abbr("123"), "?");
});
