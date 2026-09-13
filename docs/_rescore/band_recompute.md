# Band recompute - RC's headlines under BOTH individuation conventions, plus a v1.3 conformance check

Read-only measurement pass. Produced by `docs/_rescore/band_recompute.py`, run
as:

```
<project-python> docs/_rescore/band_recompute.py
```

from the repo root, with the project Python named in CLAUDE.md under Paths.
Exit code 0, zero blocking parse problems, zero malformed rows.

Every figure in this file is tagged MEASURED-THIS-RUN, DERIVED, or ATTRIBUTED.
Nothing is carried forward from a scorer's summary.

**The script imports `tally.parse_rows` rather than re-implementing the parser.**
Two ends of a band must come out of the same extraction, or the band measures
the parser instead of the convention.

---

## 0. The fine end is reproduced before any band is printed

The script refuses to print a band unless it first re-derives the four
`tally_report.md` figures from the rows. MEASURED-THIS-RUN:

| quantity | tally_report.md | this run | verdict |
|---|---|---|---|
| gate-or-contract share | 85.4 pct | 85.4 pct (169 of 198) | MATCH |
| inherited share | 48.5 pct | 48.5 pct (96 of 198) | MATCH |
| BORN-WRONG : DECAYED | 2.62 : 1 | 2.62 : 1 (55 : 21) | MATCH |
| fix-of-a-fix share | 12.1 pct | 12.1 pct (24 of 198) | MATCH |

The brief's restatement of these four was therefore not trusted; it was
checked, and it is correct.

---

## 1. The coarse convention, and the aggregation rule for each field

**Coarse N = 40** (MEASURED-THIS-RUN): distinct LEDGER entries carrying at
least one row. The window is 1365 to 1406, 42 entries; entries 1382 and 1405
carry zero rows and both zeroes were flagged deliberately by their scorer, as
`tally_report.md` section 5 records. Rows per entry range from 1 to 15.

LW's coarse re-derivation ran at N=45 against their fine N=124, a 2.76x
collapse. RC's is 40 against 198, a 4.95x collapse - **RC's fine rows are
almost twice as finely individuated per entry as LW's**, which is itself a
reason the two trees' point estimates were never comparable (DERIVED from
198/40 against LW's ATTRIBUTED 124/45).

### Aggregation rule per field, and why

**gate-or-contract, inherited, fix-of-a-fix: ANY-OF.** An entry counts for the
bucket if ANY of its rows carries a qualifying value. Justification: this is
the rule LW's own prose describes when pricing FATAL-1 - "collapsing rows makes
'did ANY link need a further fix' monotonically more likely to be true"
(ATTRIBUTED TO LW, `REFUTATION_TAXONOMY_PIN_v1_3.md` clause 1). Any other rule
(majority, first-row, most-severe) would produce a coarse end that is not the
same measurement LW made, and the band would not be comparable to theirs.

**BORN-WRONG : DECAYED: ANY-OF on each sub-value INDEPENDENTLY**, so one entry
can count toward both. A PRECEDENCE variant (BORN-WRONG outranks DECAYED when
both appear under one entry) is computed beside it because the choice moves the
ratio hard, and a reader is entitled to see that it does.

**`prevention` as a per-entry distribution: THE CHOICE IS ITSELF A FINDING, so
both are reported.** A per-entry `prevention` value requires either a
precedence order or an any-of rule, and the two give qualitatively different
answers:

- **ANY-OF** (an entry appears in every bucket present among its rows, so the
  columns sum to more than N) puts CONTRACT first at 31 of 40 and GATE-ABSENT
  second at 27 of 40.
- **v1.3 clause 2 FIRST-MATCH precedence** (exactly one bucket per entry, sums
  to N) puts **GATE-FIRED-CAUGHT first at 15 of 40**, with GATE-ABSENT down to
  4 and CONTRACT down to 4.

Both MEASURED-THIS-RUN. **Under v1.3's own precedence order, applied at the
coarse grain, RC's leading `prevention` bucket is neither of the two buckets the
fine end argues about.** That is a direct consequence of clause 2 ranking
GATE-FIRED-CAUGHT first: at entry grain, almost any entry containing a
gate-caught event becomes a gate-caught entry. It is a strong argument that
`prevention` should never be published at the coarse grain at all, and RC does
not publish it that way below.

---

## 2. The bands

All MEASURED-THIS-RUN. Fine end = one row per claim, N=198. Coarse end = one
event per ledger entry, N=40.

| quantity | fine (N=198) | coarse (N=40) | BAND |
|---|---|---|---|
| gate or contract reachable | 85.4 pct | 95.0 pct (38 of 40) | **85.4 to 95.0 pct** |
| inherited from a durable record | 48.5 pct | 85.0 pct (34 of 40) | **48.5 to 85.0 pct** |
| BORN-WRONG : DECAYED | 2.62 : 1 (55 : 21) | 1.73 : 1 (26 : 15) any-of | **1.73 to 2.62 : 1** |
| fix-of-a-fix | 12.1 pct | 47.5 pct (19 of 40) | **12.1 to 47.5 pct** |

Sensitivity on the one field where the aggregation rule is contestable: under
the PRECEDENCE variant the coarse BORN-WRONG : DECAYED is **5.2 : 1** (26 : 5),
not 1.73 : 1. **The ratio moves by a factor of three on the aggregation rule
alone**, at a fixed convention and a fixed corpus. That is a second
individuation-sensitivity finding sitting underneath LW's FATAL-1, and it is
not covered by v1.3: clause 1 defines the event, and says nothing about how
sub-values aggregate when a coarser reader collapses events. RC reports the
ANY-OF number in the band above because it is the rule used for every other
field in this pass, and flags the precedence number here rather than choosing
silently.

**RC's coarse movement is the same direction and the same order as LW's.**
ATTRIBUTED TO LW: gate-or-contract 82.3 to 93.3, inherited 62.9 to 80.0,
fix-of-a-fix 24.2 to 46.7. RC MEASURED-THIS-RUN: 85.4 to 95.0, 48.5 to 85.0,
12.1 to 47.5. **The fix-of-a-fix band is the most violent in both trees, and
the two coarse ends nearly coincide (47.5 against 46.7) while the two fine ends
differ by a factor of two (12.1 against 24.2).** DERIVED: that is what a
convention artifact looks like, and it is evidence for LW's claim that the
apparent cross-tree gap in this quantity was never measured.

---

## 3. CONFORMANCE CHECK against v1.3 clause 1

v1.3 clause 1: "An EVENT is one CLAIM shown to be wrong. Individuate by the
CLAIM, not by the artifact, the root cause, the fix, or the ledger entry."
(ATTRIBUTED TO LW.)

### Method

24 rows, 6 per chunk, selected by a deterministic rule fixed before any row body
was read and printed by the script:
`index(k) = round((k-1)*(N-1)/5) + 1` over each chunk's rows in file order. The
stride differs from the adjudication pass's, so the two samples are not the same
rows. Each sampled `claim` field was then read and classified BY-CLAIM,
BY-ARTIFACT, BY-FIX or AMBIGUOUS.

### Result, MEASURED-THIS-RUN over 24 rows

| classification | count |
|---|---|
| BY-CLAIM (conformant) | 22 |
| BY-ARTIFACT | 1 |
| BY-FIX | 0 |
| AMBIGUOUS (under-split) | 1 |

The two non-conformant rows, named:

- **`chunk1-48` - BY-ARTIFACT.** Its `claim` is "the filed row's body, naming
  three terminal states". Its own `refuter` then splits that body three ways:
  two of the three had shipped closed, and the third "was never this row's
  class". Three separately assertable claims with distinct truth conditions,
  and two distinct reasons for being wrong, collapsed into one row. Under
  clause 1 this is at least 2 events and arguably 3. The row's own `uncertain`
  line already says so, proposing BORN-WRONG for the third clause against
  DECAYED for the other two.
- **`chunk3-38` - AMBIGUOUS.** `claim` is "that RM-387 or RM-388 are open work
  to pick up". Two ids, two separately assertable claims, refuted by one fact
  (both had shipped). A strict clause-1 reader emits two events; a reader who
  treats the fallback sentence as one assertion emits one. The contract does
  not break this tie, so it is reported rather than resolved.

### Verdict, stated plainly

**RC's fine end is APPROXIMATELY v1.3-conformant on clause 1, not exactly
conformant.** 22 of 24 sampled rows individuate by the claim. Three further
things are worth stating because they bear on the direction of the residual
error:

1. **Zero rows individuate by FIX, and that is structural rather than lucky.**
   All four scorer preambles state the FORWARD reading explicitly and fold a
   refuted remedy into `fix_chain` instead of emitting it as a row
   (MEASURED-THIS-RUN by reading all four preambles; corroborated by entry 1382
   carrying zero rows for exactly this reason, `tally_report.md` section 5).
   Clause 1's "not by the fix" is already satisfied corpus-wide.
2. **Zero rows individuate by ENTRY.** 198 rows over 40 entries, up to 15 rows
   on one entry. One chunk's preamble states a clause-1-shaped event definition
   outright, before v1.3 existed - "a point where a CLAIM made in the course of
   the work was contradicted, corrected, retracted or found wrong"
   (MEASURED-THIS-RUN by reading the chunk4 preamble) - and flags its own
   `pin_gap` on `chunk4-25` saying two readings of section 6 give different
   counts. That is a scorer independently locating FATAL-1 in its own work while
   scoring under v1.2.
3. **Where RC does deviate, it deviates by UNDER-splitting, never by
   over-splitting.** Both exceptions collapse several claims into one row.
   DERIVED consequence: **RC's fine N=198 is a FLOOR under v1.3, and a fully
   clause-1-conformant re-score would move RC's fine end further from its
   coarse end, not closer.** RC's band would widen, not narrow.

Counter-evidence checked rather than assumed: `chunk2-43`, `chunk2-44` and
`chunk2-45` all come from ONE artifact - one filed item's report - and are
three separate rows, one for its figures, one for its characterisation of the
population, one for the alternative it proposed. Clause 1 says that is CORRECT -
"two claims
with distinct truth conditions that were separately assertable and separately
wrong are TWO events even when one pass, one artifact and one root cause
produced both". So the corpus contains a worked example of the clause being
satisfied in the hard direction, not only in the easy one.

---

## 4. The other four clauses - how many existing rows would CHANGE

### CLAUSE 2, `prevention` precedence order: PARTIALLY EVALUABLE, upper bound 31 of 198

The rows record the value a scorer chose, not the full fact pattern, so a firm
per-row delta is not derivable without re-reading the ledger. Two bounded
populations are (MEASURED-THIS-RUN):

- **18 rows sit in `PROXY-MEASURE`.** Clause 2 reserves that value for an
  instrument that actually RAN and whose correct answer was taken for an answer
  to a different question. Any of the 18 where no instrument ran must move to
  `GATE-EXISTING` with vacuity in `prevention_why`. Upper bound 18, firm count
  unmeasured.
- **13 rows are NOT scored `GATE-FIRED-CAUGHT` while their `refuter` field
  names a standing check, gate, hook, CI run or verifier**: `chunk1-02`,
  `chunk1-03`, `chunk1-05`, `chunk1-15`, `chunk1-16`, `chunk1-27`, `chunk1-32`,
  `chunk1-52`, `chunk2-37`, `chunk2-47`, `chunk3-03`, `chunk3-30`, `chunk3-41`.
  Clause 2 ranks `GATE-FIRED-CAUGHT` FIRST, so each is a candidate to move.
  This is a text match over the `refuter` field, so it is an upper bound and
  carries false positives.

**Corroboration from an independent pass:** the adjudication found exactly this
defect as its GAP 1 and named 3 affected rows in a 40-row sample (ATTRIBUTED TO
adjudication A: `chunk1-27`, `chunk3-06`, `chunk3-32`). `chunk1-27` appears in
both lists, found by two methods that share no mechanism. The adjudication also
found the scorers internally inconsistent on this exact question -
`chunk1-37/-47/-50/-51` score a verifier catch as `GATE-FIRED-CAUGHT` while
`chunk1-27/chunk3-06/chunk3-32` do not.

**Clause 2 is the clause that would move RC's most-argued-about number**, and
at the coarse grain it moves it decisively (section 1 above).

Already conformant and needing no change: **3 rows** carry `GATE-EXISTING` with
a `prevention_why` beginning VACUOUS, which is exactly where clause 2 says
vacuity belongs.

### CLAUSE 3, per-link `chain_kind` LIST: FULLY EVALUABLE, 3 rows change shape, 0 change the headline

MEASURED-THIS-RUN. Rows with more than one link, which therefore carry a scalar
kind covering several links:

| row | fix_chain | filed chain_kind |
|---|---|---|
| `chunk1-32` | 2 | SELF |
| `chunk1-42` | 3 | SIBLING-SURFACE |
| `chunk1-60` | 2 | SELF |

Those 3 rows must be re-expressed as lists. **Ratio MEMBERSHIP changes for
nobody: the corpus carries 0 `SAME-ARTIFACT` rows** (MEASURED-THIS-RUN,
independently reported by `tally_report.md`), and clause 3's rule is "counts if
ANY link is not SAME-ARTIFACT". **RC's fix-of-a-fix band is therefore invariant
under clause 3.** RC cannot claim that as a virtue - it is invariant because
RC never used the value whose ambiguity clause 3 repairs, so RC is a tree on
which this fatal could not have been detected.

### CLAUSE 4, correctness filter on a link: UNEVALUABLE, population at risk 24 rows / 28 links

**UNEVALUABLE from the rows, and the reason is structural: v1.2 supplied no
per-link correctness field, so the rows do not carry the datum clause 4 needs.**
Deciding it requires re-reading the ledger for each of the 28 links and judging
whether the refutation OF THE REMEDY was itself correct. Bounds
MEASURED-THIS-RUN: 24 rows carry `fix_chain >= 1`, 28 links in total, so the
delta lies in 0 to 28 links across 0 to 24 rows, which is 0 to 12.1 points of
the fine fix-of-a-fix share.

The delta is known to be **strictly greater than zero in at least one case**:
`correct_field_probe.md` locates an entry-1371 chain whose own ledger headline
reads that the correction was false too, and an entry-1385 into 1386 chain where
the correction was refuted a second time (ATTRIBUTED TO that probe, which cites
the entries). Whether those links survive clause 4 is exactly the judgement the
rows cannot make.

### CLAUSE 5, an in-session agent report is FRESH: PARTIALLY EVALUABLE, upper bound 22 of 198

MEASURED-THIS-RUN by text match over the `claim` and `refuter` fields for
subagent, verifier, slice, parallel-agent, adjudicator, auditor and scorer
mentions:

- **22 rows are `INHERITED` and mention an in-session agent artifact.** Each is
  a candidate to move to `FRESH` under clause 5, unless its source was written
  durably before being acted on. Ids: `chunk1-04`, `chunk1-47`, `chunk1-52`,
  `chunk2-17`, `chunk2-35`, `chunk2-39`, `chunk2-41`, `chunk3-06`, `chunk3-31`,
  `chunk4-03`, `chunk4-05`, `chunk4-06`, `chunk4-07`, `chunk4-08`, `chunk4-10`,
  `chunk4-13`, `chunk4-23`, `chunk4-24`, `chunk4-28`, `chunk4-33`, `chunk4-41`,
  `chunk4-43`.
- 26 rows are already `FRESH` and mention one, which is the conformant
  direction and needs no change.

Upper bound 22 rows, or 11.1 points off the fine inherited share of 48.5 pct.
Firm count unmeasured, because "written durably before being acted on" is not a
field the rows carry. **LW is right that this clause is worth more to an
orchestrated tree**: 22 candidate rows is more than RC's entire
`GATE-EXISTING` bucket, and 13 of the 22 sit in one chunk.

### Summary of clause deltas

| clause | evaluable? | rows that would CHANGE |
|---|---|---|
| 1, event = one claim | yes, by sample | 2 of 24 sampled (1 firm, 1 ambiguous); corpus-wide unmeasured |
| 2, prevention precedence | partially | upper bound 31 of 198; firm count needs a ledger re-read |
| 3, per-link chain_kind | fully | 3 of 198 change shape, 0 change any published figure |
| 4, link correctness filter | **UNEVALUABLE** | population at risk 24 rows / 28 links |
| 5, agent report is FRESH | partially | upper bound 22 of 198 |

---

## 5. RC's own published positions, re-measured

MEASURED-THIS-RUN from the same rows:

| RC published | measured under the contract |
|---|---|
| a 30.1 pct RECORD-DECAY axis | inherited is 48.5 pct fine / 85.0 pct coarse; **DECAYED alone is 21 of 198 = 10.6 pct**, and 21.9 pct of the inherited half |
| the binding constraint is WHEN checks run, not WHICH exist | **GATE-ABSENT 65 against GATE-EXISTING 17 = 3.82 : 1 toward never-graded** (fine); 27 against 10 = 2.7 : 1 (coarse any-of) |

Both re-measurements contradict the published position, and neither is a
nuance. They are written up as such in the outbound note.

ATTRIBUTED TO LW for comparison: their gate family splits 2.2 to 1 toward
ABSENT, and their inherited share is 62.9 to 80.0 pct. RC's 3.82 to 1 is the
same direction and larger.

---

## 6. LIMITS of this pass

1. **This pass inherits every limit of `tally_report.md`**, because it reads the
   same rows through the same parser. It cannot detect a shared misreading, it
   does not re-read the ledger, and every count is a FLOOR.
2. **The coarse end is a CONVENTION, not a better measurement.** Neither end of
   any band above is RC's "real" number. That is the point of publishing a band.
3. **The clause-1 conformance figure rests on 24 rows.** 22 of 24 supports
   "approximately conformant"; it does not support a corpus-wide percentage,
   and none is offered.
4. **The clause-2 and clause-5 deltas are text-match upper bounds** and contain
   false positives by construction. They bound the movement; they do not
   measure it.
5. **Clause 4 is unevaluable and will stay unevaluable** until either RC
   re-reads 28 links against the ledger or the rows gain a per-link correctness
   field. No estimate is offered in its place.
6. **RC has not re-scored under v1.3 and this pass is not a re-score.** It
   measures the distance between RC's existing rows and v1.3. Closing that
   distance is a third scoring pass, which RC is deliberately not doing while
   v1.3 is still under attack.
