// web/js/lib/overlay_settings.test.mjs
//
// Behaviour tests for the shared overlay-settings helper (S144-T true-audit).
// Run with `node --test`. The helper touches localStorage / window / document
// only at call time, so each test installs fresh Map-backed shims first.

import test from "node:test";
import assert from "node:assert";

import {
  OVERLAY_SETTINGS_DEFAULTS,
  PGR_RANK_KEY,
  readOverlaySettings,
  writeOverlaySettings,
  hydrateOverlaySettings,
  sendOverlayAction,
  readRoleOverride,
  writeRoleOverride,
  readBenchmarkRankTier,
} from "./overlay_settings.js";

const LS_KEY = "rc_overlay_settings";

function install(win = {}) {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => {
      store.set(k, String(v));
    },
    removeItem: (k) => {
      store.delete(k);
    },
  };
  globalThis.window = win;
  delete globalThis.document;
  return store;
}

// The rc-shell authority (rc-shell/src/overlay_state.js overlaySettingsFrom)
// returns exactly these seven keys - it does NOT own the page-only keys.
function shellReply(over = {}) {
  return {
    pulseNotify: true,
    activeRevertSec: 20,
    keepCompanion: true,
    companionAlwaysOnTop: true,
    overlayOpacity: 1,
    clickThroughZones: true,
    separateWindows: true,
    ...over,
  };
}

// ---- characterization -------------------------------------------------------

test("fresh read returns the defaults", () => {
  install();
  assert.deepStrictEqual(readOverlaySettings(), { ...OVERLAY_SETTINGS_DEFAULTS });
});

test("corrupt mirror JSON reads as the defaults (never throws)", () => {
  const store = install();
  store.set(LS_KEY, "{not json");
  assert.deepStrictEqual(readOverlaySettings(), { ...OVERLAY_SETTINGS_DEFAULTS });
});

test("numeric settings clamp to the shell bounds", () => {
  install();
  assert.strictEqual(writeOverlaySettings({ activeRevertSec: 1 }).activeRevertSec, 3);
  assert.strictEqual(writeOverlaySettings({ activeRevertSec: 999 }).activeRevertSec, 120);
  assert.strictEqual(writeOverlaySettings({ activeRevertSec: 44.6 }).activeRevertSec, 45);
  assert.strictEqual(writeOverlaySettings({ overlayOpacity: 0.1 }).overlayOpacity, 0.3);
  assert.strictEqual(writeOverlaySettings({ overlayOpacity: 0.456 }).overlayOpacity, 0.46);
});

test("a numeric STRING from an <input> value is accepted", () => {
  install();
  assert.strictEqual(writeOverlaySettings({ activeRevertSec: "45" }).activeRevertSec, 45);
  assert.strictEqual(readOverlaySettings().activeRevertSec, 45);
});

test("a tier write mirrors to the shared PGR key", () => {
  const store = install();
  assert.strictEqual(writeOverlaySettings({ benchmarkRankTier: "Gold" }).benchmarkRankTier, "gold");
  assert.strictEqual(store.get(PGR_RANK_KEY), "gold");
});

// ---- F3: blank / non-numeric patch values must not clamp to the floor --------

test("blank / null / boolean / array activeRevertSec keeps the current value", () => {
  install();
  writeOverlaySettings({ activeRevertSec: 45 });
  for (const junk of ["", "   ", null, true, false, [], [7], "abc", NaN, Infinity]) {
    const r = writeOverlaySettings({ activeRevertSec: junk });
    assert.strictEqual(r.activeRevertSec, 45, `activeRevertSec ${JSON.stringify(junk)}`);
  }
  assert.strictEqual(readOverlaySettings().activeRevertSec, 45);
});

test("blank / null / boolean overlayOpacity keeps the current value", () => {
  install();
  writeOverlaySettings({ overlayOpacity: 0.8 });
  for (const junk of ["", null, true, false, [], "x"]) {
    const r = writeOverlaySettings({ overlayOpacity: junk });
    assert.strictEqual(r.overlayOpacity, 0.8, `overlayOpacity ${JSON.stringify(junk)}`);
  }
});

test("a mirror holding a non-number reads as the default, not the floor", () => {
  const store = install();
  store.set(LS_KEY, JSON.stringify({ activeRevertSec: null, overlayOpacity: "" }));
  const s = readOverlaySettings();
  assert.strictEqual(s.activeRevertSec, OVERLAY_SETTINGS_DEFAULTS.activeRevertSec);
  assert.strictEqual(s.overlayOpacity, OVERLAY_SETTINGS_DEFAULTS.overlayOpacity);
});

test("the shell bridge never receives a junk numeric", () => {
  const sent = [];
  install({ rcShell: { setOverlaySettings: (s) => sent.push(s) } });
  writeOverlaySettings({ activeRevertSec: 60 });
  writeOverlaySettings({ activeRevertSec: "" });
  assert.strictEqual(sent.at(-1).activeRevertSec, 60);
});

// ---- F4: the shared PGR key is the single source of truth, "" included ------

test("PGR key explicitly cleared to off overrides a stale mirror tier", () => {
  const store = install();
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  // The PGR page / desktop Settings "off" option writes "" to the shared key.
  store.set(PGR_RANK_KEY, "");
  assert.strictEqual(readBenchmarkRankTier(), "");
  assert.strictEqual(readOverlaySettings().benchmarkRankTier, "");
});

test("PGR key absent falls back to the mirror tier", () => {
  const store = install();
  store.set(LS_KEY, JSON.stringify({ benchmarkRankTier: "diamond" }));
  assert.strictEqual(readBenchmarkRankTier(), "diamond");
});

test("PGR key wins over the mirror when set", () => {
  const store = install();
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  store.set(PGR_RANK_KEY, "emerald");
  assert.strictEqual(readBenchmarkRankTier(), "emerald");
});

test("a junk PGR value reads as off", () => {
  const store = install();
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  store.set(PGR_RANK_KEY, "wood");
  assert.strictEqual(readBenchmarkRankTier(), "");
});

test("re-selecting the stale mirror tier after an off on the PGR page re-mirrors it", () => {
  const store = install();
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  store.set(PGR_RANK_KEY, "");
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  assert.strictEqual(store.get(PGR_RANK_KEY), "gold");
});

test("writing the mirror's tier while the PGR key is absent creates the key", () => {
  const store = install();
  store.set(LS_KEY, JSON.stringify({ benchmarkRankTier: "diamond" }));
  writeOverlaySettings({ benchmarkRankTier: "diamond" });
  assert.strictEqual(store.get(PGR_RANK_KEY), "diamond");
});

test("the repaint event fires only when the resolved tier changes", () => {
  let fired = 0;
  install({ dispatchEvent: () => (fired += 1) });
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  writeOverlaySettings({ benchmarkRankTier: "gold" });
  assert.strictEqual(fired, 1);
});

// ---- F1 / F2: hydrate must not wipe page-only keys --------------------------

test("hydrate keeps the page-only role override the shell does not carry", async () => {
  install({ rcShell: { getOverlaySettings: () => Promise.resolve(shellReply({ pulseNotify: false })) } });
  writeRoleOverride("jungle");
  const s = await hydrateOverlaySettings();
  assert.strictEqual(s.pulseNotify, false, "shell-owned key applied");
  assert.strictEqual(s.roleOverride, "jungle", "returned role kept");
  assert.strictEqual(readRoleOverride(), "jungle", "mirror role kept");
});

test("hydrate keeps the mirror tier when the PGR key is absent", async () => {
  const store = install({ rcShell: { getOverlaySettings: () => shellReply() } });
  store.set(LS_KEY, JSON.stringify({ benchmarkRankTier: "silver" }));
  const s = await hydrateOverlaySettings();
  assert.strictEqual(s.benchmarkRankTier, "silver");
  assert.strictEqual(readBenchmarkRankTier(), "silver");
});

test("hydrate's return value honours the PGR key like readOverlaySettings", async () => {
  const store = install({ rcShell: { getOverlaySettings: () => shellReply() } });
  store.set(PGR_RANK_KEY, "master");
  const s = await hydrateOverlaySettings();
  assert.strictEqual(s.benchmarkRankTier, "master");
  assert.deepStrictEqual(s, readOverlaySettings());
});

test("hydrate with a non-object shell reply leaves the mirror untouched", async () => {
  for (const reply of [undefined, null, [], "x", 5]) {
    const store = install({ rcShell: { getOverlaySettings: () => reply } });
    writeOverlaySettings({ activeRevertSec: 70, roleOverride: "mid" });
    const before = store.get(LS_KEY);
    let writes = 0;
    const realSet = globalThis.localStorage.setItem;
    globalThis.localStorage.setItem = (k, v) => {
      writes += 1;
      realSet(k, v);
    };
    const s = await hydrateOverlaySettings();
    assert.strictEqual(writes, 0, `no mirror write for ${JSON.stringify(reply)}`);
    assert.strictEqual(store.get(LS_KEY), before, `mirror kept for ${JSON.stringify(reply)}`);
    assert.strictEqual(s.activeRevertSec, 70);
    assert.strictEqual(s.roleOverride, "mid");
  }
});

test("hydrate never rejects when the bridge throws or rejects", async () => {
  install({ rcShell: { getOverlaySettings: () => Promise.reject(new Error("ipc")) } });
  assert.deepStrictEqual(await hydrateOverlaySettings(), readOverlaySettings());
  install({
    rcShell: {
      getOverlaySettings: () => {
        throw new Error("sync");
      },
    },
  });
  assert.deepStrictEqual(await hydrateOverlaySettings(), readOverlaySettings());
});

test("hydrate in a plain browser returns the local mirror", async () => {
  install();
  writeOverlaySettings({ separateWindows: false });
  const s = await hydrateOverlaySettings();
  assert.strictEqual(s.separateWindows, false);
});

// ---- F5 / F6: input shape at the IPC and patch boundaries -------------------

test("sendOverlayAction forwards only a plain object with a string action", () => {
  const got = [];
  install({ rcShell: { overlayAction: (m) => got.push(m) } });
  for (const junk of [undefined, null, "set-active", 5, [], {}, { action: 7 }, { action: "" }]) {
    assert.strictEqual(sendOverlayAction(junk), false, `rejected ${JSON.stringify(junk)}`);
  }
  assert.strictEqual(got.length, 0);
  assert.strictEqual(sendOverlayAction({ action: "set-active" }), true);
  assert.deepStrictEqual(got, [{ action: "set-active" }]);
});

test("sendOverlayAction is false without a bridge", () => {
  install();
  assert.strictEqual(sendOverlayAction({ action: "set-active" }), false);
});

test("a non-string tier / role patch never throws and resolves to off / auto", () => {
  install();
  const evil = {
    toString() {
      throw new Error("boom");
    },
  };
  const r = writeOverlaySettings({ benchmarkRankTier: evil, roleOverride: evil });
  assert.strictEqual(r.benchmarkRankTier, "");
  assert.strictEqual(r.roleOverride, "");
});

test("a non-object patch is a no-op that still returns the settings", () => {
  install();
  writeOverlaySettings({ activeRevertSec: 33 });
  for (const junk of [undefined, null, "x", 5, []]) {
    assert.strictEqual(writeOverlaySettings(junk).activeRevertSec, 33);
  }
});
