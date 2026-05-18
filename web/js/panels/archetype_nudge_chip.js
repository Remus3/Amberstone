// Archetype-mismatch nudge chip (s184.1, 2026-05-13).
//
// Header chip that fires when the operator's CS archetype pick doesn't
// match the dispatcher's top-15 for their first completed item. Backend
// lives in core/archetype_mismatch.py + dashboard/routes_archetype.py
// (s184); this module is purely a render + dismiss wire-in.
//
// Reads /api/state.archetype_nudge - which the state-builder stamps via
// compute_nudge_payload() on every poll. Mode-gating mirrors #ds-pill
// (hidden in client/tft modes via CSS so the header row doesn't shift
// when a game starts). JS additionally hides when phase != "fired" so
// dismissed / pending / no_mismatch states stay invisible.
//
// Dismiss path is idempotent + restart-wipes (matches the backend cache
// lifecycle) - fire-and-forget POST is fine, no need to retry on failure.

import { el } from '../lib/helpers.js';

const NC = {
  chip: el("archetype-nudge-chip"),
  text: el("archetype-nudge-chip-text"),
  xBtn: el("archetype-nudge-chip-x"),
};

let _lastSig = "";

function _hideChip() {
  if (!NC.chip) return;
  if (!NC.chip.hidden) NC.chip.hidden = true;
  _lastSig = "";
}

async function _dismiss(champion) {
  if (!champion) { _hideChip(); return; }
  try {
    await fetch("/api/archetype-nudge/dismiss", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ champion }),
    });
  } catch (_) { /* swallow - backend cache restart-wipes anyway */ }
  _hideChip();
}

// Wire the X-button once at module load. The chip element itself is
// declared in index.html with hidden by default, so this listener is a
// no-op until renderArchetypeNudge() flips it visible.
if (NC.xBtn) {
  NC.xBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const champion = NC.chip && NC.chip.dataset.champion;
    _dismiss(champion);
  });
}

// Format the chip's display label. Keeps it terse because the row has
// limited horizontal room next to #ds-pill + #trigger-pill; full message
// + expected items go in the title attr for hover.
function _label(primary) {
  if (!primary) return "Pick";
  return primary.charAt(0).toUpperCase() + primary.slice(1);
}

export function renderArchetypeNudge(stateObj) {
  if (!NC.chip || !NC.text) return;
  const n = (stateObj && stateObj.archetype_nudge) || null;
  // Fire-gating: only show on phase=="fired" with a non-empty champion.
  // Pending / no_mismatch / dismissed all collapse the chip.
  if (!n || n.fired !== true || n.phase !== "fired" || !n.champion) {
    _hideChip();
    return;
  }
  const champion = String(n.champion);
  const primary = String(n.primary || "").toLowerCase();
  const firstItem = String(n.first_item_name || n.first_item_id || "?");
  const expected = Array.isArray(n.expected_items) ? n.expected_items : [];
  const message = String(n.message || "");

  // Idempotency - skip DOM writes when the signature is unchanged. The
  // chip lives on a 2s poll cadence; without this guard the X-button's
  // hover state would tear down + recreate on every tick.
  const sig = `${champion}|${primary}|${firstItem}|${expected.join(",")}`;
  if (sig === _lastSig) return;
  _lastSig = sig;

  NC.text.textContent = `⚠ ${_label(primary)}? · ${firstItem}`;
  NC.chip.dataset.champion = champion;
  const tipBody = message || `Picked ${_label(primary)} but first item is ${firstItem}.`;
  const tipExpect = expected.length ? `\nExpected: ${expected.slice(0, 3).join(", ")}` : "";
  NC.chip.title = `${tipBody}${tipExpect}\nClick × to dismiss for this game.`;
  NC.chip.hidden = false;
}

// Test/diagnostic helper - lets external callers reset the dedup
// signature so the next render call writes to the DOM unconditionally.
export function _resetArchetypeNudgeSig() { _lastSig = ""; }
