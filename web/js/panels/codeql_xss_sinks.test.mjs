// web/js/panels/codeql_xss_sinks.test.mjs
//
// PUBREPO 1g (CodeQL, JavaScript half): js/xss alerts 6-10. The dashboard
// WebSocket payload (main.js onmessage -> JSON.parse) reaches these innerHTML
// builders; every interpolated payload field must be escaped. Run with
// `node --test` (gated by tests/test_web_panels_node_suite.py).
//
// Own file because it installs a richer DOM shim than
// codeql_js_hardening.test.mjs: getElementById hands back one stub element
// per id so the render functions can write innerHTML we then read back.

import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

class StubEl {
  constructor(tag) {
    this.tagName = tag; this.innerHTML = ""; this.textContent = ""; this.hidden = true;
    this.children = []; this.className = ""; this.dataset = {}; this.style = {};
    const set = new Set();
    this.classList = {
      add: (c) => set.add(c), remove: (c) => set.delete(c),
      toggle: (c, on) => (on ? set.add(c) : set.delete(c)), contains: (c) => set.has(c),
    };
  }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener() {}
  setAttribute() {}
  querySelectorAll() { return []; }
}
const ELS = new Map();
globalThis.document = {
  getElementById: (id) => { if (!ELS.has(id)) ELS.set(id, new StubEl("div")); return ELS.get(id); },
  createElement: (tag) => new StubEl(tag),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: () => {},
};

const { escHtml } = await import("../lib/helpers.js");
const XSS = "<img src=x onerror=alert(1)>";
const XSS_ESC = "&lt;img src=x onerror=alert(1)&gt;";
const RAW = /<img src=x|<IMG SRC=X|" onmouseover="/;

// ---------------------------------------------------------------------------
// Alert 6: augment_reco.js:114 - r.score and r.n_own went into the row HTML
// unescaped.
// ---------------------------------------------------------------------------
const { renderAugmentReco, _resetAugmentRecoSig } = await import("./augment_reco.js");

test("augment_reco escapes the score and sample-size fields", () => {
  _resetAugmentRecoSig();
  renderAugmentReco({ aug_reco: [{ id: 1, name: "Ok", rarity: "gold", score: XSS, n_own: XSS,
    own_wr: 0.5, ext_wr: 0.4, syn: 0 }] });
  const html = document.getElementById("ib-aug-reco-list").innerHTML;
  assert.doesNotMatch(html, RAW, html);
  assert.ok(html.includes(XSS_ESC), html);
});

test("augment_reco renders well-formed numbers exactly as before", () => {
  _resetAugmentRecoSig();
  renderAugmentReco({ aug_reco: [{ id: 2, name: "Ok", rarity: "gold", score: 0.731, n_own: 12,
    own_wr: 0.5, ext_wr: 0.4, syn: 0.02 }] });
  const html = document.getElementById("ib-aug-reco-list").innerHTML;
  assert.ok(html.includes('title="Blended marginal + synergy score">0.731</span>'), html);
  assert.ok(html.includes('title="Your win-rate (n=12) / external Mayhem prior"'), html);
});

// ---------------------------------------------------------------------------
// Alert 7: coach_choices.js:223 - the confidence band went raw into a class
// and a title attribute via _bandDots.
// ---------------------------------------------------------------------------
const { _internals } = await import("./coach_choices.js");

test("coach_choices confidence band cannot break out of its attributes", () => {
  const html = _internals._chipHtml({ key: "A", label: "Contest", confidence: 'high" onmouseover="alert(1)' });
  assert.doesNotMatch(html, RAW, html);
  const dots = _internals._bandDots(XSS);
  assert.doesNotMatch(dots, RAW, dots);
});

test("coach_choices band dots are unchanged for the real bands", () => {
  assert.strictEqual(_internals._bandDots("high"),
    '<span class="rc-band rc-band-high" title="confidence: high">' +
    '<span class="rc-band-dot filled"></span><span class="rc-band-dot filled"></span>' +
    '<span class="rc-band-dot filled"></span></span>');
});

// ---------------------------------------------------------------------------
// Alerts 8-10: champ_select.js:958 (_csvArenaPaneHtml), :971 (_csvBenchHtml via
// the bench strip) and :3636 (_csvRenderEnemiesArena). champ_select.js is not
// importable in node (it pulls the whole view graph), so - as the repo's other
// champ_select guards do - the three builders are extracted from the source by
// balanced braces and run against stubs.
// ---------------------------------------------------------------------------
const CS_SRC = readFileSync(new URL("./champ_select.js", import.meta.url), "utf8");

function fnSpan(name) {
  const i = CS_SRC.indexOf(`function ${name}(`);
  assert.ok(i >= 0, `${name} not found in champ_select.js`);
  const j = CS_SRC.indexOf("{", CS_SRC.indexOf(")", i));
  let depth = 0;
  for (let k = j; k < CS_SRC.length; k++) {
    const c = CS_SRC[k];
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return CS_SRC.slice(i, k + 1); }
  }
  throw new Error(`unbalanced ${name}`);
}

function loadBuilders(byId) {
  const CHAMPS = { version: "testver", byId };
  const body = [fnSpan("_csvBenchHtml"), fnSpan("_csvArenaPaneHtml"), fnSpan("_csvRenderEnemiesArena")].join("\n");
  const factory = new Function(
    "escHtml", "CHAMPS", "_csChampName", "_csvCompVerdictHtml", "_CSV_COMPVERDICT",
    "_csvNormChampName", "document",
    body + "\nreturn { _csvBenchHtml, _csvArenaPaneHtml, _csvRenderEnemiesArena };");
  return factory(
    escHtml, CHAMPS,
    (cid) => (cid && CHAMPS.byId[String(cid)]) || "",
    () => "",
    { key: "", data: null, inflight: false },
    (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, ""),
    globalThis.document);
}

test("champ_select bench strip escapes the champion id and name", () => {
  const b = loadBuilders({ 145: "Kaisa", 666: XSS });
  const html = b._csvBenchHtml({ bench: ['1"><img src=x onerror=alert(1)>', 666] });
  assert.doesNotMatch(html, RAW, html);
  assert.ok(!html.includes('1"><img'), html);
  assert.ok(html.includes('data-bench-id="1&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"'), html);
});

test("champ_select bench strip is unchanged for a real champion", () => {
  const b = loadBuilders({ 145: "Kaisa" });
  const html = b._csvBenchHtml({ bench: [145] });
  assert.ok(html.includes('data-bench-id="145" data-bench-name="Kaisa" title="Swap to Kaisa"'), html);
  assert.ok(html.includes('<img src="/data/ddragon/testver/img/champion/Kaisa.png" alt="Kaisa" ' +
    "onerror=\"this.style.display='none'\">"), html);
});

test("champ_select arena pane escapes names, augments and the round tier", () => {
  const b = loadBuilders({ 145: "Kaisa", 666: XSS });
  const cs = {
    arena_teams: [{ is_me: true, cells: [{ championId: 666, summonerName: "me", completed: true },
                                         { championId: 145 }] }],
    augments: { my_slots: [{ tier: "silver", id: 5, name: XSS }],
                options: [{ id: XSS, name: XSS, blurb: XSS, tier: XSS }],
                current_round: "<img src=x onerror=alert(2)>" },
  };
  const html = b._csvArenaPaneHtml(cs, 666, "me");
  assert.doesNotMatch(html, RAW, html);
  assert.ok(html.includes("&lt;IMG SRC=X ONERROR=ALERT(2)&gt; round"), html);
});

test("champ_select arena pane is unchanged for a real roster", () => {
  const b = loadBuilders({ 145: "Kaisa" });
  const html = b._csvArenaPaneHtml({ arena_teams: [{ is_me: true, cells: [{ championId: 145 }] }],
    augments: { my_slots: [], options: [], current_round: "gold" } }, 145, "me");
  assert.ok(html.includes('<div class="csv-duo-cell-name">Kaisa</div>'), html);
  assert.ok(html.includes("GOLD round . pick one"), html);
});

test("champ_select arena enemies escape the team label and champion name", () => {
  const b = loadBuilders({ 666: XSS });
  b._csvRenderEnemiesArena({ arena_teams: [{ is_me: false, label: XSS,
    cells: [{ championId: 666, completed: true }] }] }, 0);
  const list = document.getElementById("csv-enemies-list");
  assert.strictEqual(list.children.length, 5);
  for (const li of list.children) assert.doesNotMatch(li.innerHTML, RAW, li.innerHTML);
  assert.ok(list.children[0].innerHTML.includes(`<div class="csv-arena-team-head">${XSS_ESC}</div>`));
  assert.ok(list.children[1].innerHTML.includes('<div class="csv-arena-team-head">TEAM 3</div>'));
});
