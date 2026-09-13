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
