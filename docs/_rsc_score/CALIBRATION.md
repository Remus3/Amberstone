# CALIBRATION - RC scoring convention v1 re-applied to RC's own 198 published rows

**Status: COMPLETE. Verdict: NOT CALIBRATED, 0 of 4 anchors reproduced.** The
method, blinding and script-audit sections were written and committed
(`d77b02d6b`) BEFORE any scored row existed; sections 4 through 7 were added
after the tally and changed nothing above them. This file was written
incrementally on purpose: a partial calibration that states its own coverage
honestly is worth more than a complete one that is never committed.

**The headline is in section 4, ABOVE the anchor table, because it cuts against
RC and a finding against the author does not get filed under the numbers.** RC
criticised a sibling for naming eight `prevention` values
without defining them, defined all eight with boundary cases, and its own three
scorers then independently reported that the undefined term RELOCATED into the
predicates that arbitrate between the eight. Read section 7 first.

This is the validation step required by `PREREGISTRATION.md` section 2. The
instrument under test is `RC_SCORING_CONVENTION_v1.md` (committed `73aef40c8`),
applied EXACTLY as written. It was not amended, and no amendment was requested.

**No row of the target sibling's corpus was read at any point in this pass.**
That corpus is not present in this tree. The constraint is structurally
satisfied, not merely observed.

---

## 1. The harness - reused, not rewritten

`docs/_rsc_score/calibrate.py` already existed on disk, untracked, left by a
prior session that did not finish. It was AUDITED rather than taken on trust,
and the audit is recorded here because "it exists" is not evidence that it is
right.

**Verdict: sound and reusable. It was REUSED, with one additive change.**

What was checked, and what was found:

- `load_source_rows` reuses the block/field parser shape from
  `docs/_rescore/tally.py` as instructed, and it FAILS LOUDLY: a missing KEEP
  field, a heading/field id mismatch, a duplicate id, or a parsed count other
  than 198 all raise. It cannot silently under-count.
- `cmd_blind` strips exactly the eight fields PREREGISTRATION 2.1 names
  (`prevention`, `prevention_why`, `discovery`, `origin_time`, `correct`,
  `fix_chain`, `chain_kind`, `pin_gap`) and reduces `uncertain` to a presence
  FLAG, which is the blinding 2.1 specifies.
- `cmd_check` implements the two-grep-per-stripped-name check (field-key form
  and bare token, scoped below the `## ROWS` marker) AND adds a value-token
  sweep over every legal `prevention`, sub-value and `chain_kind` name. The
  value sweep is the leak that matters more than the field names, and the prior
  agent got that right.
- `validate_score` enforces every cross-field constraint the convention implies:
  `prevention_why` present if and only if `GATE-EXISTING`; `odf` legal only on
  `FRESH`; `chain_kind` list length equal to `fix_chain`; `chain_undetermined`
  legal only at `fix_chain = 0`; cross-row links bounded by `fix_chain`; `gfck`
  present if and only if `GATE-FIRED-CAUGHT`; a strict fallback required exactly
  where the firing was DIRECTED. These are not decorative - they are what stops
  a scorer inventing an internally impossible row.
- `family_label` implements convention 4.1 TRUE / FALSE / SPLIT correctly, and
  `strict_family_label` implements the mandatory second column of 3.4 by
  substituting the scorer's declared strict fallback for a DIRECTED
  `GATE-FIRED-CAUGHT` before the family label is computed. This is the one part
  of the design that can catch RC grading toward its own prior (convention
  weakness 1), and it is present and correct.
- `majority` implements majority-of-three with a real no-majority return, and
  `cmd_tally` COUNTS and PUBLISHES the no-majority rows per field rather than
  dropping them, which is what PREREGISTRATION section 8 pins.
- The verdict block applies the 2.3 tolerances literally: `+/- 5.0` points on
  the three shares, `+/- 0.50` on the ratio, and the 4 / 3 / <=2 verdict ladder.
  Nothing is rounded into it and no tolerance was widened.

**The one real defect found, and what was done about it.** Every share divides a
numerator counted over the 198 FILED rows by `N_events`, which is 198 PLUS
splits MINUS merges. A scorer emits exactly one value set per FILED row, so
where a row is SPLIT the harness has no second value set to count and the share
silently reads low. The prior agent did not guard this. **Fix applied: additive
only.** `cmd_tally` now emits a GRAIN WARNING naming the exact mismatch and the
maximum points it can cost, whenever splits or merges are non-zero. The
computation was NOT changed, because changing it would mean inventing values for
sub-events no scorer produced. If the individuation delta comes back zero, the
warning does not fire and the defect is inert on this corpus.

`ruff check` passes. `py_compile` passes. The file is 0 non-ASCII bytes.

---

## 2. Blinding, verified mechanically before any scorer saw the file

`calibrate.py blind` produced `docs/_rsc_score/rc198_blinded.md` - 198 rows,
70365 characters, carrying `entry`, `claim`, `quote`, `refuter` and
`uncertain_present` only.

`calibrate.py check` result table, published in full including every non-zero
cell, as PREREGISTRATION 2.1 requires:

| stripped field | key-form hits | bare-token hits |
|---|---|---|
| `prevention` | 0 | 0 |
| `prevention_why` | 0 | 0 |
| `discovery` | 0 | 0 |
| `origin_time` | 0 | 0 |
| `correct` | 0 | 4 |
| `fix_chain` | 0 | 0 |
| `chain_kind` | 0 | 0 |
| `pin_gap` | 0 | 0 |

Key-form hits over all stripped names: **0**, which is the pass.

**Value-token sweep: 0 hits.** No legal `prevention` value, `origin_time`
sub-value or `chain_kind` name appears anywhere in the blinded rows.

**The 4 bare-token `correct` hits, enumerated individually rather than waved
away**, exactly as 2.1 pre-commits. All four are the ordinary English adjective
inside a `claim` or `refuter` sentence, none is a filed value:

1. `refuter`: "the pre-commit gate, corroborated by my own re-derivation; the
   correct predicate yields 7 sites across 2 files."
2. `refuter`: "reading the log properly - there were two failing cycles and the
   counter is correct."
3. `claim`: "The tracer's per-destination totals are correct."
4. `claim`: "The 7 citation offsets in the new guard file are correct."

None of the four states whether the REFUTATION was correct, which is the
question section 7 asks. The blinding holds.

---

## 3. How the filed-value exposure was handled

This is the method point that decides whether the whole exercise means anything,
so it is stated before the numbers rather than after.

The 198 rows carry RC's ORIGINAL filed values, scored under a DIFFERENT
convention (`REFUTATION_TAXONOMY_PIN v1.2`). Copying any filed value forward
would reproduce the four anchors trivially and prove nothing whatever about the
instrument. The measures taken:

1. **The scorers never saw a filed value.** They were given exactly two files -
   the convention and the blinded rows - and were told in capitals not to open
   `docs/_rescore/chunk{1,2,3,4}_rows.md`, `ROWS_PINNED.md`, `tally_report.md`
   or `band_recompute.md`, all of which carry filed values. The blinding is
   mechanically verified above, so the prohibition is backed by the artifact and
   not only by the instruction.
2. **The `uncertain` BODY was removed, keeping only a presence flag.** This is
   PREREGISTRATION 2.1's own measure and it matters: RC has already measured
   that 31 of 56 such notes name a candidate value outright. Leaving the bodies
   in would have leaked a filed value in plain prose on roughly a sixth of the
   corpus.
3. **The orchestrating session did not read the filed values either**, beyond
   the first four rows of `chunk1_rows.md` read once to learn the FILE FORMAT
   before the harness was audited. Those four rows are `chunk1-01` to
   `chunk1-04`. This is disclosed rather than judged acceptable and left quiet.
   The orchestrator scores nothing and aggregates by script, so the exposure
   cannot reach a scored value, but it is a non-zero exposure and it is named.

**The residual contamination that no measure removes** is stated in the results
section, because its size is only knowable once the numbers exist.

---

## 4. THE HEADLINE FINDING - the gap RELOCATED, it did not close

**RC's diagnosis of a sibling's instrument was that it named eight `prevention`
values and did not define them, so the scorer supplied the definitions and the
convention measured the scorer. RC defined all eight, with boundary cases and
worked examples. The three scorers then independently reported that the
undefined term moved one level down - into the PREDICATES that arbitrate between
the eight defined values.**

This is not RC's reading of their output. It is what they wrote, unprompted, in
three separately authored `## Ambiguities I resolved` sections, in three
different vocabularies, without seeing each other's files:

- Scorer 1: "RC defined all eight and left the predicate that selects among them
  - 'what counts as an instrument' - exactly as manufacturable."
- Scorer 2: "RC has relocated rather than closed the gap it criticised: the
  eight values are now defined, but the CONSTRUCTIBILITY predicate that
  arbitrates between two of them is not."
- Scorer 3: "the gap RC diagnosed in a sibling's instrument appears to have been
  relocated rather than closed."

**Three named arbitrating predicates carry the relocation, and all three were
flagged by more than one scorer** - `what counts as a standing check or a named
instrument` (3.4, all three scorers), `whether GATE-FIRED-CAUGHT and GATE-ABSENT
co-apply` (3.2 against 3.4, all three scorers), and `was the instrument wrong
about the thing it measured` (3.5 condition 2, all three scorers). Each scorer
then invented its own rule and said so: scorer 1 "That line is mine; the
convention does not contain it", scorer 2 "it is my invention, not RC's", scorer
3 "This proxy is mine, not the convention's".

**This reproduces, on RC's own instrument, the general claim LW published - that
each repair relocates the undefined term one level down.** RC is the author of
this instrument and the author of the criticism the instrument was built to
answer, and the instrument returned the criticism to RC. That is the finding.
It is not softened by the fact that the eight definitions are real and better
than none: the measured consequence of writing them was that the arbitration
moved, not that it disappeared.

**A second-order consequence, stated because it is the operative one.** RC's
pre-registration section 3.1 pinned this exact check in advance: "a convention
that defines all eight values should produce SHORTER such sections than one that
names them without defining them, and if it does not, that is a finding against
the convention and is reported as one." The three sections run to 32 logged
resolutions over 198 rows. RC does not hold LW's or RSC's per-scorer ambiguity
counts in a comparable form in this tree, so RC cannot claim the sections are
LONGER - it can only report that they are not short, that 7 of the 23
consolidated entries were reached by two or three scorers independently, and
that the pre-registered prediction of a shorter section is not supported by
anything measured here.

---

## 5. THREE LIMITATIONS THAT BOUND EVERY NUMBER BELOW

These are stated before the results, not after, because two of them change what
an anchor comparison can mean.

### 5.1 This is ONE scoring assembled from THREE HANDS on DISJOINT blocks. It is NOT an inter-scorer measurement.

`scores_cal_1.md` holds file positions 1-66, `scores_cal_2.md` 67-132,
`scores_cal_3.md` 133-198. No row was scored twice. **There is therefore no
agreement rate, no unanimity rate, no pairwise disagreement rate, no
majority-of-three, and no P1 / P2 quantity in this file at all.**
PREREGISTRATION section 2.3 specifies "majority-of-three aggregation over 198
rows"; this pass delivers SINGLE-SCORER aggregation over 198 rows, assembled
from three disjoint single-scorer blocks. That is a departure from the
pre-registered aggregation rule and it is named as one rather than presented as
an equivalent.

**The aggregate shares therefore blend THREE DIFFERENT RESOLUTIONS of one
convention.** Section 7 shows the resolutions were not the same: scorer 2 scored
every `fix_chain` in its block at the floor of 0 as a deliberate reading of 6.1,
while scorer 1 admitted 6 links in its block under a different reading of the
same clause. A share computed across those blocks is a mixture, not a
measurement of one instrument.

**The defence for doing it this way is a measurement, not convenience, and the
measurement is LW's, not RC's.** LW reports that at n=198 the identity of the
scorer moves a published share by an amount indistinguishable from zero - exact
two-sided p 0.503, 0.388 and 0.625 on the three shares it tested - while moving
individual ROWS on about a quarter of the corpus. That is attributed to LW's own
note. **RC did not reproduce those p values in this tree and does not hold the
data to.** If LW's result is wrong, or if it does not transfer from LW's corpus
and convention to this one, then the figures in section 6 are NOISIER than
stated, and the true uncertainty on each share is larger than the zero this
design implicitly assumes. RC states that rather than treating a borrowed null
result as a property of its own pass.

### 5.2 `prevention_why` was NEVER COLLECTED, and that is a DISPATCH HARNESS defect, not a convention defect

Convention 3.1 makes `prevention_why` mandatory on every `GATE-EXISTING` row,
as exactly one of `WRONG-SCOPE`, `WRONG-TIME` or `VACUOUS`. **The scorer output
schema used for this pass has four keys - `prevention`, `origin_time`,
`fix_chain`, `note` - and `prevention_why` is not among them.** Two scorers
raised this independently and both worked around it by writing the value into
`note` (scorer 1 on chunk1-07 and chunk1-15; scorer 2 on chunk3-16 and
chunk3-23).

**The fault is in the harness that dispatched the scorers, and it must NOT be
charged to the convention.** The convention specifies the field correctly; the
pass simply had no slot to put it in. The consequence is that **every clause
depending on `prevention_why` is UNMEASURED here** - the `WRONG-SCOPE` versus
`WRONG-TIME` versus `VACUOUS` distribution, and with it scorer 1's consolidated
entry A9 below (whether the tie-breaker empties `WRONG-SCOPE` entirely) cannot
be settled from this output. **It cannot be recovered without a re-score**, and
no re-score was run, because re-scoring after seeing the anchors would destroy
the blinding the whole pass rests on.

### 5.3 `fix_chain` is reported by the scorers as VACUOUS, so the fix-of-a-fix anchor is measuring the FLOOR RULE and not the corpus

Convention 6.1's cross-row link rule - "A forward link established by a
DIFFERENT ROW IN THE SAME CORPUS does count" - requires reading later rows
before finalising earlier ones. Two scorers independently reported it
unexecutable under a partitioned, file-order, single-pass scoring task:

- Scorer 2: "I scored every `fix_chain` at the 6.1 floor of 0 and flagged the
  affected rows rather than revising ... the result is that `fix_chain` in this
  block carries no information at all, which is worth saying plainly."
- Scorer 3: "any link established by a row outside my block is invisible and my
  `fix_chain` figures are a floor bounded by my block, not by the corpus."

The per-block figures show it directly: rows carrying at least one link are
**6 in block 1, 0 in block 2, 1 in block 3**. A field whose value depends that
strongly on which hand scored the block is not measuring the corpus.

**The fix-of-a-fix anchor comparison in section 6 is therefore presented as
NEITHER a clean reproduction NOR a clean miss.** It is a comparison against a
quantity the pass could not produce. Its arithmetic is reported because the
pre-registration pins the rule literally and a suppressed cell would be a
convenient omission - but no inference about the corpus may be drawn from it in
either direction.

---

## 6. RESULTS

Every figure below names its GRAIN and its AGGREGATION RULE. All are script
output from `docs/_rsc_score/tally_cal.py`, reproducible with:

    python docs/_rsc_score/tally_cal.py

**Harness reuse, asked and answered.** `calibrate.py`'s BLIND and CHECK halves
were REUSED as-is and produced the blinded corpus and the leak table in sections
2 and 3. Its TALLY half was **NOT** reusable and was not used: `parse_scorer`
requires a `ROW <id> | k=v` line carrying THIRTEEN keys and requires each scorer
file to hold all 198 rows for majority-of-three, and the files produced are
markdown blocks of 66 disjoint rows carrying four keys. `tally_cal.py` replaces
that half and only that half; `calibrate.py` was not edited for this step.
`ruff check` passes on `tally_cal.py` and it is 0 non-ASCII bytes.

### 6.1 Denominators and individuation

    N_events   198   filed rows, taken AS FILED per PREREGISTRATION 3.2
    N_links      9   sum of fix_chain over all 198 rows - see 5.3, this is a
                     floor bounded by the blocks, not by the corpus
    N_decomp   207   = N_events + N_links

**Individuation delta: NOT SUPPORTED by these score files, and not invented.**
The scorer output schema carries no `indiv` key, so no scorer recorded a
per-row KEEP / SPLIT / MERGE judgement and no split count or merge count exists.
`N_events` is held at the filed 198 for that reason. **One merge candidate was
named incidentally**, in prose, by scorer 2: chunk2-31 and chunk2-32 are "the
same sufficiency assumption, in its second failing case", which convention 1.3
calls ONE event. The scorer scored both as filed because the pass forbids
re-individuation. That is one observation, not a delta - a delta would require
the judgement on all 198 rows, and this pass did not collect it. Zero split
candidates were named.

### 6.2 The four anchor quantities

Grain and rule stated per row. Aggregation is SINGLE-SCORER over each disjoint
block, concatenated to 198 - see limitation 5.1.

| anchor | grain | measured | published | delta (points) | tolerance | result |
|---|---|---|---|---|---|---|
| `inherited` | `origin_time` FAMILY, per row | **40.4 pct** (80 / 198) | 48.5 pct | **-8.10** | +/- 5.0 | **MISSES** |
| `fix-of-a-fix` | `fix_chain >= 1` BOOLEAN, per row | **3.5 pct** (7 / 198) | 12.1 pct | **-8.60** | +/- 5.0 | **MISSES** (see 5.3 - not interpretable) |
| `BORN-WRONG : DECAYED` | `origin_time` SUB-VALUE, per row | **4.33** (52 : 12) | 2.62 | **+1.71** | +/- 0.50 | **MISSES** |
| `gate-or-contract` | `prevention` FAMILY, per row, TRUE over `N_events` | **79.8 pct** (158 / 198) | 85.4 pct | **-5.60** | +/- 5.0 | **MISSES** |

**Anchors that reproduce: 0 of 4. Anchors that do not: 4 of 4.**

Supporting counts, each named beside the share it bounds:

- **gate-or-contract, FAMILY grain (convention 4.1).** TRUE 158, **SPLIT 19**,
  FALSE 21. The share is the TRUE count over `N_events`, which is what 4.1 pins:
  a SPLIT row is "NEVER silently assigned to a side, never dropped, and never
  given partial credit". **A sensitivity, labelled as a sensitivity and NOT
  substituted into the verdict:** were SPLIT rows counted as TRUE, the share
  would be 89.4 pct and the delta +4.0, inside tolerance. The pre-registration
  forbids substituting a statistic, so 79.8 pct is the figure and 89.4 pct is an
  observation about where the miss comes from. **19 of the 198 rows, roughly one
  in ten, sit on a boundary whose handling alone decides this anchor.**
- **`prevention`, PER-VALUE grain.** A row contributes to EVERY value in its set,
  so these do not partition and their sum is not `N_events`:
  GATE-FIRED-CAUGHT 108, GATE-ABSENT 69, PROXY-MEASURE 27, ADVERSARY 13,
  GATE-EXISTING 8, CONTRACT 3, CONTRACT-MISFIRED 1, GATE-FIRED-IGNORED 0.
  **Sum of per-value counts 229 over 198 rows.**
- **Multi-value rows: 31 of 198.** Set-size distribution: 167 rows at one value,
  31 at two, **0 at three or more**, so convention 3.9's "each such row is listed
  by id" requirement is satisfied by an empty list. Per block: 14, 9, 8.
  **These were VERIFIED from the files, not carried forward from the scorers'
  own reported 14 / 9 / 8 - the two agree exactly.**
- **`origin_time`, FAMILY-plus-SUB-VALUE grain.** INHERITED 80 (BORN-WRONG 52,
  DECAYED 12, **UNKNOWN 13**, OVER-GENERALISED 3, UNDER-PROVEN 0), FRESH 118.
  The 13 UNKNOWN rows are the convention's own default under 5.2 and are the
  direct cost of its four positive tests not fitting; scorer 2 says of them that
  "UNKNOWN here is not 'the record is silent', it is 'the record is loud and the
  four tests do not fit'".
- **`fix_chain` distribution.** 191 rows at 0, 5 at 1, 2 at 2. The 191 zeroes are
  a FLOOR under 6.1 and the share above them can only be higher. `chain_kind`,
  `chain_undetermined` and the cross-row link count were NOT collected, so the
  "both ways" fix-of-a-fix reading pinned in PREREGISTRATION 2.1 - with and
  without SAME-ARTIFACT links - collapses to one column here. RC's own corpus
  carries zero SAME-ARTIFACT rows, so the exclusion was already inert; that does
  not rescue the figure, for the reason in 5.3.

### 6.3 Which anchors reproduce, per the pre-registered rule

**None.** Applying PREREGISTRATION 2.3 literally, with no tolerance widened and
no statistic substituted:

    inherited share          40.4 vs 48.5, |delta| 8.10 > 5.0    NOT reproduced
    fix-of-a-fix share        3.5 vs 12.1, |delta| 8.60 > 5.0    NOT reproduced
    BORN-WRONG : DECAYED     4.33 vs 2.62, |delta| 1.71 > 0.50   NOT reproduced
    gate-or-contract share   79.8 vs 85.4, |delta| 5.60 > 5.0    NOT reproduced

Three of the four misses run in the direction section 2.2 of the pre-registration
predicted BEFORE the pass: it said the origin-side anchors would be the harder
pair, that 5.2a's FRESH default "can only move the inherited share DOWN" (it
moved down 8.1 points), and that 5.2b's UNKNOWN default moves the ratio "toward a
smaller numerator". The ratio instead moved UP, to 4.33, because UNKNOWN absorbed
DECAYED rows faster than BORN-WRONG rows - scorer 3's entry A5 is the mechanism,
label-only staleness routed to UNKNOWN rather than to DECAYED. **That prediction
was wrong in direction and is recorded as wrong rather than quietly dropped.**

One structural cause of the gate-or-contract shortfall is worth naming because it
is the convention working as designed: convention 3.6 narrows `CONTRACT` to rows
naming a specific rule, and `CONTRACT` plus `CONTRACT-MISFIRED` landed on **4 of
198 rows, 2.0 pct**, against the 25.3 pct of events RC's own corpus carries under
its prior taxonomy. The narrowing was pre-registered as able to "only move
`CONTRACT` DOWN"; it moved it down by an order of magnitude on RC's own material.

---

## 7. THE CONSOLIDATED AMBIGUITY LIST - 32 logged resolutions, 23 distinct

This is the highest-value output of the pass. The three scorers logged 9, 12 and
11 resolutions respectively - **32 in total, deduplicating to 23 distinct
entries**. Each is named by the clause it attacks and typed as:

- **GAP** - the convention does not define the term the clause turns on.
- **CONTRADICTION** - two clauses of the convention disagree, and a row can
  satisfy both.
- **UNEXECUTABLE** - the clause is well defined, and the stated procedure cannot
  apply it.

**Type totals: 13 GAP, 7 CONTRADICTION, 3 UNEXECUTABLE.**
**Hit by more than one scorer independently: 7 of 23. Hit by all three: 3.**

### 7.1 Reached by ALL THREE scorers independently

**A1. Do `GATE-FIRED-CAUGHT` and `GATE-ABSENT` co-apply? (3.2 against 3.4) -
CONTRADICTION.** 3.2 requires that no mechanised instrument graded the property
at the moment the defect was written; 3.4 rules a DIRECTED pass a standing
check. Gates fire after the writing, so on a literal reading nearly every
`GATE-FIRED-CAUGHT` row is also `GATE-ABSENT` and the set stops discriminating.
Nothing orders the two. The three scorers resolved it three different ways -
scorer 1 admitted both only where the row's text independently states a gap (4
rows), scorer 2 took `GATE-FIRED-CAUGHT` alone unless a distinct prevention
failure is named, scorer 3 read "graded the property" as satisfied by any
standing check so a directed catch SUPPRESSES `GATE-ABSENT`. **This single
unresolved ordering is the largest lever on the SPLIT count and therefore on the
gate-or-contract anchor.**

**A2. What counts as a "standing check" or a NAMED INSTRUMENT? (3.4) - GAP.**
3.4 requires "a NAMED instrument WITH A FIRING VERB which a STANDING RULE
REQUIRED to run", admits "a mandated self-audit" and excludes "an unprompted
re-read". In a tree whose standing rule is to re-verify before any assertion,
nearly every self-check is both at once. All three scorers invented a
substitute test and all three said so: scorer 1 required a named control and
refused bare acts of measuring or re-deriving; scorer 2 separated "a pass owed
BEFORE the claim could stand" from "the work itself doing its own job"; scorer 3
built a two-limb row-text proxy. Scorer 2 reports this moved EIGHT rows in its
block alone.

**A3. "It was not wrong about the thing it measured" (3.5 condition 2) - GAP.**
The clause does not say which DESCRIPTION of the measured thing governs. All
three hit it on different shapes: a quotient whose inputs were each correct and
whose result was meaningless (scorer 1), a heuristic that correctly reported its
own matches while being a bad detector (scorer 2), an over-broad extractor right
about its own predicate and wrong about the named quantity (scorer 3). All three
took the predicate-level reading, which ADMITS `PROXY-MEASURE`. Scorer 3 names
the consequence exactly: `PROXY-MEASURE` is OUT-FAMILY, so "this single
unresolved word moves FAMILY-grain results, not just SET-grain ones - the exact
failure mode section 4.2 says the convention was written to prevent".

### 7.2 Reached by TWO scorers independently

**A4. `prevention_why` is mandatory and has nowhere to go (3.1) -
UNEXECUTABLE.** Scorers 1 and 2. Both wrote the value into `note`. See
limitation 5.2: the defect is the dispatch harness's, not the convention's.

**A5. 6.1's cross-row link rule cannot run in a partitioned, file-order pass
(6.1) - UNEXECUTABLE.** Scorers 2 and 3. The rule requires reading later rows
before finalising earlier ones. See limitation 5.3.

**A6. Is a claim carried by CODE, or by an RM id, "already committed, filed, or
sitting in a tracked artifact"? (5.1) - GAP.** Scorers 1 and 2. Scorer 1 counted
committed code as INHERITED and named the six rows that turn on it, noting all
six flip to FRESH under the narrower reading. Scorer 2 had to build a nine-way
list (RM row, directive, hand-off note, docstring and committed code INHERITED;
draft, prediction, slice report, same-session dispatch and in-chat statement
FRESH) because 5.1's sub-rules pin the directive case and not the filed-row case.
**This clause alone decides the inherited-share anchor.**

**A7. The `origin_time` sub-value is mandated SINGULAR and the corpus is not
(5 and 5.2) - GAP.** Scorers 1 and 3, from opposite sides. Scorer 1 had a row
that is two-thirds DECAYED and one-third BORN-WRONG by its own arithmetic and
took the majority, noting the convention permits a SET for `prevention` and
forbids one here with no stated reason. Scorer 3 had a row where OVER-GENERALISED
and UNDER-PROVEN both pass, and observes 5.2 orders only the EMPTY case and says
nothing about two tests passing.

### 7.3 Reached by ONE scorer

**A8. 3.8's residual-ordering clause against its own SHAPE test -
CONTRADICTION.** Clause 1 checks `ADVERSARY` LAST and takes any other satisfied
value; clause 2 reserves `ADVERSARY` for reasoning errors. Since 3.2's
constructibility test can name a plausible instrument for almost any reasoning
error after the fact, clause 1 read strictly EMPTIES `ADVERSARY`. Scorer 2 made
clause 2 operative and names six rows that turn on it.

**A9. The `GATE-EXISTING` tie-breaker against 3.2's own boundary -
CONTRADICTION.** The tie-breaker sends a check that would need REWRITING to
`GATE-ABSENT` and defines rewriting to include a widened input corpus; 3.2's
boundary sends a too-narrow check to `GATE-EXISTING` with
`prevention_why: WRONG-SCOPE`. A too-narrow check is by definition one whose
corpus must widen, so read together **`WRONG-SCOPE` can never be assigned**,
though 3.1 lists it as one of exactly three permitted reasons. Scorer 1 honoured
the tie-breaker, calling it "the single largest lever in my block". Note that
limitation 5.2 makes this entry UNMEASURABLE from the output: with no
`prevention_why` field collected, RC cannot check whether `WRONG-SCOPE` in fact
went to zero.

**A10. 3.4's OWED test imports exactly the knowledge 3.6 forbids -
CONTRADICTION.** 3.4 keys on "whether the pass was OWED before the work started",
a property of the tree's standing directives; 3.6 pins the opposite discipline
for `CONTRACT` - "The rule must be identifiable from the row - not supplied by
the scorer's knowledge of what rules the tree has". Scorer 3: the
largest-impact value in the taxonomy "is allowed to import exactly the knowledge
the neighbouring value forbids".

**A11. `CONTRACT-MISFIRED` has no home for a spec found wrong BEFORE it was
applied (3.7) - CONTRADICTION.** 3.7's stated purpose is "The fault is in the
rule, not in the observance", but its gating condition requires the rule to have
been CORRECTLY APPLIED, and its own boundary sends a not-followed rule to
`CONTRACT`, the opposite finding. Scorer 3 scored three such rows on the
constructible instrument instead, with the consequence that "'the spec itself was
wrong' is invisible in my output".

**A12. 3.9's "a set of ONE is the expected case" against 3.9's own admission
rule - CONTRADICTION.** The admission rule admits every value the row's text
grounds, which on several rows is two or three; the surrounding sentence calls
one expected and three rare. No rule says which wins. Scorer 3.

**A13. 3.4 admits "a mandated self-audit" while the tree's orchestration
principle forbids a producer grading its own work - CONTRADICTION.** Scorer 3
allowed the self-run pass, because "3.4 says so in terms and nothing in the
convention subordinates it".

**A14. 3.2's "knowable before the defect's content was known" is not operable as
written - GAP.** A barred predicate and a permitted one can be the same
instrument with the answer factored out, and the clause does not say which
phrasing governs. Scorer 2 allowed answer-free phrasings. **This is the entry in
which scorer 2 states the relocation finding of section 4.**

**A15. Does `PROXY-MEASURE` DISPLACE an otherwise-applicable `GATE-ABSENT`?
(3.5) - GAP.** 3.5 handles only the reverse direction. Scorer 2 took
`PROXY-MEASURE` alone, noting it is OUT-FAMILY "so the choice moves the family
answer, not just the set".

**A16. 3.8's shape test against errors that are BOTH a discrete datum and an
inference - GAP.** A misattributed cause and a mechanism mischaracterisation sit
in both of 3.8's lists at once. Scorer 1 took `ADVERSARY` in both and notes the
row's text supports `GATE-ABSENT` equally - "the same IN/OUT family boundary 3.5
was written to protect, crossed by a different door".

**A17. 5.2(b)'s positive tests exclude a common shape - GAP.** A claim
re-derived over a DIFFERENT corpus than the one it was filed against fails the
DECAYED test and the BORN-WRONG test both. Scorer 2 assigned UNKNOWN as required
and notes that here UNKNOWN means the tests do not fit, not that the record is
silent.

**A18. "Stale" asserts decay without supplying the time index DECAYED demands
(5.2) - GAP.** Scorer 3 routed label-only staleness to UNKNOWN and reserved
DECAYED for a described or dated superseding event, which enlarges the UNKNOWN
bucket. **This is the mechanism behind the ratio anchor moving in the direction
the pre-registration did NOT predict.**

**A19. BORN-WRONG's test does not say how to treat a claim ABOUT CODE that does
not date itself (5.2) - GAP.** Scorer 3 built the rule and says "This rule is
mine; 5.2 does not contain it".

**A20. 3.1's `VACUOUS` has no PARTIAL case - GAP.** "It ran and measured
NOTHING" is an absolute; a guard green under one mutation and presumably red
under others satisfies neither it nor the alternatives. Scorer 2 assigned it
anyway, "which overstates the guard's emptiness".

**A21. `fix_chain` when the remedy is invalidated by the tree MOVING rather than
by being wrong (6) - GAP.** Section 6's `chain_kind` list has no value for it.
Scorer 1 counted one link in each of two such rows and states plainly "I am not
confident in either row".

**A22. How specific must "WHICH instrument fired" be? (section 2 boundary on
3.4) - GAP.** "An adversarial slice" names a class, not an instance. Scorer 3
accepted a class name drawn from 3.4's own enumeration, noting the strict reading
"would void `GATE-FIRED-CAUGHT` on most of chunk3-25 through chunk3-28".

**A23. 1.3's individuation boundary is stated and this pass is FORBIDDEN to act
on it - UNEXECUTABLE.** Scorer 2 identified a two-row pair that 1.3 calls ONE
event and scored both as filed, concluding that "the convention's individuation
rule and a per-row scoring task are not compatible without a separate
individuation pass". This is the same finding as section 6.1's absent
individuation delta, arrived at from the scorer's side.

### 7.4 What the list says about the instrument

**7 of the 23 entries fall on `prevention` predicates that decide the IN-FAMILY
/ OUT-FAMILY boundary** (A1, A2, A3, A8, A14, A15, A16), which is the boundary
the gate-or-contract anchor is computed over. **4 fall on `origin_time`** (A6,
A7, A18, A19), which is the boundary the inherited share and the ratio are
computed over. The ambiguities are not scattered across the convention - they
cluster precisely on the two arbitrations the four anchors depend on.

---

## 8. VERDICT

### 8.1 The pinned verdict, applied literally

Anchors reproduced: **0 of 4**. PREREGISTRATION 2.3 pins: "NOT CALIBRATED - 2 or
fewer reproduce."

> # NOT CALIBRATED

Nothing was rounded into this. No tolerance was widened, no statistic was
substituted, and the one sensitivity that would have rescued an anchor (counting
SPLIT rows as TRUE, section 6.2) is reported as an observation and is NOT applied.

### 8.2 Coverage - what this verdict does and does not cover

Stated because a verdict whose coverage is unstated is worth less than the
coverage itself.

- **COVERED at full strength:** the `prevention` FAMILY-grain and PER-VALUE-grain
  quantities, the `origin_time` FAMILY and SUB-VALUE quantities, the multi-value
  and SPLIT counts, `N_events`, `N_links`, `N_decomp`. Three of the four anchors
  rest on these and all three miss.
- **COVERED but NOT INTERPRETABLE:** the fix-of-a-fix anchor. Section 5.3. It is
  counted in the 0-of-4 because the pre-registration's rule is literal and
  arithmetic, and it is excluded from every inference about the corpus.
- **NOT COVERED AT ALL:** every inter-scorer quantity - agreement, unanimity,
  pairwise and pooled disagreement, the P1 and P2 verdicts, the three-different-
  sets count. This pass has no overlap by construction (5.1). **Also not
  covered:** `prevention_why` and everything downstream of it (5.2), `chain_kind`,
  `chain_undetermined`, the cross-row link count, the `gfck` MECH/DIR split and
  the STRICT standing-check column of convention 3.4, `correct`, and the
  individuation delta.
- **The STRICT column absence is worth naming separately.** Convention 3.4 makes
  LW's strict reading a MANDATORY second column, and `calibrate.py` implements it
  correctly in `strict_family_label`. It could not be computed here because the
  output schema carries neither `gfck` nor a strict fallback. **That column is
  the one part of the design that could catch RC grading toward its own prior
  (convention weakness 1), and this pass does not have it.** It is a gap in the
  evidence, not a clean bill.

### 8.3 The consequence, which the pre-registration attached in advance

PREREGISTRATION 2.3 and 5.1, written before any row was read:

> "The consequence of NOT CALIBRATED is pinned here so it cannot be negotiated
> later: RC does NOT publish any SHARE off RSC's corpus."

**That consequence now applies, and it stops the next stage.** Concretely:

- **No share of any kind may be published off the target corpus** - no
  gate-or-contract share, no inherited share, no fix-of-a-fix share.
- **P3 is SUPPRESSED**, per 5.4's own SUPPRESSED branch. There is no P3 verdict.
- **What RC may still publish**, per 2.3: this validation failure, the four
  re-scored figures against the four anchors, and inter-scorer DISAGREEMENT
  rates on the target corpus - the one class of figure that does not depend on
  the instrument being calibrated, because a disagreement rate is a property of
  the readers rather than of the level the instrument lands at. **This pass
  produced no such rate on RC's own corpus (5.1), so RC does not hold a
  calibration baseline for one.**

**This is a legitimate outcome and it is not worked around.** The instrument was
pre-registered, applied exactly as written, not amended, and it failed its own
gate on its author's own corpus. That is the result the design was built to be
able to return, and returning it is the design working.

### 8.4 The honest reading of WHY it failed

Not offered as a rescue - the verdict stands regardless - but recorded because
suppressing it would be its own defect.

The pre-registration predicted in section 2.2 that five deliberate departures
would move these anchors, and said "A convention that reproduced all four anchors
trivially would be a convention that changed nothing, and this one changes five
things on purpose." **All five departures fired, and they fired harder than the
+/- 5.0 tolerances allowed for.** A convention that changes five things and then
lands inside a five-point band on all four anchors would have been the surprising
result. **What the pre-registration did not anticipate is that the tolerances it
pinned were sized for an instrument that changes nothing much** - and it pinned
them anyway, before seeing this, which is why the verdict is usable at all.

Whether the failure means the convention is WORSE than RC's prior taxonomy, or
merely DIFFERENT from it, is not measurable here: section 2.4 already pinned that
RC's corpus is the material and never the answer key, so landing somewhere else
is not landing somewhere wrong. **What is measurable, and what section 4 reports,
is that defining the eight values did not remove the arbitration - it moved it.**
