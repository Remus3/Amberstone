# Lane prompt reference

On-demand detail for the rotating lane directive. The directive names the section to
read and when. Every floor (no push, halt boundary, stop files, exclusions, tests,
verifier gate) is stated in the directive itself; this file holds the procedure and
the reasoning behind it. Where the two differ, the directive wins. `<main>` is the
main checkout, `<lane>` your lane, `<stop>` your lane's stop file.

## R1. Rebase conflict and leftovers

- Commits on the lane branch that are not in `main` are earlier cycles' work waiting
  for the merger, including commits from earlier sessions. Keep them. Never redo
  their rows, and never drop, squash, amend, reset or rewrite them.
- If the driver note says a rebase onto main conflicted: run `git rebase main` and
  resolve it, keeping both sides of an append conflict. If it cannot be resolved
  cleanly, `git rebase --abort`, keep working on your current HEAD, and say so in the
  report.
- Uncommitted changes at start are a previous cycle's leftovers. Read `git status`
  and `<main>/ops/loop/control/lane_prompts/s144_<lane>_cycles.jsonl` (tail only, it
  is large). Finish and commit them if they are a coherent verified slice, otherwise
  `git stash push -m s144-leftover-<run id>`. Record which in the report. Never pop or
  drop a stash you did not create this cycle.

## R2. Why the worktree base is inside the repo

The lane base is `<repo>/.claude/worktrees`, through `RC_LANE_WORKTREE_BASE`. A
worktree outside the repo root would be a halt-boundary write. Lane doc pre-flight
worktree checks hold with that base.

## R3. The push block

The driver sets `GIT_CONFIG_COUNT` entries that rewrite the origin push URL and the
GitHub push URLs to `no-push://disabled`, so a push fails closed. The driver's
lane-leak alarm stops ALL lanes if a lane ref or lane-only commit appears on a
remote-tracking ref; a main-session push of local main is expected and does not stop
you. If a tier-1 test that pushes to a temporary local repo fails with "Unable to
find remote helper for 'no-push'", that is the block, not your defect: record it
under MERGER RERUNS and do not work around it.

## R4. Stop files that are not yours

`<main>/ops/loop/control/STOP` (2026-09-11) is the old loop controller's halt and
stays in place on purpose. This driver does not read it. The older session files
under `ops/loop/control/lanes/` (`S133_*`, `S134_*`) are not read either. A lane does
not wrap on any of them and never creates, edits, renames or deletes one.

## R5. Live state a lane may read

`ops/runtime/health.json`; `curl -k https://127.0.0.1:8888/api/state`;
`/api/health/all`; `curl -s http://127.0.0.1:8860/health`; the `:8889` relay over
plain http with the `X-RC-Token` header from `core.vision_token` (never print the
token); LCU GET requests through RC's own lcu client code; `schtasks /Query`; the
process tree.

## R6. Taken-row check

A row or target is taken when `git log --oneline main..lane/<x>` on ANY lane branch,
your own included, names its id or file (older-session commits awaiting landing
count), or a report under `<main>/ops/loop/control/lane_prompts/s144_reports/` does.
Grep the row id or file name; do not read the reports whole.

## R7. Report headings, defined

- SUMMARY: one paragraph.
- COMMITS: sha + subject of every commit this cycle, and `git log --oneline main..HEAD`
  at exit.
- TESTS: each file run, the summary line and exit code observed THIS run.
- VERIFIER: verdict and what it re-ran.
- LEDGER-PENDING: the unnumbered LEDGER entry text.
- ROADMAP-PENDING: any ROADMAP pointer text.
- FILINGS: provisional S144 ids with one-paragraph bodies: where, acceptance, tier,
  gated or not.
- CLOSURES: rows this cycle closes or partly closes, with the commit sha.
- MERGER FOLLOW-UPS: restarts, Tier-2 runs, live checks, BACKLOG / ROADMAP edits the
  merger owes.
- MERGER RERUNS: tests that must be re-run outside the lane environment.
- NEXT CANDIDATE: the next row or target.

## R8. Lane doc reads

`python tools/lane_doc_sections.py <lane>` prints the lane doc's mandate and required
sections, then an index of on-demand sections with a trigger for each. The map lives
in that tool; `tests/test_lane_doc_sections.py` fails if a doc section is unclassified
or a named one vanishes. Sections the directive overrides (push, CI, dual suite, wrap,
banner) are on-demand, never deleted. If the tool is missing or exits non-zero, read
the whole `tools/headless-<lane>.md`.
