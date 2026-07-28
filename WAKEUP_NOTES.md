# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28h - R217-U2 tools ASCII sweep. The decorative glyphs were fine; two of them were data.

Gemini-loop cycle 24. Full detail in `docs/LEDGER.md` 1096. Commits `84535bdf` (work)
+ `7cfebcce` (sync). Host tools only: no engine, no ENGINE bump, no DS path, no Share
mirror, no restart, no route or panel.

- `tools/extract_panels.py` 189 non-ASCII bytes of 11094 -> 0, `tools/rc_facts.py`
  10 of 10139 -> 0. Item-176 doctrine: 1:1 substitution, character count identical
  before and after (10968 / 10133), so nothing re-flowed.
- **Both from-digest premises held on disk.** After seven no-op cycles it is worth
  saying plainly: unverified is not the same as stale. Re-read cost one Read each.
- **The hazard the directive did not name.** The `U+25B6` / `U+2022` bytes sit inside
  `.replace()` MATCH patterns at `extract_panels.py:158-162` - the same load-bearing
  data class that makes `tools/p3_ascii_sweep.py` EXEMPT. Resolved by reading the
  tree: `web/js/panels/champ_select.js:195` already reads `"> "` and `:200` reads
  `"  *  "`, and the extractor's input is gone in the shape it slices (`main.js` is
  7565 lines; every `L(start,end)` addresses the 6223-line pre-split file). A re-run
  would destroy `main.js`, not re-extract it. Spent one-shot; the sweep is cosmetic.
- **The exemption is now pinned in the direction that can break.**
  `tests/test_tools_ascii_hygiene.py::test_p3_ascii_sweep_exemption_is_intact` fails
  if a later sweep strips the sweeper's own glyph inventory. A guard that only bans
  glyphs would let the next well-meaning sweep disarm the tool and stay green.
- The guard parses the extractor with `ast` rather than importing it - that module
  rewrites `web/js/main.js` at module scope, so an import destroys the file the test
  reads. Its width assertion reads the real `main.js` line off disk.
- **The executor-override's collision claim was FALSE:** it refused the 2-agent block
  saying both agents name `extract_panels.py`. They do not; the sets are disjoint.
  Refused anyway on the real ground - R9's subagent floor, two files and one test.
  A false collision report is worse than none, because the next reader discounts it.
- Scope stays narrow: per-file pin, not a repo-wide ASCII ban. `U+2500` is not banned
  and `web/js/main.js` alone carries 1310.
- Verified: TDD RED 3 failed / 2 passed first; ruff + py_compile clean; RC suite
  13766 passed / 106 skipped / 477 subtests / 0 failed at `-n 8`.

---

# 2026-07-28g - R217-U1 full RC suite on push. The named edits were fine; the budget was the bug.

Gemini-loop cycle 23. RM-119 second half, the RC-half CI promotion the operator
authorized in `roadmap work.txt`. Full detail in `docs/LEDGER.md` 1095. Commit
`9e7b70d1` + this sync. CI config only: no engine, no ENGINE bump, no DS path, no
Share mirror, no restart, no runtime `.py`.

- `.github/workflows/ci.yml` `check:` now installs `requirements.txt` and runs
  `pytest tests/ agents/daemon_slayer/tests/ -q -n auto --dist loadfile`. The two
  subset steps (`smoke + regression tests`, `panel snapshot tests`) are deleted.
- **The install line is the point, not bookkeeping.** An ImportError-guarded test
  that cannot import is a SKIP, and a skip is a green tick - promoting the suite
  without the runtime stack buys minutes and almost no assertions.
- **The defect nobody named: `timeout-minutes: 25` would have CANCELLED it.** The
  19m42s dispatch price is pytest in a job that does nothing else; `check:` also
  installs Playwright, sweeps py_compile, runs ruff and the Share mirror check
  (DS-only shape = 9m1s end to end, run `30342574878`). New shape prices at ~26m.
  Raised to 40. A blown ceiling reports as *cancelled*, not failed.
- 4 named-file steps kept, all justified IN the file: two turn a skip into a
  failure (`RC_REQUIRE_*`), two are 10-second fast-fail guards. Otherwise the next
  reader deletes them as duplicates and is right by every argument but the useful one.
- RM-119 CLOSED both halves; narrative relocated to `docs/ROADMAP_HISTORY.md`
  (`ROADMAP.md` 80351 -> 76662 of 81920). Skip-audit B2/B4/B5 stay - open work.
- Gate: full dual `-n 8` **23861 passed / 106 skipped / 6178 subtests / 0 failed**
  in 131.49s; verifier CONFIRM on an independent re-run; ruff clean; 14 `check:`
  steps parse.
- **Carry-forward: every push now costs ~26 CI minutes.** That makes the docs-only
  `paths-ignore` skip and `concurrency: cancel-in-progress` load-bearing, not
  cleanup targets. R217-U2 (tools non-ASCII residue) is still OPEN.

---

# 2026-07-28f - R217 desktop-queue drain. Half the notes were already true on disk.

Gemini-loop cycle 22. RM-121 item 4 (`random.txt` + `roadmap work.txt`), which
DRAINS the five-file desktop chain - four items, no file 5, do not re-pick RM-121.
Full detail in `docs/LEDGER.md` 1094. Commit `4e9bf60b` + this sync. Tier-0 docs
only: no `.py` / `.yml` / `.css` / `.html`, no engine, no ENGINE bump, no DS path,
no Share mirror change, no restart.

## The override held this time, and the unit was real

Cycles 13-19 kept ordering work already on disk. This directive's `[from-digest]`
premise was TRUE - `ROADMAP.md:42` carries the sentence verbatim - and both desktop
sources exist. The re-read still earned its keep at one Read.

## Three things to carry

1. **An operator note is no more current than an audit digest.** 5 of the 11 claims
   across these two notes were already resolved: the `wakeup_prune` SESSION_RE
   blindness (fixed `2f35163d`; `--check` exits 0, this file was 10759 bytes with
   exactly 3 headings), the "loop is PARKED" claim (RM-120 closed it), the
   git-hook BOM/non-ASCII ask (`.githooks/` + `precommit_gate.py` + the hygiene
   trio already do it), the `performance_tracker.py:37-39` em-dashes, and the
   `data/ratings/*.json` backfill behind them (0 of 4 files carry a dash). Probe
   every line of a note, not just an inherited premise.
2. **The disqualifying instruction can be the header, not the content.**
   `random.txt` part 2 opens "operator-present; Do NOT run headless" and then lays
   out a well-specified 6-item queue that never repeats the prohibition - exactly
   the shape a headless executor consumes. Filed as RM-122 with the gate restated
   inside the row.
3. **The plan-file relocation is now a steady state, not a chore.** Keep exactly
   ONE findings block at the tail of `docs/ORCHESTRATION_PLAN.md`: relocate the
   previous cycle's block verbatim as you append yours. R217 did that and landed
   the newest row at 9004 bytes from EOF instead of the ~20000 R216 predicted.

## Open

- **`ROADMAP.md` is at 80351 of its 81920-byte budget - 1569 bytes of headroom.**
  The next writer relocates shipped narrative to `docs/ROADMAP_HISTORY.md` first.
- Plan rows `R217-U1` (`ci.yml` RC-half promotion, operator-authorized, ~20min per
  push measured) and `R217-U2` (`tools/extract_panels.py` + `tools/rc_facts.py`
  non-ASCII; `p3_ascii_sweep.py` EXEMPT) are OPEN and chunked, not built.
- LEDGER 1092's 16-instance whole-file-rewrite class is still unclaimed.
