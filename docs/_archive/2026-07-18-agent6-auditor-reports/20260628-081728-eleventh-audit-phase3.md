# Agent 6 - Eleventh Audit (Phase 3 repo pass)

- **Date:** 2026-06-28 08:17 UTC (cron `t-fbcd49d7b4f0`)
- **Auditor:** Agent 6 (Opus 4.7, ephemeral, $3.00 spawn budget)
- **Scope:** Closure verification of audit-10 findings + recency pass on
  activity between 2026-06-21 and 2026-06-28 (~70 commits, including
  bridge decommission ADR-012 + overlay redesign series).
- **Follows:** `20260621-100200-tenth-audit-phase3.md`.

## Live-state snapshot

- RC supervisor: pid 9156 / RC pid 9144 alive=True last_reload_ok=true
  mode=game aram_mode=true has_game=true (operator IN ARAM).
- Vision: alive api_key_ok uptime 58s (recent restart).
- Daemon Slayer: ENGINE 1.154.0 (was 1.149.0), patch 16.13.1, 173
  champs (was 172) / 706 items.
- Bridge: REMOVED. `dashboard/routes_health_peer.py` deleted;
  `ops/runtime/peer_health/` folder gone. ADR-012 commit 49b1c9ea.
- agent6 health block live in `/api/health/all`: `last_outcomes` len=3,
  status=green. FAIL FAIL COMPLETED sequence -> not 2-in-a-row, green
  correct.
- `agents/state/task_queue.jsonl`: 5447 events (was 5386).
- `agents/state/resolved_decisions.json`: STILL 20 decisions, STILL
  version phase3-1.1, STILL locked_at 2026-04-22. **67 days stale.**

## Closure verification - audit-10 findings

### C-01 cron silent-fail -> stub mechanism - **CLOSED**

Implementation report `20260621-120000-c01-cron-silent-fail-implemented.md`
verified live:
- `/api/health/all.agent6.last_outcomes` returns 3 entries with task_id,
  event, ts, status, last_error. Schema matches the proposal.
- `agent6.status` field present (`green` this pass since the most recent
  outcome was `completed` for t-d213fa672bac).
- `_agent6_audit_outcomes()` in `dashboard/routes_state.py` walks
  `task_queue.jsonl` for the last 3 final events; agent6_degraded
  participates in the top-level yellow rollup.
- `_write_agent6_failure_stub()` added to
  `agents/_supervisor_ephemeral.py`. Failure stubs will be written on
  every future non-zero claude exit for agent 6.

Past failures (t-b0af80b08abc, t-0e64d21ea495, t-9061a61f1ef1) not
backfilled - per-task logs pruned by 7-day cap. Acceptable per the
proposal's note.

### H-04 publisher-vs-watcher freshness - **CLOSED + MOOT**

`fix(health): peer rollup uses max(publisher_age, heartbeat_age)`
commit c76cc2fe landed 2026-06-21. Subsequently the entire
`dashboard/routes_health_peer.py` module and the `ops/runtime/peer_health/`
folder were removed when the RC<->Peer cross-Claude bridge was
decommissioned (ADR-012, commit 49b1c9ea, 2026-06-24). The H-04 seam is
now moot - there is no peer freshness logic to drift.

### M-04 resolved_decisions.json drift - **STILL OPEN, RE-ESCALATED**

The proposal in
`agents/agent6_auditor/proposals/20260621-100200-m04-decisions-drift/`
filed phase3-d021 (ADR-011 1-PC), phase3-d022 (101.qq.com live-wire),
phase3-d023 (DS live truth) but Agent 1 has not applied. The drift has
grown - see M-04-bis below.

### L-02 orphan `gamepc.json` - **AUTO-RESOLVED**

Resolved by the ADR-012 bridge decommission - the entire
`ops/runtime/peer_health/` directory was removed, gamepc.json along
with it. No autonomous cleanup needed.

## New findings (this pass)

### MEDIUM

**M-04-bis - resolved_decisions.json drift now spans 4 ADRs + 1 doctrine**

- **Location:** `agents/state/resolved_decisions.json`
  (locked_at=2026-04-22, version=phase3-1.1, 20 decisions).
- **What:** Beyond the audit-10 missing 3 entries (d021 ADR-011 1-PC,
  d022 101.qq.com live, d023 DS live truth), TWO MORE missing decisions
  have accreted in the past 7 days:
  - **ADR-012 RC<->Peer cross-Claude bridge decommissioned** (2026-06-24,
    commit 49b1c9ea). `dashboard/routes_health_peer.py` deleted, the
    peer_health folder deleted, `core.bridge.send()` and all
    `bridge_watcher_*.py` tools severed. Charter line "no cross-machine
    authority - never write to `\\192.168.8.237\RCClient\*`" still
    holds, but the rationale shifted from "Game-PC peer is read-only" to
    "Game-PC peer no longer exists". A new resolved_decisions entry
    (phase3-d024) should record the bridge teardown.
  - **Overlay all-panels doctrine** (ledger items 644-648, commits
    b16bfce1 ... 9bb382dd, 2026-06-26 .. 2026-06-27). Each rc-shell
    panel is now individually accessible with per-panel opacity/scale;
    the panel-set abstraction is retired. Three panels are interactive
    while playing via passive click-through zones; enemy-spell
    tap-tracker + API stats mini-panel landed. This is a major UX
    contract that future audits and future Agent 5 work will be
    evaluated against; should be a resolved_decisions entry (phase3-d025
    "Overlay all-panels doctrine + click-through interactivity").
- **Why it's wrong:** Charter L18 - "`agents/state/resolved_decisions.json`
  is the source of truth for locked decisions; any code that drifts
  from it is a finding". 67 days of operator-locked decisions are
  invisible to this contract. M-04 has now been open across audits 10
  and 11 with the drift growing each pass.
- **Concrete fix:** Apply the existing M-04 proposal AND extend it with
  phase3-d024 (ADR-012) + phase3-d025 (overlay all-panels). Bump
  `version` to `phase3-1.2`, `locked_at` to `2026-06-28`. Also bump
  `EXPECTED_DECISIONS_VERSION` in `agents/_supervisor_common.py` from
  `phase3-1.1` to `phase3-1.2`.
- **Disposition:** Re-escalation note appended to existing M-04
  proposal; Agent 1 follow-up task filed.

**M-05 - smb_push.py + gatekeeper UNC guard target a retired host**

- **Location:** `agents/agent2_backend/smb_push.py`
  (`SHARE_UNC = r"\\192.168.8.237\RCClient"`, line 41) +
  `agents/agent0_gatekeeper/evaluator.py` (`P-audit-h1` guard) +
  charter refs in `agents/agent2_backend/charter.md`,
  `agents/agent3_testing/charter.md`, `agents/agent5_ui/charter.md`,
  `agents/agent6_auditor/charter.md`.
- **What:** Game-PC retired from the live pipeline 2026-05-29 (ADR-011)
  AND the RC<->Peer cross-Claude bridge was decommissioned 2026-06-24
  (ADR-012). `\\192.168.8.237\RCClient\*` is a dead share - the
  receiving end is no longer in the topology. Yet:
  - `agents/agent2_backend/smb_push.py` is still loaded as a module and
    has live test coverage in
    `agents/agent3_testing/suite/test_quality_pass.py` and elsewhere.
  - The Agent 0 gatekeeper `P-audit-h1` guard ("defends the share even
    when callers bypass smb_push") still gates evaluations against a
    UNC that no live agent should push to.
  - Multiple agent charters still document `smb_push.push(...)` as the
    cross-machine push API.
- **Why it's wrong:** Dead-code surface attracts confused re-use by
  future ephemeral agents that read the charters at boot. The Brawl-mode
  precedent (s214: retired-from-champ-select, backend kept as deadcode
  for a SEPARATE cleanup pass) is the operator-blessed pattern, so this
  is a propose-and-document finding, not an autonomous-delete.
- **Concrete fix:** Either
  1. Mark `smb_push.py` deprecated in a module docstring, retire
     `share_reachable()` calls from agent flows, and document under a
     new resolved_decisions entry "Game-PC SMB push deadcode pending
     cleanup pass" (mirror of d019 Brawl retirement). OR
  2. Delete `smb_push.py`, the `P-audit-h1` guard call sites, and the
     `_smb_push` charter lines in agent2/3/5/6 in one slice.
- **Disposition:** Operator-decision proposal filed for Agent 1.
  `agents/agent6_auditor/proposals/20260628-081728-m05-smb-push-deadcode/`.

### LOW

**L-03 - `ops/audit/p0_inventory_full.csv` carries stale paths**

- **Location:** `ops/audit/p0_inventory_full.csv` rows 16915
  (`dashboard\routes_health_peer.py`) + 20605/20608
  (`ops\runtime\peer_health\gamepc.json` + `peer.json`).
- **What:** A frozen post-deletion inventory snapshot from before the
  bridge decom. Not loaded at runtime; not exercised by any live agent.
  Could re-confuse a future audit that grep-discovers a "missing" file.
- **Concrete fix:** Regenerate `p0_inventory_full.csv` after a quiescent
  point or add a header line `# inventory frozen at <date>, regenerate
  after structural deletions`.
- **Disposition:** Autonomous-edit deferred (this CSV is generated by an
  ops/audit pipeline, not a safeguards file; out of Agent 6 autonomous
  scope). Logged for an Agent 1 housekeeping pass.

### INFO

**I-05 - rc-shell signal-file watchers: 2x setInterval@200ms blocking reads**

- **Location:** `rc-shell/src/main.js:1076` (`startActiveToggleWatch`)
  + `rc-shell/src/main.js:1107` (`startPanelCycleWatch`).
- **What:** Two `setInterval(... , 200)` blocking `readFileSync` polls
  on Electron's main thread. Chosen because `fs.watch` is unreliable
  across Windows atomic tmp+replace (documented inline at L1059).
  Atomic-write semantics (d006) make the read race-safe; ENOENT during
  rename is caught.
- **Why noteworthy:** Acceptable but worth a perf eye if Electron main-
  thread budget tightens. A debounced watcher backed by `chokidar`'s
  polling adapter would offload from the main-thread tick.
- **Disposition:** No action this pass. Logged.

**I-06 - source_quality.json still dormant**

- **Location:** `agents/agent6_auditor/source_quality.json`.
- **What:** Re-confirmed from audit-10 I-03: `updated_at` =
  `2026-04-22T09:51:10Z`, 5 sources at sample_count=0,
  last_fetch_ok_at=null. Scraper-reweighting authority intact but
  dormant. No agent feeds signals.
- **Disposition:** No action; still pending an operator-direction call
  on whether to wire it or move to a Settled do-not-revive entry.

**I-07 - 74 ENGINE bumps in last 28 days (1.75 -> 1.154)**

- 5 bumps in the past 7 days (1.149 -> 1.154). Per ledger inspection
  (items 638-648) these are live-flip seam wiring, R5 self-HP plumbing,
  base-siege coach instrumentation, and overlay UX redesign - no
  security/perf surface this audit can flag from ledger alone.
- Daemon Slayer Share/ mirror remains drift-guarded via
  `tools/ds_share_sync.py --check`.

## Follow-ups filed

- **M-04-bis decisions drift** - re-escalation note on existing Agent 1
  proposal `20260621-100200-m04-decisions-drift/`; new resolved_decisions
  drafts d024 + d025 appended.
- **M-05 smb_push deadcode** - operator-decision proposal for Agent 1
  in `agents/agent6_auditor/proposals/20260628-081728-m05-smb-push-deadcode/`.
- **L-03 stale inventory CSV** - logged for Agent 1 housekeeping; no
  proposal this pass.

## Budget

Spawn budget consumed ~$1.60 of $3.00 at report-write start; remaining
~$1.40 reserved for proposal writes + queue filings + final stdout.
No Explore sub-agents fired this pass.

## Notes

- Operator is mid-ARAM during this audit run (`mode=game aram_mode=true
  has_game=true`). Audit is read-only and does not touch the in-game
  surface. No interruption posted to overlay or dashboard.
- The agent6 health rollup `last_outcomes` correctly reports green
  this pass: the FAIL FAIL COMPLETED sequence is not 2-consecutive-fail.
  C-01 stub mechanism will write a FAILED-<task_id>.md file if THIS
  task exits non-zero, but a normal completion produces a regular
  `completed` event with `result` payload set to the final stdout.
