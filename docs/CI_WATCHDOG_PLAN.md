# CI Watchdog - Scoping Plan

Scoping doc only. Implementation deferred to a separate scoped session.

## Goal

Eliminate the "CI red for N consecutive runs" lane (item 167 ruff blocked CI for 10 runs before item 172 fixed). Detect main-branch CI failure, auto-diagnose, write minimal fix, open PR. Operator never has to babysit lint/format/type breakage again.

## Trigger surface

Source-of-truth: `gh run list -R Remus3/riot-commander --branch main --json databaseId,status,conclusion,headSha`. No webhook (local-only; Legion has no public ingress). Poll cadence = 120s (matches RC-BridgeWatcher; cheap; sub-2-min detection is overkill for nightly-paced CI).

## Failure scope (in-bounds)

Only auto-fix:
- `ruff check` violations
- `py_compile` failures from syntax-level breakage
- Import errors caused by typo/path drift
- Single-test obvious assertion failures with a localized fix (NEW field, count off-by-1)

Out-of-bounds (escalate, do not patch):
- Multi-test failures (regression suite light-up)
- Snapshot drift on `tests/snapshot_panels/` or `tests/snapshot_regressions/`
- Anything that touches a frozen file (CLAUDE.md "Frozen files" list)
- Anything modifying behavior (logic, control-flow, public API)

Contract: edit `tests/`, `*.py` linting/types/imports only. No edits to coach prompts, dashboards, supervisors, or DS engine.

## Architecture

```
tools/ci_watchdog.py            -- poller + dispatcher
tools/ci_watchdog_fix.md        -- prompt for headless claude
ops/runtime/ci_watchdog/
    last_seen_run_id.txt        -- sentinel (single int)
    HALT                        -- presence kills the loop
    audit.jsonl                 -- one line per run inspected
    ESCALATION.md               -- written on 2nd consecutive fail
ops/RC-CIWatchdog.xml           -- scheduled task definition
```

Poller logic (pseudo):
1. Read HALT - if exists, exit 0 silently.
2. `gh run list ... --limit 5` -> JSON.
3. Filter `conclusion == "failure" AND databaseId > last_seen`.
4. For each failed run (oldest first):
   a. `gh run view <id> --log-failed` -> capture failing step + tail.
   b. `git show <headSha>` -> diff context.
   c. Invoke `claude -p` headless with `tools/ci_watchdog_fix.md` system prompt + `--allowed-tools "Edit Read Bash(ruff *) Bash(python -m py_compile *) Bash(pytest *) Bash(git *)"` + `--disallowed-tools "Write(frozen/*)"` (or guard inside the prompt).
   d. Claude produces a fix on `ci-fix/<run-id>` worktree branch.
   e. Local verify: `ruff check .` clean AND `pytest tests/phase2_smoke tests/snapshot_regressions tests/phase8_smoke -q` green.
   f. `gh pr create --base main --head ci-fix/<run-id> --title "ci(fix): <one-line root cause>" --body <structured>`.
5. Update last_seen_run_id.txt.

Failure budget: max 2 PR attempts per run-id (sentinel: `ops/runtime/ci_watchdog/attempts/<run-id>.txt`). On 2nd fail, write ESCALATION.md with the diff + claude transcript + ping operator via bridge.

## Headless claude isolation

Run from a dedicated git worktree at `C:\RC-CIWatchdog\` (not the live Legion checkout). Avoids stomping on operator's in-flight edits. Worktree refresh: `git fetch && git reset --hard origin/main` before each invocation. Worktree pattern matches the orchestrator-merge precedent (items 134-188).

## Scheduled task

`RC-CIWatchdog` on Legion, every 2 min, runs as Administrator, action = `pythonw.exe tools\ci_watchdog.py`. Mirrors RC-BridgeWatcher cadence + identity. HIGHEST priority NO (background-class only).

## Cost model

Per-invocation: 1 headless claude run with ~5k input tokens (CI log tail + diff + prompt) + ~1k output (fix patch). At haiku-4-5: ~$0.005/run. At 1 CI failure / week typical cadence: ~$0.02/month. Within RC's cost-trace budget (item 152 closed gap C).

## Kill switches

- `ops/runtime/ci_watchdog/HALT` presence -> loop exits without action.
- 2-strike escalation -> ESCALATION.md + bridge note.
- Scheduled task `Disable-ScheduledTask -TaskName RC-CIWatchdog` -> hard stop.
- Hard upper bound: max 3 PR creations per 24h (rate-limit gate).

## TDD-first build order (when implementation session opens)

1. NEW `tests/test_ci_watchdog.py` characterization tests: HALT honored, sentinel monotonic, 2-strike escalation, frozen-file refusal, rate-limit gate, audit.jsonl shape.
2. NEW `tools/ci_watchdog.py` poller + dispatcher.
3. NEW `tools/ci_watchdog_fix.md` system prompt.
4. NEW `ops/RC-CIWatchdog.xml` scheduled task.
5. Dry-run dispatch on the item-167 failed run (`64fc7cfc`) - verify ruff fix is the minimum 3-paren removal that item 172 shipped.
6. Live-arm via `Register-ScheduledTask`.
7. 1-week soak monitoring `audit.jsonl`.

## Out-of-scope this plan

- GitHub Actions webhooks (no Legion public ingress).
- Multi-repo support (RC only).
- Behavior-change fixes (out-of-bounds; escalate).
- Snapshot regeneration (operator-decided).
- Test-author judgment calls (out-of-bounds).

## Don't-redo when implementing

- Worktree at `C:\RC-CIWatchdog\` NOT inside `C:\Riot Commander\`.
- `--allowed-tools` whitelist on every headless invocation; never `--dangerously-skip-permissions`.
- Frozen-file refusal pinned in the system prompt AND enforced by Bash glob deny.
- `last_seen_run_id.txt` is the only state file the poller mutates; everything else is per-run.
- The 2-strike escalation is per-run-id, not per-day.

## Open questions for implementation session

- Does the operator want PR auto-merge on green CI, or always leave for review?
- Bridge-note format for ESCALATION.md (kind="ci_watchdog_escalation" envelope)?
- Should the watchdog also self-cancel if the operator pushes a new commit to main while a ci-fix branch is in flight (avoid stale-fix PRs)?
