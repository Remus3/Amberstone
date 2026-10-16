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
    // A <br>-split name keeps one flex item per part (the flex .lol-tt-title
    // renders it as ONE row, name left / subtitle right, as before).
    assert.strictEqual(lol.itemTooltipHtml("9002"),
      '<div class="lol-tt-title"><span>Fire at Will</span><br><span>500 Silver Serpents</span></div>' +
      "<i>Cannon Barrage fires faster.</i>");
    // Only the bare allowed tags + the tooltip's own div wrappers survive.
    for (const html of [item, ks]) {
      assert.doesNotMatch(html, /<(?!\/?(?:b|i|br|span)>|div class="lol-tt-[a-z]+">|\/div>)/, html);
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

// ---------------------------------------------------------------------------
// js/xss-through-dom (alert 11): main.js show() handed the data-tt-html
// attribute straight to tip.innerHTML. The tooltip DOM is now rebuilt from
// an allowlist by helpers.renderTooltipHtml (no innerHTML at all).
// ---------------------------------------------------------------------------
class FakeNode {
  constructor(name, text) {
    this.localName = name; this.text = text; this.attrs = {}; this.childNodes = [];
  }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(n) { this.childNodes.push(n); return n; }
  removeChild(n) { this.childNodes.splice(this.childNodes.indexOf(n), 1); return n; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
}
const fakeDoc = {
  createElement: (t) => new FakeNode(t, null),
  createTextNode: (t) => new FakeNode("#text", t),
};
const ser = (n) => (n.localName === "#text" ? n.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  : `<${n.localName}${Object.entries(n.attrs).map(([k, v]) => ` ${k}="${v}"`).join("")}>` +
    (n.localName === "br" ? "" : n.childNodes.map(ser).join("") + `</${n.localName}>`));
const tipHtml = (html) => {
  const tip = new FakeNode("div", null);
  tip.ownerDocument = fakeDoc;
  tip.appendChild(new FakeNode("#text", "stale"));
  helpers.renderTooltipHtml(tip, html);
  return tip.childNodes.map(ser).join("");
};

test("renderTooltipHtml drops scripts, handlers and every non-allowlisted tag", () => {
  assert.strictEqual(typeof helpers.renderTooltipHtml, "function");
  const out = tipHtml('<img src=x onerror=alert(1)><script>alert(2)</script>' +
    '<div class="a" onclick="x()">t<iframe src="javascript:alert(3)"></iframe></div>' +
    '<style>b{}</style><svg onload=alert(4)>u</svg>');
  assert.strictEqual(out, '<div class="a">t</div>u');
});

test("renderTooltipHtml rebuilds the real producers' markup exactly", () => {
  // lib/lol_descriptions item tooltip shape.
  assert.strictEqual(
    tipHtml('<div class="lol-tt-title">Doran\'s Blade<div class="lol-tt-gold">450g</div></div>' +
      '<b>8</b> Attack Damage<br><b>80</b> Health<br><br><i>Lifesteal</i>'),
    '<div class="lol-tt-title">Doran\'s Blade<div class="lol-tt-gold">450g</div></div>' +
      "<b>8</b> Attack Damage<br><b>80</b> Health<br><br><i>Lifesteal</i>");
  // main.js games-by-mode tip shape.
  assert.strictEqual(
    tipHtml('<div class="lv-mc-games-tip"><div class="lv-mc-games-tip-row lv-mc-games-tip-head">' +
      "<span>RIFT</span><span>ARAM</span></div></div>"),
    '<div class="lv-mc-games-tip"><div class="lv-mc-games-tip-row lv-mc-games-tip-head">' +
      "<span>RIFT</span><span>ARAM</span></div></div>");
  // last_match Quick Review `why`: escaped text.
  assert.strictEqual(tipHtml("x &lt;b&gt; &amp; &#39;y&#39; &quot;z&quot; &#x41;&#66;"),
    "x &lt;b&gt; &amp; 'y' \"z\" AB");
});

test("renderTooltipHtml clears the previous tooltip content", () => {
  assert.strictEqual(tipHtml(""), "");
});

// Verifier finding on slice F: DDragon items 3901-3903 carry LoL markup in the
// NAME ("<rarityLegendary>X</rarityLegendary><br><subtitleLeft><silver>Y
// </silver></subtitleLeft>"). The old innerHTML tooltip kept those unknown
// wrappers, so the flex .lol-tt-title had three flex items (X, br, Y) and
// rendered ONE row. The cleaned title must keep that child structure.
test("a markup-carrying item name keeps the old title child structure", () => {
  assert.ok(lol.__test && typeof lol.__test._titleHtml === "function",
    "lol_descriptions.js must expose _titleHtml on __test");
  const raw = "<rarityLegendary>Fire at Will</rarityLegendary><br><subtitleLeft><silver>500 Silver Serpents</silver></subtitleLeft>";
  const title = lol.__test._titleHtml(raw);
  assert.strictEqual(title, "<span>Fire at Will</span><br><span>500 Silver Serpents</span>");
  // Rebuilt through the tooltip sink: element, br, element - each part its
  // own child, same text as the old <rarityLegendary> / <subtitleLeft> pair.
  const tip = new FakeNode("div", null);
  tip.ownerDocument = fakeDoc;
  helpers.renderTooltipHtml(tip, `<div class="lol-tt-title">${title}</div>`);
  const kids = tip.childNodes[0].childNodes;
  assert.deepStrictEqual(kids.map((n) => n.localName), ["span", "br", "span"]);
  assert.deepStrictEqual(kids.map((n) => n.childNodes.map((t) => t.text).join("")),
    ["Fire at Will", "", "500 Silver Serpents"]);
  // A plain name (no <br>) is unchanged: one text run, no wrapper.
  assert.strictEqual(lol.__test._titleHtml("Doran's Blade"), "Doran's Blade");
  assert.strictEqual(lol.__test._titleHtml(""), "");
});

test("main.js show() renders data-tt-html through renderTooltipHtml, not innerHTML", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../main.js", import.meta.url), "utf8");
  const m = src.match(/function show\(el\) \{([\s\S]*?)\n    \}/);
  assert.ok(m, "main.js tooltip show() not found");
  const code = m[1].replace(/\/\/.*$/gm, "");   // ignore comments
  assert.match(code, /renderTooltipHtml\(tip, html\)/);
  assert.doesNotMatch(code, /innerHTML/);
  assert.match(src, /import \{[^}]*\brenderTooltipHtml\b[^}]*\} from '\.\/lib\/helpers\.js';/);
});

// ---------------------------------------------------------------------------
// js/incomplete-sanitization (alerts 28, 29): champion_tags.js built its
// spelling-variant keys with replace("'", "") / replace(" ", ""), which drop
// only the FIRST apostrophe / space. The server (dashboard/routes_dictionary
// .py) builds the same variants with Python's str.replace, which drops ALL.
// ---------------------------------------------------------------------------
test("champion_tags spelling variants drop every apostrophe and space", async () => {
  const realFetch = globalThis.fetch;
  const E1 = { tags: ["AP", "MAGE"] };
  const E2 = { tags: ["AD", "TANK"] };
  globalThis.fetch = async (url) => (String(url).includes("/api/dictionary/champion-tags")
    ? { ok: true, json: async () => ({ "A'b'c": E1, "Nunu & Willump": E2 }) }
    : { ok: false });
  try {
    const ct = await import("../lib/champion_tags.js");
    ct.preloadChampionTags();
    await new Promise((r) => setTimeout(r, 20));
    assert.strictEqual(ct.championTags("A'b'c"), E1);
    assert.strictEqual(ct.championTags("Abc"), E1);
    assert.strictEqual(ct.championTags("Nunu&Willump"), E2);
    assert.strictEqual(ct.championTags("Nunu & Willump"), E2);
  } finally {
    globalThis.fetch = realFetch;
  }
});

// ---------------------------------------------------------------------------
// js/incomplete-multi-character-sanitization (alert 16): web/legacy_index.html
// (still served at /?ui=legacy and as the index fallback) rebuilt its
// coach-dedupe key with a one-pass tag strip. The key is only compared, never
// rendered; it now strips to a fixpoint like lib/helpers.stripTags.
// ---------------------------------------------------------------------------
test("legacy_index.html dedupe key strips tags to a fixpoint", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../../legacy_index.html", import.meta.url), "utf8");
  assert.doesNotMatch(src, /_lastCoachImmediate = _chatMsgs\[i\]\.text\.replace/,
    "single-pass strip still assigned straight to the dedupe key");
  const m = src.match(/function _legacyStripTags\(s\) \{([\s\S]*?)\n\}/);
  assert.ok(m, "_legacyStripTags helper not found");
  assert.match(m[1], /do \{[\s\S]*\} while \(out !== prev\);/);
  const strip = new Function(m[0] + "; return _legacyStripTags;")();
  assert.strictEqual(strip("<b>Push</b> top &lt;now&gt;"), "Push top &lt;now&gt;");
  assert.strictEqual(strip("a<x>b<<y>>c"), "ab>c");
});

test("items_index.parseItemTooltip output is unchanged for a real DDragon item", async () => {
  const { parseItemTooltip } = await import("../lib/items_index.js");
  const t = parseItemTooltip({ name: "Sheen",
    description: "<mainText><stats></stats><br><br><passive>Spellblade</passive><br>After using an Ability, your next Attack deals <physicalDamage>bonus damage</physicalDamage> &amp; more.</mainText>" });
  assert.deepStrictEqual(t, { name: "Sheen", stats: [],
    passive: "Spellblade\nAfter using an Ability, your next Attack deals bonus damage & more." });
});
