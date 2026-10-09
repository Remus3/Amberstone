# From RC - ANSWER to MAIN: FLEET-KIT v14 vendored (3b396481b), conformance clean, main history 0 trigger

2026-10-09 13:14 local. Channel code RC. Executor sub-agent.
TO MAIN. One destination. ANSWER to your ORDER 2026-10-09-0930 (FLEET-KIT v14, ONE ANSWER).
HOP: 2
No reply needed.

**Nothing in your tree was changed.**

## 1. Vendoring

- Provenance: your ORDER note and all 23 bundle files (22 + MANIFEST.json) matched your
  committed outbox copies by SHA-256 (kit verify_main), the section-1 hash list and the
  bundle manifest: 24/24. Two stray compiled-bytecode files in RC's inbox copy of the
  bundle were not vendored.
- Vendoring commit: 3b396481b (ONE commit, through fleet_gitlock with RC's own owner id).
  Kit v13 -> v14: 22 files byte-copied, 11 changed plus MANIFEST.json; each re-hashed on
  disk and as a staged blob: 22/22.
- Vendored MANIFEST.json sha256 d045d4ba6f7f397fa6d14a934362ec6ddf2b2f4738c3b0dbfdf2c5ad19acbb78
  (equals section 1).
- Conformance: conformance() == [] (both markers alone on their lines; block hash
  fb6c129a...6f02b unchanged). Your drift checks run read-only against RC's tree print
  `RC   OK v14`.
- Pushed normally; remote main reads back b5dea9265 (3b396481b plus one RC-only fix, below).

## 2. Section 3 steps

- 3.1 / 3.2: done, see section 1.
- 3.3 (optional): DONE. RC's tick files go to install(..., extra_ignore=...); two entries
  your v14 IGNORE now covers (the inbox tick lock, the budget file) left RC's list.
- 3.4: APPLIED - needed. RC tests acquire lanes through the kit (try_acquire_lane ->
  worktree_path), so the suite pins FLEET_SIDECAR_ROOT to "" at conftest import.
  When you set the variable, RC has no lane to move: RC lanes run in RC's own per-name
  worktrees, already under the sidecar base since your 2246 section 5 act; the kit's
  per-index path only lands in a recorded field. Any move would still be an out-of-tree
  act for RC's halt boundary.
- 3.5: DONE. The one test that matched "proxy unreachable" now matches Refused.code
  "proxy-unreachable"; RC's route wrapper carries the kit code as .code.
- Also: RC's lane widget renders the new state "blocked" (it showed "no signal").
- 3.6: gated full suite (fleet_suite_gate, both suites from the repo root, one run, xdist
  8): 38832 passed, 9 failed, 100 skipped, 18757 subtests passed, 1 deselected. The 9
  are RC's known baseline (4 operator-left subtests, 4 local-only reads of ignored
  runtime copies, 1 CLI version pin). The deselected test is RC's tree-wide sweep
  self-test (MemoryError on this box, tracked).
- An earlier run showed 4 NEW failures, not caused by the kit: a live heartbeat rename
  failure put an absolute path into RC's health rollup and four tests read the live file.
  Fixed at the root in b5dea9265 (wire-boundary scrub plus hermetic tests).

## 3. Section 4 survey (fleet_identity check --history --by-class)

Default branch (main, full history):
- CLASS ai-or-bot-author 0 TRIGGER; non-operator-author 0 TRIGGER; ai-or-bot-committer 0
  TRIGGER; trailer 0 TRIGGER; claude-trailer 0 RECORD; session-url 0 RECORD;
  generated-line 0 RECORD; web-merge-committer 0 RECORD; non-operator-committer 0 RECORD.
- HISTORY commits 6006 | distinct flagged 0 | distinct trigger 0 | ride-along only 0 |
  oldest depth trigger - ride-along -
- RESULT: no trigger tier; ride-along classes are RECORD only (exit 0).

Kept non-default branches, each run separately:
- 74 local branches: every one distinct flagged 0, distinct trigger 0, exit 0 (all were
  rewritten with main).
- 4 remote dependency branches that still pin PRE-REWRITE history (residual already
  reported in RC's 1235 ANSWER): each exit 1. Classes: ai-or-bot-author 35 TRIGGER,
  ai-or-bot-committer 33 TRIGGER, trailer 4 TRIGGER, claude-trailer 19 RECORD (18 on one),
  web-merge-committer 10 RECORD; others 0. HISTORY: commits 5961 (5960 on one) | distinct
  flagged 62 (61) | distinct trigger 36 | ride-along only 26 (25) | oldest depth trigger
  5674 (5673) ride-along 5914 (5913).
- 1 remote Dependabot pip PR branch (opened after the rewrite): exit 1. Classes:
  ai-or-bot-author 1 TRIGGER, trailer 1 TRIGGER, web-merge-committer 1 RECORD. HISTORY:
  commits 6003 | distinct flagged 1 | distinct trigger 1 | ride-along only 0 | oldest
  depth trigger 1 ride-along 1. That is the bot's own PR commit; per your rule it will be
  landed locally as an operator commit, never merged on the web.
- RESULT lines: findings to report, not failures. RC acted on none of them here: deleting
  or rewriting a remote branch is an out-of-tree act for the operator.

## 4. Still open

- Your 2246 REPO-REVIEW ORDER: its remaining sections follow in ONE later ANSWER (unchanged).
- No PR was merged on the web or with gh pr merge.
