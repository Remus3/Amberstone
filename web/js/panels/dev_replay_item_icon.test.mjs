// web/js/panels/dev_replay_item_icon.test.mjs
//
// RM-857: the Replay scrubber's item column never showed an icon. dev.js
// built /icons/items/<numeric id>.png, but that route serves
// data/icons/aram_items/, which holds name-slug files only, so every request
// 404'd and the img onerror hid it silently. Live 2026-10-25:
// /icons/items/3100.png 404, /data/ddragon/<ver>/img/item/3100.png 200.
//
// These pin the fix: the replay item icon URL is the local DDragon mirror by
// item id, built by the ONE shared builder (last_match.js _itemIconUrl), with
// the patch taken from ITEMS.version (items_index.js) - never a literal.
// Run by tests/test_web_panels_node_suite.py (node --test over this dir).
//
// dev.js transitively imports items_index.js, whose async loaders call
// document.getElementById / dispatchEvent once their fetch settles, so -
// mirroring build_insights_rune_tooltip.test.mjs - a MINIMAL globalThis.document
// shim is installed before the dynamic imports.

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

const { ITEMS, DDRAGON_FALLBACK_VERSION } = await import("../lib/items_index.js");
const { __test } = await import("./dev.js");
const lastMatch = await import("./last_match.js");
const { _replayItemIconUrl } = __test;

function withVersion(ver, fn) {
  const saved = ITEMS.version;
  ITEMS.version = ver;
  try { return fn(); } finally { ITEMS.version = saved; }
}

test("item 3100 resolves to the local DDragon mirror path", () => {
  const url = _replayItemIconUrl(3100);
  assert.match(url, /^\/data\/ddragon\/[^/]+\/img\/item\/3100\.png$/);
  assert.strictEqual(url, `/data/ddragon/${ITEMS.version}/img/item/3100.png`);
  assert.ok(!url.startsWith("/icons/items/"), "the dead slug route is gone");
});

test("the patch comes from ITEMS.version, not a hard-coded literal", () => {
  withVersion("99.1.1", () => {
    assert.strictEqual(_replayItemIconUrl(3100), "/data/ddragon/99.1.1/img/item/3100.png");
  });
  withVersion("", () => {
    assert.strictEqual(
      _replayItemIconUrl(3100),
      `/data/ddragon/${DDRAGON_FALLBACK_VERSION}/img/item/3100.png`,
    );
  });
});

test("the replay table reuses the shared item-icon builder", () => {
  assert.strictEqual(typeof lastMatch._itemIconUrl, "function",
    "last_match.js exports its DDragon item-icon URL builder");
  assert.strictEqual(_replayItemIconUrl, lastMatch._itemIconUrl,
    "dev.js must not carry a second URL builder");
});

test("an empty slot id yields no URL, so no request is made", () => {
  assert.strictEqual(_replayItemIconUrl(0), "");
  assert.strictEqual(_replayItemIconUrl(null), "");
});
