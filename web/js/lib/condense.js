// condense.js - RC2 Phase 3.6 dashboard primary-panel condensation.
//
// Spec lineage: docs/_archive/2026-07-28-research-consolidation/RC2_OVERLAY_CONDENSATION_SPEC.md gave the OVERLAY
// its slot budget + 2-row callout clamp. 3.6 is the DASHBOARD counterpart: the
// full :8888 view keeps its density (it is NOT the 460px HUD), but the PRIMARY
// coaching panels (RIGHT NOW, NEXT) render fixed supporting KV rows that paint
// the "-" no-data sentinel in client / pregame / ARAM / aftergame states - a
// dead-dash wall under the live headline. This module collapses those empty
// rows so the glance lands on the rows that actually carry a value. It is the
// same move the STATS panel already makes inline (right_now.js
// _hideEmptyStatRows), generalized into one reusable + testable helper.
//
// Pure + idempotent: toggles display only, never rewrites innerHTML, so a row
// reappears the tick its value latches (e.g. Fight rule arrives at the first
// teamfight). Dual ESM/CJS export so the node test can require() the decision
// logic with no DOM emulation (jsdom/playwright are absent on CI).

// The no-data sentinels a coaching KV row paints when its producer is silent.
// "-" is the repo-wide functional no-data sentinel (CLAUDE.md). "- / -" covers
// the paired-stat rows; "" covers an un-set textContent. "0" is NOT here - a
// zero is a real value (0 deaths, 0 wards), never a no-data dash.
const EMPTY_SENTINELS = ["", "-", "- / -"];

/**
 * Is this KV value text the no-data sentinel (the row carries nothing to read)?
 * Pure - the single decision the DOM pass and the test share.
 * @param {string} text - the value cell's textContent.
 * @param {string[]} [sentinels] - override set (defaults to EMPTY_SENTINELS).
 * @returns {boolean} true iff the trimmed text is a no-data sentinel.
 */
function isEmptyValue(text, sentinels) {
  const set = sentinels || EMPTY_SENTINELS;
  const t = (text == null ? "" : String(text)).trim();
  return set.indexOf(t) !== -1;
}

/**
 * Given the value-cell text of each KV row in order, return a parallel boolean
 * plan: true == hide this row. Pure; the DOM function maps it onto
 * row.style.display. Never throws on a non-array input (reads as no rows).
 * @param {string[]} values
 * @param {string[]} [sentinels]
 * @returns {boolean[]}
 */
function planKvCondense(values, sentinels) {
  if (!Array.isArray(values)) return [];
  return values.map(function (v) { return isEmptyValue(v, sentinels); });
}

/**
 * Collapse empty supporting KV rows under a dashboard panel root.
 *
 * Scans `.kv` rows in root (the RIGHT NOW / NEXT supporting rows), reads each
 * row's value cell (the LAST span - the key label is the first span), and hides
 * the row when the value is a no-data sentinel; shows it otherwise. Idempotent
 * + null-safe. A no-op outside a DOM (the node test drives the pure fns).
 *
 * In the ?overlay=1 shell these `.kv` rows are already
 * `display:none !important` (overlay.css `#right-now .panel-body > *`), so an
 * inline display write can never reveal them there - this stays a
 * dashboard-surface condensation by construction, no shell guard needed.
 *
 * @param {Element|null} root - the panel section (RN.root / NX.root).
 * @param {string[]} [sentinels]
 * @returns {{visible:number, hidden:number}} per-call row tallies.
 */
function condenseKvRows(root, sentinels) {
  const out = { visible: 0, hidden: 0 };
  if (!root || typeof root.querySelectorAll !== "function") return out;
  const rows = root.querySelectorAll(".kv");
  rows.forEach(function (row) {
    const cells = row.querySelectorAll("span");
    const valEl = cells.length ? cells[cells.length - 1] : null;
    const val = valEl ? (valEl.textContent || "") : "";
    if (isEmptyValue(val, sentinels)) {
      row.style.display = "none";
      out.hidden += 1;
    } else {
      row.style.display = "";
      out.visible += 1;
    }
  });
  return out;
}

// Dual export: ES module for the browser dashboard (import { condenseKvRows }
// from '../lib/condense.js') AND CommonJS for the node-run test. The browser
// never sees `module`; node (22+ require-of-ESM) takes the CJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { EMPTY_SENTINELS, isEmptyValue, planKvCondense,
                     condenseKvRows };
}
export { EMPTY_SENTINELS, isEmptyValue, planKvCondense, condenseKvRows };
