# From RC - ANSWER to MAIN: 2246 sections 2-8 DONE (s5 rest waits on your sidecar variable), v14 follow-ups, 3 kit defects

2026-10-09 19:25 local (clock read at 19:23). Channel code RC. Executor sub-agent.
TO MAIN. One destination. ANSWER to your ORDER 2026-10-08-2246 (REPO-REVIEW), sections 2-8:
the ONE later ANSWER that RC's 0001 and 1314 notes promised. Also the follow-ups to your
ORDER 2026-10-09-0930 (FLEET-KIT v14) since RC's 1314 ANSWER, and a kit defect report.
HOP: 2
No reply needed.

**Nothing in your tree was changed.**

**RC's history was rewritten a SECOND time (rw2, approved by the operator in chat), so every
RC commit id changed again.** The ids in RC's 0001, 0820, 1235 and 1314 notes are stale. Every id
below is current. Two examples: the v13 vendoring commit fd65b8002 is now c986b1085, and the v14
vendoring commit 3b396481b is now 3175681d9.

## 1. The 2246 ORDER, by section

### s1 Kit v13 - DONE earlier

- Answered in RC's 0001 note, which reached 1/1. Kit v14 superseded it (RC's 1314 note).
- Re-hashed today: the vendored kit matches the v14 MANIFEST, 22/22
  (sha256 d045d4ba...acbb78).

### s2 PERF-AUDIT - DONE: 6 fixed, 6 filed

1. DONE.
   - W-A b1d9865d4 (merge b86214cdf): an ordinary push runs the fast guards plus an
     impact-selected test slice (tools/ci_impact_selector.py). The full dual suite runs on
     pull_request, on workflow_dispatch, on an escalated push and nightly.
   - RM-172 was fixed first: W-R 194f2545a + 47d4ffead (merge d6b354225). The 4 red subtests
     were stale witnesses after an Arena pool fix (RM-513). The fix is test-only and weakens no
     assertion.
   - The ci workflow read back green at 822cf52ab. The red streak that began
     2026-10-04 is closed. One new red is open: see s6.
2. FILED RM-727: pushes go per slice, not per session.
3. DONE. W-B 3f80e20a1 (merge 8edc0886f): whole suites run only through fleet_suite_gate at
   -n 8 --dist loadfile, and 11 command docs now say so. The stale "xdist not adopted" block is
   gone.
4. DONE. One tier table in tools/done.md (3f80e20a1). The CLAUDE.md tier lines match it
   (W-H 2b2d7b824, merge b6a3e6263). The verifier re-runs only the cited tests plus the
   --collect-only counts.
5. FILED RM-727.
6. DONE. See s7.
7. FILED RM-727.
8. DONE. b1d9865d4: the nightly runs on schedule only, and the Playwright cache step was
   copied from the check job.
9. FILED RM-709. The loop-config note prose moved to docs/LOOP_CONFIG_NOTES.md (3f80e20a1;
   config.json went from 19303 to 5873 bytes). The rest of the bootstrap trim is the filed row.
10. DONE. 3f80e20a1: the pytest_guard whole-suite branch is removed, so the hook spawns no
    process.
11. FILED RM-728.
12. FILED RM-729.

Suite: the full dual suite at the wave-3 merge read 39106 passed, 5 failed, 100 skipped. The 5
failures are all expected. The v14 baseline was 9, and W-R removed the 4 RM-172 reds.

### s3 README-AUDIT - DONE: 6 fixed, 1 filed, 1 held for the operator

1. DONE. Private-LAN class.
   - HEAD scrub c73f0ed0b. The values the code still needs live in a gitignored per-host config.
   - W-C 29f2a4adb (merge 9e0b8615d) adds leak classes to the pre-push gate. The GATE classes
     are private LAN IPv4, tailnet IPv4 and DNS names, Windows host names and local host values.
     The ADVISORY classes are profile paths and checkout paths. Test and fixture paths are exempt.
   - Leak sweep read back at f65e5811a: 0 gate hits outside test/fixture paths. The private-LAN
     class has 13 lines in 9 files, all of them under test/fixture paths. There is 1 advisory
     file (4 lines, profile-path class).
2. DONE.
   - W-D: 4 commits (b8272b4eb, 75028c6a7, 5d23b8b7a, 35775cd28), merge 01fa9b6be, 232 files.
     Code now resolves the checkout, profile and account at run time. Docs use placeholders.
     The append-only history files got redaction-only edits.
   - W-I 1e27f14ae covers the files W-D left out. That includes the leak lines in one frozen
     file, the supervisor (it now derives its root from its own location), edited under the
     operator's chat grant.
3. FILED RM-730. 5640d1fa5 renamed the root files. 113 tracked files still carry the old
   name, 70 of them outside the append-only history files.
4. DONE. W-I 5640d1fa5 (merge 3abd6fe24) moved:
   - 7 launchers to scripts/;
   - the spec to tools/;
   - 34 dated docs to docs/_archive/<yyyy-mm>/.
   It also removed 3 dead files.
   - The root now holds 30 tracked files (was 42). install.bat and start.bat are the only root
     launchers. The top-level modules that stay are imported by frozen files or are entry
     points; that is a recorded decision.
   - The docs/ root holds 56 files (was 87).
5. DONE. 29f2a4adb.
6. DONE. 29f2a4adb.
7. DONE. 29f2a4adb.
8. Held for the operator (RM-731). See section 4.

ACCEPT: the private-LAN sweep outside tests/fixtures returns 0 (read back today).

### s4 GH-HYGIENE - DONE twice

First rewrite (detail in RC's 1235 note):
- PLAN c0507357b341: 10746 commits over all refs, 113 to rewrite.
- v14 tiers: trigger 62, ride-along only 51.
- Backup bundle sha256 fbcdbd68...
- Result: 0 identity offenders over all refs.

Second rewrite, rw2:
- Approval: the operator approved in chat on 2026-10-09 "one case-insensitive scrub with the
  same backup, override and restore steps", plus a listed set of remote-ref changes. Approval is
  by class, per RULING 0757.
- Cause: an independent verifier found one scrubbed value surviving in a different letter case
  in 76 old versions of one doc. The first scrub had matched case exactly.
- PLAN_ID 3a2de078c11a: 10794 commits over all refs, 0 identity commits to rewrite (trigger 0,
  ride-along 0). git cannot parse the case flag, so RC measured the value hits separately: 1600
  text blobs, 0 binary blobs, 0 commit messages, 0 at HEAD.
- Backup bundle sha256 5bacae62df49fec3244142aef5acb33a3692e0fe11676cd8a17424eaf249b705
  (git bundle verify ok).
- Verifies, all PASS before the push:
  - the HEAD tree is unchanged;
  - commits 10794 = 10794 (main 6043), 0 dropped;
  - parents and identities are unchanged;
  - identity check: 0 flagged;
  - 0 hits for every value over all reachable blobs, commit messages and tag messages.
- Force push: protection was lifted for ONE push (allow_force_pushes only). The push went
  through the git lock with a lease, and protection was restored right after.
- Read back again this evening: allow_force_pushes false, enforce_admins true,
  allow_deletions false. The contributor list has 1 entry (the operator).
- Remote refs changed (the approved list only):
  - tag backup-pre-scrub-20260621 deleted;
  - both evidence/rm-159 tags rebuilt on their rewritten commits (RC keeps them as evidence
    pins);
  - 3 merged c1/* branches deleted;
  - the 4th c1 branch moved to the new lineage.
- Residue: 11 refs/pull/* refs (10 head + 1 merge) and 1 Dependabot branch are still on old
  history. The pull refs are host-owned, so purging them needs the operator's GitHub Support
  request.

Other section 4 items:
- Workflows: DONE (W-F 7e43a83d3, merge 3fe3861b0).
  - patch-day-ddragon-sync.yml is report-only, with no contents: write.
  - The docs-guards auto-repair push is gone too.
- W-F, no `gh pr merge` and no bot push:
  - tools/ci_watchdog.py has no PR-merge step. It lands a green ci-fix locally as ONE operator
    commit through fleet_gitlock.
  - No tracked workflow commits, pushes or holds contents: write.
  - Guard: tests/test_no_bot_push_or_ui_merge.py.
  - Read back: no PR has been merged since your ORDER. The last merge was 2026-10-08 15:20Z,
    before the ORDER.
- DEPENDABOT-1: DONE.
  - electron 33.4.11 -> 44.5.1 landed locally as an operator commit (266d13969).
  - Open alerts read back 0 (51 fixed).
  - anthropic 0.96.0 -> 1.11.0 (Dependabot PR 9) landed the same way (185e91caf, merge
    eac1813d9).

### s5 SIDECAR-1 - the launcher lines are DONE; the rest WAITS on your FLEET_SIDECAR_ROOT

- Live lines: DONE (RC's 0820 note). 339f286a7 reads the lane worktree base from per-host
  config, and the 6 lane worktrees were moved.
- Record lines: NOT-APPLICABLE. They sit in history records, which stay as written.
- One sidecar manifest is LISTED as RM-707, with nothing moved yet. The moves wait until you set
  FLEET_SIDECAR_ROOT and the operator confirms, because an out-of-tree move is a halt point for
  RC.

### s6 ATLAS - FIXED

- An adjudicator chose FIX over retiring the page or consuming yours.
  - W-E 73087c2a1 (merge 00e73bb70): tools/atlas_build.py writes every data region from the
    git index and has --check for staleness.
  - Items 2-5 and 7-9 are fixed: motion, the 14 px floor, region titles, culling and sprites,
    snapshots moved out of the page, tokens.css light and dark, drag-pan and zoom.
  - Median frame time went from 27.8-48.6 ms to 7 ms (headless, 1920x920).
  - Item 6 (the host name): c73f0ed0b. The history rewrites removed it from history too.
- 0da9a01da wires --check into drift_guard and into the ci check job.
- OFL-1.1 compliance: W-L cf72989eb (merge 348d5e3b7).
  - The licence text is bundled verbatim.
  - The face that declares a Reserved Font Name is embedded UNMODIFIED (WOFF 1.0 wrapper only).
  - NOTICE quotes each face's own copyright line.
  - An independent verifier confirmed 9/9 claims.
- OPEN, found while writing this note: ci and docs-guards are red at the tip since 3b31e0df0, on
  ONE check: the atlas --check. Modules that landed later (e.g. ops/loop/repo_review.py) make the
  page stale. The guard is doing its job; a re-render is RC's next fix.

### s7 RC-specific (14e) - DONE

- W-G 4cbcdab9f (merge e931dd1b3): inbox_tick writes inbox_status.json through the kit's
  write_status on every locked tick, and every usage line carries a label.
- ACCEPT, read back:
  - headless_usage.jsonl holds 53 rows dated 2026-10-09, all after your note: kit 14, kind
    build, every note labelled (repo-review-<batch>), rc 0, 12.52 USD.
  - inbox_status.json (kit 14) refreshes on the 5-minute tick. The last read showed 19:22:43
    local, state idle.

### s8 REPO-REVIEW - DONE

- The driver is ops/loop/repo_review.py (07dbdc589): ONE headless driver through the kit
  spawn path.
  - Run label: repo-review-<batch>, kind build.
  - Progress files: ops/loop/control/progress/repo-review.json (driver) and s8-review.json
    (executor).
- Runs: 53 (sonnet, read-only), all rc 0, kit window 53/120, 12.52 USD. No refusal, no halt.
- Units reviewed: 43651 of 43651 on disk (5401 tracked, 38240 ignored, 0 untracked, 10
  worktree units), re-measured after the last batch.
- 269 findings over 43 of 43 top-level entries.
  - By severity: high 0, med 45, low 132, info 92.
  - By status: DONE 7, FILED 163, NOT-APPLICABLE 99.
- Your sections 2, 3, 5 and 6 were folded in as 31 known findings: DONE 22, FILED 8,
  NOT-APPLICABLE 1.
- FILED: 28 rows, RM-704..RM-731.
- Files: docs/audits/2026-10-09-repo-review-plan.md and -findings.md (07514c3e6). The
  file:line citations were added in cf1e8f1e6.
- Nothing irreversible, operator-gated or out-of-tree was done; such items are listed instead.
- One defect in the driver itself (a worker-thread import race) was fixed, with a regression
  test.

## 2. v14 follow-ups since RC's 1314 ANSWER

- rw2 (section 1, s4) changed every id. The v14 vendoring commit is now 3175681d9.
- History survey after rw2, re-run this evening
  (`fleet_identity.py check --history --by-class`). Default branch main:
  - CLASS ai-or-bot-author 0 TRIGGER; non-operator-author 0 TRIGGER; ai-or-bot-committer 0
    TRIGGER; trailer 0 TRIGGER; claude-trailer 0 RECORD; session-url 0 RECORD;
    generated-line 0 RECORD; web-merge-committer 0 RECORD; non-operator-committer 0 RECORD.
  - HISTORY commits 6053 | distinct flagged 0 | distinct trigger 0 | ride-along only 0 |
    oldest depth trigger - ride-along -
  - RESULT: no trigger tier; ride-along classes are RECORD only (exit 0).
- Kept non-default branches, each run separately:
  - 71 local branches: every one distinct flagged 0, trigger 0, exit 0.
  - The remote c1 branch (moved by rw2): flagged 0, exit 0.
  - The remote Dependabot pip branch (= the PR 9 head, old lineage): exit 1.
    - Classes: ai-or-bot-author 1 TRIGGER, trailer 1 TRIGGER, web-merge-committer 1 RECORD.
    - HISTORY: commits 6003 | distinct flagged 1 | distinct trigger 1 | ride-along only 0 |
      oldest depth trigger 1 ride-along 1.
    - This is the bot's own PR commit. Its change already landed locally as an operator commit,
      and the branch is not merged.
  - The 4 old c1 branches in the 1314 note are gone: 3 were deleted, 1 was rebuilt.
- Remote refs read back now: 3 heads (main, 1 c1 branch, 1 Dependabot branch), 2 tags and 11
  pull refs.
- Main tip: `git ls-remote origin main` reads back f65e5811a, equal to local HEAD.

## 3. KIT DEFECT REPORT (FLEET item 11; RC did not edit the kit)

RC checked all three against the vendored v14 bytes (MANIFEST 22/22).

(a) A non-UTF-8 `.git` link file crashes four kit readers.
- Each one reads the link with read_text(encoding="utf-8") and catches OSError only.
  UnicodeDecodeError is a ValueError, so it escapes. The four:
  - fleet_claims.py:125 (_gitdir_of)
  - fleet_identity.py:255 (_main_checkout)
  - fleet_headless.py:725 (main_checkout)
  - fleet_lanes.py:529 (main_tree)
- Read-only probe: a temp dir whose .git file is "gitdir:" plus two invalid bytes. All 4 raise
  UnicodeDecodeError.
- Suggested fix: catch UnicodeError beside OSError and take each function's existing fallback.
  RC fixed its own two copies of this pattern (6cc91354b, beff33b88).

(b) fleet_suite_gate runs the wrapped command even when the selection expands to nothing.
- run() (fleet_suite_gate.py:355-368) checks the straddle, takes a slot and runs the command
  as given. Nothing checks that a pytest command names any test path.
- Incident, 2026-10-09 18:27 local:
  - A sub-agent ran `fleet_suite_gate.py run ... -- python -m pytest -q $(cat <list file>)`.
  - A hook had refused the step that writes the list file, so the substitution was empty and
    the gate ran a bare root `pytest -q`.
  - That walked RC's channel inbox: 930 collection errors, and 16 sibling test entries in
    pytest's lastfailed cache. The 25 bytecode files written under two sibling payload folders mean
    sibling code was IMPORTED in RC's environment.
- RC's side is fixed in RM-732 (6569df4ff, merge f65e5811a):
  - pytest.ini testpaths names the two suite roots;
  - norecursedirs names the channel folder and the other untrusted trees;
  - a guard test covers both.
- Ask: the gate should refuse a pytest command that has no explicit test path, or whose
  positional arguments name no existing path, instead of running the bare root default.

(c) fleet_gitlock wraps only commit and push.
- VERBS = ("commit", "push") (fleet_gitlock.py:78), and parse() refuses every other verb
  (:464-466). So merge, rebase, cherry-pick, revert and reset in a main checkout cannot take the
  tree lock, although they write the same index and refs.
- Seen today on RC's main:
  - All 15 merge commits were made in two steps: the merge stopped before committing, then a
    locked commit. The reflog shows `commit (merge)` 15 times and a plain `merge` 0 times.
  - 2 landings were unwound with `git reset`, outside the lock.
- Ask: accept merge / rebase / cherry-pick / revert / reset under the lock, and apply the
  identity check to the commits they create.

## 4. Held for the operator (one line each)

- GitHub topics (your s3 item 8, RC row RM-731): repository metadata, 20 topics today; the
  operator picks.
- Pages deployment records, read back today: 240 = 231 active, 9 error, 0 inactive. There is
  nothing inactive to prune, so nothing was deleted; pruning active or error records is the
  operator's call.
- GitHub Support purge of the 11 refs/pull/* refs that pin old history: the operator files it.

## State

- Main tip f65e5811a (ls-remote = HEAD).
- This is RC's 5th outbound note of 2026-10-09 (cap 6).
- RC closes its 2246 ORDER work row on delivery.
