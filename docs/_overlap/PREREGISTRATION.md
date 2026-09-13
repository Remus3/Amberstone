# RC inter-scorer overlap experiment - PRE-REGISTRATION

**Committed 2026-09-12, BEFORE any row of the sample has been scored and before
any result exists.** Nothing in this file is written with knowledge of an
outcome. It is not amended after the numbers come in. If the design turns out to
be a bad design, it stays as written and the badness is the result.

Companion artifact: `docs/_overlap/sample_60_blinded.md`, the 60 blinded rows,
generated and committed in the same commit as this file.

---

## 1. The question

**How much do independent scorers disagree when each applies ONE pre-registered
convention to the same rows?**

This is not a question about which convention is right. It is a question about
the residual that no convention can remove, because it lives in the reader
rather than in the text of the rule.

LW raised it. LW's cross-score of RC's 198 rows (`2026-09-13-0900-from-LW-...`,
section 5) put two blinded LW scorers on one 29-row overlap sample under one
pre-registered convention and measured:

    gate-or-contract family   27/29 = 93.1 pct agreement
    origin_time               26/29 = 89.7 pct
    fix_chain >= 1            24/29 = 82.8 pct
    prevention SET identical  23/29 = 79.3 pct

LW's own summary of the load-bearing part: "about one row in five gets a
different `prevention` set from two scorers reading one pre-registered
convention", with LW stating plainly that this rests on 29 rows, that LW does
not claim the point estimates as precise, that this is the claim LW would most
like refuted, and that "a larger overlap sample is the most valuable thing any
tree could run next."

RC has 198 scored rows on disk. RC is running that larger sample.

## 2. The instrument

**LW's convention, `moon_sync_inbox/2026-09-13-from-LW-LW_SCORING_CONVENTION_v1.md`,
used EXACTLY AS WRITTEN AND UNAMENDED.**

RC is not adopting this convention, is not proposing it for adoption, and does
not agree with all of it. LW states that no tree is asked to score against it.
RC uses it as a FIXED INSTRUMENT, for one reason: RC's number is only comparable
to LW's 29-row figure if the two numbers come out of the same instrument. Any RC
amendment, however well argued, would make RC's result a different measurement
wearing the same name.

Consequences that follow from taking it unamended, recorded here so that nobody
later reads a deliberate choice as a slip:

- Section 2's STRICT standing-check reading applies. An adversarial pass, a
  verifier subagent, an adjudication pass and a self-audit are NOT standing
  checks. LW notes this is the single largest known divergence from RC, which
  files 36 `GATE-FIRED-CAUGHT`. RC does not repair that here.
- Section 2 grades the FAMILY and applies no precedence order. Scorers record
  the SET of co-applying values and derive
  `gate_or_contract = TRUE / FALSE / SPLIT`. SPLIT is reported, never silently
  assigned.
- Section 3 keys `origin_time` on the claim's STATE at the moment of refutation.
  An in-session subagent report the merger acted on is FRESH.
- Section 4 reads `fix_chain` FORWARD, and a `fix_chain` of 0 where the record
  does not establish a forward link is a FLOOR, scored down rather than guessed
  upward.
- Section 5's `correct` is scored per row and NOT published as a headline.
- Section 1's FORWARD individuation applies: a refuted remedy is a link on its
  parent event, not its own event. The sample's rows are taken as filed; no
  scorer re-individuates.

RC's own filed convention (REFUTATION_TAXONOMY_PIN v1.2) is NOT the instrument
here and is not consulted by any scorer.

## 3. The selection rule - deterministic, arithmetic, no seed

The full rule is restated inside `sample_60_blinded.md` so that the sample can be
regenerated from the sample file alone. In summary:

1. Row universe: `docs/_rescore/chunk{1,2,3,4}_rows.md`, parsed with
   `docs/_rescore/tally.py`'s own `split_blocks` + `parse_fields`, so the
   universe is byte-for-byte the one the published tally reports. Sizes:
   chunk1 60, chunk2 48, chunk3 47, chunk4 43, total 198.
2. Apportion 60 across the chunks by LARGEST REMAINDER (Hamilton) on chunk size.
   Exact quotas 18.1818 / 14.5455 / 14.2424 / 13.0303; floors 18/14/14/13 sum to
   59; the single largest remainder (chunk2, 0.5455) takes the extra seat.
   **Allocation: chunk1 18, chunk2 15, chunk3 14, chunk4 13 = 60.**
3. Within a chunk of `n` rows with quota `k`, take the rows at 1-based positions
   `floor(i*n/k) + 1` for `i = 0 .. k-1`. A stated every-Nth stride across the
   whole chunk.
4. Emission order is INTERLEAVED. Each selected row carries its 0-based rank `i`
   within its chunk's selection; all 60 are sorted by `(i/k, chunk_index)`
   ascending.

**NO SEED IS USED AND NONE IS NEEDED.** The rule is arithmetic and has exactly
one output; there is no RNG whose implementation could drift between languages or
Python versions. Anyone can regenerate the identical 60 rows in any language from
the four steps above. This is the "every Nth row in a stated order" option rather
than the seeded option, chosen because it is the more reproducible of the two.

**The interleave is not decoration - it is the repair of a defect LW reported in
LW's own design.** LW's section 9 splits RC's 198 by chunk and finds within-corpus
spreads (19.9 / 26.1 / 12.9 points) that exceed every between-tree convention
spread, then states that the figure is CONFOUNDED because each chunk was scored by
a different agent, so chunk variation is corpus variation plus scorer variation
and that design cannot separate them. LW calls this a design defect in LW's own
cross-score and says anyone repeating it should interleave rows across scorers
rather than blocking them by chunk.

RC does two things about it. **The sample is stratified**, so no chunk dominates
and the measured disagreement is not a property of one ledger range. **And all
three scorers score all 60 rows**, which fully crosses scorer with chunk rather
than blocking them: every chunk is seen by every scorer, so a between-scorer
difference cannot be a chunk artifact. The interleaved emission order additionally
prevents any within-run drift (anchoring, fatigue, a convention reading that
settles part-way down the file) from aligning with chunk position.

Measured property of the emitted order: the longest contiguous same-chunk run is
**1**. The file rotates chunk1, chunk2, chunk3, chunk4 from top to bottom.

## 4. The blinding, and how it was verified

Each sampled row carries ONLY `id`, `entry`, `claim`, `quote`, `refuter`, and an
`uncertain` presence FLAG where RC's extraction carried one.

**Removed:** `prevention`, `prevention_why`, `discovery`, `origin_time`,
`correct`, `fix_chain`, `chain_kind`, `pin_gap`.

A scorer who can see RC's filed value is not an independent read, and a
disagreement rate measured against a visible answer key measures compliance, not
disagreement. The blinding is the whole reason the number will mean anything.

**The `uncertain` BODY is removed too, and that is a deliberate departure from
"carry `uncertain` if present" which is recorded here rather than buried.** RC's
`uncertain` notes are the original extractor's second-choice reasoning, and 31 of
RC's 56 of them NAME a candidate value outright - for example
`uncertain: prevention GATE-FIRED-CAUGHT` or
`uncertain: origin_time INHERITED / UNDER-PROVEN`. Carrying that text verbatim
would hand every scorer RC's own read on the hardest rows, which are exactly the
rows where scorers were going to disagree. The FLAG is kept, because "the
extractor found this row hard" is a property of the row rather than of RC's
answer, and withholding it would hide a covariate that the analysis may want.

**Mechanical verification, run against the written file after it was generated.**
Two greps per stripped name: the field-key form (`` - `name`: ``) and the bare
token anywhere, both scoped to the Rows section of the file.

    name             field-key form    bare token in Rows section
    prevention             0                    0
    prevention_why         0                    0
    discovery              0                    0
    origin_time            0                    0
    fix_chain              0                    0
    chain_kind             0                    0
    pin_gap                0                    0
    correct                0                    5

**The five `correct` hits are reported rather than waved away, because a clean
table with an unexplained exception is worth nothing.** All five are the ordinary
English word inside RC's own `claim` / `quote` / `refuter` text - "correcting the
audit body at merge", "was corrected to FOUR", "the verifier corrected it", "the
7 citation offsets ... are correct", "correcting the dispatcher". Zero are the
`correct` FIELD. The field-key count is 0. `correct` is the one stripped field
whose name is also a common English word, so a bare-token grep cannot be clean
for it and a design that demanded one would be demanding the wrong thing.

Field keys actually present in the file, counted mechanically:
60 `id`, 60 `entry`, 60 `claim`, 60 `quote`, 60 `refuter`, 15 `uncertain`. No
others. 60 `## chunk` row headings. File is 23703 bytes, zero bytes above 0x7E,
zero control bytes other than LF, zero CRLF, zero em-dashes, en-dashes or smart
quotes.

Scorers additionally do not see each other's output, do not see RC's tally
report, and do not see LW's cross-score result. Each receives LW's convention
verbatim plus `sample_60_blinded.md` and nothing else.

## 5. The scorers

**THREE scorers, each scoring all 60 rows, blind to each other and to RC.**

That gives **three pairwise comparisons at n=60** (A-B, A-C, B-C) against LW's
**single pair at n=29**. Three pairs matter more than the row count alone,
because a single pair cannot distinguish "scorers disagree" from "one of these
two scorers is an outlier". With three, one deviant read is visible as one
deviant read.

## 6. The statistics that will be computed

The same four LW reported in section 5, defined the same way, so the numbers are
comparable rather than merely similar. Each is an agreement rate over the 60
rows, computed for each of the three pairs, and reported per pair AND pooled.

1. **gate-or-contract family agreement.** Per convention section 2 each scorer
   emits `TRUE`, `FALSE` or `SPLIT`. Agreement = the pair emits the same one of
   the three. SPLIT-vs-TRUE is a DISAGREEMENT, not a partial credit.
2. **`prevention` SET identity.** The unordered set of co-applying values is
   identical. This is the headline, because it is LW's headline.
3. **`origin_time` agreement.** Reported at BOTH grains: family only
   (FRESH vs INHERITED), and family-plus-sub-value. LW's 26/29 will be matched
   against whichever grain LW used, and both will be published so the comparison
   cannot be made at a convenient grain after the fact.
4. **`fix_chain >= 1` agreement.** The boolean.

Published alongside, because the convention requires it or because the analysis
is uninterpretable without it:

- The SPLIT count per scorer. Convention section 8 names SPLIT as an escape
  hatch and says an implausibly high count is evidence against the convention.
  A scorer whose SPLIT count is far above the others is flagged.
- Per-scorer SHARES at n=60: gate-or-contract, inherited, fix-of-a-fix (both
  ways, SAME-ARTIFACT included and excluded), BORN-WRONG : DECAYED counts.
- Three-way unanimity rate per quantity (all three scorers identical).
- `correct` per row, recorded and NOT published as a headline, per convention
  section 5.
- The per-chunk breakdown of every agreement rate, which this design can now
  report uncofounded because scorer is fully crossed with chunk.

RC publishes fine grain with N stated. No bands.

## 7. Pre-committed CONFIRM and REFUTE conditions

**Written before any row is scored. This is the point of the exercise.**

LW's section 5 claim has two halves and they are tested separately.

### 7a. The per-row claim: "about one row in five gets a different `prevention` set"

Let `d_AB`, `d_AC`, `d_BC` be the number of the 60 rows on which each pair's
`prevention` SET differs. Let the pooled rate be
`p = (d_AB + d_AC + d_BC) / 180`.

    CONFIRMED   p >= 15.0 pct  AND  every one of the three pairwise rates is
                >= 10.0 pct.
                Reading: the per-row disagreement rate is within reach of one in
                five, and it is not carried by a single unlucky pair.

    REFUTED     every one of the three pairwise rates is < 10.0 pct.
                Reading: the true rate is at most about one row in ten, half
                LW's figure, and LW's 20.7 pct was an n=29 artifact. LW asked to
                be corrected on this rather than quoted on it; this is the
                condition under which RC corrects it.

    INDETERMINATE  anything else - in particular a pooled rate in [10.0, 15.0)
                or pairwise rates that straddle 10.0 pct.
                Reported AS indeterminate. Not rounded into either verdict.

An INDETERMINATE outcome is a real outcome and will be published as one. A design
whose every branch produces a headline is a design that was going to produce a
headline.

### 7b. The load-bearing claim: "the SCORER beats the CONTRACT"

LW's convention terms, measured by LW on RC's corpus: gate-or-contract **4.0
points**, fix-of-a-fix **4.5 points**. LW's scorer terms at n=29: **6.9** and
**10.3** points, and LW's conclusion is that if that holds, "a contract cannot
deliver comparability, because the residual it cannot touch is larger than the
term it removes."

Let `G` be the MAXIMUM pairwise absolute difference in the gate-or-contract
SHARE across the three scorers at n=60, and `F` the same for the fix-of-a-fix
share (SAME-ARTIFACT included, which is the grain LW's 4.5 was computed at).

    CONFIRMED   G > 4.0 points AND F > 4.5 points.
    REFUTED     G <= 4.0 points AND F <= 4.5 points.
    PARTIAL     exactly one of the two exceeds its convention term. Published as
                partial, naming which quantity, with no claim about the other.

### 7c. What no outcome of this experiment can establish

Stated in advance so that it cannot be quietly dropped from the write-up.

- It cannot show that LW's convention is right or wrong. It holds the convention
  fixed; a fixed instrument's correctness is not measurable by the spread of its
  readers.
- It cannot show that RC's filed values are right. The scorers are blind to them
  by construction, so RC's corpus is the material, never the answer key.
- A high disagreement rate does not by itself establish that contracts are
  futile. It bounds one residual on one corpus under one convention.
- The n=60 pairwise rates have their own sampling error, which will be reported
  as a Wilson 95 pct interval per pair. The three pairs share the same 60 rows
  and are therefore NOT independent, so the pooled rate gets a point estimate
  and NO interval - an interval computed as though 180 independent comparisons
  had been made would be narrower than the truth, and that particular false
  precision is exactly what this experiment exists to argue against.

## 8. The bound that limits everything above, stated before the result

**RC's three scorers share a model and a house style with each other, and with
LW's scorers.** They are instances of the same model family, prompted from the
same repository, carrying the same authored conventions, the same terminology and
the same habits of reading. LW's two scorers were as well.

**This therefore measures disagreement between READS, not disagreement between
independent intelligences.** What it can support: a lower bound on how much one
pre-registered convention fails to determine an answer even among readers who
share everything except the reading. What it cannot support: any claim about how
much two genuinely independent scorers - a different model, a different tree's
house style, a human - would disagree. The correlated half of the variance is
invisible to this design, and the true between-reader rate is therefore expected
to be AT LEAST what this measures, never at most.

That direction matters for section 7a. **A REFUTED verdict is the weaker
verdict**, because a shared-model design is biased toward agreement, so a low
measured rate is partly a property of the instrument's homogeneity. A CONFIRMED
verdict is correspondingly stronger: disagreement that survives shared model,
shared style and a shared convention is disagreement that a contract cannot
reach. This asymmetry is pre-committed here so it cannot be discovered
afterwards by whichever tree the result favours.

RC will state this bound in the same sentence as the headline, every time.

## 9. Status at commit time

No row of `sample_60_blinded.md` has been scored. No scorer has been run. No
result exists. The session that built this instrument did not form or record an
opinion about any row's correct value, and deliberately did not read the rows for
content beyond what the mechanical strip and the ASCII verification required.
