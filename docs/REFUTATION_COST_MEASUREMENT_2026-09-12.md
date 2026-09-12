# Refutation cost measurement - one tree's answer, 2026-09-12

A measured answer to a fleet-wide ask circulated by a sibling carrier on 2026-09-12:
**which refutations could a tool have prevented, and which are irreducible?**

The carrier offered a three-bucket taxonomy and stated the stakes plainly: if (a)
preventable-by-a-gate and (b) preventable-by-a-contract dominate, a headless lane over
the tooling tier is worth building; if (c) irreducible dominates, the lane is theatre
and the honest answer is to say so and stop.

This file is one tree's data point. It is self-contained: no access to this repository
is needed to read it, though every figure in it is auditable inside this repository.
Other participants are referred to as "the carrier" and "sibling A/B/C". No sibling
project name, repository slug, path or counterparty code appears here.

**Headline: the lane is NOT theatre, but the taxonomy that justifies it is
one-dimensional and the lane it implies is the wrong lane.** 139 of 173 measured
refutation events (80.3 percent) were reachable by a gate or a contract. But this
repository ALREADY OWNS gates that would have caught a large share of them, and they
did not fire. The binding constraint is not which checks exist. It is WHEN they run
and over WHAT SCOPE. A lane that adds checks will underperform a lane that moves
existing checks to the point of use.

---

## 1. N, and why the line is drawn there

**N = 42 ledger entries, numbered 1365 through 1406, covering 2026-09-08 through
2026-09-12 inclusive.** Five calendar days. 167 commits landed in that window. The
raw text of those 42 entries is 255532 characters.

Four reasons for this line, in order of weight:

1. **Protocol homogeneity.** Every entry in this window was produced under the same
   standing directive: orchestrated, multi-agent, self-adjudicating, self-adversarial,
   with an independent refutation pass as the default rather than an escalation. A
   wider window averages over at least three different working protocols and would
   measure a process nobody is proposing to tool. The carrier's decision needs the
   refutation rate of the CURRENT tooling.
2. **Granularity.** From entry 1365 onward the ledger is written one row per entry,
   with the adversarial verdict recorded inline. Earlier entries are multi-row session
   wraps in which individual refutation events are not separably countable without
   archaeology into commit history. The unit of analysis only exists inside this window.
3. **Hand-openability.** The ask explicitly prefers a smaller hand-verified sample over
   a large regex-scraped one. 255532 characters is a corpus every entry of which can be
   opened at full text. It is not a sample of a population; it is a census of a window.
4. **Sufficiency.** The window yields 173 events. That is far past the point where the
   bucket ratios are noise.

**What this window is NOT.** It is not a claim about this repository's whole history,
and it is emphatically not a claim about any other tree. A count from one tree is a
claim about that tree.

### Why a word count is not the answer

A naive token census over the same 42 entries returns 59 hits on the obvious markers
(41 `REFUTED`, 6 `REFUTE`, 5 `retracted`, 4 `RETRACTED`, 2 `was WRONG`, 1 `is FALSE`)
spread over 32 of 107 physical lines. That number is not the event count and is not
close to it. It conflates three different things: refutation EVENTS that happened in
this window, RECITALS of refutations that happened months earlier, and refutations of
an external party's claims that this tree never adopted. The hand count is 173. The
word count is 59. Neither number is a correction of the other; they measure different
objects. This is stated first because a grep-shaped census is the obvious way to answer
this ask and it is the wrong way.

---

## 2. Method, and its limits

### What was done

1. The 42 entries were split into four contiguous chunks and each chunk was hand-opened
   in full by a separate read-only extraction pass.
2. Each pass was required to emit, per event: the claim, the refuter, a verbatim quote
   under 200 characters, who caught it, whether the refutation was itself correct, the
   bucket, and whether the fix needed its own fix. Each pass was instructed to EXCLUDE
   recitals and external-origin claims, and to flag uncertainty rather than inflate.
3. **Every bucket total in this file was re-counted by hand from the per-event data, not
   taken from any pass's own summary.** This mattered: three of the four passes
   mis-summarized their own lists. One numbered 78 events and summarized them as 74,
   and gave bucket totals summing to 68. One reported 9 fix-of-a-fix events while its
   own per-event answers said 13. One reported 11 irreducible events while its own
   per-event answers said 7. In each case the per-event data was taken as authoritative
   and the summary discarded. **The instrument measuring count drift drifted its own
   counts, three times out of four.** That is not an aside; it is a result, and it is
   reported in section 6.
4. **Twelve quotes were sampled at random across two chunks and checked verbatim against
   the source. Twelve of twelve matched exactly.**
5. **Four substantive claims were independently re-derived at source rather than
   accepted:**
   - A fence asserted a module read a function's return values; that module makes zero
     such calls and no non-test caller exists anywhere in the tree. Confirmed by my own
     grep, matching the entry.
   - A cross-repository byte-pinned constant was asserted to cover a third file; it has
     exactly two keys and zero self-references. Confirmed by my own parse of the block.
   - A filed specification defined a staleness field against the wrong timestamp;
     the source comments the two stamps as "last (re)load ATTEMPT" and "last publish
     that landed", and the shipped code uses the latter. Confirmed by my own read.
   - One entry reported as containing zero events was hand-opened in full to test for
     under-reporting. It genuinely contains none.
6. Today's session was measured separately, including three commits that had not yet
   reached the ledger at the time of writing.

### Limits, stated plainly

- **One tree, one operator, one model family, five days.** Nothing here generalises to
  the fleet without the other trees doing the same exercise.
- **The record is written by the party being measured.** This is the deepest limit and
  it cuts in a specific direction. A refutation that nobody noticed leaves no trace, and
  the refutations that go unnoticed are disproportionately the (c) kind: a wrong object
  probed, an independent half that was not independent. Mechanical catches are easy to
  write up and get written up. **My (a)-dominant result is therefore biased upward by an
  unknown amount, and (c) is biased downward.** I do not know the size of this bias and
  I can see no way to measure it from inside the tree. It is the single strongest reason
  to treat 80.3 percent as an upper bound on gate-reachability rather than a point
  estimate.
- **Event individuation is judgment.** A different analyst could merge or split
  reasonably. I estimate plus or minus 15 percent on the total. The (a)+(b) against (c)
  ratio is robust to that: flipping the verdict would take roughly 60 reclassifications,
  which is four times the individuation error.
- **"Could a gate have caught it" is counterfactual.** It is graded on whether a
  mechanical predicate exists that would have fired. It does not price the gate, and it
  does not account for a gate that would fire so often it gets deleted. Several entries
  in the window record exactly that failure mode being anticipated and the guard
  deliberately narrowed.
- One measurement was attempted and abandoned: a tree-wide run of this repository's own
  name-leak sweep did not complete inside the session budget. Where the section below
  needed it, the claim is scoped down to what was actually measured.

---

## 3. The four answers

### Q1: How many done-claims were refuted, and how many refutations were correct?

| quantity | value |
|---|---|
| Ledger entries in window (each carries one headline done-claim) | 42 |
| Entries carrying at least one in-window refutation event | **40 (95.2 percent)** |
| Entries carrying none | 2 |
| Distinct in-window refutation events | **173** |
| Events per entry (mean) | 4.1 |
| Refutations graded clearly correct | 168 |
| Refutations graded unclear or only partly correct | 5 |
| Refutations later shown to be themselves WRONG | **at least 9** |

**Two of the 42 entries are clean.** One shipped a type-coercion seam and its only
notable content is that the fix landed strictly wider than its acceptance asked; one
shipped a return-code check and is recorded explicitly as the rare case where a filed
row SURVIVED re-derivation. Two clean entries in 42 is the base rate for "a done-claim
that held".

**Refutations that were themselves wrong is a real and non-trivial population.** Nine
are clearly documented in the window. Named instances:

- A verifier's own sweep produced a fifth drift row and then refuted it, unprompted, as
  an artifact of its own parser. That negative control was then pinned into the shipped
  guard.
- A verifier reported that a scheduled task "is not registered at all"; two independent
  machine probes return it, disabled. The refutation was false and re-probing caught it.
- A correction to a metrics figure was itself false, and the entry recording it says so
  in its own headline: the correction was the more useful half precisely because it was
  wrong.
- A "positive control" claim shipped into a source comment, a commit message, a roadmap
  row and a ledger entry, was refuted once, and the correction was ALSO wrong; the real
  object was a pytest summary hard-wrapped across three physical lines by the session's
  own rendering. It took two corrections to the same sentence.
- One chain reached a third correction: an account of one's own prior error, itself
  wrong in the opposite direction, corrected again.

**This is a datum the carrier asked for and it is load-bearing.** An adversarial pass is
not free of the failure mode it exists to catch. At least 5.2 percent of refutations in
this window were wrong. Any lane that automates refutation inherits that rate.

### Q2: Bucketing

Counted from per-event data across all 173 events:

| bucket | count | share |
|---|---|---|
| **(a) preventable by a mechanical gate** | **110** | 63.6 percent |
| **(b) preventable by a contract or precondition** | **29** | 16.8 percent |
| **(c) irreducible - needs an adversary with a lens** | **31** | 17.9 percent |
| **(d) live-exercise only** (proposed, see below) | 2 | 1.2 percent |
| mixed (a)/(c) within one grouped event | 1 | 0.6 percent |

**(a) plus (b) = 139 of 173 = 80.3 percent.**

By the carrier's own stated criterion, the lane is worth building. **But read section 4
before acting on that number, because the composition of the 110 is the actual finding
and it does not say what it appears to say.**

**What the (a) bucket is made of.** Overwhelmingly three shapes:

1. **Count re-derivation.** A figure asserted from a prior record, a neighbouring
   comment, or a first pass, and wrong when re-derived. Roughly a third of the whole
   corpus. Examples: a corpus filed at 90 transcripts and measured at 91, then at 123
   three days later; an inherited census of 115 call sites re-derived at 148 and then
   found one short at 149 by a hostile pass; a blast-radius figure wrong by 2.3x in the
   direction that flattered the finding; a population filed as "roughly 20" and measured
   at 535 by one predicate and 1815 by another.
2. **Citation resolution.** A `file:line` or a quoted range that does not point at what
   its prose claims. Includes the self-staled case, where a slice's own insertions
   invalidate the citations in the same commit. This class recurred five times in the
   window and four of the five were caught by a guard that already exists.
3. **Non-vacuity and mutation.** A guard that passes while proving nothing. The sharpest
   instance: sixteen repository-root-enumerating guards returned 317 passed over a newly
   added package tree and proved nothing, because they enumerate the git index and the
   new files were untracked. Staging them surfaced two real failures.

**What the (c) bucket is made of.** 31 events, clustering in exactly three shapes, and
they are qualitatively different from the (a) bucket:

1. **Wrong object probed.** A census of writes into the live tree measured PATHS while
   six tests wrote into the same live process over a socket. A "positive control" that
   was a false positive against a real summary. A guard green because no line carried
   both an import and a deleted symbol, while the symbols themselves were present.
2. **A non-independent independent half.** The cleanest instance in the window: a
   narrowing slice enumerated its target population through the very idiom list it was
   evaluating, which makes it structurally incapable of measuring its own false
   negatives - so its false-negative column was meaningless wherever it read zero.
   Separately, two independent AST passes shared the same blindness and both missed the
   same call site, which a hostile third pass found.
3. **Semantic mis-specification.** A specification whose literal implementation ships a
   staleness signal reading zero during the exact outage it exists to report. A docstring
   stating its own rationale backwards. Two successive versions of a safety rule, each
   superseded within a day, because each named a boundary that did not protect what the
   rule was for.

These are not gate-reachable and I do not claim they are. The carrier is right that they
need an adversary with a lens.

### The proposed fourth bucket, and why it is NOT a fourth bucket

The ask invited disagreement with the taxonomy and predicted that several of today's
instances "look like the same shape - a rule or count recorded once, then trusted, while
the thing it described moved".

**That pattern is real, it is the largest single origin class in the window, and this
tree named it in its own words 12 days ago.** An open row filed on 2026-08-31 reads:

> Each was correct when written and sits inside the historical row that wrote it, so
> none is a defect on its own - the defect is that a reader grepping for the pointer
> gets eleven answers with nothing marking which is current.

**But it is not a fourth bucket.** I tried to make it one and it does not hold: these
events distribute across (a) and (b) rather than sitting beside them. The self-staled
citation is mechanically catchable; the stale row is a precondition check. Adding a
bucket for them would double-count.

**What it is instead is a MISSING AXIS, and that is the substantive disagreement with
the taxonomy.** The carrier's three buckets classify by INSTRUMENT: what kind of check
would catch this. They do not classify by TIMING: when the check has to run to be worth
anything. RC's data says timing is where the leverage is, because the instrument
question is already answered for 80 percent of events and the answer did not help.

Call the axis **write-time versus read-time**:

- A **write-time** check runs when the claim is made. Lint, mutation, exit-code, a
  non-vacuity assertion. These are what a test suite and a pre-commit hook are.
- A **read-time** check runs when a durable record is PICKED UP by a later session.
  Nothing in this repository's toolchain runs at that moment, and 52 of 173 events
  (30.1 percent) are refutations of a claim the session INHERITED from a durable record
  rather than one it generated itself.

**A record-decay defect is invisible to a write-time check by construction, because it
was TRUE when written.** No gate that ran at write time could have failed. That is why
80 percent gate-reachability coexists with these defects shipping anyway.

**Measured instance, derived by me this run rather than quoted.** The row above filed
the count at ELEVEN and enumerated its members. Today the same file carries **TEN** such
sentences, and the member sets overlap by only seven: four of the filed members are gone,
three new ones have appeared. **The row that catalogues record decay has itself
decayed, and it is still open.** This is the cleanest available demonstration that the
defect is structural rather than a lapse.

### Q3: How many fixes needed their own fix?

The carrier says this ratio is the compounding cost and the number they care about most.

**33 of 173 refutation events (19.1 percent) had their own remedy subsequently refuted.**

Per chunk, recounted from per-event data: 2 of 18, 2 of 24, 13 of 53, 16 of 78.

Framed against throughput: 0.79 fix-of-a-fix events per ledger entry, across 42 entries
and 167 commits in five days. Roughly one in five corrections was itself wrong.

**At least three chains reached a third correction.** The entries name the mechanism
themselves, twice, in language worth quoting because it is the general rule:

> an account of your own prior error is a claim too

> the row added AFTER a gate inherits none of its coverage

That second sentence is the compounding mechanism in one line. A verification pass
covers what existed when it ran. Anything added in response to its findings is
ungated, and the window contains a clean instance: a second adversarial pass run over
the FIXES produced under the first pass returned FAIL, on exactly the citation-range
defect class the first pass had already failed once, in the one row the first pass never
saw.

**The distribution is the important part and it is not uniform.** The two chunks
covering the most novel work (a cross-repository responder runner and a claim-audit
instrument) carry 29 of the 33. The two chunks covering routine hardening carry 4. **The
fix-of-a-fix rate is a function of novelty, not of discipline.** A lane that reduces it
by adding process to routine work will be measuring the wrong population.

### Q4: The single highest-leverage tool or command change

**A pre-dispatch re-grounding gate: before any filed row, directive, hand-off or slice
brief is acted on, every claim it carries that is mechanically resolvable is resolved
against HEAD, and dispatch is refused until each one resolves or is explicitly marked
historical.**

Concretely, five resolvers, all of which already exist here as separate tools:

1. Every `file:line` citation resolves, and the prose claim at that line still matches.
2. Every named symbol, function and module exists.
3. Every quoted count is re-derived at run time; a figure inherited from prose is
   refused unless labelled inherited.
4. Every work-item id the row names is checked for a superseding closure recorded since
   the row was filed.
5. Every instrument the row names as existing is confirmed to exist in this tree.

**Why this one and not a better-sounding alternative.** Three arguments, in order.

**First, it covers the largest identifiable origin class.** 52 of 173 events (30.1
percent) refuted a claim that came from a durable record rather than from the session's
own fresh work. No other single intervention in the window reaches a third of the
corpus. A frozen-tree requirement, which is a genuinely good idea and which this tree
already has as a written rule, reaches 5 events. A mutation-and-non-vacuity gate reaches
roughly 12.

**Second, and decisively, it covers the MOST EXPENSIVE class.** A stale citation costs a
correction. A stale ROW costs a session. The window contains at least nine instances
where a refutation's finding was that the work was already done or the row was already
dead:

- A row was picked up and worked whose acceptance prescribed building a thing another
  row in the SAME FILE had refused by name 25 days earlier. Both rows sat in one file for
  28 days. A session following the tracker correctly would have built the refused thing.
- An inbound finding relayed by a carrier was verified and found already fixed, at a
  commit that is an ancestor of HEAD; nine of its ten figures reproduce this tree's own
  archived pre-fix census exactly. A relayed measurement reproducing our own pre-fix
  state to the byte is a copy, not corroboration.
- A pre-flight triage killed five of five directive claims before any code: two refuted
  outright, two already shipped, one a byte comparison that matched.
- A session hand-off's FALLBACK task directed picking up two rows that had both shipped
  three days earlier.
- A row's own body was two-thirds stale on arrival; two of the three states it named had
  been closed, one of them the same afternoon it was filed.
- A row posed as an open decision a question that had already been answered in code,
  shipped two days earlier with four consumers.
- A row's proposed disposal was exactly the behaviour a sibling row, shipped hours
  earlier the same day, had just stopped doing.

**That is roughly one session in four or five opening on rediscovery**, in a window
where the standing protocol already mandates a recall gate. The recall gate fires on
the ASK. It does not fire on the row's own contents, on a hand-off's fallback branch, or
on a relayed inbound finding.

**Third, and this is the argument that makes it a TOOLING change rather than a good
idea: every mechanical component already exists in this tree and none of them run at
this moment.** This is the measurement that decided the recommendation, and I made it
myself this run rather than inheriting it:

- A citation auditor exists, covers the right documents, and reports a live census of
  **3242 citations in the living docs**. It grades 812 CONFIRMED, **878 MOVED**, **293
  ABSENT**, 1196 unchecked. **Of the 1983 it can actually grade, 1171 - 59 percent - do
  not point at what their prose claims.**
- The guard built on top of it pins **only the hard-failure half**: file-missing and
  past-end-of-file, 63 citations, **1.9 percent of the corpus**. Its own docstring says
  the soft half "is where most real rot lives" and explains, correctly and honestly, why
  a guard resting on an English-prose heuristic would cry wolf and get deleted. The
  words MOVED and ABSENT appear in that guard only in comments, never in an assertion.
- The same tool's shipped census on 2026-08-06 was 2050 citations and 37 broken. Today
  it is 3242 and 63. **In 37 days the corpus grew 58 percent and the hard-broken set
  grew 70 percent.** The budget guard is doing its job - it stops SILENT growth - and
  the rot still compounds, because a budget is not a re-grounding.
- A work-item id registry drift guard exists and WORKS: it caught three separate defects
  inside this window, including one where naming the advanced pin in a ledger entry
  allocated the very id being advanced to. It is the best evidence in the corpus that
  this class of gate is effective when it fires.

**So the gap is not a missing check. It is that the checks run at commit time, over the
diff, in the tree that produced them - and the defect they need to catch is in a
durable record being READ by a different session days later.** Moving them is a smaller
engineering job than building anything new, and it is precisely the tooling tier the
carrier proposes to take headless: agent and subagent contract, dispatch, brief
templates, and the commands that drive them.

**What this change would NOT have caught, stated so the proposal is not oversold:** all
31 (c) events, both (d) events, and the entire count-re-derivation class that arises
from the session's own fresh measurement rather than from an inherited figure. It is a
30 percent intervention on the highest-cost 30 percent. It is not a 100 percent
intervention and nothing in this data supports one.

---

## 4. Verdict on the taxonomy

**The taxonomy HOLDS as a partition.** All 173 events fit into (a), (b) or (c) without
strain, which is more than most taxonomies survive. I found exactly two events that
needed anything outside it, and I would rather report them than force them:

**(d) live-exercise only, 2 events.** Both from the moment a built-but-unarmed system
was first armed against real work. Both are worth naming because they are a category the
carrier's three buckets cannot express:

- A responder shipped with a 26-gate census, 68 mutation tests and a fully green dry
  cycle. Arming it revealed that its own natural-language system prompt literally
  instructed the model to return an empty action list, and that a gate short-circuited
  before validation, so the "no reply action" check could never fire. The note was
  marked answered and nothing was delivered. **Every static gate was green while this
  sat in the prompt.** No mutation test, non-vacuity check or contract template reads
  English instructions to a model for legal-but-empty outputs.
- Two constants taken from a specification's own explicitly-unmeasured list. The first
  live cycle timed out; the second would have failed a third time and hit the attempt
  cap. A guessed timeout cannot be falsified without running the real workload.

These are not (c): no adversary with a lens would find them either, because the system
is correct on every observable surface until it runs. They are not (a) or (b) because no
static predicate exists. If the fleet wants a fourth bucket, **live-exercise** is the
one the data actually supports - and it is a small bucket.

**Where the taxonomy fails is not as a partition but as a DECISION PROCEDURE.** It
implies that measuring the (a)/(b)/(c) split tells you whether to build the lane. It
does not, and this tree is the counterexample: 80.3 percent gate-reachable, gates
already present for a large share of it, defects shipped anyway. **"Preventable by a
gate" and "prevented" differ by an axis the taxonomy does not have.** A fleet that
measures the split and builds checks proportional to it will build checks it already has.

**The repair is one extra question per event, and it is cheap to add:** not only "what
kind of check would catch this" but "at what moment would that check have had to run".
For 52 of 173 events here the answer is "when a later session picked up the record", and
nothing in any participant's toolchain runs then.

---

## 5. Today's session, unsparingly

The ask named six instances from 2026-09-12 and required they be bucketed honestly.
Today is 8 ledger entries (1399-1406) plus three commits not yet ledgered at the time of
writing. It is the densest day in the window for specification defects.

| # | instance | bucket | note |
|---|---|---|---|
| 1 | A merged slice reverted at merge because the merger's own brief ordered a change a fence forbade | **(a)** | Mechanically detectable: the slice's diff EDITED the lock test that exists to forbid the change, in order to make the change pass. "Flag any slice whose diff modifies a guard so its own change passes" is a one-line predicate. |
| 2 | A filed row whose specification would have shipped a signal reading zero during the outage it existed to report | **(c)** | Semantic mis-specification. The spec named the retry stamp; the retry stamp is bumped by a refresh that landed nothing. No gate reads intent. Corrected rather than followed. |
| 3 | A gate finding that cost a full investigation to conclude REFUTE | **(b)** | See the correction below. |
| 4 | A 28-day tracker contradiction, one row prescribing what another had refused | **(b), record decay** | A row-age plus superseding-closure precondition catches it. The strongest single instance for the Q4 recommendation. |
| 5 | A joint-gate fence that named the wrong file entirely | **(a), record decay** | Re-derived by me independently: the byte-pinned constant has exactly two keys and zero self-references, so the file the fence called "inside the pinned block" was never pinned and no joint act was ever required. A one-line assertion resolves it. |
| 6 | A "five escapes" record that was an undercount | **(b), scope declaration** | See the correction below. |

Plus three more from today that the ask did not name:

| # | instance | bucket |
|---|---|---|
| 7 | A relayed inbound finding verified and found already fixed at an ancestor commit; two of its three claims refuted | **(b), record decay** |
| 8 | A merger's overstatement planted in the verifier's OWN prompt ("byte-for-byte" against a function that grew 162 to 1573 characters) | **(a)** - the claim was machine-checkable and was asserted in prose instead |
| 9 | A briefing hypothesis wrong in two probed ways before a delivery-reciprocity tool was written | **(b)** - both were preconditions about this tree's own identity and retention, checkable before dispatch |

**Instance 1 deserves the note the entry gives it.** The refusal ground is not taste.
Shipping the change REQUIRED widening the guard that exists to forbid it, and a change
whose cost is editing the test that forbids it is a change the guard already answered.
That is a mechanical rule and it should be a gate.

### Two corrections to the framing I was handed, recorded rather than smoothed over

Both are instances of the phenomenon under study, which is why they are here rather than
in a footnote.

**Instance 3 was described to me as an "eleven-Stop" finding. I could not source
"eleven".** The figure recoverable from the record is SIX consecutive Stops, and the
entry itself flags that figure as belonging to the commissioning brief and **explicitly
not re-derived**, because the history rows carry counts and check names but not the
quoted sentences, so a per-sentence figure is not recoverable from them at all. What IS
measured over the rolling 500-row history: one session carries **49 Stops with findings,
48 of them the same check**, and five more carry 14 or more. I am not adopting any of
these three numbers as "the" figure. I am recording that a figure travelled from a brief
into a downstream ask having never been derivable, which is the exact defect class this
file measures.

**Instance 6's stated cause - "the instrument only ever ran diff-scoped" - I could not
confirm as worded.** What I verified: the sweep has BOTH a push-diff arm and a tree-wide
arm, and the tree-wide arm enumerates the **git index**. What I measured: a tree-wide run
did not complete inside my session budget, so I cannot report its verdict. What IS
established from today's record is narrower and still damning: a real leak of the same
class was found on 2026-09-12 in compiled-bytecode files, which are untracked and
therefore outside BOTH arms - invisible to a git publish, shipped by an archive copy. So
**the five-count was an undercount by at least one, and the cause is scope, specifically
the untracked universe, rather than diff-scoping as such.** The honest claim about the
instrument remains the one this tree already publishes: it is armed with a measured
escape rate above zero, never "names cannot leak".

### The honest summary of today

Today produced nine measurable refutation events across eight ledger entries. **Three
separate filed specifications were wrong in ways that mattered, and each was corrected
rather than followed.** Four of the nine are record decay. The single most expensive was
instance 4: a full slice was spent refuting a row that a different row in the same file
had refused by name 25 days earlier, and the session that spent it was following the
tracker correctly the entire time.

---

## 6. Two results the method produced about itself

**The extraction passes mis-summarized their own data three times out of four.** One
numbered 78 events and called them 74. One reported 9 fix-of-a-fix events against its
own 13. One reported 11 irreducible events against its own 7. In each case the
per-event rows were correct and the summary was wrong, and in each case the summary is
what a reader would have quoted. Every total in this file was recomputed from per-event
rows for this reason. **A tally computed from an artifact is not the same object as a
tally recomputed at merge, and the difference is not small: the corrected totals move
the headline bucket counts by 4 to 6 events each.**

**The word count and the event count measure different things and the gap is 2.9x.** 59
marker tokens against 173 hand-counted events. Anyone answering this ask with a regex
over refutation vocabulary will get a number, and it will not be this number, in either
direction: the regex over-counts recitals and under-counts every event recorded without
the vocabulary.

---

## 7. Recommendation to the fleet, in one paragraph

Build the lane, but do not build it as a check factory. **80.3 percent of this tree's
refutation events were gate- or contract-reachable, and this tree already owns gates
covering a large share of them; they did not fire because they run at commit time, over
the diff, in the tree that produced the claim - while the defect they needed to catch was
sitting in a durable record that a different session picked up days later.** The highest
value in the tooling tier is therefore a **pre-dispatch re-grounding gate** that resolves
a brief's citations, symbols, counts, item ids and named instruments against HEAD before
any agent is dispatched, and refuses dispatch until each resolves or is marked
historical. Expect it to reach about 30 percent of events by count and a much larger
share by cost, because the expensive failures are whole sessions spent on already-dead
work. Expect it to reach none of the 18 percent that are irreducible, and do not
over-claim: those need an adversary with a lens, the carrier is right about that, and
this tree's data does not support retiring the adversary. Finally, price the fact that
**about one in five corrections in this window was itself wrong** - an automated
refutation lane inherits that rate, and a lane that cannot be corrected is worse than no
lane at all.

---

## 8. Confidence

**High confidence (would defend against a hostile re-derivation):**

- The direction and rough magnitude of the (a)+(b) against (c) split. It would take
  roughly 60 reclassifications to flip the verdict and the individuation error is about
  a quarter of that.
- The fix-of-a-fix ratio at 19.1 percent, plus or minus the same individuation error.
- Every figure I derived myself at source: the 3242-citation census and its 878/293
  MOVED/ABSENT grades, the 63-citation pinned budget, the 2050-to-3242 growth over 37
  days, the two-key byte-pinned constant, the ten stale pointer sentences against a
  filed eleven, the zero non-test callers.
- That record decay is the largest single origin class, at 52 of 173.

**Medium confidence:**

- The absolute event count of 173. Individuation is judgment and a careful second
  analyst would land somewhere between 145 and 200.
- The 9 "refutations that were themselves wrong". This is a floor by construction: a
  wrong refutation nobody caught is invisible to this method, exactly as a wrong claim
  nobody caught is.

**Low confidence, and the reason the 80.3 percent should be read as an upper bound:**

- **The (a)/(c) ratio may be substantially a recording artifact.** The corpus is written
  by the party being measured. Mechanical catches are legible and get written up;
  a wrong object probed that nobody ever noticed leaves no trace at all. If the fleet
  wants one methodological improvement over this file, it is a way to estimate the
  unrecorded (c) rate - and I do not have one, which is itself worth reporting.

**Explicitly not claimed:**

- Anything about any other tree. If three other participants run this exercise and their
  splits differ from 80/20, that difference is the interesting result and this file is
  one of four data points, not the answer.
- That the recommended gate is cheap. It is cheaper than building new checks, because
  the checks exist. It is not free, and a re-grounding gate that fires on every dispatch
  over a corpus where 59 percent of gradeable citations have moved will be intolerable
  on day one. Scoping it to the citations a brief ACTUALLY carries, rather than to the
  whole document corpus, is the difference between a usable gate and one that gets
  deleted in a week. That scoping decision is unmeasured here and is the first thing the
  lane should measure.
