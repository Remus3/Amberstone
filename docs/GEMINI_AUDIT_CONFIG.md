# Gemini CLI Overnight Auditor - Config

> **PROVISIONAL - revisit after calibration.** Nothing here is hard-ruled into
> CLAUDE.md or any frozen file. Authored 2026-06-04. All knobs are tunable.

## Division of labor

- **Gemini CLI** = read-only advisor / critic / researcher. Reads the repo,
  writes findings to a review file. NEVER edits source, never commits.
- **Claude (me)** = sole implementer / writer. I parse Gemini's review file,
  verify every claim against ground truth, and am the only agent that touches
  source or version control. Gemini proposes; I dispose.

## Decisions (this round)

| # | Category        | Decision                                                      | Source     |
|---|-----------------|--------------------------------------------------------------|------------|
| 1 | Auth Mode       | API key via `GEMINI_API_KEY` env var (User scope)            | default    |
| 2 | Cadence         | Nightly timer (RC-GeminiAudit scheduled task)              | OPERATOR   |
| 3 | Scope Lanes     | open-task audit + analyzer triage + architecture critique + research | OPERATOR |
| 4 | Output Channel  | `docs/EXTERNAL_REVIEW_<YYYY-MM-DD>.md`                        | default    |
| 5 | Autonomy        | Supervised digest - findings only, I review before any code  | OPERATOR   |
| 6 | Rate Ceiling    | 1 audit call per trigger; hard cap 10 calls/day (backstop)   | default    |
| 7 | Model           | gemini-3-pro-preview (paid, billing on), diff/backlog-scoped | OPERATOR   |

## Cost (verified 2026-06-04)

- Gemini 3 Pro paid: `$2.00/M` in, `$12.00/M` out (<=200K ctx).
- Diff-scoped audit ~ 70K in / 8K out per run -> ~`$0.24`/run.
- Nightly cadence: ~30 runs/mo -> ~`$7`/mo. (Per-commit was considered then
  dropped in favor of the overnight night-watch timer.)
- Full-tree was rejected (~`$97`/mo, re-reviews static code).

## Open design flags (resolve in STEP C)

- **Cadence mechanism.** RESOLVED 2026-06-04 -> nightly `schtasks` timer
  (`RC-GeminiAudit`, overnight), matching the existing RC-* task pattern.
- **Paid tier.** Enable billing on the AI Studio / Cloud project at key
  creation. Removes the free-tier train-on-prompts behavior (moot here, but a
  bonus). Env-var wiring is identical to free.
- **Diff source.** "the diff" = `git diff` of the merge (changed files +
  surrounding context) + open `ROADMAP.md` / `BACKLOG.md` items, NOT the full
  tree. `.geminiignore` still excludes `Share/src`, `_archive`, `node_modules`,
  `.git`, `*.db`, secrets.

## Status

- [x] STEP A - Q&A recorded (this file)
- [x] STEP B - pricing + token math
- [x] BREAKPOINT - GEMINI_API_KEY set (User scope) + billing enabled, live-verified 2026-06-04
- [x] STEP C - DONE. gemini-cli 0.45.1; model gemini-3-pro-preview (via RC_GEMINI_MODEL,
      User scope); read-only enforced by `--approval-mode plan`, workspace via `--skip-trust`;
      tools/gemini_audit.ps1 (stdin-pipe + retry + atomic write) + tools/gemini_audit_prompt.md;
      .geminiignore; docs/GEMINI_REVIEW_CONSUMPTION.md; RC-GeminiAudit nightly 03:00 registered +
      Enabled but NOT currently producing reviews - the 2026-07-19 03:00 run exited 0xC000013A and
      the newest review on disk is 2026-06-21 ("Ready" is the scheduler idle state, not evidence of
      a healthy run); tools/gemini_audit.ps1 repaired 2026-07-19, next nightly re-verifies.
      First real review docs/_archive/EXTERNAL_REVIEW_2026-06-04.md (gitignored) verified genuine.
- [x] STEP D - DONE. Tone/style/memory artifacts: GEMINI.md repo-root context (ASCII-only +
      ultra-terse style, verify-before-assert, frozen-file flag-only) 2026-06-04; stateless-per-call
      continuity hardened to the caller-appended ALREADY-COMPLETED DIGEST (newest-first LEDGER HEAD
      + persisted directive chain) 2026-06-27; audit output shape in tools/gemini_audit_prompt.md.
- [x] EXPANDED - in-session Q/A channel `tools/gemini_ask.ps1` -> `gemini_io/answer_<id>.md`
      (read-only, validated); AHK self-clear primitive `tools/claude_send.ahk` (AHK v2, target
      `ahk_exe claude.exe`, DRY-RUN default + window-verify + kill-switch Ctrl+Alt+Q, NOT auto-wired).

## Expanded scope (operator, 2026-06-04)

Gemini is not only the nightly critic - it is also an **in-session + headless
research / orchestration assistant** for autonomous RC & DS development:

- Gemini reads the repo + answers Claude's questions by writing/updating files;
  Claude reads them. File-based Q/A, mirroring the RC<->Peer bridge pattern.
- Proposed channel: `gemini_io/` (gitignored) - `ask_<id>.md` (Claude -> Gemini)
  + `answer_<id>.md` (Gemini -> Claude). Plus the nightly
  `docs/EXTERNAL_REVIEW_<date>.md`.
- Used in normal sessions AND headless-upgrade runs for find/research/
  orchestrate tasks. Still read-only - Gemini never writes source or commits.

### AHK self-drive primitive (prototype, NOT auto-wired yet)

An AutoHotkey script that focuses the Claude prompt window, types a command
(e.g. `/clear`), and presses Enter - so a headless loop can self-clear context
between tasks. Claude Code (terminal) can call it directly; Gemini can too.
SAFETY before any autonomous wiring: verify the target window title BEFORE
typing, a kill-switch hotkey, a dry-run mode, a fired-commands log. OPEN: target
= Claude.ai desktop app (which exe/title?) or Claude Code in a terminal?
