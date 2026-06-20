// status.js - Grafana-style threshold -> status helper (RC2 B1).
//
// Research: docs/research/RC2_RESEARCH_nonleague_uiux.md section B1
// (Grafana threshold model + the 5-second rule). Replaces scattered
// per-panel JS magic numbers with ONE shared mapping so the status
// system is consistent and auditable. Pure vanilla JS, no deps.
//
// Model: a thresholds object names the two boundaries between the three
// bands. statusFor() maps a numeric value to "good" | "warn" | "bad".
// Two directions:
//   higher_is_better (default) - value >= good is "good", value >= warn
//     is "warn", below warn is "bad". (e.g. CS-per-min, win rate.)
//   lower_is_better - value <= good is "good", value <= warn is "warn",
//     above warn is "bad". (e.g. deaths, gold-behind, cooldown remaining.)
//
// thresholds = { good: <num>, warn: <num>, higherIsBetter?: <bool> }
//   higherIsBetter defaults to true when omitted.
//
// Adopt incrementally: a panel that currently hard-codes
//   const cls = cs >= 8 ? 'good' : cs >= 6 ? 'warn' : 'bad';
// becomes
//   const cls = statusFor(cs, { good: 8, warn: 6 });
// and statusVar(cls) yields the matching --signal-* custom property so
// the element can set `el.style.setProperty('--status', statusVar(cls))`.

// Map a status band to its semantic CSS custom-property reference
// (the tokens.css --signal-* layer). Unknown band -> dim.
const _STATUS_VAR = {
  good: 'var(--signal-good)',
  warn: 'var(--signal-warn)',
  bad: 'var(--signal-bad)',
};

/**
 * Classify a numeric value into a status band against a threshold table.
 *
 * @param {number} value - the metric's current value.
 * @param {{good:number, warn:number, higherIsBetter?:boolean}} thresholds
 * @returns {"good"|"warn"|"bad"} - the status band. A non-finite value
 *   or a malformed thresholds object yields "bad" (fail-loud: an unknown
 *   metric reads as a problem to dig into, never as a false "good").
 */
function statusFor(value, thresholds) {
  const num = Number(value);
  if (!Number.isFinite(num) || thresholds == null) return 'bad';

  const good = Number(thresholds.good);
  const warn = Number(thresholds.warn);
  if (!Number.isFinite(good) || !Number.isFinite(warn)) return 'bad';

  // higherIsBetter defaults to true (the common dashboard case).
  const higher = thresholds.higherIsBetter !== false;

  if (higher) {
    if (num >= good) return 'good';
    if (num >= warn) return 'warn';
    return 'bad';
  }
  // lower_is_better: smaller value is healthier.
  if (num <= good) return 'good';
  if (num <= warn) return 'warn';
  return 'bad';
}

/**
 * Map a status band to its semantic CSS custom-property reference.
 * @param {"good"|"warn"|"bad"} status
 * @returns {string} e.g. "var(--signal-good)"; unknown -> "var(--signal-dim)".
 */
function statusVar(status) {
  return _STATUS_VAR[status] || 'var(--signal-dim)';
}

// Dual export: ES module for the browser dashboard (import { statusFor }
// from './lib/status.js') AND CommonJS for the node-run test. The browser
// never sees `module`; node never sees `export`. Guard each independently.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { statusFor, statusVar };
}
export { statusFor, statusVar };
