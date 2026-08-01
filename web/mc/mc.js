// Mission Control - the RC control plane, standalone (S10, 2026-07-31).
//
// This file imports NO game-dashboard code, by design. During S9 a single
// `mk` ReferenceError in web/js/panels/dev.js - game-dashboard code, not
// Mission Control code - left the INTERRUPT victim list unrendered while the
// armed kill button still displayed. That is the measurement S10 exists to
// answer, so keep this file's import list at exactly one entry.
import { createArmController } from './arm_confirm.js';

// Fix round 1 (2026-07-31, MINOR 7): there is NO module-level `mk` here on
// purpose. A prior version of this file defined one "for structural parity"
// with dev.js, but the reviewer proved it dead by replacing its body with a
// `throw` - every flow behaved identically, because the real `mk` this file
// uses is the function-LOCAL `const mk` inside `renderLoopStatus` below
// (verified: grep -n "function mk\|const mk\|mk =" web/js/panels/dev.js).
// A module-scope `mk` is worse than neutral: the comment inside
// `_mcPaintInterrupt` below states plainly that calling `mk` at module scope
// is a ReferenceError, and that statement is exactly what makes it safe for
// a future module-scope paint function to call `document.createElement`
// directly instead - a module-level `mk` would silently make that statement
// false, turning a loud failure into a wrong-scope success. If you add one
// back, you must correct that comment in the same edit.

// Bearer token. Prompted once, kept in localStorage. A 401 clears it and
// re-prompts; a 503 means the SERVER has no token configured, which is a
// deploy problem the operator must fix on Legion - retrying cannot help.
const TOKEN_KEY = "rc_mc_token";

function mcToken() {
  let t = localStorage.getItem(TOKEN_KEY);
  if (!t) {
    t = window.prompt("Mission Control token");
    if (t) localStorage.setItem(TOKEN_KEY, t);
  }
  return t || "";
}

function mcPost(body) {
  return fetch("/api/loop-control", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + mcToken(),
    },
    body: JSON.stringify(body),
  }).then((r) => {
    if (r.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      throw new Error("unauthorized - token cleared, retry to re-enter it");
    }
    if (r.status === 503) {
      throw new Error("auth not configured on the server");
    }
    return r.json();
  });
}

// -- Headless loop status (2026-06-07) ----------------------------
// Read-only, mobile-friendly surface over /api/loop-status (which reads the
// ops/loop/control/* files + last commit). Rendered on each Settings show so
// a Gemini-directed loop is watchable from the phone over Tailscale.
//
// CONTROL half (2026-06-07): POST /api/loop-control writes ops/loop/control/*
// so the loop can be halted / resumed / re-directed from the phone. The helper
// re-renders the card and echoes the action result into #loop-ctl-msg.
function _loopControl(action, extra) {
  mcPost(Object.assign({ action: action }, extra || {}))
    .then((d) => {
      const txt = d && d.ok
        ? action + ": " + (d.detail || "ok")
        : "error: " + (d && d.error ? d.error : "failed");
      renderLoopStatus(txt);
    })
    .catch((e) => renderLoopStatus((e && e.message) || "request failed"));
}

// -- Mission Control S4: lock rows + shortcuts 1 and 2 ------------
// Three lock states, never two. A lock file whose pid is DEAD reads exactly
// like a live one from the file alone, so RECLAIMABLE gets its own colour and
// its own note and is NEVER collapsed into RUNNING - collapsing them is what
// made a dead loop report as live (docs/MISSION_CONTROL_PLAN.md).
const _LOCK_STATES = ["FREE", "RUNNING", "RECLAIMABLE"];

function _loopAge(secs) {
  if (typeof secs !== "number" || !isFinite(secs) || secs < 0) return null;
  if (secs < 90) return Math.round(secs) + "s";
  if (secs < 5400) return Math.round(secs / 60) + "m";
  if (secs < 172800) return Math.round(secs / 3600) + "h";
  return Math.round(secs / 86400) + "d";
}

function _loopLockRow(mk, label, block) {
  // An absent block means S1 is not installed. It still renders a row: a
  // vanishing row reflows everything under it (feedback_no_reflow_on_data_absence).
  const known = block && _LOCK_STATES.indexOf(block.state) >= 0;
  const st = known ? block.state : "UNAVAILABLE";
  const cls = st.toLowerCase();
  const row = mk("div", "loop-lock-row");
  row.append(mk("span", "loop-lock-label", label));
  row.append(mk("span", "loop-lock-dot " + cls));
  row.append(mk("b", "loop-lock-state " + cls, st));

  const bits = [];
  if (known) {
    if (block.lane) bits.push("lane " + block.lane);
    if (block.pid != null) bits.push("pid " + block.pid);
    if (block.run_id) bits.push("run " + block.run_id);
    const age = _loopAge(block.age_s);
    if (age) bits.push("held " + age);
  }
  // No `dim` class here: web/css has no bare `.dim` rule, only descendant-scoped
  // ones, so it is inert. .loop-lock-meta owns its own colour.
  row.append(mk("span", "loop-lock-meta", bits.join("  -  ")));
  if (st === "RECLAIMABLE") {
    row.append(mk("span", "loop-lock-note", "holder is gone - free to claim"));
  }
  return row;
}

// The two shortcuts that cannot spawn a lane. Both only WRITE an intent file
// the running session consumes at its next safe boundary - nothing is killed
// and nothing is signalled.
const _MC_SHORTCUTS = [
  { id: "halt_save", label: "Halt and Save",
    hint: "finish the step, run the done ritual, write the next-session prompt to the Desktop" },
  { id: "done_continue", label: "/done Continue",
    hint: "done ritual, then auto-clear and re-run the prompt it just emitted" },
];

// The key is minted at ARM and discarded on disarm - see web/mc/arm_confirm.js.
// A key reused across arms replays the first refusal forever, so the button
// looks alive and is permanently inert. MEASURED against the real S2 route.
const _mcArm = createArmController({ onChange: () => _mcPaint() });
let _mcHost = null;
let _mcTimer = null;

function _mcSetTimer(on) {
  if (on && _mcTimer == null) {
    _mcTimer = setInterval(() => { _mcArm.tick(); _mcPaint(); }, 250);
  } else if (!on && _mcTimer != null) {
    clearInterval(_mcTimer);
    _mcTimer = null;
  }
}

function _mcMsg(text) {
  const node = document.getElementById("loop-ctl-msg");
  if (node) node.textContent = text;
}

function _mcFire(shortcut, key) {
  _mcMsg(shortcut.label + ": sending...");
  mcPost({
    action: "queue_intent", intent: shortcut.id, idempotency_key: key,
  })
    .then((d) => {
      if (d && d.ok) {
        _mcMsg(shortcut.label + ": " + (d.detail || "queued")
          + (d.replayed ? " (replayed)" : ""));
      } else {
        const why = d && (d.refused || d.error) ? (d.refused || d.error) : "failed";
        _mcMsg(shortcut.label + " refused: " + why);
      }
    })
    .catch((e) => _mcMsg(shortcut.label + ": " + ((e && e.message) || "request failed")));
}

// S5: the headless lanes. Mutually exclusive - one lock - and a fire against a
// held lane is REFUSED, never queued. The wired list comes from the SERVER
// (lanes_available.wired, derived from the launcher's own map) so the panel
// cannot drift as S6 and S8 wire the rest.
const _LANE_LABELS = {
  "upgrade": "Headless-Upgrade",
  "uiux": "Headless-UIUX",
  "research": "Headless-Research",
  "ds": "Headless-DS",
  "repo": "Headless-Repo",
  "true-audit": "Headless-True-Audit",
};

let _mcLanes = { all: [], wired: [] };
let _mcLaneHost = null;

function _mcSteerKey() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  let out = "";
  for (let i = 0; i < 8; i += 1) {
    out += Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
    if (i === 1 || i === 3 || i === 5) out += "-";
  }
  return out;
}

function _mcRunId() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID().slice(0, 8);
  return Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
}

function _mcFireLane(lane, key) {
  const label = _LANE_LABELS[lane] || lane;
  _mcMsg(label + ": starting...");
  mcPost({
    action: "fire_lane", lane: lane,
    run_id: _mcRunId(), idempotency_key: key,
  })
    .then((d) => {
      let txt;
      if (d && d.ok) {
        txt = label + ": " + (d.detail || "running")
          + (d.replayed ? " (replayed)" : "");
      } else if (d && d.refused) {
        txt = label + " REFUSED - " + (d.detail || d.refused);
      } else {
        txt = label + " failed: " + ((d && d.error) || "request failed");
      }
      // Fix round 1 (IMPORTANT 6): renderLoopStatus() bare (no argument)
      // rebuilds #loop-ctl-msg EMPTY - _mcMsg's write above would show for
      // a moment then be clobbered the instant this rebuild lands. Thread
      // the same text through so it survives the rebuild, matching the
      // pattern _loopControl already used.
      _mcMsg(txt);
      renderLoopStatus(txt);
    })
    .catch((e) => _mcMsg(label + ": " + ((e && e.message) || "request failed")));
}

function _mcPaintLanes() {
  const host = _mcLaneHost;
  if (!host || !host.isConnected) return false;
  const focusedId = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  let refocus = null;
  host.innerHTML = "";
  const wired = _mcLanes.wired || [];
  const all = (_mcLanes.all && _mcLanes.all.length) ? _mcLanes.all
    : Object.keys(_LANE_LABELS);
  let anyArmed = false;
  all.forEach((lane) => {
    const id = "lane:" + lane;
    const isWired = wired.indexOf(lane) >= 0;
    const armed = _mcArm.isArmed(id);
    if (armed) anyArmed = true;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "loop-btn loop-lane-btn" + (armed ? " loop-btn-armed" : "")
      + (isWired ? "" : " loop-lane-unwired");
    b.dataset.mcId = id;
    if (focusedId === id) refocus = b;
    b.setAttribute("aria-pressed", armed ? "true" : "false");
    const label = _LANE_LABELS[lane] || lane;
    if (!isWired) {
      b.disabled = true;
      b.textContent = label;
      b.title = "no command doc wired yet - a later stage lands this lane";
      b.setAttribute("aria-disabled", "true");
    } else if (armed) {
      b.textContent = "Confirm " + label + " ("
        + Math.ceil(_mcArm.remainingMs() / 1000) + "s)";
      b.title = "fires a real headless run in its own git worktree";
    } else {
      b.textContent = label;
      b.title = "fires a real headless run in its own git worktree";
    }
    b.addEventListener("click", () => {
      if (b.disabled) return;
      if (_mcArm.isArmed(id)) {
        const res = _mcArm.confirm(id);
        if (res.fired) _mcFireLane(lane, res.key);
        return;
      }
      _mcArm.arm(id);
      _mcMsg("armed: click again within 3s to start " + label);
    });
    host.append(b);
  });
  if (refocus) refocus.focus();
  return anyArmed;
}

// S9 - INTERRUPT. The only Mission Control action that kills a process, so it
// is the only one whose ARM does a round trip first: the plan requires the
// button to NAME the agents it will kill BEFORE the confirm, and the names can
// only come from the server.
//
// The fingerprint lives here beside the victims and is dropped by the same
// paint that observes the arm has lapsed - deliberately the same lifecycle as
// the idempotency key in arm_confirm.js. A fingerprint that outlived its arm
// would let a later confirm fire against a list the operator is no longer
// looking at, which is precisely what the fingerprint exists to prevent.
const _MC_IRQ_ID = "interrupt";
let _mcIrq = { fp: null, victims: [], host: null };

function _mcIrqForget() {
  _mcIrq.fp = null;
  _mcIrq.victims = [];
}

function _mcVictimLine(v) {
  const bits = [String(v.pid), v.name || "?"];
  if (v.lane) bits.push("lane " + v.lane);
  else if (v.kind === "controller") bits.push("loop controller");
  else if (v.kind === "child") bits.push("child of " + v.ppid);
  return bits.join("  -  ");
}

function _mcIrqPreview() {
  _mcMsg("INTERRUPT: probing what is running...");
  mcPost({ action: "interrupt_preview" })
    .then((d) => {
      if (!d || !d.ok) {
        _mcMsg("INTERRUPT preview failed: " + ((d && d.error) || "request failed"));
        return;
      }
      if (!d.count) {
        // Nothing to kill, so nothing to name - arming here would offer a
        // confirm whose victim list is empty, and the server refuses it anyway.
        _mcIrqForget();
        _mcMsg("INTERRUPT: nothing is running - nothing to interrupt");
        _mcPaint();
        return;
      }
      _mcIrq.fp = d.fingerprint;
      _mcIrq.victims = d.victims || [];
      _mcArm.arm(_MC_IRQ_ID);
      _mcMsg("INTERRUPT armed: " + d.count
        + " process(es) named below - click again within 3s to KILL them");
    })
    .catch((e) => _mcMsg("INTERRUPT preview: " + ((e && e.message) || "request failed")));
}

function _mcIrqFire(key, fp) {
  // `fp` is passed IN, never read from _mcIrq here. MEASURED live 2026-07-31:
  // _mcArm.confirm() disarms and notifies SYNCHRONOUSLY, that notify repaints,
  // and the repaint sees armed === false and calls _mcIrqForget() - so by the
  // time this function ran, the fingerprint it needed was already null and the
  // server answered 400 "requires 'fingerprint'". The tier failed safe (nothing
  // died) but could never kill anything. The caller reads the fingerprint
  // BEFORE confirm() and hands it over.
  _mcIrqForget();
  _mcMsg("INTERRUPT: killing...");
  mcPost({ action: "interrupt", fingerprint: fp,
           idempotency_key: key })
    .then((d) => {
      let txt;
      if (d && d.ok) {
        txt = "INTERRUPT: " + (d.detail || "done")
          + (d.replayed ? " (replayed)" : "");
      } else if (d && d.refused === "victims_changed") {
        // The honest failure: what the operator approved is no longer what is
        // running, so nothing was killed. Say that plainly and make them look
        // again rather than silently re-targeting.
        txt = "INTERRUPT REFUSED - the running processes changed since the "
          + "preview. Nothing was killed. Preview again to see the current "
          + (d.count || 0) + ".";
      } else if (d && d.refused) {
        txt = "INTERRUPT REFUSED - " + d.refused;
      } else {
        txt = "INTERRUPT failed: " + ((d && d.error) || "request failed");
      }
      // Fix round 1 (IMPORTANT 6). Measured: renderLoopStatus() bare
      // rebuilds #loop-ctl-msg empty, so "INTERRUPT REFUSED - the running
      // processes changed..." - the single most important message on the
      // kill path - never reached the screen. Thread it through.
      _mcMsg(txt);
      renderLoopStatus(txt);
    })
    .catch((e) => _mcMsg("INTERRUPT: " + ((e && e.message) || "request failed")));
}

function _mcPaintInterrupt() {
  const host = _mcIrq.host;
  if (!host || !host.isConnected) return false;
  const armed = _mcArm.isArmed(_MC_IRQ_ID);
  // The arm lapsing is what expires the fingerprint. Handled on the paint that
  // notices, so a countdown running out is indistinguishable from a Cancel.
  if (!armed && _mcIrq.fp) _mcIrqForget();
  const focused = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  let refocus = null;
  host.innerHTML = "";

  const b = document.createElement("button");
  b.type = "button";
  b.className = "loop-btn loop-irq-btn" + (armed ? " loop-btn-armed" : "");
  b.dataset.mcId = _MC_IRQ_ID;
  b.setAttribute("aria-pressed", armed ? "true" : "false");
  if (focused === _MC_IRQ_ID) refocus = b;
  if (armed) {
    b.textContent = "Confirm INTERRUPT - kill " + _mcIrq.victims.length
      + " (" + Math.ceil(_mcArm.remainingMs() / 1000) + "s)";
    b.title = "kills exactly the processes listed below, and nothing else";
  } else {
    b.textContent = "INTERRUPT - show what dies";
    b.title = "probes what is running and names it before anything is killed";
  }
  b.addEventListener("click", () => {
    if (_mcArm.isArmed(_MC_IRQ_ID)) {
      // Read the fingerprint FIRST: confirm() notifies synchronously, the
      // notify repaints, and the repaint clears it. See _mcIrqFire.
      const fp = _mcIrq.fp;
      const res = _mcArm.confirm(_MC_IRQ_ID);
      if (res.fired) _mcIrqFire(res.key, fp);
      return;
    }
    _mcIrqPreview();
  });
  host.append(b);

  if (armed && _mcIrq.victims.length) {
    // The named victims. This list IS the safety property - it must be on
    // screen before the confirm is reachable, not behind a disclosure.
    //
    // document.createElement, NOT the `mk` helper. `mk` is a function-LOCAL
    // const inside renderLoopStatus, so at module scope it is a ReferenceError
    // - and one thrown here is swallowed by the preview's .catch, which
    // reported it as "request failed". The armed button still rendered
    // "Confirm INTERRUPT - kill 3" with NO list beneath it, which is precisely
    // the blind kill this tier exists to prevent. Every other module-scope
    // paint function here already uses createElement for the same reason.
    const list = document.createElement("ul");
    list.className = "loop-irq-victims";
    list.setAttribute("aria-label", "processes this interrupt will kill");
    _mcIrq.victims.forEach((v) => {
      const li = document.createElement("li");
      li.className = "loop-irq-victim";
      li.textContent = _mcVictimLine(v);
      list.append(li);
    });
    host.append(list);
  }
  if (refocus) refocus.focus();
  return armed;
}

function _mcPaint() {
  // Lanes first, and its armed flag is folded into the timer decision below -
  // otherwise a lane armed on its own would have its countdown cancelled by
  // the shortcut row reporting nothing armed.
  const laneArmed = _mcPaintLanes();
  const irqArmed = _mcPaintInterrupt();
  const host = _mcHost;
  if (!host || !host.isConnected) { _mcSetTimer(!!laneArmed || !!irqArmed); return; }
  // The countdown repaints 4x/second while armed, and innerHTML="" destroys the
  // node the operator is standing on. Without this, tabbing to a shortcut and
  // pressing Enter armed it and threw focus to <body> - so the confirm click
  // could never be reached from the keyboard and the whole flow was mouse-only.
  const focusedId = (document.activeElement && host.contains(document.activeElement))
    ? document.activeElement.dataset.mcId : null;
  host.innerHTML = "";
  let anyArmed = false;
  let refocus = null;
  _MC_SHORTCUTS.forEach((sc) => {
    const armed = _mcArm.isArmed(sc.id);
    if (armed) anyArmed = true;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "loop-btn loop-shortcut" + (armed ? " loop-btn-armed" : "");
    b.setAttribute("aria-pressed", armed ? "true" : "false");
    b.dataset.mcId = sc.id;
    if (focusedId === sc.id) refocus = b;
    b.title = sc.hint;
    if (armed) {
      const left = Math.ceil(_mcArm.remainingMs() / 1000);
      b.textContent = "Confirm " + sc.label + " (" + left + "s)";
    } else {
      b.textContent = sc.label;
    }
    b.addEventListener("click", () => {
      if (_mcArm.isArmed(sc.id)) {
        const res = _mcArm.confirm(sc.id);
        if (res.fired) _mcFire(sc, res.key);
        return;
      }
      _mcArm.arm(sc.id);
      _mcMsg("armed: click again within 3s to " + sc.label.toLowerCase());
    });
    host.append(b);
  });
  // laneArmed and irqArmed too: the arm controller is global, so an armed LANE
  // or INTERRUPT - the heavier actions - would otherwise be the ones with no
  // visible abort.
  if (anyArmed || laneArmed || irqArmed) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "loop-btn loop-btn-cancel";
    cancel.dataset.mcId = "cancel";
    if (focusedId === "cancel") refocus = cancel;
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      _mcArm.disarm();
      _mcMsg("disarmed");
    });
    host.append(cancel);
  }
  if (refocus) refocus.focus();
  _mcSetTimer(anyArmed || !!laneArmed || !!irqArmed);
}

function renderLoopStatus(ctlMsg, preserve) {
  // Fix round 2: any call - timer, action-triggered, ceiling-forced, the
  // initial load - means a real refresh is imminent, so the staleness
  // clock resets here rather than in each individual caller.
  _mcDeferredTicks = 0;
  _mcSetStale(false);
  const host = document.getElementById("loop-status-body");
  if (!host) return;
  const mk = (tag, cls, txt) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };
  fetch("/api/loop-status", { cache: "no-store" })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => {
      if (!d || !d.ok) {
        host.innerHTML = '<div class="home-empty">loop status unavailable</div>';
        return;
      }
      host.innerHTML = "";
      const st = d.state || "idle";

      const stateRow = mk("div", "loop-state-row");
      stateRow.append(mk("span", "loop-dot " + st));
      stateRow.append(mk("b", null, st.toUpperCase()));
      if (d.cycle != null) {
        stateRow.append(mk("span", "dim",
          "cycle " + d.cycle + (d.max_cycles ? " / " + d.max_cycles : "")));
      }
      if (d.mode) stateRow.append(mk("span", "loop-mode", d.mode));
      host.append(stateRow);

      // Fix round 2 (VISIBLE STALENESS). Persistent across repaints only in
      // the sense that this exact id is recreated fresh (and therefore
      // blank) on every real rebuild; _mcSetStale mutates it directly,
      // without a rebuild, while a tick is being deferred. Reusing the
      // already-legible, already-contrast-checked .loop-line class rather
      // than inventing a new one - see the RC2 header.css block this card's
      // CSS is copied from.
      const staleNote = mk("div", "loop-line", "");
      staleNote.id = "loop-stale-note";
      staleNote.setAttribute("role", "status");
      staleNote.setAttribute("aria-live", "polite");
      host.append(staleNote);

      if (d.stop_reason) host.append(mk("div", "loop-line dim", "stop: " + d.stop_reason));

      // Lock states. Two separate locks with two separate lifetimes: the lane
      // mutex (control/lanes/0.lock) and the loop controller's own single-flight
      // lock (control/RUNNING.lock). Reported side by side, never merged.
      const locks = mk("div", "loop-locks");
      locks.append(_loopLockRow(mk, "LANE", d.lanes));
      locks.append(_loopLockRow(mk, "LOOP", d.controller_lock));
      host.append(locks);

      if (d.last_done) {
        const ld = d.last_done;
        const row = mk("div", "loop-line");
        row.append(mk("span", "dim",
          "last cycle " + (ld.cycle != null ? ld.cycle : "?") + ":"));
        row.append(mk("code", null, ld.sha || "?"));
        row.append(mk("span", null,
          "tests " + (ld.tests_pass != null ? ld.tests_pass : "?")));
        row.append(mk("span", ld.regressions ? "loop-bad" : "loop-ok",
          ld.regressions ? "REGRESS" : "clean"));
        host.append(row);
      }

      if (d.budget) {
        const b = d.budget;
        const num = (v) => (typeof v === "number" ? v : null);
        // No ceiling is rendered: since 2026-08-01 the loop is single-vendor and
        // nothing caps spend, so a "/ $200" would state a rail that does not
        // exist. Both figures are ESTIMATES and read as workload size.
        const a = num(b.adjudicator_usd), c = num(b.claude_usd_info);
        host.append(mk("div", "loop-line dim",
          "spend: adjudicator $" + (a != null ? a.toFixed(2) : "?") +
          "  -  executor(info) $" + (c != null ? c.toFixed(2) : "?")));
      }

      if (d.last_commit) {
        const lc = d.last_commit;
        const row = mk("div", "loop-line");
        row.append(mk("code", null, lc.sha || "?"));
        row.append(mk("span", "dim", lc.subject || ""));
        host.append(row);
      }

      if (Array.isArray(d.log_tail) && d.log_tail.length) {
        host.append(mk("pre", "loop-log", d.log_tail.join("\n")));
      }

      // -- Control row (CONTROL half): stop / resume + one-shot directive
      // override. Each writes ops/loop/control/* via POST /api/loop-control.
      // Fix round 2: `id` (5th arg, optional) sets dataset.mcId so a
      // ceiling-forced repaint can find and refocus THIS SPECIFIC button
      // after the rebuild - see _mcFindByMcId. Every btn() call site below
      // now passes one; before this, only the shortcut/lane/interrupt
      // buttons had a stable identity, so a click that left focus on
      // Send NOTE/Send STEER/Queue directive/Clear/Stop/Resume with
      // nothing else to restore it to.
      const btn = (label, cls, fn, id) => {
        const b = mk("button", "loop-btn " + (cls || ""), label);
        b.type = "button";
        if (id) b.dataset.mcId = id;
        b.addEventListener("click", fn);
        return b;
      };
      const ctl = mk("div", "loop-controls");
      if (st === "stopped") {
        ctl.append(btn("Resume", "loop-btn-resume", () => _loopControl("resume"), "resume"));
      } else {
        ctl.append(btn("Stop loop", "loop-btn-stop",
          () => _loopControl("stop", { reason: "stopped from dashboard" }), "stop"));
      }
      host.append(ctl);

      // Shortcuts 1 and 2 - queued intents, safe alongside a running lane.
      // Arm-then-confirm: a stray single click decays after 3s and fires nothing.
      host.append(mk("div", "loop-sub-head", "SHORTCUTS - ARM, THEN CONFIRM"));
      _mcHost = mk("div", "loop-shortcuts");
      host.append(_mcHost);

      // Lanes (S5). Mutually exclusive; a fire against a held lane is refused.
      _mcLanes = d.lanes_available || { all: [], wired: [] };
      // The count is in VISIBLE text on purpose. Five permanently-dim buttons
      // under a heading that only says "refused if held" read as "currently
      // held" - a transient explanation for a permanent state - and the real
      // reason lived only in a hover title, which a disabled button does not
      // reliably announce.
      const nWired = (_mcLanes.wired || []).length;
      const nAll = (_mcLanes.all || []).length || Object.keys(_LANE_LABELS).length;
      host.append(mk("div", "loop-sub-head",
        "LANES - ARM, THEN CONFIRM - ONE AT A TIME, REFUSED IF HELD - "
        + nWired + " of " + nAll + " wired"));
      _mcLaneHost = mk("div", "loop-shortcuts loop-lanes-row");
      host.append(_mcLaneHost);
      _mcPaint();

      // Steer channel (S7). NOTE and STEER only - INTERRUPT is S9 and is a
      // different act entirely. Single click on purpose: a steer is GUIDANCE,
      // it executes nothing and kills nothing, and the text has to be typed
      // first, which is itself the deliberate act. The arm-then-confirm window
      // is for things that cannot be taken back.
      const steerInfo = d.steer || null;
      host.append(mk("div", "loop-sub-head",
        "STEER - GUIDANCE, NEVER AN INTERRUPT"
        + (steerInfo && steerInfo.pending
           ? " - " + steerInfo.pending + " PENDING" : "")));
      const sta = mk("textarea", "loop-ta");
      sta.id = "loop-steer-input";
      sta.rows = 2;
      sta.placeholder = "note for the running session...";
      // A placeholder is NOT an accessible name - it disappears on the first
      // keystroke, so a screen reader loses the label exactly when the field
      // has content. The visible sub-head above is not programmatically
      // associated with the field, so name it explicitly.
      sta.setAttribute("aria-label", "steer text for the running session");
      host.append(sta);
      const steerRow = mk("div", "loop-dir-row loop-steer-row");
      const _sendSteer = (tier) => {
        const node = document.getElementById("loop-steer-input");
        const text = node && node.value ? node.value.trim() : "";
        if (!text) { _mcMsg("steer: type something first"); return; }
        mcPost({
          action: "steer", tier: tier, text: text,
          // One key per SEND, minted here - the same rule as the arm path.
          idempotency_key: _mcSteerKey(),
        })
          .then((dd) => {
            if (dd && dd.ok) {
              // Fix round 1 (IMPORTANT 6): thread the same text through the
              // rebuild instead of a bare renderLoopStatus() - the bare call
              // rebuilds #loop-ctl-msg empty and clobbers the _mcMsg write
              // above the instant the rebuild lands.
              const txt = tier.toUpperCase() + ": " + (dd.detail || "queued");
              _mcMsg(txt);
              if (node) node.value = "";
              renderLoopStatus(txt);
            } else {
              // Fix round 2: deliberately RETAINED, not cleared. An
              // operator who just typed a real note does not want to
              // retype it because one send attempt failed (transient
              // network blip, a momentary 401 before a re-prompt, etc.) -
              // clearing on failure punishes exactly the case where the
              // text is most valuable. This is safe specifically BECAUSE
              // the fix round 2 ceiling now exists: retaining used to mean
              // _mcSafeToRepaint blocked every future tick forever (this
              // was mainline path (a) in the ceiling defect report); now it
              // means at most _MC_DEFER_CEILING_TICKS * _MC_POLL_MS of
              // deferred refreshes before a forced repaint that preserves
              // the same text and refocuses the box. The .catch below
              // retains for the same reason and is not a separate choice.
              _mcMsg(tier.toUpperCase() + " failed: "
                + ((dd && dd.error) || "request failed"));
            }
          })
          .catch((e) => _mcMsg(tier.toUpperCase() + ": "
            + ((e && e.message) || "request failed")));
      };
      // No accent on either: see the .loop-steer-row comment in header.css.
      steerRow.append(btn("Send NOTE", "", () => _sendSteer("note"), "send_note"));
      steerRow.append(btn("Send STEER", "", () => _sendSteer("steer"), "send_steer"));
      host.append(steerRow);
      if (steerInfo && steerInfo.newest) {
        // No `dim` class - web/css has no bare `.dim` rule, and .loop-line
        // already carries --text-dim. Same inert-class trap as S4.
        host.append(mk("div", "loop-line",
          "newest pending: " + steerInfo.newest));
      }

      // INTERRUPT (S9). Its own sub-head, below STEER, because it is a
      // different ACT and not a louder tier of the same one - the two share a
      // heading only in the plan's prose, never on screen.
      host.append(mk("div", "loop-sub-head",
        "INTERRUPT - STOPS THE TURN AND KILLS AGENTS"));
      host.append(mk("div", "loop-line",
        "names every process first - the confirm can only kill what the "
        + "preview listed"));
      _mcIrq.host = mk("div", "loop-shortcuts loop-irq-row");
      host.append(_mcIrq.host);
      // Paint again now that the interrupt host exists. The earlier call sits
      // above this block and painted into a host that was still null, so
      // without this the button is missing until the next 5s poll - the same
      // class of bug as the S4 card that rendered into markup that did not
      // exist.
      _mcPaint();

      // Its own sub-head. Before S7 this was the trailing block and read as a
      // group; once the steer row landed above it, it became the only unheaded
      // group in the card and both textareas read as one STEER control.
      host.append(mk("div", "loop-sub-head",
        "DIRECTIVE OVERRIDE - ONE SHOT, NEXT CYCLE"));
      const ta = mk("textarea", "loop-ta");
      ta.id = "loop-directive-input";
      ta.rows = 3;
      ta.placeholder = "one-shot directive override for the next cycle...";
      ta.setAttribute("aria-label",
        "one-shot directive override for the next loop cycle");
      host.append(ta);

      const dirRow = mk("div", "loop-dir-row");
      dirRow.append(btn("Queue directive", "loop-btn-dir", () => {
        const node = document.getElementById("loop-directive-input");
        const t = node && node.value ? node.value : "";
        if (t.trim()) _loopControl("set_directive", { text: t });
      }, "queue_directive"));
      dirRow.append(btn("Clear", "loop-btn-clear", () => _loopControl("clear_directive"), "clear_directive"));
      host.append(dirRow);

      const msg = mk("div", "loop-ctl-msg");
      msg.id = "loop-ctl-msg";
      // The arm transition is announced here; without a live region a screen
      // reader never hears that a 3s confirm window just opened.
      msg.setAttribute("role", "status");
      msg.setAttribute("aria-live", "polite");
      if (ctlMsg) msg.textContent = ctlMsg;
      host.append(msg);

      // Fix round 2 (property 2: the ceiling must not reintroduce round 1's
      // findings 3+4). Applied LAST, after every element above exists, so
      // there is always something live to restore onto. sta/ta are the
      // FRESH textareas just created above - a forced repaint always makes
      // new ones, so restoring their value/selection here is what makes the
      // operator's in-progress edit survive it. focusKey identifies which
      // control had focus before the wipe: "steer"/"directive" for the two
      // textareas (stable ids), or a dataset.mcId for any button (every
      // btn() call site above now passes one, and the shortcut/lane/
      // interrupt buttons always have - see _mcFindByMcId).
      if (preserve) {
        if (preserve.steerValue) {
          sta.value = preserve.steerValue;
          if (preserve.steerSel && typeof sta.setSelectionRange === "function") {
            sta.setSelectionRange(preserve.steerSel.start, preserve.steerSel.end);
          }
        }
        if (preserve.directiveValue) {
          ta.value = preserve.directiveValue;
          if (preserve.directiveSel && typeof ta.setSelectionRange === "function") {
            ta.setSelectionRange(preserve.directiveSel.start, preserve.directiveSel.end);
          }
        }
        const target = preserve.focusKey === "steer" ? sta
          : preserve.focusKey === "directive" ? ta
          : _mcFindByMcId(host, preserve.focusKey);
        if (target) target.focus();
      }
    })
    .catch(() => {
      host.innerHTML = '<div class="home-empty">loop status error</div>';
    });
}

// Fix round 1 (2026-07-31, IMPORTANT 3 + 4). Measured: the 5s poll called
// renderLoopStatus() unconditionally, which does host.innerHTML = "" and
// rebuilds both textareas from scratch - a typed-but-unsent steer note or
// directive became "" after one tick, and the same wipe orphans keyboard
// focus (host.contains(activeElement) is already false by the time
// renderLoopStatus's own focus-preservation logic could run, because the
// host it would check was already replaced). With a 3s arm window against a
// 5s poll, a tick usually lands mid-arm, which made the confirm button
// keyboard-unreachable - the exact mouse-only defect a comment elsewhere in
// this file says was already fixed once.
//
// Scoped to ONLY the recurring timer call, not the initial load and not any
// action-triggered call (Stop/Resume, a lane firing, INTERRUPT, a steer
// send) - those must always repaint so their result is visible immediately
// (see the IMPORTANT 6 fixes above), and none of them run every 5s
// regardless of what the operator is doing, so they carry none of the
// runaway-timer risk this guard exists for.
function _mcSafeToRepaint() {
  const host = document.getElementById("loop-status-body");
  if (!host) return true;
  const steer = document.getElementById("loop-steer-input");
  if (steer && steer.value) return false;
  const directive = document.getElementById("loop-directive-input");
  if (directive && directive.value) return false;
  if (document.activeElement && host.contains(document.activeElement)) return false;
  return true;
}

// Fix round 2 (2026-07-31, the ceiling). Measured: the round-1 guard above
// has no upper bound, so two MAINLINE paths freeze the card forever -
// (a) a FAILED steer send (see the comment on _sendSteer's failure branch:
// the text is deliberately retained, not cleared, so a failure alone blocks
// every future tick), and (b) clicking Send NOTE / Send STEER / Queue
// directive with an EMPTY box, which does nothing but leaves focus inside
// #loop-status-body. Either way the LANE/LOOP lock rows, the RUNNING/
// STOPPED dot, budget and log tail silently stop refreshing - the "armed
// button beside stale data" defect shape, one level up from S9's.
//
// _mcCapturePreserve/_mcFindByMcId exist so a ceiling-forced repaint can
// restore exactly what it is about to destroy, which is what makes forcing
// it SAFE rather than just moving round 1's bug to a 30s timescale instead
// of a 5s one.
const _MC_POLL_MS = 5000;
const _MC_DEFER_CEILING_TICKS = 6; // 6 * 5s = 30s, per the coordinator's figure
let _mcDeferredTicks = 0;

function _mcSetStale(on) {
  const node = document.getElementById("loop-stale-note");
  if (node) {
    node.textContent = on
      ? "updates paused while editing - will refresh within "
        + (_MC_DEFER_CEILING_TICKS * _MC_POLL_MS / 1000) + "s"
      : "";
  }
}

// Depth-first search for the first descendant (or root) whose dataset.mcId
// equals `key`. Generalises the refocus-by-dataset-mcId pattern already
// used inside _mcPaintLanes/_mcPaintInterrupt/_mcPaint (each of which only
// searches its OWN sub-host) to the whole card, which is what a repaint
// forced from OUTSIDE all three of those needs.
function _mcFindByMcId(root, key) {
  if (!root || !key) return null;
  if (root.dataset && root.dataset.mcId === key) return root;
  const kids = root.children || [];
  for (let i = 0; i < kids.length; i += 1) {
    const found = _mcFindByMcId(kids[i], key);
    if (found) return found;
  }
  return null;
}

// Snapshot of everything a ceiling-forced repaint would otherwise destroy:
// both textarea values (+ selection, where the element supports it - real
// textareas always do), and which control had keyboard focus, identified by
// a key stable across a rebuild (the two textareas have fixed ids; every
// other focusable control in this card carries dataset.mcId - see the btn()
// helper inside renderLoopStatus).
function _mcCapturePreserve() {
  const host = document.getElementById("loop-status-body");
  const steer = document.getElementById("loop-steer-input");
  const directive = document.getElementById("loop-directive-input");
  const active = document.activeElement;
  let focusKey = null;
  if (active && host && host.contains(active)) {
    if (active === steer) focusKey = "steer";
    else if (active === directive) focusKey = "directive";
    else if (active.dataset && active.dataset.mcId) focusKey = active.dataset.mcId;
  }
  const sel = (el) => (el && typeof el.selectionStart === "number"
    ? { start: el.selectionStart, end: el.selectionEnd } : null);
  return {
    steerValue: steer ? steer.value : "",
    steerSel: sel(steer),
    directiveValue: directive ? directive.value : "",
    directiveSel: sel(directive),
    focusKey: focusKey,
  };
}

// No view router in this page - it IS the view. Render on load, then poll.
renderLoopStatus();
setInterval(() => {
  if (_mcSafeToRepaint()) {
    renderLoopStatus();
    return;
  }
  _mcDeferredTicks += 1;
  if (_mcDeferredTicks >= _MC_DEFER_CEILING_TICKS) {
    // The ceiling. Capture what the operator is doing FIRST - the capture
    // must run before renderLoopStatus touches any DOM - then force the
    // repaint anyway and hand the snapshot through to be restored onto the
    // freshly rebuilt nodes. renderLoopStatus itself resets
    // _mcDeferredTicks to 0 as its first line, so this does not need to.
    renderLoopStatus(null, _mcCapturePreserve());
    return;
  }
  _mcSetStale(true);
}, _MC_POLL_MS);
