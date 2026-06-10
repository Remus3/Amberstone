// rc-shell/test/active_indicator.test.js
//
// node:test for the PURE Phase 4 ACTIVE-indicator module (no electron). The
// overlay needs an on-screen cue for "interactive right now" vs the passive
// click-through HUD - these are the strings main.js injects to draw it.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const ind = require("../src/active_indicator");

// Same stub shape as drag_region.test.js, extended with a Set-backed classList
// so the set/unset JS can be exercised behaviorally without a browser.
function makeFakeDocument() {
  const children = [];
  const classes = new Set();
  return {
    children,
    classes,
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
      classList: {
        add(c) {
          classes.add(c);
        },
        remove(c) {
          classes.delete(c);
        },
        contains(c) {
          return classes.has(c);
        },
      },
    },
  };
}

test("constants: indicator id + active class are non-empty strings", () => {
  assert.ok(typeof ind.INDICATOR_ID === "string" && ind.INDICATOR_ID.length > 0);
  assert.ok(typeof ind.ACTIVE_CLASS === "string" && ind.ACTIVE_CLASS.length > 0);
  assert.strictEqual(ind.INDICATOR_ID, "rc-shell-active-indicator");
  assert.strictEqual(ind.ACTIVE_CLASS, "rc-shell-active");
});

test("activeIndicatorCSS: id selector + never eats clicks", () => {
  const css = ind.activeIndicatorCSS();
  assert.ok(css.includes("#" + ind.INDICATOR_ID), css);
  assert.ok(css.includes("pointer-events: none"), css);
  assert.ok(css.includes("position: fixed"), css);
});

test("activeIndicatorCSS: hidden by default, visible under html.rc-shell-active", () => {
  const css = ind.activeIndicatorCSS();
  assert.ok(css.includes("opacity: 0"), css);
  assert.ok(css.includes("html." + ind.ACTIVE_CLASS + " #" + ind.INDICATOR_ID), css);
  assert.ok(css.includes("opacity: 1"), css);
});

test("activeIndicatorCSS: border glow only - no animation keyframes (perf rule)", () => {
  const css = ind.activeIndicatorCSS();
  assert.ok(css.includes("border"), css);
  assert.ok(css.includes("inset") && css.includes("box-shadow"), css);
  assert.ok(!css.includes("@keyframes"), css);
});

test("activeIndicatorMountJS: syntactically valid JS", () => {
  assert.doesNotThrow(() => new Function(ind.activeIndicatorMountJS()));
});

test("activeIndicatorMountJS: behaviorally idempotent against a document stub", () => {
  const doc = makeFakeDocument();
  const run = new Function("document", ind.activeIndicatorMountJS());
  run(doc);
  run(doc);
  assert.strictEqual(doc.children.length, 1, "exactly one indicator mounted");
  assert.strictEqual(doc.children[0].id, ind.INDICATOR_ID);
  assert.strictEqual(doc.children[0].tagName, "div");
});

test("activeIndicatorSetJS: syntactically valid JS for both states", () => {
  assert.doesNotThrow(() => new Function(ind.activeIndicatorSetJS(true)));
  assert.doesNotThrow(() => new Function(ind.activeIndicatorSetJS(false)));
});

test("activeIndicatorSetJS: true adds the class, false removes it", () => {
  const doc = makeFakeDocument();
  new Function("document", ind.activeIndicatorSetJS(true))(doc);
  assert.ok(doc.classes.has(ind.ACTIVE_CLASS), "class added on true");
  new Function("document", ind.activeIndicatorSetJS(true))(doc);
  assert.strictEqual(doc.classes.size, 1, "re-apply is idempotent");
  new Function("document", ind.activeIndicatorSetJS(false))(doc);
  assert.ok(!doc.classes.has(ind.ACTIVE_CLASS), "class removed on false");
});

test("activeIndicatorSetJS: truthy/falsy inputs coerce to a serialized boolean", () => {
  const doc = makeFakeDocument();
  new Function("document", ind.activeIndicatorSetJS(1))(doc);
  assert.ok(doc.classes.has(ind.ACTIVE_CLASS), "truthy coerces to true");
  new Function("document", ind.activeIndicatorSetJS(undefined))(doc);
  assert.ok(!doc.classes.has(ind.ACTIVE_CLASS), "falsy coerces to false");
});
