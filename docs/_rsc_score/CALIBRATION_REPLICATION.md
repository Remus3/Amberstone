# CALIBRATION, independent replication pass - verdict NOT CALIBRATED, 1 of 4 anchors

**Status: COMPLETE. Verdict: NOT CALIBRATED (1 of 4 anchors reproduced).**

This is a SECOND, separately-run pass at the validation gate pinned in
`docs/_rsc_score/PREREGISTRATION.md` section 2. It does not supersede
`docs/_rsc_score/CALIBRATION.md`, which a CONCURRENT SESSION in this same tree
produced and committed while this pass was running. Both documents are kept.
Section 1 explains why, and states exactly how entangled the two passes are.

**Neither pass reads any row of RSC's corpus.** That corpus is not present in
this tree at all - `docs/_rsc_score/` contains only the instrument, the
pre-registration, the harnesses, the blinded RC rows and the scorings - so the
hard constraint is satisfied structurally, not merely by observation.

---

## 1. THE COLLISION, disclosed before any number

This session was asked to run the calibration, write `CALIBRATION.md` and
`calibrate.py`, and commit them. Mid-run, `git status` and `ls` began returning
artifacts this session did not create, and `HEAD` had moved from `67c4700f5` to
`10041443f`. The cause was not a wedged tool pipe. **Another session was running
the same brief in the same working tree and committed three times while this one
worked:** `d77b02d6b`, `3bbee3c77`, `10041443f`.

Their `CALIBRATION.md` was already tracked and 38770 bytes when this session went
to write its own. **Overwriting it would have destroyed a committed artifact
belonging to work this session did not do, on no instruction to do so.** This
pass therefore writes under non-colliding names and reports the collision:

| this pass | the concurrent pass |
|---|---|
| `CALIBRATION_REPLICATION.md` | `CALIBRATION.md` |
| `calibrate_rep.py` | `calibrate.py` |
| `scores_rep_A.md`, `scores_rep_B.md`, `scores_rep_C.md` | `scores_A.md`, `scores_B.md`, `scores_cal_1.md`, `scores_cal_2.md`, `scores_cal_3.md` |

**THE TWO PASSES ARE NOT INDEPENDENT, and the entanglement is measured, not
estimated.** `scores_rep_B.md` and their `scores_B.md` are BYTE-IDENTICAL
(sha256 `694b14a555c7b3587662e8576b520eb9d70183e34505d0e9c148d24d3f6bd145`). One
of this pass's three scorers is also one of theirs. Scorers A and C here share no
hash with any of their five files. So the two verdicts agree on a shared 1-of-3
scorer, and **two entangled passes agreeing is weaker evidence than two
independent passes agreeing.** It is recorded that way rather than presented as
corroboration.

**Both passes reach NOT CALIBRATED.** Theirs: 0 of 4. This one: 1 of 4. The one
anchor that separates them is discussed in section 4.

---

## 2. METHOD

**Instrument.** `docs/_rsc_score/RC_SCORING_CONVENTION_v1.md`, committed at
`73aef40c8` on 2026-09-12 together with the pre-registration, before any target
row was read. Applied exactly as written. Not amended, and no amendment
requested. Where it was ambiguous, the ambiguity was resolved and the resolution
recorded - section 6 is that record, and it is the primary deliverable.

**Material.** RC's own 198 published rows, `docs/_rescore/chunk{1,2,3,4}_rows.md`.

**Blinding.** `calibrate_rep.py blind` parses the four chunk files and emits
`id`, `entry`, `claim`, `quote`, `refuter` and an `uncertain` presence FLAG only.
Removed: `prevention`, `prevention_why`, `discovery`, `origin_time`, `correct`,
`fix_chain`, `chain_kind`, `pin_gap`, and the `uncertain` BODY. 198 rows, 70365
chars.

**Blinding verified mechanically before any scorer saw the file**, by the
two-grep-per-stripped-name check pinned in PREREGISTRATION 2.1, scoped to the
rows section, plus a value-token sweep the pre-registration did not require:

| stripped name | key-form hits | bare-token hits |
|---|---|---|
| `prevention` | 0 | 0 |
| `prevention_why` | 0 | 0 |
| `discovery` | 0 | 0 |
| `origin_time` | 0 | 0 |
| `correct` | 0 | **4** |
| `fix_chain` | 0 | 0 |
| `chain_kind` | 0 | 0 |
| `pin_gap` | 0 | 0 |

Zero key-form hits. The four `correct` hits are enumerated rather than waved
away, exactly as PREREGISTRATION 2.1 requires - all four are the ordinary English
adjective inside `claim` or `refuter` prose ("the correct predicate yields 7
sites", "the counter is correct", "per-destination totals are correct", "the 7
citation offsets ... are correct"). None is a filed value.

**The value-token sweep returned ZERO hits** for all 8 `prevention` values, all 5
`origin_time` sub-values and all 5 `chain_kind` values. No filed value name
appears anywhere in the blinded rows.

**Scorers.** Three, run in parallel, blind to each other, blind to RC's filed
values, blind to the four anchors and blind to the pre-registration's
predictions. Each received the convention and the blinded rows and nothing else,
and each was instructed not to open `docs/_rescore/` or `PREREGISTRATION.md`.
Each emitted a machine-validated line per row and a `## Ambiguities I resolved`
section.

**Aggregation.** Majority-of-three per row per field. `calibrate_rep.py` fails
loudly: a scorer file with an unparseable line, a missing field, an illegal
value, a `chain_kind` list whose length does not match `fix_chain`, a
`GATE-EXISTING` without a `prevention_why`, or anything other than exactly 198
rows raises and stops. Nothing is dropped. All three files parsed clean.

**Reproduce:**

```
py docs/_rsc_score/calibrate_rep.py tally --scorers \
    docs/_rsc_score/scores_rep_A.md \
    docs/_rsc_score/scores_rep_B.md \
    docs/_rsc_score/scores_rep_C.md
```

---

## 3. THE INDIVIDUATION DELTA (convention 1.2, 1.3)

Measured against the filed 198, at majority-of-three on the `indiv` field:

    rows SPLIT   5 (5 extra events)
    rows MERGED  1
    N_events     202
    N_links      10
    N_decomp     212

**A grain limit this harness has and cannot hide.** A scorer emits ONE value set
per FILED row, so a split row's two sub-events cannot be scored separately. Every
numerator below is counted over the 198 filed rows while the pinned denominator
is `N_events` = 202. Shares are therefore printed over BOTH denominators and the
verdict is taken over `N_events`, which is what convention 1.2 pins. The gap
between the two columns is at most 2.5 points and it does not change any anchor's
verdict.

---

## 4. THE FOUR ANCHORS

All four at majority-of-three over `N_events` = 202, each naming its grain.

| anchor | grain and aggregation | measured | published | delta | tolerance | result |
|---|---|---|---|---|---|---|
| `inherited` | FRESH/INHERITED, majority-of-three | **42.1 pct** (85) | 48.5 pct | **-6.40** | +/- 5.0 | **MISS** |
| `fix-of-a-fix` | `fix_chain >= 1` boolean, majority-of-three | **4.5 pct** (9) | 12.1 pct | **-7.60** | +/- 5.0 | **MISS** |
| `BORN-WRONG : DECAYED` | sub-value, majority-of-three | **3.47 : 1** (59 : 17) | 2.62 : 1 | **+0.85** | +/- 0.50 | **MISS** |
| `gate-or-contract` | FAMILY, majority-of-three, TRUE over `N_events` | **85.1 pct** (172) | 85.4 pct | **-0.30** | +/- 5.0 | **REPRODUCES** |

Beside each, as the convention requires:

- **inherited is a FLOOR.** `origin_default_fresh` = 30 rows were assigned FRESH
  by the 5.2(a) default because the row did not establish durability. The true
  value can only be higher.
- **fix-of-a-fix is a FLOOR.** `chain_undetermined` = 174, cross-row links = 3.
  Both ways give the same figure: 9 all-chains and 9 non-`SAME-ARTIFACT`, because
  no scorer emitted a `SAME-ARTIFACT` link, so the exclusion is inert here just
  as it is on the filed corpus.
- **the ratio excludes UNKNOWN** = 6 rows. `OVER-GENERALISED` 2,
  `UNDER-PROVEN` 0. UNKNOWN (6) does not exceed BORN-WRONG + DECAYED (76), so
  convention weakness 7 does not fire and the ratio is computable.
- **gate-or-contract, FAMILY grain:** TRUE 172, **SPLIT 12**, FALSE 14. The SPLIT
  rows are published as their own count and are not assigned to a side.
- **the mandatory STRICT second column (convention 3.4):** TRUE 162, SPLIT 3,
  FALSE 33 = **80.2 pct**. The BROAD-to-STRICT drop is 4.9 points.

**A structural note on the fourth anchor.** RC's published 85.4 pct is GATE
family plus `CONTRACT` and EXCLUDES `CONTRACT-MISFIRED`, which the filed corpus
carries on 1 row. Convention 4.1 puts `CONTRACT-MISFIRED` IN-FAMILY, so the
strictly like-for-like published figure is 85.9 pct. The difference is 0.5 points
and changes nothing.

**Why this pass reproduces the fourth anchor and the concurrent pass does not.**
Theirs measured 79.8 pct (158/198), a 5.60 miss; this one measures 85.1 pct, a
0.30 hit. **The anchor with a +/- 5.0 tolerance landed on either side of the
boundary depending on which three scorers were drawn.** That is the more
important finding than either number: the one anchor that can reproduce is
fragile to the scorer draw, so "3 of 4" was never available here and "1 of 4"
versus "0 of 4" is not a disagreement about the corpus.

---

## 5. WHERE THE GAP WENT - the per-value collapse behind a stable family share

`prevention` per-value counts, SET grain, majority-of-three. Sum = 212 over 198
rows; 14 multi-value rows. **These counts are NOT a partition.**

| value | this pass | RC's filed corpus |
|---|---|---|
| `GATE-FIRED-CAUGHT` | **100** | 36 |
| `GATE-ABSENT` | 83 | - |
| `PROXY-MEASURE` | 23 | - |
| `ADVERSARY` | 3 | - |
| `GATE-EXISTING` | 3 | - |
| `CONTRACT` | **0** | 50 (25.3 pct) |
| `CONTRACT-MISFIRED` | 0 | 1 |
| `GATE-FIRED-IGNORED` | 0 | - |

**This is the result.** The family share reproduces to within 0.3 points while
the per-value composition underneath it is unrecognisable: `CONTRACT` goes from
50 rows to ZERO, and `GATE-FIRED-CAUGHT` nearly triples. A share can be stable
because its components cancel, and here they did.

**That directly contradicts convention 4.2**, which claims this instrument
governs BOTH grains and pre-commits to being held to it: "Under THIS convention
the answer is: both, and that is a claim this document can be held to." Section 6
supplies the mechanism - the per-value definitions collide with each other, and
the convention's own section 4.3 refusal of a precedence order leaves no rule to
break the tie. **The gap RC criticised in LW's convention was not removed. It was
relocated from "the values are undefined" to "the values are defined and
overlap, and nothing orders them."**

`CONTRACT` at 0 is exactly the confound convention weakness 6 pre-committed to
checking for, at its maximum. Weakness 6 anticipated the narrow `CONTRACT` might
undercount on a foreign tree; it undercounts to zero on RC'S OWN tree, which is
the tree it was tuned for.

**Other required counts.** Rows where no refuting instrument could be identified
from the row's own text: **50**. `correct`: NO = 0, UNCLEAR = 0 - reported in
this single sentence per convention 7, and it is NOT evidence that refutations
are reliable, because a ledger-derived corpus cannot see a refutation that was
itself wrong. No-majority rows (all three scorers differ): 1, on `origin_time`,
and zero on every other field.

**Inter-scorer disagreement** (pairwise and pooled over 198 x 3 = 594
comparisons):

| quantity | A-B | A-C | B-C | pooled | unanimity |
|---|---|---|---|---|---|
| `prevention` SET | 7.1 | 13.6 | 11.6 | **10.8 pct** | 83.8 pct |
| `prevention` FAMILY | 4.5 | 10.1 | 6.6 | 7.1 pct | 89.4 pct |
| `origin_time` family | 12.1 | 8.1 | 10.1 | 10.1 pct | 84.8 pct |
| `origin_time` family+sub | 14.1 | 11.1 | 12.6 | 12.6 pct | 81.3 pct |
| `fix_chain >= 1` | 1.5 | 2.0 | 1.5 | 1.7 pct | 97.5 pct |

Recorded but NOT read as a P1 verdict: P1 is defined over RSC's corpus, not this
one, and NOT CALIBRATED suppresses that pass. The low spread is also bounded by
PREREGISTRATION section 6 - three reads of one model family with one house style
measure disagreement between READS, never between independent intelligences, so
it is a LOWER bound. And low per-row spread coexisting with a 50-to-0 collapse in
`CONTRACT` shows agreement is not the same thing as the instrument determining an
answer: the three scorers agreed because they each independently resolved the
same collision the same way, not because the convention told them to.

---

## 6. AMBIGUITIES IN RC'S CONVENTION THAT HAD TO BE RESOLVED

This section is the deliverable. PREREGISTRATION 3.1 pins its purpose: a
convention that defines all eight values should produce SHORTER such sections
than one that names them without defining them, "and if it does not, that is a
finding against the convention and is reported as one."

**It does not. The sections are long, and all three scorers independently opened
with the SAME structural defect.** Verbatim sections are in
`scores_rep_{A,B,C}.md`.

### 6.1 The defect all three found: the values OVERLAP and nothing orders them

`GATE-FIRED-CAUGHT` (3.4) answers "what caught it". The other seven answer "what
would have prevented it". They are not mutually exclusive. On a row where no
mechanised guard existed AND a mandated directed pass caught the defect, 3.2
(`GATE-ABSENT`) and 3.4 (`GATE-FIRED-CAUGHT`) are BOTH literally satisfied. 3.9
then admits both. But 3.9 also says "a set of ONE is the expected case", and 4.3
explicitly refuses a total precedence order that would break the tie.

All three scorers refused the literal reading, because it would have made nearly
every row multi-valued and the SPLIT count an artefact. All three resolved it the
same way - `GATE-FIRED-CAUGHT` alone where a standing check fired - **and all
three flagged it as the single highest-leverage choice in their pass.** Scorer C:
"a different scorer could defensibly double almost every row."

**This is not a scorer failing. It is section 3 needing a precedence order that
section 4.3 refuses to supply on principle.** 4.3's reason - that a disputed
total order makes the number measure the order - is sound, but the consequence is
that the per-value grain is decided by each reader instead.

### 6.2 A DIRECT INTERNAL CONTRADICTION between section 3's tie-breaker and 3.2

Section 3's tie-breaker, "applied FIRST, before any definition below": a check
that could not have seen the defect without its "predicate changed, its input
corpus widened, or a new assertion added" is `GATE-ABSENT`.

Section 3.2's own stated boundary: "if a check DID exist but was too narrow, the
value is `GATE-EXISTING` with `prevention_why: WRONG-SCOPE`, not `GATE-ABSENT`."

**A too-narrow check is exactly a check needing a widened corpus or predicate.
The two rules give opposite answers on one fact pattern.** Scorer B applied the
tie-breaker because section 3 declares it first, and reported the consequence:
**`WRONG-SCOPE` on ZERO rows**, `GATE-EXISTING` surviving only as `WRONG-TIME`
and `VACUOUS`, and `GATE-EXISTING` at 3 rows total. A scorer taking 3.2's
boundary as governing would move a large block of `GATE-ABSENT` to
`GATE-EXISTING` without departing from the text either.

This one is not an underdetermination. It is a contradiction, and it is in the
part of the convention written specifically to remove underdetermination.

### 6.3 `sfb` - the STRICT column the convention mandates but does not define

3.4 makes the second column under LW's STRICT reading MANDATORY and calls it the
only part of the design that can catch RC grading toward its own prior. **It
never says what value a `GATE-FIRED-CAUGHT` row takes once the directed pass is
disqualified.** Scorer B resolved it by re-running all of section 3 with
`GATE-FIRED-CAUGHT` unavailable. Scorers A and C reached the same place by
different routes. The mandatory anti-bias control is undefined at the point of
use, and its value here is a scorer invention.

### 6.4 "Standing check" is not decidable from a row

3.4's discriminator is "whether the pass was OWED before the work started". Rows
name the pass, not the rule requiring it. All three scorers manufactured a
LINGUISTIC test instead - a control role-noun (gate, verifier, adjudicator,
audit, named suite) counts; a bare actor ("me", "the session", "the merger",
"reading X") does not. Their lists overlap heavily but are not identical, and all
three noted this knowingly undercounts `GATE-FIRED-CAUGHT` relative to what RC's
directives actually mandate. Convention section 2 already declares that count a
FLOOR; what it does not say is that the floor's HEIGHT is a reader invention.

Scorer A named the sharpest instance: a mandated pre-arm dry cycle
(`chunk1-56`) is `GATE-FIRED-CAUGHT` while an ordinary delivering cycle
(`chunk1-57`) is `GATE-ABSENT`, "on almost identical fact patterns".

### 6.5 3.4 versus the 3.8 SHAPE test - which is checked first

3.8 pins `ADVERSARY` as the residual checked LAST and pins the shape test against
it, but does not say whether a discrete checkable datum caught by a standing
directed pass is `GATE-FIRED-CAUGHT` or `GATE-ABSENT`. Scorer B resolved that
`GATE-FIRED-CAUGHT` takes precedence, reading the shape test as policing only the
`ADVERSARY` / `GATE-ABSENT` boundary.

### 6.6 3.6 - what "observance" of a rule means

Roughly a fifth of this corpus is the shape "a claim misdescribes what a document
says". If reading a document correctly counts as observing it, every such row is
`CONTRACT` and the value stops discriminating exactly as 3.6 warns. Scorer C
pinned that `CONTRACT` requires a failure to COMPLY with a named rule, never a
failure to read one accurately, and routed the misdescription rows to
`GATE-ABSENT` via the shape test. **That single resolution is most of the 50-to-0
`CONTRACT` collapse in section 5.**

### 6.7 6.1 and the `cu` flag - what "silent on the remedy" means

Almost every row states the refutation and nothing about a later fix. Scorer C
set `cu=N` where the row supplies the corrected value or names a shipped remedy
and `cu=Y` where it records only that the claim was wrong, while noting "a
stricter reader would set `cu=Y` everywhere `fix=0`". `chain_undetermined` = 174
of 198 is the result, and the fix-of-a-fix anchor is therefore measuring the
FLOOR RULE more than it is measuring the corpus.

### 6.8 The verdict on the convention's central claim

Convention section 0 states that supplying real definitions for all eight values
is "the single most valuable thing RC can contribute". Section 4.2 claims the
instrument governs both grains. **On RC's own corpus, the family grain reproduced
and the per-value grain did not, and the ambiguity sections came back long rather
than short. The per-value definitions are individually precise and collectively
underdetermined, because precision per value does not compose without an ordering
rule, and 4.3 declines to supply one.** Convention weakness 9 anticipated exactly
this: "A definition can be precise and still not be the one two readers converge
on."

---

## 7. FILED-VALUE CONTAMINATION - honest assessment

The brief required this section, and required saying plainly if contamination
makes the result uninterpretable.

**Assessment: the row-level contamination is LOW and the result is interpretable.
The instrument-level contamination is REAL, is not removable without amending the
convention, and is disclosed below.**

**1. The scorers never saw a filed value.** This is the load-bearing control and
it is mechanically verified, not asserted. The blinded file was generated by
script, and the section 2 sweep returned zero key-form hits and zero value-token
hits across all 18 value names. The four `correct` hits are ordinary English and
are enumerated. A scorer could not have copied a filed value forward because no
filed value was in front of it.

**2. The orchestrating session DID see filed values, and it is named here.**
Before dispatching, this session read roughly the first 8 rows of `chunk1` with
their filed values intact, and ran `docs/_rescore/tally.py` to confirm the four
anchors are live figures from the tracked rows rather than doc recitations. That
exposure could only have biased the scorers through the prompts, and the prompts
contain no value, no distribution, no anchor and no expected direction. The
per-value collapse in section 5 - `CONTRACT` 50 to 0, `GATE-FIRED-CAUGHT` 36 to
100 - is itself evidence the scorers were not steered toward the filed
distribution: a contaminated pass reproduces the composition, and this one
destroyed it while reproducing one share.

**3. The INSTRUMENT leaks aggregate facts about the corpus being scored, and the
scorers had to read it.** This is the real contamination channel and it is
structural. `RC_SCORING_CONVENTION_v1.md` states, in prose the scorers cannot
skip:

- `:253` "RC files 36 in its own corpus, 29 of them found by a mandated
  self-audit" - a filed per-value count for the exact field with the largest
  declared divergence.
- `:592` "RC measured 0 of 198" for `correct`.
- `:671` pooled `prevention` SET disagreement of 26.1 pct on 60 rows.
- `:484` "produced zero measured disagreement in a 60-row sample".
- `:289` scorer B's three named `PROXY-MEASURE` close calls from RC's prior pass.

**This channel does not exist when the instrument is pointed at RSC.** It exists
only because the calibration target is RC's own corpus, which is the very thing
the convention's prose is about. The scorers were told to ignore these as
evidence about any row; that instruction cannot be verified. **The measurable
sign is that it did not work as an anchor pull: the `GATE-FIRED-CAUGHT` figure
the convention names as 36 came back as 100.** Whatever the leak did, it did not
drag the scorers toward the filed number - if anything the disclosure of a
BROAD reading pushed the other way.

It was not redacted because the pre-registration pins that scorers receive the
convention verbatim, and the convention pins that it is not amended. Redacting
would have been an amendment. The right handling was to disclose it, and the
existence of an unremovable leak in a pre-registered instrument is itself a
finding against the design.

**4. The two passes share a scorer, by measured hash.** Section 1. This weakens
the agreement between the two NOT CALIBRATED verdicts; it does not weaken either
verdict on its own.

**5. What this step cannot establish, per PREREGISTRATION 2.4.** It cannot show
RC's filed values are right - the scorers are blind to them by construction, so
RC's corpus is the material and never the answer key. Reproducing an anchor means
the convention lands in the same place, not that the place is correct. And it
cannot show the convention transfers to a corpus another tree extracted.

---

## 8. THE VERDICT

Applied literally per PREREGISTRATION 2.3, nothing rounded into it. Tolerances as
pinned: +/- 5.0 points, +/- 5.0 points, +/- 0.50, +/- 5.0 points.

    inherited share          42.1 vs 48.5   delta -6.40   > 5.0    NOT reproduced
    fix-of-a-fix share        4.5 vs 12.1   delta -7.60   > 5.0    NOT reproduced
    BORN-WRONG : DECAYED     3.47 vs 2.62   delta +0.85   > 0.50   NOT reproduced
    gate-or-contract share   85.1 vs 85.4   delta -0.30   < 5.0    REPRODUCED

Anchors reproduced: **1 of 4**. PREREGISTRATION 2.3: "NOT CALIBRATED - 2 or
fewer reproduce."

> # NOT CALIBRATED

The concurrent pass returned NOT CALIBRATED at 0 of 4. Both land in the same
branch, and the branch is not close: 3 of 4 was needed for
CALIBRATED-WITH-A-MISS, and the best either pass reached was 1.

**The pinned consequence, quoted so it cannot be negotiated later:**

> "The consequence of NOT CALIBRATED is pinned here so it cannot be negotiated
> later: RC does NOT publish any SHARE off RSC's corpus."

**This stops the next stage.** Suppressed: the `gate_or_contract` share (both the
BROAD and the STRICT column), the inherited share, the fix-of-a-fix share, the
`prevention` per-value counts, and **P3 entirely**.

**Still permitted, and only these:** the validation failure itself, the four
re-scored figures against the four anchors, and the inter-scorer DISAGREEMENT
rates on RSC's corpus - which do not depend on the instrument being calibrated,
because a disagreement rate is a property of the readers rather than of the level
the instrument lands at.

**PREREGISTRATION 2.2 predicted the wrong pair would be hard.** It said the
origin-side anchors would be the harder pair to reproduce, and they were - but it
expected the three gate-side departures to push in opposite directions and
roughly cancel, and on the family grain they did, to within 0.3 points. What it
did not anticipate is that the cancellation would be hiding a `CONTRACT` count
that went to zero. **A convention can land a share and still not be measuring the
same thing.**

RC publishes this, including the parts worse for RC's own framing than for
anyone else's: RC's central contribution to this exercise was section 3, and
section 3 is where every one of the three scorers reported it had to legislate.
