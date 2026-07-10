// Combat-style archetype chip for the champ-select My Pick card (R89 Aggregator C
// competitor lift - the RC analog of a per-champion class tag).
//
// RC resolves the primary archetype (carry / bruiser / tank / mage / assassin /
// enchanter) via core.archetype_picks.get_archetype_for and serves it on
// /api/cs-archetype-pick; champ_select.js fetches + caches it in _CSV_ARCH_CACHE
// and feeds it to the DS scorer cache key. Since the operator archetype picker
// was removed (LEDGER 823) nothing renders it, so the operator never sees the
// combat style the coach + builds are keyed to. This chip surfaces it read-only.
//
// Pure presentation over already-computed, already-client-cached data - no fetch,
// no backend, no new math. Reuses the existing .csv-build-badge tint family
// (champ_select_view.css) so it adds zero new CSS / UI-audit surface.
//
// Discipline: pure ESM, DOM-free (node --test importable), ASCII only, fail-soft
// on empty / null. Mirrors the ds_matchup.js pure-function shape.

// Resolved archetype primary -> an existing .csv-build-badge tint class. Unknown
// but non-empty primaries fall through to the neutral default tint so a future
// taxonomy addition still renders a correctly-labeled chip rather than vanishing.
const _ARCH_TINT = {
  carry:     "csv-build-badge-crit",
  marksman:  "csv-build-badge-crit",
  adc:       "csv-build-badge-crit",
  bruiser:   "csv-build-badge-tank",
  tank:      "csv-build-badge-tank",
  mage:      "csv-build-badge-ap",
  assassin:  "csv-build-badge-lethality",
  enchanter: "csv-build-badge-support",
  support:   "csv-build-badge-support",
};

function _archTint(primary) {
  const key = String(primary == null ? "" : primary).trim().toLowerCase();
  return _ARCH_TINT[key] || "csv-build-badge-default";
}

// HTML-escape the label. The source is a controlled enum, but the chip is written
// via innerHTML in champ_select.js, so escape defensively. Mirrors ds_matchup.js.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Build the combat-style chip HTML for a resolved archetype primary. Returns ""
// (no chip) on empty / null / whitespace so the My Pick card never shows an empty
// pill before the archetype fetch lands.
export function archetypeChipHtml(primary) {
  const key = String(primary == null ? "" : primary).trim();
  if (!key) return "";
  const tint = _archTint(key);
  const label = _esc(key.toUpperCase());
  return `<span class="csv-build-badge csv-archetype-chip ${tint}" title="Combat style (DS archetype)">${label}</span>`;
}

export const __test = { archetypeChipHtml, _archTint, _esc, _ARCH_TINT };
