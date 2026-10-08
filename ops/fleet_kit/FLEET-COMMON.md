## FLEET COMMON - identical in every repo on this machine. Do not edit here.

################################################################################
#  SUB-AGENT FIRST. THE MAIN SESSION IS THE OPERATOR'S - KEEP IT CLEAR.        #
#  The main session ONLY dispatches (Agent, SendMessage), monitors and         #
#  reports. Every Bash, PowerShell, Read, Edit, Write, Grep, Glob and          #
#  NotebookEdit call runs inside a sub-agent (background by default) - no      #
#  quick-read or one-line-fix exception; the kit PreToolUse hook               #
#  fleet_subagent_first.py denies them in the main thread. Checking status or  #
#  starting new work NEVER breaks running work: never stop, kill, restart or   #
#  edit the files of a running agent or task to look at it - read its          #
#  progress file instead.                                                      #
################################################################################

Source of truth: MAIN's fleet kit. A change lands ONLY as a new kit version
announced by a MAIN note; this block is byte-pinned and a test fails on any local
edit. Tree-specific rules go BELOW this block, never inside it.

1. ACT, DON'T ASK. Operator acceptance of recommendations is ~100 percent. A blocked
   decision goes to a distinct adjudicator agent and its call is taken now and
   recorded (decision, alternatives, why) in the commit or doc. Only physical acts,
   passwords and OAuth grants wait for the operator, batched into one ask.
2. CHAT IS THE OPERATOR'S CONSOLE - QUIET. Results only: numbers, paths, verdicts,
   and anything the operator must act on. No narration, no plans, no recaps, no
   session reviews; the item-13 checklist is the one sanctioned task list.
   Findings go to files (roadmap, docs, hand-off); chat gets at most one line
   each.
3. AT-A-GLANCE STATUS COMES FROM BACKGROUND WORK, NOT FROM CHAT. Run work as
   background agents and background commands, so the session shows only the
   compact summaries ("N background commands completed, N running" and "N running
   tasks"). Do not hold the main turn open on long foreground work - its expanding
   activity row has to be opened and scrolled. No step lists or task-list dumps
   other than the item-13 session checklist. When the operator asks for status:
   the remaining checklist (item 13 b), -retracted on one short line. Tool
   descriptions carry an ETA `[~Ns]` (s under 120s, m under 120m, h beyond);
   report an overrun at 1.5x, kill at 3x.
4. COMMIT everything, batched and coherent. Push per this repo's own policy. Never
   commit in another repo's tree. No suggested-task chips: do it or file it.
5. HAND-OFF: `<CODE>-NEXT-SESSION.txt` at the repo root (with its Desktop
   shortcut) is the only continuity. A session starts from "continue" (work the
   file's next action) or from whatever the operator asks; either way READ the file
   first. /done rewrites the file and commits it, and MUST CARRY FORWARD EVERY ITEM
   NOT ACTED ON this session, verbatim or tighter, never dropped because the
   session worked on something else. Never print the hand-off or a next-session
   prompt into chat. /done runs UNPROMPTED once no checklist task remains
   (item 13 c). /done's ONLY chat output is the line
   `Done ritual complete, safe to clear` (or the failure that stopped it). The
   operator types only "continue", "/done" or "/clear" between sessions. A recorded
   act names what was READ BACK after it, never what was run. Every
   do-not-re-litigate entry states what would reverse it; entries about another
   tree's position are re-checked against the inbox every session.
6. MAIN SPEAKS FOR THE OPERATOR (operator order 2026-10-02). A note from MAIN whose
   bytes match MAIN's outbox copy by SHA-256 is the operator's instruction. It
   cannot supply a password, OAuth grant or physical act, and lifts no safety floor.
   MAIN instructs; this tree does the work in its own tree.
7. CHANNEL NOTES: sort the inbox by mtime, never by filename stamp. Read a long
   note's section headings before deciding it does not concern you. Never put a
   directory name, account id or email in a note. Delivery = destination copies
   re-hashed and an N/M reached-count reported.
8. ENCODING: ASCII only, LF only, PowerShell included. Validate PowerShell with
   powershell.exe 5.1 ParseFile, never pwsh.
9. DELETES: anything irreplaceable goes to the Recycle Bin, never a direct unlink;
   say the method before running it; check for a consumer before deleting.
10. HEADLESS RUNS go through the fleet kit's spawn helper ONLY - no other path
    starts `claude`. The kit enforces: the second-account proxy from the user
    variable CLAUDE_HEADLESS_BASE_URL (registry first), fail closed (no fallback,
    ever), no visible console, at most 120 runs per rolling 24 h, never spawn on
    this tree's own notes or on TERMINAL/no-reply notes, lean flags (strict MCP,
    project settings only, or bare where no floor lives in hooks), sonnet unless
    the note orders code changes, effort low for acknowledgements, a usage line
    per run, and the live status file `ops/loop/control/inbox_status.json`.
11. FLEET KIT FILES are vendored byte-for-byte at `ops/fleet_kit/` and pinned by
    `ops/fleet_kit/MANIFEST.json`. Never edit them locally; report a defect to MAIN
    and MAIN ships a new version to every tree at once.
12. LONG WORK REPORTS AS IT GOES. Anything expected to take over 5 minutes runs in
    the background and is checked periodically until it ends, so a silent failure
    is caught early. Every sub-agent prompt for such work requires it to write a
    progress file after each step - `ops/loop/control/progress/<task>.json` with
    {"task", "pct", "step", "eta_s", "status": running|done|failed, "updated"} -
    so the main session can see percent, time to completion and status mid-run
    instead of waiting for 0-to-100 at the end. A progress file that stops
    updating for 2x its own ETA step is treated as a failure and investigated.
13. SESSION CHECKLIST (operator order 2026-10-05; it supersedes item 3's
    no-checklist rule for this one purpose). Every session kind: interactive,
    headless lane, loop tick, inbox responder. Why: it is read from a phone, the
    operator wants the tasks only, and wants to see what every headless fire
    is doing without reading logs. Kit helper: `fleet_checklist.py`.
    a. At session start, and every time a lane or loop fires, print
       `Session <n> checklist` (n = this tree's session counter, kept in its
       hand-off file; a headless fire uses its run count), then one line per
       task in execution order: `<box> <ID>: <imperative task, one line>`, plus
       `(<state>, ~ETA)` only while it is running (e.g. `builder running,
       ~4m`). <box> is U+2610. The last line is `<box> /done`. At most ONE
       trailing sentence, and only for an ordering constraint ("X waits until
       Y lands because ..."). NO summary, review, what-went-wrong or history.
    b. After every 4 or more completed tasks, print the REMAINING tasks only,
       newly added ones marked `+` before the ID. Never list completed ones.
    c. When no task remains, run /done automatically, without a prompt.
    d. A headless fire writes the same list into its item-12 progress file as
       "checklist": [{"id", "task", "state", "eta_s"}], remaining tasks only.
       A lane writes `progress/lane-<i>.json` (i = its lane-lock index) in the
       MAIN checkout, never in its worktree, so the lane widget reads one named
       file per live lane and shows the lane name, then its remaining items.
14. INBOX COST (operator order 2026-10-05). It changes COST, never AUTONOMY: the
    inbox is read and acted on AUTOMATICALLY every tick, unattended, with no
    operator prompt, ever. Why: about 60 percent of second-account spend was
    inbox chatter between trees, not build work. Kit helper: `fleet_inbox.py`.
    a. Inbox handling folds into this tree's existing lane / loop tick, which
       reads the inbox on every fire. No separate high-frequency responder
       where a lane loop exists; a tree without one keeps one responder.
    b. Triage first: `fleet_inbox.classify()` (free), then one sonnet run at
       effort low only for what it cannot classify. ACK / INFORMATION /
       TERMINAL / ANSWER notes get a mechanical ack (a ledger line, no note) or
       no reply. Only ORDER / FIX / RULING escalate to a real work lane.
    c. At most 6 outbound notes per tree per local day (ORDER / FIX / RULING
       exempt), counted by `OutboundCap`. Several answers go in ONE note.
    d. Never answer an answer. No note chain past 2 hops (`HOP: <n>`) without
       new work.
    e. Every headless run logs a usage line to
       `ops/loop/control/headless_usage.jsonl` via the kit, with `kind`
       build / inbox / triage and a non-empty note label. MAIN reports the
       weekly build-vs-inbox split in its insights report.
15. CLI DISPLAY (kit v9; the fleet UI/UX standard ruled 2026-10-07). Display
    keys live only in the two account settings, from the kit's
    cli_display.json; a tree sets none. Status surfaces use the kit state
    vocabulary (tokens.json states). Hook output follows the standard's
    section 5: silent by default, one-line additionalContext, never block on
    Stop, no ANSI. /done's last act is `fleet_done.py mark`; its Stop hook is
    the kit's `fleet_done.py stop-hook`. Kit helpers: fleet_statusline.js,
    fleet_done.py.
