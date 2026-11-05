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
  compareStacking, dismissStrandedLayers, openEntries, pickTopmost,
  registerEscapeLayer, stackingZ, strandedLayers,
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
    // RM-1075: measured in headless Chromium 147.
    { viewTransitionName: "u48" }, { contentVisibility: "auto" },
    { contentVisibility: "hidden" }, { webkitBoxReflect: "below" },
    { offsetPath: 'path("M0,0")' },
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
    { viewTransitionName: "none" }, { contentVisibility: "visible" },
    { webkitBoxReflect: "none" }, { offsetPath: "none" },
  ];
  for (const extra of inert) {
    const cs = { position: "static", zIndex: "auto", ...extra };
    assert.strictEqual(stackingZ(cs, BLOCK), null, JSON.stringify(extra));
  }
});

test("stackingZ: a display:contents element has no box and makes no context", () => {
  for (const extra of [
    { opacity: "0.5" }, { transform: "matrix(1, 0, 0, 1, 0, 0)" },
    { position: "fixed" }, { isolation: "isolate" },
    { position: "relative", zIndex: "9" },
  ]) {
    const cs = { display: "contents", position: "static", zIndex: "auto", ...extra };
    assert.strictEqual(stackingZ(cs, BLOCK), null, JSON.stringify(extra));
    assert.strictEqual(stackingZ({ ...cs, zIndex: "9" }, FLEX), null, JSON.stringify(extra));
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

// RM-1075: top-layer entries carry their open stamp `seq`.
const t = (node, seq) => ({ node, path: [seq === undefined
  ? { el: node, z: Infinity } : { el: node, z: Infinity, seq }] });

test("compareStacking: two top-layer layers go to the one opened last", () => {
  // Tree order 1 < 2; 2 was opened first (seq 4), 1 second (seq 9).
  assert.ok(compareStacking(t(1, 9), t(2, 4), follows) > 0);
  assert.ok(compareStacking(t(2, 4), t(1, 9), follows) < 0);
});

test("compareStacking: a stamped top-layer layer beats an unstamped one", () => {
  // The unstamped one was opened before the listener bound, so earlier.
  assert.ok(compareStacking(t(1, 1), t(2), follows) > 0);
  assert.ok(compareStacking(t(2), t(1, 1), follows) < 0);
});

test("compareStacking: two unstamped top-layer layers fall back to tree order", () => {
  assert.ok(compareStacking(t(2), t(1), follows) > 0);
  assert.ok(compareStacking(t(1), t(2), follows) < 0);
});

test("compareStacking: open stamps never outrank a z difference", () => {
  // seq is only ever set on top-layer entries; a stray one below is inert.
  const low = { node: 2, path: [{ el: 2, z: 10, seq: 99 }] };
  const high = { node: 1, path: [{ el: 1, z: 20 }] };
  assert.ok(compareStacking(high, low, follows) > 0);
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

// RM-1365: a layer open by class but rendered nowhere takes no press.
const lay = (name, open, node) => ({
  name, el: () => node, isOpen: () => open, close: () => {},
});
const names = (entries) => entries.map((x) => x.layer.name);

test("openEntries: an open layer with no box takes no press", () => {
  const boxes = new Set(["shown"]);
  const got = openEntries(
    [lay("stranded", true, "hidden-node"), lay("view", true, "shown")],
    (n) => boxes.has(n),
  );
  assert.deepStrictEqual(names(got), ["view"]);
});

test("openEntries: a rendered open layer still takes part, a closed one never", () => {
  const got = openEntries(
    [lay("closed", false, "a"), lay("open", true, "b")],
    () => true,
  );
  assert.deepStrictEqual(names(got), ["open"]);
  assert.strictEqual(got[0].node, "b");
});

test("openEntries: no element keeps the old z 0 entry; hasBox is not asked", () => {
  let asked = 0;
  const got = openEntries([lay("bare", true, null)], () => { asked += 1; return false; });
  assert.deepStrictEqual(names(got), ["bare"]);
  assert.strictEqual(asked, 0);
});

test("openEntries: an isOpen that throws reads as closed", () => {
  const bad = { name: "bad", el: () => "x", isOpen: () => { throw new Error("x"); } };
  assert.deepStrictEqual(names(openEntries([bad], () => true)), []);
});

test("openEntries: only stranded layers open leaves nothing to pick", () => {
  const got = openEntries([lay("stranded", true, "n")], () => false);
  assert.strictEqual(pickTopmost(got.map((x) => ({ ...x, path: [] })), (a, b) => a > b), null);
});

// RM-1368: a view change dismisses the layers it left open with no box.
test("strandedLayers: only an open layer with an unrendered element", () => {
  const boxes = new Set(["shown"]);
  const got = strandedLayers(
    [
      lay("stranded", true, "hidden-node"),
      lay("rendered", true, "shown"),
      lay("closed", false, "hidden-node"),
      lay("bare", true, null),
    ],
    (n) => boxes.has(n),
  );
  assert.deepStrictEqual(got.map((l) => l.name), ["stranded"]);
});

test("strandedLayers: an isOpen that throws reads as closed", () => {
  const bad = { name: "bad", el: () => "x", isOpen: () => { throw new Error("x"); } };
  assert.deepStrictEqual(strandedLayers([bad], () => false), []);
});

test("strandedLayers: no element means hasBox is never asked", () => {
  let asked = 0;
  strandedLayers([lay("bare", true, null)], () => { asked += 1; return false; });
  assert.strictEqual(asked, 0);
});

test("dismissStrandedLayers: no document (node) dismisses nothing and never throws", () => {
  assert.deepStrictEqual(dismissStrandedLayers(), []);
});

test("registerEscapeLayer: no document (node) binds nothing and never throws", () => {
  assert.doesNotThrow(() => registerEscapeLayer({
    name: "t", el: () => null, isOpen: () => false, close: () => {},
  }));
});
