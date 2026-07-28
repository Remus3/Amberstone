# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-28e - R216 xdist subTest gate. The override looked for drift in the wrong place.

Gemini-loop cycle 21. RM-121 item 3 (`replay continue.txt`) sub-item 4, which
completes item 3. Full detail in `docs/LEDGER.md` 1093. Commits `981f138c` (gate)
+ `3b7b20d4` (plan sha). Tier-1 test infrastructure: no engine, no ENGINE bump, no
DS path, no Share mirror change, no restart.

The directive ordered a fix for "the 6 xdist shared-state failures" and arrived
wrapped in a stale-grounding override: re-read ROADMAP.md before trusting the
from-digest premise. I re-read it. **The premise was true** - `ROADMAP.md:42` said
it verbatim.

**The stale artifact was not the digest. It was ROADMAP.md.** The override is
built to catch a digest drifting away from the tree, so it asks one question: does
the file still say what the digest claims? It has no question for the case where
the file agrees and both are wrong. Two sources agreeing is one premise, not two.

What closed it was the cheapest check available - run the thing the row says is
broken, before fixing it. 132 seconds:

    pytest tests/ agents/daemon_slayer/tests/ -n 8 --dist loadfile
    23849 passed, 106 skipped, 6161 subtests, 0 failed

Five of the six died in `cd0f115d` on 2026-07-27, three hours AFTER the desktop
note that seeded the queue row was written. The sixth went with the RM-100
`tests/_asyncio_isolation.run_coro` consolidation. The row was obsolete before it
was ever scheduled.

## What shipped instead

`cd0f115d`'s own commit body says it "swept every other subTest call site in both
suites" and warns that "any future hostile-input matrix is one non-primitive away
from the same `-n`-only failure". It diagnoses the residual risk correctly and
then answers it with prose - over 463 call sites in 100 files, in a defect class
**a serial run cannot observe by construction**. There is no execnet channel
serially, so the failure mode does not exist to be seen. An eye-sweep is the
weakest available instrument for a defect whose defining property is invisibility
in the default run.

A repo-root `conftest.py` now validates every `subTest` kwarg against execnet's
OWN `dumps` at call time - not a hand-written type whitelist, which would be the
same guessing that produced the bug. Repo-root because `tests/conftest.py` cannot
reach `agents/daemon_slayer/tests/`, which has no conftest and held one of the
five instances.

The guard is also the enumeration probe. Installed, full dual suite re-run:
**23861 passed, 0 failed** - exactly +12 tests / +17 subtests, the new file to the
unit, so **0 additional instances repo-wide**. `cd0f115d`'s sweep was correct. The
value delivered is that it is no longer a claim.

## Three things to carry

- **A queue row is a claim with a timestamp, not a fact.** Check the row's age
  against the tree before building on it. Cycles 13-19 were no-ops for adjacent
  reasons; this is the same family seen from a new angle.
- **If a fact matters enough to write down twice, assert it.** A shipped docstring
  claimed `set()` raises `DumpError` alongside `object()`. Measured: sets and
  frozensets serialize fine, the containers recurse so `[object()]` fails and
  `{1, 2}` does not. Never load-bearing, but it is exactly the
  remembered-not-measured detail that sends the next reader rewriting working
  code. The grammar is now pinned by a test.
- **The verifier earned its slot on the check I could not self-certify.** It wrote
  a throwaway `subTest(bad=object())` test INTO the DS suite, watched it fail with
  the guard's TypeError, deleted it and proved no residue. Being importable is not
  the same as reaching.

## Open

- **Do NOT re-open "the 6 xdist failures". There are none.** Measured twice this
  session.
- **Reach limit, deliberate:** a rootdir conftest only loads when pytest runs from
  the repo root, so a DS-dir invocation bypasses the guard. Do NOT close it with a
  conftest under `agents/daemon_slayer/tests/` - that path mirrors into
  `Share/src/`, and `Share/` runs standalone (RM-112) where the helper does not
  exist, so the mirror would import a missing module and break a clean package.
- **`ROADMAP.md` is at 91 percent of its 81920-byte budget and was already
  breaching at HEAD.** Reported, not silenced. It needs a relocation pass; RM-117
  was moved out for this reason and the pressure is back.
- **Unclaimed, from LEDGER 1092:** the 16-instance
  whole-file-rewrite-under-a-narrowed-work-plan class, live DS-consumer blast
  radius. Schedule it before someone runs a narrowed regen by hand.
- **NEXT in the operator queue:** RM-121 item 4, `random.txt` + `roadmap work.txt`.
