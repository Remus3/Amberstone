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

// ---------------------------------------------------------------------------
// js/double-escaping (alerts 17, 18) + js/incomplete-multi-character-
// sanitization (alerts 14, 15): build_insights.js and main.js each carried a
// _stripHtml that decoded &amp; FIRST (so "&amp;lt;" double-decoded to "<")
// and stripped tags in one pass. Both now delegate to lib/helpers.htmlToText.
// ---------------------------------------------------------------------------
const helpers = await import("../lib/helpers.js");

test("helpers.stripTags removes every tag and is null safe", () => {
  assert.strictEqual(typeof helpers.stripTags, "function");
  assert.strictEqual(helpers.stripTags("a<b>b</b>c<br/>d"), "abcd");
  assert.strictEqual(helpers.stripTags(null), "");
  assert.strictEqual(helpers.stripTags(undefined), "");
  assert.strictEqual(helpers.stripTags("no tags here"), "no tags here");
});

test("helpers.htmlToText decodes &amp; LAST - a double-encoded entity decodes once", () => {
  assert.strictEqual(typeof helpers.htmlToText, "function");
  assert.strictEqual(helpers.htmlToText("&amp;lt;b&amp;gt;"), "&lt;b&gt;");
  assert.strictEqual(helpers.htmlToText("a &amp;amp; b"), "a &amp; b");
});

test("helpers.htmlToText keeps the old contract for well-formed DDragon text", () => {
  assert.strictEqual(
    helpers.htmlToText("deals bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_adaptive'>adaptive damage</lol-uikit-tooltipped-keyword>."),
    "deals bonus adaptive damage.");
  assert.strictEqual(helpers.htmlToText("gain &lt;A&gt; &amp; &#39;B&#39;&nbsp;now"), "gain <A> & 'B' now");
  assert.strictEqual(helpers.htmlToText("  lots\n\tof   space  "), "lots of space");
  assert.strictEqual(helpers.htmlToText(null), "");
});

test("build_insights._stripHtml decodes a double-encoded entity once", async () => {
  const { __test } = await import("./build_insights.js");
  assert.strictEqual(__test._stripHtml("&amp;lt;script&amp;gt;"), "&lt;script&gt;");
});

test("main.js _stripHtml delegates to the shared helpers.htmlToText", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../main.js", import.meta.url), "utf8");
  const m = src.match(/function _stripHtml\(s\) \{([\s\S]*?)\n  \}/);
  assert.ok(m, "main.js _stripHtml not found");
  assert.match(m[1], /return htmlToText\(s\);/);
  assert.doesNotMatch(m[1], /&amp;/, "no hand-rolled entity chain left in main.js");
  assert.match(src, /import \{[^}]*\bhtmlToText\b[^}]*\} from '\.\/lib\/helpers\.js';/);
});

// ---------------------------------------------------------------------------
// js/incomplete-multi-character-sanitization (alerts 12, 13).
// lol_descriptions._cleanLolHtml feeds the innerHTML tooltip: an allowed tag
// kept its attributes (<b onmouseover=...>) and removing one tag could splice
// an allowed tag together with an attribute ("<i<x> onmouseover=...>").
// items_index.parseItemTooltip strips via the shared fixpoint stripTags.
// ---------------------------------------------------------------------------
const lol = await import("../lib/lol_descriptions.js");

test("lol_descriptions._cleanLolHtml drops attributes from allowed tags", () => {
  assert.ok(lol.__test && typeof lol.__test._cleanLolHtml === "function",
    "lol_descriptions.js must expose _cleanLolHtml on __test");
  const clean = lol.__test._cleanLolHtml;
  assert.strictEqual(clean('<b onmouseover="alert(1)">x</b>'), "<b>x</b>");
  assert.strictEqual(clean("<i<x> onmouseover=alert(1)>y</i>"), "<i>y</i>");
  assert.strictEqual(clean("<br onload=alert(1)>z"), "<br>z");
});

test("lol_descriptions._cleanLolHtml leaves no executable tag and escapes stray '<'", () => {
  assert.ok(lol.__test, "lol_descriptions.js must expose __test");
  const clean = lol.__test._cleanLolHtml;
  const out = clean("<scr<x>ipt>alert(1)</script><img src=x onerror=alert(1)>");
  assert.doesNotMatch(out, /<(?!\/?(?:b|i|br)>)/, out);
  assert.strictEqual(clean("a <b c"), "a &lt;b c");
});

test("lol_descriptions._cleanLolHtml output is unchanged for a real DDragon item description", () => {
  assert.ok(lol.__test, "lol_descriptions.js must expose __test");
  const clean = lol.__test._cleanLolHtml;
  assert.strictEqual(
    clean("<mainText><stats><attention>55</attention> Attack Damage<br><attention>10%</attention> Critical Strike Chance</stats><br><br><passive>Spellblade</passive><br>After using an Ability, your next Attack deals <physicalDamage>bonus damage</physicalDamage>.<br><br><rules>Hello</rules></mainText>"),
    "<b>55</b> Attack Damage<br><b>10%</b> Critical Strike Chance<br><br><b>Spellblade</b><br>After using an Ability, your next Attack deals bonus damage.<br><br><i>Hello</i>");
});

test("lol_descriptions tooltips clean the DDragon name / plaintext / tree fields", async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes("/api/dictionary/items")) {
      return { ok: true, json: async () => ({ data: {
        "9001": { name: "<img src=x onerror=alert(1)>", plaintext: "<svg onload=alert(2)>",
                  description: "", gold: { total: 0 } },
        // Real DDragon shape (item 3901): the NAME carries LoL markup.
        "9002": { name: "<rarityLegendary>Fire at Will</rarityLegendary><br><subtitleLeft><silver>500 Silver Serpents</silver></subtitleLeft>",
                  plaintext: "Cannon Barrage fires faster.", description: "", gold: { total: 0 } } } }) };
    }
    if (String(url).includes("/api/dictionary/runes")) {
      return { ok: true, json: async () => ([{ name: "<img src=y onerror=alert(3)>", slots: [{ runes: [
        { id: 9100, name: "Evil<script>", shortDesc: "<b>ok</b>", longDesc: "" }] }] }]) };
    }
    return { ok: false };
  };
  try {
    lol.itemTooltipHtml("9001");
    lol.keystoneTooltipHtml("evilscript");
    await new Promise((r) => setTimeout(r, 20));
    const item = lol.itemTooltipHtml("9001");
    const ks = lol.keystoneTooltipHtml("Evil<script>");
    assert.ok(item.startsWith('<div class="lol-tt-title">'), item);
    assert.doesNotMatch(item, /<img|<svg|onerror|onload/);
    assert.ok(ks.includes('<div class="lol-tt-title">Evil<div class="lol-tt-tree">'), ks);
    assert.doesNotMatch(ks, /<img|<script|onerror/);
    assert.ok(ks.includes("<b>ok</b>"), "cleaned rune HTML keeps its allowed tags");
    assert.strictEqual(lol.itemTooltipHtml("9002"),
      '<div class="lol-tt-title">Fire at Will<br>500 Silver Serpents</div><i>Cannon Barrage fires faster.</i>');
    // Only the bare allowed tags + the tooltip's own div wrappers survive.
    for (const html of [item, ks]) {
      assert.doesNotMatch(html, /<(?!\/?(?:b|i|br)>|div class="lol-tt-[a-z]+">|\/div>)/, html);
    }
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("items_index.parseItemTooltip strips via the shared fixpoint stripTags", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../lib/items_index.js", import.meta.url), "utf8");
  assert.match(src, /import \{[^}]*\bstripTags\b[^}]*\} from "\.\/helpers\.js";/);
  const m = src.match(/export function parseItemTooltip\(detail\) \{([\s\S]*?)\n\}/);
  assert.ok(m, "parseItemTooltip not found");
  assert.match(m[1], /stripTags\(/);
  assert.doesNotMatch(m[1], /replace\(\/<\[\^>\]\*>\/g, ""\)/, "no single-pass tag strip left");
});

test("items_index.parseItemTooltip output is unchanged for a real DDragon item", async () => {
  const { parseItemTooltip } = await import("../lib/items_index.js");
  const t = parseItemTooltip({ name: "Sheen",
    description: "<mainText><stats></stats><br><br><passive>Spellblade</passive><br>After using an Ability, your next Attack deals <physicalDamage>bonus damage</physicalDamage> &amp; more.</mainText>" });
  assert.deepStrictEqual(t, { name: "Sheen", stats: [],
    passive: "Spellblade\nAfter using an Ability, your next Attack deals bonus damage & more." });
});
