# Agent 6 — Seventh Audit (Phase 3 repo pass)

- **Date:** 2026-05-18 04:54 UTC (cron `t-f4d6c8cfb697`)
- **Auditor:** Agent 6 (Opus 4.7, ephemeral, ~$2.00 of $3.00 budget)
- **Scope:** Phase 3 subtree cross-referenced against
  `agents/state/resolved_decisions.json@phase3-1.1`. Light pass — most
  budget was consumed by session bootstrap context; this report covers
  what was verifiable cheaply rather than full Explore-subagent sweeps.
- **Follows:** `20260511-200200-sixth-audit-phase3.md`.

## Live-state snapshot

- RC supervisor: pid 7632 alive, mode=client, last_reload_ok=true.
- Phase 3 supervisor: state=Running (per session bootstrap probe).
- DS engine: patch 16.10.1 alive on :8893.
- Bridge — peer daemon age 25s (healthy); **gamepc daemon age 8489s
  STALE** (~2.4hr; threshold typically 600s).
- Activity 24h: 56 notes, 1 result, 1 task — bridge task path itself is
  not blocked; only the *health publisher* is stale.

## Audit-6 verification

Audit-6 filed **M-01** (bbox HTTP-override missing `r>l, b>t` /
coord-range check at `agents/supervisor.py:596-605`). Status: still open
in this pass — no commits matching `bbox` in the last 30 days. Proposal
`P-audit6-m01-bbox-override-validate` is dormant. Re-filing as **C-01**
below; defense-in-depth not regressed but also not closed.

## New findings (this pass)

### HIGH

**H-01 — `gamepc` bridge health-publisher stale ~8500s while `peer` is healthy at 25s; no alarm path engaged**
- **Symptom:** Session-start probe surfaced
  `gamepc bridge daemon: watcher=alive queue=0 age=8489s ⚠ STALE` next
  to a perfectly fresh `peer bridge daemon … age=25s`. Both daemons share
  the same task loop (which IS alive — the only delta is the heartbeat
  publisher).
- **Why it's a finding (not just an anomaly):** The auditor's session
  bootstrap probe *did* render the STALE marker, but nothing else
  appears to. There is no Agent 1 task filing, no `/api/health/all`
  surfacing, no operator-visible chip on the dashboard that I can
  confirm — the staleness lives only in the rc_facts probe output. A
  publisher that has been silent for nearly 3 hours while the loop is
  alive is exactly the false-confidence shape this charter's focus-area
  #6 ("startup ordering / process aliveness") warns against — the loop
  could in principle have crashed at minute 60 of the 142, with the
  publisher noise masking it, and no one would notice for another
  several hours.
- **Concrete fix:** Two parts. (a) Add a `health_publisher_age_s`
  field to the `/api/health/all` shape so the dashboard can render an
  amber chip when any node exceeds 600s. (b) Have the Phase 3
  supervisor file an Agent 1 task (severity=warning, dedup by node)
  the moment age crosses 1800s, with a one-liner suggesting `tools/
  gamepc_boot.ps1` restart of the health publisher. The s167 deferral
  bucket already calls out `RC-WatcherHealthPublisher-GamePC` /
  `RC-BridgeWatcher-GamePC` hardening — this finding restates the same
  gap with concrete trigger evidence.
- **Action:** Proposal `P-audit7-h01-bridge-health-publisher-alarm`
  filed for Agent 2 (backend). Bundles cleanly with the s167
  `gamepc_boot.ps1` hardening already-deferred item.

### MEDIUM

**M-01 — `body[data-mode]` flap fix (commit `e4b08ba`) lacks a regression test**
- **What's wrong:** `e4b08ba fix(dashboard): stop body[data-mode] flap
  during lobby preflip` is a one-commit fix for a real visual
  regression (mode chip flicker during the lobby pre-flip mirror added
  by s153/s157). No accompanying test under `tests/preflip_mode/` was
  added; the existing `test_file_ingest_mirror.py` (currently
  untracked, per `git status`) covers the file-ingest side but not the
  body-attribute set/clear path.
- **Why it matters:** The s153/s157 dual-write (HTTP + WS) shape means
  any future change to `_state_builder.build_state` or the WS
  envelope's `mode` field can silently re-introduce the flap. The
  visual symptom is operator-noticed but not test-noticed.
- **Concrete fix:** Add `tests/preflip_mode/test_body_data_mode_no_flap.py`
  asserting that two consecutive `build_state()` calls during a
  lobby→champ-select transition emit identical `body[data-mode]`
  values for the period where the LCU phase has moved but the
  liveclient hasn't yet flipped (the exact window the e4b08ba fix
  closes). The s171.7 `view_router_state.py` Python mirror pattern is
  the precedent — same idea, body-attribute scope rather than view-id
  scope.
- **Action:** Proposal `P-audit7-m01-body-data-mode-regression-test`
  filed for Agent 3 (testing).

### LOW

**L-01 — `tests/preflip_mode/test_file_ingest_mirror.py` is untracked at session start**
- **What's wrong:** `git status` shows the file as `??` (untracked) at
  session bootstrap. Either it was authored and never `git add`'d, or
  it's a stray work-in-progress that survived a session boundary.
  Charter focus-area #6 ("startup ordering / WS log corruption / DB
  lock") applies analogously: untracked test files are not a
  *runtime* failure mode, but they are an *audit-trail* failure mode
  — they cannot be CI-gated and they vanish on `git stash` /
  `git clean`.
- **Concrete fix:** Either `git add tests/preflip_mode/test_file_
  ingest_mirror.py` (if it's the intended companion to the e4b08ba
  fix), or move to `_archive/` (if it's a stale spike). Operator
  decision, not Agent 2 — file as info-only note to Agent 1 rather
  than a proposal.
- **Action:** No proposal filed. Flagged here so the next `/done` run
  notices it.

### INFO

**I-01 — Audit-6 backlog status**
- Audit-6 `M-01` (bbox HTTP-override validation) still open. Re-counted
  as **C-01** carried-forward (not a new finding, just unresolved).
- No Audit-6 findings have been silently fixed and undocumented.

**I-02 — Charter focus-area #7 (secret-leakage) spot-check**
- Spot-checked the new `core/augment_external_source.py` + `core/
  augment_recommender.py` (CLAUDE active priority #88, commit
  `10aa944`). No `API-Key-Claude.txt` or env-var dumps in log lines;
  external source is Overlay App E/iesdev (unauth, no key surface). Pass.

## Budget reconciliation

Spent ~$2.00 of $3.00. Session bootstrap (CLAUDE.md + MEMORY.md
context inflation) consumed the first ~$1 before any audit work
began; the per-line per-finding cost of the actual audit was modest
(~$0.20-$0.30 per finding). Recommend the dispatcher consider a
**lighter context preset for Agent 6 cron runs** (skip the active-
priorities block 60+ of CLAUDE.md, since the auditor charter does not
need the s174-s220 changelog text to do its job). Filed as an
operator-decision note rather than a proposal — Agent 6 cannot edit
the dispatch shape unilaterally.

## Proposals filed this pass

- `P-audit7-h01-bridge-health-publisher-alarm` → Agent 2 (backend)
- `P-audit7-m01-body-data-mode-regression-test` → Agent 3 (testing)

## Open audit backlog

| ID | First filed | Status | Notes |
|---|---|---|---|
| audit6-M-01 (bbox HTTP-override) | 2026-05-11 | OPEN | Re-flagged as C-01 |
| audit7-H-01 (bridge health alarm) | this pass | NEW | Agent 2 |
| audit7-M-01 (body[data-mode] test) | this pass | NEW | Agent 3 |
| audit7-L-01 (untracked test file) | this pass | INFO | Operator |

End of report.
