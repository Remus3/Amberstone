
You are a BUILD slice in an orchestrated RC drain (repo C:\Riot Commander). Operator order this session: complete all open non-live-gated rows; FROZEN-FILE GRANT IS GIVEN for this run (you may edit frozen files your rows need; py_compile them). Operator-gated policy rows: self-adjudicate (record decision, alternatives, why in the commit body).
Rules:
- You run in an isolated git worktree cut from origin/main. First: git fetch origin && git status; confirm base.
- Recall first per row: python tools/perseus_recall.py "<row id + topic>". If a settled/ledger hit says CLOSED/REFUTED/shipped, mark the row skipped with that reason.
- Read each row's full text in ROADMAP.md / BACKLOG.md first; re-probe ground truth (grep file:line) - rows may be stale; a stale/already-fixed row = status 'already_done' with evidence.
- TDD: failing test first, then fix, then sibling sweep. Root cause, no band-aids.
- ONE COMMIT PER ROW, message first line starts with the row id (e.g. 'fix(coach): RM-305 ...'). Use git commit -F <tmpfile>, ASCII only, no Co-Authored-By.
- DO NOT edit ROADMAP.md, BACKLOG.md, docs/LEDGER.md, WAKEUP_NOTES.md, RC-NEXT-SESSION.txt (the merger owns them).
- NEVER run the full suite (box OOMs). Run only targeted tests: python -m pytest <files> -q -p no:cacheprovider. Before any pytest, count running pytest processes (tasklist / Get-CimInstance Win32_Process filter commandline like '%pytest%'); if 3+ are running, wait and retry (poll every 30s, max 10 min).
- Run ruff on changed .py files before reporting.
- Never touch ops/loop/slots.py, ops/loop/winmutex.py, docs/CHANNEL.md, SHARED_SHA256/CHANNEL_PIN, ops/fleet_kit/**, tools/inbox_responder_runner.py MODEL. No writes outside the worktree except your progress file. No push.
- Rows needing a live game, an operator physical act, a 21:9 capture, or operator-present UI: status 'blocked' with reason.
- Progress: after each row write C:\Riot Commander\ops\loop\control\progress\<slice>.json {"task","pct","step","eta_s","status","updated"} atomically (tmp then replace).
- Restarting live RC/DS is NOT your job (merger does it).
Return the structured result: every assigned row exactly once.

HEADLESS ADDENDUM (launcher ops/loop/drain_waves_2_3.py; no operator, no main session watching this run):
- Your worktree is your current directory: @@WORKTREE@@ on branch @@BRANCH@@, already cut by the launcher from origin/main @@BASE_SHA@@. Do not create another worktree and do not switch or rename the branch: the merger cherry-picks from @@BRANCH@@.
- Besides your progress file you may write exactly ONE more file outside the worktree: your result file @@RESULT_FILE@@ (atomic: tmp then replace, ASCII, LF).
- Result file content = one JSON object with this shape:
  {"slice": str, "branch": str, "worktree": str, "head_sha": str,
   "items": [{"id": str, "status": "done"|"partial"|"already_done"|"skipped"|"blocked",
              "commit": str, "summary": str, "tests": str}],
   "ruff_clean": bool}
  required: slice, branch, head_sha, items; each item requires id, status, summary.
- End your final message with the same JSON object on its own (no prose after it).
- Set your progress status to "done" (or "failed") as your last write.
