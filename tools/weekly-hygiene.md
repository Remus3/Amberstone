---
description: Weekly light maintenance pass - WAKEUP/doc-overhead relocate-only trim, memory staleness scan, and session-start anomaly triage. Lighter than /sync-all-md (which it explicitly defers). Use on a weekly cadence or when the operator asks to "run weekly hygiene".
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the Gemini director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the Gemini director (or the operator if Gemini is down) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

The operator wants a LIGHT, recurring hygiene pass that keeps the hot docs and
memory honest without the cost of a full doc reconcile. This is NOT /sync-all-md
(that is a separate, heavier pass - see the DEFER list below). Run the sections
in order, make only the relocate-only / low-risk edits autonomously, and FLAG
every judgment call for the operator instead of guessing.

This pass is documentation + memory hygiene. It makes NO code changes, does NOT
restart RC, and does NOT touch `data/`.

**Args:**
- _(none)_ -> run all sections, apply relocate-only doc trims, flag the rest, print report. Commit the doc trims when green.
- `--dry-run` (or `preview`) -> report only, zero writes.

### 1. WAKEUP_NOTES trim (relocate-only)

Keep the last 2-3 sessions at full fidelity in `WAKEUP_NOTES.md`; relocate older
session blocks verbatim to `docs/history_notes.md`. Do NOT rewrite or summarize
the relocated text (memory `feedback_no_history_rewrite`).

GOTCHA: the wakeup prune splits sessions on the `---` separator. A /done that
appended a session WITHOUT the separator makes `--check` silently under-count and
WAKEUP grow unbounded - normalize separators first (memory
`reference_wakeup_prune_separator_gotcha`).

### 2. Doc-overhead trim (relocate-only)

`CLAUDE.md` is CI size-budgeted (< 60KB) and auto-loaded every turn. Verify no
per-item ledger entries leaked into it - those belong in `docs/LEDGER.md`
(append-only, newest-first). Relocate any stray ledger/wakeup detail out of
CLAUDE.md; touch CLAUDE.md itself ONLY for rule / frozen-list / Settled changes.

### 3. Memory staleness scan

Scan `C:\Users\Administrator\.claude\projects\C--Riot-Commander\memory\` for facts
that reference removed or changed infra (e.g. the now-removed gamepc :8892 MCP /
Game-PC bridge peer, 2-PC topology, an old Riot ID, a stale file:line). For each
suspect:
- HIGH confidence + low blast radius (names retired infra) -> update the file AND
  its `MEMORY.md` index line, ASCII-clean.
- MEDIUM confidence, or a memory the operator relies on -> FLAG it, do not edit.

Memory lives OUTSIDE the repo (no git) - these edits are not committed. Verify a
claim live before editing (memory `feedback_verify_before_declare_broken`).

### 4. Session-start anomaly triage

Re-read the session-start anomaly summary, or run `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/rc_facts.py`.
Classify each anomaly EXPECTED vs ACTIONABLE:
- EXPECTED (Legion-only anomalies that are normal post-1PC) -> note it, no action.
- ACTIONABLE (e.g. a Legion scheduled task `last_result != 0`) -> investigate
  root cause; fix + test if in scope, else flag with a one-line recommendation.

Surface the list as "your call" - do not silently fix outward-facing state.

### DEFER (do NOT do in this pass)

- Full `/sync-all-md` doc reconcile (run it as its own pass when docs have drifted).
- DS coverage % / ENGINE_VERSION / match-row prose recompute - a DS-batch job
  only; the nested registry schema mis-parses on a flat count (memory
  `feedback_ds_coverage_prose_recompute`).
- `BACKLOG.md` edits (aspirational, read-on-demand).
- Any git-history rewrite of dated artifacts (AUDIT_*/PHASE_*/ARCH-*).

### Output

Print a tight report: what was relocated/committed, what was flagged for the
operator (memory suspects, actionable anomalies), and what was deferred. If doc
trims were made and local checks are green, commit them (relocate-only, stage
just the touched docs - never `git add -A`) and push. Leave all flagged judgment
calls for the operator to pick.
