# From RC - ANSWER to MAIN 0909: GH-IDENT-REWRITE BLOCKED (RC's own step failed; nothing left the box)

2026-11-01 local. Channel code RC.
TO MAIN. One destination. ANSWER.
HOP: 4

Re 2026-11-01-0909-from-MAIN-ORDER-to-RC-GH-IDENT-REWRITE-operator-ruling-allow-one-force-push-ONE-ANSWER.md (sha256 21bacccba8e38f9d...), 0808 (73d693680f047b95...) and 0038 (3174ebdd35a0f6aa...): verify_main True on all three.

**BLOCKED after the local rewrite, before any lift. The push window never opened. No force push. allow_force_pushes never lifted. The ALLOW ONCE grant is unused. Origin is unchanged.** About 18 minutes of the 150 used; this is not a time stop.

## What failed: RC's error, not a gate

Recipe trap (c) in RM-1265 says delete refs/remotes/* and refs/rw2-backup/* after the bundle and before the run. I piped them all to one `git update-ref --stdin`. It refused the whole batch because refs/remotes/origin/HEAD is a symref to a ref in the same batch, so none were deleted. I had chained filter-repo in the same command with no check between, so it ran with those 22 refs still present. The delete should have been its own read-back step. The rehearsal missed this because its mirror deleted refs one at a time.

The run ended with 39 commits flagged, which the kit CLI treats as a non-zero exit. Per the drive's rule 4 I stopped and took no repair step. After that I only read and measured.

## Exact state, READ BACK

- Origin: main c77c7c8df, tag v0.1.0 071e03cd3, c1/deps-pip-anthropic1-measure 24c54ec39, all unchanged.
- Protection: allow_force_pushes false, enforce_admins true, allow_deletions false. Push protection enabled, secret-scanning alerts 0, contributors 1, open PRs 0, forks 1.
- Local main: 945938817 (was fd49f42f6). Tracked files clean. main's tree equals fd49f42f6's.
- Local refs: filter-repo moved 9 stale origin refs to refs/heads/ and created 2 stray refs/tags/refs/rw2-backup/* tags; refs/remotes/pr/* and refs/rw2-backup/* were rewritten in place; refs/remotes/origin/* are gone. Local tag v0.1.0 was rewritten to f40cdf302 (local only, never pushed). refs/stash 11 -> 12 entries (the duplicate tip the recipe predicted).
- Worktrees: 10 admin dirs moved aside inside .git, NOT restored; the worktrees are not reset. `git worktree list` shows main only.
- The earlier filter-repo state is archived inside .git; the new commit-map is in place.
- Bundle: 60 branch and tag refs, sha256 f762e532dc7484ef, verify exit 0, outside the worktree. It holds the pre-run state, including the refs that were to be deleted.
- Plan 7a345d388b6e. result.json before: 7985 commits, 7981 to rewrite, trigger 7981, ride-along only 0, SHA change 7985. After: 12511, 39, 33, 6, 4478 (it scanned the extra refs).
- Lanes and responder: STILL PAUSED. S144_LANES_STOP and INBOX_RESPONDER_STOP stay in place; the rotator exited cleanly (58 cycles) and is not relaunched. They must not resume in this state: the lane branches are rewritten, the worktrees are not.
- RC's hand-off is NOT updated, because I left tracked files alone. RC-NEXT-SESSION.txt does not describe this state; a new RC session must read this note first. A copy of this note is in .git/fleet-rewrite/s68/ and still owes its docs/_archive copy.

## Measured on this state (none of it authorises a push)

- Identity: the 60 intended refs, 7985 commits, 0 violations; main, 7500 commits, 0 violations. All 39 flagged commits sit on the 11 stray refs and the old pr and backup refs.
- Delta gates, normal range. Before the rewrite, c77c7c8df..fd49f42f6 (includes fd49f42f6): sweep clean, credential 0 + 0 over 1839 lines, identity exit 1 (2 violations, both on 1fc987f2d, non-operator author and committer, the class this rewrite fixes). On the rewritten equivalent: identity exit 0, sweep clean, credential 0 + 0 over 1839 lines. I read the pre-rewrite identity result as the rewrite's target, not a dirty delta; no push rested on that reading, and you may rule otherwise.
- Whole lineage, 945938817 against c77c7c8df: credential exit 2, 87 credential + 834 leak + 661 advisory; every row inside the saved set after mapping through the commit-map, 0 outside, 0 dropped. Sweep exit 2, 32 findings: 0 outside the saved 35, 3 dropped by the rewrite. Identity exit 0.
- `git lfs push` not run.

## The rewritten main is NOT the rehearsed one

I replayed the clean recipe from the bundle in a scratch mirror (.git/fleet-rewrite/s68/mirror.git, 2.4 GB, kept for inspection; no ref of the real repo touched). Clean tip e731b334e; real tip 945938817. Over the 7500 main commits: trees, authors, committers and dates all equal; 689 messages differ, every one only in hex tokens, and the shas differ from there on. Cause not proven: the extra refs fed filter-repo's cited-hash remap is my inference. The clean replay of 9f23bb476 gives ea7b92153, equal to the s148 rehearsal, so the clean path reproduces.

So I did not delete the stray refs and carry on: the ORDER named a fresh plan by the recipe, and 945938817 is not that output.

## What unblocks: ONE reply

- B (recommended): restore every ref from the bundle and the worktree admin dirs' state, delete the stale refs as their own read-back step, re-run the recipe, expect main e731b334e, then gates, window, push and read-back under the same conditions a to g. About 45 minutes. It gives the rehearsed lineage.
- A: keep 945938817, delete the stray and stale refs, re-count, push under a to g. About 25 minutes. Its only measured difference is the 689 message tokens. Not recommended.
- C: restore from the bundle and leave the history as it is.

Please state that the ALLOW ONCE grant stands for the re-run, since condition g limits it to this rewrite. It was not consumed.

## Rows and other items

- Rows 0909 and 0038 closed with outcome BLOCKED, per 0909 (0808 was already closed), so no second worker takes a half-done tree. This drive was the one worker; the inbox tick queued 0909 and started nothing.
- Remote dependency branch c1/deps-pip-anthropic1-measure NOT deleted: it goes with the push. Whole suite: not run (0808 item c). /done: not run, it would move refs; the hand-off item stays.
- Kit gap, report only: fleet_rewrite's mailmap reads branches and tags while filter-repo rewrites every ref and migrates origin refs, so a tree with stale remote-tracking refs gets an unclean after-count with no refusal up front.
