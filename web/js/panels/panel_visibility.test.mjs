// web/js/panels/panel_visibility.test.mjs
//
// RC2 E1: pure-logic tests for the per-panel visibility gate (separate IN-GAME
// vs OUT-OF-GAME panel toggles). Run with `node --test`.
//
// Only the PURE core is covered here (schema read / merge / resolve / context
// derivation). The DOM-applying wrapper (applyPanelVisibility) needs a live
// document and is exercised in the dashboard at runtime - these tests pin the
// persistence schema + the in/out-game context switch that the gate reads.

import test from "node:test";
import assert from "node:assert";

import {
  GAME_PANELS,
  CONTEXTS,
  contextForMode,
  defaultVisibility,
  readVisibility,
  setPanelVisible,
  isPanelVisible,
} from "./panel_visibility.js";

test("GAME_PANELS: the five in-game dashboard panels", () => {
  assert.deepStrictEqual(
    GAME_PANELS.map((p) => p.id),
    ["minimap", "right-now", "next", "item-build", "adaptation"]
  );
  // Every panel carries a human label for the settings UI.
  for (const p of GAME_PANELS) {
    assert.ok(typeof p.label === "string" && p.label.length > 0, p.id);
  }
});

test("CONTEXTS: exactly in-game + out-game", () => {
  assert.deepStrictEqual(CONTEXTS, ["in-game", "out-game"]);
});

test("contextForMode: a game mode -> in-game", () => {
  for (const m of ["sr", "aram", "arena", "tft", "brawl"]) {
    assert.strictEqual(contextForMode(m), "in-game", m);
  }
});

test("contextForMode: client / empty / unknown / non-string -> out-game", () => {
  for (const m of ["client", "", "lobby", null, undefined, 42]) {
    assert.strictEqual(contextForMode(m), "out-game", JSON.stringify(m));
  }
});

test("contextForMode: case + whitespace insensitive", () => {
  assert.strictEqual(contextForMode("  ARAM "), "in-game");
  assert.strictEqual(contextForMode("Client"), "out-game");
});

test("defaultVisibility: every panel visible in both contexts by default", () => {
  const d = defaultVisibility();
  for (const ctx of CONTEXTS) {
    for (const p of GAME_PANELS) {
      assert.strictEqual(d[ctx][p.id], true, `${ctx}/${p.id}`);
    }
  }
});

test("readVisibility: missing / garbage blob -> all-visible default", () => {
  for (const g of [null, undefined, "", "junk", "[]", "42", "{}"]) {
    const v = readVisibility(g);
    assert.deepStrictEqual(v, defaultVisibility(), JSON.stringify(g));
  }
});

test("readVisibility: a saved false for one panel/context is honored; rest default true", () => {
  const blob = JSON.stringify({ "in-game": { minimap: false } });
  const v = readVisibility(blob);
  assert.strictEqual(v["in-game"].minimap, false);
  // every other in-game panel stays visible
  assert.strictEqual(v["in-game"]["right-now"], true);
  // the out-game context is untouched (all visible)
  assert.strictEqual(v["out-game"].minimap, true);
});

test("readVisibility: unknown panel ids + unknown contexts are dropped", () => {
  const blob = JSON.stringify({
    "in-game": { minimap: false, bogus: false },
    "zzz-context": { minimap: false },
  });
  const v = readVisibility(blob);
  assert.ok(!("bogus" in v["in-game"]));
  assert.ok(!("zzz-context" in v));
  assert.strictEqual(v["in-game"].minimap, false);
});

test("readVisibility: non-boolean panel values fall back to true", () => {
  const blob = JSON.stringify({ "in-game": { minimap: "no", next: 0 } });
  const v = readVisibility(blob);
  assert.strictEqual(v["in-game"].minimap, true);
  assert.strictEqual(v["in-game"].next, true);
});

test("setPanelVisible: returns a new blob string with the panel hidden in one context only", () => {
  const next = setPanelVisible("{}", "in-game", "minimap", false);
  const v = readVisibility(next);
  assert.strictEqual(v["in-game"].minimap, false);
  assert.strictEqual(v["out-game"].minimap, true); // other context untouched
});

test("setPanelVisible: re-showing a panel persists true", () => {
  let blob = setPanelVisible("{}", "out-game", "adaptation", false);
  assert.strictEqual(readVisibility(blob)["out-game"].adaptation, false);
  blob = setPanelVisible(blob, "out-game", "adaptation", true);
  assert.strictEqual(readVisibility(blob)["out-game"].adaptation, true);
});

test("setPanelVisible: unknown panel id / context is a no-op (blob still valid)", () => {
  const next = setPanelVisible("{}", "in-game", "bogus", false);
  assert.deepStrictEqual(readVisibility(next), defaultVisibility());
  const next2 = setPanelVisible("{}", "zzz", "minimap", false);
  assert.deepStrictEqual(readVisibility(next2), defaultVisibility());
});

test("setPanelVisible: garbage prev blob starts fresh, does not throw", () => {
  const next = setPanelVisible("not json", "in-game", "next", false);
  assert.strictEqual(readVisibility(next)["in-game"].next, false);
});

test("isPanelVisible: resolves a panel for a given context from a blob", () => {
  const blob = setPanelVisible("{}", "in-game", "item-build", false);
  assert.strictEqual(isPanelVisible(blob, "in-game", "item-build"), false);
  assert.strictEqual(isPanelVisible(blob, "out-game", "item-build"), true);
  // unknown -> visible (fail-open: never hide a panel we don't recognize)
  assert.strictEqual(isPanelVisible(blob, "in-game", "bogus"), true);
});

test("round-trip: set several, read back the exact map", () => {
  let blob = "{}";
  blob = setPanelVisible(blob, "in-game", "minimap", false);
  blob = setPanelVisible(blob, "in-game", "next", false);
  blob = setPanelVisible(blob, "out-game", "right-now", false);
  const v = readVisibility(blob);
  assert.strictEqual(v["in-game"].minimap, false);
  assert.strictEqual(v["in-game"].next, false);
  assert.strictEqual(v["in-game"]["right-now"], true);
  assert.strictEqual(v["out-game"]["right-now"], false);
  assert.strictEqual(v["out-game"].minimap, true);
});
