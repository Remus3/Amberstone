// web/js/lib/escape_layers.test.mjs
//
// RM-1070 - the pure topmost-layer choice behind the one Escape
// dispatcher, and (RM-1074) the stacking-context rules it ranks by. Run
// with `node --test`. The DOM half (computed styles, tree order, the top
// layer, the capture listener) is pinned in headless Chromium against
// elementsFromPoint by tests/snapshot_panels/test_escape_one_action.py.

import test from "node:test";
import assert from "node:assert";

import {
  compareStacking, pickTopmost, registerEscapeLayer, stackingZ,
} from "./escape_layers.js";

// Nodes are tree positions; `follows(a, b)` = a comes after b.
const follows = (a, b) => a > b;
// A layer alone in the root context: its path is itself at z.
const e = (name, z, node) => ({ layer: { name }, node, path: [{ el: node, z }] });

test("pickTopmost: nothing open picks nothing", () => {
  assert.strictEqual(pickTopmost([], follows), null);
});

test("pickTopmost: the highest z wins whatever the registration order", () => {
  // Registration order of the page: digest, draft-elo, modal, menu, picker.
  const open = [e("task-modal", 200, 3), e("view-menu", 9100, 1)];
  assert.strictEqual(pickTopmost(open, follows).layer.name, "view-menu");
  open.reverse();
  assert.strictEqual(pickTopmost(open, follows).layer.name, "view-menu");
});

test("pickTopmost: equal z goes to the later node in tree order", () => {
  const open = [e("later", 9100, 7), e("earlier", 9100, 2)];
  assert.strictEqual(pickTopmost(open, follows).layer.name, "later");
  open.reverse();
  assert.strictEqual(pickTopmost(open, follows).layer.name, "later");
});

test("pickTopmost: a layer with no node ranks at z 0", () => {
  const open = [e("nodeless", 0, null), e("modal", 200, 3)];
  assert.strictEqual(pickTopmost(open, () => false).layer.name, "modal");
});

// RM-1074 - the stacking-context creation rules and the path comparison.
// Computed styles are plain objects holding only the keys a case sets.
const FLEX = { display: "flex" };
const BLOCK = { display: "block" };

test("stackingZ: positioned z-index, fixed and sticky create a context", () => {
  assert.strictEqual(stackingZ({ position: "static", zIndex: "auto" }, BLOCK), null);
  assert.strictEqual(stackingZ({ position: "relative", zIndex: "auto" }, BLOCK), null);
  assert.strictEqual(stackingZ({ position: "absolute", zIndex: "5" }, BLOCK), 5);
  assert.strictEqual(stackingZ({ position: "relative", zIndex: "-2" }, BLOCK), -2);
  assert.strictEqual(stackingZ({ position: "fixed", zIndex: "auto" }, BLOCK), 0);
  assert.strictEqual(stackingZ({ position: "sticky", zIndex: "auto" }, BLOCK), 0);
});

test("stackingZ: z-index on a static flex or grid item counts, elsewhere not", () => {
  assert.strictEqual(stackingZ({ position: "static", zIndex: "60" }, FLEX), 60);
  assert.strictEqual(stackingZ({ position: "static", zIndex: "60" }, { display: "inline-grid" }), 60);
  assert.strictEqual(stackingZ({ position: "static", zIndex: "60" }, BLOCK), null);
  assert.strictEqual(stackingZ({ position: "static", zIndex: "60" }, null), null);
});

test("stackingZ: non-position creators paint at their z, 0 when it does not apply", () => {
  const made = [
    { transform: "matrix(1, 0, 0, 1, 0, 0)" }, { translate: "1px" },
    { rotate: "1deg" }, { scale: "2" }, { opacity: "0.99" },
    { filter: "blur(1px)" }, { backdropFilter: "blur(1px)" },
    { perspective: "10px" }, { clipPath: "inset(0px)" },
    { maskImage: "linear-gradient(red, red)" }, { mixBlendMode: "multiply" },
    { isolation: "isolate" }, { contain: "paint" }, { contain: "strict" },
    { contain: "layout" }, { willChange: "transform" },
    { willChange: "scroll-position, opacity" },
  ];
  for (const extra of made) {
    const cs = { position: "static", zIndex: "auto", ...extra };
    assert.strictEqual(stackingZ(cs, BLOCK), 0, JSON.stringify(extra));
    assert.strictEqual(stackingZ({ ...cs, zIndex: "7" }, BLOCK), 0, JSON.stringify(extra));
    assert.strictEqual(stackingZ({ ...cs, zIndex: "7" }, FLEX), 7, JSON.stringify(extra));
  }
  const inert = [
    { transform: "none" }, { opacity: "1" }, { filter: "none" },
    { mixBlendMode: "normal" }, { isolation: "auto" }, { contain: "size" },
    { containerType: "size" }, { containerType: "inline-size" },
    { willChange: "auto" },
    { willChange: "scroll-position" },
  ];
  for (const extra of inert) {
    const cs = { position: "static", zIndex: "auto", ...extra };
    assert.strictEqual(stackingZ(cs, BLOCK), null, JSON.stringify(extra));
  }
});

// Paths are [{ el, z }] outermost first; els are tree positions.
const s = (node, ...path) => ({ node, path: path.map(([el, z]) => ({ el, z })) });

test("compareStacking: a z-index trapped in a z 0 context loses to a z 50 layer", () => {
  // wrapper (transform, el 1) > child (z 9999, el 2); sibling (z 50, el 3).
  const trapped = s(2, [1, 0], [2, 9999]);
  const sibling = s(3, [3, 50]);
  assert.ok(compareStacking(sibling, trapped, follows) > 0);
  assert.ok(compareStacking(trapped, sibling, follows) < 0);
  // A sibling EARLIER in tree order still wins on z.
  assert.ok(compareStacking(s(0, [0, 50]), trapped, follows) > 0);
});

test("compareStacking: an equal-z context goes to tree order", () => {
  assert.ok(compareStacking(s(5, [4, 0], [5, 1]), s(3, [3, 0]), follows) > 0);
  assert.ok(compareStacking(s(5, [2, 0], [5, 1]), s(3, [3, 0]), follows) < 0);
});

test("compareStacking: inside one context the inner z decides", () => {
  const low = s(3, [1, 0], [3, 10]);
  const high = s(2, [1, 0], [2, 20]);
  assert.ok(compareStacking(high, low, follows) > 0);
  assert.ok(compareStacking(low, high, follows) < 0);
});

test("compareStacking: a layer inside another layer's context paints over it", () => {
  const outer = s(1, [1, 5]);
  const inner = s(2, [1, 5], [2, 1]);
  assert.ok(compareStacking(inner, outer, follows) > 0);
  assert.ok(compareStacking(outer, inner, follows) < 0);
});

test("compareStacking: the top layer ranks over any z-index", () => {
  assert.ok(compareStacking(s(1, [1, Infinity]), s(9, [9, 2147483647]), follows) > 0);
});

test("pickTopmost: picks by stacking path, not by the deepest z-index", () => {
  const open = [
    { layer: { name: "trapped" }, ...s(2, [1, 0], [2, 9999]) },
    { layer: { name: "sibling" }, ...s(3, [3, 50]) },
  ];
  assert.strictEqual(pickTopmost(open, follows).layer.name, "sibling");
  open.reverse();
  assert.strictEqual(pickTopmost(open, follows).layer.name, "sibling");
});

test("registerEscapeLayer: no document (node) binds nothing and never throws", () => {
  assert.doesNotThrow(() => registerEscapeLayer({
    name: "t", el: () => null, isOpen: () => false, close: () => {},
  }));
});
