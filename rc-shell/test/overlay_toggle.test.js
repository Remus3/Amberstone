// rc-shell/test/overlay_toggle.test.js
//
// S134 operator request: "the ingame overlay [should] have a toggle icon
// [movable] to enable or disable the visual overlay."
//
// The toggle is its OWN tiny always-on-top window (rc-shell/src/overlay_toggle
// .html), separate from the fullscreen overlay window, because the icon must
// stay visible while the overlay content is hidden. This suite pins:
//   - the pure core (src/overlay_toggle.js): on/off state + persistence merge,
//     per-display position resolve + on-screen clamp after a resolution or
//     monitor change, the tap-vs-drag state machine, the surface gate and the
//     IPC allow-list;
//   - the page (src/overlay_toggle_page.js) driven through a hand-rolled DOM
//     stub (the harness ships no jsdom - same approach as overlay_flash.test.js);
//   - the main.js wiring by reading the source off disk (same approach as
//     overlay_display_change.test.js / overlay_settings_ipc.test.js), because the
//     window options are what keeps the icon from ever taking focus off the game.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const tog = require("../src/overlay_toggle");
const ov = require("../src/overlay_state");
const page = require("../src/overlay_toggle_page");

const SRC = path.join(__dirname, "..", "src");
const MAIN_SRC = fs.readFileSync(path.join(SRC, "main.js"), "utf8");
const HTML_SRC = fs.readFileSync(path.join(SRC, "overlay_toggle.html"), "utf8");
const PRELOAD_SRC = fs.readFileSync(path.join(SRC, "toggle_preload.js"), "utf8");

const D1080 = { id: 1, bounds: { x: 0, y: 0, width: 1920, height: 1080 } };
const D1440 = { id: 1, bounds: { x: 0, y: 0, width: 2560, height: 1440 } };
const LEFT = { id: 2, bounds: { x: -1920, y: 0, width: 1920, height: 1080 } };

function onScreen(r, b) {
  return (
    r.x >= b.x &&
    r.y >= b.y &&
    r.x + r.width <= b.x + b.width &&
    r.y + r.height <= b.y + b.height
  );
}

// --- on/off state + persistence ----------------------------------------------

test("default is ON when nothing is saved", () => {
  assert.strictEqual(tog.TOGGLE_DEFAULTS.visible, true);
  assert.strictEqual(tog.toggleStateFrom({}).visible, true);
  assert.strictEqual(tog.toggleStateFrom(undefined).visible, true);
  assert.strictEqual(tog.toggleStateFrom({ overlay: { toggle: {} } }).visible, true);
});

test("a persisted OFF is honored; a non-boolean falls back to the ON default", () => {
  assert.strictEqual(tog.toggleStateFrom({ overlay: { toggle: { visible: false } } }).visible, false);
  assert.strictEqual(tog.toggleStateFrom({ overlay: { toggle: { visible: true } } }).visible, true);
  for (const junk of ["false", 0, null, [], {}]) {
    assert.strictEqual(
      tog.toggleStateFrom({ overlay: { toggle: { visible: junk } } }).visible,
      true,
      JSON.stringify(junk)
    );
  }
});

test("merge keeps every sibling key and never mutates its inputs", () => {
  const prev = {
    x: 10,
    y: 20,
    sizePreset: "standard",
    overlay: {
      x: 5,
      panelSet: "build",
      settings: { overlayOpacity: 0.8 },
      widgetLayout: { "w-call": { x: 1, y: 2 } },
      toggle: { visible: true, pos: { displayId: 1, fx: 0.5, fy: 0.5 } },
    },
  };
  const snapshot = JSON.stringify(prev);
  const next = tog.mergeToggleStatePatch(prev, { visible: false });
  assert.strictEqual(JSON.stringify(prev), snapshot, "prev mutated");
  assert.strictEqual(next.x, 10);
  assert.strictEqual(next.sizePreset, "standard");
  assert.strictEqual(next.overlay.panelSet, "build");
  assert.deepStrictEqual(next.overlay.settings, { overlayOpacity: 0.8 });
  assert.deepStrictEqual(next.overlay.widgetLayout, { "w-call": { x: 1, y: 2 } });
  assert.strictEqual(next.overlay.toggle.visible, false);
  // The position survives a visibility-only patch.
  assert.deepStrictEqual(tog.toggleStateFrom(next).pos, { displayId: 1, fx: 0.5, fy: 0.5, x: null, y: null });
});

test("merge drops garbage fields and a null pos clears the saved position", () => {
  const a = tog.mergeToggleStatePatch({}, { visible: "no", pos: { fx: "x" }, extra: 1 });
  assert.deepStrictEqual(a.overlay.toggle, {});
  const b = tog.mergeToggleStatePatch(
    { overlay: { toggle: { visible: false, pos: { displayId: 1, fx: 0.1, fy: 0.1 } } } },
    { pos: null }
  );
  assert.strictEqual(b.overlay.toggle.visible, false);
  assert.strictEqual(tog.toggleStateFrom(b).pos, null);
  // Garbage prev starts fresh instead of throwing.
  for (const junk of [null, 7, "s", []]) {
    const c = tog.mergeToggleStatePatch(junk, { visible: false });
    assert.strictEqual(c.overlay.toggle.visible, false);
  }
});

test("the saved position fractions are clamped to [0,1]", () => {
  const s = tog.toggleStateFrom({ overlay: { toggle: { pos: { displayId: 3, fx: 4, fy: -2 } } } });
  assert.deepStrictEqual(s.pos, { displayId: 3, fx: 1, fy: 0, x: null, y: null });
  assert.strictEqual(tog.toggleStateFrom({ overlay: { toggle: { pos: { fx: NaN, fy: 0 } } } }).pos, null);
});

// --- size + default position ----------------------------------------------------

test("the hit target is never under 24px on any display", () => {
  assert.ok(tog.TOGGLE_DEFAULTS.minSize >= 24);
  for (const b of [
    { x: 0, y: 0, width: 800, height: 600 },
    { x: 0, y: 0, width: 1280, height: 720 },
    D1080.bounds,
    D1440.bounds,
    { x: 0, y: 0, width: 3840, height: 2160 },
  ]) {
    assert.ok(tog.toggleSize(b) >= 24, JSON.stringify(b));
  }
  assert.strictEqual(tog.toggleSize(D1080.bounds), tog.TOGGLE_DEFAULTS.baseSize);
  assert.ok(tog.toggleSize(D1440.bounds) > tog.toggleSize(D1080.bounds), "grows with the HUD scale");
});

test("no saved position lands under the in-overlay launcher on the primary display", () => {
  const r = tog.resolveToggleBounds(null, [D1080], 1);
  assert.deepStrictEqual(
    { x: r.x, y: r.y, width: r.width, height: r.height, displayId: r.displayId },
    { x: tog.TOGGLE_DEFAULTS.designX, y: tog.TOGGLE_DEFAULTS.designY, width: 32, height: 32, displayId: 1 }
  );
  // Below the w-launcher square (design 24,24 + 34px) so the two never stack.
  assert.ok(tog.TOGGLE_DEFAULTS.designY >= 24 + 34 + 8);
  // At 1440 the default scales with the HUD body zoom, like the launcher does.
  const s = ov.resolveOverlayScale(D1440.bounds);
  const q = tog.resolveToggleBounds(null, [D1440], 1);
  assert.strictEqual(q.x, Math.round(tog.TOGGLE_DEFAULTS.designX * s));
  assert.strictEqual(q.y, Math.round(tog.TOGGLE_DEFAULTS.designY * s));
});

test("the primary display is the default even when it is not listed first", () => {
  const r = tog.resolveToggleBounds(null, [LEFT, D1080], 1);
  assert.strictEqual(r.displayId, 1);
  assert.ok(onScreen(r, D1080.bounds));
});

test("garbage displays fall back to a sane 1920x1080 box, never throw", () => {
  for (const junk of [undefined, null, [], [null], [{ id: 1 }], "x", [{ bounds: { width: -1 } }]]) {
    const r = tog.resolveToggleBounds(null, junk, undefined);
    assert.ok(Number.isFinite(r.x) && Number.isFinite(r.y), JSON.stringify(junk));
    assert.ok(onScreen(r, { x: 0, y: 0, width: 1920, height: 1080 }), JSON.stringify(junk));
  }
});

// --- per-display persistence + clamp after a resolution / monitor change ------------

test("a saved position round-trips exactly on the same display", () => {
  const size = tog.toggleSize(D1440.bounds);
  const pos = tog.posFromWindow({ x: 1700, y: 900 }, size, D1440);
  assert.strictEqual(pos.displayId, 1);
  const r = tog.resolveToggleBounds(pos, [D1440], 1);
  assert.strictEqual(r.x, 1700);
  assert.strictEqual(r.y, 900);
});

test("a resolution drop keeps the icon in the same relative spot and on-screen", () => {
  // Parked bottom-right at 1440, then the game flips the display to 1080.
  const size = tog.toggleSize(D1440.bounds);
  const pos = tog.posFromWindow({ x: 2560 - size, y: 1440 - size }, size, D1440);
  const r = tog.resolveToggleBounds(pos, [D1080], 1);
  assert.ok(onScreen(r, D1080.bounds), JSON.stringify(r));
  assert.strictEqual(r.x + r.width, 1920, "still flush right");
  assert.strictEqual(r.y + r.height, 1080, "still flush bottom");
});

test("a saved spot on a monitor that is gone moves to the nearest display, clamped", () => {
  const pos = tog.posFromWindow({ x: -400, y: 500 }, 32, LEFT);
  assert.strictEqual(pos.displayId, 2);
  // The left monitor was unplugged; only the primary remains.
  const r = tog.resolveToggleBounds(pos, [D1080], 1);
  assert.strictEqual(r.displayId, 1);
  assert.ok(onScreen(r, D1080.bounds), JSON.stringify(r));
});

test("a secondary display at negative coordinates is honored when present", () => {
  const pos = tog.posFromWindow({ x: -1000, y: 300 }, 32, LEFT);
  const r = tog.resolveToggleBounds(pos, [D1080, LEFT], 1);
  assert.strictEqual(r.displayId, 2);
  assert.strictEqual(r.x, -1000);
  assert.strictEqual(r.y, 300);
  assert.ok(onScreen(r, LEFT.bounds));
});

test("a hand-edited off-screen absolute position is pulled back on-screen", () => {
  const r = tog.resolveToggleBounds({ displayId: 99, fx: 0.5, fy: 0.5, x: 99999, y: 99999 }, [D1080], 1);
  assert.ok(onScreen(r, D1080.bounds), JSON.stringify(r));
});

test("clampToggleToBounds pins every edge", () => {
  const b = D1080.bounds;
  assert.deepStrictEqual(tog.clampToggleToBounds({ x: 5000, y: 5000 }, 32, b), { x: 1888, y: 1048 });
  assert.deepStrictEqual(tog.clampToggleToBounds({ x: -50, y: -50 }, 32, b), { x: 0, y: 0 });
  assert.deepStrictEqual(tog.clampToggleToBounds({ x: 100.4, y: 200.6 }, 32, b), { x: 100, y: 201 });
});

// --- tap vs drag --------------------------------------------------------------

test("a press that never passes the threshold is a TAP", () => {
  const d = tog.makeToggleDrag({});
  d.press({ x: 100, y: 100 }, { x: 90, y: 90 });
  assert.strictEqual(d.move({ x: 102, y: 103 }), null, "inside the threshold is not a drag");
  assert.strictEqual(d.release(), "tap");
  assert.strictEqual(d.pressed(), false);
});

test("a press that moves past the threshold DRAGS the window and is never a tap", () => {
  const d = tog.makeToggleDrag({ thresholdPx: 4 });
  d.press({ x: 100, y: 100 }, { x: 90, y: 90 });
  assert.deepStrictEqual(d.move({ x: 110, y: 100 }), { x: 100, y: 90 });
  // Once dragging, even a move back inside the threshold keeps tracking.
  assert.deepStrictEqual(d.move({ x: 101, y: 101 }), { x: 91, y: 91 });
  assert.strictEqual(d.release(), "drag");
});

test("release / move without a press are inert; cancel never taps", () => {
  const d = tog.makeToggleDrag({});
  assert.strictEqual(d.move({ x: 1, y: 1 }), null);
  assert.strictEqual(d.release(), "none");
  d.press({ x: 0, y: 0 }, { x: 0, y: 0 });
  assert.strictEqual(d.cancel(), "none", "an unmoved cancel must not toggle");
  d.press({ x: 0, y: 0 }, { x: 0, y: 0 });
  d.move({ x: 50, y: 0 });
  assert.strictEqual(d.cancel(), "drag", "a moved cancel still persists the new spot");
  assert.strictEqual(d.release(), "none", "a release after cancel is a no-op");
});

test("garbage cursor points never produce a NaN window position", () => {
  const d = tog.makeToggleDrag({});
  assert.strictEqual(d.press(null, { x: 0, y: 0 }), false);
  assert.strictEqual(d.pressed(), false);
  d.press({ x: 0, y: 0 }, { x: 0, y: 0 });
  assert.strictEqual(d.move({ x: NaN, y: 3 }), null);
});

// --- surface gate ---------------------------------------------------------------

test("in a game the icon shows in BOTH content states; the overlay follows the toggle", () => {
  const base = ov.windowActions(ov.SURFACES.OVERLAY);
  assert.deepStrictEqual(tog.applyContentToggle(base, ov.SURFACES.OVERLAY, true), {
    companion: "hide",
    overlay: "show",
    toggle: "show",
  });
  assert.deepStrictEqual(tog.applyContentToggle(base, ov.SURFACES.OVERLAY, false), {
    companion: "hide",
    overlay: "hide",
    toggle: "show",
  });
});

test("out of a game, and under the panic hide, the icon is hidden too", () => {
  for (const s of [ov.SURFACES.COMPANION, ov.SURFACES.HIDDEN, "junk"]) {
    const a = tog.applyContentToggle(ov.windowActions(s), s, true);
    assert.strictEqual(a.toggle, "hide", s);
    assert.strictEqual(a.overlay, "hide", s);
  }
});

test("keepCompanion survives the toggle layer", () => {
  const base = ov.windowActionsWithPolicy(ov.SURFACES.OVERLAY, { keepCompanion: true });
  const a = tog.applyContentToggle(base, ov.SURFACES.OVERLAY, false);
  assert.strictEqual(a.companion, "show");
  assert.strictEqual(a.overlay, "hide");
});

test("only the in-game surface accepts a toggle press or hotkey", () => {
  assert.strictEqual(tog.acceptsToggleInput(ov.SURFACES.OVERLAY), true);
  for (const s of [ov.SURFACES.COMPANION, ov.SURFACES.HIDDEN, null, "overlay "]) {
    assert.strictEqual(tog.acceptsToggleInput(s), false, String(s));
  }
});

test("the toggle IPC is an allow-list", () => {
  for (const a of ["press", "move", "release", "cancel", "activate"]) {
    assert.strictEqual(tog.normToggleAction({ action: a }), a);
  }
  assert.strictEqual(tog.normToggleAction({ action: " Release " }), "release");
  for (const junk of [null, "press", { action: "close" }, { action: 1 }, [], { action: "set-active" }]) {
    assert.strictEqual(tog.normToggleAction(junk), null, JSON.stringify(junk));
  }
});

// --- the page (overlay_toggle_page.js) through a DOM stub ---------------------

function makeStubDom() {
  const listeners = {};
  const attrs = {};
  const classes = new Set();
  const btn = {
    attrs,
    classes,
    captured: [],
    title: "",
    setAttribute(k, v) {
      attrs[k] = String(v);
    },
    getAttribute(k) {
      return k in attrs ? attrs[k] : null;
    },
    classList: {
      toggle(c, on) {
        if (on) classes.add(c);
        else classes.delete(c);
      },
      add(c) {
        classes.add(c);
      },
      remove(c) {
        classes.delete(c);
      },
      contains(c) {
        return classes.has(c);
      },
    },
    addEventListener(t, fn) {
      (listeners[t] = listeners[t] || []).push(fn);
    },
    setPointerCapture(id) {
      this.captured.push(id);
    },
    releasePointerCapture() {},
    fire(t, ev) {
      for (const fn of listeners[t] || []) fn(ev);
    },
  };
  const doc = {
    getElementById(id) {
      return id === "rc-toggle" ? btn : null;
    },
  };
  const frames = [];
  const win = {
    requestAnimationFrame(fn) {
      frames.push(fn);
      return frames.length;
    },
  };
  return { btn, doc, win, frames };
}

function makeBridge(initial) {
  const sent = [];
  let onState = null;
  return {
    sent,
    push(s) {
      onState(s);
    },
    send(a) {
      sent.push(a);
    },
    getState() {
      return Promise.resolve(initial);
    },
    onState(cb) {
      onState = cb;
    },
  };
}

function ev(extra) {
  return Object.assign({ button: 0, pointerId: 7, preventDefault() {} }, extra || {});
}

test("render reflects ON / OFF on aria-pressed + the off class, label fixed", () => {
  const { btn } = makeStubDom();
  page.render(btn, true);
  assert.strictEqual(btn.attrs["aria-pressed"], "true");
  assert.strictEqual(btn.classes.has("off"), false);
  assert.strictEqual(btn.attrs["aria-label"], "Overlay on/off");
  assert.strictEqual(btn.title, "Overlay on/off");
  page.render(btn, false);
  assert.strictEqual(btn.attrs["aria-pressed"], "false");
  assert.strictEqual(btn.classes.has("off"), true);
  // Anything but a strict false renders ON (default ON).
  page.render(btn, undefined);
  assert.strictEqual(btn.attrs["aria-pressed"], "true");
});

test("mount seeds from getState and follows pushed state", async () => {
  const { btn, doc, win } = makeStubDom();
  const bridge = makeBridge({ visible: false });
  page.mount(doc, bridge, win);
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(btn.attrs["aria-pressed"], "false");
  bridge.push({ visible: true });
  assert.strictEqual(btn.attrs["aria-pressed"], "true");
});

test("pointer press / move / release drive the bridge; moves are frame-coalesced", () => {
  const { btn, doc, win, frames } = makeStubDom();
  const bridge = makeBridge({ visible: true });
  page.mount(doc, bridge, win);
  btn.fire("pointerdown", ev());
  assert.deepStrictEqual(bridge.sent, ["press"]);
  assert.deepStrictEqual(btn.captured, [7], "captures the pointer so a fast drag cannot escape");
  btn.fire("pointermove", ev());
  btn.fire("pointermove", ev());
  btn.fire("pointermove", ev());
  assert.strictEqual(frames.length, 1, "one frame scheduled for a burst of moves");
  frames.shift()();
  assert.deepStrictEqual(bridge.sent, ["press", "move"]);
  btn.fire("pointerup", ev());
  assert.deepStrictEqual(bridge.sent, ["press", "move", "release"]);
  // A move after release sends nothing.
  btn.fire("pointermove", ev());
  assert.strictEqual(frames.length, 0);
});

test("a non-primary button is ignored; a lost capture cancels", () => {
  const { btn, doc, win } = makeStubDom();
  const bridge = makeBridge({ visible: true });
  page.mount(doc, bridge, win);
  btn.fire("pointerdown", ev({ button: 2 }));
  assert.deepStrictEqual(bridge.sent, []);
  btn.fire("pointerdown", ev());
  btn.fire("pointercancel", ev());
  assert.deepStrictEqual(bridge.sent, ["press", "cancel"]);
  // A lostpointercapture right after a normal release is a no-op (no double end).
  btn.fire("pointerdown", ev());
  btn.fire("pointerup", ev());
  btn.fire("lostpointercapture", ev());
  assert.deepStrictEqual(bridge.sent, ["press", "cancel", "press", "release"]);
});

test("Enter / Space activate the toggle from the keyboard", () => {
  const { btn, doc, win } = makeStubDom();
  const bridge = makeBridge({ visible: true });
  page.mount(doc, bridge, win);
  btn.fire("keydown", ev({ key: "Enter" }));
  btn.fire("keydown", ev({ key: " " }));
  btn.fire("keydown", ev({ key: "a" }));
  assert.deepStrictEqual(bridge.sent, ["activate", "activate"]);
});

test("mount without a bridge or button never throws", () => {
  const { doc, win } = makeStubDom();
  assert.doesNotThrow(() => page.mount(doc, undefined, win));
  assert.doesNotThrow(() => page.mount({ getElementById: () => null }, makeBridge({}), win));
});

// --- the page markup --------------------------------------------------------------

test("the toggle page is ASCII, labelled, CSP-locked and loads only its local script", () => {
  for (const [name, src] of [
    ["overlay_toggle.html", HTML_SRC],
    ["toggle_preload.js", PRELOAD_SRC],
    ["overlay_toggle.js", fs.readFileSync(path.join(SRC, "overlay_toggle.js"), "utf8")],
    ["overlay_toggle_page.js", fs.readFileSync(path.join(SRC, "overlay_toggle_page.js"), "utf8")],
  ]) {
    assert.ok(/^[\x09\x0a\x20-\x7e]*$/.test(src), name + " must be 7-bit ASCII, LF only");
  }
  assert.match(HTML_SRC, /<button[^>]*id="rc-toggle"/);
  assert.match(HTML_SRC, /aria-label="Overlay on\/off"/);
  assert.match(HTML_SRC, /title="Overlay on\/off"/);
  assert.match(HTML_SRC, /http-equiv="Content-Security-Policy"/);
  assert.match(HTML_SRC, /default-src 'none'/);
  assert.match(HTML_SRC, /<script src="overlay_toggle_page\.js"><\/script>/);
  assert.ok(!/https?:\/\//.test(HTML_SRC.replace(/xmlns="http:\/\/www\.w3\.org\/2000\/svg"/g, "")),
    "the toggle page must load nothing remote");
});

test("the button fills the window so the whole window is the hit area", () => {
  assert.match(HTML_SRC, /#rc-toggle\s*\{[^}]*width:\s*100vw/);
  assert.match(HTML_SRC, /#rc-toggle\s*\{[^}]*height:\s*100vh/);
  assert.match(HTML_SRC, /background:\s*transparent/);
});

test("the preload exposes only the toggle channels", () => {
  assert.match(PRELOAD_SRC, /exposeInMainWorld\("rcToggle"/);
  assert.match(PRELOAD_SRC, /"rc-shell:overlay-toggle"/);
  assert.match(PRELOAD_SRC, /"rc-shell:overlay-toggle:get"/);
  assert.match(PRELOAD_SRC, /"rc-shell:overlay-toggle:state"/);
  assert.ok(!/exposeInMainWorld\("rcShell"/.test(PRELOAD_SRC), "must not re-expose the overlay bridge");
});

// --- main.js wiring (read off disk) -----------------------------------------------

function fnBody(name) {
  const i = MAIN_SRC.indexOf("function " + name + "(");
  assert.ok(i >= 0, "precondition: main.js defines " + name);
  const j = MAIN_SRC.indexOf("\nfunction ", i + 1);
  return MAIN_SRC.slice(i, j < 0 ? undefined : j);
}

test("the toggle window can never take focus or a taskbar slot", () => {
  const fn = fnBody("createToggleWindow");
  for (const re of [
    /focusable:\s*false/,
    /skipTaskbar:\s*true/,
    /alwaysOnTop:\s*true/,
    /transparent:\s*true/,
    /frame:\s*false/,
    /show:\s*false/,
    /sandbox:\s*true/,
    /contextIsolation:\s*true/,
    /nodeIntegration:\s*false/,
    /toggle_preload\.js/,
    /overlay_toggle\.html/,
    /setAlwaysOnTop\(true, "screen-saver"\)/,
  ]) {
    assert.match(fn, re);
  }
  // Every show of the toggle window is inactive; it is never focused.
  assert.ok(!/toggleWindow\.(show|focus)\(\)/.test(MAIN_SRC), "toggle must only showInactive");
  assert.match(MAIN_SRC, /toggleWindow\.showInactive\(\)/);
});

test("applySurface layers the content toggle over the window policy", () => {
  const fn = fnBody("applySurface");
  assert.match(fn, /tog\.applyContentToggle\(/);
  assert.match(fn, /overlayContentOn/);
  assert.match(fn, /actions\.toggle === "show"/);
});

test("the overlay's first-paint show also respects the content toggle", () => {
  const fn = fnBody("createOverlayWindow");
  assert.match(fn, /shouldShowOverlayNow\(\s*overlayReady,\s*lastSurface === ov\.SURFACES\.OVERLAY && overlayContentOn\s*\)/);
});

test("the on/off choice and the dragged position are persisted through the pure merger", () => {
  assert.match(fnBody("setOverlayContent"), /tog\.mergeToggleStatePatch\(/);
  assert.match(fnBody("persistTogglePosition"), /tog\.mergeToggleStatePatch\(/);
  assert.match(fnBody("persistTogglePosition"), /tog\.posFromWindow\(/);
  assert.match(MAIN_SRC, /overlayContentOn = tog\.toggleStateFrom\(saved\)\.visible/);
});

test("the toggle IPC goes through the allow-list and only from the toggle page", () => {
  assert.match(MAIN_SRC, /ipcMain\.on\("rc-shell:overlay-toggle"/);
  assert.match(MAIN_SRC, /ipcMain\.handle\("rc-shell:overlay-toggle:get"/);
  assert.match(MAIN_SRC, /tog\.normToggleAction\(/);
  assert.match(MAIN_SRC, /event\.sender !== toggleWindow\.webContents/);
});

test("the icon is applied AFTER the overlay so a fresh HUD show never covers it", () => {
  const fn = fnBody("applySurface");
  const overlayShow = fn.indexOf("overlayWindow.showInactive()");
  const toggleBranch = fn.indexOf('actions.toggle === "show"');
  assert.ok(overlayShow > 0 && toggleBranch > overlayShow, "toggle branch must follow the overlay show");
  assert.match(fn.slice(toggleBranch), /raiseToggle\(\)/);
  assert.match(fnBody("raiseToggle"), /toggleWindow\.moveTop\(\)/);
});

test("an overlay that takes focus (ACTIVE click) re-lifts the icon above it", () => {
  assert.match(fnBody("createOverlayWindow"), /overlayWindow\.on\("focus", raiseToggle\)/);
});

test("turning the content ON or OFF always lands the HUD PASSIVE", () => {
  const fn = fnBody("setOverlayContent");
  // Unconditional (not inside an OFF-only branch): an ACTIVE flip pressed while
  // OFF must not survive into the next ON.
  assert.ok(!/if \(!overlayContentOn\)/.test(fn), "the PASSIVE reset must not be OFF-only");
  assert.match(fn, /overlayClickThrough = true;/);
  assert.match(fn, /overlayZoneHover = false;/);
  assert.match(fn, /applyClickThrough\(\);/);
  assert.match(fn, /lastSurface = null;/);
});

test("a relaunch tap keeps an operator OFF and raises the icon instead", () => {
  const i = MAIN_SRC.indexOf('app.on("second-instance"');
  assert.ok(i > 0, "precondition: second-instance handler");
  const handler = MAIN_SRC.slice(i, MAIN_SRC.indexOf("app.whenReady()", i));
  assert.match(handler, /if \(overlayContentOn && overlayWindow/);
  assert.match(handler, /raiseToggle\(\);/);
});

test("the state read channel follows the same sender rule as the action channel", () => {
  const i = MAIN_SRC.indexOf('ipcMain.handle("rc-shell:overlay-toggle:get"');
  assert.ok(i > 0);
  assert.match(MAIN_SRC.slice(i, i + 400), /event\.sender !== toggleWindow\.webContents/);
});

test("toggleShowable: only a painted, live, in-game icon may be shown", () => {
  assert.strictEqual(tog.toggleShowable(true, ov.SURFACES.OVERLAY, false), true);
  // A crash-guard give-up keeps the window dark whatever else holds.
  assert.strictEqual(tog.toggleShowable(true, ov.SURFACES.OVERLAY, true), false);
  assert.strictEqual(tog.toggleShowable(false, ov.SURFACES.OVERLAY, false), false, "not painted yet");
  for (const s of [ov.SURFACES.COMPANION, ov.SURFACES.HIDDEN, null]) {
    assert.strictEqual(tog.toggleShowable(true, s, false), false, String(s));
  }
  for (const v of [1, "true", {}, undefined]) {
    assert.strictEqual(tog.toggleShowable(v, ov.SURFACES.OVERLAY, false), false, JSON.stringify(v));
  }
});

test("the ONLY icon show path goes through toggleShowable with the give-up flag", () => {
  const shows = MAIN_SRC.match(/toggleWindow\.showInactive\(\)/g) || [];
  assert.strictEqual(shows.length, 1, "exactly one show site (raiseToggle)");
  const fn = fnBody("raiseToggle");
  assert.match(fn, /toggleWindow\.showInactive\(\)/);
  // The WHOLE condition, so a widened gate (e.g. "|| true") cannot pass.
  assert.match(
    fn,
    /if \(\s*toggleWindow &&\s*!toggleWindow\.isDestroyed\(\) &&\s*tog\.toggleShowable\(toggleReady, lastSurface, toggleGaveUp\)\s*\) \{/
  );
});

test("a crash-looping icon stays dark AND fails safe to overlay content ON", () => {
  assert.match(fnBody("attachCrashGuard"), /onGiveUp\(\)/);
  const fn = fnBody("createToggleWindow");
  const m = fn.match(/attachCrashGuard\(toggleWindow, "toggle", \(\) => \{([\s\S]*?)\n  \}\);/);
  assert.ok(m, "toggle crash guard passes an onGiveUp callback");
  const body = m[1];
  const flag = body.indexOf("toggleGaveUp = true;");
  const on = body.indexOf("setOverlayContent(true)");
  assert.ok(flag >= 0 && on > flag, "mark given-up BEFORE the fail-safe re-apply can re-raise the icon");
});

test("a display change re-clamps the toggle icon", () => {
  const fn = fnBody("scheduleOverlayDisplayReapply");
  assert.match(fn, /applyToggleDisplay\(\)/);
  assert.match(fnBody("applyToggleDisplay"), /resolveToggleBoundsNow\(\)/);
});

test("the keyboard toggle reads the hotkey listener's signal file, gated to in-game", () => {
  // PKG-6 (M3): the file name lives in rc_root.SIGNAL_FILES; main.js watches it
  // under the resolved backend root by key.
  const rcRootSrc = fs.readFileSync(path.join(__dirname, "..", "src", "rc_root.js"), "utf8");
  assert.match(rcRootSrc, /visibleToggle: "overlay_visible_toggle\.txt"/);
  assert.match(fnBody("startVisibleToggleWatch"), /watchSignal\("visibleToggle"/);
  const listener = fs.readFileSync(
    path.join(__dirname, "..", "..", "tools", "hotkey_listener.py"),
    "utf8"
  );
  assert.match(listener, /"overlay_visible_toggle\.txt"/);
  const fn = fnBody("startVisibleToggleWatch");
  assert.match(fn, /tog\.acceptsToggleInput\(/);
  const ready = MAIN_SRC.slice(MAIN_SRC.indexOf("app.whenReady()"));
  assert.match(ready.slice(0, 2500), /startVisibleToggleWatch\(\)/);
});
