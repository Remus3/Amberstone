// scorer_units.js - DS pick row -> display unit mapping.
//
// Source of truth: coach_integration/archetype_dispatch.py:_UNIT_SUFFIX (s182).
// Per-archetype DS scorers produce different deltas (DPS / EHP / hybrid %
// / ability-DPS / burst / HPS). The legacy schema's `delta_dps` field
// carries the scorer's primary delta regardless of scorer; this helper
// maps `row.scorer` to the correct unit suffix so the pill / chip / tile
// renderers show "+25hps" for an enchanter pick instead of "+25dps".
//
// Mapping must stay in sync with the Python helper. Rows without a
// `scorer` field (pre-s182 supervisors, or callers that haven't been
// migrated yet) fall back to "dps" - numerically wrong unit on non-DPS
// scorers, but matches the pre-s183 status quo for backward-compat.
const SCORER_UNIT = {
  dps:     'dps',
  ehp:     'ehp',
  hybrid:  '%',
  ability: 'adps',
  burst:   'burst',
  hps:     'hps',
  onhit:   'dps',
};

export function scorerUnit(scorer) {
  return SCORER_UNIT[String(scorer || '').toLowerCase()] || 'dps';
}

// Formats a single DS pick row's delta into "+<N><unit>". Reads
// `row.delta_dps` (legacy field, populated for every scorer) and
// `row.scorer` (s182+). Used by #ds-pill, #cs-ds-block chips,
// active-match DS strip, and the next-row Build fallback.
export function formatDsDelta(row) {
  if (!row) return '+0dps';
  const rawSrc = (row.delta_dps != null) ? row.delta_dps
            : (row.delta != null)     ? row.delta
            : 0;
  // Guard against a non-finite / non-numeric delta (malformed engine row,
  // null, "NaN") so the pill never renders "+NaNdps". Number() coerces a
  // numeric string normally; non-finite results fall back to 0. Finite
  // numbers round identically to the prior Math.round(raw), so valid rows
  // are unchanged.
  const num = Number(rawSrc);
  const raw = Number.isFinite(num) ? num : 0;
  return `+${Math.round(raw)}${scorerUnit(row.scorer)}`;
}
