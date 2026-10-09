# CI Watchdog - Scoping Plan

Scoping doc only. Implementation deferred to a separate scoped session.

## Goal

Eliminate the "CI red for N consecutive runs" lane (item 167 ruff blocked CI for 10 runs before item 172 fixed). Detect main-branch CI failure, auto-diagnose, write minimal fix, open PR. Operator never has to babysit lint/format/type breakage again.

## Trigger surface

Source-of-truth: `gh run list -R Remus3/Amberstone --branch main --json databaseId,status,conclusion,headSha`. No webhook (local-only; Legion has no public ingress). Poll cadence = 120s (cheap; sub-2-min detection is overkill for nightly-paced CI).

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

Failure budget: max 2 PR attempts per run-id (sentinel: `ops/runtime/ci_watchdog/attempts/<run-id>.txt`). On 2nd fail, write `ops/runtime/ci_watchdog/ESCALATION.md` with the diff + claude transcript for the operator (local-only; the cross-Claude bridge was decommissioned 2026-06-24, ADR-012).

## Headless claude isolation

Run from a dedicated git worktree at `<ci-watchdog-worktree>\` (not the live Legion checkout). Avoids stomping on operator's in-flight edits. Worktree refresh: `git fetch && git reset --hard origin/main` before each invocation. Worktree pattern matches the orchestrator-merge precedent (items 134-188).

## Scheduled task

`RC-CIWatchdog` on Legion, every 2 min, runs as the operator account, action = `pythonw.exe tools\ci_watchdog.py`. HIGHEST priority NO (background-class only).

## Cost model

Per-invocation: 1 headless claude run with ~5k input tokens (CI log tail + diff + prompt) + ~1k output (fix patch). At haiku-4-5: ~$0.005/run. At 1 CI failure / week typical cadence: ~$0.02/month. Within RC's cost-trace budget (item 152 closed gap C).

## Kill switches

- `ops/runtime/ci_watchdog/HALT` presence -> loop exits without action.
- 2-strike escalation -> local ESCALATION.md (no bridge; decommissioned 2026-06-24, ADR-012).
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

- Worktree at `<ci-watchdog-worktree>\` NOT inside `<repo>\`.
- `--allowed-tools` whitelist on every headless invocation; never `--dangerously-skip-permissions`.
- Frozen-file refusal pinned in the system prompt AND enforced by Bash glob deny.
- `last_seen_run_id.txt` is the only state file the poller mutates; everything else is per-run.
- The 2-strike escalation is per-run-id, not per-day.

## Open questions - RESOLVED 2026-06-18 (operator)

- PR auto-merge on green CI: YES, AUTO-MERGE (self-heal unattended). `tools/ci_watchdog._MERGE_METHOD` = `--squash` (ci-fix PRs are tiny + CI-green at merge; branch auto-deleted).
- ESCALATION: LOCAL-ONLY. The RC<->Peer bridge was decommissioned 2026-06-24 (ADR-012), so `core.bridge.send` no longer exists; on the 2nd failed attempt the watchdog writes `ops/runtime/ci_watchdog/ESCALATION.md` (diff + claude transcript) for the operator. No cross-machine envelope.
- Self-cancel on a newer main commit: YES, CANCEL + restart on newest HEAD - `is_stale(run_head_sha, current_head_sha)` skips any fix whose target run is no longer at `origin/main` HEAD.

## Build status - item 204 BUILT 2026-06-18; DISPATCH WIRED 2026-06-24 (still NOT live-armed)

`tools/ci_watchdog.py` (pure decision logic + thin I/O main), `tools/ci_watchdog_fix.md` (headless system prompt), `ops/RC-CIWatchdog.xml` (task artifact), `tests/test_ci_watchdog.py` (27 tests) all shipped.

**Dispatch wiring (2026-06-24):** the `main()` stub is replaced by a real two-function dispatch - pure `plan_dispatch(run_id, head_sha)` returns the ordered (label, argv) command plan (worktree sync -> gather log+diff -> headless `claude -p` fix -> frozen guard -> push -> `gh pr create` -> self-gate on the PR's own CI (`gh pr checks --watch --fail-fast`) -> `gh pr merge --squash` on green), and `execute_dispatch(..., arm=)` either surfaces it (dry run) or runs it. The headless fix is tool-restricted (`--allowedTools Edit Read Bash(ruff:*) Bash(git:*) Bash(python -m py_compile:*) Bash(pytest:*)`, `--disallowedTools Write "Bash(git push:*)"`, NO `--dangerously-skip-permissions` - non-whitelisted tools auto-deny in `-p`), reads its context from `<worktree>/.ci_watchdog_context.md`, and cannot push (the watchdog owns push/PR/merge). The frozen-file guard runs BETWEEN the fix and any push.

**Dry-run-by-default safety:** `main()` (and the bare scheduled-task invocation) is READ-ONLY - it logs each decision + the would-run plan to `audit.jsonl` but mutates NO state (sentinel / attempts / pr-log) and runs no side effects. Arming is the single literal flag `--arm`. Live-verified 2026-06-24: a bare run correctly `skip_stale`-skipped the 4 then-stale red runs with the sentinel left absent; `execute_dispatch(arm=False)` prints the exact 10-step plan.

**ARM step (operator, when ready):** (1) create the dedicated worktree `git worktree add <ci-watchdog-worktree> origin/main` (kept OUT of the live checkout); (2) enable repo auto-merge + a branch-protection CI gate so `--squash --auto` merges only on green; (3) edit `ops/RC-CIWatchdog.xml` action args to append `--arm`, then `schtasks /Create /TN RC-CIWatchdog /XML "ops\RC-CIWatchdog.xml" /F` (runs as the logged-on operator account so gh/claude/git auth resolves); (4) soak: watch `audit.jsonl` over a real red main before trusting unattended merge. Kill-switch: create `ops\runtime\ci_watchdog\HALT`. The unattended auto-merger must not race the headless run that built it.

**SELF-GATE design update + ARMED 2026-06-25 (item 622).** The `--auto` + branch-protection merge described above was REPLACED by an in-watchdog self-gate: after `gh pr create`, the dispatch BLOCKS on the ci-fix PR's OWN CI via `gh pr checks <branch> --watch --fail-fast` and squash-merges (`gh pr merge --squash`, no `--auto`) ONLY on green; a red or timed-out check ESCALATES and is never merged. This needs NO `allow_auto_merge` and NO branch protection, so step (2) above is moot and the direct-push-to-main workflow is preserved (verified live: `allow_auto_merge=false`, main unprotected, repo is a private personal account where classic branch protection is gated anyway). Armed via `Register-ScheduledTask` with the task XML carrying `--arm`; `ExecutionTimeLimit` raised PT10M -> PT30M for the blocking check-watch, and the pre-existing `MultipleInstancesPolicy=IgnoreNew` prevents overlapping armed cycles during the wait. Per-step subprocess timeouts (`_STEP_TIMEOUTS`: claude_fix 600s, wait_checks 900s) bound each blocking step. +3 self-gate tests (30 total in `tests/test_ci_watchdog.py`). The CI workflow runs on `pull_request: [main]`, so the ci-fix PR genuinely gets checks for the gate to watch.

**LAND-LOCALLY redesign 2026-10-09 (MAIN kit-v13 ORDER section 4 + kit-v14 ORDER section 4, operator authority).** The squash-merge step above is GONE: no PR is merged on GitHub in any mode, because the web-merge committer (and a squash that keeps the fixer as author) puts a non-operator identity on main. The self-gate is unchanged; on green the dispatch now runs `_land` in the watchdog worktree: `land_fetch` -> `land_head` (origin/main must still equal the failing run's head, decision 3; otherwise NOT landed) -> `land_branch` (`checkout -B ci-land/<id> origin/main`) -> `land_squash` (`merge --squash ci-fix/<id>`) -> `land_commit` (ONE commit whose message the watchdog writes, run through `ops/fleet_kit/fleet_gitlock.py run --owner ci-watchdog`, which refuses a Claude / bot author or committer) -> `land_verify` (fleet_identity on `origin/main..HEAD`: exactly one commit, operator idents from the worktree's local `fleet.operatorIdent`, no trailer class; fails closed) -> `land_push` (`push origin HEAD:main` inside the git lock, a plain fast-forward, never forced) -> `pr_close` (closed with a comment, branch deleted). Any refusal leaves main untouched and the PR open, and escalates to ESCALATION.md so the operator lands it by hand. The fixer prompt (`tools/ci_watchdog_fix.md`) no longer asks for a co-author trailer; the squash drops the fixer's message anyway. Guard: `tests/test_no_bot_push_or_ui_merge.py` (no tracked code merges a PR on GitHub, no workflow commits / pushes / holds `contents: write`, no tracked script sets a git identity); land-phase end-to-end tests with a real bare origin and the real kit in `tests/test_ci_watchdog.py`. Measured 2026-10-09: the `C:\RC-CIWatchdog` worktree is absent on this box, so no armed cycle can reach the land phase until it is recreated (`git worktree add`), and the recreated worktree needs `fleet.operatorIdent` in its local config for `land_verify` to pass.
