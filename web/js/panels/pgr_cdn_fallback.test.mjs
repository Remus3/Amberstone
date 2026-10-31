// web/js/panels/pgr_cdn_fallback.test.mjs
//
// RM-967: the Post Game Review (last_match.js) and the historical PGR
// (historical_pgr.js) icon onerror fallback asked the DDragon CDN for
// <id>.png.png, so it could never load. _onErrCdnFallback(ver, kind, id)
// appends ".png" itself, and all four callers passed an id that already
// ended in ".png". Probed 2026-10-27 at patch 16.21.1: img/item/3031.png 200,
// img/item/3031.png.png 403; img/spell/SummonerFlash.png 200,
// img/spell/SummonerFlash.png.png 403. On a local-mirror miss the icon went
// straight to hidden, so the patch-gap safety net never worked.
//
// These pin the fallback URL each module's _itemImgTag / _summonerImgTag
// writes into the onerror string, plus the local-first order and the
// hide-on-second-error behaviour that must survive the fix. Run by
// tests/test_web_panels_node_suite.py (node --test over this dir).
//
// Both modules import items_index.js, whose async loaders touch the DOM once
// their fetch settles, so - as in dev_replay_item_icon.test.mjs - a MINIMAL
// globalThis.document shim is installed before the dynamic imports.

import test from "node:test";
import assert from "node:assert";

globalThis.document = {
  createElement: () => ({ dataset: {}, style: {}, children: [],
    appendChild() {}, addEventListener() {}, setAttribute() {} }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: () => {},
};

const { ITEMS } = await import("../lib/items_index.js");
const lastMatch = await import("./last_match.js");
const historical = await import("./historical_pgr.js");

const VER = "16.21.1";
const CDN = `https://ddragon.leagueoflegends.com/cdn/${VER}`;
const MODULES = [
  ["last_match.js", lastMatch],
  ["historical_pgr.js", historical],
];

function withVersion(ver, fn) {
  const saved = ITEMS.version;
  ITEMS.version = ver;
  try { return fn(); } finally { ITEMS.version = saved; }
}

function onerrorOf(tag) {
  const m = /onerror="([^"]*)"/.exec(tag);
  assert.ok(m, `tag carries an onerror attribute: ${tag}`);
  return m[1];
}

for (const [name, mod] of MODULES) {
  test(`${name} exposes its icon tag builders for tests`, () => {
    assert.ok(mod.__test, `${name} exports __test`);
    assert.strictEqual(typeof mod.__test._itemImgTag, "function");
    assert.strictEqual(typeof mod.__test._summonerImgTag, "function");
  });

  test(`${name} item fallback asks the CDN for <id>.png, never .png.png`, () => {
    const tag = withVersion(VER, () => mod.__test._itemImgTag(3031, "x"));
    const onErr = onerrorOf(tag);
    assert.ok(onErr.includes(`'${CDN}/img/item/3031.png'`),
      `item CDN fallback is ${CDN}/img/item/3031.png: ${onErr}`);
    assert.ok(!onErr.includes(".png.png"), `no double suffix: ${onErr}`);
    assert.ok(tag.includes(`src="/data/ddragon/${VER}/img/item/3031.png"`),
      `local mirror stays first: ${tag}`);
  });

  test(`${name} spell fallback asks the CDN for <key>.png, never .png.png`, () => {
    // Summoner spell id 4 is Flash (SUMMONER_SPELL_BY_ID in both modules).
    const tag = withVersion(VER, () => mod.__test._summonerImgTag(4, "x"));
    const onErr = onerrorOf(tag);
    assert.ok(onErr.includes(`'${CDN}/img/spell/SummonerFlash.png'`),
      `spell CDN fallback is ${CDN}/img/spell/SummonerFlash.png: ${onErr}`);
    assert.ok(!onErr.includes(".png.png"), `no double suffix: ${onErr}`);
    assert.ok(tag.includes(`src="/data/ddragon/${VER}/img/spell/SummonerFlash.png"`),
      `local mirror stays first: ${tag}`);
  });

  test(`${name} keeps the hide-on-second-error order`, () => {
    const onErr = onerrorOf(withVersion(VER, () => mod.__test._itemImgTag(3031)));
    assert.ok(onErr.startsWith("if(this.dataset.cdn){this.style.visibility='hidden';}"),
      `a second error hides the icon: ${onErr}`);
    assert.ok(onErr.includes("else{this.dataset.cdn='1';this.src='"),
      `the first error retries the CDN once: ${onErr}`);
  });

  test(`${name} builds no tag for a missing item or an unknown spell`, () => {
    assert.strictEqual(mod.__test._itemImgTag(0), "");
    assert.strictEqual(mod.__test._summonerImgTag(99999), "");
  });
}
