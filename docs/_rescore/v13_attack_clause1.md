# Adversarial attack on v1.3 CLAUSE 1 (the EVENT definition)

RC's read of clause 1 of `REFUTATION_TAXONOMY_PIN_v1_3.md`, published by LW
2026-09-13. Read-only. This file attacks the CLAUSE. It scores no events and
re-scores nothing. Where an RC row or ledger entry is named it is named as a
TEST INPUT. Other trees are initials only.

**Sources actually opened for this attack, in full or in the cited part:** the
v1.3 pin; `docs/_rescore/pin_audit.md` (RC's v1.2 audit, source of FATAL-1);
`docs/_rescore/chunk1_rows.md` through `chunk4_rows.md` (198 rows);
`docs/_rescore/band_recompute.md`; `docs/LEDGER.md` entries 1373, 1392, 1399,
1402. Nothing is cited that was not opened.

**Clause under attack, quoted:**

> An EVENT is one CLAIM shown to be wrong. Individuate by the CLAIM, not by the
> artifact, the root cause, the fix, or the ledger entry. Two claims with
> distinct truth conditions that were separately assertable and separately
> wrong are TWO events even when one pass, one artifact and one root cause
> produced both. One claim is ONE event however many files its remedy touched.

**Ranking uses pin_audit's own scale.** FATAL = two good-faith readers produce
corpora with non-identical MEMBERSHIP. MATERIAL = membership is nested or
stable and totals shift. COSMETIC = wording, or a clause half that does no work
on this corpus.

**Counts: 2 FATAL, 3 MATERIAL, 1 COSMETIC.**

**Baseline figures used throughout, all re-derived from the rows this pass and
matching `band_recompute.md`:** RC fine N = 198 rows over 40 ledger entries in
a 42-entry window (1365-1406; entries 1382 and 1405 carry zero rows). Sum of
`fix_chain` links = 28, spread over 24 rows (21 rows at 1, 2 rows at 2, 1 row
at 3). Fix-of-a-fix fine share 24/198 = 12.1 pct; coarse (one event per entry)
19/40 = 47.5 pct. **RC's individuation band on that quantity is 35.4 points.**
LW's is 22.5 points (24.2 to 46.7). That 35.4 is the number clause 1 was
written to close, and every residual below is measured against it.

---

## PART 1 - FATAL

### FATAL-A. Clause 1 defines `event` in terms of `claim` and never defines `claim`, and RC's own four scorers already split on it under one prompt

**The defect is one level down, and it is the same defect.** v1.2 used `event`
thirty times undefined. v1.3 uses `claim` five times in one paragraph,
undefined, and makes it the sole individuation key. The question it fails on is
not exotic: **is the implied contract of shipped code a claim?**

**Case 1, and it is the decisive one: clause 1 does not decide FATAL-1's own
test case.** pin_audit built FATAL-1 on LEDGER 1402 (RM-313) and said the pin
permitted "ONE event or TWO" over two live defects in
`web/js/panels/champ_select.js` - the `:3516` strict-compare that badged the
wrong Arena player, and the `:3523`/`:3612` truthiness defect where the string
`"0"` read as a pick. **RC's scorer produced neither answer.** Entry 1402 yields
THREE rows (`chunk4-24`, `chunk4-25`, `chunk4-26`), and all three individuate by
a FILED CLAIM - RM-313's risk fence, RM-313's "hypothetical" framing, RM-313's
one-pass acceptance. **The `:3523`/`:3612` truthiness defect appears in zero of
RC's 198 rows** (grep for `3523`, `3612` and `truthy` across all four chunk
files returns nothing). So the case that generated the clause scores as 3, 2, 1
or 0 events depending on what a claim is, and clause 1 - written to repair
exactly this - adds no term that decides it.

**Case 2, the airtight cluster.** LEDGER 1392 yields 7 rows, of which
`chunk3-24`, `chunk3-25`, `chunk3-26`, `chunk3-27` and `chunk3-28` are latent
instrument defects found by an adversarial code read. `chunk3-28`'s claim is
"The tracer's patch of `builtins.open` is safely installed and removed" -
nobody ever asserted that in prose. Its own `pin_gap` says so: "The pin defines
fields and exclusions but never defines an EVENT. This row is a latent
instrument defect surfaced by an adversarial pass rather than a stated claim
contradicted; whether such rows count is unpinned."

**Case 3, the disagreement is INSIDE RC, not between trees.** `chunk4_rows.md`'s
preamble states an event definition that is already clause-1 shaped and then
draws the opposite boundary: "a point where a CLAIM made in the course of the
work was contradicted... **A pre-existing code bug with no stated antecedent
claim is NOT scored as an event here.**" `chunk2-21`'s `pin_gap` draws it the
other way: "a latent code defect carries no stated claim - only the implied
contract of the artifact. Scoring it INHERITED treats the code itself as the
durable record; the pin neither licenses nor forbids that." `chunk4-25`'s
`pin_gap` (b) names the collision outright: "Pin section 6 says 'score the event
as the DEFECT', which would admit bare code defects with no antecedent claim as
events; the task's definition would not."

**Why FATAL and not MATERIAL.** Every other attack in this file produces NESTED
corpora - a finer reader's events partition a coarser reader's. This one
produces non-identical MEMBERSHIP: `chunk3-28` is in one reader's N and absent
from another's, and its five siblings with it. A row present in one tree and
absent in another is not a rounding error on a shared measurement, it is a
different corpus.

**Row-count estimate.** 47 of 198 rows carry `discovery: CODE-READ`. A
mechanical pass for rows whose `claim` names no author, session, filing, figure
or document - i.e. reads as a bare artifact property - returns 26, but that
heuristic is noisy in RC's favour (several are genuine filed fences, e.g.
`chunk4-29`, `chunk4-30`). **The airtight pool is 5 (entry 1392); the defensible
pool is 10 to 14.** Removing 14 moves fix-of-a-fix from 12.1 pct to 24/184 =
13.0 pct, **+0.9 points against the 35.4-point band clause 1 closes**. The
SHARE movement is small. The membership movement is total for those rows, and
membership is what makes two trees' numbers the same measurement.

**Minimal repair.** One sentence, either way, stated: *"A CLAIM is a
proposition someone asserted, in prose or in a durable record. The implied
contract of shipped code is not a claim; a latent defect with no stated
antecedent is not an event. (Or: it IS, and the artifact is its author.)"* RC
does not care which. It cares that 198 and 184 stop both being conformant.

---

### FATAL-B. Clause 1 makes every refuted REMEDY an event, while the unwithdrawn v1.2 section 6 forbids emitting one as a row - and the collision lands on the exact quantity clause 1 exists to fix

**v1.3's header says "Nothing in v1.2 is withdrawn."** v1.2 section 6 requires
the FORWARD reading and bans emitting chain links as their own rows. All four
RC chunk preambles state the ban and apply it; `chunk1_rows.md`'s says "The
later links are deliberately NOT emitted as their own rows, per the section 6
worked example and its explicit ban on the backward reading."

**Clause 1 contradicts that, on its face.** A refuted remedy is a claim shown to
be wrong. Clause 1 says individuate by the claim and "not by ... the fix" - a
refuted remedy is not a fix being used as an individuation key, it is its own
assertion with its own truth conditions, separately assertable and separately
wrong. **Clause 4 makes this worse rather than better**, because clause 4
answers whether a link COUNTS as a link and is silent on whether it also counts
as an event, so a correct refutation of a remedy now has two homes and a rule
for neither.

**Case.** LEDGER 1373 carries a three-deep correction chain in one entry: an
adjudication pass asserted a live false-GREEN, that was corrected in source,
and "**My correction of THAT was then corrected in turn**" - the trigger set
was called "wider" when it is DISJOINT. The entry states the general principle
itself: "an account of your own prior error is a claim too." RC scored this as
ONE row, `chunk1-08`, with `fix_chain: 1`. Under clause 1 read literally it is
two or three events. **`chunk2-41`'s `pin_gap` names the seam in the abstract:**
"When the remedy for a badly-filed row is a REFUTATION WRITEUP, a false clause
inside that writeup is ambiguous between fix_chain on the original event and a
fresh event of its own. This file scored it as fix_chain; the pin does not say."

**Row-count estimate, and this one is large.** 28 links across 24 rows.
Links-as-events moves N from 198 to 226, **+14.1 pct on the denominator of
every published ratio**. The numerator of fix-of-a-fix also moves, since the 3
rows carrying `fix_chain` 2 or 3 imply links whose own remedies were refuted:
roughly 24 to 28. Net fix-of-a-fix 28/226 = 12.4 pct against 12.1 pct, so the
SHARE is nearly stationary - but the inherited share and the gate-or-contract
share have no such luck, because a link's `origin_time` is almost always FRESH
(it is authored inside the refuting session) while the parent event's is
INHERITED in 48.5 pct of rows. **Adding 28 FRESH events to a 198-row corpus
with a 48.5 pct inherited share drops that share to 96/226 = 42.5 pct, a 6.0
point move on the field the pin itself calls "the pin's most load-bearing
change".**

**Why FATAL.** Two readers of ONE contract - one following clause 1's text, one
following the unwithdrawn section 6 - publish corpora of 198 and 226 rows over
the same window, and the 28 rows of difference are not a refinement of anything;
they are absent from one corpus entirely. Same membership test as FATAL-A.

**Minimal repair.** *"A refuted remedy is recorded as a link on its parent
event and is NOT separately an event. Clause 1 individuates the DEFECTS in the
window; section 6 individuates their remedies."* (Or the converse, with
`fix_chain` deleted as redundant. Either is comparable; both being conformant
is not.)

---

## PART 2 - MATERIAL

### MATERIAL-A. "Separately assertable" has no stopping rule, so a conjunctive claim splits to arbitrary depth

**The clause tells you when two claims are two events and never tells you when
one sentence is one claim.** Any conjunctive assertion "X, at N, because Y"
satisfies the test - each conjunct has distinct truth conditions, each was
assertable alone, and where two are wrong, clause 1 mandates two events.

**Case, and it decides against the scorer.** `chunk2-19`'s claim is "that the
over-strip's blast radius was **1408 spans over 200 chars, 131 claim-shaped,
longest 5502**." Its refuter re-derived "565 scanned spans / 57 claim-shaped".
**1408 and 131 have distinct truth conditions, were separately assertable, and
were separately wrong.** Clause 1 as written mandates TWO events. RC scored ONE.

**Second case.** `chunk1-04`'s claim is "the prior session's census of 115
external-binary call sites over 940 top-level `tests/*.py`, 39 of them
false-RED", against LEDGER 1373's headline "EVERY INHERITED NUMBER WAS WRONG,
AND SO WAS THE PREMISE." The premise was split off as its own row
(`chunk1-06`), so the scorer split at one joint and not at the other, with no
stated principle separating them.

**The clause is not useless here - and the counter-case matters.** `chunk1-55`
reads "the responder, green across a 26-gate census, 68 mutants and a clean dry
cycle, would deliver a reply." Three figures, one operative claim; the three
are the JUSTIFICATION, not conjuncts of the assertion, and all three were true.
Clause 1 correctly yields ONE event. Likewise `chunk3-06`, where a sweep fixed
four instances of one class: "separately assertable" does real work and returns
ONE, because the four sites were never separately asserted. **So the clause
decides the easy conjunctive cases and fails only where conjuncts were
independently wrong** - which is the case its own second sentence was written
for.

**Row-count estimate.** 23 of 198 rows carry a `claim` with two or more
numerals, the identified pool. `band_recompute.md` sampled 24 rows on a fixed
deterministic stride and found 22 BY-CLAIM conformant, 1 BY-ARTIFACT
(`chunk1-48`, a filed row body naming three terminal states, "at least 2 events
and arguably 3" under clause 1) and 1 AMBIGUOUS (`chunk3-38`, two ids in one
fallback sentence). **That is 2 of 24 = 8.3 pct non-conformant, ALL of it
under-splitting, none over-splitting**, which extrapolates to roughly 16 rows
adding about 21 events: N 198 to 219, fix-of-a-fix 24/219 = 11.0 pct, **a 1.1
point move**.

**Why MATERIAL and not FATAL.** Every split refines; nothing is added or
dropped. A finer reader's events partition a coarser reader's, so membership is
nested and every event is traceable to exactly one event in the other reading.
That is a different animal from the entry-versus-claim collapse, and it is why
the residual is a point rather than thirty-five.

**Minimal repair.** *"A claim is individuated at the granularity at which its
author asserted it. A conjunctive sentence whose conjuncts were separately
wrong is one event per separately-wrong conjunct; a conjunctive JUSTIFICATION
for a single operative assertion is one event."*

---

### MATERIAL-B. "Separately assertable" presupposes an assertion, so an IMPLICIT claim has no handling

A stale document row asserts by implication: it does not say "this is still
true", it simply stands. Clause 1's test asks whether the claims "were
separately assertable", which is a counterfactual about a speech act that never
occurred.

**Case.** `chunk4-13`'s `pin_gap`: "the entry records the corrected effect
without restating the antecedent claim in full, so **event-hood rests on the
word 'already'**. The pin gives no rule for a correction whose antecedent is
implied rather than quoted." Same shape at `chunk4-21` (the root
`.gitattributes` "covered the new package, so a local green meant a green fresh
clone") and `chunk1-44` (a spec fence).

**Why it is not the same finding as FATAL-A.** A stale doc row HAS an author and
a durable text; what is missing is a restatement, not an assertion. FATAL-A is
about artifacts with no author at all. A repair to one does not repair the
other.

**Row-count estimate.** 21 rows carry `origin_time: INHERITED / DECAYED` (a
decayed record is the canonical implicit-claim shape). Between a strict reading
(an implication is not an assertion, so these are not separately assertable and
collapse toward their parent record) and a permissive one, movement is bounded
by those 21 and is realistically 5 to 8 rows, **under 1 point on any published
share**.

**Minimal repair.** *"A record that stands unrevised asserts its content
continuously. An implicit claim is separately assertable if its text can be
quoted and shown false without quoting any other."*

---

### MATERIAL-C. Individuating by CLAIM requires a claim IDENTITY relation, and clause 1 supplies none, so one claim refuted twice in-window is one event or two

Clause 1 replaces the entry as the individuation key with the claim, and a key
needs an identity criterion. "One CLAIM shown to be wrong" is silent on whether
the same proposition refuted on two occasions is one event.

**Case.** `chunk3`'s `pin_gap` at the RM-396 row: "Exclusion 1 covers recitals
of refutations from OUTSIDE the window. This refutation is re-told inside the
window at entry 1391; the pin does not say whether an in-window re-tell is a
second event. Scored once." pin_audit filed the same seam as MATERIAL-8 against
v1.2 (LEDGER 1379's rejection of a retraction token, quoted verbatim while
closing RM-217 at LEDGER 1406, both inside the declared window). **v1.3 does not
address it, and clause 1 makes it sharper rather than softer**, because under
v1.2 the ledger entry was at least an available tiebreak and clause 1 forbids
using it.

**Row-count estimate.** RC's scorers applied exclusion 1 by hand; the identified
in-window re-tells are 2 to 4 rows. **Under 0.5 points.** Reported because the
mechanism is clause-1-specific, not because it moves anything.

**Minimal repair.** *"A claim already scored as an event is never scored again,
in or out of window. Two claims are the same claim if they have the same truth
conditions."*

---

## PART 3 - COSMETIC

**C1. The clause's fourth sentence is inert on RC's corpus.** "One claim is ONE
event however many files its remedy touched" fixes individuation-by-fix.
`band_recompute.md` measured **zero of 198 rows individuated by fix**, and
found it structural rather than lucky: all four scorer preambles state the
FORWARD reading and fold a refuted remedy into `fix_chain`. Half the clause's
prohibitions ("not by the fix") therefore bind nothing here. Worth noting only
so that a reader does not credit clause 1 with a correction it did not have to
make on this corpus - it may well bind elsewhere.

---

## PART 4 - WHAT CLAUSE 1 UNAMBIGUOUSLY FIXES

A review that cannot say what a clause fixed is not a review, and this one is a
real improvement, not a cosmetic one.

**1. It forbids the coarse convention outright, and that IS the 35.4 points.**
"Individuate by the CLAIM, not by ... the ledger entry" makes RC's coarse end -
N=40, fix-of-a-fix 47.5 pct - simply non-conformant. It is no longer one of two
defensible readings; it is out of contract. The entire band LW priced at 22.5
points and RC measures at 35.4 exists because BOTH ends were admissible under
v1.2. Clause 1 deletes one end by fiat, which is the correct move for a
contract whose purpose is comparability, and it is the whole of the headline
defect.

**2. It decides the artifact case, against the intuition, and RC's scorer had
already guessed right without authority.** `chunk4-18`, `chunk4-19` and
`chunk4-20` are three false propositions in one README, one artifact, one
author, one pass. The scorer's own `pin_gap` says they are "equally defensible
as one event or three. Scored as three ... because each is a distinct false
proposition." Clause 1's "not by the artifact" plus "even when one pass, one
artifact and one root cause produced both" now backs that reading explicitly.
`chunk2-43`/`-44`/`-45` are the same shape from one filed report and get the
same answer.

**3. It decides the root-cause case, which is the harder direction.** A reader
tempted to merge two defects because one root cause produced both is now
forbidden to. That is the direction people actually err in, and the clause
names it.

**4. "Separately assertable" does real work at the lower bound.** It correctly
returns ONE event for `chunk3-06` (four instances of one class fixed by one
sweep, never separately asserted) and ONE for `chunk1-55` (three green signals
justifying one operative claim). Those are the two shapes most likely to be
over-split by a scorer trying to be thorough, and the clause stops both without
needing a further rule.

**5. It moots a second individuation sensitivity RC had measured underneath
FATAL-1.** `band_recompute.md` found that at the COARSE grain the
BORN-WRONG:DECAYED ratio moves from 1.73:1 to 5.2:1 purely on the sub-value
aggregation rule (any-of against precedence), a factor of three at fixed
convention and fixed corpus, and that under clause 2's precedence order the
leading `prevention` bucket at coarse grain becomes GATE-FIRED-CAUGHT (15 of
40), which is neither bucket the fine end argues about. **Clause 1 makes all of
that unreachable**, because a conformant tree never aggregates to entry grain in
the first place. That is a second defect closed as a side effect, and LW did not
claim it.

---

## VERDICT

**Clause 1 CLOSES the denominator problem it was written for and RELOCATES a
residual roughly one tenth its size, with one genuinely open membership
question that is not a residual at all.** Measured on RC's corpus: the band
clause 1 deletes is 35.4 points on fix-of-a-fix (12.1 fine against 47.5
coarse); the band it leaves is the distance between "one claim as its author
asserted it" and "one truth condition per separately-wrong conjunct", which
RC's deterministic 24-row conformance sample prices at 8.3 pct of rows, all
under-splitting, moving N from 198 to about 219 and fix-of-a-fix by 1.1 points,
and which is NESTED rather than disjoint so that every finer event maps to
exactly one coarser one. On the owner's decisive question - does clause 1 stop
the monotonic inflation of fix-of-a-fix under collapse - the answer is **yes for
the mechanism they named and no for a second mechanism they did not**: collapse
to entry grain is now out of contract, but the clause's own text makes every
refuted remedy an event while v1.2 section 6, explicitly unwithdrawn, forbids
emitting one, and that single unresolved reading moves RC's N by 14.1 pct and
its inherited share by 6.0 points in one step, which is larger than every
splitting residual in this file combined. **The two findings ranked FATAL are
both membership questions rather than grain questions** - whether a latent code
defect with no author is a claim at all (clause 1 inherits `claim` undefined
exactly as v1.2 inherited `event` undefined, and RC's own four scorers, under
one prompt, drew that boundary two different ways and said so in their own
`pin_gap` lines), and whether a refuted remedy is an event as well as a link.
Neither is closed by a finer grain, because no amount of splitting decides
whether a thing is in the corpus. **The honest summary is that clause 1 is a
large, real and correctly-targeted repair that fails its own worked test case:
LEDGER 1402, the case pin_audit used to raise FATAL-1, still scores as 3, 2, 1
or 0 events under v1.3, and RC's actual scorer produced three rows none of which
is either defect pin_audit named.**
