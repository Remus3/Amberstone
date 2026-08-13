// A/B tutoring coach choice block.
//
// Reads state.coach.choices (an array stamped server-side by
// core.coach_choices.parse_choices + synthesize_simple_choices) and
// paints 2-3 chip buttons in #rn-choices, which now sits directly under
// #rn-action and visually occupies the slot that used to host the
// Immediate prose (right_now.js hides #rn-immediate when choices are
// non-empty - item 189, 2026-05-25). Each chip carries:
// - the option key letter A/B/C
// - an ALT+N hotkey hint (1/2/3) shown as a sub-pill on every chip
// - the option label (Contest / Concede / Engage / Disengage / etc)
// - confidence band (low / mid / high) rendered as a 3-segment bar
// - source-tag pill (synth / archetype_sim / winrate_hist / etc)
// On click OR Alt+1/Alt+2/Alt+3 hotkey: POST /api/coach-choice with the
// selection + a tiny game context snapshot, log-only on the server; chip
// visually marks selected with a green ring + brief "ACK" toast.
//
// When state.coach.choices is empty or absent, the mount is hidden + no
// DOM is generated. The hotkey handler is a NO-OP when no chips exist.

import { stripCoachTags } from '../lib/helpers.js';

import { directivesAllowed } from '../lib/live_directive_gate.js';

const MOUNT_ID = "rn-choices";

// Module-level state: latest rendered state (for game_context snapshot
// inside the keydown handler, which fires outside renderCoachChoices's
// scope) + dedupe key + cache of {A: chipEl, B: chipEl, C: chipEl}.
let _lastSig = "";
let _lastSelectedKey = null;
let _latestState = null;
let _chipByKey = {};

function _chipsSignature(choices) {
  if (!Array.isArray(choices) || choices.length === 0) return "";
  return choices.map((c) => `${c.key}:${c.label}:${c.confidence}:${c.source_tag || ""}:${c.trigger || ""}:${c.rebranch_when || ""}:${c.rebranch_to || ""}`).join("|");
}

function _bandDots(band) {
  const total = 3;
  const filled = band === "high" ? 3 : band === "low" ? 1 : 2;
  let html = "";
  for (let i = 0; i < total; i++) {
    html += `<span class="rc-band-dot${i < filled ? " filled" : ""}"></span>`;
  }
  return `<span class="rc-band rc-band-${band}" title="confidence: ${band}">${html}</span>`;
}

// Map chip key A/B/C to the corresponding ALT+digit hotkey 1/2/3.
const _KEY_TO_DIGIT = { A: "1", B: "2", C: "3" };

// HTML-escape for the LLM-derived choice text (label / expected_outcome /
// source_tag / trigger). parse_choices (core/coach_choices.py) only
// length-limits these fields - it does NOT escape markup, so the
// Haiku/Sonnet output is untrusted at this boundary. Escape both the
// element-content and the attribute interpolations (& < > " all matter
// in an HTML attribute).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _chipHtml(c) {
  const k = (c.key || "?").slice(0, 1).toUpperCase();
  // Strip the coach bracket-timer tags BEFORE the length slice (these raw
  // fields bypass safe(), so they would otherwise render literal [t]..[/t]).
  const label = stripCoachTags(c.label || "").slice(0, 80);
  const outcome = stripCoachTags(c.expected_outcome || "").slice(0, 160);
  const src = (c.source_tag || "").slice(0, 32);
  const trigger = stripCoachTags(c.trigger || "").slice(0, 120);
  const rebranchWhen = stripCoachTags(c.rebranch_when || "").slice(0, 120);
  const rebranchTo = (c.rebranch_to || "").slice(0, 1).toUpperCase();
  const confidence = String(c.confidence == null ? "" : c.confidence);
  const srcPill = src ? `<span class="rc-src">${_esc(src)}</span>` : "";
  const digit = _KEY_TO_DIGIT[k] || "";
  const hotkeyPill = digit
    ? `<span class="rc-hotkey" title="Press Alt+${digit} to pick">Alt+${digit}</span>`
    : "";
  // RC2 5.3: the trigger names the live condition the option assumes, shown
  // as a muted sub-line under the label (overlay HUD hides it - lean glance).
  const triggerLine = trigger
    ? `<span class="rc-trigger">${_esc(trigger)}</span>`
    : "";
  // RC2 5.4: the condition-change branch ("-> B if enemy goes missing"). Both
  // halves are required to render; muted, dashboard-only (overlay HUD hides it).
  const rebranchLine = (rebranchWhen && rebranchTo)
    ? `<span class="rc-rebranch">-&gt; ${_esc(rebranchTo)} if ${_esc(rebranchWhen)}</span>`
    : "";
  return `
    <button type="button" class="rc-chip" data-key="${_esc(k)}" data-label="${_esc(label)}"
            data-confidence="${_esc(confidence)}" data-source="${_esc(src)}"
            title="${_esc(outcome)}">
      <span class="rc-key">${_esc(k)}</span>
      <span class="rc-labelcol">
        <span class="rc-label">${_esc(label)}</span>
        ${triggerLine}
        ${rebranchLine}
      </span>
      ${hotkeyPill}
      ${_bandDots(confidence)}
      ${srcPill}
    </button>`;
}

function _gameContextSnapshot(state) {
  const coach = (state && state.coach) || {};
  const lc = (state && state.liveclient) || {};
  return {
    mode_key:     state ? state.mode_key : "",
    champion:     coach.champion || lc.champion || "",
    level:        lc.level || coach.level || 0,
    game_time_s:  lc.game_time_s || coach.game_time_s || 0,
    kda:          coach.kda || lc.kda || "",
    cs:           coach.cs || lc.cs || 0,
  };
}

async function _postSelection(chip, state) {
  const body = {
    choice_key:    chip.dataset.key,
    choice_label:  chip.dataset.label,
    confidence:    chip.dataset.confidence,
    source_tag:    chip.dataset.source,
    game_context:  _gameContextSnapshot(state),
  };
  try {
    const r = await fetch("/api/coach-choice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      console.warn("coach-choice POST failed:", r.status);
    }
  } catch (e) {
    console.warn("coach-choice POST error:", e);
  }
}

function _activateChip(mount, chip, state) {
  if (!chip) return;
  if (_lastSelectedKey === chip.dataset.key) return;
  _lastSelectedKey = chip.dataset.key;
  mount.querySelectorAll(".rc-chip").forEach((c) => c.classList.toggle(
    "rc-selected", c.dataset.key === _lastSelectedKey));
  _postSelection(chip, state).then(() => {
    // ACK toast: brief "PICKED" bubble over the chip so a hotkey-driven
    // selection (no mouse cursor near the chip) still has visible
    // feedback that the choice was logged.
    const bubble = document.createElement("span");
    bubble.className = "rc-ack-bubble";
    bubble.textContent = "PICKED";
    chip.appendChild(bubble);
    requestAnimationFrame(() => bubble.classList.add("show"));
    setTimeout(() => bubble.remove(), 900);
  }).catch(() => {});
}

function _onAltDigitKeydown(ev) {
  if (!ev.altKey) return;
  if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
  // ev.code is layout-stable (e.g. Digit1) vs ev.key which depends on
  // OS layout. Browsers also emit ev.key for Alt+digit on most layouts
  // - check both for robustness.
  let key = null;
  if (ev.code === "Digit1" || ev.key === "1") key = "A";
  else if (ev.code === "Digit2" || ev.key === "2") key = "B";
  else if (ev.code === "Digit3" || ev.key === "3") key = "C";
  if (!key) return;
  const chip = _chipByKey[key];
  if (!chip) return;
  ev.preventDefault();
  ev.stopPropagation();
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  _activateChip(mount, chip, _latestState);
}

// Bind ALT+1/2/3 once at module load. The handler is a NO-OP when no
// choices are currently rendered (chip lookup returns undefined), so
// the bind is safe even before the first coach tick.
if (typeof window !== "undefined" && !window.__rcCoachChoicesAltBound) {
  window.addEventListener("keydown", _onAltDigitKeydown, { capture: true });
  window.__rcCoachChoicesAltBound = true;
}

export function renderCoachChoices(state) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  // Stash the freshest state in module scope so the keydown handler
  // (which fires outside this function's closure) can build a
  // game_context snapshot at the moment the operator hits Alt+N.
  _latestState = state;
  const coach = (state && state.coach) || {};
  // B4 (RM-189): the A/B decision chips are the most literal form of the
  // banned artefact (a notification dictating player action from live game
  // state), and #rn-choices is one of only three mounts the overlay shell
  // keeps visible. Coercing to [] here reuses the existing clear-and-hide
  // branch below rather than adding a second teardown path. The server has
  // already blanked coach.choices; this catches a replayed cached tick.
  const choices = (directivesAllowed(state) && Array.isArray(coach.choices))
    ? coach.choices
    : [];
  const sig = _chipsSignature(choices);
  if (choices.length === 0) {
    if (_lastSig !== "") {
      mount.innerHTML = "";
      mount.hidden = true;
      _lastSig = "";
      _lastSelectedKey = null;
      _chipByKey = {};
    }
    return;
  }
  if (sig === _lastSig) return;
  _lastSig = sig;
  _lastSelectedKey = null;
  mount.hidden = false;
  mount.innerHTML = choices.map(_chipHtml).join("");
  _chipByKey = {};
  mount.querySelectorAll(".rc-chip").forEach((chip) => {
    _chipByKey[chip.dataset.key] = chip;
    chip.addEventListener("click", () => _activateChip(mount, chip, _latestState));
  });
}

// Test seam.
export const _internals = {
  _chipsSignature,
  _bandDots,
  _chipHtml,
  _esc,
  _gameContextSnapshot,
  _onAltDigitKeydown,
  _activateChip,
  _KEY_TO_DIGIT,
  MOUNT_ID,
};
