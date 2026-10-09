# Back-test of RC's own Q4 recommendation - the pre-dispatch re-grounding gate

Consolidated evidence file, 2026-09-12. Supersedes the two scratch reports
`docs/_scratch_backtest_A.md` (historical back-test, "report A") and
`docs/_scratch_fparm_B.md` (false-positive and cost arm, "report B").

**Provenance convention used throughout.** A figure is marked (A) if it comes from
report A, (B) if it comes from report B, and (THIS FILE) if it was derived while
assembling this file. Nothing here is inherited from the published recommendation
without being marked INHERITED.

---

## 1. What was tested

`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md` section 3 Q4 recommends a
**pre-dispatch re-grounding gate**: before any filed row, directive, hand-off or slice
brief is acted on, every mechanically resolvable claim it carries is resolved against
HEAD, and **dispatch is refused** until each one resolves or is marked historical.

Five resolvers, as published (INHERITED, quoted in substance from that section):

1. **R1** - every `file:line` citation resolves, and the prose claim at that line still
   matches.
2. **R2** - every named symbol, function and module exists.
3. **R3** - every quoted count is re-derived at run time; a figure inherited from prose
   is refused unless labelled inherited.
4. **R4** - every work-item id the row names is checked for a superseding closure
   recorded since the row was filed.
5. **R5** - every instrument the row names as existing is confirmed to exist.

The published section makes three claims about this gate: that it reaches 52 of 173
refutation events (30.1 percent), that it covers the **most expensive** class, and that
every mechanical component "already exists in this tree".

Two independent arms tested it.

- **Arm A, historical back-test.** Grade each rediscovery instance the section
  enumerates against the tree as it stood at the pick-up moment, resolver by resolver:
  would any of the five have fired? This is the arm LL's OPS-87 criterion 3 asks for.
- **Arm B, false-positive and cost arm.** Implement the five resolvers over a seeded
  random sample of current RM-bearing rows and measure the refusal rate, then hand-grade
  every refusal as genuinely stale or benign.

---

## 2. Arm A - the historical back-test

### 2.1 Table

Reproduced from report A. Pick-up moment is approximated as the parent of the shipping
commit (A, and see LIMITS).

| # | Instance (published wording, abbreviated) | Resolver that fires | Verdict |
|---|---|---|---|
| A | Row worked whose sibling row in the SAME file refused it by name, 28 days | NONE | **MISSED** |
| B | Relayed inbound finding already fixed at an ancestor commit | R3 | **CAUGHT** |
| C | Pre-flight triage killed 5 of 5 directive claims | R2 | **CAUGHT** |
| D | Hand-off FALLBACK named two rows shipped 3 days earlier | R4 | **CAUGHT** |
| E | Row two-thirds stale on arrival | R3, literal reading only | **PARTIAL** |
| F | Row posed as open a question already answered in code | NONE | **MISSED** |
| G | Proposed disposal was what a sibling row had just stopped doing | NONE | **MISSED** |
| H | (never enumerated in the source) | - | **UNGRADEABLE** |
| I | (never enumerated in the source) | - | **UNGRADEABLE** |

### 2.2 Totals

All from report A:

- Instances the published text claims: **9** ("at least nine").
- Instances it actually enumerates: **7**.
- **LOCATED with primary evidence: 7 of 7 enumerated.**
- **CAUGHT: 3** (B, C, D).
- **MISSED: 3** (A, F, G).
- **PARTIAL: 1** (E).
- **UNGRADEABLE: 2** (the two never enumerated).

Catch rate over the gradeable set: **3 of 7**, or 3.5 of 7 counting PARTIAL at half (A).

### 2.3 The detail that most damages the recommendation

Instance A is the published section's **own lead example**, presented first and at
greatest length as the archetype of the highest-cost class, and it is a clean miss (A).
Report A resolved both of its citations against the record as it stood and found them
CORRECT, its symbols present, its ids carrying no superseding closure and its
instruments present. The gate returns GREEN and dispatch proceeds into the rediscovery.

---

## 3. Arm B - the false-positive and cost arm

### 3.1 Sample and method

Report B implemented the five resolvers as a scratchpad script and ran them over a
uniform random sample without replacement, `random.seed(20260912)`, drawn from the
**326 RM-bearing bullets** in `BACKLOG.md` (250) and `ROADMAP.md` (76) (B). Sample size
20. Positive controls were run first: the resolver correctly caught fabricated needles in
both hard classes (`FILE_MISSING`, `PAST_EOF`) and in both symbol directions, so the
zero columns below are a measurement and not a broken pattern (B).

### 3.2 Headline

All from report B:

- **REFUSED: 18 of 20 rows (90 percent).**
- **GENUINELY STALE: 0 of 20 (0 percent).**
- **BENIGN false positives: ~91 failure instances across 11 distinct mechanisms.**
- **R1 hard failures (full `path:N` citations): 0 of 44 in the sample.**

### 3.3 Refusal attributable per resolver

| Gate configuration | Rows refused | Rate |
|---|---|---|
| All five resolvers (as specified) | 18/20 | **90 pct** |
| R4 alone (RM-id superseding closure) | 17/20 | 85 pct |
| R3 alone (named modules) | 12/20 | 60 pct |
| R2 alone (bare `:N` citations) | 6/20 | 30 pct |
| R5 alone (named instruments) | 3/20 | 15 pct |
| R1 plus soft grades (MOVED/ABSENT count as fail) | 5/20 | 25 pct |
| **R1 alone, hard only (FILE_MISSING / PAST_EOF)** | **0/20** | **0 pct** |

(B. Resolver numbering in report B's own table is its implementation ordering; the rows
above are restated against the published R1-R5 numbering.)

### 3.4 The eleven benign mechanisms

Each verified by report B against HEAD:

1. **Port numbers are syntactically identical to bare line citations** - 7 instances
   (`:2999`, `:8860` x3, `:8888`, `:8890`, `:8895`); 67 port occurrences across the two
   docs. No regex separates `:8860` the port from `:8860` the line.
2. **Directory prefixes read as missing files** - ~20 instances; all 17 probed exist,
   14 tracked.
3. **HTTP route paths read as file paths** - 6 (`/ehp`, `/rank-tank`, `/rank-bruiser`,
   `/api/lcu-cmd`, `/lcu-cmd-result`, `/health`).
4. **`schtasks` CLI flags read as file paths** - 5 (`/TR`, `/TN`, `/F`, `/Create`,
   `/Run`), in a row that is ABOUT schtasks command lines.
5. **`module/path.symbol` dotted form** - 3; both halves resolve, only the
   concatenation fails.
6. **Commit SHAs read as symbols** - 3, all confirmed `commit` by `git cat-file -t`.
7. **Memory filenames, deliberately out-of-tree** - 2; memory files live outside the
   repo by design.
8. **Gitignored runtime artifacts** - 5; one of them is an ORPHAN the row explicitly
   tells a reader to go look for, so demanding it exist inverts the row's meaning.
9. **External third-party names** - 9, in a row about an external wiki. These names
   MUST NOT exist in RC.
10. **Tokenizer debris** - 6 prose fragments, not claims.
11. **RM-id closure false positives** - **26 of 30 ids flagged** (B). Verified case: a
    row flagged CLOSURE_FOUND is genuinely OPEN; the marker fires on a LEDGER line whose
    `DONE` belongs to a different work item. This cannot be fixed by tightening the
    marker list, because RC rows recite sibling closures **by design** and that recital
    is the row's value.

### 3.5 The two most damaging sub-results

Both from report B.

**Refusal correlates with citation DENSITY, not with staleness.** The two survivors are
the two rows whose bodies were relocated verbatim to a history document, so they carry
almost no resolvable claim. **The gate passes exactly the rows that say the least** - an
inverted incentive in which the cheapest way to get dispatched is to strip evidence out
of a row. The most-refused row in the sample (22 failures) was filed this week by a
verify-then-file slice and is the most carefully verified row present.

**A correct row can be refused for being accurate about an absence.** Two sampled rows
were graded ABSENT while being verbatim correct. In one, the row's claim is that a file
**hand-rolls** a lookup INSTEAD of calling a named function; the cited line is exactly
right and the token is absent **because the row says it is absent**. A content-aware
resolver therefore does not rescue the gate - it adds a new false-positive class.

### 3.6 Citation census - a decaying figure, correct at two moments

| Figure | Published (INHERITED) | Report B, re-derived | Delta |
|---|---|---|---|
| TOTAL citations | 3242 | **3227** | -15 |
| CONFIRMED | 812 | **808** | -4 |
| MOVED | 878 | **876** | -2 |
| ABSENT | 293 | **291** | -2 |
| UNCHECKED | 1196 | **1189** | -7 |
| hard failures pinned by guard | 63 | **63** | **0** |
| hard failures as pct of guarded | 1.9 pct | **1.95 pct** | +0.05 |

**Both columns are correct at their own moment.** Three commits landed between the
published census and report B's run, churning `WAKEUP_NOTES.md` (143 lines), `ROADMAP.md`,
`docs/LEDGER.md`, `BACKLOG.md` and others (verified by the orchestrating session, not by
A or B). The load-bearing figure - 63 hard failures - **reproduced EXACTLY**.

**The lesson is not that either figure is wrong. It is that a census figure recited in
prose without a tree state is a decaying claim.** Every volume figure moved downward
within days; only the guarded one held.

### 3.7 Scope note: hard rot inside the dispatch corpus

Report B's re-derivation, which the published text does not carry:

| Doc | CONFIRMED | MOVED | ABSENT | UNCHECKED | HARD BROKEN | total |
|---|---|---|---|---|---|---|
| BACKLOG.md | 300 | 245 | 131 | 165 | **9** | 850 |
| ROADMAP.md | 12 | 19 | 9 | 1 | **0** | 41 |
| **both** | 312 | 264 | 140 | 166 | **9** | **891** |

**Within the dispatch corpus specifically, hard rot is 9 of 891 - 1.0 percent, half the
repo-wide rate** (B). Three distinct paths across four rows. That is the entire hard-rot
surface a dispatch gate would be protecting a session from.

---

## 4. The structural finding - a presence check cannot see an absence

This is the single result the two arms agree on from opposite directions, and it is the
one this file most wants carried forward.

**Every one of the five resolvers is a PRESENCE check over tokens the row NAMES. The
defect class the recommendation targets is an ABSENCE.**

From arm A, each verified against the historical record (A):

- **F**'s row never names the module that answers its question. `grep -c` for that module
  over the row returns **0**. R1, R2 and R5 can only check tokens the row carries.
- **G**'s row never names the sibling id that contradicts it - the contradicting line is
  the line immediately above it in the same file, and adjacency is not a resolver input.
- **A**'s row never names either of the two ids that refuse it.
- **E**'s row asserts that something is **missing** which had already been added.

In every one of those four the citations resolve, the symbols exist, the ids carry no
superseding closure and the instruments are present. **The gate returns GREEN and
dispatch proceeds into the rediscovery.**

From arm B, the same property seen from the cost side: because the resolvers can only
interrogate what a row names, **a row that names more is refused more**, which is why
refusal tracks citation density rather than staleness.

A stale row does not name the id that kills it. That is what makes it stale.

---

## 5. What SURVIVES the test

Three things survive, and they are worth keeping.

### 5.1 R2 - symbol existence

**SURVIVES as specified, narrowed to symbols.** Arm A instance C is a pure existence
predicate over one token, with no judgement in it: a directive proposed building on a
class that did not exist anywhere in the tree, and a single `git grep` returns empty (A).
That is the cleanest catch in the set.

**The caveat arm B attaches:** R2 as measured over *named modules and paths* is the
60-percent refuser (mechanisms 2, 3, 4, 8, 9, 10 above). The surviving half is symbol
existence in code, not path existence in prose.

### 5.2 R4 - disposition drift, and RC has ALREADY SHIPPED the parser

**SURVIVES, and its mechanizability is PROVEN rather than argued.** Arm A instance D is
a status-word parse with a binding rule (A), and **RC subsequently built exactly that
parser**.

**Verified THIS FILE, not inherited:** `tests/test_roadmap_backlog_disposition_drift.py`
exists on disk and is tracked (`git ls-files` returns the path). Its docstring names
`RM-387` and `RM-388` among the four rows it was built from, which are the same two rows
arm A grades as instance D. A resolver that has since been implemented and shipped is not
a hypothesis.

**Two caveats, both load-bearing:**

- **The catch depends on which instrument the resolver reads.** At the pick-up moment
  `ROADMAP.md` graded both rows `OPEN` (A). A resolver consulting ROADMAP returns CLEAN
  and passes the stale hand-off through. The catch requires reading BACKLOG or LEDGER -
  which is the instrument the burned session did not read.
- **The published claim that every mechanical component "already exists in this tree"
  OVERSTATES the R4 half.** Report A ran `tools/rm_id_registry.py`: it resolves
  **allocation and collisions**, not disposition. Asked about a shipped id it answers
  "the id is free", which is not a disposition answer at all. The disposition instrument
  was born from instance D rather than existing before it.
- **And R4 as a refusal is separately refuted by arm B:** 26 of 30 sampled ids
  false-positive (B), because the closure marker lands on the right line for the wrong
  work item.

So: R4's **predicate** survives and is shipped. R4 as a **dispatch refusal** does not.

### 5.3 R3's label-inherited-figures clause, as a WARN

**SURVIVES only in its narrow second clause and only as a warning.** "A figure inherited
from prose is refused unless labelled inherited" is the clause that fires on arm A
instance B (A) - a relayed inbound census where none of the ten figures was labelled
inherited and none was derivable from this tree.

**What does not survive is the first clause, "every quoted count is re-derived at run
time".** Report B counted **169 numeric literals** in the non-backticked prose of 20 rows
and found no single re-derivation procedure covers them: they are a mix of source-derived
counts, historical BEFORE censuses, third-party version strings, arithmetic intermediates
and measured latencies. Re-deriving a BEFORE census against HEAD and refusing on the
delta **refuses the row for being correct**. The extreme case in the sample is a row
whose entire purpose is to record a stale relayed census so a future session does not act
on it; it carries 45 numeric literals, every one deliberately not current (B).

Section 3.6 of this file is the same phenomenon in RC's own published prose, which is why
the clause is worth keeping as a WARN: an unlabelled inherited figure is a real smell.
Refusing on it is not.

---

## 6. What is MEASURED-REFUTED

Recorded here explicitly so it is not re-pitched.

### 6.1 The five-resolver gate as a dispatch REFUSAL gate - REFUTED

Measured refusal 18 of 20 (90 percent) with **0 true findings** (B). Precision zero in
the sample. A gate with zero measured precision is a stop, not a gate. RC's own citation
guard docstring already predicts the consequence: a control that refuses too often is
bypassed or deleted, and a documented control that provably does nothing is strictly
worse than no control.

The failure is not a tuning problem. It is a **category problem**: four of the five
resolvers ask prose-judgement questions wearing a resolver's clothes. R2-on-paths cannot
separate a directory, a route, a CLI flag, an external wiki name and a gitignored runtime
artifact from a missing file. The bare-`:N` form cannot separate a port from a line
number. R4 cannot separate this row's closure from a sibling's. R5 is R2 restricted.
R3-on-counts has no procedure at all.

### 6.2 R1 full-citation resolution as a dispatch BLOCKER - REFUTED

R1's hard half is the only mechanically sound resolver in the set, and it has **nothing
left to catch**: 0 failures in 44 sampled citations, 9 in 891 corpus-wide (1.0 percent),
across three distinct paths (B). The instrument already exists as `tools/citation_audit.py`
and the 63 repo-wide hard failures are already pinned by a guard.

R1's **prose half** ("the claim at that line still matches") was never mechanical. Report
A records that `tools/citation_audit.py` says so in its own source: it calls a MOVED or
ABSENT row a hint to check by hand, states that MOVED and ABSENT are upper bounds and
neither number is exact, and keeps them out of the budget guard because a guard built on
a heuristic goes red on a prose reword and then gets disabled (A). On arm A's sample R1
fired on nothing: every citation resolved was CORRECT.

### 6.3 R5 - REFUTED

R5 is R2 restricted to `tests/*` and `tools/*` tokens. It refused 3 of 20 rows on its own
(B) and caught nothing in either arm. It has no independent content.

---

## 7. The narrowing the data supports

Exactly one, and it is small. It is a **different artifact** from the one recommended.

**A pre-dispatch WARNING that prints the row's existing `citation_audit` hard-failure
rows, and nothing else.**

- **Scope: full `path.ext:N` citations only**, hard classes only (FILE_MISSING,
  PAST_EOF).
- **Predicted firing rate: 4 of 326 rows, 1.2 percent** (B, projected from 9 hard
  failures across 4 rows in the 891-citation dispatch corpus).
- **WARN, do not refuse.** With 0 true findings in 20 rows, the expected value of a
  refusal is negative even at 1.2 percent: the cost of a wrong refusal is a bypass habit,
  which is larger than the cost of dispatching on a row whose one stale citation the
  warning already printed.
- **No new instrument.** Reuse `tools/citation_audit.py --json`, filter to the row's
  `doc_line`, print the hard rows, exit 0 always.
- **Explicitly excluded, each with a measured reason:** bare `:N` (ports), named
  modules and paths (six distinct benign classes), named symbols (SHAs, out-of-tree
  memory filenames, external names), RM-id closure (26 of 30 false), quoted counts (no
  procedure exists).

**One thing worth doing that is NOT a gate:** fix the nine. Three distinct paths across
four BACKLOG rows (B). That takes the dispatch corpus's hard-rot rate to zero and costs
less than specifying the gate did.

**And one thing the presence/absence finding implies:** whatever is eventually built for
the rediscovery class must be able to surface a row the brief does **not** name. Arm A's
three misses all need that property and none of the five resolvers has it. This file does
not propose a mechanism for it and does not know of one.

---

## 8. LIMITS - what this test could not see

1. **Arm B's sample is 20 of 326 rows, one tree, one day.** Every rate in section 3 is a
   sample rate with a sample of 20. A different seed lands on different rows.
2. **Arm A's sample is 7, not 9.** Two of the nine instances the published text claims
   are never enumerated in it, so they cannot be located, reconstructed or graded. They
   may be the two the gate catches best or the two it misses worst.
3. **Arm A's grading is COUNTERFACTUAL.** No integrated gate exists; report A ran each
   predicate by hand with `git grep`, `git show` and `sed` against historical blobs. A
   real implementation has parse and false-positive behaviour neither arm can model - in
   particular R4 needs a row-to-id binding rule, and RC's shipped disposition parser says
   in its own docstring that the binding rule is the whole difficulty and that a naive
   per-line regex is wrong in both directions.
4. **The pick-up moment is approximated** as the parent of the shipping commit. The real
   moment a session read a stale row may be several commits earlier. For the MISSED
   verdicts this is harmless; for the CAUGHT ones it could only help.
5. **The dispatch artifact does not exist on disk for arm A's instances B, C and D.** A
   relayed note, a loop directive and a hand-off prompt are not tracked files; report A
   graded the resolvers against the ledger's account of what those artifacts claimed.
6. **Arm A graded "would a resolver fire", not "would the cost have been avoided".**
   Instance B shows the gap: the gate fires, and the work it then demands is the same
   verification the session actually performed. A firing gate is not automatically a
   saved session.
7. **A 0-genuinely-stale result on CURRENT rows does not prove past rows were clean.**
   Arm B sampled `BACKLOG.md` and `ROADMAP.md` as they stand at one HEAD. Arm A found
   real staleness in the same two files weeks earlier - and every one of those instances
   has since been repaired, which is exactly why the current sample is clean. The two
   arms are measuring different populations at different times, and the correct reading
   is "the gate refuses 90 percent of today's rows to catch a defect class today's rows
   do not exhibit", not "these rows were never stale".
8. **Arm B's corpus is not all open work.** 6 of the 20 sampled bodies are
   shipped or closed records retained as history, and one is an anti-row telling a
   future session NOT to act. No mechanical test tried distinguished them from open rows
   (B). A real gate would refuse those too.

---

## 9. The repair this session commissioned was itself refuted, and reverted

Arm B reported nine hard-broken citations in the dispatch corpus, 9 of 891, and called
them "the ENTIRE hard-rot surface the gate would be protecting a dispatched session
from". A repair pass was commissioned to take that to zero. **The repair was wrong, the
repo's own guard caught it, and it has been reverted in full.** The sequence is recorded
here because it is a cleaner result than the one that was expected.

**The nine were never rot.** All nine are DELIBERATELY BASELINED in
`tests/test_citation_drift_guard_rm171.py` under `_KNOWN_BROKEN`, each with a written
reason and a classification of HISTORICAL or DELETED. The baseline's own comments draw
the exact distinction that matters: a citation to a deleted file is left in place when
the prose is a point-in-time record, and is CORRECTED INSTEAD when the deletion makes
the prose materially false. Two prior cases are named there as having been corrected
rather than baselined.

**How the repair failed.** It converted each `path:N` citation to `path LN`, which is
invisible to the auditor's `path:<N>` regex. That does not pay the debt, it evades the
parser - and it defeats the guard's shrink-with-the-debt design. The guard failed with
"These baseline entries are NO LONGER broken. Delete them from `_KNOWN_BROKEN` so the
budget shrinks with the debt", naming all seven distinct entries (THIS FILE, measured).
`python -m pytest tests/test_citation_drift_guard_rm171.py` red before revert, green
after.

**One true positive survived the revert and was kept.** One row asserted in the PRESENT
TENSE that this repository HAS an edge-trigger mechanism, citing
`web/js/panels/spike_cue.js:45`. Verified independently for this file: the path is
absent from `git ls-files`, it was deleted in `1a401b4b2` ("remove Riot-banned
surfaces"), and `git grep` over `web/` for its two functions returns nothing. What
survives is thinner than the row claims - a level EQUALITY test at `web/js/main.js:1111`
and `core/event_callouts.py:396`, the latter re-pointed from a stale `:355`. The prose
was corrected; the citation was left in place, because it is baselined and the record is
the point.

**Then the correction defected the same way, in the same run.** Restating the citation
in bare-filename form inside the corrected prose scored as a NET-NEW break, because the
guard keys on raw citation text and treats the two spellings as separate entries. Caught
by the same guard, on the next run, and fixed. **That is a fix-of-a-fix, live, inside
the session measuring fix-of-a-fix rates.**

**What this does to the recommendation.** It weakens it further rather than rescuing it.
The mechanical citation surface here is not unguarded rot - it is an actively maintained
ledger with reasons attached, and a dispatch-time gate on top of it buys nothing that
the existing commit-time guard does not already buy. The one defect worth catching was
PROSE asserting a present-tense capability that no longer exists, and **no citation
resolver reads prose**. That is the same presence-versus-absence wall as section 5.
