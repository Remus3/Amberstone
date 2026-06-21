// web/js/lib/combat_mode.js
//
// QA9 (RC2 overlay): auto-declutter "combat mode". When the overlay's S0
// arbitration (lib/overlay_priority.selectPrimary) flags a high-stakes combat
// moment, right_now.js stamps body[data-fight="1"] and overlay.css sheds the
// non-urgent panes so the critical call + the A+B decision own the screen.
//
// Two pure pieces, both node-testable (no DOM, no electron):
//   - isFightCue(sel): the CONSERVATIVE trigger. The overlay's own emergency
//     tier (lethal / objective-steal / coach-urgent headline) OR an explicit
//     fight-band headline counts as combat; spike / choices / good / none keep
//     the full HUD. Reusing the existing arbitration means the declutter and
//     the S0 pop-out can never disagree about "is this a fight".
//   - makeCombatLatch(): a hysteresis hold (mirrors overlay_state.makeActive
//     Revert). A multi-exchange fight briefly drops its emergency headline
//     between coach ticks; without a hold the panes would strobe in and out
//     every ~2s. The latch keeps the decluttered state for holdMs after the
//     trigger clears so the HUD stays stable through the fight.

// The conservative fight trigger over a selectPrimary() result.
function isFightCue(sel) {
  if (!sel || typeof sel !== "object") {
    return false;
  }
  if (sel.tier === "emergency") {
    return true;
  }
  return sel.cue === "fight";
}

// Default hold: ~2 coach ticks, long enough to bridge a brief headline change
// mid-fight without overstaying once the fight truly ends.
const DEFAULT_HOLD_MS = 3500;

// Hysteresis latch. update(isFight, nowMs) returns the EFFECTIVE combat state:
// true while the instantaneous trigger holds, and for holdMs after it clears.
// now defaults to Date.now for the live render path; tests inject nowMs for
// determinism. Pure - the caller owns the body attribute.
function makeCombatLatch(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const holdMs = Number.isFinite(o.holdMs) && o.holdMs >= 0 ? o.holdMs : DEFAULT_HOLD_MS;
  const now = typeof o.now === "function" ? o.now : Date.now;
  let until = 0; // ms timestamp the effective state stays true through
  return {
    update(isFight, nowMs) {
      const t = Number.isFinite(nowMs) ? nowMs : now();
      if (isFight === true) {
        until = t + holdMs;
        return true;
      }
      return t < until;
    },
    active(nowMs) {
      const t = Number.isFinite(nowMs) ? nowMs : now();
      return t < until;
    },
    reset() {
      until = 0;
    },
  };
}

// Dual export: ES module for the browser overlay AND CommonJS for a node-run
// test, matching lib/overlay_priority.js (the module this pairs with).
if (typeof module !== "undefined" && module.exports) {
  module.exports = { isFightCue, makeCombatLatch, DEFAULT_HOLD_MS };
}
export { isFightCue, makeCombatLatch, DEFAULT_HOLD_MS };
