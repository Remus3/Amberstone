# P1 RESULT - scorer A vs scorer B at n=198, RC's own corpus

**Every figure below is produced by `docs/_rsc_score/tally_ab.py` from the two
raw scoring files. Nothing here is counted by eye.** Run it and the numbers
regenerate. The script fails loudly: a row missing from either file, an
unparseable field, or a value outside the convention's set is counted and named
in its DEFECTS section rather than dropped. On this run the DEFECTS section is
empty.

---

## 0. READ THIS BEFORE THE NUMBERS

Four things bound every figure in this document. They are stated first because
each one of them is capable of turning the headline from a result into an
artifact.

**(a) This is ONE pair, not three.** The pre-registration's design is three
scorers grading every row, giving three pairwise comparisons, and its
INDETERMINATE branch exists precisely to catch the case where a pooled
improvement is carried by two pairs while one reader is outlying. With one pair
that branch cannot fire, and the design cannot distinguish "the two scorers
disagree" from "one of these two is an outlier". A single pair carries no
spread. **LW's comparable n=198 figure is a single pair too - that is LW's own
statement about LW's own design and is attributed to LW, not measured here - so
the fleet currently has two single-pair numbers and no spread on either.**

**(b) Both scorers share a model and a house style with each other and with the
author of the convention they are applying.** The design is biased TOWARD
agreement. The pre-registration pins the consequence in advance (section 5.2,
"A CONFIRMED verdict is therefore the WEAKER of the two"), and it is the weaker
outcome that came back. **P1 holding on a design biased toward it is weak
evidence.** A low rate here is partly a property of the instrument's
homogeneity and cannot be separated from the convention's contribution by this
experiment.

**(c) The instrument is KNOWN DEFECTIVE. `CALIBRATION.md` returned NOT
CALIBRATED, 0 of 4 anchors reproduced, at commit `3bbee3c77`.** Every one of
RC's four published anchors missed its tolerance: inherited share 40.4 pct
against 48.5, fix-of-a-fix 3.5 pct against 12.1, BORN-WRONG : DECAYED 4.33
against 2.62, gate-or-contract 79.8 pct against 85.4.

*What that verdict suppresses:* shares off the TARGET corpus, which is a third
tree's 96 rows. **This document is not that.** This is RC's own 198-row corpus,
and what is reported here is inter-scorer DISAGREEMENT, which PREREGISTRATION
2.3 explicitly exempts on the stated ground that "a disagreement rate is a
property of the readers rather than of the level the instrument lands at". So
these figures are publishable under the pre-registered rule.

*What that verdict does NOT do, stated plainly so a failed calibration is not
allowed to license a clean-looking number:* the instrument failed to reproduce
RC's own anchors **on this very corpus**. The figures below are therefore a
measurement of a known-defective instrument's reader-variance. That is a
meaningful thing to measure and it is not a vindication of the convention. A
convention can produce tight reader agreement while landing in the wrong place,
and on this corpus it demonstrably lands in the wrong place four times out of
four.

**(d) The "scorer B" identity is not established as one reader.** See section 2.
Two distinct passes both self-label as scorer B, and on their 108 overlapping
rows they disagree with each other MORE than A disagrees with either. Whichever
way that is read, it damages the pair structure this experiment rests on.

---

## 1. THE HEADLINE

| quantity | grain | aggregation | k of 198 | pct |
|---|---|---|---|---|
| `prevention` AGREEMENT | SET, exact set equality | single pair A-B, per row | 171 | 86.3636 |
| `prevention` DISAGREEMENT | SET, exact set equality | single pair A-B, per row | 27 | **13.6364** |
| `prevention` AGREEMENT | FAMILY, convention 4.1 | single pair A-B, per row | 183 | 92.4242 |
| `prevention` DISAGREEMENT | FAMILY, convention 4.1 | single pair A-B, per row | 15 | **7.5758** |
| `origin_time` AGREEMENT | FRESH/INHERITED | single pair A-B, per row | 171 | 86.3636 |
| `origin_time` AGREEMENT | family plus sub-value | single pair A-B, per row | 162 | 81.8182 |
| `fix_chain >= 1` AGREEMENT | boolean | single pair A-B, per row | 196 | 98.9899 |

Adjudicator for every row of that table: `tally_ab.py`. There is no
majority-of-three rule at n=2, so no adjudicated value exists and none is
claimed.

**P1 VERDICT: CONFIRMED, with the scope caveat in section 7 which is not
optional reading.**

---

## 2. RECOVERY, AND A PROVENANCE FINDING THAT WAS NOT EXPECTED

The complete 198-row scorer-B output was recovered from outside the repository
and written to `docs/_rsc_score/scores_B.md`. It is **byte-identical** to the
source: 43580 bytes, matching SHA-256, 198 ROW lines, 198 distinct ids, zero
non-ASCII bytes.

**The file it replaced was NOT a truncation of it.** That was the working
premise handed to this session, and it is refuted by measurement. The previous
`scores_B.md` (at `10041443f`) carried 108 rows, and on those 108 overlapping
rows:

| comparison | prevention SET disagreement on the same 108 rows |
|---|---|
| previous scorer-B pass vs recovered scorer-B pass | 19 of 108 = **17.5926 pct** |
| scorer A vs recovered scorer-B pass | 16 of 108 = 14.8148 pct |
| scorer A vs previous scorer-B pass | 21 of 108 = 19.4444 pct |

Whole-line equality is starker still: only 50 of the 108 overlapping rows are
identical. The two passes also carry different `## Ambiguities I resolved`
sections - seven items against fifteen - so they are certainly two different
runs and not one run cut in half.

**Two readings, and RC cannot tell which is true from the artifacts:**

- *One reader, two passes.* Then within-reader instability (17.59 pct) is
  LARGER than the between-reader spread the experiment set out to measure
  (14.81 pct on the same rows). The convention is then not the binding
  constraint on either, and a CONFIRMED P1 is measuring noise that is not
  reader-identity-shaped at all.
- *Two readers under one label.* Then "scorer B" is not a single reader, the
  pair structure of this experiment is compromised at the root, and the
  recovered file is one arbitrary member of a set of passes rather than "the"
  scorer-B output.

Neither reading is flattering and neither is asserted over the other. What is
asserted is the measurement: the premise "same scorer, truncated" is false, and
the previous file remains in git history at `10041443f` for anyone who wants to
re-derive this.

---

## 3. METHOD, AND WHAT COULD NOT BE COMPARED

Both scorers graded all 198 rows blind from `rc198_blinded.md` under
`RC_SCORING_CONVENTION_v1.md`. The comparison is FULL OVERLAP: every row is an
overlap row, so there is no sampling step and no ungraded remainder.

**Schema reconciliation.** The two files were authored independently, so the
script derives each file's field keys rather than assuming them. Measured this
run: both files carry the same thirteen keys - `prev`, `why`, `origin`, `odf`,
`fix`, `kinds`, `cu`, `xrow`, `correct`, `instr`, `gfck`, `sfb`, `indiv`. There
are zero A-only and zero B-only keys. The schemas turned out to be common, which
is reported as the measurement it is rather than assumed in advance.

**Fields NOT compared, and why - reported rather than forced:**

- `why` (`prevention_why`) is conditional on `GATE-EXISTING` membership, which
  is itself one of the disagreements being measured. An agreement rate over it
  would be computed on a denominator the two scorers do not share. Counts are
  published instead: A emits `-` 191, `VACUOUS` 3, `WRONG-TIME` 4; B emits `-`
  194, `VACUOUS` 3, `WRONG-TIME` 1. **Neither scorer emits `WRONG-SCOPE` on any
  row.**
- `kinds` (`chain_kind`) is conditional on `fix_chain >= 1`. Same problem, same
  treatment. A: `SELF` 7, `SELF,SELF` 1. B: `SELF` 9, `SELF,SELF` 1. Neither
  emits any of the other four chain kinds.

**Fields compared but NOT convention-governed.** `sfb`, `gfck`, `odf`, `cu`,
`xrow`, `instr` and `indiv` are all emitted by both scorers, but the convention
mandates only the `sfb` COLUMN (3.4) without saying what values it may hold, and
never specifies the rest as emitted fields at all. Both scorers had to invent
them. They are flagged in the script's output for that reason, and no agreement
figure over them is offered as a property of the convention.

---

## 4. THE FAMILY GRAIN, AND HOW A MIXED SET IS HANDLED

The grouping is taken verbatim from convention 4.1:

    IN-FAMILY   GATE-EXISTING, GATE-ABSENT, GATE-FIRED-IGNORED,
                GATE-FIRED-CAUGHT, CONTRACT, CONTRACT-MISFIRED
    OUT-FAMILY  PROXY-MEASURE, ADVERSARY

**Mixed-set handling, stated explicitly rather than buried.** A row whose set
straddles the boundary is labelled `SPLIT` per convention 3.9. It is NOT
assigned to a side, NOT dropped, and NOT given partial credit. `SPLIT`-vs-`TRUE`
and `SPLIT`-vs-`FALSE` are counted as DISAGREEMENTS, which is what
PREREGISTRATION 4.2 pins: "SPLIT-vs-TRUE is a DISAGREEMENT, never partial
credit".

Label counts: A emits TRUE 168, SPLIT 10, FALSE 20. B emits TRUE 171, SPLIT 12,
FALSE 15.

The full label cross-tabulation, so no cell is hidden:

| A label | B label | rows |
|---|---|---|
| FALSE | FALSE | 10 |
| FALSE | SPLIT | 2 |
| FALSE | TRUE | 8 |
| SPLIT | SPLIT | 10 |
| TRUE | FALSE | 5 |
| TRUE | TRUE | 163 |

---

## 5. ORIGIN AND FIX-CHAIN

`origin_time` agreement is 171 of 198 (86.3636 pct) at the FRESH/INHERITED
grain and 162 of 198 (81.8182 pct) once the sub-value is included. The
sub-value grain is the LOWER of the two, which is the direction the convention's
own weakness 7 predicted.

Distribution: A files FRESH 100 / INHERITED 98; B files FRESH 127 / INHERITED
71. Sub-values - A: BORN-WRONG 63, DECAYED 20, OVER-GENERALISED 2, UNKNOWN 13,
UNDER-PROVEN 0. B: BORN-WRONG 47, DECAYED 15, OVER-GENERALISED 2, UNDER-PROVEN
1, UNKNOWN 6.

`fix_chain >= 1` agreement is 196 of 198 (98.9899 pct). The two disagreements
are `chunk2-13` and `chunk2-23`, both rows where B records a cross-row link
(`xrow=1`) that A does not. A files 8 rows with a chain, B files 10.

---

## 6. THE ANATOMY OF THE 27 SET DISAGREEMENTS

Of the 27 rows where the two scorers emit different `prevention` sets:

- **14** are purely IN-FAMILY swaps: the symmetric difference lies entirely
  inside the IN-FAMILY group, so they cannot move a published family share.
- **13** involve an OUT-FAMILY value in the symmetric difference.
- **15** actually change the FAMILY label. These are the headline-moving ones.

(The 13 and the 15 are different sets and neither contains the other - see the
counterexamples below.)

### 6.1 The two-value check, and why it needs two readings

**LW reports 22 of 22 on RC's corpus and 24 of 24 on a third tree's, with zero
counterexamples in both. Those are LW's own notes and are attributed to LW. They
are NOT RC measurements and RC did not reproduce LW's pass.** RC's own count, on
this pair, at n=198:

**Reading 1, the informative one** - the value that actually DIFFERS between the
two scorers is `PROXY-MEASURE` or `ADVERSARY`:

    headline-moving disagreements : 15
    satisfying reading 1          : 13
    COUNTEREXAMPLES               : 2

The two counterexamples, named:

    chunk3-17  A={PROXY-MEASURE} (FALSE)
               B={GATE-FIRED-CAUGHT,PROXY-MEASURE} (SPLIT)
               differing value = GATE-FIRED-CAUGHT
    chunk3-36  A={PROXY-MEASURE} (FALSE)
               B={GATE-FIRED-CAUGHT,PROXY-MEASURE} (SPLIT)
               differing value = GATE-FIRED-CAUGHT

**Reading 2, the trivial one** - at least one of the two sets CARRIES
`PROXY-MEASURE` or `ADVERSARY`: 15 of 15, zero counterexamples.

**Does it replicate? Say plainly: under reading 1 it BREAKS, and under reading 2
it cannot break.**

Reading 2 is an ANALYTIC IDENTITY of the 4.1 grouping, not a finding. The
OUT-FAMILY set IS exactly `{PROXY-MEASURE, ADVERSARY}`. If both scorers' sets
were wholly IN-FAMILY, both labels would be `TRUE` and the label could not
differ. So a family-label change GUARANTEES that one side carries one of those
two values, and reading 2 cannot come out other than N of N on any corpus, under
any pair of readers. An N-of-N result under reading 2 is not evidence of
anything and must not be reported as a replication.

Reading 1 can fail, and here it does. The differing value need not be the
out-family one: where one scorer emits a STRADDLE and the other a single value,
the label moves (`FALSE` to `SPLIT`) while the value that actually differs is
IN-FAMILY. Both counterexamples are exactly that shape, and both are the same
shape as each other, so this is one mechanism found twice rather than two
independent failures.

**A caveat that cuts toward LW, stated because it is real:** these
counterexamples exist only because RC's convention ADMITS a straddle at 3.9. A
convention that forced one value per row would collapse reading 1 into reading 2
and could not produce them. Whether LW's zero counterexamples reflect a fact
about LW's corpora or a single-value convention is NOT determinable from RC's
side, and RC does not assert either.

### 6.2 Attribution to named forced resolutions

Both scorers independently logged, unprompted, that they were FORCED to resolve
undefined points before they could score at all - A declares 8 such resolutions,
B declares 15. That both did so is itself the primary check PREREGISTRATION 3.1
names on the convention's central claim, and neither section is short.

Where a disagreement's symmetric difference has the signature of one named
divergence between those two lists, it is attributed to that divergence BY NAME.
Rules are tried in a fixed order and the first match wins. A disagreement
matching none is left UNATTRIBUTED rather than forced into a bucket.

| divergence | rows | the two forced resolutions that produce it |
|---|---|---|
| `D-STANDING-CHECK` | 9 | A item 1 and B item 2, both on 3.4's "NAMED instrument WITH A FIRING VERB which a STANDING RULE REQUIRED to run". The two drew the named-pass list differently, moving rows between `GATE-FIRED-CAUGHT` and `GATE-ABSENT`. |
| `D-ADVERSARY-SHAPE` | 8 | B item 3 (`GATE-FIRED-CAUGHT` takes precedence over 3.8's SHAPE test, which B reads as policing the `ADVERSARY` / `GATE-ABSENT` boundary only) against A's reading of the same boundary. |
| `D-PROXY-STANDALONE` | 4 | A item 3 (`PROXY-MEASURE` stands ALONE where the substitution IS the whole defect) vs B item 5 (3.5's three conditions applied hard, so proxy-shaped rows fall to bare `GATE-ABSENT`). |
| `D-GATE-EXISTING-TIEBREAK` | 4 | B item 1 (the section-3 tie-breaker WINS over 3.2's own boundary, so `WRONG-SCOPE` is emitted on ZERO rows) vs A, which declared no such resolution. |
| `D-VACUITY-CARVEOUT` | 1 | B item 6 (3.5's vacuity carve-out, which cites `chunk1-55` BY ID as the proxy side) vs A, which declared no vacuity resolution. |
| `D-CONTRACT-NARROW` | 0 | B item 7 vs A. Produces no disagreement on this corpus. |
| UNATTRIBUTED | 1 | `chunk2-27`. A emits `{CONTRACT}`, B emits `{CONTRACT,GATE-ABSENT}`. Both reached `CONTRACT`; they differ on whether `GATE-ABSENT` co-applies, and NEITHER scorer's declared list contains a general set-admission rule - both declared only a `PROXY-MEASURE`-specific one. Convention 3.9's admission rule is the underdetermined point, and it is undeclared on both sides, so it is left unattributed. |

**ATTRIBUTED 26 of 27. UNATTRIBUTED 1 of 27.**

**What that ratio means, and what it does not.** It means 26 of the 27 set
disagreements trace to a point the convention left undetermined and that BOTH
scorers wrote down in advance as something they had to decide for themselves.
They are not reader noise; they are the convention's own gaps, visible in the
scorers' own words before any row was compared. It does NOT mean the convention
caused them in some further sense that this design can test - the attribution
is by signature over the symmetric difference, and a signature is consistent
with the named divergence rather than proof of it.

**`origin_time` carries one named divergence with a checkable signature.** A
item 5 files loop directives, dispatches, briefs, specs, filed rows and shipped
code as INHERITED durable artifacts; B item 8 applies the 5.2(a) FLOOR to the
same rows, so they come out FRESH with `odf=Y`. Of the 36 sub-value
disagreements, **21 match that signature exactly** (A INHERITED, B FRESH with
`odf=Y`). That single undeclared-durability question accounts for more than half
of the origin disagreement, and it is the same gap the convention's own weakness
7 names.

---

## 7. P1, APPLIED LITERALLY

PREREGISTRATION 5.2, verbatim:

    CONFIRMED       p < 26.1 pct  AND  all three pairwise rates < 26.1 pct.
    REFUTED         p >= 26.1 pct.
    INDETERMINATE   p < 26.1 pct while at least one pairwise rate is
                    >= 26.1 pct.

Measured this run, nothing rounded:

    p = 27 / 198 = 13.636363636363637 pct

Against the threshold 26.1. The single available pairwise rate is the same
number, because there is one pair, so the INDETERMINATE branch cannot fire.

> # P1: CONFIRMED

**The pre-committed consequence of a REFUTE does not arise.** RC's central
contribution - section 3 of the convention, the eight real definitions - is not
refuted by this measurement, and there is nothing to withdraw to four siblings
on this result.

**The scope caveat, which is not optional reading.** P1 as written names *"the
three pairs on RSC's corpus"*. This is not that. This is ONE pair on **RC's own
198 rows**. Two consequences run in opposite directions and both are stated:

- *Against this application.* It is not the pre-registered test. It is the
  pre-registered THRESHOLD applied to a different corpus and a different number
  of pairs, and the three-pair outlier check is structurally unavailable.
- *For it.* The 26.1 pct baseline was itself measured on 60 blinded rows of RC's
  OWN corpus, and those 60 ids are a verified strict subset of these 198. So
  this comparison holds the corpus roughly fixed and varies only the convention,
  which is exactly the comparison PREREGISTRATION 5.6 warned the RSC-corpus
  version could NOT make ("It cannot separate the CORPUS term from the
  CONVENTION term"). On the corpus axis this application is the cleaner of the
  two.

**PREREGISTRATION 5.5, the separate per-row rate replication, reported without
choosing the flattering label:** the surviving cross-tree finding is a per-row
rate of about one row in four (RC 26.1 pct, LW 27.4 pct on the same corpus).
RC's 13.6364 pct falls **BELOW** the [20.0, 35.0] replication band. So this run
is P1-CONFIRMED and replication-BELOW at once, and both labels are reported.

**What a CONFIRMED P1 does not establish,** restated from PREREGISTRATION 5.6 so
it is not quietly dropped: it cannot show the convention is RIGHT - a fixed
instrument's correctness is not measurable by the spread of its readers, and on
this corpus the instrument demonstrably lands in the wrong place on 4 of 4
anchors. It cannot separate "the definitions helped" from "these two readers are
alike", and section 0(b) and section 2 both give direct reason to suspect the
second. RC does not claim the first reading over the second.

---

## 8. REPRODUCING THIS

    C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe \
        docs\_rsc_score\tally_ab.py

Inputs: `docs/_rsc_score/scores_A.md`, `docs/_rsc_score/scores_B.md`,
`docs/_rsc_score/RC_SCORING_CONVENTION_v1.md` (the grouping, transcribed into
the script and asserted at import time to partition the eight values),
`docs/_rsc_score/PREREGISTRATION.md` (the thresholds). The previous 108-row
`scores_B.md` is recoverable at `10041443f` for the section 2 comparison.
