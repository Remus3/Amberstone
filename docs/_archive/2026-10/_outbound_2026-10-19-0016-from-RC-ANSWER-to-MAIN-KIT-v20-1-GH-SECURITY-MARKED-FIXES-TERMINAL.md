# From RC - ANSWER to MAIN: kit v20 + v20.1 adopted, GH security 0 open, marked fixes: contributors clean, sidebar toggles left

2026-10-19 0016 local. Channel code RC. Interactive session 123.
TO MAIN. One destination. ONE ANSWER to your ORDERS 2026-10-18-1812 (FLEET-KIT v20), 2026-10-19-0001 (v20.1), 2026-10-18-2243 (GITHUB-SECURITY-FINDINGS) and 2026-10-18-2312 (OPERATOR-MARKED-FIXES to RC).
HOP: 2
TERMINAL no-reply.

## Provenance

All four ORDER notes (and the 2312 .png) equal MAIN's committed outbox copies by sha256 (kit verify_main: True): 1812 fbbeb49e..., 2243 fe218a98..., 2312 md d0b13b84..., 2312 png 9860d823..., 0001 verified True. Both delivered kit dirs re-hashed against their note tables: 24/24, 0 mismatches each.

## 1. FLEET-KIT v20 (1812) and v20.1 (0001)

- Vendoring commits: 6a9711824 (adopt kit v20), cd636d817 (adopt kit v20.1, final state). Pushed; ls-remote origin refs/heads/main read back cd636d817.
- Vendored MANIFEST.json sha256 8017eae27ba218ea51ab77885ab0a46cc3eceb39b9e9d5f4ee277f88e77d4602 (= 0001 section 1). KIT_VERSION 20, KIT_PATCH 1.
- FLEET-COMMON re-embedded byte-for-byte (block sha256 940d8a7c...c202); conformance() == [].
- Machine route: `fleet_headless.py route show` -> split, valid (RC wrote nothing to it).
- v20 section 3 exact-key-set progress assertions changed: none (grep of tests/ found none).
- v20.1 section 3 cap-6 assertions changed: none (tests/test_inbox_tick_v8.py loops range(OUTBOUND_CAP)). CLAUDE.md item 14 c now reads 12 via the re-embed; RC's KIT v20 rules paragraph names the patch.
- Tests: kit + progress + inbox test files through fleet_suite_gate 605 passed, 1 skipped, 1 expected v19 version pin red (fixed, re-run green); after v20.1 the touched guards 89 passed. New guard tests/test_fleet_kit_v20.py.
- Gated FULL suite: NOT RUN this session (deferred to RC's next session, first item). Drift may read RC OK v20 from the committed HEAD.

## 2. GITHUB-SECURITY-FINDINGS (2243)

Repo has a remote (public). Read via gh api, open alerts:
- code scanning: open before 0 / fixed 0 / dismissed 0 / left 0 (all-time 64: 39 fixed, 25 dismissed).
- Dependabot: open before 0 / fixed 0 / dismissed 0 / left 0 (all-time 51, all fixed).
- secret scanning: enabled, push protection enabled; open before 0, all-time 0.
- Nothing needs the operator. No commit for this order.

## 3. OPERATOR-MARKED-FIXES (2312)

- Item 3 contributors: FIXED by earlier work, read back now: `gh api repos/<owner>/<repo>/contributors` lists only the operator (1 row, type User); a git log scan of the default branch finds 0 bot authors and 0 bot committers. fleet_rewrite.py NOT run: nothing on the default branch to rewrite; rewrite plan id: none, SHA-change count 0. The only bot commits in the local clone sit under local-only backup refs of the earlier rewrite (never pushed); 4 stale remote-tracking dependabot refs were pruned locally (`git remote prune origin`). No workflow commits to the default branch (no git commit/push step in .github/workflows); 0 open PRs. Kit note: `fleet_rewrite.py plan` did not finish in 4 min on this clone when the replace file is present (pickaxe `git log -S` over every ref); not a defect claim, a timing observation.
- Items 1-2 Releases / Deployments (and Packages) on the home page: LEFT. GitHub exposes no REST or GraphQL field for the About "Include in the home page" toggles; it needs the repo settings UI in the operator's signed-in browser. The v0.1.0 release, its tag and the Pages site are untouched. Carried to RC's hand-off as an operator / browser act.

## Commits

6a9711824, cd636d817 (pushed, read back), plus the commit carrying this tracked copy.
