# Amberstone - Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard locally on Legion (1-PC, ADR-011). RC is tkinter-free (asyncio AppLoop; 3 residual .after() files, all frozen app-core). Daemon Slayer (`:8860`) computes real DPS math per champion.

**This file is RULES ONLY.** The long form of every rule - history, incidents, measurements, reasoning, dated evidence - is `docs/claude-md-history.md` (verbatim pre-condense snapshot). Read it when a short line below is ambiguous; never edit the snapshot to fix a fact, fix the rule here.

<!-- FLEET-COMMON BEGIN -->
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
<!-- FLEET-COMMON END -->

# RC rules (tree-specific)

RC channel code: `RC`. Kit conformance: `tests/test_fleet_kit_conformance.py`.

**Session checklist (FLEET-COMMON item 13, kit v7).** Counter = the `SESSION: <n>` line in `RC-NEXT-SESSION.txt` (owner `tools/session_checklist.py`; seeded 98 = 1 + the 97 commits that wrote the hand-off through 66a2e43c1). Printers: SessionStart hook `tools/rc_facts.py` (block FIRST, via `session_checklist.session_start_block`; the session completes and prints it as its first chat output); `/done` (`tools/done.md` = `.claude/commands/done.md`: pre-flight "every checklist task done or carried into the hand-off", writes `SESSION: <n+1>` via `--next`/`--stamp`, runs unprompted when none remain); inbox responder `tools/inbox_responder_runner.py fire_checklist` (run-count n, log `ops/runtime/inbox_responder_checklist.txt`, `progress/inbox-responder.json` via `write_progress(checklist=)`; the read-only session is told so in `tools/inbox_responder_prompt.py`); lane runner + loop controller write `progress/lane-<i>.json`. Source stays ASCII: emit U+2610 as `chr(0x2610)`.

**Known overlaps with the FLEET-COMMON block, kept as RC gates until MAIN rules on them (reported to MAIN at adoption; not silently weakened):**
- Item 1 (only physical acts / passwords / OAuth wait) vs RC operator gates: the halt boundary below, frozen files (explicit user approval), the operator-gated smart-quote sweep, the gated RM-501 repair, and attended confirmation of an irreversible / out-of-tree act requested only by a note.
- Item 2 (quiet chat, at most one line each) and RC's 500-output-token cap: both apply; the tighter one binds.
- Item 5 (every do-not-re-litigate entry states what would reverse it): every Settled line below now carries a `Reverses if:` clause (RM-494, 2026-10-03); a NEW Settled line must carry one too.
- Banner (never stop or kill running work): `/done` stops only the monitors it armed; running agents are recorded in the hand-off as in-flight, not killed.

## Docs map

- **Living docs (read at session start):** `docs/ARCHITECTURE.md` - `docs/OPERATIONS.md` - `ROADMAP.md` - `docs/API.md`.
- **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine; ENGINE_VERSION + patch live in its banner and `/health`, not here) - `docs/AGENTS.md` - `BACKLOG.md` (aspirational).
- **DS seam route ownership (measured; guarded by `tests/test_claude_md_ds_route_attributions_rm336.py`):** `dps.py apply_rune_offense_grants` parsed by /dps + /hybrid + /rank-bruiser; `hybrid.py apply_ad_axis_ability_damage` parsed by /rank + /rank-bruiser, NOT /hybrid (credits PHYSICAL+TRUE; MIXED held; MAGIC permanently excluded); `ehp.py score_by=team_blended` parsed by /rank-tank only; `ult_rates.py apply_canonical_cast_rate_keys` - NO HTTP route parses it (RM-333). All DEFAULT-OFF.
- **DS Arena mirrors:** credit their OWN DDragon stat line (R161 doctrine B), but DDragon carries no proc MAGNITUDE for burst mirrors, so the row's own `note` is the authority - doctrine B is NOT a licence to zero a mirror out (RM-323).
- **ADRs:** `docs/adr/README.md` - check it before re-litigating a past choice.
- **Dated artifacts** live in `docs/_archive/` (excluded from ripgrep).

## Topology

- Legion is the ONLY box (1-PC, ADR-011): League + Vanguard + RC + supervisor + vision + dashboard + OBS. Agents RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener run local as ONLOGON tasks.
- Canonical name: Tailscale `legion-rc` / `100.70.22.55` (LAN `192.168.8.230`), tailnet `tailc150de.ts.net`. Prefer tailnet hostnames.
- NEVER record the Windows computer name (it is re-rolled). Probe `$env:COMPUTERNAME` live; never reconcile MagicDNS to it. `hostname` returning `LEGION-RC` is expected to differ.
- Peer machine row is history only (bridge decommissioned, ADR-012).
- Vision in-process at `127.0.0.1:8889`. Game host is config: `core/game_host.py` `RC_GAME_HOST` (default `127.0.0.1`) for Live Client `:2999` + LCU.

## Cross-repo channel and byte pins

- Sibling names/paths are per-host CONFIG only: gitignored `ops/moon_sync_repos.json` (template `ops/moon_sync_repos.example.json`; `RC_MOON_SYNC_REPOS` overrides). Never write a sibling name or path into a tracked file.
- Spelling traps: a checkout path may hold a REAL SPACE where its GitHub name uses a hyphen (on purpose); always QUOTE such paths (`-File C:\Some Sibling\x.ps1` unquoted fails silently).
- Channel = gitignored `moon_sync_inbox/` in each repo root: WRITE into the sibling's, READ your own. Do not invent another channel.
- `ops/loop/slots.py` + `ops/loop/winmutex.py` are BYTE-IDENTICAL-BY-CONTRACT, pinned by `SHARED_SHA256` in `tests/test_loop_concurrency.py`. Re-pin is a JOINT act: never regenerate digests from local disk; copy the sibling's file BYTE-level, never `write_text`.
- Pin carriers: RC + Sibling-A + Sibling-B. Sibling-C is archived - never chase its digest. The newest participant vendors last.
- `docs/CHANNEL.md` is pinned on LF-normalised bytes by `CHANNEL_PIN` in `tests/test_channel_doc_pin.py`; re-pin is a five-way act.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID`.
- **Commit messages:** `git commit -F <tmpfile>` (ASCII) or a single-quoted here-string; never double-quoted or piped. `tools/precommit_gate.py` blocks banned glyphs + net-new ruff.
- **Never add a `Co-Authored-By: Claude` trailer, and never file its absence as a defect** (`.githooks/commit-msg` strips it, operator policy 2026-06-03). Audit with an ANCHORED predicate on the message tail.
- **Git hooks are the AUTHORITATIVE gate; a fresh clone has NONE.** First action in a fresh clone: `python scripts/install_hooks.py`. Claude hooks are defense in depth only.
- **Hook findings are version-specific and expire - re-measure, never inherit.** Before concluding a hook did not fire, rule out (1) invalid `settings.json` (single-backslash paths) and (2) an untrusted workspace (trust key is per path STRING). Presence is not proof; the only valid test is end-to-end (stage a banned glyph, commit, assert HEAD unchanged). Memory `reference_git_hooks_authoritative_and_traps`.
- **Restart via `restart_trigger.txt`** (supervisor restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`.**
- **State assumptions explicitly before coding.**
- **No em-dashes or en-dashes, no smart quotes - ever.** 7-bit ASCII in all authored text incl. chat. Use ` - `. (Why: PS 5.1 ANSI-decodes no-BOM `.ps1`.) Em/en purge done (`tools/strip_em_dashes.py`; the `"-"` no-data sentinel is operator-approved); smart-quote retro-sweep NOT done (operator-gated). Not swept: `*.log*`, `docs/_archive/**`, `.jsonl`, binaries.
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/diagnose.md`, `tools/caveman.md`.

## Restart workflow

`echo restart > restart_trigger.txt`, then read `ops/runtime/health.json`: new `pid`, `alive=true`, `last_reload_ok=true`. Fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Third-party lift: license gate

Before lifting ANYTHING external, check the license and say what it is.
- A repo can contradict itself (LICENSE vs `package.json`): read both.
- Whoever cleared it may not own it (credited prior authors = multiple holders).
- A LICENSE can name NOBODY (unrendered template): read the copyright LINE. Also watch truncated licenses, commented-out manifest declarations, and `NOTICE` files naming adapted upstreams.
- BUSL-1.1 = DO-NOT-VENDOR.
- The WRAPPER does not clear the PAYLOAD: enumerate marks, icons, fonts, sample data and committed binaries. RC is Apache-2.0 and PUBLIC, so NC / SA assets cannot be absorbed. The trap is licence-family INDEPENDENT.
- A licence audit and a behaviour audit are DIFFERENT audits; enumerate EVERY top-level directory for both. An empty grep is a claim about your pattern. Do NOT write "audit the tarball, not the repo" (refuted).
- GPL/copyleft stays DO-NOT-VENDOR regardless of verbal clearance. Always-legal path: re-implement from observed behaviour.

## Memory recall (Perseus Vault)

- Local store at `~/.perseus-vault/`, MCP server `perseus-vault`. A fresh clone has NO wiring: `perseus-vault connect --client claude-code --hooks`, then sync.
- **BEFORE any non-trivial item, recall first:** `python tools/perseus_recall.py "<task>"`. A `settled` / `ledger` hit saying CLOSED / REFUTED / shipped = stop and report.
- Recall through that tool, not raw `perseus_vault_recall` (returns bodies twice).
- Take a `key` from the listing and fetch that ONE entity when you need a body.
- It is a MIRROR, never the source of truth: never fix a fact only in the vault. Re-sync after changing CLAUDE.md / `memory/*.md` / LEDGER / ROADMAP / BACKLOG: `python tools/perseus_sync.py`; coverage: `--verify`.
- `status: healthy` is NOT proof recall works; only `embedded == active` is.

## Session workflow and hand-off

- Scoped sessions: one focused task per session; `/clear` between Tier items, modes and focus areas.
- **Start:** READ `RC-NEXT-SESSION.txt` first (on "continue" or any other ask), then bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md`.
- **Session-End Ritual** (`wrap` / `/done` / `end session`; procedure in `tools/done.md`): audit pending changes, run tests, commit, push, append the per-item entry to `docs/LEDGER.md` (never CLAUDE.md), update ROADMAP/README, keep `WAKEUP_NOTES.md` to the last 2-3 sessions (older to `docs/history_notes.md`), process lessons into memory, rewrite the hand-off, record the CI result in it. Run independent steps in parallel. No banner, no review: the ONLY chat output is `Done ritual complete, safe to clear` (or `/done stopped: <reason>`).
- **The hand-off file is `RC-NEXT-SESSION.txt` in the REPO ROOT, TRACKED, and the write is UNCONDITIONAL.** Overwritten whole each /done, never appended, dated or duplicated, and it CARRIES FORWARD every item not acted on this session. Never print it or a next-session prompt into chat. `Desktop\RC-NEXT-SESSION.lnk` is only a shortcut - do NOT write to the Desktop. `NEXT_SESSION_PROMPT.md` is RETIRED - do not recreate it or file its absence.
- Do NOT probe the retired Peer bridge at wrap.
- Keep individual chat responses under 500 output tokens.

## Execution Efficiency & Tooling Rules

These govern HOW a step runs; the SHAPE of work is set by "Session Default" below, which wins on conflict.
- **R1** Files = Read / Edit / Write / Grep / Glob only. No Bash-mediated WRITES to tracked files (`tools/stop_claim_gate.py` reads them as unbacked claims); if you did, back the claim with `git show <sha> -- <path>`; never fabricate an Edit.
- **R2** Runtime state via `curl -k https://127.0.0.1:8888/api/...` or `ops/runtime/health.json`; never screenshot to read a number.
- **R3** Visual tools only for rendered-pixel / layout checks and live-game capture; the UI-audit ritual + game-monitor are the sanctioned visual uses.
- **R4** Prefer built-in tools; shell = absolute paths, one compound command.
- **Tiers:** Tier-0 cosmetic = Edit + `py_compile` (no suite, no restart). Tier-1 one module = `py_compile` + that module's tests. Tier-2 schema / engine / scorer / item-effect / `ENGINE_VERSION` = full dual suite + DS `:8860` restart + Share mirror.
- **R5** Classify every change into a tier; run only that tier. **R6** Run a suite ONCE; re-run only if edited since or the pipe glitched.
- **R7** Adversarial verification is the DEFAULT: every substantive claim gets an independent verifier / refutation pass before "done" (Tier-0 exempt).
- **R8** Never re-Read a file just Edited. **R9** Multi-agent is the default shape; substance decides, not file count. **R10** Batch independent reads. **R11** No screenshot ritual for backend / version / doc changes.
- Hooks: PostToolUse `tools/pytest_guard.py` is py_compile-only (`RC_FULL_SUITE=1` for Tier-2); PreToolUse `tools/text_first_guard.py` denies screen-text readers (escape hatch `ops/runtime/allow_visual.flag`).

## Session Default

Every session is **orchestrated + multi-agent + self-adjudicating + self-adversarial** (operator 2026-07-30; restated 2026-09-09: "sub-agent first to keep main session quiet and clear, always"). Choosing it needs no justification; departing from it does.
- The main window is the OPERATOR'S surface: main holds plan, merge, gate and report - never the doing. "It is faster inline" is not a reason.
- Orchestrated: one merger, disjoint slices decided before work starts. Multi-agent: parallel, worktree-isolated where they write. Self-adjudicating: the producer never grades its own output. Self-adversarial: done-claims get a refutation pass defaulting to refuted; agreement between agents is not evidence.
- Only exception: genuinely trivial work (one-line cosmetic, typo, single string, conversational answer).
- Spec first, verified against ground truth (grep file:line, live `/api/state`, health.json, git) before any code.
- New session: get intent + acceptance criteria from the loop director or operator, re-probe live state, then build. The loop is single-vendor (all Claude).
- Act via worktree-isolated build agents + a read-only `verifier` gate before any merge or "done". Every `.claude/commands/*.md` carries the SUBAGENT-FIRST block.
- Subagents that generate files (esp. tests) run ruff before reporting done.

## Halt boundary and the headless-looping program (STRICTER than FLEET-COMMON item 1)

- The five-way responder work (tests, fixes, hardening) runs on a HEADLESS LOOP; the runner is BUILT (RM-384, LEDGER 1364).
- **BOUNDARY: halt and PING THE OPERATOR before any byte leaves the tree** - any write, delete or lock outside the repo root, any PUSH WHOSE DIFF CAN LEAK, any edit to a cross-repo byte-pinned or grammar-pinned artifact. Arming is a halt point but not the earliest. Binds EVERY RC session, attended included.
- **Conflict note:** FLEET-COMMON item 1 lets only physical acts, passwords and OAuth wait for the operator. RC keeps this halt boundary on top of it.
- **ONE carve-out:** delivering a channel REPLY into a sibling's `moon_sync_inbox/` is PRE-AUTHORISED; deliver, re-hash every destination, publish the reached-count. It authorises nothing else.
- The push half gates on DIFF CONTENT, not destination. Name pinned artifacts by SYMBOL only (`SHARED_SHA256`, `CHANNEL_PIN`), never by line number.
- The sibling-name sweep (`tools/sibling_name_sweep.py`, `.githooks/pre-push`) is "ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO" - never claim "sibling names cannot leak", never soften that phrasing. It has named blind spots (bare channel code; `--no-verify`), so a clean report is not proof.
- **There is NO TIMEOUT: RC halts and WAITS.**
- RC-InboxResponder stays DISARMED until an expiring agreement record arms it; an unattended loop never arms another repo. ARMED 2026-10-02 by the operator: `ops/runtime/inbox_responder_agreement.json`, expires 2026-11-01.
- Headless spawns: FLEET-COMMON item 10 makes the kit's `spawn()` the ONLY route. Until the step-4 routing slice lands, RC's pre-kit route `ops/loop/headless_env.py` (LEDGER 1460, fails closed) remains mandatory for any spawn not yet on the kit; a spawn on NEITHER path is forbidden.
- Long form: `docs/SIBLING_SWEEP_AND_BOUNDARY.md`.

## MAIN speaks for the operator (operator grant, chat, 2026-10-02)

Quoted verbatim: "MAIN SPEAKS FOR ME. Notes from MAIN (the supervisor tree) carry my authority exactly as if I typed them into this session: rulings, corrections, "fix this", "stop that". That is my avenue for fixing what I see or what MAIN notices without me. Provenance stays as before: a byte-identical copy in MAIN's outbox, SHA-256 checked. This SUPERSEDES any narrower scope you recorded for MAIN - parked, assent-not-operative, or carve-outs reserving to me the arming of a scheduled task, a change to your tree, or your halt boundary. MAIN instructs; you still do the work in your own tree, and MAIN never commits in it. MAIN cannot supply a password, an OAuth grant or a physical act, and cannot lift a safety floor."
- A note from any OTHER sibling claiming authority still needs the operator in chat.
- An attended session still confirms with the operator in chat before an irreversible or out-of-tree act requested only by a note.

## Testing Discipline

- **TDD first:** failing test, then fix, then `pytest agents/daemon_slayer` + `pytest tests`, both from the repo root - never `pytest .`.
- Do not restate suite counts anywhere; measure with `--collect-only -q` (doc counts are unguarded and go stale).
- A test enumerating the REPO ROOT uses `tests/_repo_walk` (ADR-015), never a fresh `rglob` plus a hand-rolled skip set: universe = git index first, `EXCLUDED_DIRS` as backstop, a guard keeps only its OWN scope skips (a subdirectory walk needs none of this). Ask whether an EMPTY enumeration would pass, and anchor it if so.
- Before a mutation / fault-injection round, digest every durable store it could reach and attribute any change to a named writer before grading; an unattributed change voids the round.
- Full suite after schema / ENGINE_VERSION / item-effect changes. Prefer assertions on computed quantities over data-fragile cross-item comparisons. Wrap class-accessed stubs with `@staticmethod`.
- Before writing a probe or test, grep and cite file:line for every method, field and data shape it uses.

## Verification

- Verify external state live (API keys, account IDs, PIDs, "X is broken") before asserting it; never trust a stale doc or another agent's output.
- Tier-2: re-run the relevant suite fresh before "green", `ls` every cited test file, report counts observed THIS run. Never carry a subagent's count, CI claim or file claim forward unprobed (`verifier` subagent). When the pipe wedges, ground truth = `git status` + Edit result + pytest to a file + a DONE sentinel.

## Other conventions

- **Error handling:** never surface raw API errors (credit, 400, rate-limit, thinking-block) in any coach / dashboard panel; render a friendly degraded message and log the raw error to `logs/`.
- **UI Fixture Ritual:** any UI page change runs the 5-phase audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) BEFORE commit; every MUST-FIX resolved in the same slice.
- **Python:** a new required dataclass field goes at the END with a default.
- **Data fixes:** not done until already-corrupted rows are backfilled and verified live, in the same fix.
- **Engine / build:** validate champion-specific fixes per champion; grep sibling cases (champions, modes, duplicate build paths) and test each, root-cause first. Narrow a proc/effect fold from the tightest set, with a test that unrelated proc types are excluded, before widening.
- **DS batch workflow:** next batch from ROADMAP, schema/engine change, tests green, bump engine version, commit + push, verify live, hand-off. Wait for Share mirror sync + DS `:8860` restart to settle before launching a suite.
- **Windows:** Claude Desktop may be an MSIX install (`%LOCALAPPDATA%\Packages`). Background daemons use `pythonw.exe`; every console-subsystem child of a windowless parent needs `creationflags=CREATE_NO_WINDOW`. Keep runtime records under the repo root (AppData is MSIX-virtualised).

## Runtime reference

- **Dashboard:** `web_dashboard.py` at `:8888` HTTPS; endpoints `/`, `/api/state`, `/api/health/all`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed at `https://legion-rc:8888/`; design baseline 1920x1080 WITH Chrome chrome (~1920x920 viewport); `main` flex-grows (no layout pinned to 1280). Cert: `tools/regen_rc_cert.ps1`. Per-host Anthropic key names are NOT recited here.
- **Scheduled tasks:** `RC-Supervisor` (logon, Administrator, HIGHEST). Vision has NO task; `dashboard/server.py` self-heals `:8889`. Full list: `docs/OPERATIONS.md`.
- **Vision:** `screen_agent.py` POSTs frames every 2s to `:8889/upload-frame`; coaches read `:8889/latest-frame`. `_run_vision()` gates on `_fetch_game_data() is not None`. Tiered: OCR first, Sonnet for misses; calibrate `data/vision_regions.json`. Live Client relay self-heals in-process when stale and `GAME_HOST` is local.
- **Mode detection:** `game_reader.py._process_game()` -> `core/game_snapshot.py`. ARAM Mayhem (`KIWI`) -> `MODE_ARAM`.
- **Current state:** health/PID `ops/runtime/health.json`; game `data/{aram,arena,brawl,tft}_coaching_data.json`; activity `logs/YYYY-MM-DD.log`; commands `docs/OPERATIONS.md`.

## Active priorities

Per-item completion ledger relocated to `docs/LEDGER.md` (append-only, newest-first). NEVER append item-ledger entries here (CLAUDE.md is CI size-budgeted < 60KB); touch CLAUDE.md only for rule / frozen-list / Settled changes. Open work: `ROADMAP.md` + `BACKLOG.md`. Recent sessions: `WAKEUP_NOTES.md`. Deep archive (items 1-324): `docs/history_notes.md`.

### Settled - do not re-litigate (long form of each line: `docs/claude-md-history.md`; items 1-149: `docs/history_notes.md`)

Shape (RM-494, FLEET item 5): every line is the RECORD of a measurement at a date, not a live check - this block has itself carried three fences that were false when written (brawl-deadcode, "audit the tarball", the `KNOWN_EXCEPTIONS` fence). Each line therefore ends in `Reverses if:` naming the observation that re-opens it. Meeting a reversal condition re-opens the question for a measured re-check; it is NOT a licence to delete the fence, and a fence is never deleted for lacking a live defect.

- **Phases 1-7, 2.1-2.4, 3, 4-6, FU01/FU02/FU04 shipped; the 6-scorer archetype plan is fully wired, no fallbacks.** Do not re-plan or re-pitch a scorer. Reverses if: a scorer is measured at HEAD returning a fallback / unwired result, or the operator orders a new archetype.
- **DS conditional-target-state arc is operator-CLOSED (s232); Part-2 live target-state plumbing is shelved permanently.** Do not re-pitch or re-scan. Reverses if: the operator (or MAIN) re-opens it in writing.
- **DS block_index / form_index / max_priority / combo_sequence registries are provably saturated (machine-guarded).** Growth needs a schema lift. Never `--force` a Meraki re-extract. Reverses if: a schema lift lands (growth resumes under the new schema) or the saturation guard is measured passing on a non-saturated registry.
- **Meraki is NOT the source for item PEN / LETHALITY / resist-reduction MAGNITUDES (DDragon `<stats>` only), and `aram_modifiers` is LOLMATH-sourced, not Meraki.** Meraki stays correct for item PASSIVE FORMULAS. Reverses if: DDragon stops carrying `<stats>` magnitudes, or a live-client comparison measures DDragon wrong where Meraki is right.
- **AUTONOMOUS_AUDIT s5 menu is exhausted.** No effects.py re-merge, no `__all__`, no FastMCP/SDK rewrite of the stdlib MCP servers. Reverses if: a later audit files a NEW menu with a measured defect (this closes the s5 menu only).
- **ARAM Mayhem reports queueId 2400 (item 87); the phase-driven view-router is proven correct.** Do not re-pitch a router change; `cs.is_aram` path is preserved. Reverses if: a live game reports a different Mayhem queueId, or the router is measured misrouting a live game.
- **The augment LCU / :2999 API is a confirmed dead-end; augment-OCR is the path.** Reverses if: a live probe after a Riot patch finds augment data on an LCU or :2999 endpoint.
- **`core/build_order.py` no-double-unique rule is engine-authoritative - no family map** (a guard fails on any family literal). Reverses if: the engine's unique-group data is measured wrong on a real build (fix the engine data, still never a family map).
- **Research-list CLOSED negatives:** LCU client/codegen repos inferior; LCU endpoint catalog reference-only (verbal clearance only, no LICENSE - not permission for any other repo); no Arena/Cherry/Mayhem lobby-create payloads in the corpus; `.rofl` full parse out of scope (Layer-1 spike in BACKLOG); ML win-predictors / CV-minimap / voice / `riot-offline-mode` CLOSED; Pengu `league-client-mcp` = NO. Reverses if: a candidate's LICENSE changes (re-run the licence gate on that one) or the operator re-opens a named item.
- **`core/smoothed_rates.py` is the shared Laplace/shrink primitive; the s220 PGR 0-100 score is deferred to ROADMAP-S3** - do not pre-build it. Reverses if: ROADMAP-S3 starts.
- **Brawl is retired from champ-select, but `coaches/brawl_coach.py` is LIVE-REACHABLE** (URF / ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ route to `MODE_BRAWL`, live Haiku call). Never delete it as dead code; its `GAME_MODES` is never read - do not make it a gate. Say "unexercised, not unreachable". LEDGER 1222. Reverses if: the router is measured at HEAD sending NONE of those modes to `MODE_BRAWL` (only then may removal be proposed).
- **The Riot Personal key is valid; Match-V5 403/empty on event modes is EXPECTED; event-mode timeline placeholders are correct and permanent.** SGP (LCU-session match history) DOES return KIWI / queue-2400 games (RM-106). Reverses if: a NON-event-mode Match-V5 call 403s (key problem), or Riot starts serving event-mode timelines.
- **`web/js/dashboard.js` is GONE** (quarantined `90c54ef5`); the `dashboard.js:5055` `_replayQueueLabel` 920 bug died with it - closed fence. Reverses if: `web/js/dashboard.js` reappears in the git index.
- **ADR-008 unified asset-hash:** `web/{js,css}/panels/*` edits auto-reload; no restart for asset-only changes. Reverses if: an asset-only edit is measured NOT reloading, or ADR-008 is superseded.
- **No-em-dash retroactive purge is done; the `"-"` sentinel is operator-approved; the smart-quote retro-sweep is NOT done** (operator-gated). Reverses if: the operator lifts the smart-quote gate, or a glyph audit finds em/en dashes in a swept class.
- **The all-173 DS_SWEEP is CLOSED (173/173).** Do not re-open the roster or re-scan for uncovered champions; further growth needs a schema lift, not another pass. Probe traps: `POST /rank` is the CARRY scorer and ignores enemy shares (use `/rank-<archetype>`); `item_ids=[]` under-ranks amp items. Reverses if: Riot ships a champion beyond the 173 (sweep that one only) or a schema lift lands.
- **The live-gated set is NOT synthetically drainable** (measured; dominant kill = substitution). See `docs/LIVE_GAME_GATED_SYNC.md`. Reverses if: a synthetic harness is MEASURED closing a gated row without substitution.
- **Pre-2026-07 ledger commit citations are ~50% unresolvable, EXPECTED; most are the PARTIAL 2026-06-21 filter-repo rewrite and RECOVERABLE.** The work landed: verify by merge hash / file / test, never by a slice hash. Before calling a hash gone, look it up in `.git/filter-repo/commit-map`. Repair tool `tools/rewrite_sha_citations.py` (RM-501: never applied to the append-only history files; the LEDGER repair is a merger-owned mapping list). Reverses if: RM-501's repair is applied to a file - then re-derive that file's unresolvable count and restate it.
- **Live DS truth = `data/daemon_slayer/current.txt` + `agents/daemon_slayer/__init__.py` + `/health`.** DS coverage prose is a DS-batch docs-sync job, never recomputed in a general sync. Reverses if: DS gains a different version authority (e.g. `/health` stops reporting `ENGINE_VERSION`).
- **A DS route seam has THREE gates; ownership prose lies in both directions.** Measure owners with `inspect.signature`, then check the TRANSPORT, not just the flag. Memory `reference_ds_route_seam_transport_vs_flag`. Reverses if: the seam is consolidated to one gate (re-measure with `inspect.signature` before saying so).
- **Ability-haste is measured INERT however authored** - do not spec it a fourth time (RM-39/RM-43). Reverses if: the engine gains a cooldown-consuming term and a probe measures a non-zero haste delta.
- **Biggest pending non-engine item: the s220 Post Game Review reframe** (UI; operator-decided scope = single-match richer layout; the 0-100 score is an RC heuristic over enriched stats, no Claude/Riot dependency; staged S2-S5, each with the UI-audit ritual). Legion 1-PC consolidation is DONE (ADR-011). 101.qq.com duo-synergy is LIVE-WIRED (item 277; `RC_DUO_SYNERGY_LIVE=0` kill switch); its capture is TRACKED third-party data recorded in `NOTICE`. Reverses if: S5 ships (the item is no longer pending) or the operator re-scopes it.
