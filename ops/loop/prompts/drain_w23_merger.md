> **RACE GUARDS (FLEET-KIT v12, FLEET-COMMON item 16; MAIN 2026-10-08 2031 ORDER step 5).** Enforced by the kit hook `ops/fleet_kit/fleet_claims.py` (PreToolUse + SubagentStop in the project settings), not by this text.
> 1. Every `git commit` / `git push` runs through the tree's git lock: `python ops/fleet_kit/fleet_gitlock.py run --owner <id> -- git commit -F <tmpfile>` (same shape for `git push ...`). Python code uses `fleet_gitlock.git_lock(dir, owner)`. A bare commit or push is denied.
> 2. A WHOLE suite (pytest naming no test file) runs through the machine-wide gate: `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- <suite cmd>`. A slice that names its test files needs no gate.
> 3. `<id>` is your own claims owner id, `<session_id>.<agent_id>` (`.main` in a main thread); a deny reason names it. The hook also denies an edit, a redirect or a `git add` of a file another live agent holds - leave that file to its agent.

You are the single MERGER for wave @@TAG@@ of an RC drain (repo @@REPO@@, branch main). Inputs (build reports + verifier verdicts): the JSON array in @@MERGE_INPUT@@ (one entry per slice: key, branch, worktree, build, verdict, error).
@@EXTRA@@
Steps:
1. git fetch; fast-forward main to origin/main. Write progress to ops/loop/control/progress/@@TAG@@-merge.json.
2. Cherry-pick ONLY commits whose verifier per_item ok=true (and status done/partial) onto main, slice by slice. Resolve conflicts carefully; if a conflict cannot be resolved safely, drop that commit and list it in dropped.
3. On the merged tree: ruff on changed files, py_compile all changed .py, run repo-wide hygiene/doc guards (tests/test_*hygiene*, tests/test_*ascii*, tests/test_claude_md*, drift guard: python tools/drift_guard.py) and the targeted tests of every merged commit. Do NOT run the full suite locally (OOM); CI is the full gate. Fix or drop breakers.
4. Bookkeeping (you alone own these): append one LEDGER entry per merged row in docs/LEDGER.md (newest-first, renumber after the current top number), mark those rows shipped/closed in ROADMAP.md/BACKLOG.md (keep ROADMAP under its size budget - relocate fully closed rows to docs/ROADMAP_HISTORY.md per existing practice), file any new rows reported (RM-516 for model pins if coach slice did it, then next free ids; update the next-free-id pin in docs/DS_SWEEP_TRACKER.md), and record already_done rows as closed with evidence. Commit with git commit -F.
5. If any merged slice bumped ENGINE_VERSION: run the Share mirror sync and restart DS :8860, confirm /health. If any frozen app/core runtime file changed: echo restart > restart_trigger.txt and read back ops/runtime/health.json (new pid, alive, last_reload_ok).
6. Push: run python tools/sibling_name_sweep.py over the outgoing diff first. If it reports ANY hit, or the diff touches a cross-repo pinned artifact, DO NOT push - set halted_reason. Otherwise git push origin main (pre-push hook runs). Never --no-verify.
7. Clean up merged worktrees/branches of this wave (git worktree remove, branch -D only after git cherry shows patch-equivalent).
Return merged (row ids), dropped (row ids + why), pushed, main_sha, halted_reason, notes (incl. CI run id if visible via gh run list).

HEADLESS ADDENDUM (launcher ops/loop/drain_waves_2_3.py; no operator present):
- Your cwd is the main tree @@REPO@@ on branch main. If `git status --porcelain --untracked-files=no` is not empty before step 1, do NOTHING else: set halted_reason "main tree dirty" and return.
- Step 6 exact form (the hook's own gate, run by hand first): printf '%s\n' "refs/heads/main $(git rev-parse HEAD) refs/heads/main $(git rev-parse origin/main)" | python tools/sibling_name_sweep.py --pre-push origin ; ANY non-zero exit (hit = HALT, DEGRADED, FAULT) = do not push, set halted_reason to the exit code and the slot numbers only (never the matched text). Never set the sweep's bypass variable. Never --no-verify, never force-push.
- Step 7: the slice worktrees live under @@REPO@@\.claude\worktrees\drain-*; `git worktree remove` only (no rm -rf); keep any worktree whose branch still holds a commit that is not patch-equivalent on main, and say so in notes.
- Write your result to @@RESULT_FILE@@ (atomic tmp then replace, ASCII, LF) as one JSON object:
  {"merged": [str], "dropped": [str], "pushed": bool, "main_sha": str, "halted_reason": str, "notes": str}
  required: merged, dropped, pushed. dropped entries are "<row id>: <why>".
- End your final message with the same JSON object on its own (no prose after it). Set your progress status to "done" (or "failed") as your last write.
