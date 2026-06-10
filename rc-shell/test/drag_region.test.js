// rc-shell/test/drag_region.test.js
//
// node:test for the PURE drag-region module (no electron). The companion is
// frameless and the loaded page is the remote RC dashboard, so the drag strip
// must be injected by the main process - these strings are what gets injected.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const drag = require("../src/drag_region");

// Minimal document stub for behaviorally exercising the mount JS without a
// browser: getElementById resolves against what documentElement collected, so
// a second mount sees the first mount's node (the idempotence path).
function makeFakeDocument() {
  const children = [];
  return {
    children,
    getElementById(id) {
      return children.find((c) => c.id === id) || null;
    },
    createElement(tag) {
      return { tagName: tag, id: "" };
    },
    documentElement: {
      appendChild(node) {
        children.push(node);
        return node;
      },
    },
  };
}

test("DRAG_REGION_DEFAULTS: shape", () => {
  const d = drag.DRAG_REGION_DEFAULTS;
  assert.ok(typeof d.id === "string" && d.id.length > 0, "id non-empty string");
  assert.ok(typeof d.height === "number" && d.height >= 16, "height >= 16");
  assert.ok(typeof d.zIndex === "number", "zIndex number");
});

test("dragRegionCSS: drag rule + id selector + fixed strip geometry", () => {
  const css = drag.dragRegionCSS();
  assert.ok(css.includes("-webkit-app-region: drag"), css);
  assert.ok(css.includes("#" + drag.DRAG_REGION_DEFAULTS.id), css);
  assert.ok(css.includes(drag.DRAG_REGION_DEFAULTS.height + "px"), css);
  assert.ok(css.includes("position: fixed"), css);
  assert.ok(css.includes(String(drag.DRAG_REGION_DEFAULTS.zIndex)), css);
});

test("dragRegionCSS: no-drag escape hatch rule for nested controls", () => {
  const css = drag.dragRegionCSS();
  assert.ok(css.includes(".rc-shell-no-drag"), css);
  assert.ok(css.includes("-webkit-app-region: no-drag"), css);
});

test("dragRegionCSS: override honored, defaults object untouched", () => {
  const css = drag.dragRegionCSS({ height: 32 });
  assert.ok(css.includes("32px"), css);
  assert.ok(!css.includes("24px"), css);
  // partial override: unspecified keys still come from the defaults.
  assert.ok(css.includes("#" + drag.DRAG_REGION_DEFAULTS.id), css);
  assert.strictEqual(drag.DRAG_REGION_DEFAULTS.height, 24, "defaults mutated");
});

test("dragRegionMountJS: idempotence guard + div + documentElement target", () => {
  const js = drag.dragRegionMountJS();
  assert.ok(js.includes("getElementById"), js);
  assert.ok(js.includes(drag.DRAG_REGION_DEFAULTS.id), js);
  assert.ok(js.includes("createElement"), js);
  assert.ok(js.includes("documentElement"), js);
});

test("dragRegionMountJS: syntactically valid JS", () => {
  assert.doesNotThrow(() => new Function(drag.dragRegionMountJS()));
  assert.doesNotThrow(() => new Function(drag.dragRegionMountJS({ id: "x-id" })));
});

test("dragRegionMountJS: behaviorally idempotent against a document stub", () => {
  const doc = makeFakeDocument();
  const run = new Function("document", drag.dragRegionMountJS());
  run(doc);
  run(doc);
  assert.strictEqual(doc.children.length, 1, "exactly one strip mounted");
  assert.strictEqual(doc.children[0].id, drag.DRAG_REGION_DEFAULTS.id);
  assert.strictEqual(doc.children[0].tagName, "div");
});

test("dragRegionMountJS: id override flows into the mounted node", () => {
  const doc = makeFakeDocument();
  new Function("document", drag.dragRegionMountJS({ id: "custom-strip" }))(doc);
  assert.strictEqual(doc.children[0].id, "custom-strip");
  assert.strictEqual(drag.DRAG_REGION_DEFAULTS.id, "rc-shell-drag-region");
});
