// web/js/panels/ward_cue.js
//
// QA1 (RC2 overlay): trinket / control-ward READY single-pulse glyph cue.
// Overlay-only sibling of the other #am-grid panes - a tiny chip strip at the
// top of the CALL pane that lights the instant a warding trinket comes off
// cooldown or the operator is holding a control ward to place. No competitor
// surfaces this, and it is the one warding signal readable live (the Live
// Client emits no ward-placement events - see core/ward_cue.py).
//
// Backend: dashboard/_liveclient.py ships /api/state.liveclient.ward_cue
// (core.ward_cue.compute_ward_cue over the operator's items[].canUse + control
// ward count). This panel owns the not-ready -> ready EDGE detection so the
// pulse fires ONCE when the cue appears, not on every 2s state tick while the
// trinket sits ready. The steady "ready" chip stays lit until it is used.
//
// Discipline (mirrors overlay_ds_controls.js): pure ESM, ASCII only, sig-dedup
// so the 1Hz tick does not thrash the DOM, GPU-light (one short box-shadow
// pulse, gated on the operator pulseNotify setting + prefers-reduced-motion via
// CSS). Self-gates on body[data-shell="overlay"] - a cheap no-op on the 1920
// dashboard.

import { readOverlaySettings } from '../lib/overlay_settings.js';

// Normalize the backend cue into a strict, defensively-typed shape. Garbage /
// missing -> the safe all-off default (the field is always present from the
// backend, but the page may render a tick before /api/state lands).
function normWardCue(cue) {
  const c = cue && typeof cue === "object" && !Array.isArray(cue) ? cue : {};
  const id = Number(c.trinket_id);
  const cnt = Number(c.control_ward_count);
  return {
    trinket_ready: c.trinket_ready === true,
    trinket_id: Number.isFinite(id) && id > 0 ? Math.floor(id) : null,
    control_ward: c.control_ward === true,
    control_ward_count: Number.isFinite(cnt) && cnt > 0 ? Math.floor(cnt) : 0,
  };
}

// Is there anything worth showing? The chip strip hides entirely otherwise, so
// the cue APPEARS (and pulses) the moment it becomes actionable.
function wardCueActionable(cue) {
  const c = normWardCue(cue);
  return c.trinket_ready || c.control_ward;
}

// Signature over the ready flags + id + count: an unchanged cue on the next
// state tick does not repaint the DOM (idempotent-render discipline).
function wardCueSig(cue) {
  const c = normWardCue(cue);
  return `t${c.trinket_ready ? 1 : 0}${c.trinket_id || 0}c${c.control_ward ? 1 : 0}${c.control_ward_count}`;
}

// Which signals JUST transitioned not-ready -> ready (drives the single pulse).
// A null prev (first render) counts the currently-ready signals as edges so the
// cue catches the eye when the overlay first paints mid-game.
function risingEdges(prev, cur) {
  const c = normWardCue(cur);
  const p = prev ? normWardCue(prev) : null;
  return {
    trinket: c.trinket_ready && (!p || !p.trinket_ready),
    control: c.control_ward && (!p || !p.control_ward),
  };
}

// 3340 = Stealth Ward (yellow totem); 3363 = Farsight (blue). Both place a
// ward; the label just reflects which the operator carries.
function _trinketLabel(id) {
  return id === 3363 ? "FARSIGHT" : "WARD";
}

// Render the chip markup (pure). Empty string when nothing is actionable. No
// untrusted strings flow in (all fields are numbers/bools from our own
// backend), and the count is re-coerced through normWardCue so a wild value
// can never break out of the markup.
function wardCueHtml(cue) {
  const c = normWardCue(cue);
  if (!c.trinket_ready && !c.control_ward) return "";
  let html = "";
  if (c.trinket_ready) {
    html += `<span class="ward-chip trinket is-ready" data-cue="trinket">`
      + `<span class="ward-glyph" aria-hidden="true"></span>`
      + `<span class="ward-label">${_trinketLabel(c.trinket_id)} UP</span></span>`;
  }
  if (c.control_ward) {
    const n = c.control_ward_count > 1 ? ` x${c.control_ward_count}` : "";
    html += `<span class="ward-chip control" data-cue="control">`
      + `<span class="ward-glyph" aria-hidden="true"></span>`
      + `<span class="ward-label">CONTROL${n}</span></span>`;
  }
  return html;
}

// --- DOM render (overlay-only) -----------------------------------------------
let _prevCue = null; // last cue seen (for the rising-edge pulse)
let _sig = null;     // last painted signature
let _pulseTimer = null;

// Add the one-shot pulse class to whichever chip(s) just became ready, then
// strip it after the animation window so a later edge re-triggers it. A forced
// reflow between remove + add restarts the CSS animation if the same chip
// re-fires.
function _pulseEdges(mount, edges) {
  const fire = (sel) => {
    const el = mount.querySelector(sel);
    if (!el) return;
    el.classList.remove("is-pulsing");
    void el.offsetWidth; // reflow -> restart the keyframe
    el.classList.add("is-pulsing");
  };
  if (edges.trinket) fire('[data-cue="trinket"]');
  if (edges.control) fire('[data-cue="control"]');
  if (_pulseTimer) clearTimeout(_pulseTimer);
  _pulseTimer = setTimeout(() => {
    mount
      .querySelectorAll(".ward-chip.is-pulsing")
      .forEach((el) => el.classList.remove("is-pulsing"));
  }, 1300);
}

// Render from the raw liveclient block (lc.ward_cue). Hidden everywhere except
// the overlay shell; the 1920 dashboard never shows the warding cue strip.
export function renderWardCue(lc) {
  const mount = document.getElementById("am-ward-cue");
  if (!mount) return;
  if (!document.body || document.body.dataset.shell !== "overlay") {
    mount.hidden = true;
    return;
  }
  const cue = normWardCue(lc && lc.ward_cue);
  // Edge detection BEFORE we overwrite _prevCue.
  const edges = risingEdges(_prevCue, cue);
  _prevCue = cue;

  if (!wardCueActionable(cue)) {
    if (_sig !== "_empty") {
      mount.innerHTML = "";
      mount.hidden = true;
      _sig = "_empty";
    }
    return;
  }

  const sig = wardCueSig(cue);
  if (sig !== _sig) {
    mount.innerHTML = wardCueHtml(cue);
    mount.hidden = false;
    _sig = sig;
  }

  // One-shot pulse on a rising edge, honoring the operator pulse toggle (the
  // same gate overlay_pulse.js uses). prefers-reduced-motion is handled in CSS.
  let pulseOn = true;
  try {
    pulseOn = readOverlaySettings().pulseNotify !== false;
  } catch (_e) {
    pulseOn = true;
  }
  if (pulseOn && (edges.trinket || edges.control)) {
    _pulseEdges(mount, edges);
  }
}

// Test reset (module-scope edge/sig/timer state).
export function _resetWardCue() {
  _prevCue = null;
  _sig = null;
  if (_pulseTimer) clearTimeout(_pulseTimer);
  _pulseTimer = null;
}

export const __test = {
  normWardCue,
  wardCueActionable,
  wardCueSig,
  risingEdges,
  wardCueHtml,
  _trinketLabel,
};
