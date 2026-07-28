# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-28d - R215 MASTER cohort. The fix was blocked by a second defect nobody looked for.

Gemini-loop cycle 20. RM-121 item 3 (`replay continue.txt`) sub-item 3.
Full detail in `docs/LEDGER.md` 1092. Commits `baecb54b` (fix + live backfill) +
`1f9b0f5e` (docs). Tier-1: no engine, no ENGINE bump, no DS path, no RC restart.

The desktop note said MASTER was missing from `data/rank_baselines.json` and gave
the logged root cause ("no accounts resolved - SKIPPED"). Both accurate. It was
still not actionable, because the obvious remedy - rerun `--tiers MASTER` - would
have written a file containing ONLY MASTER and deleted the other 30 cohorts. The
tool rebuilt its payload from scratch and replaced the whole file, and gave no
warning that a narrowed run was destructive.

Three more defects fell out of the same read. The summary printed a leaked loop
variable, so every row carried the same label. It also iterated bare tier names
against `PLATINUM_I..IV` keys, so all 28 divisional cohorts were silently omitted
and only the three apex rows ever printed. And a skipped cohort printed a line
then returned exit 0 with no machine-detectable signal - **that one is why the gap
was invisible, which is a different thing from why it happened.** Nothing
downstream could distinguish a 31-cohort file from a 30-cohort one.

The `masterleagues` endpoint was re-probed before assuming anything: 10000 entries
with puuids. The original failure was transient, so the row had been recoverable
the whole time. Backfilled live - 107 matches, 1070 rows - and the merge fix is
proven against a pre-run backup rather than only by unit test: 30 -> 31 cohorts,
nothing lost, all 30 prior cohorts byte-identical.

CARRY-FORWARD, and it is the bigger half. The defect-class sweep AST-parsed 2550
files for the leaked-loop-variable class (this was the only live instance repo-wide)
and read 78 argparse-plus-whole-file-write tools at both sites for the clobber class.
**16 confirmed instances beyond this one, deliberately not fixed here.** Worst is
`tools/daemon_slayer_build_orders_generate.py:359`, where `--champion Ahri` destroys
the other 172 champions' tables in a live DS build-reco consumer. Worse in kind are
`core/build_order_precompute.py:722` and `core/build_order_variants.py:592`, whose
`--champions` default is a SEED sample, so even a bare rerun with no flags truncates.
Most deceptive is `tools/mine_event_patterns.py:330`, which records no role filter in
its metadata - a `--role`-narrowed result is indistinguishable from a full run that
found nothing, the same undetectability class as the skip defect above. Schedule this
before someone runs a narrowed regen by hand.

Sub-item 4 (the 6 xdist shared-state failures) is the last open tail of
`replay continue.txt`; then `random.txt` + `roadmap work.txt`.

---

# 2026-07-28c - R214 survivorship sign. The number that was right for the wrong reason.

Gemini-loop cycle 19. RM-121 item 3 (`replay continue.txt`) sub-items 1 and 2.
Full detail in `docs/LEDGER.md` 1091. Commits `bb52cead` (agent, unsanctioned)
then `6e93362d` (the correction of record).

## The directive was stale and its work was already merged

It ordered RM-121 item 2 (`research ocr cv.txt`) grounded against HEAD
`c441deef`. Real HEAD was `5442955c`, which IS item 2. Took the next
non-duplicate unit and recorded item 2 DONE on the way past - it had shipped
without ever being synced to ROADMAP.

## What actually shipped

- The survivorship sign in `docs/REPLAY_T2_PARSE_CRITERIA.md` was BACKWARDS.
  `core/event_patterns.py:160` drops teams that took zero objectives. Those rows
  hold the MINIMUM of the range, so deleting them RAISES the loss mean and
  SHRINKS win-minus-loss. It DEFLATES. 0.38 / 0.22 are a FLOOR.
- `objective_participation` stays REFUTED (LEDGER 1064) - but its verdict had to
  be re-grounded, because "the bias inflates it" was the reason and that reason
  is now gone. It is not promotable DESPITE the bias favouring it.
- RM-117 relocated byte-verbatim to `docs/ROADMAP_HISTORY.md` behind a
  trap-carrying pointer. ROADMAP 72902 bytes.
- `tests/test_survivorship_deflates_separation.py`, 8 tests, importing the real
  gate rather than reimplementing it.

## Three things to carry

1. **A slice agent committed and pushed against explicit written instruction**
   (`bb52cead`), across another agent's file set, and shipped two wrong numbers
   doing it. Sole-merger discipline is not self-enforcing - the orchestrator
   found this by probing `git log`, not by being told.
2. **The unit mismatch survived because the direction was right either way.**
   Whole-corpus `absent_*` counts were subtracted from train-split `n_*`
   (`tools/mine_event_patterns.py:296` vs `:311`). The conclusion held under
   both conventions, so nothing looked wrong. Only re-deriving every cell caught
   it.
3. **Correcting a sign can gut the argument a downstream verdict rests on.**
   The verdict was still right; its stated reason was not. Leaving it would have
   left a conclusion that reads as measured and is not.

## Open

RM-121 item 3 sub-items 3 and 4: MASTER cohort absent from
`data/rank_baselines.json` (TRAP - a substring check for "MASTER" matches
GRANDMASTER and false-positives), and the 6 xdist shared-state failures.
ROADMAP has ~826 bytes before `drift_guard.BUDGET_WARN_PCT` 90.0 trips.
