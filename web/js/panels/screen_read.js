// On-demand VLM coach pill (s240, AUTONOMOUS_AUDIT opportunity #3).
//
// Operator clicks "SCREEN READ" -> POST /api/command {screen_read} ->
// backend does ONE Sonnet pass over the frame RC already holds and
// writes data/screen_read.json -> the state-builder stamps it onto
// /api/state.screen_read -> this module renders it on a DEDICATED pill
// (separate from #rn-immediate, so an on-demand read the operator wants
// to dwell on is NOT clobbered by the next ~2s coach tick).
//
// Mirrors the s184.1 archetype-nudge chip pattern: a self-contained
// state-fed pill with a one-time-bound action, called from the same
// /api/state consumption points in main.js. Fire-and-forget POST - the
// backend always writes a terminal status, the poll syncs the UI.

import { el } from '../lib/helpers.js';

const SR = {
  btn:  el("rn-sr-btn"),
  pill: el("rn-sr-pill"),
};

let _lastSig = "";
let _failsafe = 0;

// Friendly text per terse backend error code.
function _errText(code) {
  switch (code) {
    case "no_fresh_frame":
      return "no live frame - is a game running + the vision agent up?";
    case "no_api_key":
      return "vision key missing (API-Key-Claude.txt)";
    case "vision_failed":
    case "worker_failed":
      return "vision call failed - try again";
    case "empty_note":
      return "no read produced - try again";
    default:
      return code ? String(code) : "unavailable";
  }
}

function _age(ts) {
  const t = Number(ts) || 0;
  if (!t) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function _setReading(on) {
  if (!SR.btn) return;
  SR.btn.disabled = !!on;
  SR.btn.classList.toggle("is-reading", !!on);
}

async function _trigger() {
  if (!SR.btn || SR.btn.disabled) return;
  // Optimistic - flip to reading immediately; the pending-status poll
  // (and then the terminal status) authoritatively re-syncs button +
  // pill. Failsafe re-enables if no state update lands (e.g. the
  // result write failed before the worker could stamp a status).
  _setReading(true);
  if (SR.pill) {
    SR.pill.hidden = false;
    SR.pill.className = "rn-sr-pill is-pending";
    SR.pill.textContent = "reading the screen...";
  }
  _lastSig = "trigger";  // force the next render to repaint
  clearTimeout(_failsafe);
  _failsafe = setTimeout(() => _setReading(false), 20000);
  try {
    await fetch("/api/command", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", ...(localStorage.getItem("rc_dash_token") ? {"X-RC-Token": localStorage.getItem("rc_dash_token")} : {}) },
      body: JSON.stringify({ command: "screen_read" }),
    });
  } catch (_) { /* swallow - backend always writes a terminal status */ }
}

// Bind once at module load. The button is declared in index.html; this
// listener is harmless until the panel is on screen.
if (SR.btn && !SR.btn.dataset.bound) {
  SR.btn.addEventListener("click", _trigger);
  SR.btn.dataset.bound = "1";
}

export function renderScreenRead(stateObj) {
  if (!SR.pill || !SR.btn) return;
  const sr = stateObj && stateObj.screen_read;
  // Never triggered this session (or stale empty doc) - keep the pill
  // hidden and the button armed.
  if (!sr || typeof sr !== "object" || !sr.status) {
    if (!SR.pill.hidden) SR.pill.hidden = true;
    _setReading(false);
    _lastSig = "";
    return;
  }

  const status = String(sr.status);
  const text = String(sr.text || "");
  const error = sr.error == null ? "" : String(sr.error);
  const ts = Number(sr.ts) || 0;

  // 2s/500ms poll cadence - skip DOM writes when nothing changed so the
  // button hover/focus state isn't torn down every tick.
  const sig = `${status}|${ts}|${text}|${error}`;
  if (sig === _lastSig) return;
  _lastSig = sig;

  SR.pill.hidden = false;
  if (status === "pending") {
    SR.pill.className = "rn-sr-pill is-pending";
    SR.pill.textContent = "reading the screen...";
    SR.pill.title = "one Sonnet pass over the current frame";
    _setReading(true);
    return;
  }

  // Terminal - clear the optimistic failsafe + re-arm the button.
  clearTimeout(_failsafe);
  _setReading(false);

  if (status === "ok" && text) {
    SR.pill.className = "rn-sr-pill is-ok";
    SR.pill.textContent = text;
    const a = _age(ts);
    SR.pill.title = `VLM coach${a ? " - " + a : ""}`;
  } else {
    SR.pill.className = "rn-sr-pill is-error";
    SR.pill.textContent = _errText(error || (status !== "ok" ? status : ""));
    SR.pill.title = "click SCREEN READ to try again";
  }
}

// Test/diagnostic seam - reset the dedup signature so the next render
// writes the DOM unconditionally (mirrors _resetArchetypeNudgeSig).
export function _resetScreenReadSig() { _lastSig = ""; }
