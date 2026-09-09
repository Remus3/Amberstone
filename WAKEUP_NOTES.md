# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-09, RM-395 shipping pass (relocated `2026-09-09d` RM-393 shipped; newest 3 = RM-395 shipped `2026-09-09g` + ADR-015 `2026-09-09f` + RM-394 shipped `2026-09-09e`). The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-09g - RM-395 SHIPPED: the row I filed one commit earlier was wrong twice, and the step that caught it is the one the row demanded

Fifth row of the same headless day, operator AWAY. Tier-1: two test modules, no
engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1378.
Two parallel single-file slices, one merger, gate before the commit.

**Both corrections came from doing the step the row itself demanded FIRST** -
state whether an EMPTY enumeration would PASS each assertion before converting.
That step is in ADR-015's Watch for because RM-394 nearly shipped a silent
always-green. Here it caught my own filing.

1. **"Both are ABSENCE guards, the empty-set-safe shape" is FALSE for the laning
   guard.** `_app_source_files()` has exactly one consumer and it asserts SET
   EQUALITY against a two-element expectation, so an empty enumeration gives
   `set()` and FAILS. Self-anchoring, no anchor needed - PROVEN by mutation
   (`assert set() == {...}`, 1 failed / 26 passed), not reasoned.
2. **The row named two exposed sites; there are three** - and my framing of the
   third was ALSO wrong. `CallerSurfaceAbsenceTests.test_no_live_caller` sweeps
   6377 files with 5044 under the export trees, but its own
   `rel.startswith("ops/runtime/")` skip existed at HEAD (`:172`) and dropped
   every one BEFORE any read: read-set 1260 both sides, symmetric difference
   EMPTY. **Cost, not correctness.** I told the operator otherwise mid-session.
   Its real defect is the ADR's other green-by-luck sense - it never skipped
   `python-embed` / `node_modules` / `.claude`.

**Shipped.** `test_laning_verdict_flip_retired.py`: 2082 -> 397 enumerated, all
1685 removed are vendored `python-embed`, set-diff confirms 0 RC source lost and
0 gained, 15 first-party SCOPE skips kept and only 4 infrastructure entries
deleted; 27 passed. `test_dead_endpoint_cleanup_item186.py`: both sites, site 1
9112 -> 2386 (its two filters were removing ZERO files), site 2 to one root walk
plus a prefix filter reaching the identical 1260 read-set; 4 passed. **A gate
caught 1331 recited as the read-set in four places: 1331 is the caller SURFACE,
and this guard's own `dashboard/routes_` skip removes exactly 71 of them before
anything is opened.** Surface and read-set are different populations one line
apart, and the in-file comment saying "1331 across the caller surface" was right
while every doc restating it as the read-set was wrong.

**The anchors, and the mutation that justifies them.** With the identical
forced-empty mutation applied to the PRE-conversion code both tests PASSED
VACUOUSLY. After, they fail under three independent mutations (`Path.rglob`
empty, the `_repo_walk` enumerators empty, `EXCLUDED_DIRS` widened to a partial
collapse leaving 76 files). Each anchor checks TWO oracles - on disk AND actually
delivered to the scanning arm - so a decayed constant reports "anchor gone", not
"walk collapsed"; a `_MIN_SCANNED = 100` floor sits far below the true 2386/1260
so it tracks collapse, not roster.

**Suite:** `pytest tests -n 8` = 21639 passed, 97 skipped, 4921 subtests, 0
failed, exit 0. No `_live_surfaces_unchanged` error this run - consistent with
the window-dependent external-writer attribution, not evidence against it.

**Do NOT redo.** ADR-015 needs no amendment - both Watch-for items did exactly
what they were written to do. Do not add an anchor to the laning guard; set
equality already is one. Do not "fix" site 2's `ops/runtime/` skip as dead - it
is a no-op only under `tracked_only=True`, and still fires on the git-absent
fallback, which is the path RM-394's reds were on.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**No row is queued - pick one.** RM-392, RM-393, RM-394 and RM-395 all shipped
today, and ADR-015 records the decision behind the last two. The two known-open
items, neither adjudicated into a row:

1. **`tools/stop_claim_gate.py:38`** - `CLAIM_COUNT` has no counterfactual or
   citation suppression, unlike `CLAIM_FILE` (`:47-83`) which has both, so
   quoting a figure IN ORDER TO REFUTE IT re-fires every turn. Read the hazard
   its own comments name at `:74-77` before touching it.
2. **`tests/test_inbox_responder_runner.py`** - two defects in one module. `:214`
   asserts `_TMP_LOGS` non-empty, a positive control that cannot tell "the arms
   were skipped" from "the runner is broken" (it is the 1 residual error when git
   is off PATH). And `_live_surfaces_unchanged` is non-hermetic against a LIVE RC
   appending to `ops/runtime` mid-suite - measured three times on 2026-09-09,
   absent on a fourth run, so it is window-dependent by construction.

---

# 2026-09-09f - ADR-015 written: the record _repo_walk never had, and the reason a ledger row alone would not have worked

Fourth row of the same headless day, operator AWAY. Docs-only, Tier-0: no code,
no test, no `ENGINE_VERSION` bump, no DS bounce, nothing outward. LEDGER 1377.

**The code was never the gap.** `tests/_repo_walk.py` shipped 2026-09-07 in
`a0a23b57c` carrying a real decision - git index first, `EXCLUDED_DIRS` as
backstop, `tracked_relpaths()` returning `None` never an empty set - with its own
anti-vacuity guard and four consumers, and NO ledger row, NO ADR, NO `CLAUDE.md`
line. Two days later RM-394 proposed re-deciding the universe from scratch
because nobody could find the decision that had already been made.

**A ledger row alone would not have fixed that, so this is three places.**
`docs/adr/ADR-015-shared-repo-enumeration.md` plus an index row and a Test guards
line in the reading order (the ADR index is what `CLAUDE.md` declares as "before
re-litigating a past choice, check here first"), and ONE rule line in the
`CLAUDE.md` Testing Discipline section - because the moment discoverability has
to work is the moment somebody is WRITING a new root-walking guard, and that is
the file auto-loaded then. The ledger is append-only history 1377 entries deep,
findable only by someone who already knows what to grep for: exactly the reader
RM-394 proved does not exist.

**The ADR records the trade-off, not a sales pitch.** Untracked new `.py` is
invisible until staged (and staged is what the hook and CI see). Alternatives
named with why they lose. And the failure mode the decision CREATES is in Watch
for: converting an empty-set-safe assertion can turn a machine-local RED into a
silent always-GREEN, measured at 56 passed during RM-394.

**RM-395 filed for the two holdouts - and the gate made it a better row than I
wrote.** I filed one of them as safe; BOTH are green by luck.
`tests/test_dead_endpoint_cleanup_item186.py:199` walks **9112 `.py`, 4772 (52
percent) inside the gitignored export copies**, its two filters removing ZERO
files today. My "green because the symbols are absent there" was REFUTED - they
are PRESENT, in each export tree's copy of that guard file, which its path-exact
self-exemption misses. It is green because no line there carries both `import`
and a deleted symbol: one line-shape from a phantom. And the hazard is TIME - an
export is a snapshot of an OLDER repo. `tests/test_laning_verdict_flip_retired.py:85`
I called safe-by-accident on `ops`; also refuted as understated - it does not
skip `python-embed` and walks **2082 files, 1685 (81 percent) vendored
`python-embed`**. Bound corrected too: a stronger AST resolver finds **2** root
walkers against **39** subdirectory walks; my "11 files, 9 subdirectory" was a
receiver-name-heuristic artifact. Two is the whole set, both passes.

**A guard caught my id allocation, same lesson one size down.** I checked RM-395
was free with `grep -c RM-395` over BACKLOG / ROADMAP / LEDGER, got 0, called it
free. `tests/test_rm_id_registry_drift.py` went RED: `docs/DS_SWEEP_TRACKER.md:72`
already PINNED RM-395 as next-free. A grep finding no ROW body is not a claim
about the registry. The pin was advanced with the allocation recorded beside it
in the same commit. **Take an RM id from that registry, never from a grep** - and
do NOT recite the advanced figure in prose elsewhere: writing it into the LEDGER
entry made the same guard red a second time, because the classifier reads a bare
id as an ALLOCATION unless a "next free" cue precedes it. ROADMAP's eleven
next-free pointers were left alone - NOT because they defer to the tracker (only
three of the eleven do; the gate refuted that reason) but because RM-316 already
owns them.

**Do NOT redo.** Do not convert those two here - RM-395 owns them, and both are
`assert not offenders` shapes that MUST be anchored before conversion. Do not
turn a grep for `rglob` into a repo-wide rewrite: 11 AST hits, 9 of them
SUBDIRECTORY walks that need nothing. Two is the whole set.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**The next row is RM-395** - small, bounded, fully measured above, and the ONLY
thing it needs that is not already written down is the anchor decision: for each
of the two guards, state whether an EMPTY enumeration would PASS its assertion
before you convert it, and add the anchor where it would. Read ADR-015 first.

**Also open, neither adjudicated into a row:** `tools/stop_claim_gate.py:38`
(`CLAIM_COUNT` has no counterfactual or citation suppression, unlike `CLAIM_FILE`
at `:47-83`, so quoting a figure IN ORDER TO REFUTE IT re-fires every turn - read
the hazard its own comments name at `:74-77` first); and
`tests/test_inbox_responder_runner.py:214`, whose `_TMP_LOGS` positive control
cannot tell "the arms were skipped" from "the runner is broken", in a module
measured today to be non-hermetic against a LIVE RC writing `ops/runtime`
mid-suite.

---

# 2026-09-09e - RM-394 SHIPPED: the decision was already made in code, and the gate caught the conversion trading a red for a silent green

Third row of the same headless day, operator AWAY. Tier-1: seven test-support
files, no engine, no `ENGINE_VERSION` bump, no DS bounce, nothing outward.
LEDGER 1376. Five parallel single-file slices, one merger, TWO read-only gates
before the commit - and the second gate existed only because the first one's
repairs were written after it ran.

**The row asked which universe to build. Neither had to be built.**
`tests/_repo_walk.py` already implements the tracked-set-primary answer, with
`EXCLUDED_DIRS` as a backstop and `tracked_relpaths()` returning `None` (never an
empty set) on git failure, plus its own anti-vacuity guard and four consumers.
**Settled as CODE, not as a recorded decision** - added in `a0a23b57c`
(2026-09-07, public-flip scrub) with no ledger row naming it, which is exactly
how five guards kept hand-rolling their own root walks beside it. So the fix was
ADOPTION, not invention.

**All five converted**, plus `responder_export` added to the shared
`EXCLUDED_DIRS` for the git-absent fallback - one entry in one shared list, which
is the whole difference from the per-file hand-list the row rejects. Notable
local call: `docs` was the only genuinely non-infrastructure skip anywhere in the
five, and it was DROPPED after measuring that `pytest.ini` `norecursedirs` does
not exclude `docs`, so a test landing there really would be collected and really
would belong in the scan.

**The gate refuted the claim that mattered.** I claimed none of the five could
pass on an empty enumeration. Four cannot. `test_skip_condition_hygiene.py`
COULD - `discovered - set(_TEST_TREES)` is empty-set-safe, and forcing the
enumeration empty left it at 56 passed. Unrepaired, the conversion would have
traded a machine-local RED for a silent always-GREEN, which is worse than what it
fixed. Anchored on the directory holding the guard itself
(`assert "tests" in discovered`, asserted against the DISK so it is not circular
with `_TEST_TREES`) and proven to bite by my own mutation probe. The gate's
second finding: the new `EXCLUDED_DIRS` entry was pinned only indirectly by
another guard's fixture, so `tests/test_repo_walk.py` pins it directly now.
**Both repairs were added AFTER gate 1, so a SECOND gate ran over them and the
docs - and it found two more defects, both in the post-gate material**: the
header said six changed `.py` when repair 2 made it seven, and the row still
carried gate 1's "the only failure across all six files" three sentences after
describing the repair that makes it two. LEDGER 1374 paid for this exact lesson
two rows ago; it took a third payment to actually gate the post-gate material.

**Counts, all re-derived against the OLD algorithms on this disk and all held:**
8 phantom trees, 34 phantom ctor sites, 50 unclassified builders, 36 frozen
headers of which 24 under `responder_export` (12 modules x 2 export trees). New:
12 headers, the 4 real test trees, 17 ctor sites = `CONSTRUCT_FILES`, 17 census
entries with 0 unclassified and 0 stale.

**Suite:** `pytest tests -n 8` = 21639 passed, 97 skipped, 4921 subtests, 0
failed. Three whole-suite runs agreed on every count and DISAGREED on one ERROR
(`_live_surfaces_unchanged` teardown, "live surfaces moved") - present in mine,
absent in gate 1, present in gate 2. That disagreement IS the evidence: the LIVE
RC process was measured appending to `ops/runtime/responder_metrics.jsonl` inside
the suite window, a fresh cycle row every five minutes from a changing pid.
External writer, not a regression - the responder runner module is non-hermetic
against a live RC.

**Do NOT redo.** Do not delete the `responder_export` trees. Do not extend any
hand-list. Do not "tidy" the two cosmetic divergences between the five slices
(`relative_posix` versus `p.relative_to(...).as_posix()`, one positional
`patterns`) - no behavioural effect, and churn on five freshly converted guards
is not worth it. Do not re-derive the phantom counts.

## NEXT SESSION - HEADLESS, operator away

Same shape: orchestrated, multi-agent, self-adjudicating, self-adversarial. ONE
row per cycle, gate BEFORE the irreversible act, commit, push, LEDGER entry.
The RC <-> RSC exchange is the only outward scope; `CS`, `LW` and `LL` are on
operator-ordered STANDBY and their silence is STANDBY, never dissent. ARMING is
never adjudicated - if a row needs it, say so and move on.

**No row is queued - pick one.** RM-392, RM-393 and RM-394 all shipped today.
The three known-open items, none of them adjudicated into a row yet:

1. **`tests/_repo_walk.py` has no ledger row and four-plus-five consumers now.**
   That is the condition that caused RM-394: a settled decision nobody could
   find. Writing its row is cheap and prevents the next five divergent walks.
2. **`tools/stop_claim_gate.py:38`** - `CLAIM_COUNT` has no counterfactual or
   citation suppression, unlike `CLAIM_FILE` (`:47-83`) which has both, so
   quoting a figure IN ORDER TO REFUTE IT re-fires every turn. Note the hazard
   its own comments name at `:74-77` before touching it.
3. **`tests/test_inbox_responder_runner.py:214`** - the `_live_surfaces_unchanged`
   teardown asserts `_TMP_LOGS` non-empty, a positive control that cannot tell
   "the arms were skipped" from "the runner is broken"; it is the 1 residual
   error when git is off PATH. And the same fixture is non-hermetic against a
   LIVE RC writing `ops/runtime` mid-suite, measured today.
