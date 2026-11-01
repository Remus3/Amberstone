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
// the numbers the card already showed. ASCII only.

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
