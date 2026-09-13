# scores_B - RC convention v1 calibration, SCORER B

Scored blind from `rc198_blinded.md` alone. Ambiguities resolved, with counts:

1. S3.4 vs S3.9 - "a standing check DID fire ... and that is why the claim was refuted" does not say whether the row ALSO carries the value it would have taken had nothing fired. RESOLUTION: where GATE-FIRED-CAUGHT is grounded it is assigned ALONE (a set of one); the value it would otherwise take is recorded in `sfb` for DIR rows. Touches all 84 GATE-FIRED-CAUGHT rows and keeps every set at size 1.
2. S3.4 - "a NAMED instrument WITH A FIRING VERB which a STANDING RULE REQUIRED to run". RESOLUTION: gates / verifiers / adjudicators / adversarial passes / suites / hooks / named test files count; bare actors ("the session itself", "me", "the build, meeting the tree", "the merger", "this slice") do NOT, and live operation ("arming and running it", "the delivering cycle") does not. Touches every row.
3. S2 `instr` - "identifies WHICH instrument". RESOLUTION: Y needs a named mechanism (gate, verifier, named test, named tool, stated method such as an AST pass or a named command); a bare "re-derivation" or "reading X" is N. Touches ~60 rows.
4. S5.2a vs positive FRESH - the convention gives no marker for a row that POSITIVELY establishes in-session origin. RESOLUTION: `odf=Y` only where the row is silent on durability; `odf=N` where the row locates the claim in-session ("the entry's own draft", "my first enumeration", "the build's ..."). Touches 106 FRESH rows.
5. S5.2b BORN-WRONG - "checkable and wrong at the time it was written". RESOLUTION: a STRUCTURAL falsity that never held (a disk walk that never asked git, a negation that never protected) satisfies the positive test; a merely undated falsity does not and takes UNKNOWN. Touches 46 BORN-WRONG rows and 4 UNKNOWN.
6. S6 - a loop DIRECTIVE's durability is unstated everywhere it appears. RESOLUTION: treated as not established, so FRESH with `odf=Y` per 5.2a. Touches 12 rows.
7. S1.3 SPLIT - "separately wrong". RESOLUTION: split only where the row's own text ENUMERATES the separately-wrong assertions. 6 SPLIT rows, 1 MERGE.

ROW chunk1-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=2 | kinds=SELF,SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-03 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:3
ROW chunk1-05 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-06 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-07 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-08 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-09 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-10 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-11 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-13 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-14 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk1-15 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk1-21 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-22 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-23 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=UNCLEAR | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-25 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-26 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-27 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-30 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-31 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-32 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-33 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-34 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-35 | prev=GATE-ABSENT | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-36 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-38 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-39 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk1-41 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-42 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-43 | prev=PROXY-MEASURE | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-44 | prev=ADVERSARY | why=- | origin=INHERITED/OVER-GENERALISED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-45 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-46 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNDER-PROVEN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=SPLIT:3
ROW chunk1-49 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-50 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-51 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk1-52 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk1-53 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-54 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-55 | prev=GATE-EXISTING | why=VACUOUS | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-56 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-57 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-58 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-59 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk1-60 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-01 | prev=GATE-ABSENT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-02 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-03 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-04 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-05 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-06 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-07 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-08 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-09 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-10 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-11 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-12 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-13 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-14 | prev=ADVERSARY | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-15 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-16 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=1 | kinds=SELF | cu=N | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-17 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/UNKNOWN | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-18 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-19 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=SPLIT:2
ROW chunk2-20 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-21 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-22 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-23 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-24 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-25 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-26 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-27 | prev=GATE-ABSENT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-28 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-29 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-30 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-31 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-32 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=MERGE:chunk2-31
ROW chunk2-33 | prev=ADVERSARY | why=- | origin=FRESH | odf=Y | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-34 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-35 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=ADVERSARY | indiv=KEEP
ROW chunk2-36 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-37 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-38 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-39 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-40 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-41 | prev=GATE-FIRED-CAUGHT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-42 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=MECH | sfb=- | indiv=KEEP
ROW chunk2-43 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-44 | prev=GATE-ABSENT | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-45 | prev=ADVERSARY | why=- | origin=INHERITED/BORN-WRONG | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=N | gfck=- | sfb=- | indiv=KEEP
ROW chunk2-46 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=PROXY-MEASURE | indiv=KEEP
ROW chunk2-47 | prev=GATE-FIRED-CAUGHT | why=- | origin=FRESH | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=DIR | sfb=GATE-ABSENT | indiv=KEEP
ROW chunk2-48 | prev=GATE-ABSENT | why=- | origin=INHERITED/DECAYED | odf=N | fix=0 | kinds=- | cu=Y | xrow=0 | correct=YES | instr=Y | gfck=- | sfb=- | indiv=KEEP
