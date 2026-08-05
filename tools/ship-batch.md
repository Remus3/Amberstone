# Ship Daemon Slayer Batch (one pass)

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

One self-contained pass: select the next DS batch, implement it, prove it green,
bump the engine, ship it, verify live, hand off. Run end to end without stopping
to check in. ASCII only, no em/en dashes or smart quotes in any authored byte.

## 0. Pre-flight (state, do not trust recollection)

- Read ROADMAP.md "Open items" + BACKLOG.md; pick the next DS batch (lowest open
  priority, or the explicit "continue ds" target). Live DS truth, never the ledger:
  - `agents/daemon_slayer/__init__.py` ENGINE_VERSION (authoritative; NOT pyproject)
  - `data/daemon_slayer/current.txt` (patch)
  - `curl -sk http://127.0.0.1:8860/health` (engine_version / patch / champions / items)
- State the batch scope + assumptions explicitly before editing.

## 1. Implement

- Schema/engine/registry changes for the batch only. No drive-by refactor.
- Atomic writes (`tmp.write_text(...); tmp.replace(target)`); overlays poll mid-write.
- Write `.py` as ASCII + LF (the repo .gitattributes pins `*.py eol=lf`; the
  documented `
` incident came from autocrlf re-adds - author LF).

## 2. Prove green

- Add tests for the new behavior. Property-based over live cdragon/Meraki math
  where possible; no hardcoded magic numbers; avoid fragile cross-item comparison
  asserts (assert on computed quantities). Wrap class-accessed stubs with
  `@staticmethod` correctly.
- Full DS suite until green:
  `python -m pytest agents/daemon_slayer -q`
  then the wider guard suite `python -m pytest -q` before the version bump.

## 3. Bump ENGINE_VERSION (with the guard)

- Edit `agents/daemon_slayer/__init__.py` ENGINE_VERSION (semver; minor for a
  feature batch, patch for a correctness fix).
- Update every pinned assertion. **Do not trust a count written here** - it was
  "about 14 files" for long enough to be wrong by an order of magnitude (measured
  2026-08-04 at ENGINE 1.275.0: 126 test files, 146 quoted literals). Measure it
  yourself, every time:

  ```
  git grep -l 'ENGINE_VERSION' -- 'tests/*.py' 'agents/daemon_slayer/tests/*.py' | xargs grep -l '<old>'
  ```

  Only a handful spell the pin as a bare `== "<old>"`; most go through
  `assertEqual(daemon_slayer.ENGINE_VERSION, "<old>")`, so a grep for the
  comparison operator alone under-reports badly. Sweep them in one pass; the pin
  IS the guard test (a stale pin fails, proving the bump was deliberate).
- Re-run `python -m pytest -q` - must be fully green.

## 4. Compile + commit + push

- `python -m py_compile` every changed `.py` (syntax errors crash silently
  under pythonw.exe).
- Conventional commit naming the batch + ENGINE delta, e.g.
  `feat(daemon-slayer): <batch> (ENGINE x.y.z -> x.(y+1).0)`.
- `git push origin main`. Confirm the pre-commit hook reports py_compile OK.

## 5. Verify live (:8860 is NOT supervisor-watched)

- The DS server runs under the `RC-DaemonSlayer` scheduled task
  (`pythonw.exe tools/start_daemon_slayer.py`, :8860). It does not honor
  restart_trigger.txt and the supervisor does not bounce it.
- Restart it: `schtasks /End /TN RC-DaemonSlayer` then
  `schtasks /Run /TN RC-DaemonSlayer` (hard fallback: `taskkill /F /PID <:8860 pid>`
  then `schtasks /Run /TN RC-DaemonSlayer`). Never `Stop-Process`.
- Verify `curl -sk http://127.0.0.1:8860/health` reports the new engine_version
  and a known champion's DPS/EHP is unchanged where it should be.
- If RC itself was touched: `echo restart > restart_trigger.txt`, then confirm
  `ops/runtime/health.json` shows a new pid, `alive=true`, `last_reload_ok=true`.

## 6. Hand off

- Sync living docs on the ENGINE bump: CLAUDE.md / docs/DAEMON_SLAYER.md /
  README - engine version + DS test count. Do not rewrite dated
  ledgers; only living docs.
- Append a WAKEUP_NOTES.md entry (keep last 2-3 sessions at full fidelity,
  archive older to docs/history_notes.md): batch, ENGINE delta, commit hash,
  test totals, live-verify result, any flagged follow-up. ASCII only.
- `/done` if this was the unit of work.

## Mirror discipline

Canonical copy is the tracked `tools/ship-batch.md`. The gitignored
`.claude/skills/ship-batch/SKILL.md` and `.claude/commands/ship-batch.md` are
byte-identical mirrors of it (tracked tools/ wins; never let a `.claude/` copy
diverge or re-inject non-ASCII). Re-mirror after any edit.
