# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-12, the discovery-axis + inter-scorer wrap (relocated `2026-09-12b` the five-slice merge and `2026-09-12a` RM-412 C1 OSS extraction, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 961" - read those counts off the tool's own output, never off a recollection; newest 3 = `2026-09-12e` this wrap, `2026-09-12d` the fleet tooling-tier lane, `2026-09-12c` the prior SESSION WRAP doc-sync). The pass before this one relocated `2026-09-11d`, the one before that `2026-09-11c`, and the one before that `2026-09-11b` and `2026-09-11a`, the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-12e - Discovery axis verified, RM-408 shipped, and an n=60 inter-scorer experiment that CONFIRMED LW and found five defects of RC's own

Four commits, NONE PUSHED (the merger pushes): `0d1528b8b` (RM-408 planted-specimen control), `56cd1fdac` (discovery-axis verification), `3434990c0` (n=60 pre-registration), `a489a816d` (the n=60 result). LEDGER 1414. Tier-1: one new test file, zero production files, the rest docs. ENGINE-IMPACT NONE.

**RM-408 SHIPPED and the instrument was PROVEN BY MUTATION, not self-graded.** `tests/test_live_write_tracer_selftest.py`, 6 tests. Positive arms through the `builtins.open` append route, the `os.replace` atomic route and the pathlib route; TWO negative specimens outside every watched root; scrub before the report is built; anti-vacuous evidence graded against a SECOND ORACLE (on-disk sizes plus patch-identity flags); a regeneration arm re-firing the control twice in one process. **The proof: deleting `io.open = traced_open` reds exactly three named arms and drops the report from 3 files to 2 - reproduced independently by a verifier.** **`tools/live_write_tracer.py` IS UNCHANGED** - the `io.open` pathlib patch was confirmed already present at `:489-495` and MEASURED rather than re-plumbed. BOTH drained operator steers landed in this one row, so there is NO separate recovery pass. The merger added one cleanup line so the control leaves no `_scratch` directory, verified against a pre-existing non-empty `_scratch`. Limits NOT claimed away, and in the module docstring: subprocess blindness, and routes-fire is not watch-set-complete.

**DISCOVERY AXIS** (`docs/DISCOVERY_AXIS_RC_2026-09-13.md`). LW's RC-attributed claims verified: **36 GATE-FIRED-CAUGHT rows and 29 of them SELF-AUDIT, both CONFIRMED by two independent routes.** **RC's OWN published +9.0 union arm does NOT reproduce at ROW grain** - its 18 movers are enumerated in no RC artifact; composition is reconstructable only at CLASS grain (8 PROXY-MEASURE pre-empted by rank 1 at `docs/_rescore/v13_attack_clauses2to5.md:187`, plus ADVERSARY = 10). A collision recorded rather than smoothed: two distinct routes both land on 170/198. **Part 3's headline was DOWNGRADED by RC's own refutation pass from CONFIRMED to NOT ESTABLISHED, and explicitly NOT to REFUTED**, because `discovery` and `refuter` were written by one scorer in one pass, making the tiebreaker circular; non-circular residue 3 rows. Two riding corrections: 6 unambiguous RUN rows to 5, and a "27 of 29" sentence that had swapped its own predicate.

**n=60 INTER-SCORER OVERLAP, PRE-REGISTERED BEFORE ANY ROW WAS SCORED** (`docs/_overlap/PREREGISTRATION.md`): deterministic seedless interleaved selection, longest same-chunk run 1 so scorer is FULLY CROSSED with chunk - repairing a confound LW reported against LW's own design - mechanically verified blinding, confirm/refute thresholds pinned in advance. **RESULT** (`docs/_overlap/RESULT.md`): three blind scorers, 60 rows, LW's convention v1 unamended. `prevention` SET identity per row: A-B 44/60, A-C 48/60, B-C 41/60; pooled 133/180 agree, 47/180 = 26.1111 pct disagree; **verdict CONFIRMED against the pinned bars**, and per the pre-registration's own section 8 that is the STRONGER verdict, since same-model scorers bias toward agreement. **THE HALF THAT MUST TRAVEL WITH IT: FAMILY grain is pooled 154/180 = 85.5556 pct agree, 14.4444 pct disagree, which FAILS the same 15.0 bar by 0.5556 points - INDETERMINATE at the grain RC itself argues the instrument underwrites.** LW asked to be refuted and RC's larger sample confirmed them instead.

**STRUCTURAL FINDING, reproduced independently by all three scorers: LW's convention CITES v1.2's eight `prevention` definitions and does not CONTAIN them.** Each scorer manufactured working definitions and diverged on the repair. Qualifier RC must keep: **RC's own harness forbade scorers from fetching v1.2, so part of that gap is RC's design.**

**FIVE DEFECTS OF RC'S OWN**, found by an independent pass over RC's own result, all recorded: (1) the FAMILY INDETERMINATE was absent until the refuter demanded it - RC applying its own reading selectively, in the direction flattering RC; (2) a FALSE sensitivity claim - the mixed-set rule is inert here, result ROBUST to both alternatives; (3) attribution overstated 19 of 23 to approximately 15 of 23, pooled 39-of-47 WITHDRAWN; (4) a blanket "nothing was counted by eye" that is false for the attribution section; (5) **a REAL BLINDING LEAK - `chunk1-04`'s retained `quote` carries the stripped `origin_time` value in plain prose, all three scorers returned it, and the name-only blinding check is structurally blind to that class**, so RC's 100.0 pct `origin_time` agreement may be inflated and must NOT be run as a clean contrast against LW's 89.7 pct. RSC argued exactly this hours earlier and gets the credit.

**DELIVERY:** two notes delivered to all four sibling inboxes, both verified DELIVERED 4 of 4 by content digest.

**NOT REPORTED, do not assume covered:** pre-registration item 7b, the per-chunk breakdown, Wilson intervals.

**DO NOT REDO.** (1) Do NOT re-propose the pre-dispatch re-grounding gate - measured-REFUTED, evidence `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`. (2) Do NOT re-score RC's corpus against contract v1.3 - LW has ENDED the clause set and recommends no tree score against those clauses. (3) Do NOT quote RC's WITHDRAWN bands; only fine-grain figures, and only with the aggregation rule named. (4) Do NOT "repair" the nine baselined `BACKLOG.md` citations - `_KNOWN_BROKEN` in `tests/test_citation_drift_guard_rm171.py`, with written reasons. (5) Do NOT re-plumb `tools/live_write_tracer.py` for pathlib - the patch is present at `:489-495` and was measured. (6) Do NOT quote the n=60 CONFIRMED verdict without its FAMILY-grain INDETERMINATE half.

**NEXT SESSION - open threads.** (a) **RSC has offered 96 rows that are BLIND BY CONSTRUCTION** - never scored, so there is no strip to trust - **and invited a scorer. That is the cleanest available input for the scorer term and the natural follow-on.** (b) Pre-registration 7b, the per-chunk breakdown and Wilson intervals remain UNADJUDICATED. (c) RM-422 and RM-423 remain OPEN; RM-423 is OPERATOR-GATED. (d) **`tests/test_citation_drift_guard_rm171.py::test_no_net_new_broken_citation` is RED AT HEAD and this wrap did NOT cause it - confirmed by stashing the wrap's edits and re-running, which still fails.** The one net-new entry is `docs/_overlap/sample_60_blinded.md -> ORCHESTRATION_PLAN.md:916-919`, landed by `3434990c0`; `ORCHESTRATION_PLAN.md` is NOT a tracked file. **It is a QUOTED citation inside a blinded corpus row** (`docs/_overlap/sample_60_blinded.md:117`, a scored row's own `claim` text), not a live citation the doc is making, so the repair is a `_KNOWN_BROKEN` entry WITH A REASON or a corpus exclusion for `docs/_overlap/`, NOT an edit to the blinded sample - editing that file would corrupt the frozen experiment corpus. Left for the merger because the guard file was outside this wrap's named file set.

---

# 2026-09-12d - Fleet tooling-tier: RC's OWN gate proposal back-tested and REFUTED, nine defects conceded, bands WITHDRAWN

Four commits, ALL PUSHED to `origin/main`: `e69266ca0` (back-test of RC's own re-grounding gate - it does not survive), `a87400677` (deliver the retraction to four trees), `89721455b` (corrections and the pinned re-score, published as a band), `d47d3dfb4` (attack v1.3, withdraw our own bands, upgrade the delivery check). LEDGER 1413.

**RC'S HIGHEST-LEVERAGE PUBLISHED RECOMMENDATION DID NOT SURVIVE ITS OWN BACK-TEST.** Cost arm: 18 of 20 sampled rows refused (90 pct), ZERO genuinely stale, ~91 benign false positives over 11 mechanisms, RM-id closure false positives 26 of 30 - refusal tracked citation DENSITY, not staleness. Back-test arm, 7 located instances: 3 CAUGHT, 3 MISSED, 1 PARTIAL, 2 UNGRADEABLE. The generalising result: **EVERY RESOLVER IS A PRESENCE CHECK OVER TOKENS A ROW NAMES, AND THIS DEFECT CLASS IS AN ABSENCE.** Evidence: `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`.

**NINE defects were established in RC's published measurement** (five found by peers, each re-derived independently here). WITHDRAWN: the "rot still compounds" inference (1.805 to 1.943 pct is constant), the "29 of 33" novelty claim (z = 1.81 against a chunk-size null), the claim that RC's window is a natural unit, and a back-test limit that was too generous to RC.

**RE-SCORE under the sibling contract:** 198 per-event rows, four independent scorers over disjoint LEDGER chunks 1365-1406, machine tally with ZERO claimed-versus-actual discrepancies, independently adjudicated 40-row sample (148 of 160 field comparisons agree). Gate-or-contract 85.4 pct fine; inherited 48.5 pct; BORN-WRONG to DECAYED 2.62 to 1; fix-of-a-fix 12.1 pct. **It CONTRADICTS two of RC's own published headlines:** the 30.1 pct "record decay" axis is the MINORITY half (decay alone 10.6 pct), so the sibling reframe to RECORD TRUST is right; and "the constraint is WHEN checks run, not WHICH exist" is contradicted by GATE-ABSENT to GATE-EXISTING at 3.82 to 1.

**CONTRACT.** RC audited the sibling scoring contract v1.2 and found 5 FATAL underspecifications, led by **THE CONTRACT NEVER DEFINES WHAT ONE EVENT IS**, so it never defines the denominator of every ratio it publishes; the owner conceded all five, priced that one at 22.5 points on their own corpus, and shipped v1.3. RC then ATTACKED v1.3 as its owner asked: 2 FATAL on clause 1, 3 FATAL on clauses 2-5. Worst: clause 2's precedence order is total as a RANKING but not as a DECISION PROCEDURE (predicates exist for ranks 1-4 only, and 126 of 198 rows, 63.6 pct, fall in an un-predicated tail), and clause 1 contradicts the unwithdrawn v1.2 section 6, moving N from 198 to 226.

**RC WITHDREW ITS OWN BANDS.** An aggregation sweep showed all four intervals NON-MONOTONIC, and the rule RC published for the ratio (any-of, 1.73) sits BELOW RC's fine value (2.62), so the interval ran backwards. Aggregation dominates individuation 4 of 4 here. **DELIVERY:** RC's self-check is clean (100 distinct notes, 0 delivery faults, 0 address-list omissions), and was upgraded to the stronger roster-versus-address-list check after a sibling showed the adopted check cannot see an OMITTED addressee.

**DO NOT REDO.** (1) Do NOT re-propose the pre-dispatch re-grounding gate - it was built as a proposal, back-tested, and measured-REFUTED; the evidence is `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`. (2) Do NOT re-score RC's corpus against v1.3 - RC deliberately has not, because the contract is still under attack and its owner asked that it be attacked BEFORE anyone scores against it. (3) Do NOT quote RC's bands - they are WITHDRAWN; only the fine-grain figures are quotable, and only with the aggregation rule named. (4) Do NOT "repair" the nine baselined citations in `BACKLOG.md` - they sit deliberately in `_KNOWN_BROKEN` in `tests/test_citation_drift_guard_rm171.py` with written reasons, and a repair attempt this session was REVERTED after the guard caught it. (5) RM-422 and RM-423 remain OPEN and untouched; RM-423 is OPERATOR-GATED.

**NEXT SESSION - two operator steers were DRAINED here and belong in the hand-off, not in this session's work:** (a) the live-write row gets NO separate recovery pass - fold a regeneration assertion into the SAME row, with an anti-vacuous positive control; (b) `tools/live_write_tracer.py` ALREADY patches `io.open` for the pathlib route, so do NOT re-plumb it - confirm with a MUTATION arm instead.

---

# 2026-09-12c - SESSION WRAP doc sync: LEDGER 1407-1412, two rows filed, and three of the merger's OWN errors written into the record

LEDGER 1407-1412. DOCS ONLY - six markdown files, zero production files, zero
test files, ENGINE-IMPACT NONE. Nothing pushed. The six unpushed commits this
wrap covers are `86e4d4f0f`, `93f0e3efc` + merge `910cf8204`, `1d6d1e882` +
`2dc0cff76`, `3b5038fcb`, `14c0eadd2` + merge `dd0f43f78`, `54743bec0`.

**WHAT SHIPPED, one line each.** 1407 - `tools/outbound_reciprocity_check.py`,
RC's own answer to a sibling's delivery defect: **0 undelivered of 87**, scored
on a CONTENT DIGEST never a name, read-only across the boundary pinned at the
syscall by `sys.addaudithook`. 1408 - the fifth sibling-name escape CLOSED
UNILATERALLY and `KNOWN_EXCEPTIONS` retired to `{}`. 1409 -
`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md`, N = 42 ledger entries. 1410 -
the sweep's TREE arm wired into CI behind a gate that cannot emit an unearned
green. 1411 - the RM-296d regression fixed by grading behaviour instead of
source text. 1412 - this wrap.

**THE DURABLE PART IS THAT THREE ERRORS WERE THE MERGER'S OWN, and all three
are in `docs/LEDGER.md` rather than smoothed away.**
1. **A CRLF defect was ASSERTED into `oss/win32_atomic_io/LICENSE` and it does
   not exist.** Re-measured: **12115 bytes, CR 0, LF 219**. The "219 CR" was the
   file's LINE COUNT from a `grep -c` whose pattern degraded to empty. The
   FIRST measurement was right and said 0; the second was run because the first
   disagreed with a hypothesis already held, and was promoted over it without a
   cross-check. **`feedback_empty_grep_is_a_claim_about_the_pattern` INVERTED -
   a FULL-COUNT grep is equally a claim about the pattern**, and a count that
   matches a plausible expected magnitude is the most dangerous output the tool
   produces. Re-derive by a different mechanism whenever a re-measurement
   overturns an earlier one in the direction you wanted.
2. **Two agents were dispatched into the MAIN TREE concurrently**, against
   `feedback_verifier_needs_a_frozen_tree`. One saw the other's writes, watched
   the modified-file count move under it, and **misattributed them to an
   unrelated interactive session**. Numbers were re-derived and stand, but the
   second pass is what is relied on. **The main tree is a shared mutable
   resource; if two agents must run, at most one of them writes.**
3. **"Roughly 10 tree-scope findings" was the wrong SCOPE and reads as a live
   leak.** Those were **DIFF-arm** hits over **200-plus commits of
   ALREADY-PUBLISHED history** - commit messages and historical added lines.
   **Tree scope is 0 before and 0 after.** Re-measured at the end of this wrap
   with the sweep FULLY ARMED (4 name slots, 4 counterparty codes from
   per-host config): **clean, 630763605 bytes, 4762 files, 0 commit messages,
   482 binary/LFS blobs not content-scanned, exit 0.**

**TWO ROWS FILED to `BACKLOG.md` ("Reliability / hardening"), pin advanced by
TWO in `docs/DS_SWEEP_TRACKER.md` and `ROADMAP.md` in the same commit.**
**RM-422** - `core.longpaths` UNSET at local, global AND system scope; longest
tracked path **154 chars** (all five longest under
`docs/_archive/2026-07-26-orphaned-audit-drops/`); clone-ROOT budget therefore
**105 chars** at MAX_PATH 260. The session scratchpad root is 114, which is why
a checkout there aborted partway - and a later enumeration over the directory
the abort left MISSING printed a clean total, **a vacuous measurement arriving
through the filesystem rather than through a glob**. Fix has a CONFIG half and
a PATH-LENGTH half; the row refuses to pick one. **RM-423** - OPERATOR-GATED,
**no default recommended**: the lane refs cannot be pushed while the sweep
re-scans already-published history on every lane push. The bytes are already on
`origin/main` and all six lane worktrees sit at `86e4d4f0f`, an ancestor of it,
so nothing is stranded today.

**`CLAUDE.md` corrected at EXACTLY ONE sentence** - the Session Default block
still claimed the fifth escape "remains as a KNOWN, NAMED, VISIBLE exception
(declared in the tool)" while the tool's register is `{}`. Replaced with the
measured close plus an explicit do-not-restore. 53296 bytes, budget 61440.

**`ROADMAP.md` 72941 -> 75744 bytes** (budget 81920). Three rows relocated
VERBATIM to a new `## 2026-09-12b` block in `docs/ROADMAP_HISTORY.md`: the
FIFTH ESCAPE row, the five-slice announcement row, and the RM-420 FILED row -
**6261 chars relocated against six new rows added, so the pass ended NET
POSITIVE by 2803 bytes and is recorded as such rather than being forced to a
net reduction by gutting fences.** Every id and every fence stayed reachable.

**NEXT SESSION.** Nothing is blocked. The six commits above are still UNPUSHED
by instruction - **read RM-423 before pushing anything**, because the lane refs
and `main` are different questions and only one of them is gated. Do NOT
re-spell the next-free id in a ledger entry; a bare mention classifies as an
ALLOCATION and collides with the pin it announces
(`tests/test_rm_id_registry_drift.py`).
