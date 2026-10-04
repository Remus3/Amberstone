# ADR-017: Git hooks run the CHECKOUT'S OWN gate tools (worktree-relative), as a documented exposure

**Date:** 2026-10-04
**Status:** Accepted (closes RM-432 by decision; self-adjudicated under the 2026-10-04 drain order)

## Context

`core.hooksPath` is absolute and lives in the shared `.git/config`, so every
worktree runs the PRIMARY tree's `.githooks/` scripts. Those scripts resolve
the tools they call with `git rev-parse --show-toplevel`, so in a worktree the
verdict is decided by THAT worktree's copy of `tools/precommit_gate.py`,
`tools/sibling_name_sweep.py`, and so on - uncommitted edits included. RM-432
measured it with controls: a neutered worktree gate tool let an em-dash commit
land.

Alternatives considered:

- **(a) Fixed path.** Hooks call tools from the main working tree, resolved via
  `git rev-parse --git-common-dir`. A lane could not weaken the gate by editing
  its own copy.
- **(b) Keep worktree-relative resolution and record the exposure.** (chosen)
- **(c) Run the tool from the committed `HEAD` blob** (`git show HEAD:tools/x`).
  Rejected: a lane can commit a neutered tool once and every later commit uses
  it, so it moves the hole by one commit without closing it, at the cost of a
  temp-file extraction on every hook run.

## Decision

Keep (b). Hooks resolve gate tools from the checkout that is committing or
pushing. The exposure is recorded here, not closed.

Why (a) was not taken:

1. **It does not create a boundary a lane cannot cross.** Every hook is already
   skippable with `--no-verify`, and a lane runs with the same account and the
   same write access to the main working tree that (a) would trust. (a) stops
   ACCIDENTAL neutering in a worktree only - and the main working tree's copy is
   just as editable, so the fixed path is not a fixed TRUST root.
2. **It breaks the normal way a gate tool changes.** A slice that edits a gate
   tool (this drain's RM-492 wired a new pre-push scan; RM-399 wired the sibling
   sweep) must exercise its OWN copy before merge. Under (a) a slice's commits
   would be gated by the OLD tool and its change would first run on the merged
   tree, after the commit that introduced it - which is the opposite of
   test-first.
3. **The authoritative backstop is already merge-time, not commit-time.** Slices
   are cut from origin and repo-wide guards run on the MERGED tree before push
   (memory `feedback_parallel_slices_merge_time_guards_and_origin_base`), and CI
   runs the suite and the tree-arm sweep on what is pushed. A worktree-local
   neutered tool cannot survive those unless the neutering is itself merged,
   and a merged change to a gate tool is a reviewed diff.

## Consequences

**Good:** gate-tool changes are exercised by the commits that make them; no
extraction or path magic in `.githooks/`; no change to what gates a push.
**Trade-off:** a worktree's commit-time gate is only as strong as that
worktree's copy of the tools. "The hook passed in a lane" is evidence about that
lane's tools, not about `main`'s.
**Watch for:** a merger must treat any diff under `tools/` that a hook calls
(`precommit_gate.py`, `sibling_name_sweep.py`, `credential_history_scan.py`,
`stop_claim_gate.py`) as a gate change and review it as one. Reverses if: lanes
gain a write-scope boundary that makes the main working tree genuinely
read-only to them (then (a) becomes a real trust root and should be revisited),
or a neutered-tool commit is measured surviving the merge-time guard run.
`tests/test_hook_tool_resolution_adr017.py` pins the resolution this ADR
describes, so a hook edit that changes it fails until this record is revised.
