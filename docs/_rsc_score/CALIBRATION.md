# CALIBRATION - RC scoring convention v1 re-applied to RC's own 198 published rows

**Status: results section pending until the tally lands. Method, blinding and
script-audit sections below are final and were written BEFORE any scored row
existed.** This file is written incrementally on purpose: a partial calibration
that states its own coverage honestly is worth more than a complete one that is
never committed.

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

## 4. Results

_Pending. Written when the three scorer files have been tallied._

---

## 5. Ambiguities in RC's convention that had to be resolved

_Pending. This section is the highest-value deliverable and is populated from
the three scorers' independently recorded resolutions plus the orchestrator's
own._

---

## 6. Verdict

_Pending._
