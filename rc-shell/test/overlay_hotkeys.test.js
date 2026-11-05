// rc-shell/test/overlay_hotkeys.test.js
//
// RC-HOTKEY-HINTS (docs/OVERLAY_DOCTRINE.md section 11): the shell is the binding
// authority the overlay page's reminders read. The pure map is driven here; the
// preload + ipcMain wiring only runs under Electron, so it is pinned as text, the
// same posture as overlay_settings_ipc.test.js. The live round trip in a running
// shell is OWED: the merger adds row RM-1272 to docs/LIVE_GAME_GATED_SYNC.md at
// landing, and it does not exist before that.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const url = require("node:url");

const ov = require("../src/overlay_state");
const tog = require("../src/overlay_toggle");

const SRC = path.join(__dirname, "..", "src");
const preload = fs.readFileSync(path.join(SRC, "preload.js"), "utf8");
const mainjs = fs.readFileSync(path.join(SRC, "main.js"), "utf8");
const CHANNEL = "rc-shell:overlay-hotkeys:get";

async function pageModule() {
  const file = path.join(__dirname, "..", "..", "web", "js", "lib", "overlay_hotkeys.js");
  return import(url.pathToFileURL(file).href);
}

test("overlayHotkeyMap reads the constants the shell actually uses", () => {
  const map = ov.overlayHotkeyMap(tog.TOGGLE_DEFAULTS.hotkey);
  assert.strictEqual(map.active, ov.OVERLAY_DEFAULTS.hotkeyActive);
  assert.strictEqual(map.visible, tog.TOGGLE_DEFAULTS.hotkey);
  assert.strictEqual(map.hide, ov.OVERLAY_DEFAULTS.hotkeyToggle);
  assert.strictEqual(map.reset, ov.OVERLAY_DEFAULTS.hotkeyReset);
  assert.strictEqual(ov.overlayHotkeyMap(undefined).visible, "");
  // The panel-cycle key only reloads the window today, so no reminder reads it.
  assert.deepStrictEqual(Object.keys(map).sort(), ["active", "hide", "reset", "visible"]);
});

test("the page's fallback map is the shell's map, key for key", async () => {
  const { HOTKEY_DEFAULTS } = await pageModule();
  assert.deepStrictEqual(
    { ...ov.overlayHotkeyMap(tog.TOGGLE_DEFAULTS.hotkey) },
    { ...HOTKEY_DEFAULTS }
  );
});

test("the page refuses a malformed binding and keeps the last good one", async () => {
  const { hydrateOverlayHotkeys, hotkeyFor, _internals } = await pageModule();
  globalThis.window = {
    rcShell: {
      getOverlayHotkeys: async () => ({
        active: "Ctrl+Alt+Z",
        visible: "<b>x</b>",
        hide: "A".repeat(33),
        reset: 42,
      }),
    },
  };
  try {
    _internals._resetForTest();
    const before = { visible: hotkeyFor("visible"), hide: hotkeyFor("hide"), reset: hotkeyFor("reset") };
    assert.strictEqual(await hydrateOverlayHotkeys(), true);
    assert.strictEqual(hotkeyFor("active"), "Ctrl+Alt+Z");
    assert.strictEqual(hotkeyFor("visible"), before.visible);
    assert.strictEqual(hotkeyFor("hide"), before.hide);
    assert.strictEqual(hotkeyFor("reset"), before.reset);
    // No bridge, or a bridge that rejects: false, never a throw.
    globalThis.window = {};
    assert.strictEqual(await hydrateOverlayHotkeys(), false);
    globalThis.window = { rcShell: { getOverlayHotkeys: () => Promise.reject(new Error("x")) } };
    assert.strictEqual(await hydrateOverlayHotkeys(), false);
    globalThis.window = { rcShell: { getOverlayHotkeys: () => { throw new Error("x"); } } };
    assert.strictEqual(await hydrateOverlayHotkeys(), false);
  } finally {
    delete globalThis.window;
    _internals._resetForTest();
  }
});

test("hotkeyActionFor: the interactive set, a registered extra, nothing else", async () => {
  const { hotkeyActionFor, WIDGET_HOTKEYS } = await pageModule();
  for (const id of Object.keys(WIDGET_HOTKEYS)) {
    assert.strictEqual(hotkeyActionFor({ id }), WIDGET_HOTKEYS[id], id);
  }
  assert.strictEqual(hotkeyActionFor({ id: "w-lead" }), "");
  assert.strictEqual(hotkeyActionFor({ id: "w-x", hotkey: "visible" }), "visible");
  assert.strictEqual(hotkeyActionFor({ id: "w-x", hotkey: "cycle" }), "");
  assert.strictEqual(hotkeyActionFor({ id: "w-x", hotkey: "nope" }), "");
  assert.strictEqual(hotkeyActionFor(null), "");
});

test("the wiring exists: an allow-listed bridge method over a trusted handler", () => {
  assert.ok(preload.includes(`getOverlayHotkeys: () => ipcRenderer.invoke("${CHANNEL}")`));
  const at = mainjs.indexOf(`ipcMain.handle("${CHANNEL}"`);
  assert.notStrictEqual(at, -1, "main.js handles the channel");
  const body = mainjs.slice(at, at + 220);
  assert.ok(body.includes("trustedSender(event)"), "the handler gates on the sender");
  assert.ok(body.includes("ov.overlayHotkeyMap(tog.TOGGLE_DEFAULTS.hotkey)"), body);
});

test("the ON/OFF icon's tooltip names the authority's key", () => {
  const page = require("../src/overlay_toggle_page");
  const attrs = {};
  const btn = {
    setAttribute: (k, v) => { attrs[k] = v; },
    classList: { toggle() {} },
  };
  page.render(btn, true);
  assert.ok(btn.title.includes(tog.TOGGLE_DEFAULTS.hotkey), btn.title);
  // The accessible name stays the label; the key is the tooltip's job.
  assert.strictEqual(attrs["aria-label"], tog.TOGGLE_DEFAULTS.label);
});
