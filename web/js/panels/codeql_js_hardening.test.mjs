// web/js/panels/codeql_js_hardening.test.mjs
//
// PUBREPO 1g (CodeQL, JavaScript half): regression pins for the escaping /
// sanitising fixes behind the open js/* code-scanning alerts. Run with
// `node --test` (gated by tests/test_web_panels_node_suite.py, which globs
// every web/js/panels/*.test.mjs).
//
// Each block names the alert class it pins. The payloads are hostile on
// purpose; the "well-formed" cases pin that ordinary data renders exactly as
// it did before the fix.

import test from "node:test";
import assert from "node:assert";

// ----- minimal DOM shim (import-time surface only) ------------------------
// duration_winrate.js calls document.addEventListener at load; items_index.js
// starts a fetch at load (it fails soft in node). Install the shim BEFORE the
// dynamic imports below.
globalThis.document = {
  createElement: () => ({ dataset: {}, style: {}, children: [],
    appendChild() {}, addEventListener() {}, setAttribute() {} }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: () => {},
};

const { escHtml } = await import("../lib/helpers.js");

const QUOTE_PAYLOAD = 'x" onmouseover="alert(1)';
const ALL_FIVE = `a"b'c<d>&e`;
const ALL_FIVE_ESCAPED = "a&quot;b&#39;c&lt;d&gt;&amp;e";

// ---------------------------------------------------------------------------
// js/incomplete-html-attribute-sanitization (alerts 19-27): the seven panels'
// local _esc escaped only & < >, and its output lands in double-quoted
// attributes (title= / value=). It must escape quotes too.
// ---------------------------------------------------------------------------
const ATTR_PANELS = [
  "champ_benchmarks", "duration_winrate", "op_score", "patch_impact",
  "perf_curve", "playstyle_labels", "session_hygiene",
];

for (const name of ATTR_PANELS) {
  test(`${name}._esc escapes all five HTML-significant characters`, async () => {
    const mod = await import(`./${name}.js`);
    assert.ok(mod.__test && typeof mod.__test._esc === "function",
      `${name}.js must expose _esc on __test`);
    assert.strictEqual(mod.__test._esc(ALL_FIVE), ALL_FIVE_ESCAPED);
    assert.strictEqual(mod.__test._esc(ALL_FIVE), escHtml(ALL_FIVE));
    assert.strictEqual(mod.__test._esc(null), "");
    assert.strictEqual(mod.__test._esc(undefined), "");
    assert.strictEqual(mod.__test._esc(0), "0");
    assert.strictEqual(mod.__test._esc("plain ASCII 123"), "plain ASCII 123");
  });
}

test("patch_impact chip title cannot break out of its attribute", async () => {
  const { __test } = await import("./patch_impact.js");
  const out = __test._chips({
    item_changes: [{ name: QUOTE_PAYLOAD, fields: [{ field: "ad" }] }],
  });
  assert.ok(!out.includes('" onmouseover="'), out);
  assert.ok(out.includes("&quot; onmouseover=&quot;alert(1)"), out);
});

test("patch_impact play-share title cannot break out of its attribute", async () => {
  const { __test } = await import("./patch_impact.js");
  const out = __test._champRow({ name: "Ahri", games: 3, play_share: QUOTE_PAYLOAD });
  assert.ok(!out.includes('" onmouseover="'), out);
});

test("playstyle_labels verdict title cannot break out of its attribute", async () => {
  const { __test } = await import("./playstyle_labels.js");
  const out = __test._labelChip({ tag: "tank", verdict: QUOTE_PAYLOAD });
  assert.ok(!out.includes('" onmouseover="'), out);
  assert.ok(out.includes("&quot; onmouseover=&quot;alert(1)"), out);
});

test("session_hygiene tilt-bar title cannot break out of its attribute", async () => {
  const { __test } = await import("./session_hygiene.js");
  const out = __test._tiltStrip([{ label: QUOTE_PAYLOAD, wr: 0.5, games: 4 }]);
  assert.ok(!out.includes('" onmouseover="'), out);
});

test("op_score arc-chip title cannot break out of its attribute", async () => {
  const { __test } = await import("./op_score.js");
  const out = __test._arcChip("win", { label: "rise", read: QUOTE_PAYLOAD });
  assert.ok(!out.includes('" onmouseover="'), out);
  assert.ok(out.includes("&quot; onmouseover=&quot;alert(1)"), out);
});
