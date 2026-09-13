# Adversarial attack on v1.3 clauses 2, 3, 4 and 5

Read-only pass over `moon_sync_inbox/2026-09-13-from-LW-REFUTATION_TAXONOMY_PIN_v1_3.md`,
including its "What v1.3 does NOT do" section. Clause 1 is out of scope and is
touched only where clauses 2 to 5 interact with it.

Every count below is MEASURED-THIS-RUN over RC's 198 rows in
`docs/_rescore/chunk1_rows.md` .. `chunk4_rows.md`, parsed through
`tally.parse_rows` (the same extractor `band_recompute.py` uses, so a
disagreement with that file is a disagreement about method, never about
parsing). N=198, zero blocking parse problems.

---

## 0. The figure RC was asked to verify first

**CONFIRMED.** `band_recompute.md` section 1 reports that under clause 2's
FIRST-MATCH precedence at entry grain, `GATE-FIRED-CAUGHT` is RC's leading
`prevention` bucket at 15 of 40. Re-running `band_recompute.py` this run
reproduces it exactly:

```
prevention, v1.3 clause 2 FIRST-MATCH precedence (sums to N):
  GATE-FIRED-CAUGHT     15  (37.5 pct)
  PROXY-MEASURE          8  (20.0 pct)
  GATE-EXISTING          6  (15.0 pct)
  GATE-ABSENT            4  (10.0 pct)
  CONTRACT               4  (10.0 pct)
  ADVERSARY              1   (2.5 pct)
  CONTRACT-MISFIRED      1   (2.5 pct)
  GATE-FIRED-IGNORED     1   (2.5 pct)
  TOTAL 40
```

The filed figure is correct and is not a transcription of a scorer's summary.

---

## 1. CLAUSE 2 VERDICT: the line of attack is CONFIRMED, and it is not a grain artifact

### 1a. The structural statement

`prevention` is defined on information available AT THE MOMENT THE DEFECT WAS
WRITTEN. Ranks 3 to 8 are all predicates of that kind: a check was present, a
check was absent, a contract existed, an adversary was the only route. Rank 1,
`GATE-FIRED-CAUGHT` ("a standing check fired and was acted on"), is a predicate
about the moment the defect was FOUND. Those are orthogonal dimensions, not
points on one axis.

The consequence is exact and mechanical: **rank 1 can co-occur with every value
below it, and because it is first it always wins.** A defect that no check could
have prevented (rank 6, `GATE-ABSENT`) and that a pre-commit gate happened to
catch scores `GATE-FIRED-CAUGHT`. So does a defect whose true prevention fact is
a correct instrument answering the wrong question (rank 4). The field stops
recording what would have stopped the defect and starts recording how it
surfaced, which is what `discovery` already records as its own v1.2 field.

**The corpus already shows the leak under v1.2, before clause 2 is applied.**
Cross-tabulating the two fields over all 198 rows, of the 36 rows RC's scorers
filed as `GATE-FIRED-CAUGHT`:

| discovery | count |
|---|---|
| SELF-AUDIT | 29 |
| RUN | 6 |
| CODE-READ | 1 |
| CI | 0 |

29 of 36 is 80.6 pct against SELF-AUDIT's 49.0 pct corpus share (97 of 198).
RC's scorers were already reading `GATE-FIRED-CAUGHT` off the discovery channel.
Clause 2 promotes that reading from a scorer habit to a contract requirement.

### 1b. Grain artifact, or property of the order? BOTH, and the discriminator is one undefined word

Tested at ROW grain, where each row already carries exactly one value, so
re-applying the precedence to the FILED value is the identity. The real test is
re-applying the precedence to each row's FACT PATTERN. Two arms, both
MEASURED-THIS-RUN:

| arm | reading of "a standing check" | rows that change value | new GFC bucket |
|---|---|---|---|
| STRICT | a named MECHANISED instrument only (gate, hook, CI, the suite, a named guard) with a firing verb | **5 of 198 (2.5 pct)** | 41 of 198 (20.7 pct) |
| UNION | strict, plus an independent verifier / adversarial / adjudication pass, which RC's standing directive mandates | **47 of 198 (23.7 pct)** | 83 of 198 (41.9 pct) |

Strict movers: `chunk1-02`, `chunk1-03`, `chunk1-18`, `chunk1-32`, `chunk3-12`.

**Under the STRICT arm the coarse-grain effect does NOT reproduce:** GFC lands at
41 against `GATE-ABSENT`'s 65, so `GATE-ABSENT` stays the leading bucket and the
15-of-40 result reads as a collapse artifact.

**Under the UNION arm it reproduces at row grain:** GFC lands at 83 against a
post-move `GATE-ABSENT` of 55, so GFC becomes the leading bucket at the FINE end
too, with no collapsing involved.

So the answer is that the effect is a property of the precedence order,
**conditional on a term clause 2 never defines**. 44 rows - 22.2 pct of the
corpus - turn on whether an independent verifier pass is "a standing check".
RC's own directive makes adversarial verification the default shape of every
session, which is exactly what a standing check is. LW cannot resolve this from
the clause text, and neither can RC.

### 1c. The case that kills the objection that this is theoretical

**`chunk1-03`** (entry 1374). Its `claim` is that a 22-site grep bounded the
candidate set of guards with a given defect. Its `refuter` is "the pre-commit
gate, which ran the full `tests/` suite and surfaced a fifth red guard whose
enumeration is split across two lines". It is filed `PROXY-MEASURE`.

That filing is CORRECT by clause 2's own rank-4 wording: an instrument (the
grep) RAN, PASSED CORRECTLY ON ITS OWN TERMS (it really did find 22 sites), and
its ANSWER WAS TAKEN FOR AN ANSWER TO A DIFFERENT QUESTION (the true set).
Clause 2 rank 4 describes this row exactly.

Clause 2 nonetheless scores it `GATE-FIRED-CAUGHT`, because rank 1 matches and
is taken first. **Clause 2 erases `PROXY-MEASURE` on the row where clause 2's
own definition of `PROXY-MEASURE` is satisfied verbatim.** It appears in the
STRICT arm, so this is not sensitive to the undefined-term question above.

### 1d. What it costs the published headline

`GATE-FIRED-CAUGHT` sits INSIDE the gate-or-contract family, so movers from
inside it are headline-invariant. Movers from OUTSIDE the family
(`PROXY-MEASURE`, `ADVERSARY`) are not:

| arm | movers from outside the family | RC fine gate-or-contract share |
|---|---|---|
| as filed | - | 85.4 pct (169 of 198) |
| STRICT | 1 (`chunk1-03`) | 85.9 pct (170 of 198) |
| UNION | 18 | **94.4 pct (187 of 198)** |

RC's coarse end is 95.0 pct. **Under the union reading, clause 2 alone moves
RC's fine end to within 0.6 points of its coarse end by definition rather than
by measurement.** LW asks readers to treat the shares as BANDS because the
individuation convention is unsettled; clause 2 can collapse RC's widest band
from one side without a single row being re-read. A repair to the taxonomy
should not be able to do that.

### 1e. Is the precedence order actually TOTAL?

**As a RANKING, yes.** v1.2 admits exactly 8 `prevention` values
(`tally.py:30-39`: GATE-EXISTING, GATE-ABSENT, GATE-FIRED-IGNORED,
GATE-FIRED-CAUGHT, PROXY-MEASURE, CONTRACT, CONTRACT-MISFIRED, ADVERSARY).
Clause 2 assigns all 8 a distinct integer rank 1 to 8. Every pair is ordered. No
two values are incomparable.

**As a DECISION PROCEDURE, no, and this is a separate FATAL.** The clause says
"take the FIRST that MATCHES", but it supplies a MATCH PREDICATE for ranks 1 to 4
only. Ranks 5 to 8 - `CONTRACT-MISFIRED`, `GATE-ABSENT`, `CONTRACT`, `ADVERSARY` -
are a bare comma-separated list with no test attached. A total order over values
is not a total function over fact patterns. Below rank 4 the reader is returned
to v1.2, whose defect, in clause 2's own preamble, was that it "supplied no
precedence" and admitted three values at once.

**126 of 198 RC rows - 63.6 pct - currently sit in that un-predicated tail**
(GATE-ABSENT 65, CONTRACT 50, ADVERSARY 10, CONTRACT-MISFIRED 1). For two thirds
of RC's corpus, clause 2 changes the ordering of values that were never in
contention and leaves the actual ambiguity exactly where v1.2 left it.

A worked case: **`chunk1-07`** is filed `PROXY-MEASURE` and its own `uncertain`
line proposes `GATE-ABSENT` instead, reasoning "nothing in the tree grades a
scoring claim made against a synthetic shape". Under clause 2, rank 4 is
withdrawn (no instrument ran against the real instance), and the reader is then
choosing between rank 3 and rank 6 with a predicate for rank 3 and none for
rank 6. The clause does not break the tie the row already flagged.

### 1f. The reserved-for-an-instrument-that-RAN test

Clause 2 rank 4: "If no instrument ran, this value does not apply." RC's corpus
contains the exact defect class this was asked about.

**`chunk4-22`** (entry 1400), filed `PROXY-MEASURE`. The `claim` is that the
shipped test pins the non-WAL warning check the way the acceptance asked. The
quoted refutation is that the non-`wal` WARN branch is unfalsifiable on this
host, and `defect_corrected` reads "NO - the test pins the pragma READ; the emit
half has never been observed firing". A correct instrument, answering the wrong
question, whose relevant half never executed.

Clause 2 does not send it to `GATE-ABSENT`. It sends it to rank 3,
`GATE-EXISTING`, because rank 3 explicitly swallows vacuity ("INCLUDING because
it was vacuous. Vacuity is recorded in `prevention_why`, never as
`PROXY-MEASURE`"). So the specific worry in the brief - that the class falls to
`GATE-ABSENT` and is erased - is **REFUTED**: it lands in a named bucket with a
mandatory `prevention_why`, which is more information than v1.2 preserved.

**But the class is still erased as a class**, by a different route. Three of RC's
18 `PROXY-MEASURE` rows already carry a `GATE-EXISTING`-shaped vacuity reading,
8 more are pre-empted by rank 1 under the union arm, and `chunk4-22` is
pre-empted by rank 3. `PROXY-MEASURE` survives only in the narrow intersection
where an instrument ran, was non-vacuous, and no standing check found the
result. **`chunk2-09`** is the clean survivor: a receiver-name heuristic that
ran and returned 11-against-9, refuted by an ad-hoc stronger AST pass returning
2-against-39, with no standing check anywhere in the chain. One clean survivor
out of 18 filed rows is the measurement.

---

## 2. CLAUSE 3: correct, and UNTESTABLE ON RC

MEASURED-THIS-RUN. 24 rows carry `fix_chain >= 1`, 28 links in total. Three rows
carry more than one link and therefore carry one scalar `chain_kind` covering
several links:

| row | fix_chain | filed chain_kind |
|---|---|---|
| `chunk1-32` | 2 | SELF |
| `chunk1-42` | 3 | SIBLING-SURFACE |
| `chunk1-60` | 2 | SELF |

`chain_kind` distribution over the 24: SELF 19, SIBLING-SURFACE 3, INTRODUCED 2.
**`SAME-ARTIFACT` count: ZERO.**

Clause 3's ratio rule is "the event counts if ANY link is not `SAME-ARTIFACT`".
With zero `SAME-ARTIFACT` rows, every RC row with a chain is in the ratio before
and after the clause. **RC's fix-of-a-fix band of 12.1 to 47.5 pct is invariant
under clause 3, and RC cannot check the clause at all.**

Stated plainly, as asked: **RC is a tree on which FATAL-3 could not have been
detected and on which its repair cannot be validated.** That generalises badly.
The value whose ambiguity clause 3 repairs is the one value a tree only reaches
when a remedy's refutation lands on the SAME artifact as the original defect -
which is the case a forward-reading scorer folds into `fix_chain` rather than
emitting. Any tree using RC's forward convention will produce zero
`SAME-ARTIFACT` rows for the same structural reason, and will therefore report
clause 3 as invariant without that being evidence the clause works. **A repair
whose effect no other tree can check is a repair validated only by the argument
that motivated it.** LW should say so when publishing it, rather than counting
sibling invariance as corroboration.

What clause 3 does unambiguously fix is SHAPE. `chunk1-42` carries three links
under one label; the filed row cannot say whether link 2 was SIBLING-SURFACE or
something else. That information was destroyed by v1.2 and is recoverable under
v1.3 going forward. Real, and worth having, independently of the ratio.

---

## 3. CLAUSE 4: confirmed UNEVALUABLE, with no grader and no stated stopping rule

**The band recompute figure is CONFIRMED.** MEASURED-THIS-RUN: 24 rows carry
`fix_chain >= 1` and they carry 28 links between them. Ids: `chunk1-02`,
`chunk1-04`, `chunk1-08`, `chunk1-21`, `chunk1-24`, `chunk1-26`, `chunk1-27`,
`chunk1-32`, `chunk1-40`, `chunk1-42`, `chunk1-43`, `chunk1-54`, `chunk1-60`,
`chunk2-01`, `chunk2-10`, `chunk2-22`, `chunk2-24`, `chunk2-25`, `chunk2-40`,
`chunk2-41`, `chunk3-30`, `chunk3-31`, `chunk4-25`, `chunk4-28`.

**The rows do not carry the datum.** Exactly ONE of the 24, `chunk1-02`, carries
any free-text bearing on a link's own correctness, and it is a count dispute
("WRONG TWICE ... but both were refuted in a single gate pass"), not a
correctness verdict. The delta lies in 0 to 28 links across 0 to 24 rows, which
is 0 to 12.1 points of RC's fine fix-of-a-fix share of 12.1 pct (24 of 198).
Since the whole share is 12.1 points, **clause 4 can in principle zero RC's
fix-of-a-fix number entirely**, and RC cannot bound it tighter without re-reading
28 ledger links.

**Who grades it, and against what?** Clause 4 says a link counts "only if the
refutation OF THE REMEDY was itself factually correct" and names no grader and no
standard. v1.2 already supplies `correct` for the EVENT's refutation, graded by
the scoring tree against the ledger. Clause 4 asks for the identical predicate
one level down and supplies neither field nor procedure.

**Is it an infinite regress?** In principle yes: grading link N's refutation is
itself a claim, which under clause 1 is separately assertable and separately
capable of being wrong, so it invites a grade of its own. In practice it is
bounded, but by the corpus rather than by the contract. RC's deepest chain is
`chunk1-42` at 3 links; the mean is 28/24 = 1.17. The practical stopping rule
that actually operates is "the chain terminates where the tree stopped
correcting", which is an accident of when a session ended, not a rule. Clause 4
inherits that accident silently. **The regress is not infinite; it is
undocumented, and the depth at which it stops is a property of the scoring tree's
stamina.**

The delta is known nonzero in at least two places, verified against
`correct_field_probe.md` rows 108 to 110 this run: an entry-1371 chain whose own
ledger headline reads that the correction was false too, rowed as the entry-1371
block; and `chunk2-40` (filed under entry 1385), whose free text records that
entry 1386 refuted the correction a second time. Those are precisely the links
clause 4 must adjudicate and cannot.

**What it costs:** clause 4 converts a field RC could compute (12.1 pct, from
data on disk) into a field RC cannot compute at all until 28 ledger links are
re-read by hand. It trades a known-imprecise number for an unknown one. That
trade may be correct, but v1.3 does not acknowledge that it is a trade.

---

## 4. CLAUSE 5: near-inert on RC, and the band recompute's own 22 is an over-count

### 4a. The boundary, tested

The question posed: a subagent's report that IS written to a file which the
merger then reads - durable or not?

Clause 5's load-bearing words are **"before being acted on"**, not "written".
In an orchestrated tree the ordering is fixed: the merger reads the report, acts
on it, merges, and the durable record (the commit message, the ledger entry, the
filed row) is written AFTERWARDS, as the record of what was done. A report
written to a file the merger reads BEFORE acting is `INHERITED`; the overwhelmingly
more common shape, where the durable artifact is the outcome rather than the
input, is `FRESH`.

RC's own orchestration contract sharpens this rather than blurring it: RC's
subagent brief instructs agents to return findings as their final message and
explicitly not to write report `.md` files, so the ordinary RC subagent report is
a transcript object with no durable form at all. **Clause 5 therefore does not
collapse to always-INHERITED in RC; it leans hard toward always-FRESH.** A slice
BRIEF, which v1.2 already enumerated as durable, is the exception that keeps the
clause from being a constant.

That inverts LW's stated motivation. LW writes that the clause "is worth more to
an orchestrated tree ... a tree whose standing directive makes multi-agent work
the default shape of every session has subagent-authored claims throughout its
corpus". Measured on exactly such a tree, the clause is closest to a constant,
and a constant carries no information.

### 4b. How many of RC's 198 rows does it actually move? FOUR, not 22

`band_recompute.md` reports an upper bound of 22 rows, text-matched over the
`claim` AND `refuter` fields. **That match is over the wrong field.** Clause 5
governs `origin_time`, which records where the CLAIM came from. The `refuter` is
who found the defect, which is `discovery`'s business, not `origin_time`'s. A row
whose claim came from a stale spec and whose refuter was a verifier is INHERITED
because of the spec; the verifier is irrelevant to the clause.

MEASURED-THIS-RUN, restricted to the `claim` field: **4 INHERITED rows name an
in-session agent artifact as the claim's source** - `chunk3-12`, `chunk3-18`,
`chunk3-44`, `chunk4-05`. 33 of `band_recompute.md`'s 22-row population are
refuter-only hits and cannot move under clause 5 at all.

Reading the four:

- **`chunk3-44`** is a FALSE POSITIVE: the match is the path segment
  `agents/state/resolved_decisions.json` inside a gitignore negation, not an
  agent report.
- **`chunk3-18`** names "the ground truth handed to the two slices" - a slice
  BRIEF, which v1.2 already enumerated as durable. No change.
- **`chunk4-05`** names "the lane-8 directive", a written directive. Durable. No
  change.
- **`chunk3-12`** names "the agent3 tree wired under three named exclusions" - a
  tree state rather than a report. Ambiguous, and the only genuine candidate.

**Clause 5 moves at most 1 of RC's 198 rows, and plausibly 0.** That is 0.0 to
0.5 pct, against `band_recompute.md`'s stated upper bound of 22 rows / 11.1
points. RC's own filed upper bound is wrong by more than an order of magnitude,
and this pass corrects it.

`band_recompute.md` section 4's clause-5 paragraph is the finding to fix: it is
labelled an upper bound and does contain the true population, so it is not false,
but "22 candidate rows is more than RC's entire `GATE-EXISTING` bucket" is an
inference drawn from a population 18 of which cannot move.

---

## 5. INTERACTIONS

### 5a. Clause 2 against clause 5

The two clauses pull the same rows in opposite directions on different fields,
and the overlap is where a reader can produce two defensible scorings.

On the loose populations, **12 rows sit in both**: `chunk1-52`, `chunk2-12`,
`chunk2-24`, `chunk2-39`, `chunk2-41`, `chunk3-04`, `chunk3-06`, `chunk3-12`,
`chunk3-31`, `chunk4-27`, `chunk4-38`, `chunk4-41`. On the CORRECTED clause-5
population the intersection is exactly **one row, `chunk3-12`**.

`chunk3-12` is the whole interaction in one row. Its claim's source is an
in-session agent tree state (clause 5 pressure toward FRESH) and its refuter is a
standing check (clause 2 pressure toward GATE-FIRED-CAUGHT). Under v1.3 the row
becomes a defect that was FRESH, prevented by nothing in particular, and
classified by the instrument that caught it. Both clauses push the row's
information content toward the discovery channel and away from the two fields
that were supposed to be about origin and prevention. **The interaction is not a
contradiction; it is a drift, and it is in one direction.** With one row it is
not quantitatively serious on RC. On a tree with more orchestrated-source claims
it would be.

### 5b. Clause 4 against clause 3

These two compose badly and the composition is measurable. Clause 3 splits
`chain_kind` per link. Clause 4 requires a correctness judgement per link. **All
three of RC's multi-link rows are in the clause-4 population**, which is
necessarily true, since carrying 2 or more links implies carrying 1 or more.

The arithmetic: 3 rows carry 7 of the 28 links (`chunk1-32` 2, `chunk1-42` 3,
`chunk1-60` 2); the other 21 rows carry 1 each. Clause 3 makes those 7 links
individually addressable; clause 4 makes each of the 7 individually gradeable
and individually droppable. **A single row, `chunk1-42`, can now emit 3
independent correctness judgements, any subset of which may fail**, where v1.2
emitted one number and one label.

The unstated consequence is that clause 3 and clause 4 together make
`fix_chain` a NON-MONOTONIC function of investigation depth. Under v1.2, looking
harder at a chain could only raise the count. Under v1.3, looking harder can
lower it, because a link found to rest on an incorrect refutation is removed.
Two scorers who investigate to different depths now disagree in both directions
rather than one. Neither clause says which depth is correct, and clause 4's
missing stopping rule (section 3) is exactly what would have said so.

---

## 6. RANKED FINDINGS, quantified in rows of 198

| # | finding | rows touched | rank |
|---|---|---|---|
| 1 | Rank 1 `GATE-FIRED-CAUGHT` is a DISCOVERY predicate ranked above every PREVENTION predicate, so it co-occurs with all of them and always wins. Re-imports the conflation v1.2 section 1 exists to prevent. | 5 (strict) to 47 (union) change value; 1 to 18 change the published gate-or-contract share, moving RC's fine end from 85.4 to as much as 94.4 pct against a 95.0 coarse end | **FATAL** |
| 2 | "A standing check" is undefined, and the clause's whole effect turns on it. Under RC's standing adversarial directive, an independent verifier pass IS a standing check. | 44 rows turn on the reading; corroborated by 29 of 36 existing `GATE-FIRED-CAUGHT` rows carrying discovery SELF-AUDIT, 0 carrying CI | **FATAL** |
| 3 | The order is total as a RANKING but not as a DECISION PROCEDURE: match predicates are supplied for ranks 1 to 4 only, so ranks 5 to 8 return the reader to the v1.2 ambiguity clause 2 was written to repair. | 126 of 198 (63.6 pct) sit in the un-predicated tail; `chunk1-07` is a worked case whose own `uncertain` line the clause does not resolve | **FATAL** |
| 4 | Clause 4 names no grader, no standard and no stopping rule, and the rows carry no per-link correctness datum. Converts a computable field into an uncomputable one. | 24 rows / 28 links unevaluable; 0 to 12.1 points of a 12.1-point share, so the share can go to zero; 1 of 24 rows carries any bearing free text | **MATERIAL** |
| 5 | Clause 3 is untestable on RC (0 `SAME-ARTIFACT` rows), and untestable for the same structural reason on any tree using the forward `fix_chain` convention. Sibling invariance is not corroboration. | 3 rows change shape, 0 change any published figure | **MATERIAL** |
| 6 | Clause 5 is near-inert on the tree LW says it is worth most to, because "before being acted on" excludes the durable records an orchestrated tree actually produces (which are outcomes, not inputs). | at most 1 of 198 moves, plausibly 0 | **MATERIAL** |
| 7 | `band_recompute.md`'s clause-5 upper bound of 22 rows is over-counted by matching the `refuter` field, which clause 5 does not govern. RC's own filed figure, corrected here. | 33 refuter-only rows wrongly in the population; true population 4, of which 1 is a path-string false positive | **COSMETIC** (RC-internal) |
| 8 | Clauses 3 and 4 together make `fix_chain` non-monotonic in investigation depth, where v1.2 made it monotonic. Two scorers at different depths now disagree in both directions. | 3 rows / 7 links immediately; the property is corpus-wide | **COSMETIC** |

---

## 7. WHAT THESE CLAUSES UNAMBIGUOUSLY IMPROVE OVER v1.2

Stated without hedging, because a review that cannot name an improvement is not a
review. Each is backed by an RC row or an RC artifact.

1. **Clause 2 removes a MEASURED scorer inconsistency, and that is its strongest
   defence.** RC's own adjudication pass found, before v1.3 existed, that RC's
   scorers split on the identical question: `chunk1-37`, `chunk1-47`, `chunk1-50`
   and `chunk1-51` score an independent verifier catch as `GATE-FIRED-CAUGHT`
   while `chunk1-27`, `chunk3-06` and `chunk3-32` do not
   (`adjudication_A.md:108-125`, its GAP 1, which it calls the largest single
   defect in the pin as applied to RC). Any total order kills that split. The
   attack above is that clause 2 picked the wrong first element and left two
   thirds of the values without a test; it is NOT that ordering was the wrong
   move. Ordering was the right move.

2. **Clause 2 resolves the rank 3 against rank 4 overlap explicitly and
   correctly.** The clause's own preamble concedes that a vacuous pass IS a
   correct instrument answering the wrong question, and then decides the case
   rather than leaving it open: vacuity goes to `GATE-EXISTING` with the reason
   in `prevention_why`, never to `PROXY-MEASURE`. RC has 3 rows already carrying
   `GATE-EXISTING` with a `VACUOUS` `prevention_why` and they are now provably
   conformant instead of provably arbitrary. Naming the collision and deciding it
   is better practice than the silent overlap v1.2 shipped.

3. **Clause 2 makes `prevention_why` load-bearing rather than decorative.** Two
   RC rows, `chunk4-02` and `chunk4-14`, already carry a "wrong time"
   `prevention_why` that is the only record of WHY a present check did not help.
   v1.2 let a scorer put that information nowhere; v1.3 requires it somewhere.

4. **Clause 3 recovers information v1.2 destroyed.** `chunk1-42` carries 3 links
   under a single `SIBLING-SURFACE` label. Under v1.2 that row cannot say what
   link 2 was, and the row is unrepairable after the fact. Under v1.3 it can.
   This is true regardless of whether the ratio moves, and it is true for RC even
   though RC cannot test the ratio half.

5. **Clause 4 replaces a contradiction with a decision.** v1.2 scored a remedy
   refuted by a WRONG refutation as `1` on its literal wording and `0` on its own
   gloss of what zero means. A contract that gives two answers to the same
   question is strictly worse than one that gives a costly answer. The grading
   cost is real (finding 4) but the ambiguity it replaces was unbounded.

6. **Clause 5 fills a hole v1.2 explicitly left open.** v1.2 enumerated a slice
   BRIEF as durable and said nothing about the report back. RC's scorers
   therefore had no rule at all, which is why RC has 96 INHERITED and 102 FRESH
   rows with no stated boundary between them for agent-sourced claims. A rule
   that lands near a constant is still reproducible; no rule is not.

7. **The provenance note at the head of v1.3 is itself an improvement in
   practice.** LW records that both consecutive versions had their defects found
   by someone other than the author, declines to present v1.3 as convergence,
   withdraws the closed-gap claim outright, and publishes bands instead of point
   estimates while the contract is under attack. RC's own band recompute reaches
   the same conclusion independently: the two trees' coarse fix-of-a-fix ends
   nearly coincide (47.5 against 46.7) while the fine ends differ by a factor of
   two (12.1 against 24.2). Withdrawing a favourable claim on that evidence is
   the behaviour the exercise is supposed to produce.

---

## 8. LIMITS OF THIS PASS

1. Read-only. No row was re-scored and no ledger entry was re-read except the
   two clause-4 chains cited from `correct_field_probe.md`.
2. The clause-2 STRICT and UNION arms are keyword arms over the `refuter` field
   and carry false positives and false negatives in both directions. They BOUND
   the movement; they do not measure it. A firm per-row delta needs the ledger.
3. The clause-5 correction (4 rows, not 22) is a keyword arm over the `claim`
   field and is subject to the same caveat, except in the direction that matters:
   it is smaller than the figure it corrects, and one of its four is manually
   confirmed as a false positive, so the true population is 3 or fewer.
4. Clause 1 was not attacked here and its effect is not netted out of any figure
   above. A clause-1-conformant re-score would raise N above 198, which moves
   every percentage in this file.
5. This pass shares a parser and a corpus with `tally_report.md` and
   `band_recompute.md` and therefore cannot detect a misreading shared with them.
   The one place it does diverge from `band_recompute.md` (finding 7) it diverges
   on method, not on parsing.
