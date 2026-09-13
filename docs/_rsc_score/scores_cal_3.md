# Calibration scores, block 3 (file positions 133-198, chunk3-25 .. chunk4-43)

Scored against `docs/_rsc_score/RC_SCORING_CONVENTION_v1.md` alone, in file
order, once, with no revision of an earlier row to harmonise with a later one.

## chunk3-25
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: "An adversarial slice" is read as 3.4's enumerated "adversarial refutation pass", so the instrument IS identified for section 2's purposes.

## chunk3-26
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-27
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-28
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-29
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: "This slice, reading the direct caller" is an unprompted read, excluded from standing check by 3.4's boundary. `fix_chain` stays 0 because RM-312's shortfall is the PARENT chain, not this event's forward chain.

## chunk3-30
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-31
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: the row calls the comment "pre-existing stale prose" but names no superseding change, and 5.2b's DECAYED test demands a time index, so the sub-value falls to UNKNOWN.

## chunk3-32
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-33
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-34
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: "in-slice re-derivation BEFORE COMMIT" is positioned at a required process point, which is the row-checkable proxy I use for 3.4's OWED test.

## chunk3-35
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: no instrument ran BEFORE the defect, so PROXY-MEASURE fails condition 1 despite the "does not choke" shape.

## chunk3-36
- `prevention`: GATE-FIRED-CAUGHT, PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the extractor was right about pattern hits (11) and that was taken for real command blocks (5); the row names both quantities, so 3.5 admits it alongside the verifier catch.

## chunk3-37
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: backslash doubling in a non-raw docstring holds from authoring, so the tracked artifact carried the claim wrong from the start.

## chunk3-38
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: the row dates the shipping (2026-09-08) but not the hand-off, so it cannot be told whether the fallback was born wrong or decayed.

## chunk3-39
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: disposition drift reads as DECAYED but the row time-indexes nothing, and 5.2b forbids picking the likely sub-value.

## chunk3-40
- `prevention`: PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the parser correctly found a vocabulary token and that was taken for a disposition state; hand inspection is not a standing check.

## chunk3-41
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the registry guard is not GATE-EXISTING here - it was green and correct; the defect was a wrong prediction ABOUT it.

## chunk3-42
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / DECAYED
- `fix_chain`: 0
- `note`: "a live probe run this session" is neither a named standing instrument nor positioned before the claim. DECAYED because the row describes the change ("dropped test_doc_size_budget.py", "now selects").

## chunk3-43
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: "the recall gate" is a named standing instrument; the ask's durability is not established by the row, so 5.2a's floor applies.

## chunk3-44
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0

## chunk3-45
- `prevention`: PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: `git check-ignore -v` was right about "a pattern matched" and that was taken for "the file is ignored" - the row names both halves.

## chunk3-46
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk3-47
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: a live arm-status probe is constructible in advance and the datum is discrete; the row does not position the measurement as owed, so not GATE-FIRED-CAUGHT.

## chunk4-01
- `prevention`: GATE-FIRED-CAUGHT, PROXY-MEASURE
- `origin_time`: INHERITED / OVER-GENERALISED
- `fix_chain`: 0
- `note`: serial wall-clock was measured and taken for minimum achievable wall-clock; the suite itself is the named instrument that refuted it. OVER-GENERALISED and UNDER-PROVEN both pass their tests here and the convention orders neither - I took OVER-GENERALISED because the row names the domain (serial).

## chunk4-02
- `prevention`: GATE-EXISTING, GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: GATE-EXISTING with `prevention_why: WRONG-TIME` - the suite existed and would have run at cycle 7 and did not; the same suite later fired and caught it.

## chunk4-03
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the survival guard could not have seen this without a new predicate, so the section-3 tie-breaker sends it to GATE-ABSENT rather than GATE-EXISTING.

## chunk4-04
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: "already content-stale" labels decay without naming the change, so the same rule I applied at chunk3-31 gives UNKNOWN.

## chunk4-05
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: "triage pass before any code was written" is positioned at a required point. The directive's commit state is not established, so 5.1's commit-state test falls to 5.2a's FRESH floor.

## chunk4-06
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk4-07
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk4-08
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk4-09
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the byte pin is a named mechanised guard that the slice re-ran; it fired correctly and refuted the directive.

## chunk4-10
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: a consumer census is constructible in advance and presence of a consumer is a discrete datum; the census as run is not named or positioned as a standing pass.

## chunk4-11
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: thin row - "Slice E's probe" names no predicate, but it is the same directive-triage shape as chunk4-05 through chunk4-08 and I scored it the same rather than inventing a distinction.

## chunk4-12
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: a back-test that decides whether a gate may be armed is a mandated pre-ship measurement; 3.4 admits a self-run pass, so the producer-grades-itself objection does not block it.

## chunk4-13
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: crash-versus-stale is a discrete checkable behaviour, so 3.8's SHAPE test sends it to GATE-ABSENT even though only a reader caught it.

## chunk4-14
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: FRESH by 5.1's explicit sub-rule for an in-session agent report a merging session acted on.

## chunk4-15
- `prevention`: GATE-EXISTING, GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: GATE-EXISTING with `prevention_why: VACUOUS` - 3.5's boundary sends "317 passed proving NOTHING" here and explicitly NOT to PROXY-MEASURE.

## chunk4-16
- `prevention`: GATE-FIRED-CAUGHT, PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: a source-only sweep was right about source and was taken for the published package. The tie-breaker would also admit GATE-ABSENT (the corpus needed widening); I declined a third value because 3.9 says three-plus should be rare.

## chunk4-17
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the license gate is a named standing instrument positioned before the package mattered, so this is the gate working, not CONTRACT.

## chunk4-18
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: a count of silently-swallowed branches is a discrete datum; the re-read is not a standing check.

## chunk4-19
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk4-20
- `prevention`: ADVERSARY
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: closest call in the block. "Never left behind" is an unsupported generalisation spanning conditions (power loss) no predicate can enumerate, so the SHAPE test lands on reasoning error rather than on a checkable datum.

## chunk4-21
- `prevention`: GATE-ABSENT, PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the claim carries two halves - .gitattributes coverage (a discrete datum, GATE-ABSENT) and "local green means clone green" (a named substituted pair, PROXY-MEASURE). I did not split the row, per 1.3.

## chunk4-22
- `prevention`: GATE-EXISTING, GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: GATE-EXISTING with `prevention_why: VACUOUS` - an unfalsifiable branch check is an instrument that ran and measured nothing. FRESH because the row does not establish the test was committed at the moment of refutation.

## chunk4-23
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: "found the convention ALREADY in routes_diag.py" is the row's own pre-existence marker, which is what carries BORN-WRONG rather than UNKNOWN.

## chunk4-24
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: a fence asserting a property of consumer code that existed when the fence was filed is checkable-and-wrong at writing; not UNDER-PROVEN, because the row shows the evidence was absent, not thin.

## chunk4-25
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: this row's own text attributes the "hypothetical" framing to no durable artifact, so 5.2a's floor applies even though the neighbouring row names RM-313.

## chunk4-26
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / OVER-GENERALISED
- `fix_chain`: 0
- `note`: CONTRACT-MISFIRED nearly fits (the fault is in the acceptance, not the observance) but 3.7 requires the rule to have been CORRECTLY APPLIED, and here it was deliberately not met - so the row falls to the constructible per-field census.

## chunk4-27
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: a completeness claim ("the six detectors covered the severe case") is true in no domain, so OVER-GENERALISED's positive test is not met and the sub-value falls to UNKNOWN.

## chunk4-28
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0

## chunk4-29
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: second row where a filed spec was wrong and was corrected rather than applied; 3.7 cannot take it, so GATE-ABSENT absorbs it.

## chunk4-30
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / UNKNOWN
- `fix_chain`: 0
- `note`: "FALSE AT HEAD" explicitly scopes the falsity to the current tree and so declines to time-index it; that is 5.2b's UNKNOWN exactly.

## chunk4-31
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: merge-time adjudication is enumerated in 3.4. chunk4-32 refutes the WORDING of the revert's description, not the remedy, so 6.1's floor rule keeps this at 0 rather than 1.

## chunk4-32
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: a verifier prompt written and consumed in-session is FRESH under 5.1's directive sub-rule.

## chunk4-33
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / DECAYED
- `fix_chain`: 0
- `note`: DECAYED because the row names the dated superseding event (RM-396 REFUTED, 2026-09-09) that killed a BACKLOG row which predates it.

## chunk4-34
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / DECAYED
- `fix_chain`: 0
- `note`: the 90/91/92/93 progression against a live 123 is the row describing the change, not just labelling the result stale.

## chunk4-35
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 1
- `note`: cross-row link under 6.1 - the remedy for this defect (tightening to the 40-char window) is itself refuted at chunk4-36, `chain_kind` SELF.

## chunk4-36
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0

## chunk4-37
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: "the real gate - CLAIM_COUNT" is a named mechanised instrument the draft was run against.

## chunk4-38
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: NOT CONTRACT - "written before being checked" implicates only a check-before-asserting directive, which 3.6's boundary expressly disqualifies.

## chunk4-39
- `prevention`: GATE-ABSENT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: "and never did" is the row's own statement that the emit was wrong when written.

## chunk4-40
- `prevention`: PROXY-MEASURE
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the 3 -> 6 file movement was measured correctly and taken for an answer about WHO moved them; PROXY-MEASURE applies, so 3.8's residual ordering keeps ADVERSARY off despite the attribution being a reasoning error.

## chunk4-41
- `prevention`: GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0

## chunk4-42
- `prevention`: GATE-EXISTING, GATE-FIRED-CAUGHT
- `origin_time`: INHERITED / BORN-WRONG
- `fix_chain`: 0
- `note`: GATE-EXISTING with `prevention_why: WRONG-TIME`. NOT GATE-FIRED-IGNORED - 3.3 needs a signal that "exists in the record", and the row shows only that the guard WOULD have been red at 9b4bb834d.

## chunk4-43
- `prevention`: GATE-ABSENT
- `origin_time`: FRESH
- `fix_chain`: 0
- `note`: the stop-claim gate could not see file content without its input corpus being widened, so the section-3 tie-breaker sends it to GATE-ABSENT, not GATE-EXISTING / WRONG-SCOPE.

---

## Ambiguities I resolved

These are places where the convention underdetermined its own application on this
block. Stated flatly, including where the gap RC diagnosed in a sibling's
instrument appears to have been relocated rather than closed.

**A1. 3.4's OWED test is not checkable from a row, and 3.4 exempts itself from
the row-only discipline 3.6 imposes.** 3.4: "The discriminator is **whether the
pass was OWED before the work started**, not whether a machine ran it." Owed-ness
is a property of the TREE's standing directives, not of the row - yet 3.6 pins
the opposite discipline for CONTRACT: "The rule must be identifiable from the row
- not supplied by the scorer's knowledge of what rules the tree has." So the
largest-impact value in the taxonomy is allowed to import exactly the knowledge
the neighbouring value forbids. This matters here because a tree with a standing
adversarial-verification directive makes nearly every deliberate check owed,
which is structurally the same collapse 3.6 warns about for a broad CONTRACT
("every row in an orchestrated tree is CONTRACT ... and the value stops
discriminating"). **Resolution:** I substituted a row-text proxy - the refuter
must either (i) name a standing instrument (a named test/tool/guard/suite/hook,
or one of 3.4's enumerated directed passes: verifier, adversarial pass,
adjudication, recall gate, measurement gate), or (ii) be positioned by the row at
a required process point ("before commit", "at merge", "before any code was
written", "ahead of any repair"). A bare "the slice reading X", "the session
itself", "hand inspection", "live measurement" falls through. This proxy is mine,
not the convention's, and a second reader applying 3.4 literally would score more
of this block GATE-FIRED-CAUGHT than I did.

**A2. GATE-FIRED-CAUGHT and GATE-ABSENT are not mutually exclusive and nothing
orders them.** 3.2 requires "No MECHANISED instrument in this tree graded the
property at the moment the defect was written", while 3.4 explicitly rules a
DIRECTED pass a standing check. Every row in this block where a verifier or
adversarial pass caught a gate-shaped defect therefore satisfies both
definitions, and only ADVERSARY carries an ordering rule ("`ADVERSARY` is checked
LAST"). Left unresolved, roughly half this block becomes a two-value set, which
is the escape hatch the convention names against itself in weakness 5.
**Resolution:** I read 3.2's "graded the property" as satisfied by ANY standing
check that actually graded it, mechanised or directed, so a directed catch
suppresses GATE-ABSENT. A reader taking 3.2's word "mechanised" literally gets a
very different SET-grain number from the identical row judgements.

**A3. CONTRACT-MISFIRED has no home for a spec found wrong BEFORE it was
applied.** 3.7: "An existing rule, brief, spec or declared precondition was
CORRECTLY APPLIED, as written, and the outcome was still wrong." Three rows here
(chunk4-26, chunk4-29, chunk4-31) are filed specs or acceptances that were
refuted and deliberately NOT followed - the fault is squarely in the rule, which
is 3.7's stated purpose ("The fault is in the rule, not in the observance"), but
its gating condition excludes them, and 3.7's own boundary sends a not-followed
rule to CONTRACT, which is the opposite finding. **Resolution:** I scored them on
the constructible instrument instead (GATE-ABSENT). The consequence is that
"the spec itself was wrong" is invisible in my output.

**A4. The `origin_time` sub-value tests can both pass, and the convention orders
only the empty case.** 5.2: "If none of the four tests is satisfied by the row's
own text, the sub-value is `UNKNOWN`." It says nothing about two passing. On
chunk4-01 both OVER-GENERALISED (the row names the domain: a serial run) and
UNDER-PROVEN (the row shows real but thin evidence) are satisfied.
**Resolution:** I took OVER-GENERALISED wherever the row names a domain in which
the claim held, and reserved UNDER-PROVEN for rows that name evidence but no
domain.

**A5. The word "stale" asserts decay without supplying the time index DECAYED
demands.** 5.2's positive test: "`DECAYED` requires the row to time-index the
change - a later patch, a later commit, a superseding measurement, a 'was true
until X' shape." Several rows here say only that something is stale (chunk3-31,
chunk4-04). **Resolution:** label-only staleness -> UNKNOWN; a row that DESCRIBES
the change or names a dated superseding event -> DECAYED (chunk3-42, chunk4-33,
chunk4-34). This makes my UNKNOWN bucket larger than a reader who treats "stale"
as self-evidencing would produce.

**A6. BORN-WRONG's test does not say how to treat a claim ABOUT CODE.** 5.2:
"`BORN-WRONG` requires the row to show the claim was checkable and wrong at the
time it was written." A filed fence, premise or acceptance describing code that
existed when it was filed is wrong contemporaneously by construction, but the
rows almost never date themselves. **Resolution:** I took a claim describing a
code property that the row shows false, with no indication the property changed,
as BORN-WRONG; where the row hedges the falsity to the present ("FALSE AT HEAD",
chunk4-30) or dates only the superseding event and not the claim (chunk3-38), I
took UNKNOWN. This rule is mine; 5.2 does not contain it.

**A7. PROXY-MEASURE condition 2 does not say which description of "the thing it
measured" governs.** 3.5: "it was not wrong about the thing it measured." An
over-broad extractor (chunk3-36), a source-only sweep (chunk4-16) and a
check-ignore exit code (chunk3-45) are each wrong about the quantity the reader
NAMED and right about the predicate they actually evaluated. Under the first
description they are simply buggy instruments; under the second they are textbook
proxies. The convention's only disambiguation in this area is the vacuity carve-
out, which does not reach this case. **Resolution:** I took the predicate-level
description, which admits PROXY-MEASURE. Since PROXY-MEASURE is OUT-FAMILY, this
single unresolved word moves FAMILY-grain results, not just SET-grain ones - the
exact failure mode section 4.2 says the convention was written to prevent.

**A8. 3.9's "a set of ONE is the expected case" pulls against its own admission
rule.** The admission rule is "a value enters the set only where the ROW'S OWN
TEXT independently grounds it", which on several rows grounds two or three
values, while the surrounding sentence calls one the expected case and three
"rare". No rule says which wins. **Resolution:** I admitted a second value only
where it names a DIFFERENT prevention opportunity than the refuting pass (a
vacuous or untimely pre-existing gate, or a named substituted measurement), and
declined a third on chunk4-16 where the tie-breaker would also have admitted
GATE-ABSENT.

**A9. 6.1's cross-row link rule is not applicable to a partitioned scoring
pass.** "A forward link established by a DIFFERENT ROW IN THE SAME CORPUS **does**
count." I scored 66 of 198 rows and was instructed not to read the rest, so any
link established by a row outside my block is invisible and my `fix_chain`
figures are a floor bounded by my block, not by the corpus. The convention
provides no rule for this, and its own FLOOR language (6.1) does not name
partitioning as a floor source.

**A10. 3.4 admits "a mandated self-audit" while the same tree's orchestration
principle forbids a producer grading its own work.** Rows whose refuter is "the
builder's own measurement" or "the slice's own back-test" (chunk3-36, chunk4-12,
chunk4-16) are therefore simultaneously a standing check and a producer grading
itself. **Resolution:** I allowed a self-run pass to be GATE-FIRED-CAUGHT where
it met A1's positioning test, because 3.4 says so in terms and nothing in the
convention subordinates it.

**A11. Section 2 warns that GATE-FIRED-CAUGHT is unassignable where the row does
not identify WHICH instrument fired, but does not say how specific "which" is.**
"An adversarial slice" names a class, not an instance. **Resolution:** I treated a
class name drawn from 3.4's own enumeration as identification. Reading "which"
strictly as an instance would void GATE-FIRED-CAUGHT on most of chunk3-25 through
chunk3-28 and move them into the GATE-ABSENT / ADVERSARY region.
