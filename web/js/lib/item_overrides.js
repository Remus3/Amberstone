// WP-D2/D3 (OVERLAY_BUILD_MASTER_PLAN Section D): per-item build-order override
// store. In-memory, per-match (cleared on game end + by D3's "reset item status"
// settings control). The D2 radial writes it; the LIVE build row re-renders
// through applyItemOverrides so an operator shift survives the 4s rerank tick.
//
// D2 ships the store + the CLIENT-SIDE reorder (shift / defer ordering + the
// keep/silence flags). D3 makes the SERVER beam-search (replan.py) honor the
// pins/shifts as constraints, refines Defer-Once "re-enters after one full item"
// timing, excludes silenced items from swap suggestions, and wires the reset
// control. Entry shape: { shift:int, deferred:bool, keep:bool, silenced:bool }.

export const ITEM_OVERRIDES = {};

function _ent(id) {
  const k = String(id);
  if (!ITEM_OVERRIDES[k]) {
    ITEM_OVERRIDES[k] = { shift: 0, deferred: false, keep: false, silenced: false };
  }
  return ITEM_OVERRIDES[k];
}

// N - Build-Earlier: shift one slot toward the front (overtakes the nearest
// neighbor); repeated presses accumulate.
export function buildEarlier(id) { _ent(id).shift -= 1; }

// E - Build-Later: shift one slot toward the back.
export function buildLater(id) { _ent(id).shift += 1; }

// S - Defer-Once: sink the item to the back of the visible plan. D3 turns this
// into the "re-enters after exactly one full item completes" timing; client-side
// it just orders the deferred item last so the next buy is surfaced.
export function deferItem(id) { _ent(id).deferred = true; }

// W - Keep: lock the pick (toggle). D3 makes replan stop re-ranking a kept item.
export function keepItem(id) { const e = _ent(id); e.keep = !e.keep; }

// Center - Silence: stop suggesting changes to this item (toggle). D3 excludes
// silenced items from swap suggestions + logs the action.
export function silenceItem(id) { const e = _ent(id); e.silenced = !e.silenced; }

export function isKept(id) { const e = ITEM_OVERRIDES[String(id)]; return !!(e && e.keep); }
export function isSilenced(id) { const e = ITEM_OVERRIDES[String(id)]; return !!(e && e.silenced); }

// Clear every override (D3 reset control + the game-end hook).
export function clearItemOverrides() {
  for (const k in ITEM_OVERRIDES) delete ITEM_OVERRIDES[k];
}

// Pure: reorder a rows array by the stored shifts (deferred items sink last),
// stable on ties so unoverridden plan order is preserved. Each row carries an id
// at r.id or r.item_id. Returns a NEW array; the input is not mutated.
export function applyItemOverrides(rows) {
  if (!Array.isArray(rows) || rows.length < 2) return rows;
  const keyed = rows.map((r, i) => {
    const id = String((r && (r.id != null ? r.id : r.item_id)) || "");
    const ov = ITEM_OVERRIDES[id] || {};
    const sh = ov.shift || 0;
    // Half-step nudge in the shift direction so a single Build-Earlier (shift -1)
    // sorts STRICTLY ahead of the neighbor it overtakes (an integer shift would
    // tie, and the stable tie-break would leave it in place). Defer sinks last.
    const nudge = sh < 0 ? -0.5 : (sh > 0 ? 0.5 : 0);
    const deferBias = ov.deferred ? 1000 : 0;
    return { r, i, eff: i + sh + nudge + deferBias };
  });
  keyed.sort((a, b) => (a.eff - b.eff) || (a.i - b.i));
  return keyed.map((k) => k.r);
}
