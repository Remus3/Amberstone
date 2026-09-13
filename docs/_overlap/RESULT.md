# RC inter-scorer overlap experiment - RESULT

Computed by `docs/_overlap/tally_overlap.py` from `docs/_overlap/scores_A.md`,
`scores_B.md` and `scores_C.md`. Every COUNT, RATE and VERDICT in sections 1, 2
and 3, and in the RC column of section 5, is script output - computed by that
script and reproducible by re-running it. Nothing in those sections was counted
by eye and no row was re-scored, second-guessed or corrected by the tally.
**Section 4.3 is the exception and is NOT script output.** `tally_overlap.py`
contains no attribution logic of any kind - it dumps the named disagreeing rows
and stops - so every attribution figure in 4.3 is the author's editorial
judgement over that dump. The sentence that stood here until this revision read
"Every figure below is script output. Nothing was counted by eye", which was
false for 4.3; it is corrected in place rather than deleted, so the error stays
on the record. A disagreement is the measurement here, never an error to be
cleaned up.

Instrument: `moon_sync_inbox/2026-09-13-from-LW-LW_SCORING_CONVENTION_v1.md`,
unamended. Design: `docs/_overlap/PREREGISTRATION.md`, committed `3434990c0`
before any row was scored. Material: the 60 blinded rows of
`docs/_overlap/sample_60_blinded.md`.

**The bound that limits every number in this file, stated here and repeated in
every headline sentence below: RC's three scorers share a model and a house style
with each other. This measures disagreement between READS, not between
independent intelligences, so every rate here is a LOWER bound on what genuinely
independent scorers would produce.**

---

## 1. Parse integrity

The script fails loudly rather than dropping anything. It found nothing to fail
on. All three files carry the same **60** row ids in the **same order**, checked
as an ordered sequence and not as a set. Every row in every file carries all three
scored fields. Every `prevention` value in all 180 row-scorings is one of the
convention's eight; every `origin_time` value is `FRESH` or `INHERITED` with a
required sub-value; every `fix_chain` value is a non-negative integer. Zero
missing rows, zero unparseable fields, zero out-of-vocabulary values, zero
duplicate ids, zero duplicate fields.

## 2. The four pre-registered statistics

Grain and aggregation stated in each line. A PAIRWISE rate is over the 60 rows
for that one pair of scorers. The POOLED rate is the count over all
`60 x 3 = 180` pairwise row-comparisons, expressed as a point estimate; the three
pairs share the same 60 rows and are not independent, so per section 7c no
interval is attached to the pooled figure, and per the task instruction no bands
or intervals are reported at all.

### 2.1 `prevention` SET IDENTITY - exact set equality, per row, per pair

    A-B   agree 44 of 60 = 73.3 pct   disagree 16 of 60 = 26.7 pct
    A-C   agree 48 of 60 = 80.0 pct   disagree 12 of 60 = 20.0 pct
    B-C   agree 41 of 60 = 68.3 pct   disagree 19 of 60 = 31.7 pct
    pooled over the three pairs: agree 133 of 180 = 73.9 pct,
                                 disagree 47 of 180 = 26.1 pct
    three-way unanimous (all three scorers' sets identical): 37 of 60 = 61.7 pct

Distinct rows on which ANY pair's set differs: **23 of 60**.

### 2.2 `prevention` FAMILY - same side of the IN-FAMILY / OUT-FAMILY boundary

The convention's own grouping, section 2: IN-FAMILY is GATE-EXISTING,
GATE-ABSENT, GATE-FIRED-IGNORED, GATE-FIRED-CAUGHT, CONTRACT, CONTRACT-MISFIRED;
OUT-FAMILY is PROXY-MEASURE, ADVERSARY.

**How a MIXED set was handled, stated explicitly because the rule is a real
choice - though on THIS sample it turns out to be inert.**
A set with values on both sides is NOT forced to a side and is NOT dropped. It
takes the convention's own third label, `SPLIT`, exactly as section 2 defines
`gate_or_contract` (TRUE if every co-applying value is in family, FALSE if every
one is out, SPLIT if the set straddles). Agreement is then equality over the
three-valued label, so SPLIT against TRUE is a DISAGREEMENT and not partial
credit, per PREREGISTRATION section 6 item 1. One row in this sample is affected:
`chunk1-07`, which A scored as a straddle (`GATE-EXISTING, PROXY-MEASURE` =
SPLIT) while B and C scored `PROXY-MEASURE` alone (= FALSE). That row therefore
counts as a family disagreement on A-B and A-C.

**Correction, and it makes the result STRONGER than the sentence it replaces.**
This paragraph previously said the rule was stated "because it changes the
number". That was wrong: on this sample it changes no number at all. Both
defensible alternatives were re-derived at the FAMILY grain, per row, per pair,
and pooled over 3 pairs x 60 rows. Forcing a mixed set IN-FAMILY returns the same
pairwise 50 / 52 / 52 and the same pooled 154 of 180 agree. Counting SPLIT
against TRUE as agreement rather than disagreement returns the same pairwise
50 / 52 / 52 and the same pooled 154 of 180 agree. The reason is specific to this
sample: `chunk1-07`'s counterpart under B and C is FALSE, not TRUE, so neither
alternative can reach the only affected row. **The family figures below are
therefore ROBUST to both alternative handlings on this sample** - a stronger
statement than the sensitivity the original phrasing claimed. The rule is still
stated in full, because it would bite on a sample containing a SPLIT-against-TRUE
row; it simply does not bite on this one.

    A-B   agree 50 of 60 = 83.3 pct   disagree 10 of 60 = 16.7 pct
    A-C   agree 52 of 60 = 86.7 pct   disagree  8 of 60 = 13.3 pct
    B-C   agree 52 of 60 = 86.7 pct   disagree  8 of 60 = 13.3 pct
    pooled over the three pairs: agree 154 of 180 = 85.6 pct,
                                 disagree 26 of 180 = 14.4 pct
    three-way unanimous (all three scorers' family labels identical):
                                 47 of 60 = 78.3 pct

SPLIT counts per scorer at n=60, published because convention section 8 names an
implausibly high SPLIT count as evidence against the convention: A **2**
(`chunk1-07`, `chunk2-10`), B **1** (`chunk2-10`), C **1** (`chunk2-10`). No
scorer's SPLIT count is far above the others, so section 8's flag does not fire.
Multi-value sets of any kind: A 3, B 4, C 2.

### 2.3 `origin_time` - reported at both grains, per section 6 item 3

    FAMILY ONLY (FRESH against INHERITED), per row, per pair:
    A-B   agree 60 of 60 = 100.0 pct   disagree 0 of 60 = 0.0 pct
    A-C   agree 60 of 60 = 100.0 pct   disagree 0 of 60 = 0.0 pct
    B-C   agree 60 of 60 = 100.0 pct   disagree 0 of 60 = 0.0 pct
    pooled over the three pairs: agree 180 of 180 = 100.0 pct,
                                 disagree 0 of 180 = 0.0 pct
    three-way unanimous: 60 of 60 = 100.0 pct

    FAMILY PLUS SUB-VALUE, per row, per pair:
    A-B   agree 60 of 60 = 100.0 pct   disagree 0 of 60 = 0.0 pct
    A-C   agree 57 of 60 =  95.0 pct   disagree 3 of 60 = 5.0 pct
    B-C   agree 57 of 60 =  95.0 pct   disagree 3 of 60 = 5.0 pct
    pooled over the three pairs: agree 174 of 180 = 96.7 pct,
                                 disagree 6 of 180 = 3.3 pct
    three-way unanimous: 57 of 60 = 95.0 pct

Both grains are published so the comparison to LW cannot be made at a convenient
grain after the fact. The FRESH / INHERITED call - the one the convention states
precisely, and the one section 3 devotes its boundary clause to - was unanimous on
every row of the sample. All six pooled disagreements are sub-value only, and all
three affected rows are C differing from an agreeing A and B: `chunk4-07`
(C `INHERITED / DECAYED` against `INHERITED / BORN-WRONG`), `chunk1-41` and
`chunk1-57` (C `INHERITED / OVER-GENERALISED` against `INHERITED / BORN-WRONG`).

### 2.4 `fix_chain >= 1` - the boolean, not the integer, per row, per pair

    A-B   agree 59 of 60 = 98.3 pct   disagree 1 of 60 = 1.7 pct
    A-C   agree 60 of 60 = 100.0 pct  disagree 0 of 60 = 0.0 pct
    B-C   agree 59 of 60 = 98.3 pct   disagree 1 of 60 = 1.7 pct
    pooled over the three pairs: agree 178 of 180 = 98.9 pct,
                                 disagree 2 of 180 = 1.1 pct
    three-way unanimous: 59 of 60 = 98.3 pct

One row carries the entire disagreement: `chunk2-23`, scored 1 by A and C and 0
by B.

## 3. The pinned verdict

PREREGISTRATION section 7a, applied literally to the SET-identity numbers and to
nothing else.

    d_AB = 16, d_AC = 12, d_BC = 19
    pairwise rates: 26.7 pct, 20.0 pct, 31.7 pct
    pooled p = (16 + 12 + 19) / 180 = 47 / 180 = 26.1111 pct

    CONFIRMED condition: p >= 15.0 pct AND every pairwise rate >= 10.0 pct.
      p = 26.1 pct >= 15.0 pct                                   satisfied
      min pairwise rate = 20.0 pct (A-C) >= 10.0 pct             satisfied

    REFUTED condition: every pairwise rate < 10.0 pct.
      min pairwise rate = 20.0 pct                               not satisfied

### VERDICT: **CONFIRMED**

Read exactly as section 7a words it: the per-row `prevention` SET disagreement
rate is within reach of one in five, and it is not carried by a single unlucky
pair - the lowest of the three pairwise rates, 20.0 pct, is itself twice the
10.0 pct floor. Nothing was rounded to reach this; the pooled figure clears its
threshold by 11.1 points and the weakest pair clears its floor by 10.0 points.

Per section 8 of the pre-registration, which committed this asymmetry in advance:
**CONFIRMED is the stronger of the two verdicts here**, because a design whose
scorers share a model and a house style is biased toward agreement, so the
disagreement measured survived that homogeneity rather than being produced by it.
That is the same fact as the bound at the top of this file, and it is stated here
rather than at the end because it belongs in the same breath as the verdict.

### 3.1 The same thresholds at the FAMILY grain: INDETERMINATE

Section 4.1 below argues that the convention underwrites the FAMILY level and
declines the per-value level. That argument has a price, and RC pays it here, in
the verdict section, rather than in a footnote. Applying section 7a's own
thresholds to the FAMILY numbers - the same rule, the same grain discipline, per
row, per pair, pooled over 3 pairs x 60 rows:

    d_AB = 10, d_AC = 8, d_BC = 8
    pairwise rates: 16.7 pct, 13.3 pct, 13.3 pct
    pooled p = (10 + 8 + 8) / 180 = 26 / 180 = 14.4444 pct

    CONFIRMED condition: p >= 15.0 pct AND every pairwise rate >= 10.0 pct.
      p = 14.4444 pct >= 15.0 pct                                NOT satisfied
      min pairwise rate = 13.3 pct >= 10.0 pct                   satisfied

    REFUTED condition: every pairwise rate < 10.0 pct.
      min pairwise rate = 13.3 pct                               not satisfied

    FAMILY-grain verdict: **INDETERMINATE**

**The two readings disagree, and the flattering one is not the one RC's own
argument supports.** At the pre-registered SET grain the verdict is CONFIRMED. At
the FAMILY grain - the level section 4.1 argues is the only one the instrument
actually defines - the identical thresholds return INDETERMINATE, missing the
pooled bar by 0.5556 points. RC cannot hold both "only the family number is a
property of the instrument as written" and "the verdict is CONFIRMED" without
saying out loud that the second is measured at the level RC itself just called
delegated. So RC says it.

Which reading RC prefers, and what preferring it costs:

- **RC reports CONFIRMED as the headline**, because section 7a was pinned to the
  `prevention` SET statistic in a pre-registration committed at `3434990c0`
  before any row was scored. Re-pointing a pinned threshold at a different
  statistic after seeing the numbers is precisely the move a pre-registration
  exists to prevent. The SET verdict is the one RC promised to report, and it is
  reported unchanged.
- **The cost is that the headline verdict is measured at the grain RC's own
  instrument argument says the convention does not underwrite.** A reader who
  accepts section 4.1 should read this experiment as INDETERMINATE rather than
  CONFIRMED. RC does not think that reader is making an error, and does not
  claim the SET reading defeats the FAMILY one.
- Neither grain returns REFUTED. On both, the REFUTED condition fails outright,
  so nothing in this document supports "the scorers agree".

The honest summary of this experiment is therefore two-part, and stays two-part
wherever it is quoted: **CONFIRMED at the pre-registered SET grain, INDETERMINATE
at the FAMILY grain that RC's own reading of the instrument prefers.** Quoting
only the first half misrepresents the result.

## 4. RC's actual contribution: the family number beside the set number

### 4.1 Which level the instrument underwrites

The two `prevention` numbers, side by side, at the same grain and aggregation:

    prevention SET identity, pooled over 3 pairs x 60 rows:
        agree 133 of 180 = 73.9 pct,  disagree 47 of 180 = 26.1 pct
    prevention FAMILY,       pooled over 3 pairs x 60 rows:
        agree 154 of 180 = 85.6 pct,  disagree 26 of 180 = 14.4 pct

**The convention underwrites the FAMILY level and declines the per-value level,
and it says so in its own heading.** Section 2 is titled
"`prevention` - LW grades the FAMILY, and does not apply a precedence order". It
then lists the eight values grouped IN-FAMILY and OUT-FAMILY and defines
`gate_or_contract` over that grouping. It supplies **no per-value definitions**.
It delegates them - "grade by v1.2's eight definitions" - to a document that is
not the instrument. RC verified this by grep before computing anything.

LW's headline claim, "the SCORER beats the CONTRACT", rests on the SET-identity
number. That number is a measurement of reader spread over a vocabulary the
instrument names but does not define. The FAMILY number is the one measured over
a distinction the instrument actually states. **Both are reported here; only the
family number is a property of the instrument as written.** The set number is a
property of the instrument plus whatever definitions each reader had to
manufacture to use it - which is section 4.2.

This does not make the set number worthless and RC does not discard it. The
pre-registered verdict is written against it and is reported against it, exactly
as pinned. It does mean the set number cannot be read as "one pre-registered
convention left 26.1 pct residual", because on that axis there was no
pre-registered definition to leave a residual against.

### 4.2 The manufactured definitions, and where they diverged

**All three scorers independently opened their `## Ambiguities I resolved`
section with the same finding: the eight `prevention` values are NAMED but not
DEFINED in the instrument, and each had to declare working definitions from the
value names before any row could be graded.** A calls it item 1; B calls it
"the single largest discretion in this scoring and every row depends on it"; C
says "every figure here is conditional on those derivations". Three independent
readers reaching that conclusion separately is the finding, not a coincidence.

Six divergences between the manufactured definitions are visible in the three
files. Each is named here from the scorers' own text.

**D1 - the scope of CONTRACT.** A narrowed CONTRACT to rows whose own text NAMES
or directly implicates a specific rule, fence, spec or convention, on the stated
ground that RC's standing directives would otherwise make CONTRACT apply to
nearly every row. B declared the broad form: "a stated standing rule would have
prevented it and was not followed". C declared "a stated rule whose observance
would have prevented it". B therefore reaches CONTRACT on rows where A and C do
not. This is the largest single source of set disagreement in the sample.

**D2 - where the GATE-ABSENT / ADVERSARY line falls.** All three saw the same
collapse risk and all three drew a line to stop it, but not the same line. A
declared ADVERSARY a RESIDUAL, assigned only where no other value applies. B
declared one test: could a named mechanised instrument, if written, have caught
this - yes GATE-ABSENT, no ADVERSARY. C drew it on the SHAPE OF THE DEFECT - a
discrete checkable datum (a count, a path, a line range, a symbol's presence) is
gate-shaped and takes GATE-ABSENT, while a reasoning error, a
mischaracterisation or an over-broad statement takes ADVERSARY. C's line moves
rows off ADVERSARY that A's and B's leave on it. B and C both flagged this as
their largest judgement call.

**D3 - PROXY-MEASURE against GATE-ABSENT.** B declared a restrictive
PROXY-MEASURE, used only where the row text itself shows one quantity standing
in for another, and named `chunk1-41`, `chunk3-44` and `chunk1-24` as close calls
resolved to GATE-ABSENT. A and C did not declare a comparable restriction. This
divergence crosses the family boundary in both directions, so it moves the family
number as well as the set number.

**D4 - whether a newly written test or a tool under construction is "a named
mechanised instrument with a firing verb".** A resolved that it is, naming
`chunk1-31` and `chunk2-33`, and recorded that the opposite resolution would move
both to GATE-ABSENT. C resolved the same way, naming `chunk1-31`, `chunk2-29` and
`chunk2-33`, and separately admitted `chunk4-04`'s "baselining check" as its
borderline case. B declared no such rule and scored the affected rows
GATE-ABSENT. A and C each predicted the exact rows this would move, in advance of
seeing any disagreement.

**D5 - whether a straddling row is recorded as a multi-value set.** A recorded
genuine straddles as multi-value sets and produced 2 SPLITs; C took a set of one
as legal and assigned multiple values only where two had independent grounds in
the row's own text, producing 1 SPLIT; B produced 1 SPLIT from 4 multi-value
sets. This is the whole of the `chunk1-07` family disagreement.

**D6 - `origin_time`: whether an in-session DIRECTIVE is "tracked".** Section 3
declares a boundary for an in-session subagent REPORT (FRESH) and says nothing
about a directive or dispatch handed down to a slice. A and B both treated a loop
directive as a TRACKED artifact (INHERITED). C split it by commit state: a
directive already committed is INHERITED, one written and consumed in-session is
FRESH. **This divergence produced ZERO measured disagreement in this sample** -
the FRESH / INHERITED grain was unanimous on all 60 rows. It is recorded because a
declared divergence that did not bite is a real finding about where the convention
is load-bearing, and dropping it would flatter the instrument.

**D7 - the DECAYED / BORN-WRONG / OVER-GENERALISED default.** B and C each
declared that the sub-value test is stated "not at all" by the convention and each
declared a default of BORN-WRONG unless the row's own wording time-indexes the
falsity, listing the trigger phrases. A declared no sub-value rule. All three
sub-value disagreements in the sample sit here.

**D8 - whether a forward `fix_chain` link established by a DIFFERENT row in the
same corpus counts.** A resolved that it does and scored `chunk2-23` as 1; C
resolved the same way and named the same row plus the row that establishes the
link; B extended section 4's floor rule downward instead and did not adopt a
cross-row link. This is the entirety of the `fix_chain` disagreement.

### 4.3 Attribution of the set disagreements

Attribution rule, stated so it can be checked: a row is attributed to a named
divergence only where a scorer's own `## Ambiguities I resolved` text states a
rule, or names that row, such that the observed split FOLLOWS from the stated
rule. A row that merely looks like it could belong to a divergence is not
attributed. Attribution is at the ROW grain and each row is assigned one primary
divergence; the comparison-grain figure beside it is the sum of that row's
differing pairs.

    D1 CONTRACT scope           7 rows: chunk2-01, chunk3-01, chunk1-04,
                                        chunk4-07, chunk1-21, chunk2-17,
                                        chunk4-34
    D3 PROXY-MEASURE line       6 rows: chunk4-01, chunk3-31, chunk1-41,
                                        chunk1-47, chunk1-54, chunk3-44
    D2 GATE-ABSENT / ADVERSARY  3 rows: chunk2-07, chunk2-20, chunk1-34
    D4 new instrument as gate   2 rows: chunk4-04, chunk2-33
    D5 straddle as a set        1 row:  chunk1-07
    ------------------------------------------------------------------
    author's first pass        19 of the 23 rows with any set disagreement
    after refutation           approx 15 of the 23 rows (see the two defects
                               named immediately below)
    not attributed, first pass  4 rows: chunk4-14, chunk4-24, chunk4-30,
                                        chunk3-41

**Correction: these are editorial figures, not computed ones, and an independent
refutation pass reduces them.** `tally_overlap.py` computes no attribution at all
(see the provenance note at the top of this file), so the table above is the
author's judgement over the script's named-row dump. Two defects, both named at
the row grain so either can be checked against the scorer files:

- **`chunk2-01` was filed once under D1 but fed all three of its comparisons to
  the D-series total, and one of those legs is not D1.** `chunk2-01` is the one
  row where all three scorers differ, so it contributes 3 pairwise comparisons.
  Its A-C leg is an ADVERSARY-against-GATE-ABSENT shape, which is D2, not the D1
  CONTRACT scope the row was filed under. Crediting all three comparisons to a
  single divergence overstates the comparison-grain figure.
- **D3 is the weak claim: three of its six rows run OPPOSITE to the rule they are
  attributed to.** B declared a RESTRICTIVE PROXY-MEASURE, used only where the
  row text itself shows one quantity standing in for another. On `chunk4-01`,
  `chunk3-31` and `chunk1-47`, B is the scorer who ASSIGNS PROXY-MEASURE - the
  opposite direction to B's own declared restriction. Section 4.3's own rule
  requires the observed split to FOLLOW from the stated rule; here it runs
  against it, so those three rows are withdrawn from D3.

Restated after refutation, at the ROW grain over the 23 rows carrying any set
disagreement: **approximately 15 of 23 disagreeing rows trace to a definitional
divergence that a scorer declared in writing before any comparison existed.** The
figure is deliberately given as approximate - it is judgement over a named-row
dump, not arithmetic, and a different reader applying the same rule could land a
row on either side. **The pooled comparison-grain figure previously published
here, "39 of 47 pairwise set disagreements attributed", is WITHDRAWN rather than
restated**, because it inherits both defects above and no corrected value was
computed to replace it.

**The four unattributed rows, named rather than absorbed.** `chunk4-14` turns on
GATE-FIRED-IGNORED against GATE-EXISTING, where A's, B's and C's manufactured
definitions are near-identical in wording, so the split is a different reading of
the row's facts and not of the vocabulary. `chunk4-24`, `chunk4-30` and
`chunk3-41` are all C assigning CONTRACT-MISFIRED where A and B do not.
**RC deliberately does not attribute these three.** B's manufactured
CONTRACT-MISFIRED is causal ("a stated rule was followed and following it caused
the defect") while A's and C's are validity-based and nearly the same words as
each other ("honoured and was itself wrong or expired" against "applied and was
itself wrong or out of its validity"), so the stated texts might predict the
C-against-B leg but demonstrably do NOT predict the C-against-A leg. Claiming
them would be overclaiming, and the attribution is worth less if it is padded.

Stated plainly and without inflation, at the ROW grain over the 23 rows with any
set disagreement: **approximately 15 of 23 disagreeing rows trace to a
definitional divergence that a scorer declared in writing before any comparison
existed. The remaining rows do not, and RC records them as unexplained rather
than assigning them a mechanism. No comparison-grain attribution figure is
claimed.** The higher pair of figures this paragraph used to carry, 19 of 23 and
39 of 47, was the author's editorial judgement presented with more confidence
than the stated attribution rule supports.

The size of that attributed share is still the substantive result of this
section, at the weaker figure. A majority of the set-level disagreement is NOT
reader noise over a shared definition. It is three readers applying three
different definitions,
each of which they had to invent because the instrument named the vocabulary and
delegated its meaning elsewhere. That is a property of where the convention stops,
not of how carefully the readers read.

## 5. Comparison to LW at n=29

LW's four figures, from
`moon_sync_inbox/2026-09-13-0900-from-LW-CROSS-SCORE-RESULT-...md` section 5, one
pair of scorers over 29 rows, beside RC's pooled figures, three pairs over 60 rows
each:

    quantity                     LW, 1 pair, n=29      RC, pooled 3 pairs, n=180
    family agreement             27 of 29 = 93.1 pct   154 of 180 = 85.6 pct
    prevention SET identical     23 of 29 = 79.3 pct   133 of 180 = 73.9 pct
    origin_time                  26 of 29 = 89.7 pct   174 of 180 = 96.7 pct
                                                       (family+sub-value grain)
                                                       180 of 180 = 100.0 pct
                                                       (family-only grain)
    fix_chain >= 1               24 of 29 = 82.8 pct   178 of 180 = 98.9 pct

RC's widest single pair is B-C at 68.3 pct set agreement and RC's narrowest is
A-C at 80.0 pct; LW's single pair at 79.3 pct falls inside that range.

**What RC does NOT claim from this table.** RC does not present these numbers as
corroborating LW's, and does not present them as refuting LW's. Agreement between
two rates measured by readers who share a model is not evidence that either rate
is right. **RC's three scorers share a model and a house style with each other,
and LW's two scorers were drawn the same way**, so the entire comparison sits
inside one model family and the correlated half of the variance is invisible to
both designs. What the table can support is narrow: on the load-bearing set
statistic, two separately pre-registered designs on two different samples both
land in the same region, and RC's larger sample did not make the residual
disappear.

Two of the four quantities are not comparable in the direction the table's
alignment suggests, and saying so matters more than the tidy row:

- **`origin_time`.** RC publishes both grains precisely so this cannot be picked
  after the fact. At the family-only grain RC's scorers were unanimous on every
  row, 180 of 180. At the family-plus-sub-value grain RC is 96.7 pct. LW's
  26 of 29 = 89.7 pct is below both. RC cannot say which grain LW's figure was
  computed at, and therefore does not assert a direction for this row of the
  table. **A second and more serious reason not to read this row as a contrast is
  in section 6: RC's family-only 100.0 pct is measured on a sample containing at
  least one demonstrated value leak through retained prose, so it may be
  inflated.**
- **`fix_chain >= 1`.** RC's 98.9 pct rests on a single disagreeing row out of 60
  and on a sample in which 172 of 180 row-scorings are `fix_chain` 0. A boolean
  whose one side is that rare agrees easily; the figure is close to a measurement
  of the base rate rather than of reader spread, and should not be read as RC's
  scorers being ten times more consistent than LW's on this axis.

The one comparison RC does think is load-bearing is the SET against FAMILY gap
inside RC's own numbers - 73.9 pct against 85.6 pct pooled, a **11.7 point**
spread between the level the instrument defines and the level it delegates. LW's
own pair shows a gap in the same direction and of similar size, 79.3 pct against
93.1 pct = 13.8 points. Neither tree's readers disagree much about the family
question the convention states. Both trees' readers disagree substantially about
the per-value question it does not.

## 6. A measured blinding leak, and what it costs the `origin_time` figure

This is a finding, not a caveat, and it is reported at full size rather than
folded into a limitations list.

**The instance.** Row `chunk1-04`'s RETAINED `quote` field reads, verbatim:

    EVERY INHERITED NUMBER WAS WRONG, AND SO WAS THE PREMISE

The blinding step strips the `origin_time` field. It did strip it. But that quote
contains the stripped field's VALUE - the literal token `INHERITED` - and a
near-verbatim form of its sub-value in the same clause. All three scorers
returned `INHERITED / BORN-WRONG` on that row. RC does not claim the scorers read
the value off the quote; RC claims that on this row it is not possible to
distinguish a judgement from a read, and that is the whole problem.

**Why the pre-registration could not catch it.** The pre-registered blinding
check greps FIELD NAMES. A field whose name is absent but whose VALUE survives
inside an adjacent retained free-text field is structurally invisible to a
name-based check - there is no name to find. This leak class cannot be detected
by the check as designed, on this sample or any other, so the clean result that
check returned is not evidence that no leak occurred.

**The consequence, stated against RC's own most flattering number.** RC's
`origin_time` family-only agreement is 180 of 180 = 100.0 pct, pooled over
3 pairs x 60 rows. That figure sits above LW's 26 of 29 = 89.7 pct, and it is the
row most tempting to present as RC's instrument being cleaner than LW's.
**It must not be presented that way.** At least one of the 60 rows carries a
demonstrated value leak on exactly the field that figure measures, the check that
was supposed to exclude such rows cannot see this leak class, and no count of how
many other rows leak the same way has been made. RC's 100.0 pct may be inflated
by value leakage through retained prose, by an unmeasured amount, and until that
amount is measured the figure is not a clean contrast against LW's 89.7 pct.

**Credit.** The sibling tree RSC raised exactly this failure class in its
2026-09-13 1000 note: that a stripping step must be TRUSTED rather than assumed,
and that a filed value can leak through an adjacent free-text field even when the
named field is correctly removed. RC recorded that as a general hazard. RC now
has a measured instance of it inside RC's own sample, on RC's own headline
`origin_time` figure. The general warning and the local instance are both on the
record here.

## 7. What this document does NOT report

Stated so that a reader does not infer coverage from silence. Each of these was
pre-registered and none is adjudicated here. None is computed below; the gap is
named, not closed.

- **Pre-registration item 7b - the pre-registered comparison of the SCORER term
  against the CONTRACT term - is not reported in this document at all.** That is
  half of the pre-registration's adjudication surface, and it is unadjudicated
  here. Nothing in sections 1 through 6 bears on it in either direction.
- **The per-chunk breakdown is pre-registered and absent.** Every rate in this
  document is pooled or pairwise over all 60 rows; no figure is reported per
  chunk, so nothing here shows whether disagreement is uniform across chunks or
  concentrated in some of them.
- **The Wilson intervals are pre-registered and absent.** Per section 7c and the
  task instruction, no bands or intervals are reported anywhere in this document.
  Every rate here is a bare point estimate, and the precision of each is
  unreported.

## 8. This document was attacked, and what the attack found

RC's practice is that a defect found in RC's own work goes into the record rather
than being quietly corrected. This document was put through an independent
refutation pass that re-derived every count from the scorer files.

**What survived.** Every raw count: SET identity 44 / 48 / 41 of 60 pairwise,
pooled 133 of 180 agree and 47 of 180 = 26.1111 pct disagree, 37 of 60 unanimous,
23 distinct disagreeing rows; FAMILY 50 / 52 / 52 of 60 pairwise and pooled 154
of 180 = 85.5556 pct agree. The family grouping was checked verbatim against
convention section 2 and is correct. The section 7a verdict on SET identity -
CONFIRMED, on p = 26.1111 pct >= 15.0 pct and min pairwise 20.0 pct >= 10.0 pct -
was independently re-derived and CONFIRMED stands. The grain discipline
throughout, comparing per-row rates only to per-row rates, was checked and holds.
No count in this document was changed by the attack.

**The five defects it found, all repaired above.**

1. **The verdict was reported only at the flattering grain.** Section 7a's own
   thresholds return INDETERMINATE at the FAMILY level - the level section 4.1
   argues the instrument actually underwrites - and the document did not say so.
   Repaired in section 3.1, in the verdict section rather than a footnote.
2. **A false sensitivity claim.** Section 2.2 said the mixed-set / SPLIT rule was
   stated "because it changes the number". Both defensible alternatives return
   identical figures on this sample. Repaired to the stronger and true claim:
   the family result is ROBUST to both.
3. **Attribution overstated.** "19 of 23 rows, 39 of 47 comparisons" does not
   follow from section 4.3's own attribution rule; the refuter makes it about 15
   of 23, with `chunk2-01`'s mis-fed A-C leg and D3's three reversed-direction
   rows as the named defects. Repaired in 4.3; the 39 of 47 figure is withdrawn.
4. **A false provenance claim.** "Every figure below is script output. Nothing
   was counted by eye" is false for section 4.3, which the script does not
   compute. Repaired at the top of the file and scoped to the sections the script
   actually produces.
5. **A real blinding leak.** `chunk1-04`'s retained `quote` carries the stripped
   `origin_time` value, and the pre-registered blinding check cannot see that
   leak class. Reported in full in section 6, with the consequence for RC's
   100.0 pct `origin_time` figure stated against RC's own interest.

Defects 1, 3 and 4 all point the same way: each made this document read stronger
than its evidence supports. Defect 2 pointed the other way. That asymmetry is
itself worth recording.

## 9. Reproducing these numbers

    C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe docs\_overlap\tally_overlap.py

The script reads only the three scorer files, fails loudly on any parse or
vocabulary defect, and prints every COUNT, RATE and VERDICT in sections 1, 2 and
3 plus the named disagreeing rows behind each one. It performs no scoring and
holds no scoring judgement of its own. **It computes NO attribution**, so nothing
in section 4.3 is reproduced by running it, and the section 3.1 family-grain
threshold check and the section 2.2 robustness re-derivations are applications of
the script's printed family counts rather than separate script outputs.
