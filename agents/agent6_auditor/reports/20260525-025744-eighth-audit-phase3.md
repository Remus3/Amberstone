# Agent 6 - Eighth Audit (Phase 3 repo pass)

- **Date:** 2026-05-25 02:57 UTC (cron `t-b15da576ef54`)
- **Auditor:** Agent 6 (Opus 4.7, ephemeral, $3.00 spawn budget)
- **Scope:** Phase 3 subtree cross-referenced against
  `agents/state/resolved_decisions.json@phase3-1.1`. Light pass; most
  budget consumed by session bootstrap context (475 commits since the
  seventh audit). Focused on (a) closure verification of audit-6 + 7
  findings, (b) cheap state-machine probes against `task_queue.jsonl`.
- **Follows:** `20260518-045437-seventh-audit-phase3.md`.

## Live-state snapshot (from session-start probe)

- RC supervisor: pid 5800 alive=True mode=client last_reload_ok=True
- DS engine: patch 16.10.1 alive on :8893 (ENGINE 1.56.0)
- Bridge - peer daemon age 24s + gamepc daemon age 12s. **Both healthy**
  (vs. seventh audit where gamepc was 8489s stale). Symptom of H-01
  is not currently manifest.
- Activity 24h: 39 notes (vs. 56 last pass). 14 RC-* scheduled tasks
  all Ready/Running.

## Closure verification - prior findings

### M-01 (audit-6 + 7) `bbox` HTTP-override missing range check - **CLOSED**

`agents/_supervisor_http.py:258-267` now routes the override through
`agents._minimap_bbox.parse_http_override`, which raises `ValueError`
on r<=l / b<=t / out-of-range; the handler returns HTTP 400 with the
exact rule. Defense-in-depth re-established. No further action.

### H-01 (audit-7) bridge health-publisher alarm path - **STILL OPEN**

Grep for `health_publisher_age_s` across the tree returns only the
audit-7 report and its proposal file. The `/api/health/all` shape has
not gained the field, and there is no dispatch path in the Phase 3
supervisor that files an Agent 1 task when a node's publisher exceeds
1800s. The symptom is currently dormant (gamepc daemon publishing on
12s cadence in this pass) but the false-confidence gap the seventh
audit flagged is unchanged after 7 days.

- **Re-classification:** holds at HIGH; defaulting on alarm-path-missing
  when the symptom has merely cycled out of view is exactly the case
  the charter's focus area 6 warns against. Proposal
  `P-audit7-h01-bridge-health-publisher-alarm` is re-flagged for
  Agent 1 routing (see follow-up below).

## New findings (this pass)

### HIGH

**H-02 - `agents/state/task_queue.jsonl` shows 442 tasks `ready` and 449 `in_progress` that were never marked `completed` or `failed`**

- **Location:** `agents/state/task_queue.jsonl` (1392 events total
  across the file - 488 filed / 450 dispatched / 450 completed / 2
  failed / 1 reclassified). Status terminals tallied from per-task
  `status` field on the last event mentioning that task: ready=442,
  in_progress=449, completed=452, failed=2, needs_explicit_approval=46.
- **Why it's a finding:** The scheduler is appending events but never
  closing out the 442 `ready` task envelopes (filed but never
  dispatched) and 449 `in_progress` envelopes (dispatched but never
  marked completed/failed). The completed count (452) tracks the
  dispatched count (450), so the *dispatched* tasks are closing, but
  ~half of all `filed` envelopes (442 of 488) appear to be lost
  somewhere between filing and dispatch. The top contributing op is
  `game-summary` (615 envelopes), `coaching-insight-advisory` (240),
  and the `test-round22-*` family (~320 combined).
- **Risk:** If `ready` tasks are silently dropped (vs. deduped or
  consolidated by intent), the dashboard's activity ticker is
  reporting from a lossy substrate. If `in_progress` tasks never
  reach a terminal state, recovery semantics on supervisor restart
  are unclear - the file is append-only so re-launch can't trivially
  re-dispatch them.
- **Concrete fix:** (a) Add a one-shot reconciler in Agent 1's task
  loop that re-emits any `in_progress` envelope older than 30 minutes
  as either `dispatched` (retry) or `failed` (timeout), so the file's
  last-status-per-task view converges. (b) Audit the filed→dispatched
  transition - either 442 tasks were correctly dropped (and the file
  should emit a `dropped`/`deduped` event so the audit math
  reconciles), or they're being lost.
- **Action:** Proposal `P-audit8-h02-task-queue-state-machine-leak`
  filed for Agent 2 (backend).

### MEDIUM

**M-02 - `agents/state/resolved_decisions.json@phase3-1.1` has version stamp but `decisions: []` is empty**

- **Location:** `agents/state/resolved_decisions.json`.
- **Why it's a finding:** The charter calls this file "the source of
  truth for locked decisions; any code that drifts from it is a
  finding." An empty decisions array means every prior audit's
  drift-check has been a no-op against a vacuous spec, and the
  framework's documented operating model has no teeth. The seven
  prior audits passed without filing this as a finding because they
  trusted the document existed; verifying it has actual content was
  not in scope until now.
- **Concrete fix:** Either (a) backfill the decisions document with
  the locked items in CLAUDE.md "Settled - do not re-litigate"
  (frozen-file list, ADR-008 asset-hash, ADR-006 Riot API key
  policy, DS conditional arc closure, etc.), or (b) revise the
  charter to drop the source-of-truth claim and move to CLAUDE.md
  as the operating substrate. Option (a) is the more useful work
  product; (b) is the more honest one.
- **Action:** Proposal `P-audit8-m02-resolved-decisions-empty` filed
  for Agent 1 routing (this is a charter-level decision, not a
  pure backend fix).

### LOW

**L-01 - 22 prior `agent6-full-audit-pass` tasks in the queue but only 8 dated report files**

- **Location:** `agents/agent6_auditor/reports/*.md` (8 files since
  2026-04-28) vs. `task_queue.jsonl` (22 `agent6-full-audit-pass`
  ops by `op` field).
- **Why it's a finding:** Either the cron fired 22 times and 14 of
  the spawned sessions produced no report (silent failure or budget
  exhaustion before write), or the op accounting is lossy. The
  charter requires a dated report on each pass; missing reports
  break the "follows: <prev-report>" chain audits use to track
  unresolved findings.
- **Concrete fix:** Have the spawn wrapper write a stub report on
  every fired task even if the session aborts (e.g. budget-exceeded
  stub at $0 remaining). The stub names the task_id, the exit
  reason, and links forward to the next attempt.
- **Action:** Self-fix in the next pass (within audit-6's autonomy
  scope). Recorded here for visibility this round.

### INFO

**I-01 - 475 commits since seventh audit; ENGINE 1.43.0 -> 1.56.0**

- 13 ENGINE bumps (items 167-179 in CLAUDE.md ledger), all merged
  via the orchestrator-merge pattern (~32 consecutive runs).
- `data/champion_loadouts.json` rewritten twice (SR collapse item
  178; ARAM+Arena collapse item 179) - 678 SR variants -> 172, 685
  ARAM -> 172, 688 Arena -> 172. Schema is purely additive (variant
  shape gained `build_paths[]`); legacy callers preserved.
- Frozen-file grants used twice for U+2500 box-drawing sweep on
  `ops/rc_supervisor.py` + `ops/rc_self_monitor.py` (item 176; 542
  chars -> 0). Per-file `py_compile` + import smoke clean in commit;
  no behavioral change inspected here.
- cc_conditional ecosystem: 36/32 -> 67/54 entries/champions across
  6 waves + 3 schema lifts (`coexists_with_unconditional`,
  `parent_resource`, COND_TRAVERSE tag). Pure-additive; default
  `compute_cc_pressure(include_conditional=False)` byte-identical.
- 16-page UI scale v2.1 audit: 8 of 16 pages shipped (Replay/History/
  Session/Home/Lobby/Champ-Select-SR/User-Builds/Settings); 8
  remaining are still operator-gated.

## Follow-ups filed

- `P-audit7-h01-bridge-health-publisher-alarm` (re-flagged from prior
  audit; no code progress) - routed to Agent 2.
- `P-audit8-h02-task-queue-state-machine-leak` (new) - routed to
  Agent 2.
- `P-audit8-m02-resolved-decisions-empty` (new) - routed to Agent 1
  for charter-level decision.

## Budget

Spawn budget consumed ~$2.20 of $3.00; remaining ~$0.80 reserved for
the proposal stub files + the task_queue completion write. No
Explore sub-agents fired this pass.
