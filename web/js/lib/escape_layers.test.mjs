// web/js/lib/escape_layers.test.mjs
//
// RM-1070 - the pure topmost-layer choice behind the one Escape
// dispatcher. Run with `node --test`. The DOM half (root-level z-index,
// tree order, the capture listener) is pinned in headless Chromium by
// tests/snapshot_panels/test_escape_one_action.py.

import test from "node:test";
import assert from "node:assert";

import { pickTopmost, registerEscapeLayer } from "./escape_layers.js";

// Nodes are tree positions; `follows(a, b)` = a comes after b.
const follows = (a, b) => a > b;
const e = (name, z, node) => ({ layer: { name }, z, node });

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

test("registerEscapeLayer: no document (node) binds nothing and never throws", () => {
  assert.doesNotThrow(() => registerEscapeLayer({
    name: "t", el: () => null, isOpen: () => false, close: () => {},
  }));
});
