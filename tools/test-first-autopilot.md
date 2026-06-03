# Test-First Spec-to-Ship Autopilot

Given a batch spec, drive it strictly test-first to 100% green, then ship it.
Run end to end without checking in. ASCII only, no em/en dashes or smart
quotes in any authored byte. This is the TDD-strict sibling of `ship-batch`:
ship-batch SELECTS and implements a ROADMAP batch; this one takes a spec you
already have and proves it with derived tests before a line of impl exists.

## 0. Pin the spec + ground truth

- Restate the spec as a one-paragraph contract: exact behavior, the inputs,
  the expected outputs. State assumptions explicitly before any code.
- Source every expected number from LIVE Riot/Meraki/cdragon math, never a
  guess. Use the repo's existing UA-aware data path (`tools/daemon_slayer_extract.py`,
  the vendored `data/daemon_slayer/<patch>/items_meraki.json`,
  `core/augment_external_source.py`). raw.communitydragon.org 403s a UA-less
  urllib request - do not hand-roll a fetch.
- NO hardcoded magic numbers: a test asserts `engine(x) == formula(x)` where
  `formula` is the Riot/Meraki expression evaluated in the test, not a literal
  pasted constant. NO fragile cross-item comparison asserts (never
  "item A dps > item B dps"); assert on the computed quantity itself.

## 1. RED - scaffold the tests first

- Write the failing tests BEFORE implementation, in `agents/daemon_slayer/tests/`
  (follow the existing `test_*_sNNN.py` / `test_*_pipeline_*.py` naming).
- Prefer property/derivation tests: recompute the expected value from the
  formula for several levels / stack counts / target states and assert the
  engine matches each. Pin boundary cases (level 1, level 18, 0 stacks, max
  stacks) where the formula has known exact values.
- When stubbing a method accessed via the class, wrap it with `@staticmethod`
  correctly.
- Run the new tests and CONFIRM THEY FAIL for the right reason (RED). A test
  that passes before implementation is not testing the spec.

## 2. GREEN - loop Edit / pytest

- Implement the minimal change to satisfy the spec.
- Loop: `python -m pytest agents/daemon_slayer/tests/<new>.py -q` -> Edit ->
  repeat until the new tests pass.
- Then the FULL gate, which must be 100% green with zero regressions:
  `python -m pytest agents/daemon_slayer -q` (baseline is ENGINE-pinned;
  know the current passed + subtests count and do not drop it), then
  `python -m pytest -q` for the wider suite.
- Do not weaken a real assertion to get green. If a prior pin legitimately
  moved because the spec corrects it, rebaseline it deliberately and say so
  in the commit; never silently.

## 3. Ship

- `python -m py_compile` every changed `.py` (silent crash under pythonw.exe
  otherwise).
- Single ENGINE_VERSION bump in `agents/daemon_slayer/__init__.py` (semver:
  minor for a feature/correctness batch, patch for a pure fix) + sweep every
  pinned `ENGINE_VERSION == "<old>"` guard assertion (about 14, in
  agents/daemon_slayer/tests/test_*; the pin IS the guard - a stale pin fails,
  proving the bump was deliberate). Re-run `python -m pytest -q` fully green.
- Conventional commit naming the spec + ENGINE delta; push origin main.
  Confirm the pre-commit reports py_compile OK.
- Verify live: `RC-DaemonSlayer` task is NOT supervisor-watched - restart it
  (`schtasks /End /TN RC-DaemonSlayer` then `/Run`; hard fallback
  `taskkill /F /PID <:8893 pid>` then `/Run`; never `Stop-Process`) and
  confirm `curl -sk http://127.0.0.1:8893/health` serves the new
  engine_version. If RC core changed: `echo restart > restart_trigger.txt`
  then verify `ops/runtime/health.json` (new pid, alive, last_reload_ok).
- Sync living docs on the ENGINE bump (CLAUDE.md / docs/DAEMON_SLAYER.md /
  README: version + test count; do not rewrite dated ledgers).
  Append a WAKEUP_NOTES.md hand-off (last 2-3 sessions full, archive older).
  `/done`.

## Mirror discipline

Canonical copy is the tracked `tools/test-first-autopilot.md`. The gitignored
`.claude/skills/test-first-autopilot/SKILL.md` and
`.claude/commands/test-first-autopilot.md` are byte-identical ASCII mirrors of
it (tracked tools/ wins; never let a `.claude/` copy diverge or re-inject
non-ASCII). Re-mirror after any edit.
