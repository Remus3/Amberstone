// overlay_idle.js - RC2 Phase 4.2 overlay auto-hide (idle recede).
//
// The non-intrusive overlay should stop competing with the game when nothing
// is happening. After no coach-content change AND no pointer activity for
// ~IDLE_DELAY_MS the renderer stamps data-rc-idle="1" on the body and
// overlay.css drops the dock to a low opacity; the next coach change or a mouse
// move over the HUD snaps it back to full. This is an OPACITY recede, not
// display:none - a hard hide mid-game would remove coaching the operator may
// need at a glance.
//
// Overlay-scoped + additive: initOverlayIdle is a no-op outside
// body[data-shell="overlay"] (and main.js only calls it on the overlay route),
// it touches only a body data attribute (the live .ov-pulse change-glow path is
// untouched), and the dim is pure CSS. The pure decision (isIdle / planIdle)
// and the DOM apply (applyIdleAttr) are split out so the node test can drive
// them with no jsdom (mirrors condense.js / overlay_priority.js).

// Body attribute the CSS idle rule keys on (overlay.css section 6).
const IDLE_ATTR = "data-rc-idle";
// Quiet-time before the HUD recedes. 8s: long enough that a steadily-updating
// coach (1Hz state ticks that change content) never dims, short enough that a
// genuinely idle lane fades within a few seconds.
const IDLE_DELAY_MS = 8000;
// How often the idle check loop runs (cheap; just a time compare + maybe one
// attribute write).
const IDLE_TICK_MS = 1000;
// The overlay dock mounts whose content changes count as "something happening"
// (mirrors overlay_pulse.js TARGETS): a new coach call, a build rebuild, a
// callout / lead / choice update.
const IDLE_MOUNT_IDS = [
  "am-call-body",
  "am-build-body",
  "rn-lead",
  "rn-choices",
  "rn-callouts",
];

/**
 * Has the overlay been quiet (no activity) for at least delayMs?
 * Pure - the single decision the loop and the test share.
 * @param {number} lastActivityMs - timestamp of the last content change / hover.
 * @param {number} nowMs - current timestamp.
 * @param {number} [delayMs] - quiet threshold (defaults to IDLE_DELAY_MS).
 * @returns {boolean} true iff idle. A non-finite lastActivityMs/nowMs reads as
 *   "just active" (not idle) so a never-stamped overlay never starts dimmed.
 */
function isIdle(lastActivityMs, nowMs, delayMs) {
  if (!Number.isFinite(lastActivityMs) || !Number.isFinite(nowMs)) {
    return false;
  }
  const d = Number.isFinite(delayMs) && delayMs > 0 ? delayMs : IDLE_DELAY_MS;
  return nowMs - lastActivityMs >= d;
}

/**
 * Pure next idle-state from a prev state + the current time. Carries
 * lastActivityMs forward unchanged (only an activity event resets it) and
 * recomputes idle. The driver maps {idle} onto the body attribute.
 * @param {{lastActivityMs:number, idle:boolean}} prev
 * @param {number} nowMs
 * @param {number} [delayMs]
 * @returns {{lastActivityMs:number, idle:boolean}}
 */
function planIdle(prev, nowMs, delayMs) {
  const p = prev && typeof prev === "object" ? prev : {};
  const last = Number.isFinite(p.lastActivityMs) ? p.lastActivityMs : NaN;
  return { lastActivityMs: last, idle: isIdle(last, nowMs, delayMs) };
}

/**
 * Set / clear the idle attribute on the body element. Idempotent + null-safe.
 * @param {Element|null} body
 * @param {boolean} idle
 * @returns {boolean} the applied idle value (false on a null body).
 */
function applyIdleAttr(body, idle) {
  if (!body || typeof body.setAttribute !== "function") {
    return false;
  }
  if (idle) {
    body.setAttribute(IDLE_ATTR, "1");
  } else {
    body.removeAttribute(IDLE_ATTR);
  }
  return !!idle;
}

/**
 * Wire the idle recede on the overlay shell. No-op (returns 0) outside the
 * overlay surface or with no DOM. Returns a small handle for teardown / tests.
 * Glue only - the testable logic is isIdle / planIdle / applyIdleAttr above.
 */
function initOverlayIdle(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const doc = o.doc || (typeof document !== "undefined" ? document : null);
  const win = o.win || (typeof window !== "undefined" ? window : null);
  if (!doc || !doc.body || doc.body.dataset.shell !== "overlay") {
    return 0;
  }
  const now = typeof o.now === "function" ? o.now : Date.now;
  const delayMs = Number.isFinite(o.delayMs) && o.delayMs > 0 ? o.delayMs : IDLE_DELAY_MS;
  const body = doc.body;
  const st = { lastActivityMs: now(), idle: false };

  function bump() {
    st.lastActivityMs = now();
    if (st.idle) {
      st.idle = false;
      applyIdleAttr(body, false);
    }
  }

  let wired = 0;
  if (typeof MutationObserver !== "undefined") {
    for (const id of IDLE_MOUNT_IDS) {
      const mount = doc.getElementById(id);
      if (!mount) continue;
      const obs = new MutationObserver(bump);
      obs.observe(mount, { childList: true, subtree: true, characterData: true });
      wired += 1;
    }
  }
  // Pointer activity over the HUD wakes it ({forward:true} keeps the overlay
  // page receiving moves even while click-through).
  doc.addEventListener("pointermove", bump, true);
  doc.addEventListener("pointerdown", bump, true);

  function tick() {
    const idle = isIdle(st.lastActivityMs, now(), delayMs);
    if (idle !== st.idle) {
      st.idle = idle;
      applyIdleAttr(body, idle);
    }
  }
  const setI = win && typeof win.setInterval === "function" ? win.setInterval.bind(win) : setInterval;
  const timer = setI(tick, IDLE_TICK_MS);
  return { wired, timer, tick, bump, state: st };
}

// Dual export: ESM for the browser (import { initOverlayIdle }), CJS for the
// node test (require). The browser never sees `module`; node takes the CJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    IDLE_ATTR, IDLE_DELAY_MS, IDLE_TICK_MS, IDLE_MOUNT_IDS,
    isIdle, planIdle, applyIdleAttr, initOverlayIdle,
  };
}
export {
  IDLE_ATTR, IDLE_DELAY_MS, IDLE_TICK_MS, IDLE_MOUNT_IDS,
  isIdle, planIdle, applyIdleAttr, initOverlayIdle,
};
