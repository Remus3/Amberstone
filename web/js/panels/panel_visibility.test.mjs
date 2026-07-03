// web/js/panels/panel_visibility.test.mjs
//
// QA slice B (2026-07-03): pure-logic tests for the PER-MODE panel visibility
// gate. The 2-context model (in-game / out-game) is replaced by five contexts
// (in-game-sr / in-game-aram / in-game-arena / in-game-tft / out-game) and the
// panel registry expands from the legacy 5 to the full main-dashboard set.
// Run with `node --test`.
//
// Only the PURE core is covered here (schema read / merge / migrate / resolve /
// context derivation / tab-state normalization). The DOM wrapper
// (applyPanelVisibility / the tab bar renderer) needs a live document and is
// exercised in the dashboard at runtime; tests/test_panel_visibility_permode.py
// pins the DOM/CSS contract at source level.

import test from "node:test";
import assert from "node:assert";

import {
  PANELS,
  GAME_PANELS,
  PANEL_IDS,
  CONTEXTS,
  IN_GAME_CONTEXTS,
  TABS,
  contextForMode,
  normalizeTab,
  defaultVisibility,
  readVisibility,
  serializeVisibility,
  setPanelVisible,
  isPanelVisible,
} from "./panel_visibility.js";

// The legacy 5 - must survive the expansion (prefs for them keep working).
const LEGACY_IDS = ["minimap", "right-now", "next", "item-build", "adaptation"];

// Named expansion panels the QA ruling called out explicitly.
const EXPANSION_IDS = [
  "coach-decisions",
  "rn-lead",
  "rn-choices",
  "rn-callouts",
  "personal-context-section",
  "session-trend",
  "lm-tc-table",
  "hpgr-tc-table",
  "am-spike-curve",
  "am-spike-markers",
  "am-ward-heat",
  "aram-balance-panel",
];

// -- contexts ----------------------------------------------------------------

test("CONTEXTS: the four per-mode in-game contexts plus out-game", () => {
  assert.deepStrictEqual(CONTEXTS, [
    "in-game-sr",
    "in-game-aram",
    "in-game-arena",
    "in-game-tft",
    "out-game",
  ]);
  assert.deepStrictEqual(IN_GAME_CONTEXTS, [
    "in-game-sr",
    "in-game-aram",
    "in-game-arena",
    "in-game-tft",
  ]);
});

test("contextForMode: each live mode maps to its own context", () => {
  assert.strictEqual(contextForMode("sr"), "in-game-sr");
  assert.strictEqual(contextForMode("aram"), "in-game-aram");
  assert.strictEqual(contextForMode("arena"), "in-game-arena");
  assert.strictEqual(contextForMode("tft"), "in-game-tft");
});

test("contextForMode: brawl (retired, s214) inherits the SR context", () => {
  assert.strictEqual(contextForMode("brawl"), "in-game-sr");
});

test("contextForMode: client / empty / unknown / non-string -> out-game", () => {
  for (const m of ["client", "", "lobby", null, undefined, 42]) {
    assert.strictEqual(contextForMode(m), "out-game", JSON.stringify(m));
  }
});

test("contextForMode: case + whitespace insensitive", () => {
  assert.strictEqual(contextForMode("  ARAM "), "in-game-aram");
  assert.strictEqual(contextForMode("Client"), "out-game");
});

test("contextForMode: Object.prototype names are not modes (no proto leak)", () => {
  for (const m of ["constructor", "toString", "hasOwnProperty", "__proto__"]) {
    assert.strictEqual(contextForMode(m), "out-game", m);
  }
});

// -- panel registry ----------------------------------------------------------

test("PANELS: expanded registry keeps the legacy 5 and adds the QA set", () => {
  const ids = PANELS.map((p) => p.id);
  for (const id of LEGACY_IDS) {
    assert.ok(ids.includes(id), `legacy panel missing: ${id}`);
  }
  for (const id of EXPANSION_IDS) {
    assert.ok(ids.includes(id), `expansion panel missing: ${id}`);
  }
  assert.ok(ids.length >= 17, `expected >= 17 panels, got ${ids.length}`);
});

test("PANELS: ids unique, labels human + ASCII-only", () => {
  const ids = PANELS.map((p) => p.id);
  assert.strictEqual(new Set(ids).size, ids.length, "duplicate panel id");
  for (const p of PANELS) {
    assert.ok(typeof p.label === "string" && p.label.length > 0, p.id);
    assert.match(p.label, /^[\x20-\x7e]+$/, `non-ASCII label: ${p.id}`);
  }
  assert.deepStrictEqual(PANEL_IDS, ids);
});

test("GAME_PANELS: kept as a back-compat alias of PANELS", () => {
  assert.strictEqual(GAME_PANELS, PANELS);
});

// -- defaults ----------------------------------------------------------------

test("defaultVisibility: every panel visible in every one of the 5 contexts", () => {
  const d = defaultVisibility();
  assert.deepStrictEqual(Object.keys(d), [...CONTEXTS]);
  for (const ctx of CONTEXTS) {
    for (const p of PANELS) {
      assert.strictEqual(d[ctx][p.id], true, `${ctx}/${p.id}`);
    }
  }
});

// -- fail-open on corrupt blobs ----------------------------------------------

test("readVisibility: missing / garbage blob -> all-visible default", () => {
  for (const g of [null, undefined, "", "junk", "[]", "42", "{}", "{broken"]) {
    const v = readVisibility(g);
    assert.deepStrictEqual(v, defaultVisibility(), JSON.stringify(g));
  }
});

test("readVisibility: non-boolean panel values fall back to true", () => {
  const blob = JSON.stringify({ "in-game-sr": { minimap: "no", next: 0 } });
  const v = readVisibility(blob);
  assert.strictEqual(v["in-game-sr"].minimap, true);
  assert.strictEqual(v["in-game-sr"].next, true);
});

test("readVisibility: unknown panel ids + unknown contexts are dropped", () => {
  const blob = JSON.stringify({
    "in-game-sr": { minimap: false, bogus: false },
    "zzz-context": { minimap: false },
  });
  const v = readVisibility(blob);
  assert.ok(!("bogus" in v["in-game-sr"]));
  assert.ok(!("zzz-context" in v));
  assert.strictEqual(v["in-game-sr"].minimap, false);
});

// -- legacy-blob migration ---------------------------------------------------

test("migration: legacy in-game prefs copy to every in-game-* context", () => {
  const legacy = JSON.stringify({
    "in-game": { minimap: false, "rn-callouts": false },
    "out-game": { next: false },
  });
  const v = readVisibility(legacy);
  for (const ctx of IN_GAME_CONTEXTS) {
    assert.strictEqual(v[ctx].minimap, false, ctx);
    assert.strictEqual(v[ctx]["rn-callouts"], false, ctx);
    // untouched panels stay visible
    assert.strictEqual(v[ctx]["item-build"], true, ctx);
  }
  // out-game carries over directly, and does NOT inherit in-game prefs
  assert.strictEqual(v["out-game"].next, false);
  assert.strictEqual(v["out-game"].minimap, true);
  // the legacy key itself does not survive as a context
  assert.ok(!("in-game" in v));
});

test("migration: explicit per-mode prefs override migrated legacy values", () => {
  const blob = JSON.stringify({
    "in-game": { minimap: false },
    "in-game-aram": { minimap: true },
  });
  const v = readVisibility(blob);
  assert.strictEqual(v["in-game-sr"].minimap, false);
  assert.strictEqual(v["in-game-arena"].minimap, false);
  assert.strictEqual(v["in-game-tft"].minimap, false);
  assert.strictEqual(v["in-game-aram"].minimap, true); // explicit wins
});

test("migration: corrupt legacy sub-blob never breaks boot (fail-open)", () => {
  for (const legacy of [42, "x", [1, 2], null]) {
    const blob = JSON.stringify({ "in-game": legacy });
    assert.deepStrictEqual(
      readVisibility(blob),
      defaultVisibility(),
      JSON.stringify(legacy)
    );
  }
});

test("migration: serialize drops the legacy key (one-way upgrade)", () => {
  const blob = JSON.stringify({ "in-game": { minimap: false } });
  const out = serializeVisibility(readVisibility(blob));
  const parsed = JSON.parse(out);
  assert.ok(!("in-game" in parsed));
  for (const ctx of IN_GAME_CONTEXTS) {
    assert.strictEqual(parsed[ctx].minimap, false, ctx);
  }
});

// -- per-context matrix ------------------------------------------------------

test("matrix: hiding a panel in one context leaves the other 4 visible", () => {
  const checks = [
    ["in-game-sr", "minimap"],
    ["in-game-aram", "aram-balance-panel"],
    ["in-game-arena", "rn-choices"],
    ["in-game-tft", "item-build"],
    ["out-game", "session-trend"],
  ];
  for (const [ctx, id] of checks) {
    const blob = setPanelVisible("{}", ctx, id, false);
    const v = readVisibility(blob);
    assert.strictEqual(v[ctx][id], false, `${ctx}/${id}`);
    for (const other of CONTEXTS) {
      if (other === ctx) continue;
      assert.strictEqual(v[other][id], true, `${other}/${id} must stay visible`);
    }
  }
});

test("setPanelVisible: re-showing persists true; unknowns are no-ops", () => {
  let blob = setPanelVisible("{}", "in-game-tft", "adaptation", false);
  assert.strictEqual(readVisibility(blob)["in-game-tft"].adaptation, false);
  blob = setPanelVisible(blob, "in-game-tft", "adaptation", true);
  assert.strictEqual(readVisibility(blob)["in-game-tft"].adaptation, true);
  // unknown panel / context / legacy context name are all no-ops
  for (const [ctx, id] of [
    ["in-game-sr", "bogus"],
    ["zzz", "minimap"],
    ["in-game", "minimap"],
  ]) {
    assert.deepStrictEqual(
      readVisibility(setPanelVisible("{}", ctx, id, false)),
      defaultVisibility(),
      `${ctx}/${id}`
    );
  }
});

test("setPanelVisible: garbage prev blob starts fresh, does not throw", () => {
  const next = setPanelVisible("not json", "in-game-arena", "next", false);
  assert.strictEqual(readVisibility(next)["in-game-arena"].next, false);
});

test("isPanelVisible: per-context resolve, fail-open on unknowns", () => {
  const blob = setPanelVisible("{}", "in-game-aram", "item-build", false);
  assert.strictEqual(isPanelVisible(blob, "in-game-aram", "item-build"), false);
  assert.strictEqual(isPanelVisible(blob, "in-game-sr", "item-build"), true);
  assert.strictEqual(isPanelVisible(blob, "out-game", "item-build"), true);
  assert.strictEqual(isPanelVisible(blob, "in-game-aram", "bogus"), true);
  assert.strictEqual(isPanelVisible(blob, "in-game", "item-build"), true);
});

test("round-trip: several contexts stay independent through serialize", () => {
  let blob = "{}";
  blob = setPanelVisible(blob, "in-game-sr", "minimap", false);
  blob = setPanelVisible(blob, "in-game-aram", "minimap", false);
  blob = setPanelVisible(blob, "out-game", "coach-decisions", false);
  const v = readVisibility(serializeVisibility(readVisibility(blob)));
  assert.strictEqual(v["in-game-sr"].minimap, false);
  assert.strictEqual(v["in-game-aram"].minimap, false);
  assert.strictEqual(v["in-game-arena"].minimap, true);
  assert.strictEqual(v["in-game-tft"].minimap, true);
  assert.strictEqual(v["out-game"]["coach-decisions"], false);
});

// -- tab UI state (pure half) ------------------------------------------------

test("TABS: one tab per context, in CONTEXTS order, ASCII labels", () => {
  assert.deepStrictEqual(
    TABS.map((t) => t.context),
    [...CONTEXTS]
  );
  assert.deepStrictEqual(
    TABS.map((t) => t.label),
    ["SR", "ARAM", "ARENA", "TFT", "OUT-OF-GAME"]
  );
  for (const t of TABS) {
    assert.match(t.label, /^[\x20-\x7e]+$/, t.context);
  }
});

test("normalizeTab: valid stored tab is kept (toggle persistence)", () => {
  for (const ctx of CONTEXTS) {
    assert.strictEqual(normalizeTab(ctx, "out-game"), ctx);
  }
  assert.strictEqual(normalizeTab(" in-game-aram ", "out-game"), "in-game-aram");
});

test("normalizeTab: junk falls back to the given context, then to SR", () => {
  for (const raw of [null, undefined, "", "junk", 42, "in-game"]) {
    assert.strictEqual(normalizeTab(raw, "in-game-tft"), "in-game-tft");
  }
  // a junk fallback resolves to the SR tab (never throws, never invalid)
  assert.strictEqual(normalizeTab("junk", "also-junk"), "in-game-sr");
  assert.strictEqual(normalizeTab(null, null), "in-game-sr");
});
