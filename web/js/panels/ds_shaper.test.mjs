// web/js/panels/ds_shaper.test.mjs
//
// Interactive Item Shaper 3-knob strip (OQ14) - render + knob-clamp + reset +
// pure-query tests. Run with `node --test` (same runner + node:test/node:assert
// import style as active_match_capgap.test.mjs).
//
// renderShaperStrip builds real DOM (createElement / appendChild /
// querySelectorAll / click), so this file installs a MINIMAL globalThis.document
// shim + a fetch mock (jsdom is not a repo dependency). The shim implements
// exactly the surface ds_shaper.js touches: element props (className /
// textContent / type / dataset), addEventListener('click'), appendChild /
// removeChild / replaceChildren / firstChild, click() dispatch, and a
// class-selector querySelectorAll. computeShaperQuery + resetShaper are pure and
// exercised directly.

import test from "node:test";
import assert from "node:assert";

// ----- minimal DOM shim ---------------------------------------------------
class FakeEl {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.className = "";
    this.textContent = "";
    this.type = "";
    this.dataset = {};
    this.children = [];
    this._listeners = {};
    this._innerHTML = "";
  }
  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }
  set innerHTML(v) {
    this._innerHTML = String(v);
    this.children = [];
  }
  get innerHTML() {
    return this._innerHTML;
  }
  appendChild(child) {
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i >= 0) this.children.splice(i, 1);
    return child;
  }
  replaceChildren() {
    this.children = [];
  }
  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  }
  click() {
    const ev = { stopPropagation() {}, preventDefault() {} };
    (this._listeners.click || []).forEach((fn) => fn(ev));
  }
  // Depth-first collect elements whose className contains the requested class.
  querySelectorAll(sel) {
    const want = String(sel).replace(/^\./, "");
    const out = [];
    const walk = (node) => {
      node.children.forEach((c) => {
        const classes = String(c.className || "").split(/\s+/);
        if (classes.indexOf(want) >= 0) out.push(c);
        walk(c);
      });
    };
    walk(this);
    return out;
  }
}

function installDom() {
  globalThis.document = {
    createElement: (tag) => new FakeEl(tag),
  };
}

// Canned ok payload so _refresh (debounced fetch) never throws.
const OK_PAYLOAD = {
  ok: true,
  champion: "Jinx",
  archetype_source: "carry",
  knobs: { damage: 0, survivability: 0, utility: 0 },
  baseline: { damage: 0.65, survivability: 0.20, utility: 0.15 },
  shaped: { damage: 0.68, survivability: 0.19, utility: 0.13 },
  baseline_pct: { damage: 65, survivability: 20, utility: 15 },
  shaped_pct: { damage: 68, survivability: 19, utility: 13 },
  elapsed_ms: 3,
};

function installFetch() {
  globalThis.fetch = () =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(OK_PAYLOAD),
      clone() { return this; },
    });
}

installDom();
installFetch();

// Import AFTER the shim is live (the module reads escHtml + dedupFetch at load,
// neither of which touches document at import time; the fetch mock is only used
// by the debounced _refresh, which the tests do not await).
const {
  renderShaperStrip,
  resetShaper,
  computeShaperQuery,
  _shaperState,
} = await import("./ds_shaper.js");

function newRow() {
  return new FakeEl("div");
}

test("computeShaperQuery: pure query string with URL-encoded champion", () => {
  assert.strictEqual(
    computeShaperQuery("Jinx", { damage: 1, survivability: -2, utility: 0 }),
    "champion=Jinx&damage=1&survivability=-2&utility=0",
  );
  // A champion needing encoding (space) is percent-encoded.
  assert.strictEqual(
    computeShaperQuery("Dr Mundo", { damage: 0, survivability: 0, utility: 0 }),
    "champion=Dr%20Mundo&damage=0&survivability=0&utility=0",
  );
});

test("renderShaperStrip builds exactly 3 axes, each 2 btns + 1 val", () => {
  resetShaper();
  const row = newRow();
  renderShaperStrip(row, "Jinx", "sr");
  const axes = row.querySelectorAll(".bm-shaper-axis");
  assert.strictEqual(axes.length, 3, "three axes");
  axes.forEach((ax) => {
    const btns = ax.querySelectorAll(".bm-shaper-btn");
    const vals = ax.querySelectorAll(".bm-shaper-val");
    assert.strictEqual(btns.length, 2, "two buttons per axis");
    assert.strictEqual(vals.length, 1, "one value per axis");
  });
  // Exactly one strip + one out area under the row.
  assert.strictEqual(row.querySelectorAll(".bm-shaper-strip").length, 1);
  assert.strictEqual(row.querySelectorAll(".bm-shaper-out").length, 1);
});

test("plus button increments and clamps at +2", () => {
  resetShaper();
  const row = newRow();
  renderShaperStrip(row, "Jinx", "sr");
  // First axis = damage. Buttons are [minus, plus] in DOM order.
  const dmgAxis = row.querySelectorAll(".bm-shaper-axis")[0];
  const btns = dmgAxis.querySelectorAll(".bm-shaper-btn");
  const plus = btns[1];
  const val = dmgAxis.querySelectorAll(".bm-shaper-val")[0];
  plus.click();
  assert.strictEqual(_shaperState().damage, 1);
  plus.click();
  assert.strictEqual(_shaperState().damage, 2);
  plus.click(); // clamp
  assert.strictEqual(_shaperState().damage, 2);
  assert.strictEqual(val.textContent, "2");
});

test("minus button decrements and clamps at -2", () => {
  resetShaper();
  const row = newRow();
  renderShaperStrip(row, "Jinx", "sr");
  const dmgAxis = row.querySelectorAll(".bm-shaper-axis")[0];
  const btns = dmgAxis.querySelectorAll(".bm-shaper-btn");
  const minus = btns[0];
  const val = dmgAxis.querySelectorAll(".bm-shaper-val")[0];
  minus.click();
  minus.click();
  minus.click(); // clamp at -2
  assert.strictEqual(_shaperState().damage, -2);
  assert.strictEqual(val.textContent, "-2");
});

test("resetShaper zeroes state; re-render shows 0s", () => {
  resetShaper();
  const row = newRow();
  renderShaperStrip(row, "Jinx", "sr");
  const dmgAxis = row.querySelectorAll(".bm-shaper-axis")[0];
  const plus = dmgAxis.querySelectorAll(".bm-shaper-btn")[1];
  plus.click();
  plus.click();
  assert.strictEqual(_shaperState().damage, 2);

  resetShaper();
  const st = _shaperState();
  assert.strictEqual(st.damage, 0);
  assert.strictEqual(st.survivability, 0);
  assert.strictEqual(st.utility, 0);
  assert.strictEqual(st.champion, null);

  // Re-render (champion changed from null-tracked back to Jinx -> stays 0).
  const row2 = newRow();
  renderShaperStrip(row2, "Jinx", "sr");
  row2.querySelectorAll(".bm-shaper-axis").forEach((ax) => {
    assert.strictEqual(ax.querySelectorAll(".bm-shaper-val")[0].textContent, "0");
  });
});

test("champion change snaps knobs back to zero", () => {
  resetShaper();
  const row = newRow();
  renderShaperStrip(row, "Jinx", "sr");
  const plus = row.querySelectorAll(".bm-shaper-axis")[0]
    .querySelectorAll(".bm-shaper-btn")[1];
  plus.click();
  plus.click();
  assert.strictEqual(_shaperState().damage, 2);

  // New champion (new match) -> reset to 0 without an explicit resetShaper.
  const row2 = newRow();
  renderShaperStrip(row2, "Caitlyn", "sr");
  assert.strictEqual(_shaperState().damage, 0);
  assert.strictEqual(_shaperState().champion, "Caitlyn");
});
