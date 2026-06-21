// web/js/panels/spike_cue.js
//
// RC Overlay Doctrine w-spike: the spike-crossed cue. A transient one-shot glyph
// that fires the instant the operator crosses an ULTIMATE power spike - level 6
// (R unlocked), 11 (R rank 2), 16 (R rank 3). Ult availability is the single
// universal combat power spike every champion shares (the biggest cooldown), so
// it is the honest "fight now / look for a play" signal readable live without a
// per-champion item model.
//
// Data source: /api/state.liveclient.level (dashboard/_liveclient.py ships the
// active player's level). The not-spiked -> spiked EDGE is detected HERE (the
// rising level cross), so the cue + pulse fire ONCE on the cross, not every 2s
// tick while you sit at the level. The cue is transient: it self-expires after a
// short window (doctrine rule 6 - alerts self-expire, never need a dismissal).
//
// This is the live producer for the spike_crossed predicate overlay_priority.js
// already arbitrates (it consumed coach.spike_crossed, which the backend never
// emitted - lib/overlay_priority.js header). The widget surfaces it directly.
//
// Discipline (mirrors ward_cue.js): pure ESM, ASCII only, sig-dedup so the 1Hz
// tick does not thrash the DOM, GPU-light (one short box-shadow pulse, gated on
// the operator pulseNotify setting + prefers-reduced-motion via CSS). Self-gates
// on body[data-shell="overlay"] - a cheap no-op on the 1920 dashboard.

import { readOverlaySettings } from '../lib/overlay_settings.js';

// The ultimate power-spike milestones (R unlock + the two rank-ups). Ascending.
const _SPIKE_LEVELS = [6, 11, 16];

// How long the transient cue stays up after the cross (doctrine: self-expiring).
const _SPIKE_HOLD_MS = 8000;

// Normalize the live level to an int in [1,18], or 0 when absent (a tick before
// /api/state lands, or out of game).
function normSpikeLevel(lc) {
  const c = lc && typeof lc === "object" && !Array.isArray(lc) ? lc : {};
  const n = Number(c.level);
  if (!Number.isFinite(n)) return 0;
  return Math.min(18, Math.max(0, Math.floor(n)));
}

// The highest ultimate milestone JUST crossed going prevLevel -> curLevel, or 0.
// A null/0 prev (first render / fresh mid-game attach) NEVER fires - the cue
// marks a spike crossed THIS session, not "you happen to already be level 12".
function crossedSpike(prevLevel, curLevel) {
  const prev = Number.isFinite(prevLevel) ? prevLevel : 0;
  const cur = Number.isFinite(curLevel) ? curLevel : 0;
  if (prev <= 0 || cur <= prev) return 0;
  let hit = 0;
  for (const m of _SPIKE_LEVELS) {
    if (prev < m && m <= cur) hit = m; // keep the highest crossed this step
  }
  return hit;
}

// Glyph label for a crossed milestone. R unlock at 6, rank-ups at 11/16.
function _spikeLabel(milestone) {
  if (milestone === 6) return "ULT ONLINE";
  if (milestone === 11) return "ULT R2";
  if (milestone === 16) return "ULT R3";
  return "POWER SPIKE";
}

// Render the chip markup (pure). No untrusted strings flow in (milestone is one
// of our own integers). Empty string when there is nothing to show.
function spikeCueHtml(milestone) {
  if (!milestone) return "";
  return (
    `<span class="spike-chip is-spike" data-cue="spike">`
    + `<span class="spike-glyph" aria-hidden="true"></span>`
    + `<span class="spike-label">${_spikeLabel(milestone)}</span></span>`
  );
}

// --- DOM render (overlay-only) -----------------------------------------------
let _prevLevel = 0;   // last level seen (for the rising-edge cross)
let _shownFor = 0;    // the milestone currently displayed (0 = nothing)
let _hideTimer = 0;
let _pulseTimer = 0;

function _armHide(mount) {
  if (_hideTimer) clearTimeout(_hideTimer);
  _hideTimer = setTimeout(() => {
    _hideTimer = 0;
    _shownFor = 0;
    mount.innerHTML = "";
    mount.hidden = true;
  }, _SPIKE_HOLD_MS);
}

function _pulse(mount) {
  const el = mount.querySelector('[data-cue="spike"]');
  if (!el) return;
  el.classList.remove("is-pulsing");
  void el.offsetWidth; // reflow -> restart the keyframe
  el.classList.add("is-pulsing");
  if (_pulseTimer) clearTimeout(_pulseTimer);
  _pulseTimer = setTimeout(() => {
    const p = mount.querySelector(".spike-chip.is-pulsing");
    if (p) p.classList.remove("is-pulsing");
  }, 1300);
}

// Render from the raw liveclient block (lc.level). Hidden everywhere except the
// overlay shell; the 1920 dashboard never shows the spike cue.
export function renderSpikeCue(lc) {
  const mount = document.getElementById("am-spike-cue");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const level = normSpikeLevel(lc);
  const milestone = crossedSpike(_prevLevel, level);
  _prevLevel = level;

  if (!milestone) {
    // No fresh cross this tick. The transient hide-timer owns clearing the cue;
    // do not touch the DOM (idempotent - lets the held cue ride out its window).
    return;
  }

  // Fresh cross: show + arm the self-expire, dedup repeated identical crosses.
  if (_shownFor !== milestone) {
    mount.innerHTML = spikeCueHtml(milestone);
    mount.hidden = false;
    _shownFor = milestone;
  }
  _armHide(mount);

  // One-shot pulse, honoring the operator pulse toggle (same gate as ward_cue /
  // overlay_pulse). prefers-reduced-motion is handled in CSS.
  let pulseOn = true;
  try {
    pulseOn = readOverlaySettings().pulseNotify !== false;
  } catch (_e) {
    pulseOn = true;
  }
  if (pulseOn) _pulse(mount);
}

// Test reset (module-scope edge/timer state).
export function _resetSpikeCue() {
  _prevLevel = 0;
  _shownFor = 0;
  if (_hideTimer) clearTimeout(_hideTimer);
  _hideTimer = 0;
  if (_pulseTimer) clearTimeout(_pulseTimer);
  _pulseTimer = 0;
}

export const __test = {
  normSpikeLevel,
  crossedSpike,
  _spikeLabel,
  spikeCueHtml,
  _SPIKE_LEVELS,
};
