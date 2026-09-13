# Scorer B - RC scoring convention v1 applied to 198 blinded rows

## Ambiguities I resolved

Each item names the convention section that was underdetermined, the decision I
made, and the direction it pushes the numbers. Every one was forced - the
convention as written does not settle it, and the rows cannot be scored without
settling it.

1. **Section 3, opening tie-breaker vs 3.2's own boundary - a direct internal
   contradiction.** The pinned tie-breaker says an existing check that could not
   have seen the defect without its "predicate changed, its input corpus
   widened, or a new assertion added" is `GATE-ABSENT`. 3.2's stated boundary
   says the opposite for the same fact pattern: "if a check DID exist but was
   too narrow, the value is `GATE-EXISTING` with `prevention_why: WRONG-SCOPE`".
   A too-narrow check is exactly a check needing a widened corpus or predicate,
   so the two cannot both be applied. **Resolution: the tie-breaker wins, because
   section 3 declares it "applied FIRST, before any definition below".** The
   consequence, stated plainly because it is large: I emit `WRONG-SCOPE` on ZERO
   rows, and `GATE-EXISTING` survives only for `WRONG-TIME` (a covering gate that
   ran too late) and `VACUOUS` (a covering gate that ran and measured nothing). A
   scorer taking 3.2's boundary as governing would move a substantial block of my
   `GATE-ABSENT` rows to `GATE-EXISTING` without either of us departing from the
   text.

2. **Section 3.4 - which named passes count as STANDING.** The BROAD reading
   admits a DIRECTED pass, but its discriminator ("was the pass OWED before the
   work started") is not decidable from most rows, which name the pass and not
   the rule requiring it. **Resolution: I treat as standing exactly these, by
   name - adversarial gate / pre-commit gate / read-only gate, verifier and
   independent verifier, adjudicator and adjudication pass, recall gate, cycle
   audit and wrap-ritual runs, named test files and named suites, and any named
   guard or hook.** I treat as NOT standing the implementing agent's own work
   however labelled - "the session itself", "me", "the merger", "the build", "the
   slice's triage pass", "the slice's three-freeze-path audit", "reading the call
   site", "in-session re-derivation". The line is INDEPENDENCE or MANDATE, not
   the presence of the word "audit" or "pass". This is the single largest lever
   on my output: it decides `GATE-FIRED-CAUGHT` membership and therefore what the
   STRICT second column in 3.4 subtracts.

3. **Section 3.4 boundary vs section 3.8 shape test - which is checked first.**
   3.8 pins `ADVERSARY` as the residual checked LAST and pins the shape test
   against it, but does not say whether a discrete checkable datum caught by a
   standing DIRECTED pass is `GATE-FIRED-CAUGHT` or `GATE-ABSENT`. **Resolution:
   `GATE-FIRED-CAUGHT` takes precedence over the shape test**, because the shape
   test is written inside 3.8 to police the `ADVERSARY` / `GATE-ABSENT` boundary
   only ("the discriminator is the SHAPE of what was wrong, never the identity of
   who caught it"). So a wrong line citation caught by the adversarial gate is
   `GATE-FIRED-CAUGHT`, and its STRICT fallback is `GATE-ABSENT` by the shape
   test. This is why nearly every `sfb` I emit is `GATE-ABSENT`.

4. **The `sfb` field is not defined by the convention at all.** 3.4 promises a
   second `gate_or_contract` column under LW's STRICT reading but never says what
   value a `GATE-FIRED-CAUGHT` row takes once the directed pass is disqualified.
   **Resolution: I re-ran the whole of section 3 with `GATE-FIRED-CAUGHT`
   unavailable and recorded the value that then applies.** Where the row's set
   already carried a second value (typically `PROXY-MEASURE`), `sfb` is that
   value. Consequence for the family grain: most of my `sfb` values are
   `GATE-ABSENT`, which is IN-FAMILY, so the STRICT column moves the per-value
   counts far more than the family share.

5. **Section 3.9's "set of ONE is the expected case" vs 3.5's three-condition
   `PROXY-MEASURE`.** Many rows name both a firing control AND a substituted
   measurement pair. **Resolution: I admit the second value only where the row
   names the substituted pair explicitly enough that I could write both
   quantities down** - e.g. "a grep that finds no ROW body is not a claim about
   the registry" (measured: ROW bodies; believed: registry allocation). I
   declined `PROXY-MEASURE` wherever I could name only the believed quantity.
   That is 3.5's own restriction applied hard, and it is why several
   proxy-shaped rows come out as bare `GATE-ABSENT`.

6. **3.5's vacuity carve-out vs `PROXY-MEASURE`, where a clean zero is
   indistinguishable from a clean tree.** The convention pins vacuity to
   `GATE-EXISTING/VACUOUS`, but an instrument that intercepts nothing did in one
   sense measure something. **Resolution: where the row's own text says the
   instrument could not have distinguished a real pass from a no-op, I score
   `GATE-EXISTING` with `why=VACUOUS`; where it measured a real quantity that was
   then read as a different one, `PROXY-MEASURE`.** Vacuity applied at chunk3-16,
   chunk3-23 and chunk4-15; proxy applied at chunk1-55, where a dry cycle really
   did pass 12 of 12 and was read as proof of delivery.

7. **Section 3.6 narrow `CONTRACT` on a tree whose standing directives cover
   everything.** Nearly every row could implicate some CLAUDE.md rule, and 3.6
   forbids the scorer supplying the rule from their own knowledge of the tree.
   **Resolution: `CONTRACT` only where the ROW's text names the rule.** I reached
   it on exactly one row (chunk2-27, which names ADR-015 and its vacuity rule)
   and as one STRICT fallback (chunk4-17, whose row names the license gate).
   Known weakness 6 of the convention predicted this undercount; I report it
   rather than adjust for it.

8. **Section 5.1 on a directive handed to a headless loop cycle.** 5.1 pins the
   commit-state test, but no row states whether its directive was committed.
   **Resolution: the 5.2(a) default, so directives are `FRESH` with `odf=Y`.**
   That is a large block (the R-series directives and lane dispatches) and it
   pushes my inherited share down. It is the floor the convention says it is, not
   a finding about directives.

9. **Section 5.2(b) positive tests vs the pull toward `BORN-WRONG`.** A row
   saying a shipped claim "does not and never did" hold satisfies the
   `BORN-WRONG` test; a row saying a claim is merely "stale" time-indexes
   nothing. **Resolution: `UNKNOWN` wherever the row asserts falsity without
   either a time index or a demonstration that the claim was checkable and wrong
   when written.** Applied at chunk1-18, chunk1-47, chunk1-59, chunk3-31,
   chunk4-10 and chunk4-38.

10. **Section 6.1 cross-row links - which pairs count.** The rule is pinned, but
    the corpus is blinded, so I can use only links visible in the row text
    itself. **Resolution: I counted a cross-row link only where one row's claim
    is, on its face, that the remedy named in another row worked or stood.** I
    found four (chunk2-13, chunk2-23, chunk2-35, chunk4-35, each `xrow=1`). I did
    NOT chase links that require knowing entry ordering, and under 6.1's FLOOR
    rule I scored down everywhere else.

11. **`cu` (chain_undetermined) has no definition of "silent".** Read at its
    widest, every `fix=0` row is silent about the remedy's later fate and the
    field becomes a constant. **Resolution: `cu=Y` unless the row states the
    remedy's disposition** - the fix landing in the same commit, the proposal
    refused, DO NOTHING, "deliberately not met", or a refutation that closes the
    item with no remedy needed. Under a wider reading of "silent", all my `cu=N`
    rows flip to `Y`.

12. **`instr` (section 2) - "identifies WHICH instrument".** A refuter naming a
    role ("the merger", "the session itself") names an actor, not an instrument.
    **Resolution: `instr=Y` where the row names a control or tool that produced a
    verdict - a gate, verifier, adjudicator, named test, suite, probe, census,
    identity check, live measurement, or a named command such as
    `git diff --numstat`; `instr=N` for bare agency and bare reading.** `instr`
    and `gfck` are therefore independent: a named probe identifies the instrument
    without making it standing.

13. **Section 1.3 SPLIT - how hard to push.** A census producing several figures
    could be read as several claims. **Resolution: SPLIT only where the row's own
    text asserts that MULTIPLE named assertions were each wrong** - "EVERY
    INHERITED NUMBER WAS WRONG", "BOTH HALVES ARE FALSE AT HEAD", "90 / 91 / 92 /
    93 and every one of them is now stale". A single enumeration yielding two
    figures (8 sites across 3 files; 11 files against 9 subdirectory walks) is ONE
    claim and stays KEEP, because those figures cannot fail independently of the
    enumeration. Four SPLITs and one MERGE result. The MERGE is chunk2-32 into
    chunk2-31: chunk2-32's own claim text reads "the same sufficiency
    assumption", which is 1.3's MERGE condition verbatim.

14. **Section 7 `correct` and the `uncertain_present` flag.** The blinding
    removed the uncertainty BODY and kept the flag; the convention says nothing
    about it, and the flag may attach to the defect rather than to the
    refutation. **Resolution: I ignored the flag entirely and scored `correct`
    from the refutation text alone.** I emit `YES` on every row - no row states
    that its own SURVIVING refutation was shown wrong. Where a row records a
    correction that was itself corrected, I scored that as a `fix_chain` link
    (section 6), not as `correct=NO`, because section 7 asks about the refutation
    that stands. This reproduces the structural non-result section 7 predicts,
    and I report it as that rather than as evidence about refutation quality.

15. **A conflict I did NOT resolve in my own favour.** Several rows would take
    `GATE-FIRED-IGNORED` under a loose reading - a check that existed whose
    signal went unread, e.g. chunk4-02, where a guard was already red when the
    cycle shipped. 3.3 requires "an actual failing or warning signal that exists
    in the record". In chunk4-02 the suite was never run, so there was no signal
    to ignore; I scored it `GATE-EXISTING/WRONG-TIME` plus `GATE-FIRED-CAUGHT`
    for the later run that caught it. I emit `GATE-FIRED-IGNORED` on zero rows.

ROW chunk1-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=2 | kinds=SELF,SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:3
ROW chunk1-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-06 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-07 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-10 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-11 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-13 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-15 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-20 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-22 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-23 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-33 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-35 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-36 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-39 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-41 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-43 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-44 | prev=ADVERSARY | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-46 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-49 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-50 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-51 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-52 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-53 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-54 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-55 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-56 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-57 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-58 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-59 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-60 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-03 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-06 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-07 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-08 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-09 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-10 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-13 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-14 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-15 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-19 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-21 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-26 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-27 | prev=GATE-ABSENT,CONTRACT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-30 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-31 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-32 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=MERGE:chunk2-31
ROW chunk2-33 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-36 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-38 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk2-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-46 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-01 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-02 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-03 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk3-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-06 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-10 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-12 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-13 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-14 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-15 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-16 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-17 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-19 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-23 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-EXISTING | indiv=KEEP
ROW chunk3-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk3-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-36 | prev=GATE-FIRED-CAUGHT,PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk3-37 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-40 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-43 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk3-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-45 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk3-46 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk3-47 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-01 | prev=PROXY-MEASURE | why=- | origin=INHERITED/UNDER-PROVEN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-02 | prev=GATE-EXISTING,GATE-FIRED-CAUGHT | why=WRONG-TIME | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-03 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-05 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-06 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-10 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-12 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-13 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-15 | prev=GATE-EXISTING | why=VACUOUS | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-16 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=CONTRACT | indiv=KEEP
ROW chunk4-18 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-19 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-20 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-24 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-26 | prev=GATE-ABSENT | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-27 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-28 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-29 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-30 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:2
ROW chunk4-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-33 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk4-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=SPLIT:4
ROW chunk4-35 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=1 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-36 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-39 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-40 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk4-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk4-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk4-43 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
