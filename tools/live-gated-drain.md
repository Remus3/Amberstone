---
description: Drain session for docs/LIVE_GAME_GATED_SYNC.md - close open live-gated items while the operator plays (practice SR / ARAM Mayhem / Arena only if flagged), orchestrated multi-agent by default or a single Opus 4.8 max-effort agent when few items remain; if the Max-20x Fable session limit is reached, default the whole run to latest Opus (claude-opus-4-8) max effort + ultracode orchestration. Then resync the doc, clean worktrees/branches, run /done, and print the next-session continuation prompt. Use when the operator says "drain gated items", "live gated drain", or is about to play validation games.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

The operator wants a repeatable DRAIN session: work `docs/LIVE_GAME_GATED_SYNC.md`
top to bottom, close every item that can be closed this sitting, keep the doc
honest, and hand the next session a ready prompt. Operator prefs baked in:
SR items in PRACTICE TOOL where bots/dummies suffice; ARAM items in ARAM MAYHEM
(queue 2400 KIWI = MODE_ARAM); Arena (1750) ONLY if the doc's "ARENA NEEDED"
line says YES - call it out before the operator queues.

**Args:**
- _(none)_ -> full drain: plan -> execute -> resync -> cleanup -> /done + next prompt.
- `--status` -> report open counts + drain plan only, zero writes.
- `--resync-only` -> skip execution; run the resync workflow + wrap.

### 1. Bootstrap (read + probe, cite lines before acting)

- Read `docs/LIVE_GAME_GATED_SYNC.md`: the "Drain plan" section, the env-tagged
  open rows ((PRACTICE-SR)/(REAL-SR)/(ARAM-MAYHEM)/(ARENA)/(ANY-LOBBY)/(POST-GAME)/
  (PHYSICAL)/(ACCRUAL)), the "ARENA NEEDED" line, "ESTIMATED SESSIONS" line.
- Read `WAKEUP_NOTES.md` (last session) + `git log --oneline -15`.
- Probe live: `ops/runtime/health.json`, `curl -k https://127.0.0.1:8888/api/state`,
  DS `curl http://127.0.0.1:8860/health`. Confirm git tree state; flag dirt.
- Memory `feedback_preflight_cron_loop` applies: cite doc lines before executing.

### 2. One framed question to the operator

Ask ONCE (memory `feedback_scope_decision_cadence`): which games will you run
this sitting - practice SR / real SR / ARAM Mayhem / Arena / none (headless-only
items)? Recommended default = whatever the doc's drain plan session 1 says.
Everything after this runs autonomously.

### 3. Scale decision (orchestrated vs solo Opus max)

**Model policy (check FIRST, at bootstrap):** default engine for this command is
Fable 5 at max effort. If the plan-usage Max-20x FABLE SESSION LIMIT has been
reached - detect via: (a) the harness/session-start limit notice, (b) the
`anthropic-usage` MCP `query_usage` tool if connected, (c) the session model id
resolving to something other than `claude-fable-5`, or (d) the operator saying
so - then DEFAULT TO THE LATEST OPUS (`claude-opus-4-8`) at max effort WITH
ultracode-style orchestration (Workflow tool on every substantive step; token
cost not a constraint). Pass `model: "opus"` explicitly on Agent / workflow
`agent()` calls in that case so subagents do not try to inherit an unavailable
Fable parent. State which engine was picked and why in the first status line.

Count open ONE-SHOT items matching the operator's chosen games plus any
headless-executable prep (consumer wiring, flip PRs, harness runs):
- **>= 4 items or items spanning disjoint subsystems** -> ORCHESTRATED: use the
  Workflow tool - specialized agents per section/item (reader -> builder ->
  verifier). Worktree isolation ONLY for agents that mutate files in parallel.
- **< 4 items, one subsystem** -> SOLO-MAX: a single Agent (model `opus`, effort
  max) executes the batch inline; main thread merges + verifies.
- Either path: read-only `verifier` subagent gate before any merge or done-claim
  (CLAUDE.md Verification Discipline).

### 4. Execute the drain (per item type)

- **Live eyeball rows:** while the operator plays, probe `/api/state`, the relay
  (`:8889/latest-liveclient`), and `:8889/latest-frame` for pixel checks. Tick a
  row ONLY with recorded evidence (value seen, timestamp, screenshot path).
- **Seam flips validated live:** a default-ON flip = flag-default change ->
  Tier-2: full dual suite (DS dir + tests/) + DS `:8860` restart
  staged in the SAME commit (memory `feedback_ds_bump_run_tests_dir`).
  RC-side env flips route via Machine
  env + RC-Supervisor task restart (memory `reference_scheduled_task_env_injection`).
  NEVER flip blind (charter 4b) - flip only rows the doc marks LIVE-VALIDATED /
  FLIP-READY or that this session's eyeball just validated.
- **LCU / champ-select rows:** practice tool lobby suffices (lock-in, rune/spell/
  item push). Remember: League restart mid-session is the RuneWriter regression
  test case.
- **POST-GAME rows:** need a REAL match end - practice tool games never land in
  Match-V5. Pair them with the real SR / ARAM Mayhem game.
- **ACCRUAL rows:** do not attempt to close; log the games played into the count
  and re-run their rails (`tools/hz_shadow_report.py`,
  `tools/replay_build_order_validate.py --limit 0`) at wrap.
- **PHYSICAL rows** (e.g. Alt+Shift+A over League): instruct the operator at the
  right moment, capture the result, tick with evidence. Do NOT re-attempt
  headless synthesis (memory `reference_overlay_active_knob_physical_only`).

### 5. Resync the doc

Run the saved workflow: `Workflow({name: "live-gated-resync", args: {today: "<YYYY-MM-DD>"}})`.
It fans out readers over WAKEUP/ORCHESTRATION_PLAN/LEDGER/ROADMAP/BACKLOG/README/
OVERLAY_BUILD_MASTER_PLAN/ARCHITECTURE/OPERATIONS/RC_WORK_TRACKER
plus a repo-wide grep sweep and a seam-flag ground-truth audit, adversarially
verifies done-claims, then rewrites `docs/LIVE_GAME_GATED_SYNC.md` (removes
closed rows, adds new gated rows, rebuilds the drain plan + session estimate +
ARENA NEEDED line) behind a verifier gate. Script: `.claude/workflows/live-gated-resync.js`.

### 6. Cleanup (worktrees / branches)

- `git worktree list` + `git branch --list` - merge any surviving agent branches
  (verifier gate first), then `git worktree remove` each agent worktree and
  delete merged branches. `git worktree prune` last.
- NEVER delete an unmerged branch/worktree silently - flag it in the wrap report.

### 7. Wrap: /done + next-session prompt

- Invoke the `/done` skill (tests relevant to what changed, commit with a
  descriptive message, push, LEDGER append, WAKEUP_NOTES update, CI green).
- THEN print a **NEXT SESSION PROMPT** block the operator can paste verbatim,
  filled from the freshly resynced doc, e.g.:

```
/live-gated-drain - continue the drain of docs/LIVE_GAME_GATED_SYNC.md.
Open one-shot items: N (a PRACTICE-SR, b REAL-SR, c ARAM-MAYHEM, d ARENA).
ARENA NEEDED: YES/NO. Accrual tail: <one line>.
Suggested games this sitting: <session 1 line from the drain plan>.
```

- Close with the ready-for-/clear banner. If zero open one-shot items remain,
  say the drain is COMPLETE and the next prompt is accrual-rail-only.

### DEFER (do NOT do in this pass)

- Full `/sync-all-md` reconcile (separate pass; the resync workflow only touches
  the sync doc and emits proposals for other docs).
- Archive moves of the doc-hygiene candidates (operator-gated; proposals live in
  the sync doc appendix).
- DS coverage % prose recompute (DS-batch job only).
