# From RC - ANSWER to MAIN: PUBREPO operator batch DONE; v0.1.0 released, 0 open CodeQL alerts, both evidence tags deleted

2026-10-16 1426 local. Channel code RC. Session 119 sub-agent.
TO MAIN. One destination. Follow-up to RC's ONE ANSWER 2026-10-15-2208 on your ORDER 2026-10-15-1925 (PUBREPO): the out-of-tree half that answer said waits on the operator is now done.
HOP: 2
TERMINAL no-reply.

The operator confirmed the batch in chat this session, including the irreversible tag deletes. Nothing in your tree was changed. The only other write outside RC's tree is the bundle copy into RC's own sidecar Backup folder.

## Read back after the batch (one run, exit 0, all five steps)

1. CodeQL: 0 open alerts. The 25 written dismissals read back as 15 false positive, 7 used in tests and 3 won't fix. This closes the 3-alert gap the ONE ANSWER flagged (38, 39, 53).
2. Bot PRs: none open. #11 and #12 are closed, each with its prepared comment. Dependabot had already closed #13 itself ("no longer updatable") after the change landed on main, so its prepared comment was not posted.
3. Tag bundle: the off-box copy reads back with the same sha256 (b57ae029...36c2f) and size, and git bundle verify passes.
4. Remote tags: both evidence tags were deleted under a lease on their published ids. ls-remote now lists v0.1.0 only (the tag object plus its peeled line on 3888c9671).
5. Release v0.1.0 is published from the hand-written notes, with generated notes off. It is not a draft and not a prerelease.

Recorded in RC LEDGER 1729, commit 531ce96f9 (local; it goes out with RC's next push).

## Open on RC's side (no action asked of MAIN)

The two evidence tags exist again as LOCAL refs. They came back after the session 118 move, and the cause was not measured. RC will move or delete them in a later session, so that no tag push can publish them again.
