// overlay_priority.js - RC2 Phase 3.2 in-match overlay S0 arbitration.
//
// Spec: docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md sections 4
// (primary-slot arbitration) and 5 (motion rationing). Pure vanilla JS,
// no deps; consumed by right_now.js / callouts.js as an ES module.
//
// PROBLEM it solves: the 460px overlay dock rendered every live cue at
// flat priority and pulsed the headline on every text re-emit. This module
// makes the scarce PRIMARY (S0) slot hold exactly ONE winner per tick
// (acceptance A2 - one pop-out) and rations the change-pulse to the
// Emergency tier + a one-shot Urgent cross (acceptance A5 - no alarm
// fatigue).
//
// INPUT: a normalized signal object (the caller pre-extracts these from the
// /api/state envelope so this stays pure + testable):
//   {
//     band: "urgent"|"fight"|"good"|"empty",  // classifyAction(headline)
//     hasChoices: boolean,        // coach.choices non-empty (A+B chips)
//     spikeCrossed: boolean,      // a power-spike crossed THIS tick (one-shot)
//     objectiveStealNow: boolean, // drake/baron steal-contest window == NOW
//     lethal: boolean,            // lethal-incoming (spec Q2). signalFromState
//                                 //   derives it from band + coach.hp_pct (low
//                                 //   HP at a fight), or honors an explicit
//                                 //   lethal_incoming flag if a producer sets one
//   }
//
// LADDER (descending; the first match wins S0). The band=="urgent" headline
// sits at 85 - an Emergency the coach itself flagged - between an explicit
// objective steal (90) and the A+B decision (80); the explicit lethal/
// objective predicates outrank it because they carry combat context the
// text classifier lacks. This refines the spec's section-4 ladder, which
// left the classifyAction "urgent" band implicit. The Q2 lethal predicate is
// now wired (signalFromState derives low-HP-at-fight), so a low-HP combat tick
// promotes from the urgent headline (85) to the lethal rung (100).

// classifyAction band -> tier (spec section 1). right_now.js:472 produces
// the band; this is the single source for the band->tier mapping the
// consumers share.
const BAND_TIER = {
  urgent: 'emergency',
  fight: 'urgent',
  good: 'ambient',
  empty: 'empty',
};

// cue -> S0 priority. Higher wins. These are the section-4 ladder rungs.
const PRIORITY = {
  lethal: 100,
  objective_steal: 90,
  urgent_headline: 85,
  choices: 80,
  spike: 70,
  fight: 60,
  good: 40,
  none: 0,
};

// cue -> tier. Most rungs are not band-derived (an A+B decision or a spike
// cross is Urgent regardless of the headline band), so tier is pinned per
// cue rather than looked up via BAND_TIER.
const _CUE_TIER = {
  lethal: 'emergency',
  objective_steal: 'emergency',
  urgent_headline: 'emergency',
  choices: 'urgent',
  spike: 'urgent',
  fight: 'urgent',
  good: 'ambient',
  none: 'empty',
};

function _sel(cue) {
  return { cue: cue, tier: _CUE_TIER[cue], priority: PRIORITY[cue] };
}

/**
 * Pick the single cue that wins the PRIMARY (S0) overlay slot this tick.
 *
 * @param {object|null} state - the normalized signal object (see header).
 *   A null/partial/garbage state never throws; absent signals read as empty,
 *   yielding the "none" cue (the slot collapses to zero height).
 * @returns {{cue:string, tier:string, priority:number}} the S0 winner.
 *   All losers render in their own AMBIENT home slot (S1-S3) or not at all -
 *   never a second pop-out (acceptance A2).
 */
function selectPrimary(state) {
  const s = state || {};
  const band = typeof s.band === 'string' ? s.band : 'empty';

  if (s.lethal === true) return _sel('lethal');
  if (s.objectiveStealNow === true) return _sel('objective_steal');
  if (band === 'urgent') return _sel('urgent_headline');
  if (s.hasChoices === true) return _sel('choices');
  if (s.spikeCrossed === true) return _sel('spike');
  if (band === 'fight') return _sel('fight');
  if (band === 'good') return _sel('good');
  return _sel('none');
}

/**
 * Decide whether the change-pulse may fire for this S0 selection.
 *
 * Rations motion to two cases (spec section 5 / acceptance A5):
 *   - the EMERGENCY tier on an entry/escalation edge (the cue is new), and
 *   - a one-shot URGENT cue (spike crossed / choices appeared) on its fresh
 *     cross.
 * A sustained same-cue selection never re-pulses (kills alarm fatigue), and
 * the steady Urgent (band=="fight") + Ambient (band=="good") tiers update
 * silently - color/glyph change without motion.
 *
 * @param {string} prevCue - the cue selected on the previous tick.
 * @param {{cue:string, tier:string}} sel - the current selectPrimary result.
 * @returns {boolean} true iff the pulse may fire on this tick.
 */
function shouldPulse(prevCue, sel) {
  if (!sel) return false;
  const oneShot = sel.cue === 'spike' || sel.cue === 'choices';
  const eligible = sel.tier === 'emergency' || oneShot;
  // Key off a CUE CROSS (false->true of the entry predicate), not text
  // inequality - a persisting cue holds steady without re-firing.
  return eligible && prevCue !== sel.cue;
}

// Q2 lethal-incoming predicate (spec section 9 Q2 + the S0 ladder rung
// PRIORITY.lethal=100). "Low HP at fight": the player must disengage in ~1s or
// die. Derived from signals the coach already emits - the classifyAction band
// (the active-combat flag) plus coach.hp_pct - so no backend producer or
// /api/state schema change is needed (grep-before-wire confirmed coach.hp_pct
// is live + 0-100 scaled, no `lethal_incoming` producer exists). Conservative
// by construction so it cannot abuse the reserved lethal-red pop-out (A2):
//   - ONLY an active-combat band counts (fight | urgent). Standing low-HP in
//     base or on a recall classifies good / empty and never fires.
//   - hp_pct is the 0-100 percentage (live envelope: 100 at full HP). A missing
//     or 0 value (dead, or a data gap; the dataclass default is 0.0) is a
//     guard, not an emergency - require 0 < hp_pct <= LETHAL_HP_PCT so a
//     dropout can never false-fire.
// shouldPulse() still edge-gates the motion, so a sustained low-HP fight pulses
// once on entry, not every tick (A5 - no alarm fatigue).
const LETHAL_HP_PCT = 25; // conservative emergency floor (percent), tunable.
const _COMBAT_BANDS = { fight: true, urgent: true };

function _isLethalAtFight(band, hpPct) {
  if (!_COMBAT_BANDS[band]) return false;
  return Number.isFinite(hpPct) && hpPct > 0 && hpPct <= LETHAL_HP_PCT;
}

/**
 * Normalize a live coach state envelope into the selectPrimary() signal
 * object. This is the single mapping point the shadow consumer
 * (right_now.js, RC2 P3.3) and the eventual operator-gated live flip share,
 * so flipping from shadow to authoritative is a one-line swap (consume the
 * sel/pulse result instead of stamping it).
 *
 * @param {object|null} p - the coach payload (state.coach). null/garbage is
 *   safe (reads as empty).
 * @param {string} band - the classifyAction band already computed by the
 *   caller (right_now.js:472). Non-strings fall back to "empty".
 * @returns {{band:string, hasChoices:boolean, spikeCrossed:boolean,
 *   objectiveStealNow:boolean, lethal:boolean}} the selectPrimary input.
 */
function signalFromState(p, band) {
  const s = p || {};
  const choices = s.choices;
  const nband = typeof band === 'string' ? band : 'empty';
  return {
    band: nband,
    hasChoices: Array.isArray(choices) && choices.length > 0,
    // Crossing-edge predicates (spec section 9 Q1/Q2). spike_crossed /
    // objective_steal_now stay Phase-4 optional booleans (no producer yet, so
    // false unless a future feed sets them - no assumed surface). lethal is now
    // WIRED (spec Q2): an explicit lethal_incoming flag OR the derived
    // low-HP-at-fight predicate (_isLethalAtFight, from band + coach.hp_pct).
    spikeCrossed: s.spike_crossed === true,
    objectiveStealNow: s.objective_steal_now === true,
    lethal: s.lethal_incoming === true || _isLethalAtFight(nband, s.hp_pct),
  };
}

// Dual export: ES module for the browser overlay (import { selectPrimary }
// from './lib/overlay_priority.js') AND CommonJS for the node-run test. The
// browser never sees `module`; node (22+ require-of-ESM) takes the export.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { selectPrimary, shouldPulse, signalFromState,
                     BAND_TIER, PRIORITY };
}
export { selectPrimary, shouldPulse, signalFromState, BAND_TIER, PRIORITY };
