// web/js/panels/ops_panels.test.mjs
//
// Y-08 (external reference M): the match-ingest freshness card on /ops.html.
// Run with `node --test`. Pins the card contract the backend relies on:
//   - the same five rows render for a fresh tree, a failed fetch and a full
//     payload (no reflow on data absence);
//   - a fresh tree shows its explicit "no receipt yet" basis line;
//   - an unknown row state never renders as ok;
//   - render is idempotent and IN PLACE: a second render keeps every node
//     (no wipe-and-repaint that would drop focus or selection).
// A tiny fake DOM stands in for the browser; ops_panels.js touches the DOM
// only inside its render functions, so the import itself needs none.

import test from "node:test";
import assert from "node:assert";

import {
  INGEST_KEYS, ingestCardModel, renderIngestFreshness,
} from "./ops_panels.js";

// ------------------------------------------------------------- fake DOM
class FakeEl {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.className = "";
    this.textContent = "";
    this.children = [];
    this.attrs = {};
    this.writes = 0;
  }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  replaceChildren() { this.children = []; }
  _matches(sel) {
    const attr = sel.match(/^\[([a-z-]+)="([^"]*)"\]$/);
    if (attr) return this.attrs[attr[1]] === attr[2];
    if (sel.startsWith(".")) {
      const need = sel.slice(1).split(".");
      const have = this.className.split(/\s+/);
      return need.every((c) => have.includes(c));
    }
    return false;
  }
  querySelector(sel) {
    for (const c of this.children) {
      if (c._matches(sel)) return c;
      const hit = c.querySelector(sel);
      if (hit) return hit;
    }
    return null;
  }
  all() {
    return [this, ...this.children.flatMap((c) => c.all())];
  }
}

function installDom() {
  const host = new FakeEl("section");
  globalThis.document = {
    createElement: (t) => new FakeEl(t),
    getElementById: (id) => (id === "ingest-freshness-panel" ? host : null),
  };
  return host;
}

function rowsOf(host) {
  const list = host.querySelector(".ing");
  return list.children.map((r) => ({
    key: r.getAttribute("data-k"),
    value: r.querySelector(".ing-v").textContent,
    word: r.querySelector(".ing-s").textContent,
    cls: r.querySelector(".ing-s").className,
  }));
}

// ------------------------------------------------------------- payloads
const FRESH = {
  ok: true,
  basis: "no receipt yet - no live-writer chain has ended since receipts began",
  rows: [
    { key: "last_receipt", label: "Last game ingest", value: "no receipt yet", state: "unknown" },
    { key: "tally", label: "Recent receipts", value: "none yet", state: "unknown" },
    { key: "lag", label: "Last game vs rewind DB", value: "no game end recorded yet", state: "unknown" },
    { key: "catchup", label: "Catchup last run", value: "never ran on this tree", state: "unknown" },
    { key: "retry_backlog", label: "fetch_retry backlog", value: "0 pending", state: "ok" },
  ],
};

const FULL = {
  ok: true,
  basis: "last 3 receipt(s); newest 4m ago",
  rows: [
    { key: "last_receipt", label: "Last game ingest", value: "NA1_2, ok, 2 attempt(s)", state: "ok" },
    { key: "tally", label: "Recent receipts", value: "2 of 3 ingested (ok 2, target_not_indexed 1)", state: "amber" },
    { key: "lag", label: "Last game vs rewind DB", value: "caught up - NA1_2 is in the DB", state: "ok" },
    { key: "catchup", label: "Catchup last run", value: "hydrated at 2026-09-27T09:00:00Z", state: "ok" },
    { key: "retry_backlog", label: "fetch_retry backlog", value: "1 pending (match 1)", state: "amber" },
  ],
};

// ------------------------------------------------------------- model
test("model: fixed row keys for fresh, full, failed and garbage", () => {
  for (const data of [FRESH, FULL, { ok: false, reason: "x" }, null, {}, { ok: true, rows: "nope" }]) {
    assert.deepStrictEqual(ingestCardModel(data).rows.map((r) => r.key), INGEST_KEYS);
  }
  assert.strictEqual(INGEST_KEYS.length, 5);
});

test("model: fresh tree carries the explicit no-receipt basis line", () => {
  const m = ingestCardModel(FRESH);
  assert.strictEqual(m.failed, false);
  assert.match(m.basis, /no receipt yet/);
  assert.strictEqual(m.rows[0].value, "no receipt yet");
});

test("model: unknown or bogus row state never renders ok", () => {
  const data = structuredClone(FULL);
  data.rows[0].state = "brand_new_state";
  delete data.rows[1].state;
  const m = ingestCardModel(data);
  assert.strictEqual(m.rows[0].state, "unknown");
  assert.strictEqual(m.rows[0].word, "unknown");
  assert.strictEqual(m.rows[1].state, "unknown");
});

test("model: state is carried as a word, not colour alone", () => {
  const words = ingestCardModel(FULL).rows.map((r) => r.word);
  assert.deepStrictEqual(words, ["ok", "check", "ok", "ok", "check"]);
});

test("model: failed fetch keeps the rows and says unavailable", () => {
  const m = ingestCardModel({ ok: false, reason: "HTTP 500" });
  assert.strictEqual(m.failed, true);
  assert.strictEqual(m.basis, "unavailable - HTTP 500");
  assert.ok(m.rows.every((r) => r.value === "-" && r.state === "unknown"));
});

// ------------------------------------------------------------- render
test("render: same five rows fresh then full (no reflow)", () => {
  const host = installDom();
  renderIngestFreshness(FRESH);
  const before = rowsOf(host).map((r) => r.key);
  renderIngestFreshness(FULL);
  assert.deepStrictEqual(rowsOf(host).map((r) => r.key), before);
  assert.deepStrictEqual(before, INGEST_KEYS);
  assert.match(host.querySelector(".ing-basis").textContent, /newest 4m ago/);
});

test("render: idempotent and in place - every node survives a re-render", () => {
  const host = installDom();
  renderIngestFreshness(FRESH);
  const nodes = host.all();
  renderIngestFreshness(FULL);
  renderIngestFreshness(FULL);
  const after = host.all();
  assert.strictEqual(after.length, nodes.length);
  after.forEach((n, i) => assert.strictEqual(n, nodes[i], "a node was replaced"));
  assert.strictEqual(host.children.length, 1, "skeleton appended twice");
});

test("render: fresh tree basis line and unknown words", () => {
  const host = installDom();
  renderIngestFreshness(FRESH);
  assert.match(host.querySelector(".ing-basis").textContent, /no receipt yet/);
  const r = rowsOf(host);
  assert.strictEqual(r[0].word, "unknown");
  assert.match(r[0].cls, /s-unknown/);
});

test("render: failure marks the basis and keeps last-known layout", () => {
  const host = installDom();
  renderIngestFreshness(FULL);
  renderIngestFreshness({ ok: false, reason: "HTTP 502" });
  const basis = host.querySelector(".ing-basis");
  assert.strictEqual(basis.textContent, "unavailable - HTTP 502");
  assert.match(basis.className, /ing-fail/);
  assert.deepStrictEqual(rowsOf(host).map((r) => r.key), INGEST_KEYS);
  assert.ok(rowsOf(host).every((r) => r.value === "-"));
});
