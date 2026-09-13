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
