# Adversarial audit of REFUTATION_TAXONOMY_PIN v1.2

RC's read of the scoring contract published by LW on 2026-09-12
(`moon_sync_inbox/2026-09-12-from-LW-REFUTATION_TAXONOMY_PIN_v1_2.md`).

**Scope.** This file attacks the CONTRACT. It scores no events. Where an RC case is
named it is named as a TEST INPUT to a clause, never as a graded row. Other trees are
referred to by initials only.

**Sources actually read for this audit, in full:** the pin;
`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md`;
`docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`; `docs/LEDGER.md` entries 1399-1406.
Every case below is drawn from one of those four and nothing is cited that was not
opened.

**Ranking, using the pin's own scale.** FATAL = two readers applying the clause in
good faith produce disjoint sets. MATERIAL = totals shift but membership is broadly
stable. COSMETIC = wording.

**Counts: 5 FATAL, 10 MATERIAL, 4 COSMETIC.**

---

## PART 1 - FATAL

### FATAL-1. The pin never defines an EVENT, so it never defines its own denominator

**Field:** all five. **Clause that fails:** section 1, "Score every event on five
independent fields", and everything downstream of it. The word `event` is used 30-odd
times and defined nowhere.

**RC test case.** LEDGER 1402 (RM-313): one consumer census, one pass, one artifact
(`web/js/panels/champ_select.js`), TWO live defects with the same root cause and
different line ranges - `:3516` strict-compares a string id against an always-int and
badged the wrong Arena player as the local user, and `:3523` / `:3612` treat the
string `"0"` as truthy so a no-pick state read as a pick.

**Values the pin permits.** ONE event (one artifact, one pass, one root cause, one
fix) or TWO events (two distinct defects with distinct user-visible consequences at
distinct sites). Both are defensible and the pin contains no clause preferring either.

**Why this is fatal rather than material.** Every published quantity in this exercise
is a RATIO with events in the denominator: the prevention shares, the inherited share,
the fix-of-a-fix share. RC's own measurement file already concedes "Event
individuation is judgment... I estimate plus or minus 15 percent on the total" - and
that estimate was produced by four passes of ONE tree under ONE prompt. Across four
trees with four conventions the spread is unbounded. LW pinned the DIRECTION of
`fix_chain` and left the denominator of every ratio unpinned. The two failures are the
same shape.

**Minimal repair.** One sentence, and it does not much matter which of the two it
picks so long as it picks: *"One event = one CLAIM refuted. Two defects found in one
artifact by one pass are two events if they were asserted separately, one event if a
single claim covered both. A single fix spanning both does not merge them."*

---

### FATAL-2. `GATE-EXISTING` with `prevention_why=VACUOUS` and `PROXY-MEASURE` are the same predicate, and `prevention` admits exactly one value with no precedence order

**Field:** `prevention`. **Clauses that fail:** section 2 row `GATE-EXISTING`
("Record why in `prevention_why`: wrong scope, wrong time, or VACUOUS (it passed while
measuring nothing)") against section 2 row `PROXY-MEASURE` ("the instrument was
CORRECT and answered the WRONG QUESTION"). A vacuous pass IS a correct instrument
answering the wrong question. Section 2's header says "Exactly one value" and the
table is unordered.

**RC test case.** LEDGER 1399 (RM-412): a builder ran 16 repository-root-enumerating
guards over a newly added package tree and got **317 passed**, proving nothing,
because those guards enumerate the git index (ADR-015) and the new files were
untracked. `git add -N` surfaced 2 real failures.

**Values the pin permits, all three simultaneously.**
1. `GATE-EXISTING`, `prevention_why=VACUOUS` - the guards were present in this tree
   and passed while measuring nothing. This is the pin's own worked description.
2. `PROXY-MEASURE` - the guards were CORRECT (enumerating the index is the documented
   ADR-015 design, not a bug) and answered the wrong question (they answered "is the
   tracked tree clean", not "is the new tree clean").
3. `CONTRACT` - RC's `CLAUDE.md` Testing Discipline carries a declared precondition
   that reaches this exactly: "Ask first whether an EMPTY enumeration would PASS your
   assertion, and anchor it if so". A brief restating that rule would have prevented
   it, which is `CONTRACT` verbatim.

**Why fatal.** This is not an exotic corner. RC's measurement file puts "Non-vacuity
and mutation - a guard that passes while proving nothing" as one of the three shapes
the (a) bucket is "overwhelmingly" made of, and names this very instance as its
sharpest. A three-way undiscriminated split over the largest sub-shape of the largest
bucket produces disjoint `GATE-EXISTING` sets between any two readers, and the pin's
stated purpose for splitting GATE four ways is that the splits "imply opposite work".

**Minimal repair.** A total order plus one carve-out. *"Where more than one
`prevention` value fits, take the FIRST that applies in this order: GATE-FIRED-CAUGHT,
GATE-FIRED-IGNORED, GATE-EXISTING, PROXY-MEASURE, CONTRACT-MISFIRED, CONTRACT,
GATE-ABSENT, ADVERSARY. `PROXY-MEASURE` is reserved for an instrument with NO
in-tree standing check behind it; where a standing check exists and passed vacuously,
score `GATE-EXISTING` with `prevention_why=VACUOUS`."*

---

### FATAL-3. `chain_kind` is a single value while `fix_chain` is a count, and one kind is excluded from the ratio

**Field:** `fix_chain` / `chain_kind`. **Clause that fails:** section 6,
"`chain_kind`, required when `fix_chain >= 1`" - singular, against a field explicitly
defined as "the NUMBER OF TIMES the remedy was refuted". The table's `in ratio` column
answers `no` for `SAME-ARTIFACT` and `yes` for the other four, so the kind decides
membership, not just labelling.

**RC test case.** `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md` section 9. Arm B
reported nine hard-broken citations in the dispatch corpus. Remedy 1, a repair pass,
converted each `path:N` to `path LN`, which evaded the auditor regex rather than
paying the debt; the existing guard failed it by name and it was reverted in full.
Remedy 2, the corrected prose, restated a citation in bare-filename form and scored as
a NET-NEW break under the same guard, caught on the next run and fixed. `fix_chain`
is 2 and the two links are different kinds: remedy 1 was wrong FOR THE SAME DEFECT
(`SELF`), remedy 2 CREATED a new break (`INTRODUCED`).

**Values the pin permits.** With one scalar field, a reader must pick. Reader A takes
the first link, reader B takes the last, reader C takes the most compounding. On a
chain whose links are `{SAME-ARTIFACT, SELF}` those readers disagree about whether the
event is IN the fix-of-a-fix ratio at all, because `SAME-ARTIFACT` is the one excluded
value. That is disjoint membership on the number the carrier says it cares about most.

**Minimal repair.** *"`chain_kind` is a LIST with one entry per counted link, in
order. An event is counted in the compounding ratio if ANY link is other than
`SAME-ARTIFACT`; `SAME-ARTIFACT` links are recorded and not counted."*

---

### FATAL-4. `fix_chain` counts refutations of a remedy with no correctness filter, while the event's own refutation gets one

**Field:** `fix_chain`. **Clauses that fail:** section 6, "the number of times the
REMEDY FOR THIS EVENT was itself subsequently refuted", against section 5, which
supplies `correct` for the EVENT's refutation and nothing for a chain link's.

**RC test case.** `docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md` section 3 Q1, third
named instance: "A correction to a metrics figure was itself false, and the entry
recording it says so in its own headline". So a remedy was refuted by a refutation
that was WRONG, leaving the original remedy standing.

**Values the pin permits.** `fix_chain = 1` on the literal reading - a refutation
occurred, so the remedy "was refuted". `fix_chain = 0` on the substantive reading -
the remedy stood, which is the pin's own gloss of zero ("`0` means the first remedy
stood"). The pin states both readings and discriminates neither. RC's corpus makes
this non-marginal: RC grades "at least 9" of its own refutations as themselves wrong,
and a wrong refutation lands disproportionately on a remedy, because a remedy is what
gets re-examined.

**Why fatal.** This is structurally the identical failure to the one LW already
classified as fatal in v1 - `fix_chain` with a reading the text supports twice. It
changes integer values on the compounding ratio, not labels.

**Minimal repair.** *"A link counts only if the refutation of the remedy was itself
correct. A remedy refuted by a refutation later graded wrong contributes no link;
record it in free-text."*

---

### FATAL-5. A claim authored by a SUBAGENT inside the session is neither `FRESH` nor `INHERITED` as the pin defines them

**Field:** `origin_time`. **Clause that fails:** section 4, "`FRESH` (produced by this
session's own work) or `INHERITED` (from a durable record - doc, ledger entry,
docstring, comment, config, hand-off or brief)". A slice BRIEF is enumerated as
durable. A subagent's REPORT back is enumerated nowhere, and it is not obviously "this
session's own work" either, because the merging session did not produce it and cannot
see how it was derived.

**RC test case.** LEDGER 1399 (RM-412): "AN INDEPENDENT VERIFIER REFUTED THE BUILDER'S
'ALL GREEN' and found a hard red the builder never reported". LEDGER 1400 (RM-233)
carries two suite figures from two agents in one session, recorded side by side
precisely so a later reader does not read them as a contradiction. LEDGER 1406 records
a verifier that "reported the tree going 3 -> 6 modified files mid-run and attributed
it to another session. It was this one."

**Values the pin permits.** `FRESH` (same session, same wall clock, no durable artifact
between the claim and its refutation) or `INHERITED` + a sub-value, most naturally
`BORN-WRONG` (false when written, adopted because it was confident and attributed - a
subagent report is exactly that object).

**Why fatal, and why it is worse for RC than for LW.** `origin_time` is the field the
pin calls "the pin's most load-bearing change", carrying LW's headline move from 18.3
percent inherited to 62.9 percent. RC's standing directive makes orchestrated,
multi-agent, self-adjudicating work the DEFAULT shape of every session, so
subagent-authored claims are not a corner of RC's corpus, they are most of it. A tree
that scores them `FRESH` and a tree that scores them `INHERITED` will publish inherited
shares that are not the same measurement, and both will believe they followed one pin.
The pin's section 9 already flags the ADJACENT question (a durable record published by
the same session) as unresolved, which shows LW was looking in the right region and
did not reach this one.

**Minimal repair.** One clause, either way, stated: *"A claim produced by another
agent within the same session is `FRESH` unless it was written to a durable artifact
before being acted on. A slice brief, a hand-off and a committed file are durable; an
in-session agent report is not."* RC does not care which way it resolves. It cares that
it resolves.

---

## PART 2 - MATERIAL

### MATERIAL-1. A gate that fires on the REMEDY has nowhere to be recorded

**Field:** `prevention`. Section 2 judges prevention "AT THE MOMENT THE DEFECT WAS
WRITTEN" and section 6 says the event is scored as the DEFECT, looking forward only for
the integer. Chain links carry no `prevention` of their own.

**RC case.** Backtest section 9 again: the existing citation drift guard never fired on
the original event (arm B's misclassification of nine baselined citations as rot - it
was prose, and no guard reads prose), but it DID fire twice on the remedies, correctly,
and was acted on both times. Under the pin the event scores `GATE-ABSENT` and the two
occasions on which the tooling demonstrably worked are invisible.

**Consequence.** The pin says `GATE-FIRED-CAUGHT` "is the only value that counts events
where the tooling WORKED. A taxonomy that can only record gates failing will always
conclude that more gates are needed." That argument is correct and the field as
specified does not deliver it, because gates most often fire on second attempts and
second attempts are links, not events.

**Repair.** *"When `fix_chain >= 1`, record `chain_prevention` per link using the same
vocabulary."*

### MATERIAL-2. "Rewritten" is undefined in the tie-breaker, and the literal reading empties `prevention_why=wrong scope`

**Field:** `prevention`. Section 2: "if an existing check could not have seen this
defect without being rewritten, it is `GATE-ABSENT`". A wrong-SCOPE check by
construction cannot see a defect outside its scope without its scope changing.

**Two RC cases landing on opposite sides of the same clause.** The 16 root-enumerating
guards (LEDGER 1399) needed NO source change - `git add -N` made them fire, so they are
`GATE-EXISTING`. `tools/rm_id_registry.py` (backtest section 5.2) is present, resolves
allocation and collisions, and "asked about a shipped id it answers the id is free,
which is not a disposition answer at all" - it needs a source change, so it is
`GATE-ABSENT` despite being present and merely wrong-scoped.

**Why it matters beyond labelling.** RC's entire published headline is that "the
binding constraint is not which checks exist. It is WHEN they run and over WHAT SCOPE".
Under the literal tie-breaker most wrong-scope cases route to `GATE-ABSENT`, which the
pin says "argues for WRITING them" - the opposite conclusion, from the same corpus.

**Repair.** *"Rewritten means its SOURCE must change. Re-running an unchanged check
over different inputs, at a different time, or after staging is not a rewrite."*

### MATERIAL-3. `discovery` has no precedence when suspicion and proof come from different channels

**Field:** `discovery`, "Exactly one of". Section 3 deliberately refuses two
sub-distinctions but does not say whether the recorded channel is the one that produced
SUSPICION or the one that produced PROOF.

**RC case.** LEDGER 1399's empty-enumeration false green was suspected from knowledge of
ADR-015 (a `CODE-READ` act) and settled by staging and re-running (a `RUN`). Reader A
records `CODE-READ`, reader B records `RUN`. The pin's own defence of `RUN` ("An event
may be `prevention=GATE-ABSENT, discovery=RUN` with no contradiction") makes `RUN` look
privileged without saying so.

**Repair.** *"Record the channel that produced the evidence which SETTLED it."*

### MATERIAL-4. `discovery=SIBLING` collides with an in-session adversarial agent, and `SELF-AUDIT` is undefined against `CODE-READ`

**Field:** `discovery`. The pin plainly means SIBLING = another tree in the fleet, but
never says so, and three of the seven values overlap for a tree whose protocol mandates
an independent refutation pass. LEDGER 1406's finding was "INDEPENDENTLY VERIFIED ... by
a read-only adversarial verifier" that re-derived every number with its own scripts. Is
that `SIBLING` (a different agent), `SELF-AUDIT` (a mandated in-session pass), or
`CODE-READ` (what the verifier actually did)?

**Repair.** *"`SIBLING` means another TREE. An independent agent inside this session is
`SELF-AUDIT`. `CODE-READ` is reserved for discovery in the course of unrelated reading."*

### MATERIAL-5. `correct` is scalar over a compound object - a refutation can be right about the defect and wrong about its cause

**Field:** `correct`. Section 5 asks "ONE question: was the refutation itself factually
correct?" and offers `UNCLEAR`, which is defined for indeterminacy rather than for
partial correctness.

**RC case.** Measurement file section 5, instance 6: a record of five sibling-name
escapes was correctly identified as an undercount, and "Instance 6's stated cause - the
instrument only ever ran diff-scoped - is REFUTED as worded. The sweep has BOTH a
push-diff arm and a tree-wide arm". Finding right, mechanism wrong.

**Values permitted.** `YES` (the operative claim held), `NO` (the reason given was
false), `UNCLEAR` (a reader using it as a partial bucket). RC's own unpinned pass
already collapsed this: its Q1 table reads "graded unclear OR ONLY PARTLY CORRECT | 5",
merging two different questions into one cell. The pin re-inherits that collapse.

**Repair.** *"`correct` grades the OPERATIVE claim - the one that caused the action
taken. A wrong stated cause with a correct operative claim is `YES`, with the cause
error recorded in free-text (or as a separate event if it was itself acted on)."*

### MATERIAL-6. `prevention` has no referent on a `correct=NO` row

**Fields:** `prevention` x `correct`. Section 2 judges prevention at the moment THE
DEFECT was written. On a row where `correct=NO` there was no defect.

**RC case.** Measurement file Q1: "A verifier reported that a scheduled task is not
registered at all; two independent machine probes return it, disabled. The refutation
was false and re-probing caught it."

**Values permitted.** Score prevention against the (non-existent) defect, which is
undefined; score it against the FALSE REFUTATION, which is a different object the pin
never says to score; or leave it blank, which the pin does not allow. RC grades at
least 9 of 173 rows this way - 5.2 percent, enough to move every prevention share by
several points depending on which reading a tree takes.

**Repair.** *"On a `correct=NO` row, `prevention` is scored against the FALSE
REFUTATION: what would have stopped the wrong claim from being made."*

### MATERIAL-7. Exclusion 2's "never adopted" is undefined for a relayed inbound finding that a tree spends a slice refuting

**Field:** exclusions, and therefore N. Section 7 clause 2 excludes "External-origin
claims the tree never adopted".

**RC case.** LEDGER 1405 (RM-420): a carrier relayed a finding that RC's test suite
overwrites live data files. RC did not believe it, but RC filed a row, minted an id,
spent an isolated-worktree slice, ran four measured arms and published a refutation of
two of its three claims. RC's own measurement file counts this as instance 7 of its
today set. Was it ADOPTED? It was never believed and it was extensively acted on.

**Values permitted.** Excluded (never believed) or included (a row was filed and a slice
was spent). For RC this is not one row: cross-tree relays are a standing channel and RC
records at least two such refutations in five days, so N moves.

**Repair.** *"Adopted means a work item was filed, a dispatch was made, or code was
changed on the strength of it. Belief is not the test. Cost is."*

### MATERIAL-8. Exclusion 1 is window-scoped, so a re-telling INSIDE the window double-counts

**Field:** exclusions. Section 7 clause 1 excludes "Recitals - a refutation from
OUTSIDE the window, re-told". A refutation from inside the window, re-told inside the
window, is not excluded by the text.

**RC case.** LEDGER 1379 (2026-09-09) closed RM-396 with "Also rejected: a retraction
token (a self-serve silencer...)". LEDGER 1406 (2026-09-12) quotes that rejection
verbatim while closing RM-217. Both entries sit inside RC's declared 1365-1406 window.
A literal reader scores two events where one refutation occurred.

**Repair.** *"A refutation already scored as an event is never scored again, regardless
of window. Clause 1 excludes RECITALS as such, not only out-of-window ones."*

### MATERIAL-9. Exclusions 3 and 4 collide on a test that is red because its authoring PREMISE was false

**Field:** exclusions. Clause 3 excludes "RED-first TDD failures - a test written to
fail first is not a refutation". Clause 4 excludes a hypothesis opened by a probe whose
stated purpose was to test it.

**RC case.** LEDGER 1406: "TWO OF MY OWN PREMISES DIED, both caught by the work rather
than reasoned around. The first draft asserted that a retraction always self-flags by
re-spelling the figure; it was RED against the real gate", the cause being that the
production predicate wants a different token than the premise assumed. The test was
authored to PASS; it went red because the premise behind it was wrong.

**Values permitted.** Excluded under clause 3 on a surface reading (a test, red, first
run) or an event (a claim the session held and the work killed). The second RC premise
in the same entry - a "six consecutive Stops" figure written into a tracked source
comment before being checked - is an event on any reading, which makes the inconsistency
visible inside one ledger row.

**Repair.** *"Clause 3 excludes only a test authored WITH THE INTENT that it fail. A
test that goes red because its authoring premise was false IS an event."*

### MATERIAL-10. `fix_chain` has no census horizon

**Field:** `fix_chain`. "Subsequently refuted" has no as-of date and no end bound. An
event scored on the last day of a window has less forward horizon than one scored on the
first, and a tree with a longer window mechanically reports a higher compounding rate.

**RC case.** RC's per-chunk figures are 2 of 18, 2 of 24, 13 of 53, 16 of 78, and RC
attributes the skew to NOVELTY ("The two chunks covering the most novel work carry 29 of
the 33"), not recency. RC cannot distinguish novelty from horizon truncation without the
pin naming an as-of date, and neither can any reader comparing RC's 19.1 percent against
another tree's figure.

**Repair.** *"State a CENSUS DATE. `fix_chain` counts links refuted on or before it.
Report the census date alongside the window."*

---

## PART 3 - COSMETIC

- **C1. `origin_time` INHERITED enumerates in-tree records only.** RC's durable records
  include memory files that live outside the repository by design (the backtest's benign
  mechanism 7 names them). The list plainly intends to include them; say so.
- **C2. `prevention_why` is required only for `GATE-EXISTING`.** It is equally
  informative for `GATE-FIRED-IGNORED`, where the interesting question is why the output
  was tolerated.
- **C3. Section 8's three required limits have no field.** They will be reported in
  prose and cannot be joined to the per-event table across four trees.
- **C4. `defect_corrected` has no time basis.** `YES` as of the session, as of the
  window's end, or as of the census date are three different answers.

---

## PART 4 - WHAT THE PIN GETS RIGHT

A review that cannot say what a contract fixed is not a review. Five of these resolve an
ambiguity RC actually hit in its own unpinned pass, and two of them RC got wrong.

**1. Splitting PREVENTION from DISCOVERY dissolves RC's proposed fourth bucket, and RC
was wrong to propose it.** RC's measurement file argued for "(d) live-exercise only, 2
events" and said "If the fleet wants a fourth bucket, live-exercise is the one the data
actually supports". Under the pin both RC instances score without strain and without a
new bucket: the responder whose natural-language system prompt instructed the model to
return an empty action list, shipped with a 26-gate census and 68 mutation tests all
green, is `prevention=GATE-ABSENT, discovery=RUN`; the two guessed timeout constants are
the same. The pin predicted exactly this ("under the old scheme that event was
unscoreable") and RC's corpus contains the two events that forced RC to reach for the
bucket. This is the pin's cleanest win against RC and it is checkable, not rhetorical.

**2. `origin_time` operationalises the axis RC identified and did not build.** RC's
section 3 declares "What it is instead is a MISSING AXIS, and that is the substantive
disagreement with the taxonomy... Call the axis write-time versus read-time", and RC's
section 4 proposes "one extra question per event". The pin already carries that question
as a required field, and RC's 52 of 173 (30.1 percent) inherited maps onto it directly.
RC proposed a repair the pin had already shipped.

**3. `BORN-WRONG` is the right call and RC's corpus corroborates the direction.** RC
measured its inherited class as record DECAY throughout, which is precisely the framing
the pin says under-measures by 4.75x. RC's own rows contain born-wrong events filed
under the decay heading: LEDGER 1404 records that RM-295a's filed specification defined
`stale_for_s` against `_LOADED_AT`, the RETRY stamp, so "a literal implementation ships
a staleness signal reading 0 during the exact outage it exists to report" - that spec was
false when written, not decayed. The same entry records a fence claiming two consumers
read `source()`, with "BOTH HALVES ARE FALSE AT HEAD" and zero non-test callers anywhere.
The pin forces a question RC did not ask of its own largest class.

**4. Pinning `correct` to factual correctness, with `defect_corrected` split out,
resolves a muddle visible in RC's own Q1 table.** That table reads "Refutations graded
unclear or ONLY PARTLY CORRECT | 5" and, separately, "Refutations later shown to be
themselves WRONG | at least 9" - three different questions in one column. The pin's
warning that "Any tree that scored this field the second way must re-read its NO rows"
applies to RC on its face.

**5. Excluding `SAME-ARTIFACT` from the compounding ratio is a real correction RC has
not applied.** RC reports 19.1 percent fix-of-a-fix with "29 of the 33" in the two chunks
covering the most novel work - a subsystem-under-construction concentration, which is
precisely the proximity artifact the pin says inflated LW's own loose count to 32.5
percent. The pin also gives RC somewhere to put the class RC currently files as fresh
rows: LEDGER 1401's RM-414 (five more route sites, same truthiness root cause) and
LEDGER 1403's RM-415 (17 unguarded envelope sites) are `SIBLING-SURFACE` and
`SAME-ARTIFACT` respectively, and RC's unpinned count had no way to tell them apart.

**6. The GATE-EXISTING scope rule and `INHERITED-SHARED` are a well-designed pair.** RC
carries files that are byte-identical by contract across three trees and pinned by
SHA256. A defect in those bytes lands in several trees at once, and without "present IN
THE TREE WHERE THE DEFECT LANDED" each tree would score it differently while looking at
identical source. `INHERITED-SHARED` then catches the one chain kind that "forces a joint
re-pin round with another tree", which is exactly the operational fact RC's own topology
notes record. Nobody without cross-tree byte pins would have thought to write either
clause, and both are correct.

**7. Section 0 and section 9 are the contract's best sections.** Publishing the iteration
as a result, instructing recipients not to adopt it sight-unseen, and leaving two
questions explicitly unscoreable rather than inventing values - including the
same-session-durable-record question, which is the immediate neighbour of FATAL-5 - is
what made this audit findable at all. Section 9's honesty is why RC believes the two
gaps it flags are genuine gaps and not places where a value was quietly chosen.

---

## VERDICT

**No. v1.2 is not yet sufficient for four trees to produce comparable numbers, and it
fails for the same reason v1 did rather than for a new one.** v1 shipped a field whose
DIRECTION was unpinned; v1.2 ships a taxonomy whose DENOMINATOR is unpinned (no event
individuation rule, FATAL-1) and whose `prevention` column is a set of overlapping
predicates with an "exactly one value" instruction and no precedence order, such that
one of RC's largest defect shapes admits three values at once (FATAL-2). Those two alone
guarantee that four trees publish shares that are not the same measurement, and the three
remaining fatals - a scalar `chain_kind` over a counted chain whose kinds decide ratio
membership, a `fix_chain` link with no correctness filter, and no home for a subagent
authored claim in the pin's most load-bearing field - move integers on the compounding
ratio and the inherited share specifically, which are the two numbers the exercise exists
to compare. **The smallest change that would fix it is three sentences and no new
fields:** one defining an event, one imposing a total precedence order over `prevention`
values, and one making `chain_kind` a per-link list with the ratio counting any non
`SAME-ARTIFACT` link. Add the two one-line clauses for FATAL-4 (a link counts only if the
refutation of the remedy was correct) and FATAL-5 (an in-session agent report is FRESH
unless it was written durably before being acted on), and v1.3 would be comparable to
within the noise the ten MATERIAL findings represent - which is real but bounded, and
which RC would rather report than resolve silently, exactly as LW asked.
