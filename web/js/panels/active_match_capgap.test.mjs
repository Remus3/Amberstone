// web/js/panels/active_match_capgap.test.mjs
//
// L4 capability-gap chip (active-match twin of the item-633 champ-select
// chip) - pure render-helper tests. Run with `node --test`.
//
// Only the PURE render helper (renderCapabilityGapChip) is covered here. The
// fetch/cache host (_amRenderCapabilityGap) needs a live document + the
// /api/ds-preview (or ?ui_mock=1) data path and is exercised on the page at
// runtime. These pin the chip markup so a gap verdict always renders the GAP
// badge + mapped axis label + verdict, and a falsy payload always hides.

import test from "node:test";
import assert from "node:assert";

import { renderCapabilityGapChip } from "./active_match.js";

// Minimal fake element: a plain object with settable hidden / dataset /
// innerHTML. No real DOM - the helper only touches those three properties.
function fakeBlock() {
  return { hidden: undefined, dataset: {}, innerHTML: "" };
}

const ZONE_CONTROL_PAYLOAD = {
  applies: true,
  my_champion: "Jinx",
  mode: "sr",
  top_gap: "zone_control",
  verdict: "Enemy comp controls terrain (3 zoners); respect walls and chokes, do not get caged or cut off.",
  gaps: [
    { axis: "zone_control", demand_count: 3, severity: 3.0, detail: "Enemy comp controls terrain (3 zoners); respect walls and chokes, do not get caged or cut off." },
  ],
};

test("renderCapabilityGapChip: zone_control payload renders the GAP chip", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, ZONE_CONTROL_PAYLOAD);
  assert.strictEqual(block.hidden, false);
  assert.strictEqual(block.dataset.capgapAxis, "zone_control");
  assert.ok(block.innerHTML.includes("GAP"), "badge text present");
  assert.ok(block.innerHTML.includes("Anti-zone"), "zone_control mapped to Anti-zone");
  assert.ok(
    block.innerHTML.includes("Enemy comp controls terrain"),
    "verdict text present",
  );
});

test("renderCapabilityGapChip: objective_damage maps to Anti-siege", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, {
    applies: true,
    top_gap: "objective_damage",
    verdict: "Enemy out-sieges you; contest plates and prioritize objective damage.",
  });
  assert.strictEqual(block.hidden, false);
  assert.strictEqual(block.dataset.capgapAxis, "objective_damage");
  assert.ok(block.innerHTML.includes("Anti-siege"));
});

test("renderCapabilityGapChip: falsy payload hides the chip", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, null);
  assert.strictEqual(block.hidden, true);
  renderCapabilityGapChip(block, false);
  assert.strictEqual(block.hidden, true);
});

test("renderCapabilityGapChip: applies:false hides the chip", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, { applies: false, top_gap: "zone_control" });
  assert.strictEqual(block.hidden, true);
});

test("renderCapabilityGapChip: unmapped axis falls back to a spaced label", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, { applies: true, top_gap: "burst_threat", verdict: "x" });
  assert.strictEqual(block.dataset.capgapAxis, "burst_threat");
  assert.ok(block.innerHTML.includes("burst threat"));
});

test("renderCapabilityGapChip: escapes HTML in the verdict", () => {
  const block = fakeBlock();
  renderCapabilityGapChip(block, { applies: true, top_gap: "poke", verdict: "<script>x</script>" });
  assert.ok(!block.innerHTML.includes("<script>"), "raw script tag must be escaped");
  assert.ok(block.innerHTML.includes("&lt;script&gt;"));
});
