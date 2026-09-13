# Scorer C - 198 rows under RC_SCORING_CONVENTION_v1

## Ambiguities I resolved

1. **Section 3.9 vs 3.4 - does GATE-FIRED-CAUGHT crowd out the value that says what WOULD
   have prevented the defect?** The eight values answer two different questions: seven of
   them describe a prevention opportunity that existed before the defect, while
   GATE-FIRED-CAUGHT describes what actually caught it afterwards. Section 3.9 admits a
   value whenever the row's own text independently grounds it, and section 4.3 explicitly
   refuses a precedence order, so on a corpus whose refuters are overwhelmingly named
   standing passes, a literal reading makes almost every row multi-valued. **Resolution:**
   I assign GATE-FIRED-CAUGHT alone where the row grounds only the catching instrument,
   and add a SECOND value only where the CLAIM text independently establishes a distinct
   prevention structure - a substituted measurement (PROXY-MEASURE), a named rule that was
   not followed (CONTRACT), or a vacuous existing guard (GATE-EXISTING/VACUOUS). I did not
   add GATE-ABSENT alongside GATE-FIRED-CAUGHT, even though a directed pass is not
   mechanised and GATE-ABSENT's text is arguably satisfied on nearly every such row -
   doing so would have made the SET grain meaningless and the SPLIT count an artefact.
   This is the single largest judgement in my pass and a different scorer could
   defensibly double almost every row.

2. **Section 3.4 - which refuters count as a NAMED instrument with a FIRING VERB.** The
   convention names the categories but not the linguistic test. **Resolution, applied
   mechanically:** "the adversarial gate", "the pre-commit gate", "the second gate", "an
   independent verifier", "the read-only verifier", "an independent adjudicator", "the
   recall gate", "the cycle audit", "the docs-guards run", a named `tests/test_*.py`, "the
   mutant suite", "the stop-claim gate", "the wrap ritual's docs-guard suite" all count.
   "the session itself", "me", "reading the call site", "re-reading", "the slice's own
   triage", "hand inspection", "an AST-derived re-derivation", "the merger" (acting as
   author rather than as a gate) do NOT - section 3.4's boundary says an unprompted
   re-read is not a standing check. Those rows fall through to the shape test.

3. **Section 3.4 MECH vs DIR.** Not defined beyond a parenthetical list. **Resolution:**
   an "adversarial" / "verifier" / "adjudicator" / "refutation pass" qualifier makes it
   DIR even when it also carries a commit-time position ("the pre-commit adversarial
   gate" -> DIR). A suite, a named test file, a hook described by what it RAN ("the
   pre-commit gate, which ran the full tests/ suite"), a CI run, a dry cycle, a mutant
   suite -> MECH.

4. **Section 3.8 shape test - the recurring fact pattern the convention does not name:
   "a claim misdescribes what a document says".** Roughly a fifth of this corpus is that
   shape (a spec clause, a docstring, a README, a fence, a filed row's wording).
   **Resolution:** the presence or absence of a clause in a file is a discrete checkable
   datum, so these are GATE-ABSENT, not ADVERSARY. I reserved ADVERSARY for wrong causal
   attribution, unsupported generalisation ("stated unconditionally"), and
   evidence-to-conclusion errors.

5. **Section 3.6 - what "observance" of a rule means.** If reading a document correctly
   counted as observing it, then every misdescription row above would be CONTRACT and the
   value would stop discriminating exactly as 3.6 warns. **Resolution:** CONTRACT requires
   a failure to COMPLY with a named rule (gate-before-the-irreversible-act, the id
   registry's rule 3, a shipped decision that had just removed a behaviour), never a
   failure to read one accurately. This makes my CONTRACT count low, which is the
   confound weakness 6 pre-committed to checking.

6. **Section 6.1 / the `cu` flag - what counts as "silent on what happened to the
   remedy".** Almost every row states the refutation and nothing about a later fix.
   **Resolution:** `cu=N` where the row supplies the CORRECTED value or names a shipped
   remedy ("now 240", "the correct predicate yields 7 sites", "re-derived to 565"), on the
   reading that the row then records a remedy and does not record it refuted; `cu=Y` where
   the row records only that the claim was wrong. A stricter reader would set `cu=Y`
   everywhere fix=0, since "remedy stood" is nowhere asserted.

7. **Section 1.3 - enumerations and multi-figure censuses.** A claim like "three terminal
   states, two of which were stale" or "1408 spans, 131 claim-shaped" technically contains
   assertions that could each have been true while the other was false. **Resolution:** I
   treat a single census or enumeration as ONE claim (KEEP) and SPLIT only where the claim
   text names two structurally different artifacts or two different subjects. That yields
   very few splits; a reader applying 1.3's boundary test literally to every numeric
   conjunct would get many more.

8. **Section 5.1 / 5.2(a) - when a row calls something "filed" without saying it was
   committed.** **Resolution:** "the filed row's X", "RM-nnn's filed premise", "BACKLOG
   RM-nnn", "LEDGER nnnn", "the spec's section n", "a prior session's census", "the audit
   doc" are taken as durable -> INHERITED. Shipped CODE behaviour is also taken as durable
   (a tracked artifact), which is a positive reading a stricter scorer would default to
   FRESH under 5.2(a). "the entry's own draft", "my first phrasing", an in-session agent
   report, a directive consumed in-session -> FRESH with `odf=N`. Neutral phrasings that
   establish nothing -> FRESH with `odf=Y`.

9. **Section 5.2(b) sub-values.** I applied the four positive tests strictly, which sends a
   large share to UNKNOWN. In particular I did NOT read "the code never did this" as
   DECAYED, and I did NOT read "a later item changed the world" as BORN-WRONG.

10. **Section 6 - "wrong twice" and similar.** Where a row says a correction "was itself
    wrong twice", I read ONE refuted remedy containing two errors rather than two links,
    per the 6.1 floor rule that a scorer never guesses upward.

11. **Section 6.1 cross-row links.** I found two clear cases where one row's claim IS the
    remedy for another row's defect (chunk2-35/chunk2-36 and chunk4-35/chunk4-36) and
    recorded the link on the parent with `xrow=1`. I did not hunt for weaker pairings
    across chunks, so this count is itself a floor.

12. **Section 7 `correct`.** Nothing in this corpus states that a refutation was itself
    factually wrong in a way that survived; where a refutation was later corrected the row
    records the CORRECTED refutation, which is the one I graded. I therefore scored YES
    throughout except where the row's own text leaves the refuting measurement contested.

13. **The `sfb` field (LW STRICT reading).** The convention defines the strict reading but
    not the procedure for re-deriving a value under it. **Resolution:** I removed
    GATE-FIRED-CAUGHT from the set and re-ran my own ordering, so `sfb` is whatever the
    row's second-choice value would have been - PROXY-MEASURE or CONTRACT where the claim
    text grounded one, otherwise the shape test's answer (GATE-ABSENT or ADVERSARY).

14. **The tie-breaker in section 3 all but abolishes `GATE-EXISTING` with
    `WRONG-SCOPE`.** The tie-breaker is applied FIRST and says an instrument that needed
    its predicate changed or its corpus widened is GATE-ABSENT; but section 3.2's own
    boundary says "if a check DID exist but was too narrow, the value is GATE-EXISTING
    with WRONG-SCOPE, not GATE-ABSENT". Every too-narrow check needs a widened predicate
    or corpus, so the two rules cannot both be satisfied. **Resolution:** the tie-breaker
    wins, because the convention says to apply it first and in capitals. The consequence
    is that I filed ZERO `WRONG-SCOPE` rows and GATE-EXISTING survives in my pass only as
    WRONG-TIME and VACUOUS. A scorer who honoured 3.2's boundary instead would move a
    noticeable block of my GATE-ABSENT rows into GATE-EXISTING - within the same family,
    so it changes the per-value table and not the family share.

15. **`prevention_why` has no value for "the gate existed, covered the property, was
    green, and nobody consulted it".** That fact pattern appears in this corpus (a
    byte-pin check that would have answered a directive's assumption outright). It is not
    WRONG-SCOPE (the scope was right), not VACUOUS (it measures something real), and not
    obviously WRONG-TIME. **Resolution:** I recorded it as `WRONG-TIME`, reading "time" as
    "the check had not run at the moment the claim was made". A different scorer could
    read the same row as GATE-FIRED-IGNORED, but 3.3 requires an actual failing or warning
    signal and a green run is not one, so I did not.

16. **Rows whose refuter is a guard or sweep BUILT BY THE SAME ITEM.** Several rows are
    caught by an instrument that did not exist when the defect was written. **Resolution:**
    where the instrument fired on the work before it shipped and a standing rule now
    requires it (a pre-push sweep, a TDD arm's first red run), I allowed
    GATE-FIRED-CAUGHT; where the instrument was built specifically to test a standing
    BELIEF and the belief long predated it (the sibling-name sweep against the
    post-scrub belief that the tree was clean), I scored GATE-ABSENT, because at the
    moment the defect was written nothing graded the property. This is the least
    comfortable line I drew and it is drawn on the age of the BELIEF, not the age of the
    instrument.

ROW chunk1-01 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk1-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-06 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-08 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-10 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-11 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-13 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk1-15 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-20 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-22 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-23 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-32 | prev=GATE-FIRED-CAUGHT,CONTRACT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk1-33 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-35 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-36 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-39 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-41 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-46 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-49 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-50 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-51 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-52 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-53 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-54 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-55 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-56 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-57 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-58 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-59 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-60 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-03 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-06 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-07 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-08 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-09 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-10 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-13 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-14 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-15 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-19 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-21 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-26 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-27 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-30 | prev=ADVERSARY | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-31 | prev=ADVERSARY | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-32 | prev=ADVERSARY | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=MERGE:chunk2-31
ROW chunk2-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-36 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-38 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-42 | prev=GATE-FIRED-CAUGHT,CONTRACT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-46 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-02 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk3-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-06 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-10 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-11 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-12 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-13 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-14 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-15 | prev=PROXY-MEASURE | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-16 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-19 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-23 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-32 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-36 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-37 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-40 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-43 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-45 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-46 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-47 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-01 | prev=PROXY-MEASURE | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-03 | prev=GATE-EXISTING | why=WRONG-TIME | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-06 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-07 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-08 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-09 | prev=GATE-EXISTING | why=WRONG-TIME | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-10 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-11 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-12 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-13 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-15 | prev=GATE-EXISTING | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-16 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-19 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-20 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-22 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk4-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-24 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-26 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-27 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-28 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-30 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk4-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-35 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-36 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-39 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-40 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
