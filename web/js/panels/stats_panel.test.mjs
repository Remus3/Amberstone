// web/js/panels/stats_panel.test.mjs
//
// Stats panel (You-vs-Avg) default-role detection - pure-logic tests. Run with
// `node --test`. The DOM render (renderStatsPanel) is exercised by the rendered
// Chromium harness; these pin _detectRole: the SR assigned-lane mapping (Live
// Client position on the is_active player), the ARAM/no-lane champion-class
// fallback (Kai'Sa -> bot, not a hardcoded MID), and the honest null when
// neither resolves. tagsLookup is injected so no real fetch runs.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./stats_panel.js";

const { _detectRole } = __test;

const mkPos = (pos) => ({ players: [{ position: pos, is_active: true }] });

test("_detectRole maps the SR assigned lane from the is_active player", () => {
  const lc = {
    players: [
      { position: "MIDDLE", team: "ORDER", is_active: false },
      { position: "BOTTOM", team: "ORDER", is_active: true },
    ],
    champion: "Kaisa",
  };
  // BOTTOM lane wins over the champion class; the is_active row is the one read.
  assert.strictEqual(_detectRole(lc), "bot");
});

test("_detectRole maps every Live Client position to its compare role", () => {
  assert.strictEqual(_detectRole(mkPos("TOP")), "top");
  assert.strictEqual(_detectRole(mkPos("JUNGLE")), "jungle");
  assert.strictEqual(_detectRole(mkPos("MIDDLE")), "mid");
  assert.strictEqual(_detectRole(mkPos("BOTTOM")), "bot");
  assert.strictEqual(_detectRole(mkPos("UTILITY")), "support");
});

test("_detectRole is case-insensitive on the position string", () => {
  assert.strictEqual(_detectRole(mkPos("bottom")), "bot");
});

test("_detectRole falls back to the champion class when there is no lane (ARAM)", () => {
  const lc = { players: [{ position: "", is_active: true }], champion: "Kaisa" };
  const fakeTags = (name) =>
    name === "Kaisa" ? { primary: "Marksman", tags: ["Marksman", "Assassin"] } : null;
  // Kai'Sa is a Marksman -> BOT, not the old hardcoded MID.
  assert.strictEqual(_detectRole(lc, fakeTags), "bot");
});

test("_detectRole uses tags[0] when primary is absent", () => {
  const lc = { players: [], champion: "Lux" };
  const fakeTags = () => ({ tags: ["Mage", "Support"] });
  assert.strictEqual(_detectRole(lc, fakeTags), "mid");
});

test("_detectRole maps each known champion class", () => {
  const cls = (c) => _detectRole({ players: [], champion: "X" }, () => ({ primary: c }));
  assert.strictEqual(cls("Marksman"), "bot");
  assert.strictEqual(cls("Support"), "support");
  assert.strictEqual(cls("Mage"), "mid");
  assert.strictEqual(cls("Assassin"), "mid");
  assert.strictEqual(cls("Tank"), "top");
  assert.strictEqual(cls("Fighter"), "top");
});

test("_detectRole returns null when neither lane nor class resolves", () => {
  assert.strictEqual(_detectRole({ players: [], champion: "" }, () => null), null);
  assert.strictEqual(_detectRole({ players: [{ position: "NONE", is_active: true }], champion: "X" }, () => null), null);
  assert.strictEqual(_detectRole(null), null);
  assert.strictEqual(_detectRole({}), null);
});
