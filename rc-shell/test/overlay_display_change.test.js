"use strict";
/**
 * RM-145: the overlay must follow a display-mode change in BOTH directions.
 *
 * `createOverlayWindow` resolved the metrics and assigned `overlayScale` exactly
 * once, at window creation, and main.js registered no display listener at all -
 * so the scale captured when the overlay was built was the scale it kept for the
 * process lifetime. Operator symptom: the game client flipped video modes, the
 * overlay followed the display DOWN to 1920x1080, and correcting the in-game
 * settings back to borderless 1440 did not bring it back. Restarting rc-shell
 * was the only recovery.
 *
 * `resolveOverlayDisplayChange` is the pure decision half of the fix: given the
 * geometry the overlay was last built for and the geometry live now, what has to
 * happen? The two outcomes are deliberately SEPARATE:
 *
 *   reposition - the window box moved or resized -> setBounds is enough.
 *   reload     - the resolved scale changed -> the renderer's body zoom comes
 *                from the `ovscale` URL PARAM, which is baked in at loadURL, so
 *                only a reload can move it.
 *
 * Keeping them apart matters in-game: `display-metrics-changed` also fires for
 * work-area and color-profile changes that leave the overlay geometry alone, and
 * reloading the HUD on a taskbar auto-hide toggle mid-fight would be a visible
 * flash for nothing.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const ov = require("../src/overlay_state.js");

const MAIN_SRC = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

const AT_1440 = { scale: 1.33, x: 0, y: 0, width: 2560, height: 1440 };
const AT_1080 = { scale: 1, x: 0, y: 0, width: 1920, height: 1080 };

test("identical geometry is a no-op in both channels", () => {
  const out = ov.resolveOverlayDisplayChange(AT_1440, { ...AT_1440 });
  assert.deepStrictEqual(out, { reposition: false, reload: false });
});

test("a resolution drop repositions AND reloads", () => {
  const out = ov.resolveOverlayDisplayChange(AT_1440, AT_1080);
  assert.deepStrictEqual(out, { reposition: true, reload: true });
});

test("the reverse direction is handled too - the reported bug", () => {
  // The overlay followed the display down and then could not follow it back up.
  const out = ov.resolveOverlayDisplayChange(AT_1080, AT_1440);
  assert.deepStrictEqual(out, { reposition: true, reload: true });
});

test("a move with no scale change repositions without a reload", () => {
  // Primary display re-origined (monitor re-arranged); same size, same scale.
  const out = ov.resolveOverlayDisplayChange(AT_1440, { ...AT_1440, x: -2560 });
  assert.deepStrictEqual(out, { reposition: true, reload: false });
});

test("a size change the scale clamp absorbs still repositions, no reload", () => {
  // Both 2560x1440 and 3840x2160 clamp to OVERLAY_SCALE_MAX 1.6 -> same ovscale,
  // different box. Repositioning is required; a reload would be a pointless flash.
  const big = ov.resolveOverlayScale({ x: 0, y: 0, width: 3840, height: 2160 });
  const bigger = ov.resolveOverlayScale({ x: 0, y: 0, width: 5120, height: 2880 });
  assert.strictEqual(big, bigger, "precondition: both clamp to the same scale");
  const out = ov.resolveOverlayDisplayChange(
    { scale: big, x: 0, y: 0, width: 3840, height: 2160 },
    { scale: bigger, x: 0, y: 0, width: 5120, height: 2880 }
  );
  assert.deepStrictEqual(out, { reposition: true, reload: false });
});

test("scale change alone reloads without a reposition", () => {
  const out = ov.resolveOverlayDisplayChange(AT_1440, { ...AT_1440, scale: 1.1 });
  assert.deepStrictEqual(out, { reposition: false, reload: true });
});

test("a garbage or absent side re-applies once and self-heals", () => {
  // No previous snapshot yet, or a field that never got a finite value: treat it
  // as differing so ONE apply runs and the stored snapshot becomes clean. The
  // alternative (no-op on garbage) wedges the overlay at a stale scale forever.
  for (const bad of [null, undefined, {}, "nope", { scale: NaN, x: 0, y: 0, width: 2560, height: 1440 }]) {
    const out = ov.resolveOverlayDisplayChange(bad, AT_1440);
    assert.strictEqual(out.reload, true, `expected reload for ${JSON.stringify(bad)}`);
  }
  assert.strictEqual(ov.resolveOverlayDisplayChange(AT_1440, null).reposition, true);
});

test("it never throws on hostile input", () => {
  assert.doesNotThrow(() => ov.resolveOverlayDisplayChange([], []));
  assert.doesNotThrow(() => ov.resolveOverlayDisplayChange(0, Symbol("x")));
});

// --- main.js wiring ----------------------------------------------------------
// The pure decision passing proves nothing on its own: the ORIGINAL bug was not
// a wrong decision, it was that nothing ever asked. These read the authored
// source so deleting the listener, or never calling the registrar, fails here.

test("main.js registers the display listeners", () => {
  for (const evt of ["display-metrics-changed", "display-added", "display-removed"]) {
    assert.ok(MAIN_SRC.includes(`"${evt}"`), `main.js must listen for ${evt}`);
  }
  assert.match(MAIN_SRC, /screen\.on\(evt, scheduleOverlayDisplayReapply\)/);
});

test("the registrar is actually called at app ready - not dead code", () => {
  const ready = MAIN_SRC.slice(MAIN_SRC.indexOf("app.whenReady()"));
  assert.ok(ready, "precondition: main.js has an app.whenReady block");
  assert.match(ready.slice(0, 1500), /watchDisplayChanges\(\)/);
});

test("the re-apply reads primary.bounds, never the work area", () => {
  // Item 567 doctrine: the taskbar-excluded work area makes ovscale 1.296 rather
  // than 1.333 and lands design-px widgets ~3% off the game minimap. The re-apply
  // must feed resolveOverlayMetrics the same source create time does.
  const fn = MAIN_SRC.slice(
    MAIN_SRC.indexOf("function applyOverlayDisplayMetrics"),
    MAIN_SRC.indexOf("function scheduleOverlayDisplayReapply")
  );
  assert.ok(fn.length > 0, "precondition: applyOverlayDisplayMetrics exists");
  assert.match(fn, /workArea:\s*primary\.bounds/);
  assert.ok(!/primary\.workArea/.test(fn), "re-apply must not read primary.workArea");
});

test("the display burst is debounced and the timer is cleared on quit", () => {
  assert.match(MAIN_SRC, /OVERLAY_DISPLAY_SETTLE_MS/);
  const quit = MAIN_SRC.slice(MAIN_SRC.indexOf('app.on("will-quit"'));
  assert.match(quit.slice(0, 1200), /clearTimeout\(overlayDisplayTimer\)/);
});

test("the doctrine source is bounds, not work area - unchanged by this fix", () => {
  // Item 567: sizing to the taskbar-excluded work area makes ovscale 1.296
  // instead of 1.333 and lands every design-px widget ~3% off the game minimap.
  // The re-apply path must feed resolveOverlayMetrics the SAME source create
  // time does; this pins the two values apart so a future edit cannot quietly
  // swap them and still look correct.
  const bounds = ov.resolveOverlayMetrics({ workArea: { x: 0, y: 0, width: 2560, height: 1440 }, scaleFactor: 1 });
  const workArea = ov.resolveOverlayMetrics({ workArea: { x: 0, y: 0, width: 2560, height: 1400 }, scaleFactor: 1 });
  assert.strictEqual(bounds.scale, 1.33);
  assert.strictEqual(workArea.scale, 1.3);
  assert.notStrictEqual(bounds.scale, workArea.scale);
});
