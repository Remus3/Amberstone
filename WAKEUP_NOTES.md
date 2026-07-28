# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28i - R218 champ-select shadow flip gate. RM-12 named a gate that was never built.

Gemini-loop cycle 25. Full detail in `docs/LEDGER.md` 1097. Commits `bb746286` (work)
+ `678d4659` (sync). Section 4b Lane C. One new read-only host tool + its test: no
engine, no ENGINE bump, no DS path, no Share mirror, no restart, no route or panel.

- **The defect class was structural, not a bug.** A shadow lane writes BOTH the native
  and the deterministic column so the two can be compared later. Ten lanes do that.
  Eight have a `tools/*report*.py`; `augment_shadow` and `anvil_shadow` carry an
  in-module `summarize_agreement`. `core/champ_select_shadow.py` had neither, which
  made it the one live-wired lane whose flip readiness could not be measured at all.
- **`ROADMAP.md:146` had been citing an instrument that did not exist.** RM-12's clause
  "the champ-select brief Haiku flip after shadow-log accrual" reads as though someone
  need only check the number. There was no number. LEDGER item 500 shipped the writer
  in 2026-06 and its own NEXT jumped straight to the FLIP, so the intermediate gate was
  never filed anywhere - not ROADMAP, not BACKLOG, not the plan. It took a `grep` for
  `champ_select_shadow` across all four to establish that: zero hits.
- **Non-ARAM rows are gated out of the `swap` column, and that is the whole point.**
  Off-bench, both the native and the deterministic side say nothing. Scoring that
  silence banks a free KEEP/KEEP agreement on a row carrying no signal, and enough of
  them walk the rate to the 0.70 flip gate without a single real agreement underneath.
  Pinned by a tested invariant: `coverage.non_aram == swap.gated_out_non_aram`.
- **The ARAM sibling's substring matcher is wrong and I did not copy it.**
  `tools/aram_shadow_report.py` classifies by raw substring, so "ban" matches inside
  "banner" and "lock" inside "locked". The degraded marker here is literally
  `no champion locked`. Token-boundary matching instead. Not swept into the sibling -
  that is its own slice with its own evidence, and this one had no failing case to cite.
- **`_FIELDS` imports `core.champ_select_shadow._ADVICE_KEYS` rather than restating it.**
  A restated tuple survives a writer-side rename and silently zeroes a column; an
  import fails loudly. Same reasoning as the contract-test-reads-the-contract rule.
- The directive tagged its own premise `[UNVERIFIED]` and both halves held - plan has
  zero WIP rows, Section 4b is genuinely unfinished. Third real unit in a row.
- Verifier CONFIRM 9/9 before merge. RC 13801 passed / 106 skipped / 477 subtests
  (13766 baseline + 35 new). CI green on both SHAs.
- **NEXT / owed:** the gate exists, the log does not. `data/champ_select_shadow.jsonl`
  is empty and the report reads `state=awaiting_accrual` below MIN_SAMPLE 20. Nothing
  further to build on this lane until real champ-select rounds accrue - the RM-12 clause
  cannot be argued in either direction before then. Do NOT re-pitch the report.

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
