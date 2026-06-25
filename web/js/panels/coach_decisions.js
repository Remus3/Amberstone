// Coach decisions panel - coach decisions banner + recent coach calls log.
// setIntervals start at module load.
//
// Recovered from the former panels/bridge_pending.js (2026-06-24): that
// file was MIXED - it held this non-bridge coach UI alongside the now-
// decommissioned cross-Claude bridge pending-tasks panel. The bridge
// parts (renderBridgePending + its /api/bridge/pending poll) were dropped;
// the coach rendering below is preserved byte-for-byte in behavior.
import { el, safe, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { dedupFetch } from '../lib/dedup_fetch.js';


// -- Coach decisions banner -----------------------------------------
// Polls /api/decisions, renders pending coachable moments as a
// banner between header and main. Clicking Contest/Give/Skip POSTs
// to /api/decisions/<id> and animates removal. Records survive in
// data/decisions_log.jsonl on the backend for postmortem (V2).
const COACH_DECISIONS = {
  section: el("coach-decisions"),
  list: el("coach-decisions-list"),
  intervalMs: 1500,
  resolving: new Set(),   // ids currently animating-out (suppress redraw)
};

function renderCoachDecisions(pending) {
  const C = COACH_DECISIONS;
  if (!C.section || !C.list) return;
  if (!Array.isArray(pending) || pending.length === 0) {
    // Don't hide while animating - would yank the row mid-animation.
    if (C.resolving.size === 0) C.section.hidden = true;
    C.list.innerHTML = "";
    return;
  }
  C.section.hidden = false;
  // Diff by id so we don't re-create rows that already exist (animations
  // re-run on every render = visual chaos when poll fires every 1.5s).
  const wantIds = new Set(pending.map(p => p.id));
  for (const li of Array.from(C.list.children)) {
    if (!wantIds.has(li.dataset.id)) li.remove();
  }
  const haveIds = new Set(Array.from(C.list.children).map(li => li.dataset.id));
  for (const p of pending) {
    if (haveIds.has(p.id) || C.resolving.has(p.id)) continue;
    const li = document.createElement("li");
    li.className = "coach-decision";
    li.dataset.id = p.id;
    li.dataset.type = p.type || "";

    const text = document.createElement("div");
    text.className = "coach-decision-text";
    const title = document.createElement("p");
    title.className = "coach-decision-title";
    title.textContent = p.title || p.id;
    const sub = document.createElement("p");
    sub.className = "coach-decision-sub";
    sub.textContent = p.subtitle || "";
    text.appendChild(title);
    if (p.subtitle) text.appendChild(sub);

    const actions = document.createElement("div");
    actions.className = "coach-decision-actions";
    const opts = (Array.isArray(p.options) && p.options.length)
      ? p.options : ["contest", "give"];
    // Always offer skip as a final option so the user can dismiss.
    const allOpts = opts.includes("skip") ? opts : [...opts, "skip"];
    for (const opt of allOpts) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "coach-decision-btn";
      btn.dataset.choice = opt;
      btn.textContent = opt.toUpperCase();
      btn.addEventListener("click", () => recordChoice(p.id, opt, li, actions));
      actions.appendChild(btn);
    }

    li.appendChild(text);
    li.appendChild(actions);
    C.list.appendChild(li);
  }
}

async function recordChoice(id, choice, li, actions) {
  // Disable the row's buttons immediately so a fast double-click can't
  // double-post. Mark id as resolving so the next poll doesn't repaint.
  COACH_DECISIONS.resolving.add(id);
  for (const b of actions.querySelectorAll("button")) b.disabled = true;
  li.classList.add("resolving");
  try {
    const r = await fetch(`/api/decisions/${encodeURIComponent(id)}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({choice}),
    });
    if (!r.ok) {
      // Roll back: re-enable, drop resolving so next poll resurrects it.
      for (const b of actions.querySelectorAll("button")) b.disabled = false;
      li.classList.remove("resolving");
      COACH_DECISIONS.resolving.delete(id);
      return;
    }
  } catch (_) {
    for (const b of actions.querySelectorAll("button")) b.disabled = false;
    li.classList.remove("resolving");
    COACH_DECISIONS.resolving.delete(id);
    return;
  }
  // Success - let CSS finish the fade, then remove + clear resolving.
  setTimeout(() => {
    try { li.remove(); } catch (_) {}
    COACH_DECISIONS.resolving.delete(id);
    // If list is now empty, hide the banner.
    if (COACH_DECISIONS.list && COACH_DECISIONS.list.children.length === 0) {
      if (COACH_DECISIONS.section) COACH_DECISIONS.section.hidden = true;
    }
  }, 240);
}

async function pollCoachDecisions() {
  if (document.hidden) return;
  try {
    // item 186: dedupFetch coalesces with trigger_pill's parallel
    // /api/decisions poll (500ms cadence vs this module's 20s; the
    // 100ms grace TTL covers the typical overlap window).
    const r = await dedupFetch("/api/decisions");
    if (!r.ok) return;
    const d = await r.json();
    renderCoachDecisions(d.pending || []);
  } catch (_) {}
}
setInterval(pollCoachDecisions, COACH_DECISIONS.intervalMs);
pollCoachDecisions();

// -- Recent coach calls (Tier 4 #18, 2026-05-01) --------------------
// Reads /api/decisions/log every 30s and renders the last N resolved
// decisions so the user can review "did I contest the right Barons?"
// alongside the live pending banner above. The audit's "kill-time
// graph overlay" was speculative; the resolved-log readout is the
// useful contained version of that idea.
const RECENT_CALLS = {
  section: el("recent-coach-calls"),
  list:    el("recent-coach-calls-list"),
  empty:   el("recent-coach-calls-empty"),
  intervalMs: 30000,
  limit:   8,
};

function renderRecentCoachCalls(entries) {
  const R = RECENT_CALLS;
  if (!R.section || !R.list) return;
  if (!Array.isArray(entries) || entries.length === 0) {
    R.section.hidden = true;
    R.list.innerHTML = "";
    if (R.empty) R.empty.hidden = false;
    return;
  }
  R.section.hidden = false;
  if (R.empty) R.empty.hidden = true;
  R.list.innerHTML = "";
  for (const e of entries) {
    const li = document.createElement("li");
    li.className = "recent-coach-call rcc-choice-" + (e.choice || "skip");

    const when = document.createElement("span");
    when.className = "rcc-when";
    when.textContent = _formatRelativeAge(e.decided_at_unix || e.created_at_unix);

    const title = document.createElement("span");
    title.className = "rcc-title";
    title.textContent = e.title || e.id || "decision";

    const choice = document.createElement("span");
    choice.className = "rcc-choice";
    choice.textContent = (e.choice || "skip").toUpperCase();

    li.appendChild(when);
    li.appendChild(title);
    li.appendChild(choice);
    R.list.appendChild(li);
  }
}

async function pollRecentCoachCalls() {
  if (document.hidden) return;
  try {
    const r = await fetch(`/api/decisions/log?limit=${RECENT_CALLS.limit}`);
    if (!r.ok) return;
    const d = await r.json();
    renderRecentCoachCalls(d.entries || []);
  } catch (_) {}
}
setInterval(pollRecentCoachCalls, RECENT_CALLS.intervalMs);
pollRecentCoachCalls();

export { renderCoachDecisions, renderRecentCoachCalls };
