# SCORER A - 198 rows scored under RC_SCORING_CONVENTION_v1

## Ambiguities I resolved

Every item below is a place where the convention, applied literally, did not
decide the case for me. I name the section, the underdetermination, and the rule
I adopted and then applied uniformly to all 198 rows.

**A1. Section 3.2 vs 3.4 - GATE-ABSENT and GATE-FIRED-CAUGHT can BOTH be
satisfied on the same row, and nothing orders them.** 3.2 requires "no mechanised
instrument in this tree graded the property"; 3.4's BROAD standing check admits
DIRECTED passes, which are not mechanised. So on a row where no mechanised guard
existed and a mandated verifier/adversarial/adjudication pass caught the defect,
both definitions read TRUE, and 3.9's admission rule would then force a two-value
set on a very large share of the corpus - which contradicts 3.9's own statement
that a set of ONE is the expected case. **Resolution: where a standing check
(mechanised OR directed) actually fired and caught the defect, the row takes
GATE-FIRED-CAUGHT ALONE.** GATE-ABSENT is reserved for rows where nothing fired.
This is the single highest-leverage choice I made: it moves a large block of rows
from GATE-ABSENT to GATE-FIRED-CAUGHT without changing the family, but it changes
every per-value number and it is the reason my `sfb` column is heavily populated.

**A2. Section 3.4 - which named passes in this corpus count as STANDING checks.**
The convention says the discriminator is "whether the pass was OWED before the
work started", but the rows do not state whether a rule required each pass. I
pinned a text-level test, applied mechanically: a refuter counts as a standing
check when it is named with a CONTROL role-noun - gate, pre-commit gate,
adversarial gate, verifier, independent verifier, adjudicator, adjudication pass,
audit (cycle audit / wrap ritual / recall gate / stop gate), a named test file or
node id, a named suite or guard run, a mutant suite. A refuter named only as an
ACTOR or an ACT - "me", "the session", "the slice", "the build", "the merger",
"reading X", "re-deriving X", "a census", "a probe", "live operation" - does NOT
count, even where RC plainly has a standing directive that would have mandated it.
I am aware this undercounts GATE-FIRED-CAUGHT relative to what the tree's actual
directives require; the convention's section 2 already declares that count a
FLOOR, and this test is the only version of it a second reader can reproduce from
the row alone.

**A3. Section 3.4 - a NEWLY WRITTEN test arm or a mandated pre-arm dry cycle that
went red.** Not covered: the control did not pre-exist the work. I resolved that a
test arm written under a standing TDD rule, and a named dry cycle owed before
arming, DO count as standing checks firing (MECH), because both have a firing verb
and a pass/fail output owed before the claim could stand. A LIVE run of the system
in ordinary operation (a delivering cycle, an entry that had to be hand-deleted)
does NOT count - it is operation, not a control. This split is thin and I flag it:
chunk1-56 (dry cycle) is GATE-FIRED-CAUGHT while chunk1-57 (delivering cycle) is
GATE-ABSENT on almost identical fact patterns.

**A4. Section 3.5 vs 3.2 - PROXY-MEASURE also satisfies GATE-ABSENT.** Same
structural problem as A1. Resolution: **where PROXY-MEASURE's three conditions are
met, PROXY-MEASURE is recorded and GATE-ABSENT is NOT added**; PROXY-MEASURE is
added ALONGSIDE GATE-FIRED-CAUGHT where a standing check also fired, because that
pair straddles the family boundary and 3.9 explicitly wants straddles visible.
Every two-value set I emit is of that exact shape.

**A5. Section 3.6 - CONTRACT where a standing check ALSO fired.** 3.6 opens with
"No mechanised instrument reaches it", which is silent about directed checks. I
resolved that CONTRACT is assigned only where NO standing check fired; where one
did, GATE-FIRED-CAUGHT records what actually happened and CONTRACT survives only
in the `sfb` column as the strict-reading fallback. Consequence: my CONTRACT count
at SET grain is low, which is exactly the confound the convention's own known
weakness 6 warns about.

**A6. The `sfb` column - the convention does not define the strict-reading
fallback procedure.** 3.4 promises a second column but never says how to derive
it. I derived it by re-running the residual order with GATE-FIRED-CAUGHT deleted
from the value set: PROXY-MEASURE if that value was already in the set, else
CONTRACT if the row names a specific rule/spec/fence, else GATE-ABSENT if the
defect is a discrete checkable datum under 3.8's shape test, else ADVERSARY.

**A7. Section 6.1 / `cu` - "silent on what happened to the remedy" is
underdetermined, because almost every row is silent about the remedy's LATER
fate.** A literal reading makes `cu=Y` on nearly every fix=0 row, which drains the
field of information. Resolution: **cu=Y when the row says nothing at all about a
remedy; cu=N when the row states that a remedy was produced, shipped, corrected
in-commit or deliberately refused, and records no further refutation of it.** I
did not treat "a remedy exists" as proof it stood; I treated it as the record
speaking, which is what 6.1 asks for.

**A8. Section 5.1 - the keying rule versus claims made by an IN-SESSION agent,
adjudicator or directive.** 5.1 pins the commit-state test and says an in-session
agent report is FRESH. I extended that uniformly: a draft sentence, a build's own
report, an adjudication pass's own statement, an executing slice's own
enumeration, and a directive consumed in-session are all FRESH. A spec, docstring,
BACKLOG/ROADMAP/LEDGER row, prior session's census, committed code's contract, or
a "filed row" is INHERITED. Where the row's text supports neither, 5.2(a) gives
FRESH and I set `odf=Y`.

**A9. Section 5.2(b) - rows whose falsity is MIXED across sub-values.** chunk1-48
is two-thirds decayed and one-third born wrong; chunk1-52 is drift with no explicit
time index. The convention requires exactly one sub-value and forbids choosing the
most likely. I resolved mixed rows by the sub-value the row's own HEADLINE asserts
(so chunk1-48 is DECAYED), and used UNKNOWN only where NO positive test in 5.2 is
satisfied at all. This is a place where I may be choosing the most likely in
disguise, and I flag it rather than hide it.

**A10. Section 1.3 - how many events a multi-number census claim states.** The
boundary test ("could each half have been true while the other was false") splits
a two-number or three-number census, because the counts are logically independent.
I applied it literally: a claim reciting N independent figures, where the row's
text shows every one of them separately refuted, is SPLIT:N. A claim reciting N
figures where only ONE was refuted is KEEP (so chunk1-12 and chunk1-33 are KEEP).
A general assertion plus its derived consequence is KEEP (chunk1-20: the rate and
the years-to-bound figure derived from it). chunk4-34 recites four corpus sizes
but they are four spellings of ONE quantity over time, not four assertions, so it
is KEEP.

**A11. Section 1.3 MERGE - I found exactly one.** chunk2-32's own claim text says
"the same sufficiency assumption, in its second failing case", which is the 1.3
merge condition stated on the row's face. I merged it into chunk2-31. chunk4-07
and chunk4-08 share a quote and a refuter but state two different assertions about
two different work items, so they are KEEP, not a merge.

**A12. Section 6.1 cross-row links - I applied it only where a row's own text
names the other row's quantity.** The only instance I could ground is chunk2-23,
whose remedy (the corpus is 91) is explicitly refuted by chunk4-34 ("the rows
above recite 90 / 91 / 92 / 93 and every one of them is now stale"). Everything
else that looked like a cross-row link was two rows about the same subsystem, not
one row refuting another's remedy, so `xrow=0`.

**A13. Section 7 `correct` - the field is near-degenerate and I did not
manufacture variety.** I scored YES wherever the row's final refutation stands as
stated, NO never, and UNCLEAR only where the row's own text leaves the refutation
itself contested. Rows that describe a correction being corrected still get
correct=YES, because the row's refutation is the surviving one; the earlier bad
correction is recorded as a `fix_chain` link instead. This is the structural
non-result section 7 predicts, not a measurement.

**A14. Section 3.1 - GATE-EXISTING is reachable on this corpus ONLY through the
VACUITY door in 3.5, and that is worth flagging.** Every WRONG-SCOPE / WRONG-TIME
candidate I met ("a 2116-line guard against false-GREEN skips and NOTHING against
false-RED", a skip list that never excluded the vendored tree, a survival guard
that only reds after the row has fallen out) fails the tie-breaker in section 3's
preamble: each would have needed a new assertion or a widened corpus to see the
defect, which makes it GATE-ABSENT. So `prevention_why` values WRONG-SCOPE and
WRONG-TIME are emitted ZERO times by me, and every GATE-EXISTING I do emit carries
VACUOUS, arriving through 3.5's pinned "an instrument ran and measured NOTHING"
disambiguation. That is a consequence of the tie-breaker being applied FIRST, not
of the corpus lacking near-miss gates, and a reader should not read my zero
WRONG-SCOPE count as a claim about the tree.

**A15. Section 3.5 vacuity versus PROXY-MEASURE on a "passed and proved nothing"
row.** chunk4-15 ("16 guards, 317 passed, proving NOTHING" because the new files
were untracked) reads equally well as a proxy substitution and as a vacuous pass.
3.5 pins this: vacuity wins and the value is GATE-EXISTING/VACUOUS, "never
PROXY-MEASURE". I applied that literally, which moves the row from OUT-FAMILY to
IN-FAMILY and is therefore a family-level consequence of one clause. The same
clause carried chunk3-16 (a tracer with no planted control) and chunk3-23 (a guard
whose docstring promised a redness it did not have).

**A16. Section 5.1 - a LOOP DIRECTIVE is not covered by the report/dispatch
sub-rule.** 5.1 pins the commit-state test for a directive but the rows never state
whether the directive was committed. I resolved that a directive authored by a
PRIOR director cycle and handed to an executing cycle is INHERITED, because at the
moment of refutation it was a tracked artifact the refuting session did not
produce; a ground truth the SAME session handed its own slices (chunk3-18) is
FRESH. This decides roughly a dozen rows one way or the other and is the single
rule of mine most likely to differ from another scorer's.

ROW chunk1-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=2 | kinds=SELF,SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:3
ROW chunk1-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-06 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-07 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=SPLIT:2
ROW chunk1-10 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-11 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-13 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk1-15 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk1-20 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-22 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-23 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk1-33 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-35 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNDER-PROVEN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-36 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-39 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-41 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-43 | prev=PROXY-MEASURE | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-46 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNDER-PROVEN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:3
ROW chunk1-49 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-50 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-51 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-52 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-53 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-54 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-55 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-56 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-57 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-58 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-59 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-60 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-03 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-06 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-07 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-08 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-09 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk2-10 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk2-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-13 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-14 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-15 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk2-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-21 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-26 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-27 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-30 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-31 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-32 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=MERGE:chunk2-31
ROW chunk2-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-36 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-38 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk2-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-46 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-02 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk3-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-06 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:4
ROW chunk3-10 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-11 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-12 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-13 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-14 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-15 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-16 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-19 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SIBLING-SURFACE | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-23 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-36 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-37 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk3-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk3-40 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-43 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-45 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-46 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-47 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-01 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-03 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-06 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-07 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-08 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-10 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-11 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-12 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-13 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-15 | prev=GATE-EXISTING | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk4-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-19 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-20 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-24 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-26 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-27 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-30 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk4-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk4-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-35 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-36 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-39 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-40 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
