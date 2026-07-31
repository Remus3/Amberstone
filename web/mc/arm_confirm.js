// arch: arm-then-confirm state machine for Mission Control shortcuts | section=web | frozen=no
//
// Layer 1 + layer 2 of the Mission Control safety model (docs/MISSION_CONTROL_PLAN.md):
// a first click ARMS with a short auto-disarm window, a second click inside that
// window FIRES, and a stray single click decays to nothing.
//
// WHY THE KEY IS MINTED HERE AND NOT AT PAGE LOAD. MEASURED against the real S2
// route (plan section "Integration constraints", table step 3): a lane refusal is
// remembered by the idempotency table exactly like any other settled 200, so a
// client that reuses one key across arms replays "refused" forever - even after
// the lane frees. The key therefore belongs to ONE operator intent: minted on
// arm, DISCARDED on disarm or expiry, consumed on fire. A key minted once per
// page load produces a button that silently never works again.
//
// Pure logic, no DOM and no fetch, so `node --test` can drive the whole
// lifecycle (see arm_confirm.test.mjs). The DOM wrapper lives in
// web/mc/mc.js (and, transitionally until Task 9 deletes the import,
// also web/js/panels/dev.js).

// A stray click must decay faster than an operator can forget they made it.
export const ARM_WINDOW_MS = 3000;

function _defaultMintKey() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  // Fallback for a browser without randomUUID: hex/dash only, which is what
  // dashboard/_idempotency.is_valid_key accepts.
  let out = "";
  for (let i = 0; i < 8; i += 1) {
    out += Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
    if (i === 1 || i === 3 || i === 5) out += "-";
  }
  return out;
}

/**
 * Build an arm-then-confirm controller.
 *
 * @param {object} [opts]
 * @param {function():string} [opts.mintKey] key factory (injected in tests).
 * @param {function():number}  [opts.now]     clock in ms (injected in tests).
 * @param {number}             [opts.windowMs] arm lifetime.
 * @param {function(object):void} [opts.onChange] called after every state change.
 */
export function createArmController(opts) {
  const o = opts || {};
  const mintKey = o.mintKey || _defaultMintKey;
  const now = o.now || (() => Date.now());
  const windowMs = typeof o.windowMs === "number" ? o.windowMs : ARM_WINDOW_MS;
  const onChange = typeof o.onChange === "function" ? o.onChange : null;

  let armedId = null;
  let key = null;
  let expiresAt = 0;

  function snapshot() {
    return { armedId, key, expiresAt };
  }

  function notify() {
    if (onChange) onChange(snapshot());
  }

  /** Drop the armed intent AND its key. Returns true when something was armed. */
  function disarm(silent) {
    if (armedId === null) return false;
    armedId = null;
    key = null;          // the discard that makes a re-arm a NEW intent
    expiresAt = 0;
    if (!silent) notify();
    return true;
  }

  /**
   * Expire a stale arm. Call from the render/poll path; it is what makes the
   * auto-disarm real without a timer the caller has to own.
   */
  function tick(at) {
    if (armedId === null) return false;
    const t = typeof at === "number" ? at : now();
    if (t < expiresAt) return false;
    return disarm(false);
  }

  /**
   * ARM `id`. Mints a fresh idempotency key. Arming a different id disarms the
   * first one (and discards its key) - two intents are never armed at once.
   */
  function arm(id, at) {
    if (id === null || id === undefined || id === "") {
      throw new Error("arm requires an id");
    }
    const t = typeof at === "number" ? at : now();
    disarm(true);
    armedId = id;
    key = mintKey();
    expiresAt = t + windowMs;
    notify();
    return snapshot();
  }

  /**
   * Second click. Fires only when `id` is the armed intent and the window is
   * still open; the key is consumed and the controller returns to disarmed
   * either way, so a retry after a refusal re-arms with a NEW key.
   *
   * @returns {{fired: boolean, key: (string|null), reason: (string|null)}}
   */
  function confirm(id, at) {
    const t = typeof at === "number" ? at : now();
    if (armedId === null) return { fired: false, key: null, reason: "not_armed" };
    if (armedId !== id) return { fired: false, key: null, reason: "other_armed" };
    if (t >= expiresAt) {
      disarm(false);
      return { fired: false, key: null, reason: "expired" };
    }
    const fired = key;
    disarm(false);
    return { fired: true, key: fired, reason: null };
  }

  /** True when `id` is armed and its window is still open at `at`. */
  function isArmed(id, at) {
    if (armedId === null || armedId !== id) return false;
    const t = typeof at === "number" ? at : now();
    return t < expiresAt;
  }

  /** Whole-number seconds left on the armed window, 0 when nothing is armed. */
  function remainingMs(at) {
    if (armedId === null) return 0;
    const t = typeof at === "number" ? at : now();
    return Math.max(0, expiresAt - t);
  }

  return { arm, confirm, disarm, tick, isArmed, remainingMs, snapshot };
}
