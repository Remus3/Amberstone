// web/js/panels/active_match_buildflicker.test.mjs
//
// Regression guard for the 2026-06-29 BUILD-panel random-flicker bug. Run with
// `node --test`.
//
// _renderAmBuildBody wipes innerHTML then rebuilds the module only when
// picks || metaOrder || champion is truthy. A transient mid-game tick with an
// empty coach payload (no champion - e.g. the :8891 WS push of a momentarily
// stale coaching file) therefore cleared the pane and rendered nothing, so the
// BUILD panel blanked for a tick then came back (operator-reported). The pure
// _shouldRetainBuild guard makes the caller keep the last good paint on such a
// tick. These pin that predicate.

import test from "node:test";
import assert from "node:assert";

import { _shouldRetainBuild } from "./active_match.js";

test("no items WITH existing content -> retain (the core fix)", () => {
  // no picks, no meta, but the pane already has a render.
  assert.strictEqual(_shouldRetainBuild("", 0, 0, true), true);
});

test("no items with NO existing content -> do not retain (first paint)", () => {
  // Nothing drawn yet: fall through so the empty/placeholder state renders.
  assert.strictEqual(_shouldRetainBuild("", 0, 0, false), false);
});

test("champion present but NO items + content -> retain (no placeholder swap)", () => {
  // The broadened guard: a transient tick with a champion but empty picks/meta
  // must keep the real items, not swap them for "waiting..."/"loading...".
  assert.strictEqual(_shouldRetainBuild("Caitlyn", 0, 0, true), true);
});

test("live picks present -> never retain (real render proceeds)", () => {
  assert.strictEqual(_shouldRetainBuild("", 3, 0, true), false);
  assert.strictEqual(_shouldRetainBuild("Caitlyn", 3, 0, true), false);
});

test("meta order present -> never retain (real render proceeds)", () => {
  assert.strictEqual(_shouldRetainBuild("", 0, 6, true), false);
});

test("falsy hasContent is coerced (undefined/null behave as no-content)", () => {
  assert.strictEqual(_shouldRetainBuild("", 0, 0, undefined), false);
  assert.strictEqual(_shouldRetainBuild("", 0, 0, null), false);
});
