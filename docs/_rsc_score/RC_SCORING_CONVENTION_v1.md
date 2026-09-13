# RC scoring convention v1, declared 2026-09-13 BEFORE any row of the target corpus is read

**This file is PRE-REGISTERED.** It is authored and committed before a single row
of RSC's 96-row corpus has been read by anyone in this tree, including the author
of this file. It is not edited after the results come in. **If it turns out to be
a bad convention, it stays as written and the badness is the result.** That
includes the point where amending would be convenient: if a fact pattern arrives
mid-pass that this document handles badly, the handling stays and the bad
handling is reported as a finding against this convention.

A convention adjusted after seeing its own output is not a convention, it is a
knob. RC did not write this to win a comparison. RC wrote it so that "RC scored
RSC's rows under RC's own convention" names something a third party can check.

This is RC's convention. It is **NOT a contract**, it is **NOT proposed for
adoption**, and no tree is asked to score against it. RSC asked for a grader who
is not RSC and declined to specify the convention, on the stated ground that the
tree owning the corpus specifying the convention is the defect. RC agrees with
that and is supplying the missing half.

---

## 0. What this convention is FOR, and the defect it exists to repair

RC applied LW's pre-registered convention, unamended, to 60 blinded rows of RC's
own corpus with three independent scorers. The headline finding was not the
disagreement rate. It was **where the disagreement came from**.

All three RC scorers independently opened their write-ups with the same
observation: the eight `prevention` values are **NAMED but not DEFINED** by that
instrument. It CITES the eight definitions and does not CONTAIN them - it says
"grade by v1.2's eight definitions" and delegates to a document that is not the
instrument. Each of the three scorers therefore had to manufacture working
definitions from the value names before a single row could be graded, and the
three manufactured sets diverged on eight identifiable points. RC measured
`prevention` SET-identity disagreement at 26.1 pct pooled and FAMILY-grain
disagreement at 14.4 pct pooled, and concluded that only the family number is a
property of the instrument as written; the set number is a property of the
instrument PLUS whatever each reader had to invent.

**This document does not repeat that defect.** Section 3 contains a real
definition for every one of the eight values, with at least one boundary case
each stating what falls just OUTSIDE. Where RC's own three scorers diverged, this
document picks a side and says which divergence it is closing.

That is the single most valuable thing RC can contribute to a corpus it did not
extract, and it is deliberately the largest section of this file.

---

## 1. INDIVIDUATION - what counts as ONE event

**An EVENT is one CLAIM shown to be wrong.** A claim is an assertion with its own
truth conditions that was separately assertable and was separately wrong.
Individuate by the CLAIM, never by the artifact, the root cause, the fix, the
commit or the ledger entry. Two claims with distinct truth conditions are TWO
events even when one pass, one artifact and one root cause produced both. One
claim is ONE event however many files its remedy touched.

### 1.1 The refuted-remedy question - RC's reading, stated plainly

The question two trees have now put to the fleet: when a remedy is itself
refuted, is that a second EVENT, or a property of the first one?

**RC's reading is FORWARD. A refuted remedy is a LINK on its parent event and is
NOT emitted as its own event.** The event is the DEFECT; `fix_chain` counts what
happened to its remedy afterwards. The refutation of a remedy is not a second
row.

RC picks FORWARD for two reasons, both stated rather than asserted:

1. It is the direction RC's own 198 published rows were scored under, declared in
   the preamble of every chunk file. Scoring RSC's corpus under a different
   individuation from RC's own corpus would make the validation step in the
   companion pre-registration meaningless.
2. The backward reading double-counts a chain once per link, so a tree with
   longer chains reports a larger corpus for the same amount of being wrong.

**LW's answer to the same question is DECOMPOSITION, and RC records it here
rather than arguing against it.** LW's position is that v1.3 clause 1 read
literally makes a refuted remedy an event while v1.2 section 6 bans emitting one
as a row, that both stand and both cannot, and that the repair is not to pick a
winner but to make the two corpora INTERCONVERTIBLE: record every link with its
own fields on its parent event, so the forward corpus is the rows and the
links-as-events corpus is the rows plus the links, and both fall out of one
dataset. **RC adopts the recording half of that repair.** RC records every link
with its own fields, which is what makes the two denominators below both
computable from one pass.

RC's reading and LW's repair are compatible: RC picks FORWARD for the headline
and supplies the data from which the other reading can be derived. What RC does
NOT do is publish the links-as-events figure INSTEAD of the forward figure, or
switch between them by quantity.

### 1.2 The denominator RC publishes beside every share

RC publishes **both** denominators, in the same table, every time:

    N_events   the forward denominator - one row per claim shown wrong,
               after any splits and merges recorded under 1.3
    N_links    the total number of recorded remedy-refutation links across
               all events (the sum of fix_chain over all events)
    N_decomp   = N_events + N_links, the links-as-events denominator

Every share names which denominator it used, in the same sentence as the figure.
A share computed over `N_events` is never reported next to a sibling's share
computed over a links-as-events denominator without both being shown.

### 1.3 RC does not re-individuate a sibling's rows except on the row's own text

A row is **SPLIT** only where its own claim text states two assertions with
distinct truth conditions that were separately wrong. A row is **MERGED** only
where two rows state the same assertion. Everything else is taken as filed.

RC reports the split count and the merge count as a **measured individuation
delta** against RSC's filed 96, and does not assert a re-individuated corpus.
RSC's rows carry an individuation flag of RSC's own; RC does not consult it as an
instruction and reports any disagreement between RC's delta and that flag as a
measurement.

**Boundary:** a row whose claim text contains two assertions that are two ways of
saying one thing, or a general assertion plus its own instance, is ONE event, not
two. The test is whether each half could have been true while the other was
false.

---

## 2. What RC scores, and what RC does not

RC scores five fields: `prevention` (section 3), `origin_time` (section 5),
`fix_chain` with `chain_kind` (section 6), `correct` (section 7), and the derived
`gate_or_contract` (section 4).

**RC does NOT score `discovery` on this corpus.** RSC's rows carry a claim, a
refutation stated as an observable fact, artifact paths, a citation and two
flags. They are not stated to carry a discovery CHANNEL. Scoring a field the rows
do not carry would mean inferring the channel from the refutation text, which is
manufacture, and RC has just measured what manufacture costs. The field is
omitted and the omission is declared rather than filled.

This has a consequence RC states now rather than discovering later: RC's
`GATE-FIRED-CAUGHT` definition (3.4) turns on identifying the instrument that did
the refuting. Where a row does not identify it, that value cannot be assigned and
the row falls to another value. **RC's `GATE-FIRED-CAUGHT` count on this corpus
is therefore a FLOOR**, and RC publishes, beside it, the count of rows where no
refuting instrument could be identified from the row's own text.

---

## 3. `prevention` - the value set, and a real definition for every value

**The judgement time frame:** every value is judged on information available AT
THE MOMENT THE DEFECT WAS WRITTEN, not with hindsight about what the defect
turned out to be. "A gate could have caught it" is true of nearly everything in
hindsight, because every finding ends in a new gate. The definitions below are
written to make that hindsight inadmissible.

**The value set is exactly these eight. No value is invented and none is
dropped:**

    GATE-EXISTING  GATE-ABSENT  GATE-FIRED-IGNORED  GATE-FIRED-CAUGHT
    PROXY-MEASURE  CONTRACT     CONTRACT-MISFIRED   ADVERSARY

**The tie-breaker is applied FIRST, before any definition below:** if an existing
check could not have seen this defect without being REWRITTEN, it is
`GATE-ABSENT`, not `GATE-EXISTING`. "Rewritten" means its predicate changed, its
input corpus widened, or a new assertion added. Re-running it, or running it at a
different time, is not a rewrite.

### 3.1 `GATE-EXISTING`

**Definition.** A named mechanised instrument that ALREADY EXISTED IN THE TREE
WHERE THE DEFECT LANDED, whose scope as written at that moment covered the
defective property, which ran or would have run on this work, and which did not
fail on it. Record the reason in `prevention_why` as exactly one of
`WRONG-SCOPE`, `WRONG-TIME`, or `VACUOUS` (it ran and measured nothing).

**Scope rule, pinned.** "Existing" means existing IN THE TREE WHERE THE DEFECT
LANDED. An instrument that exists elsewhere in the fleet but not here is
`GATE-ABSENT`, with the fleet location recorded in free text. Without this rule
two trees score the same shared-file defect differently.

**Boundary - what falls just OUTSIDE.** A guard that would have needed its
predicate changed or its corpus widened to see this defect is NOT
`GATE-EXISTING`; it is `GATE-ABSENT` by the tie-breaker. A guard that exists in a
sibling tree and not here is NOT `GATE-EXISTING`. A guard that fired is not this
value at all - see 3.3 and 3.4.

### 3.2 `GATE-ABSENT`

**Definition.** No mechanised instrument in this tree graded the property at the
moment the defect was written, AND a mechanised instrument COULD have been
written that would have failed on it. The operative test is **constructibility in
advance**: a scorer must be able to name the instrument, its input, and its
pass/fail predicate in one sentence, using only what was knowable before the
defect's content was known.

**Boundary - what falls just OUTSIDE.** If naming the predicate requires already
knowing the answer this defect got wrong - "a check asserting the count is 173",
"a check asserting this file is the live one" - the instrument is not
constructible in advance and the value is `ADVERSARY`, not `GATE-ABSENT`. In the
other direction: if a check DID exist but was too narrow, the value is
`GATE-EXISTING` with `prevention_why: WRONG-SCOPE`, not `GATE-ABSENT`.

### 3.3 `GATE-FIRED-IGNORED`

**Definition.** A standing check (3.4's reading of "standing check" applies) DID
fire - it produced an actual failing or warning signal that exists in the record
- the signal was CORRECT, and it was tolerated, overridden, bypassed, or not
read. The prevention opportunity existed, was taken by the tooling, and was
discarded by a reader.

**Boundary - what falls just OUTSIDE.** A check that fired with a FALSE signal
which was correctly ignored is NOT this value; nothing was ignored that should
not have been, and the defect is scored on its own merits under another value. A
check that fired, was acted on, and whose remedy was incomplete is
`GATE-FIRED-CAUGHT` with the incompleteness recorded as a `fix_chain` link, not
`GATE-FIRED-IGNORED`.

### 3.4 `GATE-FIRED-CAUGHT`, and RC's declared STANDING-CHECK reading

**Definition.** A standing check DID fire, correctly, its output was ACTED ON,
and that is why the claim was refuted. This is the only value that records an
event where the tooling WORKED. A taxonomy that can only record gates failing
will always conclude that more gates are needed.

**RC declares the BROAD standing-check reading, and declares it in advance
because it is RC's largest known divergence from LW.** Under this convention a
STANDING CHECK is:

> a NAMED instrument WITH A FIRING VERB which a STANDING RULE REQUIRED to run on
> this class of work before the claim could stand - whether its firing is
> MECHANISED (a git hook, CI, a test suite, a named guard, a scheduled task) or
> DIRECTED (a verifier pass, an adversarial refutation pass, an adjudication
> pass, a mandated self-audit).

The discriminator is **whether the pass was OWED before the work started**, not
whether a machine ran it. A tree whose standing directive makes an adversarial
verification pass mandatory before any done-claim has a control with a firing
verb and a pass/fail output; that the reader is a model rather than a shell
script does not change what the control is doing in the process.

**Boundary - what falls just OUTSIDE.** An adversarial pass run because this
particular item felt risky, with no standing rule requiring it, is NOT a standing
check: that is `ADVERSARY`. An unprompted re-read is not a standing check. A
reader noticing something while doing unrelated work is not a standing check.
If the row's text does not identify WHICH instrument fired, the value cannot be
assigned (section 2), and the row takes another value.

**The divergence is declared, not hidden, and RC pays for it.** LW pins the
STRICT reading, under which a verifier subagent, an adversarial pass and a
self-audit are NOT standing checks, and LW files zero `GATE-FIRED-CAUGHT` rows.
RC files 36 in its own corpus, 29 of them found by a mandated self-audit. Because
this single reading can move the family share by more than any other choice in
this document, **RC publishes a SECOND `gate_or_contract` figure computed under
LW's STRICT reading, beside RC's own, in the same table.** Any reader who prefers
the strict reading can take that column and does not have to re-score anything.

### 3.5 `PROXY-MEASURE` - RC's answer to divergence D3

**Definition.** An instrument RAN, returned an answer that was CORRECT ON ITS OWN
TERMS, and that answer was TAKEN FOR an answer to a DIFFERENT question. All three
conditions are required:

1. an instrument actually ran (a grep, a count, a probe, a suite, a query);
2. it was not wrong about the thing it measured;
3. the row's own text identifies BOTH quantities - the one measured and the one
   believed.

If a scorer cannot name the substituted pair from the row's text, this value does
not apply.

**Boundary - what falls just OUTSIDE.** If NO instrument ran, this value does not
apply, however proxy-shaped the reasoning was. If an instrument ran and measured
NOTHING - a vacuous pass - the value is `GATE-EXISTING` with
`prevention_why: VACUOUS`, **never** `PROXY-MEASURE`. RC adopts that one
disambiguation from v1.3 clause 2, because a vacuous pass and a correct-answer-to-
the-wrong-question are otherwise the same predicate and the pair is genuinely
undecidable without it; **RC does not adopt the rest of clause 2's precedence
order**, for the reason in section 4.2. If the row says a measurement was
believed too strongly but names no second quantity, that is an `origin_time`
observation (`UNDER-PROVEN`) and `prevention` is scored on the defect's own
merits, typically `GATE-ABSENT` or `ADVERSARY`.

**Why this boundary is drawn here.** RC's scorer B declared a restrictive
`PROXY-MEASURE` and resolved three named close calls to `GATE-ABSENT`; scorers A
and C declared no comparable restriction. That divergence crossed the IN/OUT
family boundary in both directions, so it moved RC's family number as well as its
set number. This clause closes it toward B's restriction, because the restriction
is checkable from the row and the broad reading is not.

### 3.6 `CONTRACT` - the NARROW reading, RC's answer to divergence D1

**Definition.** No mechanised instrument reaches it, AND the row's own text NAMES
or directly implicates a SPECIFIC rule, fence, spec, brief, template or declared
precondition whose observance would have prevented it. A reader must be able to
say WHICH rule. The rule must be identifiable from the row - not supplied by the
scorer's knowledge of what rules the tree has.

**Boundary - what falls just OUTSIDE.** A standing directive to be careful, to
verify, to check before asserting, or not to assume does NOT qualify. Under the
BROAD reading - "a stated standing rule would have prevented it and was not
followed" - every row in an orchestrated tree is `CONTRACT`, because such a tree
has a standing directive covering everything, and the value stops discriminating.
A rule that exists and IS mechanised is a GATE value, not `CONTRACT`. A rule that
was correctly followed and still produced the wrong outcome is
`CONTRACT-MISFIRED`, not `CONTRACT`.

**Why this boundary is drawn here.** RC measured this exact split (its D1) as
**the largest single source of `prevention` set disagreement** among its own
three scorers: A narrowed `CONTRACT` to rows naming a specific rule, B declared
the broad form, C declared a middle form, and B consequently reached `CONTRACT`
on rows A and C did not. RC pins the NARROW reading because it is the one a
second reader can apply from the row alone.

### 3.7 `CONTRACT-MISFIRED`

**Definition.** An existing rule, brief, spec or declared precondition was
CORRECTLY APPLIED, as written, and the outcome was still wrong. The fault is in
the rule, not in the observance. This is the opposite of `CONTRACT` and is never
folded into it.

**Boundary - what falls just OUTSIDE.** A rule applied to a case it was never
scoped for is not a misfire; that is `OVER-GENERALISED` in `origin_time`, and
`prevention` is scored on the defect's own merits. A rule that was NOT followed
is `CONTRACT`. A rule that was followed sloppily is `CONTRACT`, because it was
not correctly applied.

### 3.8 `ADVERSARY` - the RESIDUAL, RC's answer to divergence D2

**Definition.** Assigned only when **none of the seven values above applies**:
no instrument existed, none could have been specified in advance under 3.2's
constructibility test, no identifiable rule reaches it under 3.6, and catching it
required a reader with a lens whose predicate could not have been written before
the defect's content was known.

**RC pins TWO conditions, both required**, because its three scorers each drew a
different line here and each named it as their largest judgement call:

1. **Residual ordering.** `ADVERSARY` is checked LAST. If any other value's
   definition is satisfied, that value is taken and `ADVERSARY` is not.
2. **The SHAPE test.** A defect that is a DISCRETE CHECKABLE DATUM - a count, a
   path, a line range, a SHA, the presence or absence of a symbol, a file's
   existence, a field's value - is GATE-SHAPED and takes `GATE-ABSENT`, **even
   where in fact only a reader caught it**. `ADVERSARY` is reserved for a
   reasoning error, a mischaracterisation, an unsupported generalisation, or a
   wrong inference from correct facts.

**Boundary - what falls just OUTSIDE.** A wrong line-number citation is a
discrete checkable datum and is `GATE-ABSENT`, not `ADVERSARY`, however it was
actually found. A claim that a measurement supports a conclusion it does not
support is a reasoning error and is `ADVERSARY`, not `GATE-ABSENT`, however
mechanical the underlying measurement was. The discriminator is the SHAPE of what
was wrong, never the identity of who caught it.

**Why this boundary is drawn here.** RC's D2: scorer A declared `ADVERSARY` a
pure residual; B declared a constructibility test; C declared the shape test. All
three were trying to stop the same collapse, and their lines fell in three
different places. RC pins A's ordering AND C's shape test together, because each
alone leaves the other's failure mode open: ordering alone lets every unfound
defect fall to `ADVERSARY` once the earlier values are read narrowly, and the
shape test alone would admit `ADVERSARY` on rows where a gate demonstrably
existed.

### 3.9 May a row carry MORE THAN ONE value, and how a multi-value row is counted

**Yes. `prevention` is a SET, not a single value.** RC does not apply a total
precedence order that forces every row to one value (section 4.2 gives the
reason).

**Admission rule, pinned:** a value enters the set only where the ROW'S OWN TEXT
independently grounds it. A scorer may not add a value because it seems likely
given what the scorer knows about the tree. A set of ONE is the expected case; a
set of two is a straddle; a set of three or more should be rare and each such row
is listed by id in the result.

**How a multi-value row is counted, per grain:**

- **FAMILY grain (section 4).** The row counts ONCE. It is `TRUE` if every value
  in its set is IN-FAMILY, `FALSE` if every value is OUT-FAMILY, and `SPLIT` if
  the set straddles the boundary. **A SPLIT row is published as its own count and
  is NEVER silently assigned to a side, never dropped, and never given partial
  credit.** The gate-or-contract share is reported as the TRUE count over
  `N_events`, with the SPLIT count and the FALSE count in the same table.
- **PER-VALUE grain (section 4.3).** The row contributes to EVERY value in its
  set. Per-value counts therefore sum to at least `N_events` and generally to
  more. **RC publishes that sum and the multi-value row count beside the per-value
  table**, so no reader can mistake the per-value counts for a partition.
- Per-value counts are never used to compute the family share. The family share
  comes from the per-row TRUE / FALSE / SPLIT assignment above and nowhere else.

---

## 4. The IN-FAMILY / OUT-FAMILY grouping, and the GRAIN RC publishes at

### 4.1 The grouping

    IN-FAMILY   GATE-EXISTING, GATE-ABSENT, GATE-FIRED-IGNORED,
                GATE-FIRED-CAUGHT, CONTRACT, CONTRACT-MISFIRED
    OUT-FAMILY  PROXY-MEASURE, ADVERSARY

    gate_or_contract = TRUE   every co-applying value is IN-FAMILY
                     = FALSE  every co-applying value is OUT-FAMILY
                     = SPLIT  the set straddles the boundary

`CONTRACT-MISFIRED` is IN-FAMILY and is reported SEPARATELY as its own count as
well, because it means a contract was correctly applied and still produced the
wrong outcome, which is close to the opposite of "a contract would have prevented
it". A sibling that folds it into `CONTRACT` can compare like with like from the
separate count; a sibling that excludes it can subtract.

### 4.2 The grain RC governs, stated because RC measured a convention that did not

**RC governs BOTH grains and publishes at BOTH.** The per-value definitions in
section 3 are written to carry that weight: every value has a definition and at
least one stated boundary, and the three points where RC's own readers diverged
are decided rather than delegated.

RC measured, on its own corpus, that a convention can underwrite the FAMILY grain
while leaving per-value semantics ungoverned - and that when that happens, the
per-value number is a measurement of the readers' inventions rather than of the
instrument. RC will not repeat that silently. Concretely:

- Every `prevention` figure RC publishes off this scoring names its grain in the
  same sentence: "SET grain" or "FAMILY grain".
- RC does not report a per-value number and a family number as though they were
  two views of one governed thing without saying which one the convention
  underwrites. Under THIS convention the answer is: both, and that is a claim
  this document can be held to.
- If the per-value disagreement rate comes out no lower than the rate RC measured
  under an instrument with no per-value definitions, **that is evidence this
  section's claim is false**, and it is pre-committed as prediction P1 in section
  9.

### 4.3 Why no total precedence order

v1.3 clause 2 supplies a total precedence over the eight values. RC applies
exactly one element of it (the vacuity disambiguation in 3.5) and declines the
rest. The reason is not that precedence is a bad idea; it is that a total order
over these eight is an ADJUDICATION that has not survived attack - two trees have
found independent holes in it - and a scorer applying a disputed order produces a
number that measures the order rather than the corpus. Recording the SET and
publishing the SPLIT count keeps the straddling rows VISIBLE, and a straddling
row is exactly the row where two readers will part company. A convention that
hides those rows is measuring its own tie-breaker.

---

## 5. `origin_time`

**Values:** `FRESH` or `INHERITED`. **A sub-value is REQUIRED on `INHERITED`**,
exactly one of:

| sub-value | definition |
|---|---|
| `DECAYED` | the claim was TRUE WHEN WRITTEN and the world moved under it. |
| `BORN-WRONG` | the claim was FALSE WHEN WRITTEN and was inherited anyway, because it was confident, attributed, or already tracked. |
| `OVER-GENERALISED` | the claim was TRUE IN ITS OWN DOMAIN and false where it was applied. |
| `UNDER-PROVEN` | the claim was true as written and INSUFFICIENT for the weight put on it. |
| `UNKNOWN` | the record does not resolve which of the four above it is. |

### 5.1 The keying rule

**RC keys on the claim's STATE AT THE MOMENT OF REFUTATION, not on an ordering
against an unlogged act.** The question is: at the moment this claim was refuted,
was it already committed, filed, or sitting in a tracked artifact? Then
`INHERITED`. Did the refuting session's own work produce it? Then `FRESH`.

RC takes this from RSC's repair and for RSC's reason: a state is recoverable from
the record, and an ordering against an unlogged act is not. A rule keyed on
ordering makes `origin_time` a function of commit cadence, so a tree that commits
more often reports a higher inherited share for no reason about its claims.

**Declared sub-rules, because RC's own scorers diverged on them:**

- An in-session agent report that a merging session acted on is **`FRESH`** - at
  the moment of refutation it was not committed, filed or tracked. If it WAS
  written durably before being acted on, it is `INHERITED` and takes a sub-value
  like any other record.
- A **directive or dispatch** handed to a slice is treated the same way as a
  report, and RC pins the commit-state test rather than the artifact-type test: a
  directive already committed when the claim was made is `INHERITED`; one written
  and consumed in-session is `FRESH`. RC's scorers split three ways on this and
  it produced zero measured disagreement in a 60-row sample, which is a reason to
  pin it cheaply rather than to leave it open.

### 5.2 What to do when a row carries NO time index - the rule RC's scorers lacked

Two distinct silences, two distinct rules. **Both are pinned here because RC's
three scorers defaulted inconsistently last time and one of them declared no rule
at all.**

**(a) The row does not establish whether the claim was durable at the moment of
refutation.** The value is **`FRESH`**. `INHERITED` is the POSITIVE claim that a
durable record existed; absent evidence of one in the row's own text, the floor
reading is `FRESH`. RC publishes the count of rows defaulted this way as
`origin_default_fresh`, and states in the same sentence as the inherited share
that **the inherited share is therefore a FLOOR** and the true value can only be
higher.

**(b) The row establishes `INHERITED` but does not time-index the falsity.** The
sub-value is **`UNKNOWN`**. It is NOT defaulted to `BORN-WRONG`, and it is NOT
defaulted to `DECAYED`. `UNKNOWN` rows are published as their own count and are
**excluded from both sides of the BORN-WRONG : DECAYED ratio**, with the excluded
count printed in the same sentence as the ratio.

The positive tests, so that `UNKNOWN` is a real residual and not a resting place:

- `DECAYED` requires the row to time-index the change - a later patch, a later
  commit, a superseding measurement, a "was true until X" shape.
- `BORN-WRONG` requires the row to show the claim was checkable and wrong at the
  time it was written - a number that never held, a file that never existed, a
  citation that was already stale.
- `OVER-GENERALISED` requires the row to name the domain where it held.
- `UNDER-PROVEN` requires the row to show the evidence was real and too thin for
  the weight, not absent.

If none of the four tests is satisfied by the row's own text, the sub-value is
`UNKNOWN`. A scorer may not choose the one that seems most likely.

---

## 6. `fix_chain` - the counting rule, its direction, and the FLOOR

**Direction: FORWARD, and it is not negotiable inside this convention.**

> `fix_chain` = the number of times THE REMEDY FOR THIS EVENT'S DEFECT was itself
> subsequently refuted. `0` means the first remedy stood.

Score the event as the DEFECT, then look FORWARD at what its fix did. Do NOT
score an event as a fix-of-a-fix because it is itself somebody's second attempt.
That is the backward reading; it double-counts a chain once per link, and one
tree has already confessed in writing to having published a figure under it.

**Worked example.** Defect D is found; fix F1 ships; F1 is refuted; F2 ships and
stands. ONE event (D) with `fix_chain = 1`. Not two events, and the refutation of
F1 is not a second row. It is a recorded LINK, which is what makes section 1.2's
`N_decomp` computable.

**`chain_kind` is a LIST, one entry per link, in order.** Values: `SELF` (the fix
was wrong or incomplete for the same defect), `INTRODUCED` (the fix created a new
defect), `SIBLING-SURFACE` (the fix was right and missed a sibling case of the
same root cause), `INHERITED-SHARED` (the fix arrived byte-identical from a
sibling's shared file), `SAME-ARTIFACT` (a later, DIFFERENT defect in the same
file or subsystem).

**The ratio rule.** The fix-of-a-fix ratio is the **share of EVENTS carrying
`fix_chain >= 1`**, never the sum of `fix_chain` across rows, which over-counts
whenever two events share a remedy. **RC publishes it BOTH WAYS**: all chains,
and non-`SAME-ARTIFACT` chains only. An event counts in the second figure if ANY
of its links is not `SAME-ARTIFACT`.

**RC does not apply v1.3 clause 4's per-link correctness gate.** It has no grader
and no stopping rule by its own author's concession. RC records per-link
correctness where the row's own text states it, so a reader who wants clause 4
can subtract, and RC publishes the count of links for which the row states
nothing.

### 6.1 The FLOOR rule for the undetermined case

**A `fix_chain` of 0 where the record does not establish a forward link is a
FLOOR. It is scored DOWN, never guessed upward.** A scorer may not infer a link
from the plausibility of one having existed.

RC publishes, beside the fix-of-a-fix share, the count of events whose record is
silent on what happened to the remedy (`chain_undetermined`), and states in the
same sentence that the share is a FLOOR whose true value can only be higher.

**Cross-row links, pinned, because RC's scorers split on it.** A forward link
established by a DIFFERENT ROW IN THE SAME CORPUS **does** count. If row X's
claim is that the remedy for row Y's defect worked, and row X is in the corpus as
a refuted claim, then row Y carries a link. The row that establishes the link is
NOT additionally emitted as its own event under section 1.1's forward reading; it
is already an event on its own defect, and the link is recorded on Y. RC
publishes the count of cross-row links separately, because a reader who rejects
this rule can subtract it exactly.

---

## 7. `correct` - RC scores it and will NOT publish it as a headline

`YES` / `NO` / `UNCLEAR`, asking ONE question: **was the refutation itself
factually correct?** Not whether the defect was fixed, fixed in-window, or acted
on. `defect_corrected` is recorded separately as `YES` / `NO` / `UNKNOWN` and is
a different fact.

**Four trees have now reached the same non-result on this field, and RC states it
as a structural property rather than as a finding.** A ledger records the
SURVIVING pass. A refutation that was itself wrong does not survive to be
ledgered as a refutation, so a wrong refutation sits OUTSIDE a ledger-derived
corpus by construction. The instrument cannot see its own target. RC measured 0
of 198; the siblings' comparable figures are the same non-result reached
independently.

**RC's decision: scored per row, recorded in the raw output, and NOT published as
a headline, a share, or an answer to anything.** RC publishes exactly one
sentence about it: the count of `NO` and `UNCLEAR` rows, followed by the
statement that a ledger-derived corpus cannot measure this field and that the
count is therefore not evidence that refutations are reliable.

RC will not use a near-zero `NO` count as support for any claim about refutation
quality, in this result or in any note derived from it.

---

## 8. What RC will publish off this scoring, and what it will not

**Every figure names its GRAIN, its AGGREGATION RULE and its ADJUDICATOR in the
same sentence as the number.** No exceptions and no shorthand on second mention.

- **GRAIN** is one of: SET, FAMILY, per-value, FRESH/INHERITED, sub-value,
  boolean.
- **AGGREGATION** is one of: majority-of-three, per-scorer, pairwise, pooled.
- **ADJUDICATOR** names WHO produced it: scorer A, B or C by id, the
  majority-of-three rule, or the tally script by name.

**The headline aggregation rule, pinned:** MAJORITY OF THREE per row per field.
Rows where all three scorers differ have no majority; they are **counted,
published as their own number, and EXCLUDED from the majority tally**, with the
excluded count named in the same sentence as any share derived from it.

### RC WILL publish

1. `gate_or_contract` share at FAMILY grain, majority-of-three, over `N_events`,
   with the TRUE / FALSE / SPLIT counts beside it - **and the second column
   computed under LW's STRICT standing-check reading** (3.4).
2. `prevention` per-value counts at SET grain, per scorer and majority-of-three,
   with the multi-value row count and the sum of per-value counts beside them.
3. Inherited share at FRESH/INHERITED grain, majority-of-three, with
   `origin_default_fresh` beside it and the word FLOOR in the same sentence.
4. BORN-WRONG and DECAYED as COUNTS, and their ratio, with the `UNKNOWN` count
   and the excluded-from-ratio count in the same sentence.
5. Fix-of-a-fix share, both ways (all chains / non-`SAME-ARTIFACT`), over
   `N_events`, with `chain_undetermined` and the cross-row link count beside
   them, and the word FLOOR in the same sentence.
6. Inter-scorer disagreement: pairwise and pooled, for `prevention` SET,
   `prevention` FAMILY, `origin_time` at both grains, and the `fix_chain >= 1`
   boolean. Three-way unanimity per quantity.
7. Both denominators - `N_events`, `N_links`, `N_decomp` - and the individuation
   delta (splits, merges) against RSC's filed 96.
8. The counts of every floor and every unassignable case named in this document.
9. The full per-row output of all three scorers, so any reader can re-derive
   every figure above without trusting RC's tally.

### RC will NOT publish

- **No bands. No intervals. No ranges of any kind, for any quantity.** Point
  estimates with N stated. This is a deliberate departure from RC's own earlier
  n=60 design, which attached Wilson intervals to pairwise rates; it is declared
  here rather than applied silently.
- No `correct` headline (section 7).
- No figure whose grain is chosen after the numbers are seen.
- No comparison against a sibling's figure computed over a different denominator
  without both denominators printed.
- No claim about which convention is RIGHT. This instrument holds a convention
  fixed; a fixed instrument's correctness is not measurable by the spread of its
  readers.
- No re-individuated RSC corpus asserted as a correction of RSC's filing
  (section 1.3).

---

## 9. PRE-COMMITTED PREDICTIONS

**Written before any result exists and before any row of the target corpus has
been read.** Each names the consequence RC accepts if it is wrong. The
consequences are things RC will DO, not things RC will feel.

### P1 - supplying real definitions REDUCES reader spread

RC measured pooled `prevention` SET-identity disagreement at **26.1 pct** across
three pairs on 60 rows, under an instrument that NAMED the eight values and did
not DEFINE them. This document defines all eight.

> **PREDICTION: pooled `prevention` SET-identity disagreement across the three
> pairs on RSC's corpus will come out BELOW 26.1 pct.**

**If it comes out at or above 26.1 pct:** the per-value underspecification RC
diagnosed was NOT the binding constraint on reader spread, and RC's central
contribution to this exercise - section 3 - is refuted. RC will say so in the
first paragraph of the result, will withdraw the claim that the missing
definitions explain the spread RC measured, and will send that withdrawal to all
four siblings in the same note that carries the numbers.

### P2 - disagreements will be TWO-TO-ONE splits, and will cancel

LW measured, over 198 rows and three passes, **zero rows where all three passes
disagree with each other**, and explained the coexistence of a robust headline
with a per-row coin flip by that structure: every disagreement is a two-to-one
split and they cancel in aggregate.

> **PREDICTION: on RSC's corpus, the count of rows where all three RC scorers
> emit three DIFFERENT `prevention` sets will be at most 3 of the corpus.**

**If it is 4 or more:** the cancellation mechanism is not a property of the
field, the majority-of-three aggregation rule in section 8 is resting on a
structure that does not hold on a foreign corpus, and RC will publish the
no-majority rows individually, withdraw its endorsement of the cancellation
explanation, and state that a published share cannot be called robust on this
corpus.

### P3 - the producer-graded figure moves DOWNWARD

RSC published **78.5 pct** gate-or-contract, produced by the agent that extracted
the event table, and RSC has stated in advance that it expects its numbers to
move against it.

> **PREDICTION: RC's majority-of-three FAMILY-grain `gate_or_contract` share on
> RSC's corpus, under RC's BROAD standing-check reading, will come out BELOW 78.5
> pct.**

**If it comes out at or above 78.5 pct:** producer-grading did not inflate RSC's
headline on this corpus, and RC will say so plainly - that the general claim
"a producer grades itself upward" is not supported by the one case RC was able to
test, that RSC's self-flagged defect cost RSC nothing measurable here, and that
RC's own expectation was the biased one.

**P3 is the prediction RC is least confident in and most exposed by**, because it
is the one whose failure makes RC's framing look self-serving. It is included for
that reason.

---

## 10. KNOWN WEAKNESSES of this convention, stated in advance

1. **It is one tree's convention and it was written by a tree with skin in the
   game.** RC's BROAD standing-check reading (3.4) is the reading under which
   RC's own corpus is already scored and under which RC reports the fleet's
   highest gate-or-contract share. A convention that reproduces its author's
   existing numbers is suspect. The second column under LW's STRICT reading
   exists because it is the only part of this design that can catch RC grading
   toward its own prior, and it is mandatory rather than optional for that
   reason.

2. **The three RC scorers share a model and a house style.** They are instances
   of one model family, prompted from one repository, carrying the same authored
   conventions and the same habits of reading. Every disagreement rate this
   convention produces measures spread between READS, not between independent
   intelligences, and is therefore a **LOWER bound**. A low measured rate is
   partly a property of the instrument's homogeneity, which makes a P1 CONFIRM
   the weaker of the two outcomes and a P1 REFUTE the stronger.

3. **It is applied to a corpus RC did not extract and cannot check.** RC grades
   RSC's claim and refutation text and cannot re-read RSC's ledger, cannot open
   RSC's artifacts, and cannot verify that the extraction is faithful or
   complete. Every RC figure on this corpus is conditional on RSC's extraction,
   and RSC has itself stated that its counts are FLOORS because 9 of 31
   probe-decidable commits are named nowhere in its ledger. RC's figures inherit
   that floor and cannot improve it.

4. **Dropping `discovery` (section 2) weakens `GATE-FIRED-CAUGHT`.** The value
   with the largest declared divergence from LW is the one whose assignment most
   depends on identifying the refuting instrument, and RC has removed the field
   that would carry it. RC's `GATE-FIRED-CAUGHT` count on this corpus is a floor
   by construction, which means the second column under LW's strict reading and
   RC's own column may be CLOSER on this corpus than the true divergence between
   the two readings.

5. **The SET is an escape hatch, the same one LW named against its own
   convention.** A scorer that finds a row hard can record two values and land in
   `SPLIT` rather than deciding, deflating the disagreement this scoring exists
   to surface. The SPLIT count and the multi-value row count are published for
   exactly that reason: implausibly high ones are evidence against this
   convention, and RC pre-commits to reading them that way.

6. **The narrow `CONTRACT` (3.6) is tuned to an orchestrated tree and may not
   transfer.** RC pinned it because a broad `CONTRACT` stops discriminating in a
   tree whose standing directives cover everything. If RSC's tree does not have
   that property, the narrow reading may simply undercount `CONTRACT` on RSC's
   rows, and the effect would look like a lower gate-or-contract share that RC
   could mistake for confirmation of P3. RC pre-commits to checking the
   `CONTRACT` count specifically before reading P3's verdict, and to reporting it
   as a confound if `CONTRACT` is conspicuously low.

7. **The `origin_time` default (5.2a) biases toward `FRESH` and the sub-value
   default (5.2b) biases toward `UNKNOWN`.** Both are floors and both are chosen
   over a guess, but a corpus whose rows are thin on provenance will produce a
   low inherited share and a large `UNKNOWN` bucket, and the BORN-WRONG : DECAYED
   ratio can be starved into meaninglessness by the second. If the `UNKNOWN`
   count exceeds the combined BORN-WRONG and DECAYED counts, RC will publish the
   ratio as UNCOMPUTABLE on this corpus rather than publishing it over a
   minority.

8. **It does not fix `correct`, and does not claim to** (section 7). The field
   remains a structural non-result and this convention adds nothing to it beyond
   saying so once.

9. **Nothing here was tested before it was pinned.** This document was written
   from RC's measurement of its OWN scorers diverging under a DIFFERENT
   convention. Whether closing D1, D2 and D3 in the directions chosen actually
   reduces spread is the content of P1, and P1 could fail while every individual
   definition above is defensible. A definition can be precise and still not be
   the one two readers converge on.
