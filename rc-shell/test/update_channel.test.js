// rc-shell/test/update_channel.test.js
//
// node:test for the PURE update-channel module (no electron) - Phase 5
// stabilization: stable/dev release channels + the update-check plan.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const upd = require("../src/update_channel");

// --- constants ---------------------------------------------------------------

test("CHANNELS: exactly stable + dev; DEFAULT_CHANNEL is stable", () => {
  assert.deepStrictEqual(upd.CHANNELS, ["stable", "dev"]);
  assert.strictEqual(upd.DEFAULT_CHANNEL, "stable");
});

// --- resolveChannel precedence ------------------------------------------------

test("resolveChannel: env beats saved beats default", () => {
  assert.strictEqual(
    upd.resolveChannel({ updateChannel: "stable" }, { RC_SHELL_CHANNEL: "dev" }),
    "dev"
  );
  assert.strictEqual(upd.resolveChannel({ updateChannel: "dev" }, {}), "dev");
  assert.strictEqual(upd.resolveChannel({}, {}), "stable");
});

test("resolveChannel: null/undefined saved or env tolerated", () => {
  assert.strictEqual(upd.resolveChannel(null, null), "stable");
  assert.strictEqual(upd.resolveChannel(undefined, undefined), "stable");
  assert.strictEqual(upd.resolveChannel(null, { RC_SHELL_CHANNEL: "dev" }), "dev");
  assert.strictEqual(upd.resolveChannel({ updateChannel: "dev" }, null), "dev");
});

test("resolveChannel: invalid env falls through to saved, then default", () => {
  // env garbage + valid saved -> saved wins.
  assert.strictEqual(
    upd.resolveChannel({ updateChannel: "dev" }, { RC_SHELL_CHANNEL: "nightly" }),
    "dev"
  );
  // env garbage + saved garbage -> default.
  assert.strictEqual(
    upd.resolveChannel({ updateChannel: "beta" }, { RC_SHELL_CHANNEL: "canary" }),
    "stable"
  );
  // blank env (set-but-empty) is unset, not garbage.
  assert.strictEqual(
    upd.resolveChannel({ updateChannel: "dev" }, { RC_SHELL_CHANNEL: "   " }),
    "dev"
  );
});

test("resolveChannel: wrong-type saved/env values fall back", () => {
  assert.strictEqual(upd.resolveChannel({ updateChannel: 42 }, {}), "stable");
  assert.strictEqual(upd.resolveChannel({ updateChannel: null }, {}), "stable");
  assert.strictEqual(upd.resolveChannel({ updateChannel: ["dev"] }, {}), "stable");
  assert.strictEqual(upd.resolveChannel({}, { RC_SHELL_CHANNEL: 7 }), "stable");
  assert.strictEqual(upd.resolveChannel("garbage", "garbage"), "stable");
});

test("resolveChannel: trims + lowercases input", () => {
  assert.strictEqual(upd.resolveChannel({}, { RC_SHELL_CHANNEL: "  DEV  " }), "dev");
  assert.strictEqual(upd.resolveChannel({ updateChannel: " Stable " }, {}), "stable");
  assert.strictEqual(upd.resolveChannel({ updateChannel: "DeV" }, {}), "dev");
});

// --- channelConfig --------------------------------------------------------------

test("channelConfig: dev rides prereleases, stable does not", () => {
  assert.deepStrictEqual(upd.channelConfig("dev"), {
    channel: "dev",
    allowPrerelease: true,
  });
  assert.deepStrictEqual(upd.channelConfig("stable"), {
    channel: "stable",
    allowPrerelease: false,
  });
});

test("channelConfig: garbage input resolves to the stable default", () => {
  assert.deepStrictEqual(upd.channelConfig("nightly"), {
    channel: "stable",
    allowPrerelease: false,
  });
  assert.deepStrictEqual(upd.channelConfig(null), {
    channel: "stable",
    allowPrerelease: false,
  });
  // normalization applies before the mapping.
  assert.deepStrictEqual(upd.channelConfig("  DEV "), {
    channel: "dev",
    allowPrerelease: true,
  });
});

// --- mergeChannelPatch -----------------------------------------------------------

test("mergeChannelPatch: preserves every sibling key", () => {
  const prev = {
    x: 10,
    y: 20,
    sizePreset: "standard",
    overlay: { x: 1, y: 2, panelSet: "coach" },
  };
  const next = upd.mergeChannelPatch(prev, "dev");
  assert.strictEqual(next.updateChannel, "dev");
  assert.strictEqual(next.x, 10);
  assert.strictEqual(next.y, 20);
  assert.strictEqual(next.sizePreset, "standard");
  assert.deepStrictEqual(next.overlay, { x: 1, y: 2, panelSet: "coach" });
});

test("mergeChannelPatch: does not mutate the input", () => {
  const prev = { x: 1, updateChannel: "stable" };
  const frozen = JSON.stringify(prev);
  const next = upd.mergeChannelPatch(prev, "dev");
  assert.notStrictEqual(next, prev);
  assert.strictEqual(JSON.stringify(prev), frozen);
  assert.strictEqual(prev.updateChannel, "stable");
});

test("mergeChannelPatch: validates the channel; garbage prev starts fresh", () => {
  // garbage channel -> stable default lands in the patch.
  assert.strictEqual(upd.mergeChannelPatch({}, "nightly").updateChannel, "stable");
  assert.strictEqual(upd.mergeChannelPatch({}, " DEV ").updateChannel, "dev");
  // non-object prev tolerated.
  assert.deepStrictEqual(upd.mergeChannelPatch(null, "dev"), { updateChannel: "dev" });
  assert.deepStrictEqual(upd.mergeChannelPatch("junk", "dev"), {
    updateChannel: "dev",
  });
});

// --- checkPlan ---------------------------------------------------------------------

test("checkPlan: not packaged -> disabled with reason not-packaged", () => {
  const plan = upd.checkPlan({ isPackaged: false, updaterPresent: true });
  assert.strictEqual(plan.enabled, false);
  assert.strictEqual(plan.reason, "not-packaged");
});

test("checkPlan: updater missing -> disabled with reason updater-missing", () => {
  const plan = upd.checkPlan({ isPackaged: true, updaterPresent: false });
  assert.strictEqual(plan.enabled, false);
  assert.strictEqual(plan.reason, "updater-missing");
});

test("checkPlan: enabled defaults - 15s initial delay, 4h interval", () => {
  const plan = upd.checkPlan({ isPackaged: true, updaterPresent: true });
  assert.strictEqual(plan.enabled, true);
  assert.strictEqual(plan.reason, "ok");
  assert.strictEqual(plan.initialDelayMs, 15000);
  assert.strictEqual(plan.intervalMs, 14400000);
});

test("checkPlan: positive finite interval override is honored", () => {
  const plan = upd.checkPlan({
    isPackaged: true,
    updaterPresent: true,
    intervalMs: 60000,
  });
  assert.strictEqual(plan.enabled, true);
  assert.strictEqual(plan.intervalMs, 60000);
});

test("checkPlan: garbage interval override falls back to the default", () => {
  for (const bad of [0, -5, NaN, Infinity, "60000", null]) {
    const plan = upd.checkPlan({
      isPackaged: true,
      updaterPresent: true,
      intervalMs: bad,
    });
    assert.strictEqual(plan.intervalMs, 14400000, JSON.stringify(bad));
  }
});

test("checkPlan: garbage opts tolerated (treated as not packaged)", () => {
  assert.strictEqual(upd.checkPlan(null).enabled, false);
  assert.strictEqual(upd.checkPlan(undefined).enabled, false);
  assert.strictEqual(upd.checkPlan(null).reason, "not-packaged");
});
