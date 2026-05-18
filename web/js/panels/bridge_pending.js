// Bridge Pending panel - coach decisions banner, recent coach calls log,
// bridge task pending display. setIntervals start at module load.
import { el, safe, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';


// ── Coach decisions banner ─────────────────────────────────────────
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
    const r = await fetch("/api/decisions");
    if (!r.ok) return;
    const d = await r.json();
    renderCoachDecisions(d.pending || []);
  } catch (_) {}
}
setInterval(pollCoachDecisions, COACH_DECISIONS.intervalMs);
pollCoachDecisions();

// ── Recent coach calls (Tier 4 #18, 2026-05-01) ─────────────────────
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

// ── Bridge Pending escalations (2026-05-03) ────────────────────────
// Reads /api/bridge/pending every 20s - the bridge_watcher writes
// the queue, this only displays it. Render is idempotent (sig
// change-detection) to avoid flicker. Menu badge shows depth so the
// operator sees pending work without navigating; sub-page shows full
// detail. Read-only at MVP; drain via /process-bridge-tasks.
const BRIDGE_PENDING = {
  list:    el("bridge-pending-list"),
  empty:   el("bridge-pending-empty"),
  count:   el("bridge-pending-count"),
  badge:   el("bridge-pending-menu-badge"),
  intervalMs: 20000,
};

function renderBridgePending(payload) {
  const B = BRIDGE_PENDING;
  const tasks = (payload && Array.isArray(payload.tasks)) ? payload.tasks : [];
  const now = Date.now() / 1000;
  const live = tasks.filter(t => !t.ttl_at || t.ttl_at > now);

  if (B.count) B.count.textContent = String(live.length);
  if (B.badge) {
    B.badge.textContent = String(live.length);
    B.badge.hidden = live.length === 0;
  }

  if (!B.list) return;
  if (live.length === 0) {
    if (B.list.dataset.sig !== "empty") {
      B.list.innerHTML = "";
      B.list.dataset.sig = "empty";
    }
    if (B.empty) B.empty.hidden = false;
    return;
  }
  if (B.empty) B.empty.hidden = true;

  const sig = live.map(t => `${t.task_id}:${t.claimed_by||""}:${t.received_at||0}`).join("|");
  if (B.list.dataset.sig === sig) return;
  B.list.dataset.sig = sig;
  B.list.innerHTML = "";
  for (const t of live) {
    const li = document.createElement("li");
    li.className = "bridge-pending-item";
    if (t.claimed_by) li.classList.add("bp-claimed");

    const head = document.createElement("div");
    head.className = "bp-head";
    const from = document.createElement("span");
    from.className = "bp-from";
    from.textContent = (t.from || "?").toUpperCase();
    const kind = document.createElement("span");
    kind.className = "bp-kind";
    kind.textContent = t.kind || "task";
    const age = document.createElement("span");
    age.className = "bp-age";
    age.textContent = _formatRelativeAge(t.received_at);
    const id = document.createElement("span");
    id.className = "bp-id";
    id.textContent = t.task_id || "";
    id.title = "click to copy";
    head.append(from, kind, age, id);

    const summary = document.createElement("div");
    summary.className = "bp-summary";
    summary.textContent = t.summary || "(no summary)";

    li.append(head, summary);

    if (t.reason) {
      const reason = document.createElement("div");
      reason.className = "bp-reason";
      reason.textContent = t.reason;
      li.append(reason);
    }
    if (t.prompt) {
      const prompt = document.createElement("pre");
      prompt.className = "bp-prompt";
      prompt.textContent = t.prompt;
      li.append(prompt);
    }
    if (t.claimed_by) {
      const claim = document.createElement("div");
      claim.className = "bp-claim";
      claim.textContent = `claimed by ${t.claimed_by}`;
      li.append(claim);
    }

    // Action row (accept / defer / dismiss). POSTs to
    // /api/bridge/pending/<id>/<action>; on success refresh the panel.
    const actions = document.createElement("div");
    actions.className = "bp-actions";
    for (const action of ["accept", "defer", "dismiss"]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `bp-btn bp-btn-${action}`;
      btn.textContent = action.toUpperCase();
      btn.dataset.taskId = t.task_id || "";
      btn.dataset.action = action;
      btn.addEventListener("click", _bridgePendingAction);
      actions.append(btn);
    }
    li.append(actions);

    B.list.appendChild(li);
  }
}

async function _bridgePendingAction(ev) {
  const btn = ev.currentTarget;
  const taskId = btn.dataset.taskId;
  const action = btn.dataset.action;
  if (!taskId || !action) return;
  if (action === "dismiss" && !confirm(`Dismiss "${taskId}"?`)) return;
  btn.disabled = true;
  btn.classList.add("bp-btn-busy");
  try {
    const r = await fetch(`/api/bridge/pending/${encodeURIComponent(taskId)}/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: "{}",
    });
    if (!r.ok) {
      const err = await r.text();
      btn.classList.add("bp-btn-err");
      btn.title = `failed: ${err.slice(0, 200)}`;
    } else {
      // Force re-render by invalidating the sig cache.
      if (BRIDGE_PENDING.list) BRIDGE_PENDING.list.dataset.sig = "";
      pollBridgePending();
    }
  } catch (e) {
    btn.classList.add("bp-btn-err");
    btn.title = `error: ${String(e).slice(0, 200)}`;
  } finally {
    btn.disabled = false;
    btn.classList.remove("bp-btn-busy");
  }
}

async function pollBridgePending() {
  if (document.hidden) return;
  try {
    const r = await fetch("/api/bridge/pending");
    if (!r.ok) return;
    const d = await r.json();
    renderBridgePending(d);
  } catch (_) {}
}
setInterval(pollBridgePending, BRIDGE_PENDING.intervalMs);
pollBridgePending();

export { renderCoachDecisions, renderRecentCoachCalls, renderBridgePending };
