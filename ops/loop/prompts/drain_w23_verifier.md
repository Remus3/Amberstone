Adversarial ground-truth verification of an RC build slice. Default to ok=false when uncertain. Read-only: never edit.
Slice report: the JSON object in @@BUILD_RESULT@@ (read it first; if it is missing, every item is ok=false with reason "no build report").
For each item with status done/partial/already_done: inspect the cited commit (git -C "@@WORKTREE@@" show <sha>, or git show <sha> from the repo root since worktrees share objects), confirm the change actually addresses the row text in ROADMAP.md/BACKLOG.md (read the row), confirm a test exists that would FAIL without the fix (reason about it or run with the fix reverted if cheap), re-run the cited tests yourself in that worktree (targeted only; if 3+ pytest processes are already running, wait). Check: ASCII only, no banned glyphs, frozen-file edits py_compile, no edits to slots.py/winmutex.py/CHANNEL.md/fleet_kit/LEDGER/ROADMAP/BACKLOG, no out-of-tree writes. For already_done claims verify the evidence. Report one per_item entry per item (include commit sha). Blocked/skipped items: ok=true only if the reason holds.

HEADLESS ADDENDUM (launcher ops/loop/drain_waves_2_3.py; you are a SEPARATE run from the producer - never trust its claims, re-derive them):
- Slice: @@SLICE@@. Worktree under test: @@WORKTREE@@ (branch @@BRANCH@@). Edit / Write / NotebookEdit are disabled for this run. "Run with the fix reverted" means in a throwaway `git stash` / `git checkout <sha>~1 -- <file>` inside that worktree that you restore before you finish, leaving `git status` exactly as you found it; if you cannot guarantee that, reason instead of reverting.
- The ONLY files you may write (via a python one-liner in Bash, atomic tmp then replace, ASCII, LF):
  1. progress: @@REPO@@\ops\loop\control\progress\@@TASK@@.json {"task","pct","step","eta_s","status","updated"}
  2. verdict: @@RESULT_FILE@@ = one JSON object
     {"slice": str, "per_item": [{"id": str, "commit": str, "ok": bool, "reason": str}], "tests_observed": str}
     required: slice, per_item; each per_item requires id, ok, reason.
- End your final message with the same verdict JSON object on its own (no prose after it).
