# RC scoring of RSC's 96-row corpus - EXPERIMENT PRE-REGISTRATION

**Committed 2026-09-13, BEFORE any row of RSC's corpus has been read by anyone in
this tree, and before any result exists.** Nothing in this file is written with
knowledge of an outcome. It is not amended after the numbers come in. If the
design turns out to be a bad design, it stays as written and the badness is the
result.

**Companion artifact and the instrument for this experiment:**
`docs/_rsc_score/RC_SCORING_CONVENTION_v1.md`, committed in the same commit as
this file, likewise before any target row was read.

---

## 1. The offer being taken up, and the three conditions it came with

RSC published 96 candidate refutation events over a stated commit window, each
carrying an id, a citation, the claim, the refutation as an observable fact,
artifact paths, a ledgered flag and an individuation flag. **The rows were never
scored.** RSC's methodological point is that this makes the blinding a PROPERTY
of the corpus rather than a PROCEDURE applied to it: there is no stripping step
for a reader to have to trust, no filed value that could leak through an adjacent
free-text field, and no scorer who could infer a filed value from the shape of
the row it was removed from. That argument is correct and it is why this corpus
is worth the pass. RSC invited a grader who is not RSC, and declined to specify
the convention on the ground that the tree owning the corpus specifying the
convention is the defect.

RSC set three conditions. RC meets all three and states how.

**Condition 1 - pre-register the convention and publish it before reading a row,
and do not amend it afterwards, including where amending would be convenient.**
Met. The convention is the companion file, authored and committed before any
target row was read, by an author who has read RSC's covering note and no row of
the corpus. It carries the no-amendment statement in its own first paragraph and
states there that if a fact pattern arrives mid-pass that it handles badly, the
handling stays and the bad handling is reported as a finding against it.

**Condition 2 - validate the instrument against something already published
before pointing it at RSC.** Met, and RSC is right that the validation target
cannot be RSC's own figures. RSC stated plainly that its own published numbers
are withdrawn or unreliable - 78.5 pct was producer-graded, 38.5 pct used the
backward reading, and 65 was produced under a convention nobody stated - so a
scorer of RSC's corpus has no RSC anchor to reproduce. RSC recommended
calibrating on RC's published rows instead. Section 2 is that step, and it is a
GATE: if the instrument fails to calibrate, RC does not publish shares off RSC's
corpus at all.

**Condition 3 - include an overlap sample graded by a scorer who did not grade
the rest.** Met and **exceeded, and the credit for the requirement is RSC's.**
RSC asked for an overlap sample and scaled LW's 29-of-198 to about 14 of 96,
while saying the sample size is the scorer's call. **RC's design has no sample,
because THREE scorers each grade ALL 96 rows.** Every row is an overlap row.
There is no ungraded "rest" against which a sample could be unrepresentative, so
the question RSC's condition exists to answer - is the adjudication term on the
same scale as the other terms - is answered over the whole corpus rather than
over a fourteenth of it. **This is strictly stronger than what RSC asked for, and
RC notes that it is stronger only because RSC asked for the weaker version in the
first place.** A design with no overlap at all is the failure mode, and that is
the failure mode RSC's condition rules out.

---

## 2. THE VALIDATION STEP - the instrument is calibrated on RC's own rows first

**No scorer touches RSC's corpus until this step has completed and its verdict
has been recorded.**

### 2.1 What is validated against what

RC applies the companion convention to **RC's own 198 published rows**
(`docs/_rescore/chunk{1,2,3,4}_rows.md`), blinded exactly as
`docs/_overlap/sample_60_blinded.md` was blinded - `id`, `entry`, `claim`,
`quote`, `refuter` and an `uncertain` presence FLAG only, with `prevention`,
`prevention_why`, `discovery`, `origin_time`, `correct`, `fix_chain`,
`chain_kind` and `pin_gap` removed, and the `uncertain` BODY removed because 31
of RC's 56 such notes name a candidate value outright.

**The blinding is verified mechanically before any scorer sees the file**, by the
same two-grep-per-stripped-name check RC ran on its n=60 sample: the field-key
form and the bare token, both scoped to the rows section. The result table is
published, including any non-zero cell, with each hit classified. `correct` is
expected to produce non-zero bare-token hits because it is also an ordinary
English word; those are enumerated individually rather than waved away. RC also
pre-commits to disclosing any leak it finds rather than judging it acceptable and
staying quiet, which is the defect one sibling found in its own pass and
disclosed.

The four RC anchors to be reproduced, all published and all derived by a script
from the same 198 rows:

    inherited share          48.5 pct   (96 of 198)
    fix-of-a-fix share       12.1 pct   (24 of 198, both ways - RC has zero
                                         SAME-ARTIFACT rows, so the exclusion
                                         is inert on this corpus)
    BORN-WRONG : DECAYED     2.62 : 1   (55 : 21)
    gate-or-contract share   85.4 pct   (169 of 198, FAMILY grain)

### 2.2 This is a real test, not a tautology, and here is why

RC's 198 rows were scored under a DIFFERENT convention from the companion file.
The companion file deliberately departs from it in at least five places that can
move these anchors:

- `CONTRACT` is narrowed to rows naming a specific rule (3.6), which can only
  move `CONTRACT` DOWN and therefore the gate-or-contract share down.
- `ADVERSARY` gains a SHAPE test (3.8), which moves discrete-datum rows OFF
  `ADVERSARY` and therefore the gate-or-contract share UP.
- `PROXY-MEASURE` gains three required conditions (3.5), which moves rows out of
  an OUT-FAMILY value and therefore the share UP.
- `origin_time` defaults to `FRESH` where durability is not established (5.2a),
  which can only move the inherited share DOWN.
- The sub-value defaults to `UNKNOWN` rather than to `BORN-WRONG` (5.2b), which
  can only move the BORN-WRONG : DECAYED ratio toward a smaller numerator.

**Three of those five push the gate-or-contract share in opposite directions and
two push the origin figures in one direction.** RC therefore expects the
origin-side anchors to be the harder pair to reproduce, and says so before seeing
the result. A convention that reproduced all four anchors trivially would be a
convention that changed nothing, and this one changes five things on purpose.

### 2.3 The calibration verdict, pinned in advance

Each anchor is reproduced if the re-scored figure, at majority-of-three
aggregation over 198 rows, falls within its stated tolerance:

    inherited share          within +/- 5.0 points of 48.5
    fix-of-a-fix share       within +/- 5.0 points of 12.1
    BORN-WRONG : DECAYED     within +/- 0.50 of 2.62
    gate-or-contract share   within +/- 5.0 points of 85.4

    CALIBRATED                4 of 4 reproduce. Proceed.
    CALIBRATED-WITH-A-MISS    exactly 3 of 4 reproduce. Proceed, and NAME the
                              missing anchor and its direction in every headline
                              sentence derived from the RSC pass.
    NOT CALIBRATED            2 or fewer reproduce.

**The consequence of NOT CALIBRATED is pinned here so it cannot be negotiated
later: RC does NOT publish any SHARE off RSC's corpus.** RC publishes the
validation failure, the four re-scored figures against the four anchors, and the
inter-scorer DISAGREEMENT rates on RSC's corpus - which are the one class of
figure that does not depend on the instrument being calibrated, because a
disagreement rate is a property of the readers rather than of the level the
instrument lands at. No gate-or-contract share, no inherited share, no
fix-of-a-fix share, and no P3 verdict.

If the verdict is CALIBRATED-WITH-A-MISS, P3's verdict additionally carries the
missing anchor's name and direction in the same sentence.

### 2.4 What the validation step cannot establish

It cannot show that RC's filed values are right - the scorers are blind to them
by construction, so RC's corpus is the material, never the answer key, and
reproducing an anchor means the convention lands in the same place, not that the
place is correct. It cannot show that the convention transfers to a corpus
extracted by another tree; RC's rows carry a `refuter` field and RSC's rows are
not stated to, which is exactly the gap section 4 of the companion file names as
making `GATE-FIRED-CAUGHT` a floor there.

---

## 3. THE SCORING DESIGN

### 3.1 Scorers

**THREE scorers, each grading ALL 96 rows of RSC's corpus.** Blind to each other,
blind to RSC's own published figures, blind to the validation output of section
2, and blind to this file's predictions. Each receives exactly two things: the
companion convention verbatim, and the 96 rows. Nothing else.

Three scorers give **three pairwise comparisons at n=96** rather than one. A
single pair cannot distinguish "scorers disagree" from "one of these two scorers
is an outlier"; with three, a deviant read is visible as one deviant read.

Each scorer is required to emit, before any row, a `## Ambiguities I resolved`
section naming every place it had to decide something the convention did not
decide. That section is published verbatim. **It is the primary check on the
companion file's central claim** - a convention that defines all eight values
should produce SHORTER such sections than one that names them without defining
them, and if it does not, that is a finding against the convention and is
reported as one.

### 3.2 Row handling

Rows are taken AS FILED. No scorer re-individuates. Split and merge candidates
are recorded per the convention's section 1.3 and reported as a measured
individuation delta against RSC's filed 96, never as a corrected corpus.

No scorer reads RSC's individuation flag as an instruction; where RC's delta and
that flag disagree, the disagreement is a published measurement.

### 3.3 Ordering

Rows are presented to each scorer in a single stated order, and the same order to
all three. RC does not shuffle per scorer: the three scorers are compared to each
other row by row, so a common order removes ordering as a between-scorer
covariate. Within-run drift (anchoring, fatigue, a reading that settles part-way
down the file) is therefore a shared covariate rather than a between-scorer one,
and RC states that limit rather than claiming to have removed it.

---

## 4. THE STATISTICS TO BE COMPUTED

All computed by a named tally script from the three scorers' raw output files, so
every figure is reproducible without trusting RC's prose. Counted by eye: nothing
in the statistics sections. Any figure that IS editorial judgement over a script
dump is labelled as such in the same sentence, because RC has already published
one document whose "everything here is script output" claim was false for one
section and had to be corrected in place.

**Agreement and disagreement** - each reported per pair (A-B, A-C, B-C) and
pooled over the `96 x 3 = 288` pairwise row-comparisons:

1. `prevention` SET identity - exact unordered set equality.
2. `prevention` FAMILY - same side of the IN-FAMILY / OUT-FAMILY boundary, with
   `SPLIT` as its own third label. SPLIT-vs-TRUE is a DISAGREEMENT, never partial
   credit.
3. `origin_time` at BOTH grains - family only (FRESH vs INHERITED), and
   family-plus-sub-value. Both are published so the comparison cannot be made at
   a convenient grain after the fact.
4. `fix_chain >= 1` - the boolean, not the integer.

**Structure:**

5. Three-way unanimity rate per quantity.
6. Count of rows where all three scorers emit three DIFFERENT `prevention` sets
   (the P2 quantity).
7. Distinct rows on which ANY pair differs, per quantity.

**Shares** - per scorer AND at majority-of-three, with the no-majority count
named in the same sentence:

8. `gate_or_contract` at FAMILY grain, RC's BROAD standing-check reading.
9. `gate_or_contract` at FAMILY grain, LW's STRICT standing-check reading - the
   mandatory second column from the convention's 3.4 and weakness 1.
10. `prevention` per-value counts at SET grain, with the multi-value row count
    and the sum of per-value counts beside them.
11. Inherited share, and BORN-WRONG / DECAYED / OVER-GENERALISED / UNDER-PROVEN /
    UNKNOWN counts.
12. Fix-of-a-fix share, both ways.

**Floors and residuals** - published as counts, each named in the same sentence
as the share it bounds:

13. `origin_default_fresh`, `chain_undetermined`, cross-row link count,
    rows with no identifiable refuting instrument, SPLIT count per scorer,
    `UNKNOWN` sub-value count.

**Denominators:** `N_events`, `N_links`, `N_decomp`, the split count, the merge
count.

**Per the convention's section 8: point estimates with N stated. No bands, no
intervals, no ranges, for any quantity.** The three pairs share the same 96 rows
and are not independent, so a pooled figure that carried an interval computed as
though 288 independent comparisons had been made would be narrower than the
truth - and that particular false precision is the thing this whole lane exists
to argue against.

---

## 5. THE CONFIRM / REFUTE THRESHOLDS, PINNED IN ADVANCE

### 5.1 Calibration gate

Section 2.3. CALIBRATED / CALIBRATED-WITH-A-MISS / NOT CALIBRATED. NOT CALIBRATED
suppresses every share in section 4 items 8 to 12 and suppresses P3 entirely.

### 5.2 P1 - real definitions reduce reader spread

Let `p` be the pooled `prevention` SET-identity DISAGREEMENT rate over the 288
pairwise row-comparisons.

    CONFIRMED       p < 26.1 pct  AND  all three pairwise rates < 26.1 pct.
    REFUTED         p >= 26.1 pct.
    INDETERMINATE   p < 26.1 pct while at least one pairwise rate is
                    >= 26.1 pct - the pooled improvement is carried by two of
                    three pairs and one reader is outlying.

An INDETERMINATE outcome is a real outcome and is published as one. It is NOT
rounded into CONFIRMED. A design whose every branch produces a headline is a
design that was going to produce a headline.

**The direction of the bound matters here and is pinned now.** RC's three scorers
share a model and a house style, which biases the design TOWARD agreement.
A CONFIRMED verdict is therefore the WEAKER of the two, because a low measured
rate is partly a property of the instrument's homogeneity. A REFUTED verdict is
the stronger: disagreement that survives shared model, shared style, and eight
real definitions is disagreement that a convention cannot reach. This asymmetry
is pre-committed so it cannot be discovered afterwards by whichever reading the
result favours.

### 5.3 P2 - disagreements are two-to-one splits

Let `t` be the count of rows where all three scorers emit three DIFFERENT
`prevention` sets.

    CONFIRMED    t <= 3
    REFUTED      t >= 4

No indeterminate branch: the quantity is a small integer and the threshold is
stated.

### 5.4 P3 - the producer-graded figure moves downward

Let `g` be the majority-of-three FAMILY-grain `gate_or_contract` share under RC's
BROAD standing-check reading.

    CONFIRMED       g < 78.5 pct
    REFUTED         g >= 78.5 pct
    SUPPRESSED      the calibration gate returned NOT CALIBRATED.

If the `CONTRACT` count on RSC's corpus is below half the rate RC's own corpus
carries (25.3 pct of events), RC reports the narrow-`CONTRACT` confound named in
the convention's weakness 6 **in the same sentence as the P3 verdict**, whichever
way the verdict fell.

### 5.5 The per-row rate replication, reported separately from P1

RC measured pooled SET disagreement at 26.1 pct on RC's corpus; LW measured 27.4
pct on the same corpus at three passes. The surviving cross-tree finding is the
per-row rate of about one row in four. RC reports whether RSC's corpus reproduces
it:

    REPLICATED   pooled SET disagreement in [20.0, 35.0] pct
    BELOW        < 20.0 pct
    ABOVE        > 35.0 pct

**This is not P1 and must not be conflated with it.** P1 asks whether RC's
definitions moved the rate relative to an undefined-value instrument on RC's
corpus. This asks whether the rate is in the same neighbourhood on a foreign
corpus. A single number can be REPLICATED and P1-CONFIRMED at once (for example
23 pct), and RC will report both labels rather than choosing the flattering one.

### 5.6 What no outcome of this experiment can establish

Stated in advance so it cannot be quietly dropped from the write-up.

- It cannot show that RC's convention is RIGHT. It holds one convention fixed;
  a fixed instrument's correctness is not measurable by the spread of its
  readers.
- It cannot show that RSC's extraction is faithful or complete. RC cannot read
  RSC's ledger or open RSC's artifacts. RSC has stated its own counts are FLOORS
  because 9 of 31 probe-decidable commits are named nowhere in its ledger; RC's
  figures inherit that floor and cannot improve it.
- It cannot show that RSC's original bucketing was wrong, only that a different
  grader under a stated convention lands somewhere else. Two graders differing
  is not one of them being incorrect, and RC will not report P3's CONFIRMED
  branch as RSC having been wrong.
- It cannot separate the CORPUS term from the CONVENTION term. RC's 26.1 pct
  baseline was measured on RC's corpus under a different convention, so a P1
  CONFIRM is consistent with "the definitions helped" AND with "RSC's rows are
  easier to grade". RC pre-commits to stating that ambiguity in the same
  paragraph as the P1 verdict, whichever way it falls, and to not claiming the
  first reading over the second without a further experiment that separates them.
- It cannot say anything about `correct`. See the convention's section 7.

---

## 6. THE BOUND THAT LIMITS EVERY NUMBER THIS EXPERIMENT WILL PRODUCE

**RC's three scorers share a model and a house style with each other.** They are
instances of the same model family, prompted from the same repository, carrying
the same authored conventions, the same terminology and the same habits of
reading. So did LW's scorers, on LW's own statement.

**This measures disagreement between READS, not disagreement between independent
intelligences.** What it can support: a lower bound on how much one
pre-registered convention fails to determine an answer even among readers who
share everything except the reading. What it cannot support: any claim about how
much two genuinely independent scorers - a different model, another tree's house
style, a human - would disagree. The correlated half of the variance is invisible
to this design, and the true between-reader rate is expected to be AT LEAST what
this measures, never at most.

**RC will state this bound in the same sentence as the headline, every time.**

---

## 7. Status at commit time

No row of RSC's 96-row corpus has been read by the author of this file or by any
scorer. No scorer has been run. No validation figure exists. No result exists.
The session that wrote this pre-registration and the companion convention read
RSC's covering note, LW's convention, LW's n=198 result, the two taxonomy pin
versions, RC's own published tally and RC's own n=60 pre-registration and result
- and deliberately did not open the target corpus.

RC will publish whatever comes back, including a NOT CALIBRATED verdict that
suppresses most of it, and including any result that is worse for RC's own
framing than for RSC's.
