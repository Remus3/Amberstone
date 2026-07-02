// Trigger pill - ADR-007 (s169) decision_detector heartbeat surface.
//
// Polls /api/decisions/heartbeat at ~2 Hz, updates #trigger-pill in
// header row 2 with eval counter + green/amber/grey alive indicator.
// Also peeks /api/decisions for pending count so the pill outlines
// blue when something is actively asking for a choice (the actual
// A/B banner lives in panels/coach_decisions.js - this is just status).
//
// Hidden by CSS on client/tft modes; render still runs so the pill
// is up-to-date the moment the operator drops into a game.
import { el } from '../lib/helpers.js';
import { dedupFetch } from '../lib/dedup_fetch.js';

const TP = {
  pill: el("trigger-pill"),
  intervalMs: 500,   // 2 Hz - matches ds-pill cadence
};

let _lastSig = "";

async function _tick() {
  if (!TP.pill) return;
  let hb = null;
  let pendingCount = 0;
  try {
    const r = await fetch("/api/decisions/heartbeat");
    if (r.ok) hb = await r.json();
  } catch (_) { /* swallow - pill will go grey */ }
  try {
    // item 186: dedupFetch coalesces with coach_decisions' parallel
    // /api/decisions poll (1.5s cadence vs this module's 500ms).
    const r = await dedupFetch("/api/decisions");
    if (r.ok) {
      const j = await r.json();
      if (Array.isArray(j.pending)) pendingCount = j.pending.length;
    }
  } catch (_) { /* swallow */ }

  // Defaults when the file doesn't exist yet (supervisor never wrote).
  const counter = hb && typeof hb.counter === "number" ? hb.counter : 0;
  const ageS = hb && typeof hb.age_s === "number" ? hb.age_s : null;
  const alive = hb && hb.alive === true;
  const detectors = hb && typeof hb.detectors === "number" ? hb.detectors : 0;
  const gameTime = hb && typeof hb.game_time === "number" ? hb.game_time : 0;

  // Color tier:
  //   alive  - last eval <5s   -> green
  //   stale  - last eval 5-15s -> amber
  //   dead   - >15s or never   -> grey
  let tier;
  if (alive) tier = "alive";
  else if (ageS !== null && ageS < 15) tier = "stale";
  else tier = "dead";

  // Idempotency - skip DOM write when nothing changed.
  const sig = `${tier}|${counter}|${pendingCount}|${detectors}`;
  if (sig === _lastSig) return;
  _lastSig = sig;

  TP.pill.classList.remove("alive", "stale", "dead", "pending");
  TP.pill.classList.add(tier);
  if (pendingCount > 0) TP.pill.classList.add("pending");

  // Display: ●  N    where N is the per-match eval counter.
  // When a decision is pending, append an asterisk so the pill flags
  // attention even without reading the banner.
  const star = pendingCount > 0 ? "*" : "";
  TP.pill.textContent = `● ${counter}${star}`;

  // Tooltip carries the diagnostic detail.
  const ageStr = ageS === null ? "never" : `${ageS.toFixed(1)}s ago`;
  const gtStr = gameTime > 0 ? `${Math.floor(gameTime / 60)}:${String(Math.floor(gameTime % 60)).padStart(2, "0")}` : "-";
  TP.pill.title = (
    `decision_detector heartbeat\n` +
    `evals this match: ${counter}\n` +
    `last eval: ${ageStr}\n` +
    `game_time: ${gtStr}\n` +
    `detectors registered: ${detectors}\n` +
    `pending decisions: ${pendingCount}`
  );
}

function _start() {
  if (!TP.pill) return;
  // Idempotency guard - if this module is ever evaluated twice (test
  // harness, hot reload) only one interval may run, mirroring the
  // coach_choices.js window.__rc* self-bind pattern. ES modules are
  // singletons in the browser so this is belt-and-suspenders.
  if (typeof window !== "undefined") {
    if (window.__rcTriggerPillStarted) return;
    window.__rcTriggerPillStarted = true;
  }
  _tick();   // first paint
  setInterval(_tick, TP.intervalMs);
}

// Wait for DOMContentLoaded so #trigger-pill exists, then kick.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _start, { once: true });
} else {
  _start();
}

export { _tick as triggerPillTick };
