# Adjudication A - independent re-grade of RC's refutation rows

Read-only pass. The adjudicator did NOT produce any of the four row files and did not
extract the events. Contract applied: `moon_sync_inbox/2026-09-12-from-LW-REFUTATION_TAXONOMY_PIN_v1_2.md`,
sections 1 through 7. Source of truth: `docs/LEDGER.md` entries 1365 to 1406.
Every figure below was derived in this pass; none is carried forward from a row file,
a scorer's summary or a prior session.

---

## 1. Population and selection rule

Rows present, counted by `^## chunk<N>-` headings in this pass:

| file | rows |
|---|---|
| `docs/_rescore/chunk1_rows.md` | 60 |
| `docs/_rescore/chunk2_rows.md` | 48 |
| `docs/_rescore/chunk3_rows.md` | 47 |
| `docs/_rescore/chunk4_rows.md` | 43 |
| total | 198 |

**Selection rule, stated so it is reproducible and cannot be cherry-picked.** Within each
file, rows are indexed 1..N in file order (ids run `chunkN-01` upward with no gaps, verified
this pass). Sample index k, for k = 1..10, is:

```
index(k) = round( (k-1) * (N-1) / 9 ) + 1
```

This spreads ten evenly spaced rows from the first to the last of each chunk, ten per chunk,
forty in total. No row was chosen for looking interesting, and the rule was fixed before any
row body was read.

Resulting sample:

- chunk1 (N=60): 01, 08, 14, 21, 27, 34, 40, 47, 53, 60
- chunk2 (N=48): 01, 06, 11, 17, 22, 27, 32, 38, 43, 48
- chunk3 (N=47): 01, 06, 11, 16, 21, 27, 32, 37, 42, 47
- chunk4 (N=43): 01, 06, 10, 15, 20, 24, 29, 34, 38, 43

Method per row: open the cited ledger entry at full length, confirm the `quote` appears
verbatim, form an independent judgement on `prevention`, `discovery`, `origin_time` and
`correct` from the entry text plus the contract, then compare to the scorer's value.

---

## 2. Integrity check - quotes and entry numbers

This check was run mechanically over **all 198 rows**, not only the 40 sampled, because it is
cheap and objective. Each row's `quote` field was unwrapped from its backtick fence,
whitespace-normalised, and searched for inside the whitespace-normalised body of the ledger
entry its `entry` field names.

**Result: 0 wrong entry numbers. 1 non-verbatim quote of 198 (0.5 percent).**

- Every `entry` value resolves to a real `docs/LEDGER.md` entry, and in every case the quote
  (or, for the single exception, the quote minus one markup token) was found in THAT entry
  and not in a neighbouring one. No row cites the wrong entry.
- **`chunk4-42` (entry 1406) is the one non-verbatim quote.** The row reads
  ``was ALREADY RED at `9b4bb834d`, on exactly this shape, from entry 1405's own "pin advanced" parenthetical``.
  The ledger reads ``was ALREADY RED at `9b4bb834d`**, on exactly this shape, from entry 1405's own "pin advanced" parenthetical``.
  The row dropped a bold-close `**` that sits mid-string in the source. **Substance is
  identical; this is markup stripping, not a fabricated or altered quote.** It is recorded
  because "verbatim" is the property being claimed, not because the row is misleading.
  `chunk4-42` is NOT in the 40-row sample; it was caught only by the full-corpus sweep, which
  is an argument for running that sweep rather than sampling for this class.

No integrity failure of the serious kind (a quote absent from the ledger, or present in a
different entry from the one cited) was found anywhere in the corpus.

---

## 3. Per-field results over the 40-row sample

Each of the four fields was graded on each of the 40 rows: 160 comparisons.

Three outcomes are used. **AGREE** - my independent value matches, or the scorer's value is
one I judge correct. **DISAGREE** - I positively judge a different value better on the
contract as written. **GAP** - two values are equally supported and the contract does not
break the tie; per the brief these are recorded as contract gaps rather than resolved
arbitrarily and counted as agreement.

| field | agree | disagree | gap | disagreement rate | disagree+gap rate |
|---|---|---|---|---|---|
| `prevention` | 34 | 2 | 4 | 5.0 pct | 15.0 pct |
| `discovery` | 39 | 0 | 1 | 0.0 pct | 2.5 pct |
| `origin_time` | 35 | 3 | 2 | 7.5 pct | 12.5 pct |
| `correct` | 40 | 0 | 0 | 0.0 pct | 0.0 pct |
| **all four** | **148** | **5** | **7** | **3.1 pct** | **7.5 pct** |

### 3.1 The five disagreements, each with its clause

| id | field | scorer | mine | clause | reason |
|---|---|---|---|---|---|
| chunk1-21 | prevention | GATE-ABSENT | CONTRACT | s2 `CONTRACT` | The defect is an adjudicator's prose mischaracterising a shipped mechanism ("trimmed to 200 rows" for a rotate-with-carry-tail). No mechanical check reaches free prose about a mechanism; a declared precondition to cite the symbol before describing its behaviour would have. |
| chunk1-53 | prevention | GATE-ABSENT | PROXY-MEASURE | s2 `PROXY-MEASURE` | A fixture making the record path a directory is a CORRECT instrument answering the WRONG question - it exercises the unreadable gate, not the unwritable branch. The same scorer used PROXY-MEASURE for exactly this shape at chunk1-03 and chunk1-07, so this is an internal inconsistency, not a borderline reading. |
| chunk1-40 | origin_time | FRESH | INHERITED / DECAYED | s4 `DECAYED` | The mutant needle and the comment asserting it is stable "because its line is unchanged" predate this item and live in a tracked test file, which is a durable record. It was TRUE WHEN WRITTEN and the world moved when this work relocated the call site. Entry 1369 says the comment was rewritten, which is what identifies the inherited claim. |
| chunk3-01 | origin_time | INHERITED / BORN-WRONG | INHERITED / DECAYED | s4 `DECAYED` | Entry 1396 states the premise's source sentence "self-staled inside `c00b9af89`, the very commit that added the 229-line guard". True when written, falsified by the same commit. The row's own `uncertain` field already names DECAYED. |
| chunk4-38 | origin_time | INHERITED / UNDER-PROVEN | INHERITED / UNKNOWN | s4 `UNKNOWN` | Entry 1406 says the history rows "carry counts and check names but not the quotes, so the per-sentence figure is NOT recoverable from them". The record does not resolve the claim either way, which is UNKNOWN, not "true as written and insufficient". The row's own `uncertain` field already names UNKNOWN. |

Two of the three `origin_time` disagreements are cases where the row's own `uncertain` line
names the value I independently arrived at. That is a point in the scorers' favour on
transparency and a point against the value they filed.

### 3.2 The seven contract gaps

**GAP 1, and it is the largest single defect in the pin as applied to RC: `prevention` gives
no precedence between a DEFECT-NATURE value and `GATE-FIRED-CAUGHT`.** Section 2 mixes three
different questions in one field: what mechanism would have prevented the defect
(`GATE-ABSENT`, `CONTRACT`), what kind of instrument error it was (`PROXY-MEASURE`,
`CONTRACT-MISFIRED`), and what actually happened to it (`GATE-FIRED-IGNORED`,
`GATE-FIRED-CAUGHT`). Whenever a standing adversarial gate or verifier DID catch an event,
`GATE-FIRED-CAUGHT` is literally true AND so is the nature value, and the pin never says
which wins. The pin's own remark that `GATE-FIRED-CAUGHT` "is the only value that counts
events where the tooling WORKED" reads as a precedence rule, but it is not stated as one.
Affected in the sample:

- `chunk1-27` - scorer CONTRACT; the first adversarial gate did catch it (entry 1371 item 4).
- `chunk3-06` - scorer PROXY-MEASURE; "the verifier REFUTED the number rather than confirming it".
- `chunk3-32` - scorer GATE-ABSENT; "Verification at merge, re-reading the build's own red report".

This matters because the scorers are not consistent about it: chunk1-37, chunk1-47, chunk1-50
and chunk1-51 all score an independent verifier catching something as `GATE-FIRED-CAUGHT`,
while chunk1-27, chunk3-06 and chunk3-32 do not. The inconsistency is the pin's fault first
and the scorers' second.

**GAP 2 - `chunk2-11` `prevention`.** The ledger (entry 1377) does not name what refuted the
struck-through-pointers claim. The surrounding paragraph attributes two neighbouring
refutations to the gate; this one is unattributed. CONTRACT and `GATE-FIRED-CAUGHT` are both
supportable and the SOURCE, not the contract, is what fails to decide.

**GAP 3 - `chunk2-27` `prevention`.** Scored `GATE-EXISTING` with `prevention_why: VACUOUS`,
for a guard the SAME SESSION was writing. Section 2's scope rule pins `GATE-EXISTING` to a
check "ALREADY PRESENT IN THIS TREE", and the pin does not say whether a check under
construction in the same session counts. This is the prevention-field twin of the pin's own
section 9 item 2, which flags exactly this ambiguity for `origin_time` and does not extend it.

**GAP 4 - `chunk2-27` `discovery`.** Entry 1383 attributes all eight findings to "building
rather than reasoning" and gives no per-finding mechanism. `RUN` and `SELF-AUDIT` are both
supportable. The general form of this gap is below.

**GAP 5 - `chunk3-21` `origin_time`.** The "0 vacuous rows over 675 test functions" figure
came from an audit document produced by the SAME session. This is precisely the pin's own
section 9 item 2, declared unresolved by LW. Scored FRESH for want of a value, same as LW's
three specimens.

**GAP 6 - `chunk3-47` `origin_time`.** The claim originated with the OPERATOR in-session.
Section 4 offers FRESH (this session's own work) or INHERITED (a durable record) and an
operator's spoken expectation is neither. The row flags this itself. **This is a gap LW did
not report and RC should send back to the fleet**, because an operator-driven tree will
accumulate these and they are currently all being filed as FRESH.

**GAP 7, structural, affecting `discovery` corpus-wide and NOT counted as a per-row gap above
because it would swallow half the field.** Section 3's seven values mix CHANNEL (`SIBLING`,
`OPERATOR`, `CI`) with METHOD (`CODE-READ`, `RUN`, `RESEARCH`) with STANCE (`SELF-AUDIT`).
A self-audit performed by reading code is scoreable as `SELF-AUDIT` or `CODE-READ` with equal
warrant, and RC's corpus is dominated by exactly that shape - `SELF-AUDIT` is 97 of 198 rows
(49.0 percent) in this pass's census. I graded these AGREE wherever the scorer's pick was
defensible, so the reported `discovery` disagreement rate of 0.0 percent should be read as
"the scorers were never indefensible", NOT as "the field is reliable". A second adjudicator
applying a different tie-break would produce a very different `discovery` histogram from the
same rows, and the two would not be comparable across trees. **This is the field LW's pin
should fix next.**

One point the pin DOES settle and the scorers did not notice: `chunk3-16` carries
`uncertain: SIBLING` for an event whose lens came from a sibling tree. Section 3 explicitly
refuses the "a run that needed a sibling's lens first" sub-distinction, so the local
mechanism is the answer and the uncertainty is closed. Scored AGREE.

---

## 4. Net directional effect

### 4.1 `prevention`

Scorer's distribution over the 40 sampled rows, derived this pass:

| value | scorer | mine (firm changes only) | delta |
|---|---|---|---|
| GATE-ABSENT | 16 | 14 | -2 |
| CONTRACT | 13 | 14 | +1 |
| GATE-FIRED-CAUGHT | 4 | 4 | 0 |
| GATE-EXISTING | 3 | 3 | 0 |
| ADVERSARY | 2 | 2 | 0 |
| PROXY-MEASURE | 2 | 3 | +1 |

**The largest `prevention` bucket does not change NAME, but it stops being a plurality.**
On the scorers' values GATE-ABSENT leads CONTRACT 16 to 13. On mine it is **14 to 14, a tie**.
A three-row lead in forty, decided by two rows, is not a result that survives being handed to
a second reader.

If the three GAP-1 rows are additionally resolved toward `GATE-FIRED-CAUGHT` (a reading the
pin's own prose invites but never states), the sample becomes GATE-ABSENT 13, CONTRACT 12,
GATE-FIRED-CAUGHT 8 - GATE-ABSENT leads again, by one row. The bucket ordering in RC's rows
is therefore **not robust**: three different defensible readings of the same 40 rows give a
clear GATE-ABSENT lead, a dead tie, and a one-row lead.

Corpus-wide context, censused this pass over all 198 rows: GATE-ABSENT 65, CONTRACT 50,
GATE-FIRED-CAUGHT 36, PROXY-MEASURE 18, GATE-EXISTING 17, ADVERSARY 10, CONTRACT-MISFIRED 1,
GATE-FIRED-IGNORED 1. The published margin is 15 rows over 198. **This pass measured a
per-row prevention movement of 5.0 percent firm plus 10.0 percent undecided; applied to 198
rows that is roughly 10 rows moving out of GATE-ABSENT and roughly 20 more unresolved, which
is larger than the 15-row margin.** No claim is made here about what a full re-grade would
return - 40 rows cannot support a point estimate - only that the margin is smaller than the
measured uncertainty, which is the condition under which a headline should not be published
as settled.

### 4.2 `origin_time`

Over the sample: FRESH 16 -> 15, INHERITED 24 -> 25. Within INHERITED, BORN-WRONG 13 -> 12,
DECAYED 6 -> 8, UNDER-PROVEN 4 -> 3, OVER-GENERALISED 1 -> 1, UNKNOWN 0 -> 1.

**The largest bucket does not flip.** INHERITED stays the majority and BORN-WRONG stays the
largest sub-value, but all three of my `origin_time` disagreements move in the SAME direction
- away from BORN-WRONG and UNDER-PROVEN, toward DECAYED and UNKNOWN. That is a directional
bias worth naming: the scorers lean toward the more damning sub-value. In the sample the
born-wrong-to-decay ratio goes from 13:6 (2.2 to 1) to 12:8 (1.5 to 1). LW reported 59:19
(3.1 to 1) on its own corpus. **RC's ratio is materially lower than LW's either way, and the
gap narrows further after adjudication** - the two trees' figures should not be compared
without saying so.

### 4.3 `correct`

Zero disagreements, and a caveat that matters more than the zero. **`correct` is `YES` on
198 of 198 rows corpus-wide.** There is not one `NO` and not one `UNCLEAR` anywhere. The pin's
section 5 exists because LW's raw `NO` rows collapsed from seven to one under the pinned
question; RC has nothing to re-read, so RC passes that check trivially and learns nothing
from it. A field that takes one value on every row of a corpus **carries zero information and
cannot contribute to any cross-tree ratio.** Two readings are available and the rows cannot
distinguish them: either RC's refutations really were all correct, or an extraction pass that
selects events BY their refutation will only ever find refutations that stuck. The second
is the survivorship shape the pin's own section 8 item 3 warns about, applied to a different
field. RC should publish `correct` with that sentence attached or not publish it at all.

---

## 5. Verdict

**SAFE WITH STATED CAVEATS. Not safe as an unqualified headline, and not in need of a full
re-grade.**

Grounds:

1. **Integrity is good.** 0 wrong entry citations of 198 and 1 quote of 198 off by a markup
   token. The rows are honest about their sources and they are checkable, which is the
   property that made this adjudication possible at all. RC's rows are per-event and
   PERSISTED, so RC clears pin section 8 item 2 outright.
2. **Field-level agreement is high.** 148 of 160 comparisons agree, 5 disagree, 7 are pin
   gaps. Nothing here resembles a corpus that needs re-extracting.
3. **But the headline `prevention` number is not robust.** The published GATE-ABSENT lead is
   15 rows over 198; this sample moved 5.0 percent of prevention values firmly and left a
   further 10.0 percent undecided on a gap in the pin. **RC must not publish "GATE-ABSENT is
   the largest bucket" as a finding.** It should publish the histogram with the measured
   movement beside it and state that the top two buckets are within the adjudication noise.
4. **`discovery` should be published as a distribution, never as a ratio against another
   tree,** until section 3 separates channel from method. RC's 49 percent `SELF-AUDIT` is an
   artifact of a value that competes with two others on almost every row.
5. **`correct` should be published with its unanimity disclosed** as a limit of the extraction,
   not as a result.
6. **RC must declare pin section 8 item 1 against itself.** The four scorers produced the rows
   they graded. This pass is the correction for a 20 percent sample only; the other 158 rows
   are still producer-graded, and that sentence belongs in RC's publication.
7. **Two gaps go back to the fleet:** the `prevention` precedence gap between a defect-nature
   value and `GATE-FIRED-CAUGHT` (GAP 1), and the missing `origin_time` value for an
   OPERATOR-originated in-session claim (GAP 6). Per the pin's own section 0, these are
   reported rather than resolved silently.

Not recommended: a full re-grade of all 198 rows. The measured per-field disagreement does not
justify the cost, and three of the five disagreements are sub-value shifts the rows already
flagged themselves. What IS recommended before publication: resolve GAP 1 with LW, then
re-run only the `prevention` field over the rows whose refuter is a standing gate or verifier,
which is where all of the undecided movement sits.
