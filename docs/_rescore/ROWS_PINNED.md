# RC per-event rows, pinned re-score 2026-09-12

198 rows, four independent scorers, LEDGER entries 1365-1406.
Machine tally: docs/_rescore/tally.py. Scored under pin v1.2.
Published as a BAND - see the cover note. Individuation is claim-level
(approximately v1.3 clause 1; deviations are UNDER-splitting, so 198 is a floor).

---

# Chunk 1 re-score - LEDGER entries 1365 to 1375, under REFUTATION_TAXONOMY_PIN v1.2

**fix_chain direction applied: FORWARD, as pinned in section 6.** Each row is scored
as the DEFECT, and `fix_chain` counts the number of times THE REMEDY FOR THAT DEFECT
was itself subsequently refuted. Where an entry narrates a chain (D, then F1 refuted,
then F2 refuted, then F3 stands) exactly ONE row is emitted for D, carrying
`fix_chain: 2`. The later links are deliberately NOT emitted as their own rows, per
the section 6 worked example and its explicit ban on the backward reading.

---

## chunk1-01

- `id`: chunk1-01
- `entry`: 1375
- `claim`: RM-393's filed citations to its four consumer lines named line numbers that were valid before this session's own edit to the same file.
- `quote`: `every consumer line RM-393 cites moved by exactly 55`
- `refuter`: the session itself, re-deriving the citations after the last edit against `git diff --numstat`.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - the row now carries both sets)
- `fix_chain`: 0

## chunk1-02

- `id`: chunk1-02
- `entry`: 1374
- `claim`: the line citations written into the new docstring and into the session's own correction note were current for the file as committed.
- `quote`: `MY OWN EDIT STALED THE ROW'S CITATIONS INSIDE THE SAME COMMIT, AND MY FIRST CORRECTION OF THAT WAS ITSELF WRONG TWICE`
- `refuter`: re-derivation after the last edit caught the first half; the pre-commit adversarial gate caught the rest.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - all of it corrected in the tree)
- `fix_chain`: 1 (chain_kind: SELF)
- `uncertain`: fix_chain 2 - the entry says the first correction was "WRONG TWICE" (the 13-versus-14 line count and the `:4xx`-only scoping), but both were refuted in a single gate pass, so "the number of times the remedy was refuted" reads as 1.

## chunk1-03

- `id`: chunk1-03
- `entry`: 1374
- `claim`: the 22-site grep for repo-root enumeration in `tests/*.py` bounded the candidate set of guards with this defect.
- `quote`: `So the grep is not a bound`
- `refuter`: the pre-commit gate, which ran the full `tests/` suite and surfaced a fifth red guard whose enumeration is split across two lines.
- `prevention`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the row now states five measured red, 18 candidates, and an unmeasured true set)
- `fix_chain`: 0

## chunk1-04

- `id`: chunk1-04
- `entry`: 1373
- `claim`: the prior session's census of 115 external-binary call sites over 940 top-level `tests/*.py`, 39 of them false-RED.
- `quote`: `EVERY INHERITED NUMBER WAS WRONG, AND SO WAS THE PREMISE.`
- `refuter`: three parallel agents re-deriving the census from scratch, then a hostile refutation pass.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1 (chain_kind: SELF) - the re-derived figure of 148 sites was itself found one short by the hostile pass, giving 149.

## chunk1-05

- `id`: chunk1-05
- `entry`: 1373
- `claim`: RC's own filed residual that a pre-push hook's PATH puts its false-RED classification in doubt in the environment that gates every push.
- `quote`: `THE INBOUND WARNING WAS REFUTED TWICE OVER.`
- `refuter`: reading all six `.githooks` bodies (no RC hook runs pytest) plus a live PATH probe on this box (only git relocates).
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: discovery RUN - the live PATH probe is a run, and the pin refuses the sub-distinction for siblings but not for this mixed case.
- `pin_gap`: section 7 exclusion 2 excludes "external-origin claims the tree never adopted". This tree DID adopt the inbound warning by filing it as a residual in its own ledger (entry 1370) without ever acting on it. The pin does not say whether filing is adoption.

## chunk1-06

- `id`: chunk1-06
- `entry`: 1373
- `claim`: `check=True` is the discriminator that separates gated from ungated external-binary call sites.
- `quote`: `is not the discriminator, since a large minority of ungated sites omit it and error identically`
- `refuter`: RC's own re-derivation during the filing pass.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - the predicate was rewritten)
- `fix_chain`: 0

## chunk1-07

- `id`: chunk1-07
- `entry`: 1373
- `claim`: the try/except-shaped repair for an ungated spawn scores UNRESOLVED under the existing hygiene guard's resolver.
- `quote`: `I CORRECTED THAT FINDING BEFORE IT SHIPPED AND THE CORRECTION MATTERED`
- `refuter`: me, measuring the real in-repo instance rather than the synthetic shape - an `importorskip` anywhere in the same function scope launders the verdict to CAPABILITY.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: prevention GATE-ABSENT - nothing in the tree grades a scoring claim made against a synthetic shape.

## chunk1-08

- `id`: chunk1-08
- `entry`: 1373
- `claim`: adjudication pass one's fact that the eol test module carries a live false-GREEN passing vacuously on every run today.
- `quote`: `but the "today" half is false, since git works here and those assertions pass for the right reason`
- `refuter`: verification in source, then a further correction of that correction.
- `prevention`: ADVERSARY
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1 (chain_kind: SELF) - my correction called the trigger set "wider" than tool absence when it is DISJOINT, and was corrected in turn.
- `uncertain`: prevention GATE-ABSENT.

## chunk1-09

- `id`: chunk1-09
- `entry`: 1373
- `claim`: adjudication pass two's census of 8 unchecked-stdout git spawns across 3 files.
- `quote`: `Pass two also attempted the census and got it WRONG in the same breath`
- `refuter`: the pre-commit gate, corroborated by my own re-derivation; the correct predicate yields 7 sites across 2 files.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-10

- `id`: chunk1-10
- `entry`: 1373
- `claim`: adjudication pass one's position that the unchecked-stdout sites fall inside the existing hygiene guard's charter.
- `quote`: `Pass two also found a SECOND error in pass one - those sites are not in the existing guard's charter at all`
- `refuter`: adjudication pass two, on the ground that the file contains no skip of any kind.
- `prevention`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: prevention CONTRACT - a rule requiring a guard's charter to be stated before a site is claimed inside it would have reached this.

## chunk1-11

- `id`: chunk1-11
- `entry`: 1373
- `claim`: the entry's own draft sentence saying `RC-InboxResponder` was disabled "and re-enabled at wrap", written in the past tense while the task was still disabled.
- `quote`: `a future act stated as done, in the file that becomes the record`
- `refuter`: the adversarial gate, against a live `schtasks` query returning Disabled.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - fixed in the working tree before commit)
- `fix_chain`: 0

## chunk1-12

- `id`: chunk1-12
- `entry`: 1373
- `claim`: CI provisions git and chromium explicitly.
- `quote`: `and the workflow installs git nowhere`
- `refuter`: the adversarial gate, reading `ci.yml` - chromium is explicit, git only implicit via `actions/checkout`.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-13

- `id`: chunk1-13
- `entry`: 1373
- `claim`: the browser fixture is requested by 55 of the 62 files.
- `quote`: `and one is the conftest that DEFINES it, so 54 request it`
- `refuter`: the adversarial gate, separating mention from request.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-14

- `id`: chunk1-14
- `entry`: 1373
- `claim`: two citation ranges quoted in the draft row were accurate.
- `quote`: `and two citation ranges off by a line at each end`
- `refuter`: the first adversarial gate.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - fixed before commit)
- `fix_chain`: 0

## chunk1-15

- `id`: chunk1-15
- `entry`: 1373
- `claim`: the RM-394 row's citation of the scanning function's span.
- `quote`: ``a function cited `:171-185` that actually spans `:171-189` ``
- `refuter`: the SECOND adversarial gate, run over the first round's fixes; the first gate never saw this row because it was added afterwards.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the same gate mechanism existed and had already taught this exact defect class, but the row was written after that gate ran, so it inherited none of its coverage.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: prevention GATE-FIRED-CAUGHT.
- `pin_gap`: when ONE mechanism misses a defect at t1 (wrong scope or time) and catches it at t2, the pin gives no rule for which of GATE-EXISTING and GATE-FIRED-CAUGHT wins. Both are literally true of the same check.

## chunk1-16

- `id`: chunk1-16
- `entry`: 1373
- `claim`: the RM-394 row's citation of the constant's assignment span.
- `quote`: ``a constant cited `:56-64` whose assignment spans `:56-65` ``
- `refuter`: the second adversarial gate.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - same as chunk1-15, a row added after the gate that would have covered it.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: prevention GATE-FIRED-CAUGHT.

## chunk1-17

- `id`: chunk1-17
- `entry`: 1373
- `claim`: the hedge that roughly 16 other unchecked git spawns do inspect the return code.
- `quote`: `as exact only for the wrong quantity: 16 is the count of OTHER unchecked sites`
- `refuter`: the second adversarial gate - 16 is the count of other unchecked sites, of which 14 inspect and 2 discard output.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-18

- `id`: chunk1-18
- `entry`: 1373
- `claim`: the frozen-file-list guard's disk walk enumerates the repository.
- `quote`: ``invisible to CI because `_scan_frozen_headers` (`:171-189`) walks the DISK at `:174-175` rather than asking git``
- `refuter`: the wrap ritual's local docs-guard suite going red on 24 orphan headers, all under gitignored export trees.
- `prevention`: GATE-EXISTING
- `prevention_why`: VACUOUS - the guard is green in CI because the export trees do not exist there, so in the environment that gates every push it enumerates nothing and grades nothing.
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: NO - filed as RM-394, and the row deliberately does not prescribe the hand-list fix)
- `fix_chain`: 0
- `uncertain`: prevention GATE-FIRED-CAUGHT - a standing guard did fire and the finding was filed.

## chunk1-19

- `id`: chunk1-19
- `entry`: 1372
- `claim`: position X - the answered record is permanent and unbounded BY DECISION, so no name may be dropped.
- `quote`: `THE ADJUDICATOR REJECTED BOTH DRAFTED POSITIONS ON A CLAUSE NEITHER HAD READ, which is the finding.`
- `refuter`: the distinct adjudicator, reading the already-shipped spec clause and a recorded live deletion in the runner.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the ruling is narrower than either position)
- `fix_chain`: 0
- `pin_gap`: section 7 exclusion 4 arguably covers a losing position in an adjudicated fork, since the fork's stated purpose is to test both positions and rejecting one is its intended output. Scored as an event anyway because position X was FACTUALLY wrong against a shipped record, which is more than the probe's intended output. The symmetric case in entry 1371 (a losing position refuted on evidence but not factually wrong) is NOT scored, so the pin is deciding two similar cases differently on my reading alone.

## chunk1-20

- `id`: chunk1-20
- `entry`: 1372
- `claim`: 2.45 arrivals per day and about 60 years to the bound.
- `quote`: `THE MEAN WAS REFUTED BY ITS OWN DISTRIBUTION`
- `refuter`: the adjudicator, re-deriving the arrival histogram - 113 arrivals over 45 calendar days but only six active days, and the figure had divided the ANSWERED count by the ARRIVAL span.
- `prevention`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the row now quotes the range, never the mean alone)
- `fix_chain`: 0
- `uncertain`: prevention PROXY-MEASURE.

## chunk1-21

- `id`: chunk1-21
- `entry`: 1372
- `claim`: the metrics ledger is trimmed to 200 rows.
- `quote`: `The adjudicator called the metrics ledger "trimmed to 200 rows": it is not trimmed at all`
- `refuter`: me, against the shipped RM-388 behaviour - it ROTATES, the 200 is a carry tail, and no rotation has fired.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1 (chain_kind: SELF) - my own correction then quoted a row count as re-derived in a file that gains a row every five minutes, and the gate found it stale before the commit.

## chunk1-22

- `id`: chunk1-22
- `entry`: 1372
- `claim`: the ten note-bearing metrics rows are all dry-cycle stubs.
- `quote`: `I described those note-bearing rows as "all dry-cycle stubs" when 6 of the 10 are`
- `refuter`: re-reading the rows - six are live cycles, and the zero intersection is a claim about the projection, not about dryness.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-23

- `id`: chunk1-23
- `entry`: 1372
- `claim`: the decision's flip condition rests on a contract prohibition against archiving notes out of the inbox.
- `quote`: `rule 7.2 bans EDITING a delivered note and says nothing about a receiver archiving its own inbox`
- `refuter`: the adversarial gate, reading the contract - the flip condition rests on a GAP plus current practice, never on a prohibition.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - corrected in all three files at once, where it had already propagated)
- `fix_chain`: 0

## chunk1-24

- `id`: chunk1-24
- `entry`: 1371
- `claim`: a rotation that archives 40 rows of another agreement.
- `quote`: `THE CORRECTION WAS FALSE TOO, WHICH IS THE MORE USEFUL HALF.`
- `refuter`: the first gate (measured 35), then the second gate (measured 36), then an independent re-derivation confirming both as answers to different questions.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the fix was to stop quoting a number no test asserts, rather than quote a third one)
- `fix_chain`: 1 (chain_kind: SELF)

## chunk1-25

- `id`: chunk1-25
- `entry`: 1371
- `claim`: the carry rule moves no row of the live agreement whatever its age, stated unconditionally.
- `quote`: `stated unconditionally, when an ABSENT record vouches with no id`
- `refuter`: the adversarial gate - an absent record and a record edited into a different agreement both archive the whole window, and only the first was the disclosed residual.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-26

- `id`: chunk1-26
- `entry`: 1371
- `claim`: a non-zero archive count is necessary and sufficient evidence that the moved-record residual fired.
- `quote`: `a non-zero archive count is EVIDENCE the window is short, says nothing about WHICH precondition broke`
- `refuter`: the first gate on the claim, then the second gate on the correction.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - written as an ALARM rather than a proof)
- `fix_chain`: 1 (chain_kind: SELF) - the correction used the word "proves", which the second gate refused on the disclosed crash-between-append-and-replace path.

## chunk1-27

- `id`: chunk1-27
- `entry`: 1371
- `claim`: the filed row's count of three call sites.
- `quote`: `the row's filed "three call sites" was corrected to FOUR, and the closing arm then made it SIX`
- `refuter`: the adversarial gate, then the session's own closing arm.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1 (chain_kind: SELF) - the correction to FOUR was itself stale against the commit that carried it.

## chunk1-28

- `id`: chunk1-28
- `entry`: 1371
- `claim`: the rotation helper's identity is root-keyed twice.
- `quote`: `A fifth was a fact inverted from a docstring I had read in this same session`
- `refuter`: the adversarial gate - one identity is cycle-keyed and one root-keyed.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-29

- `id`: chunk1-29
- `entry`: 1371
- `claim`: a single command prints all three quoted figures.
- `quote`: `one sentence credited a single command with three figures`
- `refuter`: the adversarial gate - the recipe prints only the first.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - now attributed to three commands)
- `fix_chain`: 0

## chunk1-30

- `id`: chunk1-30
- `entry`: 1371
- `claim`: the BACKLOG closure's citation of a ledger entry.
- `quote`: `the BACKLOG closure cited this ledger entry before it existed`
- `refuter`: the adversarial gate.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - landed in the same commit rather than left dangling)
- `fix_chain`: 0

## chunk1-31

- `id`: chunk1-31
- `entry`: 1371
- `claim`: a function's `__doc__` attribute is a substring of `inspect.getsource` output, so replacing it strips the docstring before a body scan.
- `quote`: `so the attribute is not a substring of the source and the replace silently does nothing`
- `refuter`: the arm's own first run, which went red when the docstring's prose tripped the assertion.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - split on the triple quotes, with the prose asserted separately as the vacuity control)
- `fix_chain`: 0
- `uncertain`: exclusion - section 7 item 3 excludes RED-first TDD failures, and this was a first cut going red. Scored as an event because the red was NOT the planned red: it exposed a wrong assumption about the Python runtime, not the absence of the feature under test.

## chunk1-32

- `id`: chunk1-32
- `entry`: 1370
- `claim`: note 1 was fit to deliver into the sibling's inbox.
- `quote`: `A verification step placed after the irreversible act converts its own findings into a contract violation.`
- `refuter`: RC's own adversarial gate, run after delivery, which found nine defects.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the gate existed and ran correctly, but after the irreversible act, so its findings could only be applied by breaking the never-edit-a-delivered-note rule.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: partially - the delivered artifact could not be un-delivered and a downstream party had already rebroadcast from it)
- `fix_chain`: 2 (chain_kind: SELF) - note 2, the correction, shipped three new false sentences, and note 3's draft was caught pre-delivery asserting a refutation that was itself wrong.
- `pin_gap`: the entry states "NINE defects" without enumerating them, so per-finding granularity is unrecoverable and this is scored as ONE event. Elsewhere in this chunk gate findings ARE enumerated and scored one row each (chunk1-11 through chunk1-14), so the pin's silence on granularity makes the same corpus countable two ways.

## chunk1-33

- `id`: chunk1-33
- `entry`: 1370
- `claim`: 121 of 139 test functions take the `world` or `git_repo` fixture.
- `quote`: `lines said 121 and missed four wrapped signatures`
- `refuter`: an AST-derived re-derivation, giving 125.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES in this tree, but the wrong figure had already been rebroadcast to four inboxes)
- `fix_chain`: 0
- `uncertain`: prevention PROXY-MEASURE - the entry's own lesson is that machine-derived is not the safe category and re-derived by a second method is, which reads as a wrong instrument rather than a correct instrument on the wrong question.

## chunk1-34

- `id`: chunk1-34
- `entry`: 1370
- `claim`: the first draft's assertion about the gate-tag census trap, which named a suffix relation as a prefix.
- `quote`: `RC's first draft asserted the second as a prefix and was wrong`
- `refuter`: the session, before the answer shipped.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the trap is now stated in both directions)
- `fix_chain`: 0

## chunk1-35

- `id`: chunk1-35
- `entry`: 1370
- `claim`: RC's test suite, guarded by a 2116-line skip-hygiene module, handles external-binary absence correctly.
- `quote`: `a 2116-line guard against false-GREEN skips and NOTHING against false-RED`
- `refuter`: a measured run with git off PATH - 17 passed and 205 errors of 221 collected, raised inside a session fixture.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the guard audits skip CONDITIONS, and an ungated spawn has no skip to inspect, so it is structurally blind to this class.
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: NO in this entry - only filed; one site was gated three entries later)
- `fix_chain`: 0
- `uncertain`: origin_time sub-value OVER-GENERALISED.

## chunk1-36

- `id`: chunk1-36
- `entry`: 1369
- `claim`: the prelude failure handler's contract that no prelude failure is silent.
- `quote`: `crashed the one handler whose contract is that no prelude failure is silent`
- `refuter`: a sibling's published refutation about unguarded directory creation, reproduced against RC's nine sites.
- `prevention`: GATE-ABSENT
- `discovery`: SIBLING
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - the two writes are attempted independently now)
- `fix_chain`: 0

## chunk1-37

- `id`: chunk1-37
- `entry`: 1369
- `claim`: the session's first enumeration of the affected directory-creation sites.
- `quote`: `my first enumeration was incomplete and the verifier corrected it`
- `refuter`: the independent adversarial verifier.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-38

- `id`: chunk1-38
- `entry`: 1369
- `claim`: the filed row's metrics-ledger row count.
- `quote`: `MEASURED BEFORE DECIDING, and the filed figure was already stale`
- `refuter`: measuring before deciding - 75 rows at filing, 98 by this session.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-39

- `id`: chunk1-39
- `entry`: 1369
- `claim`: verifier pass 3's report that no scheduled responder task is registered at all.
- `quote`: `A subagent's claim about MACHINE state is no more trustworthy than its claim about a test count.`
- `refuter`: re-probing, with both a task query and a PowerShell cmdlet returning the task in the Disabled state this session left it in.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-40

- `id`: chunk1-40
- `entry`: 1369
- `claim`: the mutant needle is stable because the line it quotes is unchanged.
- `quote`: `A procedure-A mutant needle broke TWICE mid-item because it quotes source text at a call site this work moved`
- `refuter`: the mutant suite itself, breaking twice during the item.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the needle is back to its original text and the comment now says it survives as a substring)
- `fix_chain`: 1 (chain_kind: SELF) - the first repair did not hold and the same needle broke a second time.

## chunk1-41

- `id`: chunk1-41
- `entry`: 1368
- `claim`: the assembled reply body names the file the sender actually sent.
- `quote`: `so the counterparty read their own filename truncated in the one line written for a human`
- `refuter`: reading the assemble call site - it was reusing the row's 80-character projection.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - one argument changed, with an arm asserting the sender-visible string)
- `fix_chain`: 0

## chunk1-42

- `id`: chunk1-42
- `entry`: 1368
- `claim`: the spec's section 2 statement that the envelope's raw note name equals its own projection by construction.
- `quote`: `It does not and never did - a name of 188 characters passes the grammar while`
- `refuter`: RM-387's measurement; a topic-cap raise one item earlier turned the gap from rare into routine.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES, after three attempts)
- `fix_chain`: 3 (chain_kind: SIBLING-SURFACE) - the fixing commit edited three places but only one carried the claim and a second claim site survived untouched; the correction of that called the survivor "the fourth site" and was wrong; the over-correction said the original message was NEVER true and was also false.
- `uncertain`: chain_kind SELF for links two and three.
- `pin_gap`: section 6 requires ONE `chain_kind` per event, but this chain's links differ in kind - link one is SIBLING-SURFACE (a missed sibling claim site), links two and three are SELF. The pin gives no aggregation rule, and picking the first link versus the majority link gives different answers.

## chunk1-43

- `id`: chunk1-43
- `entry`: 1367
- `claim`: the cycle's report of nothing pending meant nothing was pending.
- `quote`: `the responder saying nothing is pending while something is`
- `refuter`: reading the admission path - a junction is never a regular file, and a transposed sender prefix returns no sender code, so both classes were dropped before any gate could see them.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1 (chain_kind: INTRODUCED) - the fix's new branch shipped below a hard-link check, and a directory's link count differs between POSIX and Windows, so CI went red on two arms that every local gate had passed.
- `uncertain`: the entry calls this two classes of the same defect; scored as one event, so a two-event reading is defensible.

## chunk1-44

- `id`: chunk1-44
- `entry`: 1367
- `claim`: the spec's section 15 fence putting the admission module out of scope.
- `quote`: `that fence expired with the build and this item took it`
- `refuter`: this session, reading the fence against the build it was scoped to.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - the last strict-xfail in the suite is now a passing arm)
- `fix_chain`: 0
- `uncertain`: discovery SELF-AUDIT.

## chunk1-45

- `id`: chunk1-45
- `entry`: 1367
- `claim`: the filed row's proposed disposal, marking the refused entry answered so it stops re-cycling.
- `quote`: `and answering it is exactly what RM-386 had just stopped doing`
- `refuter`: the item shipped one entry earlier the same day, which had just removed answering-on-refusal.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - the refusal is held, not answered)
- `fix_chain`: 0

## chunk1-46

- `id`: chunk1-46
- `entry`: 1367
- `claim`: an earlier probe in this session read the transposed-name file as unanswered.
- `quote`: `LIVE IMPACT MEASURED AS ZERO, and the first measurement of it was WRONG`
- `refuter`: re-probing the answered record directly.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-47

- `id`: chunk1-47
- `entry`: 1367
- `claim`: the 106-entry seed figure carried into this entry.
- `quote`: `so the 106/2 split is not recoverable from the artifact`
- `refuter`: the adversarial verifier, raising it as its one soft spot - the live record is a flat sorted list of 108 names with no seed marker.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: YES - the prose now says which half is inherited, and the load-bearing half is measured directly)
- `fix_chain`: 0

## chunk1-48

- `id`: chunk1-48
- `entry`: 1366
- `claim`: the filed row's body, naming three terminal states that answer a note and tell the sender nothing.
- `quote`: `THE ROW THAT ASKED FOR IT WAS ALREADY TWO-THIRDS STALE`
- `refuter`: a measurement taken before any code was written - two of the three had shipped closed the same afternoon, and the third was never this row's class.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - the backlog row is kept as filed under a preamble saying which clauses went stale and when)
- `fix_chain`: 0
- `uncertain`: origin_time sub-value BORN-WRONG - two clauses decayed, but the third was misattributed from the start.

## chunk1-49

- `id`: chunk1-49
- `entry`: 1366
- `claim`: the answered record means a note was answered, at all five of its call sites.
- `quote`: `refusals were written to the answered record, which made them PERMANENT`
- `refuter`: live operation - an entry had to be deleted by hand before widened caps could re-cycle a real sibling note.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES for the mechanism; the one false historical entry is measured and deliberately LEFT IN PLACE as an operator decision, because deleting it would sort that note to the head of the next queue)
- `fix_chain`: 0
- `uncertain`: discovery SELF-AUDIT.

## chunk1-50

- `id`: chunk1-50
- `entry`: 1366
- `claim`: the prose promise that the late gate terminates with the held-notes detail when nothing else is eligible.
- `quote`: `was a promise the code does not make`
- `refuter`: the independent read-only verifier.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-51

- `id`: chunk1-51
- `entry`: 1366
- `claim`: an unwritable hold record clears the bounce target.
- `quote`: ``is true of the four held stages only, not of a `destination` refusal, which takes no hold``
- `refuter`: the independent read-only verifier.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk1-52

- `id`: chunk1-52
- `entry`: 1366
- `claim`: the spec's verbatim recital of the proposal schema matched the live schema.
- `quote`: `A verbatim schema recital in prose is a second source of truth with no guard on it`
- `refuter`: the verifier, catching pre-existing drift in a file this session touched but not on a changed line.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: origin_time sub-value DECAYED.

## chunk1-53

- `id`: chunk1-53
- `entry`: 1366
- `claim`: making the record path a directory exercises the unwritable-record branch.
- `quote`: `making the record itself a directory does not test the unwritable path at all`
- `refuter`: measurement while writing the arm - the unreadable gate catches that shape first.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the arm uses a readable-but-unwritable shape instead)
- `fix_chain`: 0
- `uncertain`: exclusion - arguably section 7 item 4, a hypothesis opened by a probe whose purpose was to test it. Scored as an event because the fixture was adopted and written before it was found to grade nothing.

## chunk1-54

- `id`: chunk1-54
- `entry`: 1365
- `claim`: the filed cause of the first armed tick's grammar refusal was the note-name length cap.
- `quote`: `Raising the named cap alone would have fixed ZERO of them.`
- `refuter`: a re-measurement across all five inboxes deduplicated - 208 unique notes, 34 regex failures, all 34 on the topic group and only 11 over the length cap.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - caps raised on both axes, post-change 0 of 208 fail)
- `fix_chain`: 1 (chain_kind: SELF) - the filed remedy was refuted one commit before it shipped.
- `uncertain`: fix_chain 0.
- `pin_gap`: section 6 says fix_chain counts times the remedy was SUBSEQUENTLY refuted, without saying whether a remedy refuted BEFORE it ships counts. Counting it rewards catching the wrong fix early; not counting it makes an early catch invisible.

## chunk1-55

- `id`: chunk1-55
- `entry`: 1365
- `claim`: the responder, green across a 26-gate census, 68 mutants and a clean dry cycle, would deliver a reply.
- `quote`: ``The 26-gate census, 68 mutants and `PASS 12 FAIL 0` dry cycle were ALL GREEN while this sat in the prompt.``
- `refuter`: arming and running it - a successful spawn returned an empty action list because the system prompt instructed exactly that, and the note was marked answered with nothing delivered.
- `prevention`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - schema minimum plus a rewritten paragraph, and a bounce design adopted)
- `fix_chain`: 0
- `uncertain`: prevention GATE-EXISTING with prevention_why VACUOUS.

## chunk1-56

- `id`: chunk1-56
- `entry`: 1365
- `claim`: the spawn timeout constant of 120 seconds was sufficient.
- `quote`: `120 was too short for the 618 MB export (first dry cycle timed out) - now 240`
- `refuter`: the first dry cycle timing out.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0
- `uncertain`: prevention CONTRACT - the spec carried these on a declared UNMEASURED list, so a rule requiring an unmeasured constant to be measured before arming would have reached it.

## chunk1-57

- `id`: chunk1-57
- `entry`: 1365
- `claim`: the max-turns constant of 12 was sufficient.
- `quote`: `so the old limit would have failed a third time and hit the attempt cap - now 30`
- `refuter`: the delivering cycle, which used 21 turns.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: YES, with the honest in-comment caveat that the failure cause is INFERRED because a non-zero exit short-circuits parsing)
- `fix_chain`: 0
- `uncertain`: prevention CONTRACT, as for chunk1-56.

## chunk1-58

- `id`: chunk1-58
- `entry`: 1365
- `claim`: the attempt counter reading 2 after what looked like one failure was a defect.
- `quote`: `Suspicion retracted after reading the log properly.`
- `refuter`: reading the log properly - there were two failing cycles and the counter is correct.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES - the refutation (that the counter is correct) was itself factually right, and the wrong claim was the suspicion of a defect. (defect_corrected: not applicable, there was no defect)
- `fix_chain`: 0

## chunk1-59

- `id`: chunk1-59
- `entry`: 1365
- `claim`: the architecture-map generator enumerates the repository.
- `quote`: `swept 194 files of the gitignored 618 MB export cache into`
- `refuter`: the polluted tracked document appearing in a commit from this session.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - the generator's skip list now excludes the runtime tree, fixed at the root rather than by re-generating)
- `fix_chain`: 0
- `uncertain`: discovery RUN.

## chunk1-60

- `id`: chunk1-60
- `entry`: 1365
- `claim`: RC's responder runtime records were bounded, so the metrics ledger needed no rotation.
- `quote`: `One APPLIES and is filed as RM-388.`
- `refuter`: a sibling's published refutation, checked against RC's own tree rather than trusted.
- `prevention`: GATE-ABSENT
- `discovery`: SIBLING
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES, at the third attempt)
- `fix_chain`: 2 (chain_kind: SELF) - the remedy needed an answer to which agreement is live, and the first two answers were both wrong and both looked right; verifier pass 1 and verifier pass 2 each measured the quotable window collapsing from 30 rows to 0.


---

# chunk2 - RC LEDGER entries 1376 to 1386, scored under LW REFUTATION_TAXONOMY_PIN v1.2

fix_chain DIRECTION APPLIED: **FORWARD**, exactly as pinned in section 6 - each row is scored as the DEFECT, and `fix_chain` counts the number of times THAT EVENT'S OWN REMEDY was subsequently refuted. The backward reading (scoring an event because it is itself somebody's second attempt) was NOT used, so a fix-of-a-fix never gets its own row. Two supersessions in this chunk are therefore folded rather than rowed: the LEDGER 1382 deletion of the own-origin push carve-out is `fix_chain` on the 1381 row, and the LEDGER 1386 correction of the "positive control" sentence is `fix_chain` on the 1385 row.

---

## chunk2-01

- `id`: chunk2-01
- `entry`: 1376
- `claim`: RM-394's filed premise that the repo-root enumeration universe (git index versus os.walk minus check-ignore) was still an open decision to be made.
- `quote`: `THE DECISION THE ROW POSED WAS ALREADY ANSWERED IN CODE, AND FINDING THAT OUT WAS THE FIRST ACT.`
- `refuter`: the RM-394 executor's own first-act read of the tree, finding tests/_repo_walk.py already implementing the answer with four consumers.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 1 (SIBLING-SURFACE) - the adoption fix converted five guards and missed two more root walkers of the same root cause, filed as RM-395 the next entry; LEDGER 1377 names it "the same blindness class that made RM-394 miss a member of its own population".
- `uncertain`: origin_time INHERITED / UNKNOWN (the decision existed in code but carried no ledger row, ADR or CLAUDE.md line, so whether the filer could have known is not resolvable from the entry)

## chunk2-02

- `id`: chunk2-02
- `entry`: 1376
- `claim`: that after conversion none of the five converted guards could pass on an empty enumeration.
- `quote`: `I claimed none of the five could now pass on an empty enumeration. Four cannot.`
- `refuter`: the first of the two read-only gates run before the commit, which forced the enumeration empty and measured the module still at 56 passed.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the repair (a disk-asserted anchor on the directory holding the guard) was proven to bite by mutation and re-verified by gate 2.
- `uncertain`: prevention GATE-EXISTING (prevention_why VACUOUS) - the guard itself was the check that would have passed while measuring nothing
- `pin_gap`: section 2 mixes two questions in one field. GATE-FIRED-CAUGHT is a DETECTION fact while every other value answers what would have PREVENTED the defect, so an event that a standing gate caught AND a declared precondition would have prevented has two defensible values and the pin gives no precedence rule. This file applies: GATE-FIRED-* wins whenever tooling actually caught it.

## chunk2-03

- `id`: chunk2-03
- `entry`: 1376
- `claim`: that the newly added shared EXCLUDED_DIRS entry was adequately pinned by the tests as shipped.
- `quote`: ``The gate's second finding was that the new `EXCLUDED_DIRS` entry was pinned only INDIRECTLY, by another guard's synthetic fixture``
- `refuter`: the same read-only gate, second finding.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the direct pin in tests/test_repo_walk.py was added and gate 2 measured it doing its job.

## chunk2-04

- `id`: chunk2-04
- `entry`: 1376
- `claim`: the entry's own first phrasing, which kept gate 1's "only failure" wording after describing the repair that made it false.
- `quote`: `a row that contradicts itself inside one paragraph is what a second gate is for`
- `refuter`: the second read-only gate.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-05

- `id`: chunk2-05
- `entry`: 1377
- `claim`: that tests/_repo_walk.py has no ledger row, no ADR and no CLAUDE.md line (stated in the present tense).
- `quote`: `a gate refuted the present-tense version of that sentence`
- `refuter`: a gate on the ADR-writing slice, which found the module named in the docs from the RM-394 repair onward.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the ADR now scopes the claim to 2026-09-07 through 2026-09-09.

## chunk2-06

- `id`: chunk2-06
- `entry`: 1377
- `claim`: that the ADR TEMPLATE is what demands the index row land in the same commit.
- `quote`: `the TEMPLATE demands nothing, a gate caught that cite`
- `refuter`: a gate, which relocated the demand to the README preamble at docs/adr/README.md:8-9.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-07

- `id`: chunk2-07
- `entry`: 1377
- `claim`: that the dead-endpoint guard is green because the deleted symbols are absent from the gitignored export copies it walks.
- `quote`: `My draft said it is green because the deleted symbols are absent there`
- `refuter`: the gate on the RM-395 filing, which found the symbols PRESENT in each export tree's copy of the guard file itself.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-08

- `id`: chunk2-08
- `entry`: 1377
- `claim`: that the laning-verdict guard was safe because its skip list excludes the ops directory.
- `quote`: `` I called safe by accident because `_SKIP_DIRS` excludes `ops` ``
- `refuter`: the same gate, which measured 2082 files walked of which 1685 (81 percent) are vendored python-embed that the skip list never excluded.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-09

- `id`: chunk2-09
- `entry`: 1377
- `claim`: that the residual population was 11 root-walking files against 9 subdirectory walks.
- `quote`: `My first pass reported "11 files, 9 subdirectory" - an artifact of a receiver-name heuristic`
- `refuter`: a stronger AST pass resolving receivers through alias chains, parents, Path/str wrappers and ROOT joins, returning 2 true root walkers against 39 subdirectory walks.
- `prevention`: PROXY-MEASURE
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the load-bearing figure (two is the whole set) survived both passes.

## chunk2-10

- `id`: chunk2-10
- `entry`: 1377
- `claim`: that RM-395 was a free id because a grep for it over BACKLOG, ROADMAP and LEDGER returned 0.
- `quote`: `a grep that finds no ROW body is not a claim about the registry`
- `refuter`: tests/test_rm_id_registry_drift.py went RED at the docs-guard run; the tracker had already PINNED RM-395 as next-free.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 1 (INTRODUCED) - the remedy (advance the pin and record the allocation beside it) was written up in prose that named the fresh figure, which the same guard graded as an ALLOCATION and went red a SECOND time.

## chunk2-11

- `id`: chunk2-11
- `entry`: 1377
- `claim`: that the ROADMAP next-free pointers were left alone because they are struck through and defer to the tracker.
- `quote`: `I said they are struck through and defer to the tracker`
- `refuter`: the slice's own measurement over ROADMAP.md - eleven pointers, exactly ONE struck through, two citing the tracker, eight bare.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the conclusion (leave them alone) survived, on the corrected ground that they are already filed as RM-316.

## chunk2-12

- `id`: chunk2-12
- `entry`: 1378
- `claim`: the RM-395 row's assertion that both remaining holdouts are absence guards and therefore share the empty-set-safe shape.
- `quote`: `"Both are ABSENCE guards, which is exactly the empty-set-safe shape" is FALSE for the laning guard`
- `refuter`: the conversion slice doing ADR-015's Watch-for step first, then proving it by mutation (forcing the enumerator to return [] gave 1 failed, 26 passed).
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0

## chunk2-13

- `id`: chunk2-13
- `entry`: 1378
- `claim`: the RM-395 row's count of exposed enumeration sites in the two holdout files.
- `quote`: `The row named two exposed sites; there are three.`
- `refuter`: the conversion slice, finding a third site in the same file enumerating the caller directories.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0

## chunk2-14

- `id`: chunk2-14
- `entry`: 1378
- `claim`: that the third site was exposed in the same correctness sense as site 1, as told to the operator.
- `quote`: `I had told the operator that site was exposed the way site 1 is; it was not.`
- `refuter`: the build slice, which measured the site's own ops/runtime prefix skip already dropping every export file, leaving a read-set of 1260 on both sides with an empty symmetric difference.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-15

- `id`: chunk2-15
- `entry`: 1378
- `claim`: that 1331 is site 2's read-set, recited in four places.
- `quote`: `I wrote 1331 as site 2's READ-set. 1331 is the caller SURFACE`
- `refuter`: the pre-commit gate, re-deriving by replaying the guard's own surface predicate and skips: the dashboard route skip removes 71, so the read-set is 1260.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES
- `fix_chain`: 0
- `uncertain`: origin_time FRESH (the in-file comment it came from was correct as written; only this session's restatement moved it out of its domain)

## chunk2-16

- `id`: chunk2-16
- `entry`: 1379
- `claim`: that the do-not-patch-the-gate hazard is recorded as a comment inside tools/stop_claim_gate.py, a cite that had propagated into three artifacts.
- `quote`: `that hazard is NOT a comment in the file`
- `refuter`: a search of the file returning ZERO matches, then the gate catching the row repeating the cite while rewriting the very memory that carried it.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - corrected in the memory, the ledger, the backlog and the hand-off together.

## chunk2-17

- `id`: chunk2-17
- `entry`: 1379
- `claim`: RM-396's premise that tools/stop_claim_gate.py needed a narrowing patch for the refutation-quoting asymmetry.
- `quote`: `It returned DO NOTHING, and the grounds are measured rather than argued.`
- `refuter`: an independent adjudicator, briefed with the conflict of interest disclosed and told to say DO NOTHING if that was honest.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - the DO NOTHING verdict survived a second adversarial pass aimed at it as motivated reasoning.
- `uncertain`: origin_time INHERITED / UNDER-PROVEN (the row named a real asymmetry; what was false was that it needed a code remedy)

## chunk2-18

- `id`: chunk2-18
- `entry`: 1379
- `claim`: that count_mismatch is the only gate check with an honest in-session cure.
- `quote`: `THE ASYMMETRY IS REAL BUT NARROWER THAN I FIRST WROTE IT, and the gate corrected me twice over in one sentence`
- `refuter`: the second gate, naming four other checks computed over the whole session's bash record that clear the same way.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-19

- `id`: chunk2-19
- `entry`: 1379
- `claim`: that the over-strip's blast radius was 1408 spans over 200 chars, 131 claim-shaped, longest 5502.
- `quote`: `AND MY BLAST-RADIUS FIGURE WAS WRONG BY 2.3x, IN THE DIRECTION THAT FLATTERED MY OWN FINDING.`
- `refuter`: the second gate, pointing at collect_evidence appending text only for assistant-role blocks; re-derived to 565 scanned spans / 57 claim-shaped.
- `prevention`: PROXY-MEASURE
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-20

- `id`: chunk2-20
- `entry`: 1379
- `claim`: that the apostrophe over-strip disarms nine of the gate's checks.
- `quote`: `It disarms EIGHT checks, not nine`
- `refuter`: the second gate, showing the hook_bypass flag runs inside the bash-command loop and never sees strip_prose_noise.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-21

- `id`: chunk2-21
- `entry`: 1379
- `claim`: the standing assumption that strip_prose_noise deletes only genuine quoted spans before the claim scan.
- `quote`: `two ordinary prose APOSTROPHES pair as quote delimiters and everything between them is deleted before any check runs`
- `refuter`: the author's own probe, re-derived rather than inherited, on a two-possessive sentence whose count vanished.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - RM-397 shipped in LEDGER 1380 measuring 8 new findings and 0 lost, and nothing in this window refutes it.
- `pin_gap`: section 4 asks where THE CLAIM came from, but a latent code defect carries no stated claim - only the implied contract of the artifact. Scoring it INHERITED treats the code itself as the durable record; the pin neither licenses nor forbids that.

## chunk2-22

- `id`: chunk2-22
- `entry`: 1379
- `claim`: the gate's own parse of space-grouped thousands, which reported a claimed figure that never appeared in the prose.
- `quote`: `` `CLAIM_COUNT` mis-parses space-grouped digits ``
- `refuter`: the RM-396 refutation pass, recording it as a finding rather than building it.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 1 (SELF) - the first version of the remedy in LEDGER 1384 (drop any 1-3 digit prefix plus a comma-free 3-digit count) was refuted by measurement for swallowing real suite totals, and the shipped form is evidence-derived instead.

## chunk2-23

- `id`: chunk2-23
- `entry`: 1380
- `claim`: that the measurement corpus is the 90 transcripts the RM-397 row was filed with.
- `quote`: `THE CORPUS IS 91 TRANSCRIPTS, NOT THE 90 THE ROW WAS FILED WITH`
- `refuter`: the build's own freeze-and-count of the transcript directory before measuring.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `fix_chain`: 0
- `uncertain`: discovery CODE-READ (the corpus was enumerated rather than exercised)

## chunk2-24

- `id`: chunk2-24
- `entry`: 1381
- `claim`: RC's own reading, already written into CLAUDE.md, that the headless loop's single mandatory stop is the ARMING seam.
- `quote`: `The ARMING-only reading was deliberately relayed to RSC 2026-09-09 for refutation rather than asserted, and RSC refuted it`
- `refuter`: RSC's adversarial pass, enumerating seven concrete paths that reach another repository with nothing armed anywhere.
- `prevention`: ADVERSARY
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SIBLING
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 1 (SELF) - the replacement rule kept one carve-out pre-authorising a push to RC's own origin, and LEDGER 1382 deleted it the next day after RSC conceded that pre-authorising an own-origin push does not narrow seam (f) but REMOVES it; the second remedy (gate on diff CONTENT, not destination) stands.
- `uncertain`: origin_time INHERITED / UNDER-PROVEN (the ARMING reading was a defensible reading of an operator sentence rather than a plainly false statement)

## chunk2-25

- `id`: chunk2-25
- `entry`: 1383
- `claim`: the standing belief, after the 2026-09-07 public-flip scrub, that RC's own tree carried no sibling names.
- `quote`: `FIVE REAL ESCAPES in RC's own tree, all live in HEAD, and ALL FIVE ALREADY PUBLISHED to the public remote.`
- `refuter`: the newly built sweep run over the tree.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 1 (SELF) - four escapes were redacted at HEAD and the fifth was declared a KNOWN exception on the premise that its removal required a joint re-pin; that premise was later found false and the exception retired unilaterally.
- `uncertain`: fix_chain 0
- `pin_gap`: section 6 requires looking FORWARD at the remedy, but a chunked re-score has a forward horizon. This row's forward refutation lies OUTSIDE entries 1376-1386 (recorded in CLAUDE.md and in a later commit), so a scorer confined to the chunk would read it as 0. The pin should say whether fix_chain may be scored from evidence outside the scored window.

## chunk2-26

- `id`: chunk2-26
- `entry`: 1383
- `claim`: the spec's assumption that one combined git log call could yield both the name-status list and the patch.
- `quote`: `the combined single call shipped silently broken for one iteration and reported "0 file(s)" over a real 40-commit push`
- `refuter`: running it against a real push, where the empty result read exactly like a clean diff.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - split into two calls.

## chunk2-27

- `id`: chunk2-27
- `entry`: 1383
- `claim`: that a soft import of the sweep module in its own guard was an acceptable shape.
- `quote`: `turned "the guard does not exist" into a GREEN run, which is the same vacuity ADR-015 exists to stop`
- `refuter`: the build, checking whether an absent sweep and a clean tree could produce the same verdict.
- `prevention`: GATE-EXISTING
- `prevention_why`: VACUOUS - the guard was present and passed while measuring nothing whenever the module was absent.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the import is now hard.

## chunk2-28

- `id`: chunk2-28
- `entry`: 1383
- `claim`: that the sweep's own test file could spell drive-rooted synthetic paths out literally.
- `quote`: `the gate would have halted the very push that shipped it`
- `refuter`: the sweep's structural arm firing on its own test file, nine live hits.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the prefix is assembled at run time and the file text carries no drive-rooted path.

## chunk2-29

- `id`: chunk2-29
- `entry`: 1383
- `claim`: that a literal sentinel config could be spelled in the tests, as the first draft did.
- `quote`: `A literal SENTINEL config cannot be spelled either, which the first draft missed`
- `refuter`: the build, on the test that asserts this file is clean under the sentinel config.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - sentinel needles are generated at run time.

## chunk2-30

- `id`: chunk2-30
- `entry`: 1383
- `claim`: the spec's assumption that word-boundary matching carries over into the whitespace-stripped tight view.
- `quote`: `WORD BOUNDARIES ARE MEANINGLESS in the whitespace-stripped view - the tight view has no boundaries left to assert on`
- `refuter`: the build, which now re-applies the boundary against the ORIGINAL text before a tight-view hit counts.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0
- `uncertain`: prevention ADVERSARY

## chunk2-31

- `id`: chunk2-31
- `entry`: 1383
- `claim`: the spec's assumption that scanning the push content diff is sufficient coverage.
- `quote`: `A content diff alone misses a RENAME: it publishes a new path with NO content change.`
- `refuter`: the build, meeting the tree.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - three scanned sources instead of one.

## chunk2-32

- `id`: chunk2-32
- `entry`: 1383
- `claim`: the same sufficiency assumption, in its second failing case.
- `quote`: `A content diff alone also misses a COMMIT SUBJECT, which is published permanently while appearing in no diff at all`
- `refuter`: the build, meeting the tree.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0

## chunk2-33

- `id`: chunk2-33
- `entry`: 1383
- `claim`: that the structural arm's false positives could be handled by widening the allowlist.
- `quote`: `SIX live hits came from exactly that shape`
- `refuter`: the live run, where a JSON ability description parsed as a drive letter followed by a newline the drive-letter lookbehind cannot reach.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - a NAMED false-positive class shipped instead.

## chunk2-34

- `id`: chunk2-34
- `entry`: 1384
- `claim`: the gate's implied coverage of CI-log fetches, where one pattern required a literal binary token while its sibling in the same file already tolerated the .exe spelling.
- `quote`: `a CI-log fetch done the way this repo actually does it was never recognised`
- `refuter`: the RM-398 build, reading the two patterns side by side against RC's own prescribed invocation.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - measured 3 findings removed, 0 added, and the summary-line fence was verified by call path.
- `uncertain`: prevention GATE-EXISTING (prevention_why wrong scope)

## chunk2-35

- `id`: chunk2-35
- `entry`: 1384
- `claim`: RM-398's headline mechanism, that count_mismatch cannot distinguish a count asserted as SUCCESS from one asserted in a RED or mutation state.
- `quote`: `THE REAL HEADLINE IS THAT RM-398'S OWN MECHANISM IS REFUTED.`
- `refuter`: a mechanism probe plus an independent adjudicator, measuring 1354 paired runs and 312 of 347 red runs harvested normally, with 0 of 28 findings caused by red-ness.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - the row's POPULATION claim was upheld and re-measured; only its causal story was replaced.

## chunk2-36

- `id`: chunk2-36
- `entry`: 1384
- `claim`: the mechanism probe's counter-headline that the RED-state population is zero.
- `quote`: `the probe's counter-headline "the RED-state population is ZERO" is ITSELF REFUTED`
- `refuter`: the independent adjudicator, naming at least 9 of the 28 flagged sentences asserting a count inside an explicitly non-green state.
- `prevention`: ADVERSARY
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-37

- `id`: chunk2-37
- `entry`: 1384
- `claim`: the build's prediction that the CI-log spelling fix would remove 4 findings.
- `quote`: `FIX 2 was PREDICTED to remove 4 and removed 3`
- `refuter`: the verifier, showing one session correctly survives because its claimed count is not on a summary line in the fetched log.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the entry says plainly not to carry the 4 forward.

## chunk2-38

- `id`: chunk2-38
- `entry`: 1384
- `claim`: the probe's recommendation to credit counts by unioning observed_counts over the parent's subagent transcripts, on the reading that those 12 findings are false positives.
- `quote`: `SUBAGENT-INVISIBLE is the LARGEST TRUE-POSITIVE class in the corpus, not a false-positive class`
- `refuter`: the adjudicator, opening all 12 and finding 12 relay / 0 independent parent re-run, three of them figures the authoring session later retracted as wrong.
- `prevention`: ADVERSARY
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - both narrowed variants were rejected too, one for inverting the incentive.

## chunk2-39

- `id`: chunk2-39
- `entry`: 1384
- `claim`: the gate's implied handling of a quoted executable path, which collapsed only POSIX spellings to a basename.
- `quote`: `pre-existing at HEAD, untouched by this diff, found incidentally by the final verifier`
- `refuter`: the final verifier on the RM-398 wrap.
- `prevention`: GATE-ABSENT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0 - shipped as RM-400 in LEDGER 1385, measured 3 removed / 0 added and independently reproduced again in LEDGER 1386.

## chunk2-40

- `id`: chunk2-40
- `entry`: 1385
- `claim`: the RM-400 build's justifying sentence that the corpus held no backslash-spelled CI log fetch, so that half of the fix was unexercised.
- `quote`: `THE BUILD'S OWN JUSTIFYING SENTENCE WAS FALSE AND IS CORRECTED IN THE SAME COMMIT`
- `refuter`: an adversarial pass, with the probe reproduced at merge on a session that runs exactly that fetch.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 1 (SELF) - the correction called that session a LIVE POSITIVE CONTROL for the summary-line fence, and LEDGER 1386 refuted that too by reading the raw tool result: it is a genuine pytest summary hard-wrapped across three physical lines, so it is a false positive against a real summary, not a control.

## chunk2-41

- `id`: chunk2-41
- `entry`: 1385
- `claim`: RM-401's premise that the adjectival sense of "pushed" is a live false-positive source worth narrowing.
- `quote`: `RM-401 - REFUTED AS SCOPED, no code shipped, and the refusal is measured rather than argued.`
- `refuter`: a census re-derived independently by the merger and again by a verifier - 428 matches across 69 of 92 sessions, 6 live at turn granularity, of which the named shape is 1 and true positives are 0.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 1 (SELF) - the refute's own writeup claimed both named residuals carry no evasion surface, which was reproduced as false for the negation half before merge and corrected there.
- `pin_gap`: section 6 assumes the REMEDY for an event is a code fix. When the remedy for a badly-filed row is a REFUTATION WRITEUP, a false clause inside that writeup is ambiguous between fix_chain on the original event and a fresh event of its own. This file scored it as fix_chain; the pin does not say.

## chunk2-42

- `id`: chunk2-42
- `entry`: 1385
- `claim`: the entry's first draft, which wrote out the newly advanced next-free id numeral in prose.
- `quote`: `the registry's rule 3 grades a BARE MENTION as ALLOCATED, so naming the next-free id in prose is what TAKES it`
- `refuter`: the docs-guards run going red.
- `prevention`: GATE-FIRED-CAUGHT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0 - the entry now cites the pin's location and never its value.
- `pin_gap`: section 9 explicitly declines to resolve whether a claim is INHERITED when the durable record was published by THE SAME SESSION. This event sits in that hole - the id pin was advanced and then mis-recited within one session - and FRESH was chosen as the best reading.

## chunk2-43

- `id`: chunk2-43
- `entry`: 1386
- `claim`: RM-402's filed figures - 6 live false positives at turn granularity, 2 of them the non-git class.
- `quote`: `The row filed "6 live false positives at turn granularity, 2 of them this class".`
- `refuter`: a re-derived whole-gate histogram over a freshly frozen 93-file corpus, reproduced independently by three passes: zero live findings of that check, and a latent non-git population of 15 across 9 sessions.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0

## chunk2-44

- `id`: chunk2-44
- `entry`: 1386
- `claim`: RM-402's characterisation of the non-git population, led by the third-party repository-listing shape.
- `quote`: `THE DOMINANT NON-GIT CLASS IS NOT THE ONE THE ROW LEADS WITH`
- `refuter`: exhaustive classification: the drift-guard budget-overflow idiom is 10 of 15, the repository listing 1 of 15.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `fix_chain`: 0

## chunk2-45

- `id`: chunk2-45
- `entry`: 1386
- `claim`: RM-402's own suggested evidence-derived alternative, a bash-window discriminator around the claim.
- `quote`: `THE ROW'S OWN SUGGESTED EVIDENCE-DERIVED ALTERNATIVE MEASURED WORSE IN BOTH DIRECTIONS`
- `refuter`: measurement - 5 of 15 non-git uses have a push in the window anyway and 98 of 415 genuine uses have none, because the budget idiom is written during the wrap, which is exactly when pushes happen.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `fix_chain`: 0
- `uncertain`: origin_time INHERITED / BORN-WRONG

## chunk2-46

- `id`: chunk2-46
- `entry`: 1386
- `claim`: the narrowing slice's population of 6 non-git uses, enumerated with an idiom-shaped scan while the thing being evaluated was idiom-list narrowings.
- `quote`: `structurally incapable of measuring its own false negatives, and its false-negative column was therefore meaningless wherever it read 0`
- `refuter`: the merger refusing to average two disagreeing counts, grepping the corpus for the shapes the low count lacked, then an independent verifier re-deriving 15 by exhaustive classification.
- `prevention`: PROXY-MEASURE
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-47

- `id`: chunk2-47
- `entry`: 1386
- `claim`: the census slice's membership of the scored non-git population.
- `quote`: `its advocacy item "the amendment LW pushed for" occurs ZERO times in the scored population`
- `refuter`: the independent verifier, which also found a missed item, so the total is the census's and the composition is the verifier's.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `fix_chain`: 0

## chunk2-48

- `id`: chunk2-48
- `entry`: 1386
- `claim`: the hand-off note's inherited whole-gate baseline, which disagreed with the measured figure.
- `quote`: `the inherited baseline was pre-RM-400, and the difference is entirely those 3`
- `refuter`: replaying the pre-RM-400 gate side by side over the same frozen corpus.
- `prevention`: CONTRACT
- `prevention_why`: n/a (not GATE-EXISTING)
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `fix_chain`: 0


---

# chunk3 - RC re-score under LW REFUTATION_TAXONOMY_PIN v1.2

`fix_chain` DIRECTION APPLIED: **FORWARD**, per pin section 6 - the number of
times the REMEDY FOR THIS EVENT was itself subsequently refuted. An event is
scored as the DEFECT and the count looks forward at what its fix did. The
backward reading (scoring a row because it is itself somebody's second attempt)
was NOT used, and the refutation of a fix is not emitted as its own row.

Scope: LEDGER entries 1387 to 1396 inclusive. Rows only.

---

## chunk3-01

- `id`: chunk3-01
- `entry`: 1396
- `claim`: No test anywhere calls `lib/ddragon/fetch.py`'s own writer, so the RM-410 guard had no behavioural coverage to build on.
- `quote`: `Its directive's HEADLINE PREMISE was REFUTED before any code was written`
- `refuter`: The executing cycle, reading `tests/test_tracked_json_producers_emit_lf_bytes.py` and finding a parametrised behavioural half over all six producers.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: DECAYED
- `correct`: YES (defect_corrected: YES - the sentence was struck and corrected at source)
- `fix_chain`: 0

## chunk3-02

- `id`: chunk3-02
- `entry`: 1396
- `claim`: Patching `fetch_mod.os` scopes the fault injection to that module, so the `os.replace` shim is contained.
- `quote`: `` `fetch_mod.os` IS the stdlib `os` singleton - `lib.ddragon.fetch.os is os` -> `True`, proved by identity, not argued. ``
- `refuter`: The R230 directive plus an identity probe run in-cycle; corroborated four times over by the defect-class census.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `uncertain`: INHERITED
- `pin_gap`: The shim was authored in the same cycle's earlier commit, which is exactly the case pin section 9 flags as unresolved (INHERITED when the durable record was published by the same session). Scored FRESH.
- `correct`: YES (defect_corrected: YES - shim made destination-scoped with a control assertion inside the armed window)
- `fix_chain`: 0

## chunk3-03

- `id`: chunk3-03
- `entry`: 1396
- `claim`: The post-edit defect-class census found 30 real `os` patch call sites.
- `quote`: `a census whose pattern appears in the prose describing it drifts upward every time someone documents it`
- `refuter`: The verifier's post-edit census compared against the orchestrator's pre-edit run.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - resolved to 29 real sites plus 1 line of docstring prose)
- `fix_chain`: 0

## chunk3-04

- `id`: chunk3-04
- `entry`: 1396
- `claim`: Running under `-n 8` widens the exposure of a process-wide `os.replace` patch, which is why the fix is needed.
- `quote`: `pytest-xdist workers are separate PROCESSES and each runs its own tests SERIALLY, so `-n 8` does not widen the exposure at all`
- `refuter`: The executing cycle's own adversarial pass on its directive.
- `prevention`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - premise recorded as refuted so it is not re-filed; the work itself stood)
- `fix_chain`: 0

---

## chunk3-05

- `id`: chunk3-05
- `entry`: 1395
- `claim`: Every CI collection root is WIRED, so the excepted-roots arm has nothing to iterate.
- `quote`: `has nothing to iterate while every root is WIRED, which is the current state`
- `refuter`: This cycle's prose audit, reading `_COLLECTION_ROOTS:101` where a root is marked `_EXCEPTED`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: DECAYED
- `correct`: YES (defect_corrected: YES - docstring rewritten to state the arm's logic so it cannot re-stale on a flip in either direction)
- `fix_chain`: 0

## chunk3-06

- `id`: chunk3-06
- `entry`: 1395
- `claim`: The defect-class population for the stale-count prose is 1 instance, so the fix ships without a guard arm.
- `quote`: `the directive's own defect-class grep UNDER-MEASURED its population, and the verifier REFUTED the number rather than confirming it`
- `refuter`: An independent verifier running a wider digit-bearing and number-word scan.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `pin_gap`: The pin does not say whether N instances of one defect class surfaced by a single sweep are N events or 1. Scored as ONE event (the count refutation) covering all four fixed instances, to avoid double-counting against the population row.
- `correct`: YES (defect_corrected: YES - 4 fixed in total)
- `fix_chain`: 0

## chunk3-07

- `id`: chunk3-07
- `entry`: 1395
- `claim`: The two dispatched slices had a colliding write set, so parallel execution had to be refused.
- `quote`: `the override's stated collision did NOT hold on inspection`
- `refuter`: The merger, inspecting the two file sets and the override's own self-contradictory collision list.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: NO - serialization was kept anyway as strictly safer)
- `fix_chain`: 0

## chunk3-08

- `id`: chunk3-08
- `entry`: 1395
- `claim`: The backgrounded full-suite run measured the tree it was launched against.
- `quote`: `AGENT 2 landed two further fixes AFTER the merger had already measured the tree and launched the full suite, so that run straddled a live edit`
- `refuter`: The merger, before the run was reported.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `pin_gap`: The pin does not say whether a claim invalidated in flight and killed before publication is an event. Scored as one, because the claim existed and was contradicted.
- `correct`: YES (defect_corrected: YES - run killed and re-run on a frozen tree)
- `fix_chain`: 0

---

## chunk3-09

- `id`: chunk3-09
- `entry`: 1394
- `claim`: The four residuals published on the RM-407 row are RM-407's own stated limits.
- `quote`: `for one cycle RM-407 published four false residuals about itself`
- `refuter`: The cycle audit, which graded the prior wrap REGRESS.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - block moved back verbatim, byte-identity proved by sha256 on both sides)
- `fix_chain`: 0

## chunk3-10

- `id`: chunk3-10
- `entry`: 1394
- `claim`: `grep -c` on the duplicated next-free-id clause shows the repair was a no-op.
- `quote`: `the duplicate `Next free id = RM-410` sat TWICE on the SAME line, so `grep -c` reports `1` before and after the fix and reads as a clean no-op`
- `refuter`: The cycle's own re-measurement with `grep -o | wc -l`.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - counted 2 -> 1 with the correct predicate)
- `fix_chain`: 0

## chunk3-11

- `id`: chunk3-11
- `entry`: 1394
- `claim`: The guard file for the id registry is `tests/test_rm_id_registry.py`.
- `quote`: `It also named `tests/test_rm_id_registry.py`, which does not exist`
- `refuter`: The re-grounding pass, resolved with one directory listing.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `uncertain`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - real file `tests/test_rm_id_registry_drift.py` used)
- `fix_chain`: 0

---

## chunk3-12

- `id`: chunk3-12
- `entry`: 1393
- `claim`: The orphan-tree repair was in place at HEAD, with the agent3 tree wired under three named exclusions.
- `quote`: `the audit doc said WIRE-WITH-EXCLUSIONS naming three exclusions that appeared in no workflow file`
- `refuter`: The following cycle, which found HEAD running the tree bare inside a push-blocking job while the guard row read `_WIRED`.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the guard graded whether `ci.yml` names the tree, and its disposition row had been edited to agree with the wrong state, so it was self-consistent with it
- `uncertain`: VACUOUS
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - the tree is now declared EXCEPTED across gate, guard row and audit verdict)
- `fix_chain`: 0

## chunk3-13

- `id`: chunk3-13
- `entry`: 1393
- `claim`: The post-exclusion agent3 suite returns 0 failed and is fit to wire into a push-blocking job.
- `quote`: `run 1 returned **1 failed / 348 passed / 2 skipped / 2 deselected**`
- `refuter`: An independent verifier running the post-exclusion set three times rather than once.
- `prevention`: PROXY-MEASURE
- `uncertain`: CONTRACT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - tree declared EXCEPTED instead of wired)
- `fix_chain`: 0

## chunk3-14

- `id`: chunk3-14
- `entry`: 1393
- `claim`: The audit's section (c) denominator of 674 test functions.
- `quote`: `its section (c) denominator read 674 against a measured 675 (its own section (b) said 675)`
- `refuter`: The merger, correcting the audit body at merge rather than only in chat.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk3-15

- `id`: chunk3-15
- `entry`: 1393
- `claim`: The directive's enumeration command lists sixteen real test-tree directories.
- `quote`: `reports a PHANTOM sixteenth directory - bare `tools`, whose only match is `tools/pytest_guard.py``
- `refuter`: The build, inspecting what the enumeration actually matched.
- `prevention`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - the guard uses a basename-anchored predicate returning 15)
- `fix_chain`: 0

## chunk3-16

- `id`: chunk3-16
- `entry`: 1393
- `claim`: The live-write tracer's clean zero is evidence that the suite no longer writes the live tree.
- `quote`: `carries NO planted control, so a run whose patches intercept nothing reports a clean zero indistinguishable from a clean tree`
- `refuter`: The RM-407 audit, applying a lens a sibling tree had already used on its own equivalent control.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `uncertain`: SIBLING
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: NO - filed as RM-408, not repaired in window)
- `fix_chain`: 0

## chunk3-17

- `id`: chunk3-17
- `entry`: 1393
- `claim`: The path-watching census establishes that the suite does not mutate live operator state.
- `quote`: `Its clean "13 units over 1 path" figure is true and says nothing whatever about this class.`
- `refuter`: The RM-407 audit plus both slice agents, who tripped the live supervisor over a socket while working.
- `prevention`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES (defect_corrected: NO - filed as RM-409)
- `fix_chain`: 0

## chunk3-18

- `id`: chunk3-18
- `entry`: 1393
- `claim`: The ground truth handed to the two slices, including that a repo-root conftest does not reach the orphan trees.
- `quote`: `the ground truth handed to both slices was wrong in one half, since a repo-root `conftest.py` DOES reach both orphan trees`
- `refuter`: The merger at wrap.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - stated as a limit in the entry)
- `fix_chain`: 0

## chunk3-19

- `id`: chunk3-19
- `entry`: 1393
- `claim`: The next free RM id after this cycle is RM-408, per the directive's step 7.
- `quote`: `R227 STEP 7 said advance the id pin to RM-408, which was written before the two findings existed`
- `refuter`: The cycle itself, having minted two further ids during the work.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - pin advanced to RM-410, deviation reported rather than buried)
- `fix_chain`: 0

## chunk3-20

- `id`: chunk3-20
- `entry`: 1393
- `claim`: The wrap prose "the pin went to <id>" correctly announced an id as free.
- `quote`: `The guard was right and the prose was wrong - a sentence announcing an id as free has to say "free".`
- `refuter`: `tests/test_rm_id_registry_drift.py::NextFreeIdIsActuallyFree`, which graded the occurrence ALLOCATED and went red.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: RUN
- `pin_gap`: Section 3's seven discovery channels have no value for "a standing gate fired", which is the actual channel here; RUN is the nearest fit. Same gap applies to chunk3-42 and chunk3-45.
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - sentence reworded)
- `fix_chain`: 0

## chunk3-21

- `id`: chunk3-21
- `entry`: 1393
- `claim`: 0 vacuous rows over 675 test functions.
- `quote`: `rests on an AST detector and a proxy probe that were NOT committed, so nobody can re-run that zero`
- `refuter`: The merger, downgrading the figure to unreproducible rather than carrying it forward.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - flagged as unreproducible; the reproducible census was independently re-derived)
- `fix_chain`: 0

---

## chunk3-22

- `id`: chunk3-22
- `entry`: 1392
- `claim`: The CRLF-emitting writer defect was confined to the producers the narrow fix already addressed.
- `quote`: `An adversarial slice found two MORE producers with the identical shape that the narrow fix missed`
- `refuter`: An adversarial slice sweeping for the same shape.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `uncertain`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - all fixed, class guard shipped covering all six producers, red-first at 6 failures)
- `fix_chain`: 0

## chunk3-23

- `id`: chunk3-23
- `entry`: 1392
- `claim`: Removing any one write redirect turns the census guard file red.
- `quote`: `the guard's docstring claimed "removing any one redirect turns this file red" and a demonstrated mutation (narrowing `_tmp_log_path` for one filename) left it green`
- `refuter`: An adversarial slice, which returned BLOCK on the commit.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the guard reds on DELETING a redirect but not on NARROWING one, so the property it advertised was wider than the property it graded
- `uncertain`: VACUOUS
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - slogan replaced with four stated limits)
- `fix_chain`: 0

## chunk3-24

- `id`: chunk3-24
- `entry`: 1392
- `claim`: The tracer's `wrote_bytes` field counts bytes written.
- `quote`: `the tracer said `wrote_bytes` while measuring CHARACTERS for text handles - wrong in the undercounting direction by one byte per newline plus UTF-8 expansion`
- `refuter`: An adversarial slice.
- `prevention`: PROXY-MEASURE
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - renamed `wrote_units` with the unit stated)
- `fix_chain`: 0

## chunk3-25

- `id`: chunk3-25
- `entry`: 1392
- `claim`: The census report at the documented default path is the full census.
- `quote`: `the controller wrote an unsuffixed near-empty file at the documented default path, which looks like a clean census rather than a partial one`
- `refuter`: An adversarial slice.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - changed before commit)
- `fix_chain`: 0

## chunk3-26

- `id`: chunk3-26
- `entry`: 1392
- `claim`: The tracer's per-destination totals are correct.
- `quote`: `the tmp half of every atomic write was double-counted against its own destination`
- `refuter`: An adversarial slice.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk3-27

- `id`: chunk3-27
- `entry`: 1392
- `claim`: The tracer is an outside observer of the tree it polices.
- `quote`: `the default report path sat in `ops/runtime/`, making the instrument a writer in the tree it polices and excluded from its own count`
- `refuter`: An adversarial slice.
- `prevention`: PROXY-MEASURE
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk3-28

- `id`: chunk3-28
- `entry`: 1392
- `claim`: The tracer's patch of `builtins.open` is safely installed and removed.
- `quote`: `a raise between patching `builtins.open` and publishing `_state` would have left the process patched for its whole life`
- `refuter`: An adversarial slice.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `pin_gap`: The pin defines fields and exclusions but never defines an EVENT. This row is a latent instrument defect surfaced by an adversarial pass rather than a stated claim contradicted; whether such rows count is unpinned. Scored as an event because the shipped artifact's correctness was asserted and the assertion did not hold.
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

---

## chunk3-29

- `id`: chunk3-29
- `entry`: 1391
- `claim`: RM-312 made an in-process LCU fault visible.
- `quote`: `THE FIX RM-312 SHIPPED WAS ONE LAYER SHORT, AND THE LAYER ABOVE IT RE-SWALLOWED THE SAME FAULT.`
- `refuter`: This slice, reading the direct caller at `dashboard/_state_builder.py`.
- `prevention`: CONTRACT-MISFIRED
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES (defect_corrected: YES - caller seam now speaks, with its own lock, throttle and independent state)
- `fix_chain`: 0

## chunk3-30

- `id`: chunk3-30
- `entry`: 1391
- `claim`: The slice's own file:line citations point at the code they name.
- `quote`: `+83 lines near the top of `_state_builder.py` and +5 in `_lcu_inprocess.py` moved every offset below them`
- `refuter`: The first verifier pass; the author did not catch it.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 1
- `chain_kind`: SELF
  (the repo-wide re-derivation that remedied this did not reach `ROADMAP.md` or `BACKLOG.md`, and the RM-312 body there was still carrying pre-shift offsets; corrected in the same entry)

---

## chunk3-31

- `id`: chunk3-31
- `entry`: 1390
- `claim`: The in-process LCU path is a 1 Hz hot path producing about 3600 log lines an hour, which sizes the throttle.
- `quote`: `That comment is **pre-existing stale prose**: the real cadence is `RC_STATE_CADENCE_SEC`, default **0.5 s** with a 0.1 floor`
- `refuter`: An independent verifier, deriving the cadence from the setting rather than the comment.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - code stood, prose corrected, including inside the new test's own docstring)
- `fix_chain`: 1
- `chain_kind`: SELF
  (LEDGER 1391 records that the cadence justification RM-312 shipped was still wrong and had to be corrected at source rather than restated)
- `pin_gap`: Exclusion 1 covers recitals of refutations from OUTSIDE the window. This refutation is re-told inside the window at entry 1391; the pin does not say whether an in-window re-tell is a second event. Scored once, here, where it was first made.

## chunk3-32

- `id`: chunk3-32
- `entry`: 1390
- `claim`: All 9 guard arms went red pre-fix carrying the no-WARNING-logged message.
- `quote`: `the truth is **8** carry that message and the 9th is an `AttributeError``
- `refuter`: Verification at merge, re-reading the build's own red report.
- `prevention`: GATE-ABSENT
- `uncertain`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - 9/9 red retained as true, the message claim corrected)
- `fix_chain`: 0

## chunk3-33

- `id`: chunk3-33
- `entry`: 1390
- `claim`: The anti-vacuity control runs inside the same capture context as the assertion it controls.
- `quote`: `The control is a SEPARATE `with` block after `assertNoLogs` exits, not literally the same capture context as the build described.`
- `refuter`: An independent verifier reading the test source.
- `prevention`: ADVERSARY
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - description corrected; the control itself proved stronger than claimed)
- `fix_chain`: 0

## chunk3-34

- `id`: chunk3-34
- `entry`: 1390
- `claim`: The 7 citation offsets in the new guard file are correct.
- `quote`: `the build's own +83-line edit invalidated all 7 offsets in the citation block inside its OWN new test file`
- `refuter`: In-slice re-derivation before commit.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - fixed in-slice)
- `fix_chain`: 0

---

## chunk3-35

- `id`: chunk3-35
- `entry`: 1389
- `claim`: The printed `schtasks /Create` blocks in the module docstrings are pasteable working commands.
- `quote`: `PowerShell does not choke - it runs `schtasks /Create` STRIPPED OF ITS PAYLOAD and then a garbage command named `/TR``
- `refuter`: A measurement gate run ahead of any repair: a PowerShell AST parse returning errors=0 and statements=2 on four of five sites.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - repaired to `Register-ScheduledTask` form, with a parse-only guard)
- `fix_chain`: 0

## chunk3-36

- `id`: chunk3-36
- `entry`: 1389
- `claim`: The extractor found 11 embedded task-command blocks in the corpus.
- `quote`: `The builder's first extractor returned **11** blocks from 5 real commands - the extra 6 were its OWN English repair notes`
- `refuter`: The builder's own measurement, reproduced by a verifier with a deliberately loose pattern.
- `prevention`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - a block must now name its task on the same line, pinned by a dedicated arm)
- `fix_chain`: 0

## chunk3-37

- `id`: chunk3-37
- `entry`: 1389
- `claim`: The docstring text as it appears in the source file is what an operator should paste.
- `quote`: `pasting from the source file rather than from `help()` yields doubled backslashes`
- `refuter`: The slice, comparing the non-raw source form against the rendered form.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: NO - flagged to the operator, declared pre-existing and out of scope)
- `fix_chain`: 0

---

## chunk3-38

- `id`: chunk3-38
- `entry`: 1388
- `claim`: The session's hand-off fallback, that RM-387 or RM-388 are open work to pick up.
- `quote`: `**RM-387 and RM-388 had BOTH SHIPPED on 2026-09-08**, LEDGER 1368 and 1369`
- `refuter`: The session itself, proving both in source before acting.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the recall gate fires on the ASK, and here the stale claim sat in the FALLBACK, which no gate covered
- `discovery`: CODE-READ
- `uncertain`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - four ROADMAP dispositions repaired and a drift guard shipped)
- `fix_chain`: 0

## chunk3-39

- `id`: chunk3-39
- `entry`: 1388
- `claim`: The ROADMAP disposition rows for RM-250 and RM-291 reflect their real state.
- `quote`: `RM-250 sat in a SHIPPED/CLOSED pointer cluster and in an OPEN row simultaneously`
- `refuter`: A census derived twice by different methods, the second adversarial and corroborated per row by a LEDGER entry and a code probe.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES)
- `fix_chain`: 0

## chunk3-40

- `id`: chunk3-40
- `entry`: 1388
- `claim`: RM-204 is a fifth disposition-drift row.
- `quote`: `The build's first parser reported **RM-204 as a fifth drift row**`
- `refuter`: Hand inspection of the row, which showed the first vocabulary hit sitting deep in lowercase prose.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `pin_gap`: Exclusion 4 covers a hypothesis opened by a probe whose purpose was to test it and cleared as that probe's intended output. This is a false positive that forced the INSTRUMENT to be narrowed, which reads as an instrument defect rather than a cleared hypothesis. Scored as an event; the neighbouring verifier parser artifact (RM-281 / RM-283) was EXCLUDED under exclusion 4 on the same boundary, so the boundary is doing real work and is not pinned.
- `correct`: YES (defect_corrected: YES - parser narrowed, never allowlisted; RM-204 carries its own pinned control)
- `fix_chain`: 0

## chunk3-41

- `id`: chunk3-41
- `entry`: 1388
- `claim`: The dispatch's own warning that RM-403 must not appear in any tracked `.md` or the registry guard would break.
- `quote`: `It already appeared - `docs/DS_SWEEP_TRACKER.md:72`, pre-existing from the RM-402 filing - and the guard was green with it present`
- `refuter`: The verifier, correcting the dispatcher.
- `prevention`: ADVERSARY
- `pin_gap`: No section 2 value covers "an existing gate was CORRECT and a claim ABOUT the gate's behaviour was wrong". GATE-EXISTING requires that the check could have FAILED on the defect, and here the check passing is precisely what refuted the claim; none of wrong scope / wrong time / VACUOUS describes it. Scored ADVERSARY.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the rule restated as cite the pin's location, never its value)
- `fix_chain`: 0

## chunk3-42

- `id`: chunk3-42
- `entry`: 1388
- `claim`: The md guard selector's documented IO-call requirement describes how modules are selected.
- `quote`: `the selector's documented IO-call requirement is **STALE** - it dropped `test_doc_size_budget.py` and mere reference now selects`
- `refuter`: A live CI-routing probe run this session.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES (defect_corrected: YES - recorded as stale)
- `fix_chain`: 0

---

## chunk3-43

- `id`: chunk3-43
- `entry`: 1387
- `claim`: Q5 is unanswered and a reply to it should be drafted.
- `quote`: `THE Q5 ASK WAS REDISCOVERY AND THE RECALL GATE CAUGHT IT.`
- `refuter`: The recall gate, which surfaced the closure at LEDGER 1370 (RM-389, 2026-09-08).
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `uncertain`: RUN
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - the existing answer was relayed byte-identically rather than re-answered)
- `fix_chain`: 0

## chunk3-44

- `id`: chunk3-44
- `entry`: 1387
- `claim`: The `!agents/state/resolved_decisions.json` negation protects that file from the ignore rule above it.
- `quote`: `The `!` line was present, read as protection, and did nothing`
- `refuter`: The ignored-tracked probe plus hand verification in both directions.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES (defect_corrected: YES - rewritten to the contents form, red-before-green proven, new guard shipped)
- `fix_chain`: 0

## chunk3-45

- `id`: chunk3-45
- `entry`: 1387
- `claim`: The first spot-check table of which gitignore negations are effective.
- `quote`: `My first spot-check table was wrong in every row and reported two effective negations as ignored`
- `refuter`: In-session re-derivation after finding that `git check-ignore -v` exits 0 on a negation match too.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES (defect_corrected: YES - corpus count re-derived with the correct predicate and came back unchanged, confining the error to the hypothetical-path probes)
- `fix_chain`: 0

## chunk3-46

- `id`: chunk3-46
- `entry`: 1387
- `claim`: A sibling's suite figures stated as though observed on this tree.
- `quote`: `A COUNT RELAYED FROM A SIBLING WAS STATED AS THOUGH OBSERVED HERE, and the stop gate caught it`
- `refuter`: `tools/stop_claim_gate.py`.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES (defect_corrected: YES - corrected in-session rather than at wrap)
- `fix_chain`: 0

## chunk3-47

- `id`: chunk3-47
- `entry`: 1387
- `claim`: A sibling had re-armed its responder, as the operator expected.
- `quote`: `**Nobody's responder is armed**, and RSC/CS/LL are silent.`
- `refuter`: Live measurement of arm status across the participating trees.
- `prevention`: CONTRACT
- `discovery`: RUN
- `origin_time`: FRESH
- `pin_gap`: Section 4 offers FRESH (this session's own work) or INHERITED (a durable record). A claim originating from the OPERATOR in-session is neither; scored FRESH for want of a value.
- `correct`: YES (defect_corrected: YES - the sibling had re-armed as a correspondent only, and its responder is built and deliberately not armed)
- `fix_chain`: 0


---

# RC re-score, chunk 4 - LEDGER entries 1397 to 1406

## Method (not a tally - totals are deliberately left to the caller)

- **`fix_chain` DIRECTION APPLIED: FORWARD, per pin section 6.** Section 6 was read
  twice. The event is scored as the DEFECT, and `fix_chain` counts how many times
  THE REMEDY FOR THAT EVENT was itself subsequently refuted. `0` means the first
  remedy stood. No event here is scored as a fix-of-a-fix merely because it is
  somebody's second attempt - that is the backward reading the pin forbids.
- **Event definition applied:** a point where a CLAIM made in the course of the work
  was contradicted, corrected, retracted or found wrong. A pre-existing code bug with
  no stated antecedent claim is NOT scored as an event here. See the `pin_gap` on
  chunk4-25: pin section 6 says "score the event as the DEFECT", which arguably
  widens this, and the two readings give different counts.
- **Entry 1405 yields ZERO rows.** Its content is the verification of a sibling
  carrier's relayed finding. The headline and claims 1 and 2 are external-origin
  claims this tree never adopted (exclusion 2) and the headline additionally fits
  exclusion 5 exactly - this tree's own correct action (RM-406, already an ancestor of
  HEAD) is what made the other tree's record false. Claim 3 was CONFIRMED, not
  refuted. The remaining candidates inside it (the `ROOT` literal ruled LATENT, the
  `core/hot_reload.py:18` docstring non-member) are hypotheses opened by the probe
  that cleared them, exclusion 4.
- Other exclusions applied: exclusion 1 (recitals) removed entry 1403's cycle-12
  citation and entry 1399's RM-406 pin-move recital; exclusion 4 removed entry 1397's
  rejected re-pointing candidate and entry 1401's five checked-and-excluded route
  sites.

---

## chunk4-01

- `id`: chunk4-01
- `entry`: 1397
- `claim`: The `tests/` tree was too slow to run inside a loop cycle, so cycle 7 shipped without running it.
- `quote`: `cycle 7 shipped without running the suite, because a prior serial run had been measured at roughly four hours`
- `refuter`: This cycle's own full `tests/` run under `-n 8`, finishing in 307 seconds.
- `prevention`: CONTRACT
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-02

- `id`: chunk4-02
- `entry`: 1397
- `claim`: Cycle 7's work was green when it shipped.
- `quote`: `A GUARD WAS ALREADY RED WHEN THIS CYCLE STARTED`
- `refuter`: Cycle 74's full `tests/` tree run.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the survival guard was already present and already failing at `7ff5fc853`, but the suite was not run at cycle 7.
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-03

- `id`: chunk4-03
- `entry`: 1397
- `claim`: The existing survival guard protects the newest session row in the director context window.
- `quote`: `the survival guard only reds AFTER the row has already fallen out`
- `refuter`: The slice's own analysis while building the replacement headroom arm.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - it grades the right property but only after the row has already been cut, so it cannot prevent the loss it detects.
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-04

- `id`: chunk4-04
- `entry`: 1397
- `claim`: The audit doc's citation to `ORCHESTRATION_PLAN.md:916-919` resolved to the sentence it quoted.
- `quote`: `the citation was ALREADY content-stale before this change`
- `refuter`: The baselining check run this cycle, resolving the range at 948 lines.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: NO - baselined historical rather than re-pointed, deliberately.
- `fix_chain`: 0

## chunk4-05

- `id`: chunk4-05
- `entry`: 1398
- `claim`: The lane-8 directive claimed `dashboard/_state_builder.py` pays a duplicate `/activeplayerrunes` fetch tax.
- `quote`: ``"duplicate `/activeplayerrunes` tax" REFUTED``
- `refuter`: The slice's own triage pass before any code was written.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-06

- `id`: chunk4-06
- `entry`: 1398
- `claim`: The directive claimed `PolledJsonFile` should be moved onto `NamedMutex`.
- `quote`: ``"`PolledJsonFile` onto `NamedMutex`" REFUTED``
- `refuter`: The slice's triage - `core/polled_json.py:204` records zero production instantiations and `ops/loop/winmutex.py` has no such class.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-07

- `id`: chunk4-07
- `entry`: 1398
- `claim`: The directive claimed orphan-tree wiring was outstanding work.
- `quote`: `orphan-tree wiring = RM-407 and split-form sibling scanner = RM-399, ALREADY SHIPPED`
- `refuter`: The slice's triage against shipped ledger state.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-08

- `id`: chunk4-08
- `entry`: 1398
- `claim`: The directive claimed a split-form sibling scanner was outstanding work.
- `quote`: `orphan-tree wiring = RM-407 and split-form sibling scanner = RM-399, ALREADY SHIPPED`
- `refuter`: The slice's triage against shipped ledger state.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-09

- `id`: chunk4-09
- `entry`: 1398
- `claim`: The directive implied the `SHARED_SHA256` pins had drifted from the live bytes.
- `quote`: ``pins MATCH live bytes``
- `refuter`: The slice re-running the byte pin.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - `tests/test_loop_concurrency.py` pins exactly this and would have answered the claim before it entered a directive.
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-10

- `id`: chunk4-10
- `entry`: 1398
- `claim`: BACKLOG RM-234 and LEDGER 1117 claimed there is no production consumer of `my_runes`.
- `quote`: ``BACKLOG RM-234 + LEDGER 1117 claimed "no production consumer of `my_runes`" - FALSE``
- `refuter`: The slice's consumer census - `coaches/aram_coach.py:430` templates it and `:1031` feeds Haiku.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `uncertain`: BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-11

- `id`: chunk4-11
- `entry`: 1398
- `claim`: Directive hypothesis H2 against `item_advisor.py` was a real defect.
- `quote`: `H2 REFUTED`
- `refuter`: Slice E's probe.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: exclusion 4 turns on WHO opened the hypothesis. The entry names H1/H2/H3 without saying whether they were filed in the directive or raised by the probe that cleared them. Scored as an event on the reading that the directive opened them, consistent with the five triage rows above.

## chunk4-12

- `id`: chunk4-12
- `entry`: 1398
- `claim`: The new `RC_ATOMIC_WRITE_GATE` could run in block mode over net-new staged runtime lines.
- `quote`: `BLOCK MODE NOT VIABLE YET - that is the finding`
- `refuter`: The slice's own back-test - strict 4 hits / 2 files, lenient 11 / 9, with named false negatives and false positives.
- `prevention`: GATE-ABSENT
- `uncertain`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: NO - shipped warn-by-default instead.
- `fix_chain`: 0

## chunk4-13

- `id`: chunk4-13
- `entry`: 1398
- `claim`: A mis-typed `win_pct` input crashes the frozen state authority.
- `quote`: ``already caught the crash; effect: STALE `win_pct` ``
- `refuter`: The slice's call-path read of `app/_game_lifecycle.py:465-467`.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: the entry records the corrected effect without restating the antecedent claim in full, so event-hood rests on the word "already". The pin gives no rule for a correction whose antecedent is implied rather than quoted.

## chunk4-14

- `id`: chunk4-14
- `entry`: 1399
- `claim`: The builder reported the RM-412 slice all green.
- `quote`: `AN INDEPENDENT VERIFIER REFUTED THE BUILDER'S "ALL GREEN" and found a hard red the builder never reported`
- `refuter`: An independent read-only verifier.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the `docs/OPERATIONS.md` test-scope guard is present and self-declared authoritative, and the builder did not run it.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - fixed in the same commit.
- `fix_chain`: 0

## chunk4-15

- `id`: chunk4-15
- `entry`: 1399
- `claim`: 317 passed across 16 repo-root-enumerating guards proved the new package tree clean.
- `quote`: `the builder ran 16 repo-root-enumerating guards and got **317 passed**, proving NOTHING`
- `refuter`: A `git add -N` re-run, which surfaced 2 real failures.
- `prevention`: GATE-EXISTING
- `prevention_why`: VACUOUS - the guards enumerate the git index per ADR-015 and the new files were untracked, so every one of them passed while measuring nothing.
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-16

- `id`: chunk4-16
- `entry`: 1399
- `claim`: The package was swept clean of sibling names across 31 banned identifiers in three variants.
- `quote`: ``THE ONE REAL SIBLING-NAME LEAK WAS IN `__pycache__`, NOT SOURCE.``
- `refuter`: The slice's own publish-shape check, which found `.pyc` files embedding the absolute repo path.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the sibling-name sweep reads tracked source, and the leak sat in untracked bytecode invisible to a git publish but shipped by a tar or cp -r publish.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES, with the entry stating the residual is transient because any pytest run repopulates `__pycache__`.
- `fix_chain`: 0

## chunk4-17

- `id`: chunk4-17
- `entry`: 1399
- `claim`: The new package could declare itself all-rights-reserved and not yet distributable.
- `quote`: `the package declared itself all-rights-reserved and "not yet distributable" while sitting in a PUBLIC repo`
- `refuter`: The slice's own license-gate pass before the package mattered.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - byte-identical Apache-2.0 copy plus three guards.
- `fix_chain`: 0

## chunk4-18

- `id`: chunk4-18
- `entry`: 1399
- `claim`: The package README claimed exactly one degraded input is swallowed silently.
- `quote`: `the README claimed ONE degraded input was silent when **TWO** are`
- `refuter`: The slice re-reading the `OSError` branch against the prose.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: the pin fixes no granularity rule. The three README corrections in this entry share one artifact, one author and one pass, and are equally defensible as one event or three. Scored as three (chunk4-18, -19, -20) because each is a distinct false proposition.

## chunk4-19

- `id`: chunk4-19
- `entry`: 1399
- `claim`: The package README claimed the replace retry simply never fires on POSIX.
- `quote`: ``it claimed the retry "simply never fires" on POSIX when a bare `PermissionError` catch means **`EACCES` DOES fire it**``
- `refuter`: A measured ACL-denial run - 4 attempts, roughly 275 ms.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-20

- `id`: chunk4-20
- `entry`: 1399
- `claim`: The package README claimed a scratch file is never left behind.
- `quote`: ``"never left behind" is true for raised exceptions and **FALSE** for `SIGKILL` / `taskkill /F` / power loss``
- `refuter`: The slice re-deriving the guarantee from the code paths.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-21

- `id`: chunk4-21
- `entry`: 1399
- `claim`: The repo's root `.gitattributes` covered the new package, so a local green meant a green fresh clone.
- `quote`: ``the root `.gitattributes` pins only `*.py` / `*.md`, so the new `.gitignore` would have checked out CRLF in a fresh clone``
- `refuter`: The slice's own clone-shape reasoning against `core.autocrlf=true`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - package-local `.gitattributes` pinning `eol=lf`.
- `fix_chain`: 0

## chunk4-22

- `id`: chunk4-22
- `entry`: 1400
- `claim`: The shipped test pins the non-WAL warning check the way RM-233's acceptance asked.
- `quote`: ``the non-`wal` WARN branch is UNFALSIFIABLE ON THIS HOST``
- `refuter`: The slice's own caveat, corroborated by the independent verifier.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: NO - the test pins the pragma READ; the emit half has never been observed firing.
- `fix_chain`: 0

## chunk4-23

- `id`: chunk4-23
- `entry`: 1401
- `claim`: RM-296d's filed row claimed that mapping the string "false" to False invents a JSON convention the rest of the API does not use.
- `quote`: `"invents a JSON convention the rest of the API does not use". It does not invent one`
- `refuter`: The slice's precedent search, which found the convention already in `dashboard/routes_diag.py:347-350`.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-24

- `id`: chunk4-24
- `entry`: 1402
- `claim`: RM-313's fence claimed that coercing `championId` risks breaking JS consumers that currently strict-compare strings.
- `quote`: `That census was run, and it inverted the expected risk.`
- `refuter`: The slice's census over the `web/js` consumers - zero unsafe-on-int, two unsafe-on-string.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-25

- `id`: chunk4-25
- `entry`: 1402
- `claim`: The string-`championId` consumer exposure was hypothetical.
- `quote`: `a string id silently badged the **WRONG ARENA PLAYER AS ME** - a live rendering defect, not a hypothetical`
- `refuter`: The same consumer census, reading `web/js/panels/champ_select.js:3516`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES, partially
- `fix_chain`: 1
- `chain_kind`: SIBLING-SURFACE
- `pin_gap`: two gaps meet here. (a) The remedy was found incomplete in the SAME session that shipped it - `arena_teams()` at `:195` is read first and stays uncoerced - and the pin does not say whether a same-session limitation counts as the remedy being "subsequently refuted". Scored as 1 on the reading that it does. (b) Pin section 6 says "score the event as the DEFECT", which would admit bare code defects with no antecedent claim as events; the task's definition would not. This row is scored under the task's definition because the entry explicitly contradicts the filed "hypothetical" framing.

## chunk4-26

- `id`: chunk4-26
- `entry`: 1402
- `claim`: RM-313's acceptance claimed `championId` and its sibling fields could be coerced in one pass.
- `quote`: `THE ROW'S ONE-PASS ACCEPTANCE IS DELIBERATELY NOT MET`
- `refuter`: The per-field census result, which found two live consumer defects on one field and did not generalise.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES
- `defect_corrected`: NO - siblings filed as RM-417 rather than shipped.
- `fix_chain`: 0

## chunk4-27

- `id`: chunk4-27
- `entry`: 1403
- `claim`: RM-318's acceptance scope - the six detectors - covered the severe case.
- `quote`: `THE SEAM REACHES ONE SITE THE FILED ROW DID NOT ASK FOR, AND THAT SITE IS THE SEVERE ONE.`
- `refuter`: The slice reading `DecisionLoop._loop`, whose `gameTime` read sits outside the per-detector try/except and kills the whole tick.
- `prevention`: CONTRACT
- `uncertain`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES - the shipped coercion covers that read too.
- `fix_chain`: 0

## chunk4-28

- `id`: chunk4-28
- `entry`: 1404
- `claim`: RM-295a's premise claimed the only signal on a frozen duo-synergy snapshot is a log.warning.
- `quote`: ``the row's own premise that "the only signal is a `log.warning`" was itself optimistic on one of the three paths``
- `refuter`: The slice's three-freeze-path audit - the `_refresh` except handler logged nothing at all.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 1
- `chain_kind`: SELF
- Note on the chain: the remedy, `health()`, was found in the same entry to have no consumer at all, filed as RM-416, and the entry names that as a repeat of RM-295b's own mistake.

## chunk4-29

- `id`: chunk4-29
- `entry`: 1404
- `claim`: RM-295a's parenthetical defined `stale_for_s` as now minus `_LOADED_AT`.
- `quote`: `THE FILED SPEC WAS WRONG AND IS CORRECTED RATHER THAN FOLLOWED`
- `refuter`: The slice, finding `_LOADED_AT` is the RETRY stamp, so the literal spec reads 0 during the exact outage it exists to report.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - measured from `_LAST_GOOD_AT` while keeping the row's key names.
- `fix_chain`: 0

## chunk4-30

- `id`: chunk4-30
- `entry`: 1404
- `claim`: RM-295a's fence claimed `dashboard/routes_duo_synergy.py` and the UI badge both read `source()`.
- `quote`: `BOTH HALVES ARE FALSE AT HEAD`
- `refuter`: The merger's independent re-probe - zero `source()` calls there and no non-test caller repo-wide.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNKNOWN
- `uncertain`: DECAYED
- `correct`: YES
- `defect_corrected`: YES - the reason was replaced and the fence deliberately kept on other ground.
- `fix_chain`: 0

## chunk4-31

- `id`: chunk4-31
- `entry`: 1404
- `claim`: A `stale:live` / `stale:static` prefix on `source()` was the right way to surface staleness; it shipped in slice `95c5fa2fa`.
- `quote`: `THE PREFIX EXPERIMENT WAS BUILT, MEASURED AND DELIBERATELY REFUSED AT MERGE`
- `refuter`: The merge-time adjudication, on the ground that shipping it required widening the lock test that exists to forbid it.
- `prevention`: GATE-FIRED-IGNORED
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - reverted in `b51b05092`, lock test byte-identical across both slice commits, plus an inverted test asserting the prefix is absent.
- `fix_chain`: 0

## chunk4-32

- `id`: chunk4-32
- `entry`: 1404
- `claim`: The merger's verifier prompt claimed the revert restored `source()` byte-for-byte.
- `quote`: ``the verifier prompt claimed the revert restored `source()` "byte-for-byte", and that was REFUTED as worded``
- `refuter`: The independent verifier - the function text grew from 162 to 1573 chars.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - restated as AST-identical body with an unchanged return domain.
- `fix_chain`: 0

## chunk4-33

- `id`: chunk4-33
- `entry`: 1406
- `claim`: BACKLOG RM-217 stood OPEN, prescribing a `RETRACTED:` marker the stop-claim scanner honours.
- `quote`: `THE FIRST FINDING IS THAT THE ROW WAS ALREADY DEAD.`
- `refuter`: This slice's row-age check against RM-396 (REFUTED, 2026-09-09) and RM-398 in the same file.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES - RM-217 closed.
- `fix_chain`: 0

## chunk4-34

- `id`: chunk4-34
- `entry`: 1406
- `claim`: The filed rows recited the transcript corpus size as 90 / 91 / 92 / 93.
- `quote`: `the rows above recite 90 / 91 / 92 / 93 and every one of them is now stale`
- `refuter`: This run's re-derivation - 123 frozen transcripts, 0 parse errors.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-35

- `id`: chunk4-35
- `entry`: 1406
- `claim`: A loose retraction rule - a retraction verb anywhere in a sentence naming the number - would clear genuine retractions.
- `quote`: `4 of the 5 cleared are OFF-TARGET`
- `refuter`: Corpus scoring over 123 frozen transcripts, including three pure collisions where nothing was retracted and RM ids parsing as numbers.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: FRESH
- `correct`: YES
- `defect_corrected`: YES - variant A refused.
- `fix_chain`: 0

## chunk4-36

- `id`: chunk4-36
- `entry`: 1406
- `claim`: Tightening the retraction rule to the 40-char `_negated` window makes it both safe and useful.
- `quote`: `Precision 0 of 1, recall 0 of 1 on the target class.`
- `refuter`: The same corpus scoring - the one finding it clears is a true positive and not a retraction.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - variant B refused.
- `fix_chain`: 0

## chunk4-37

- `id`: chunk4-37
- `entry`: 1406
- `claim`: A retraction always self-flags by re-spelling the figure.
- `quote`: `The first draft asserted that a retraction always self-flags by re-spelling the figure; it was RED against the real gate`
- `refuter`: The real gate - `CLAIM_COUNT` wants `passed`, so only a retraction that QUOTES the figure self-flags.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-38

- `id`: chunk4-38
- `entry`: 1406
- `claim`: The brief's "six consecutive Stops" figure, written into a tracked source comment.
- `quote`: `the brief's "six consecutive Stops" figure was written into a tracked source comment before being checked`
- `refuter`: The slice checking `ops/runtime/stop_claim_history.jsonl`, whose rows carry counts and check names but not the quotes.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNDER-PROVEN
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES - attributed to the brief rather than asserted, with the measured figures in the comment.
- `fix_chain`: 0

## chunk4-39

- `id`: chunk4-39
- `entry`: 1406
- `claim`: The gate's armed emit told sessions to retract, a remedy the file implements.
- `quote`: ``the armed emit read "Fix or retract, then finish" - half of it naming a remedy `audit()` does not implement and never did``
- `refuter`: This slice reading `audit()`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - one-string correction, `audit()` untouched and frozen-corpus figures identical on both sides.
- `fix_chain`: 0

## chunk4-40

- `id`: chunk4-40
- `entry`: 1406
- `claim`: The verifier claimed the mid-run modified-file movement came from another session.
- `quote`: `it reported the tree going 3 -> 6 modified files mid-run and attributed it to another session. It was this one.`
- `refuter`: The merger, recording the process caveat rather than smoothing it over.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - every measurement re-run against the current bytes, with the entry stating the second pass is what is relied on.
- `fix_chain`: 0

## chunk4-41

- `id`: chunk4-41
- `entry`: 1406
- `claim`: RM-396 left an evidence-bearing retraction defensible as an escape hatch.
- `quote`: `ITS ADVERSARIAL PASS CLOSED THE ONE ESCAPE HATCH RM-396 HAD LEFT OPEN.`
- `refuter`: The adversarial verifier - the attack transcript already contains a real green run, so any evidence-keyed rule silences the fabrication too.
- `prevention`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES - the space collapses to an external human.
- `fix_chain`: 0

## chunk4-42

- `id`: chunk4-42
- `entry`: 1406
- `claim`: Entry 1405's own "pin advanced" parenthetical, naming the next-free id, was clean.
- `quote`: ``was ALREADY RED at `9b4bb834d`, on exactly this shape, from entry 1405's own "pin advanced" parenthetical``
- `refuter`: `tests/test_rm_id_registry_drift.py::test_the_pinned_next_free_id_is_not_allocated_anywhere`.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the guard was present and would have failed at 1405's own commit, but was not observed until this run.
- `uncertain`: GATE-FIRED-IGNORED
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - cleared by advancing the pin past the now genuinely allocated id.
- `fix_chain`: 0

## chunk4-43

- `id`: chunk4-43
- `entry`: 1406
- `claim`: The stop-claim gate covers a fabricated count.
- `quote`: ``records an edit's `file_path` and NEVER its content, so a fabricated count written into a tracked file draws zero findings``
- `refuter`: The slice's own three-case control - chat-only 1 finding, file-only 0, both 1.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - `collect_evidence` reaches chat text and edit paths but never edit content, so the laundering route is unmeasured.
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: NO - spun off as RM-421, explicitly do not fold back.
- `fix_chain`: 0


---

