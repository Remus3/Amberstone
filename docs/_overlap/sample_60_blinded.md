# RC overlap sample - 60 blinded rows

**Generated BEFORE any scorer read a row. Do not edit.** Companion file:
`docs/_overlap/PREREGISTRATION.md`, which states the question, the
instrument, the selection rule and the pre-committed confirm/refute
conditions. Read that first.

Source corpus: `docs/_rescore/chunk{1,2,3,4}_rows.md`, 198 rows, parsed
with `docs/_rescore/tally.py`'s own `split_blocks` + `parse_fields` so the
row universe is identical to the one the tally reports.

## Selection rule - deterministic, no RNG, no seed

Reproduce it in any language:

1. Parse the four chunk files in order chunk1, chunk2, chunk3, chunk4.
   Row order within a file is file order. Sizes: chunk1 60, chunk2 48, chunk3 47, chunk4 43 = 198.
2. Apportion 60 across the four chunks by LARGEST REMAINDER (Hamilton) on
   chunk size, so the sample is stratified in proportion to chunk size:

       chunk1  n=60   exact quota 18.1818  allocated 18
       chunk2  n=48   exact quota 14.5455  allocated 15
       chunk3  n=47   exact quota 14.2424  allocated 14
       chunk4  n=43   exact quota 13.0303  allocated 13

       total allocated 60

3. Within a chunk of n rows with quota k, take the rows at 1-based
   positions `floor(i*n/k) + 1` for `i = 0 .. k-1`. This is a stated
   every-Nth stride, evenly spread over the whole chunk. No seed is used
   and none is needed - the rule is arithmetic and has one output.
4. Emission order is INTERLEAVED, never blocked. Each selected row carries
   its 0-based rank `i` within its chunk's selection; sort all 60 by
   `(i / k, chunk_index)` ascending. That rotates chunk1, chunk2, chunk3,
   chunk4 down the file, so no scorer meets one chunk as a contiguous run
   and within-run drift cannot align with chunk position.

## Blinding

Each row carries ONLY `id`, `entry`, `claim`, `quote`, `refuter`, and an
`uncertain` presence FLAG where RC's extraction carried one. Removed:
`prevention`, `prevention_why`, `discovery`, `origin_time`, `correct`,
`fix_chain`, `chain_kind`, `pin_gap`.

**The `uncertain` BODY is removed as well, and that is a deliberate
departure worth stating.** RC's `uncertain` notes are the extractor's own
second-choice reasoning and 31 of RC's 56 of them NAME a candidate value
outright (for example `prevention GATE-FIRED-CAUGHT`). Carrying that text
would hand a scorer RC's read and destroy the blinding the sample exists
to create. The FLAG is kept because it is a property of the row's
difficulty rather than of RC's answer.

## Rows

## chunk1-01

- `id`: chunk1-01
- `entry`: 1375
- `claim`: RM-393's filed citations to its four consumer lines named line numbers that were valid before this session's own edit to the same file.
- `quote`: `every consumer line RM-393 cites moved by exactly 55`
- `refuter`: the session itself, re-deriving the citations after the last edit against `git diff --numstat`.

## chunk2-01

- `id`: chunk2-01
- `entry`: 1376
- `claim`: RM-394's filed premise that the repo-root enumeration universe (git index versus os.walk minus check-ignore) was still an open decision to be made.
- `quote`: `THE DECISION THE ROW POSED WAS ALREADY ANSWERED IN CODE, AND FINDING THAT OUT WAS THE FIRST ACT.`
- `refuter`: the RM-394 executor's own first-act read of the tree, finding tests/_repo_walk.py already implementing the answer with four consumers.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk3-01

- `id`: chunk3-01
- `entry`: 1396
- `claim`: No test anywhere calls `lib/ddragon/fetch.py`'s own writer, so the RM-410 guard had no behavioural coverage to build on.
- `quote`: `Its directive's HEADLINE PREMISE was REFUTED before any code was written`
- `refuter`: The executing cycle, reading `tests/test_tracked_json_producers_emit_lf_bytes.py` and finding a parametrised behavioural half over all six producers.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk4-01

- `id`: chunk4-01
- `entry`: 1397
- `claim`: The `tests/` tree was too slow to run inside a loop cycle, so cycle 7 shipped without running it.
- `quote`: `cycle 7 shipped without running the suite, because a prior serial run had been measured at roughly four hours`
- `refuter`: This cycle's own full `tests/` run under `-n 8`, finishing in 307 seconds.

## chunk1-04

- `id`: chunk1-04
- `entry`: 1373
- `claim`: the prior session's census of 115 external-binary call sites over 940 top-level `tests/*.py`, 39 of them false-RED.
- `quote`: `EVERY INHERITED NUMBER WAS WRONG, AND SO WAS THE PREMISE.`
- `refuter`: three parallel agents re-deriving the census from scratch, then a hostile refutation pass.

## chunk2-04

- `id`: chunk2-04
- `entry`: 1376
- `claim`: the entry's own first phrasing, which kept gate 1's "only failure" wording after describing the repair that made it false.
- `quote`: `a row that contradicts itself inside one paragraph is what a second gate is for`
- `refuter`: the second read-only gate.

## chunk3-04

- `id`: chunk3-04
- `entry`: 1396
- `claim`: Running under `-n 8` widens the exposure of a process-wide `os.replace` patch, which is why the fix is needed.
- `quote`: `pytest-xdist workers are separate PROCESSES and each runs its own tests SERIALLY, so `-n 8` does not widen the exposure at all`
- `refuter`: The executing cycle's own adversarial pass on its directive.

## chunk4-04

- `id`: chunk4-04
- `entry`: 1397
- `claim`: The audit doc's citation to `ORCHESTRATION_PLAN.md:916-919` resolved to the sentence it quoted.
- `quote`: `the citation was ALREADY content-stale before this change`
- `refuter`: The baselining check run this cycle, resolving the range at 948 lines.

## chunk1-07

- `id`: chunk1-07
- `entry`: 1373
- `claim`: the try/except-shaped repair for an ungated spawn scores UNRESOLVED under the existing hygiene guard's resolver.
- `quote`: `I CORRECTED THAT FINDING BEFORE IT SHIPPED AND THE CORRECTION MATTERED`
- `refuter`: me, measuring the real in-repo instance rather than the synthetic shape - an `importorskip` anywhere in the same function scope launders the verdict to CAPABILITY.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk2-07

- `id`: chunk2-07
- `entry`: 1377
- `claim`: that the dead-endpoint guard is green because the deleted symbols are absent from the gitignored export copies it walks.
- `quote`: `My draft said it is green because the deleted symbols are absent there`
- `refuter`: the gate on the RM-395 filing, which found the symbols PRESENT in each export tree's copy of the guard file itself.

## chunk3-07

- `id`: chunk3-07
- `entry`: 1395
- `claim`: The two dispatched slices had a colliding write set, so parallel execution had to be refused.
- `quote`: `the override's stated collision did NOT hold on inspection`
- `refuter`: The merger, inspecting the two file sets and the override's own self-contradictory collision list.

## chunk4-07

- `id`: chunk4-07
- `entry`: 1398
- `claim`: The directive claimed orphan-tree wiring was outstanding work.
- `quote`: `orphan-tree wiring = RM-407 and split-form sibling scanner = RM-399, ALREADY SHIPPED`
- `refuter`: The slice's triage against shipped ledger state.

## chunk1-11

- `id`: chunk1-11
- `entry`: 1373
- `claim`: the entry's own draft sentence saying `RC-InboxResponder` was disabled "and re-enabled at wrap", written in the past tense while the task was still disabled.
- `quote`: `a future act stated as done, in the file that becomes the record`
- `refuter`: the adversarial gate, against a live `schtasks` query returning Disabled.

## chunk2-10

- `id`: chunk2-10
- `entry`: 1377
- `claim`: that RM-395 was a free id because a grep for it over BACKLOG, ROADMAP and LEDGER returned 0.
- `quote`: `a grep that finds no ROW body is not a claim about the registry`
- `refuter`: tests/test_rm_id_registry_drift.py went RED at the docs-guard run; the tracker had already PINNED RM-395 as next-free.

## chunk3-11

- `id`: chunk3-11
- `entry`: 1394
- `claim`: The guard file for the id registry is `tests/test_rm_id_registry.py`.
- `quote`: `It also named `tests/test_rm_id_registry.py`, which does not exist`
- `refuter`: The re-grounding pass, resolved with one directory listing.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk1-14

- `id`: chunk1-14
- `entry`: 1373
- `claim`: two citation ranges quoted in the draft row were accurate.
- `quote`: `and two citation ranges off by a line at each end`
- `refuter`: the first adversarial gate.

## chunk4-10

- `id`: chunk4-10
- `entry`: 1398
- `claim`: BACKLOG RM-234 and LEDGER 1117 claimed there is no production consumer of `my_runes`.
- `quote`: ``BACKLOG RM-234 + LEDGER 1117 claimed "no production consumer of `my_runes`" - FALSE``
- `refuter`: The slice's consumer census - `coaches/aram_coach.py:430` templates it and `:1031` feeds Haiku.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk2-13

- `id`: chunk2-13
- `entry`: 1378
- `claim`: the RM-395 row's count of exposed enumeration sites in the two holdout files.
- `quote`: `The row named two exposed sites; there are three.`
- `refuter`: the conversion slice, finding a third site in the same file enumerating the caller directories.

## chunk1-17

- `id`: chunk1-17
- `entry`: 1373
- `claim`: the hedge that roughly 16 other unchecked git spawns do inspect the return code.
- `quote`: `as exact only for the wrong quantity: 16 is the count of OTHER unchecked sites`
- `refuter`: the second adversarial gate - 16 is the count of other unchecked sites, of which 14 inspect and 2 discard output.

## chunk3-14

- `id`: chunk3-14
- `entry`: 1393
- `claim`: The audit's section (c) denominator of 674 test functions.
- `quote`: `its section (c) denominator read 674 against a measured 675 (its own section (b) said 675)`
- `refuter`: The merger, correcting the audit body at merge rather than only in chat.

## chunk4-14

- `id`: chunk4-14
- `entry`: 1399
- `claim`: The builder reported the RM-412 slice all green.
- `quote`: `AN INDEPENDENT VERIFIER REFUTED THE BUILDER'S "ALL GREEN" and found a hard red the builder never reported`
- `refuter`: An independent read-only verifier.

## chunk1-21

- `id`: chunk1-21
- `entry`: 1372
- `claim`: the metrics ledger is trimmed to 200 rows.
- `quote`: `The adjudicator called the metrics ledger "trimmed to 200 rows": it is not trimmed at all`
- `refuter`: me, against the shipped RM-388 behaviour - it ROTATES, the 200 is a carry tail, and no rotation has fired.

## chunk2-17

- `id`: chunk2-17
- `entry`: 1379
- `claim`: RM-396's premise that tools/stop_claim_gate.py needed a narrowing patch for the refutation-quoting asymmetry.
- `quote`: `It returned DO NOTHING, and the grounds are measured rather than argued.`
- `refuter`: an independent adjudicator, briefed with the conflict of interest disclosed and told to say DO NOTHING if that was honest.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk3-17

- `id`: chunk3-17
- `entry`: 1393
- `claim`: The path-watching census establishes that the suite does not mutate live operator state.
- `quote`: `Its clean "13 units over 1 path" figure is true and says nothing whatever about this class.`
- `refuter`: The RM-407 audit plus both slice agents, who tripped the live supervisor over a socket while working.

## chunk4-17

- `id`: chunk4-17
- `entry`: 1399
- `claim`: The new package could declare itself all-rights-reserved and not yet distributable.
- `quote`: `the package declared itself all-rights-reserved and "not yet distributable" while sitting in a PUBLIC repo`
- `refuter`: The slice's own license-gate pass before the package mattered.

## chunk1-24

- `id`: chunk1-24
- `entry`: 1371
- `claim`: a rotation that archives 40 rows of another agreement.
- `quote`: `THE CORRECTION WAS FALSE TOO, WHICH IS THE MORE USEFUL HALF.`
- `refuter`: the first gate (measured 35), then the second gate (measured 36), then an independent re-derivation confirming both as answers to different questions.

## chunk2-20

- `id`: chunk2-20
- `entry`: 1379
- `claim`: that the apostrophe over-strip disarms nine of the gate's checks.
- `quote`: `It disarms EIGHT checks, not nine`
- `refuter`: the second gate, showing the hook_bypass flag runs inside the bash-command loop and never sees strip_prose_noise.

## chunk3-21

- `id`: chunk3-21
- `entry`: 1393
- `claim`: 0 vacuous rows over 675 test functions.
- `quote`: `rests on an AST detector and a proxy probe that were NOT committed, so nobody can re-run that zero`
- `refuter`: The merger, downgrading the figure to unreproducible rather than carrying it forward.

## chunk1-27

- `id`: chunk1-27
- `entry`: 1371
- `claim`: the filed row's count of three call sites.
- `quote`: `the row's filed "three call sites" was corrected to FOUR, and the closing arm then made it SIX`
- `refuter`: the adversarial gate, then the session's own closing arm.

## chunk4-20

- `id`: chunk4-20
- `entry`: 1399
- `claim`: The package README claimed a scratch file is never left behind.
- `quote`: ``"never left behind" is true for raised exceptions and **FALSE** for `SIGKILL` / `taskkill /F` / power loss``
- `refuter`: The slice re-deriving the guarantee from the code paths.

## chunk2-23

- `id`: chunk2-23
- `entry`: 1380
- `claim`: that the measurement corpus is the 90 transcripts the RM-397 row was filed with.
- `quote`: `THE CORPUS IS 91 TRANSCRIPTS, NOT THE 90 THE ROW WAS FILED WITH`
- `refuter`: the build's own freeze-and-count of the transcript directory before measuring.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk1-31

- `id`: chunk1-31
- `entry`: 1371
- `claim`: a function's `__doc__` attribute is a substring of `inspect.getsource` output, so replacing it strips the docstring before a body scan.
- `quote`: `so the attribute is not a substring of the source and the replace silently does nothing`
- `refuter`: the arm's own first run, which went red when the docstring's prose tripped the assertion.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk3-24

- `id`: chunk3-24
- `entry`: 1392
- `claim`: The tracer's `wrote_bytes` field counts bytes written.
- `quote`: `the tracer said `wrote_bytes` while measuring CHARACTERS for text handles - wrong in the undercounting direction by one byte per newline plus UTF-8 expansion`
- `refuter`: An adversarial slice.

## chunk2-26

- `id`: chunk2-26
- `entry`: 1383
- `claim`: the spec's assumption that one combined git log call could yield both the name-status list and the patch.
- `quote`: `the combined single call shipped silently broken for one iteration and reported "0 file(s)" over a real 40-commit push`
- `refuter`: running it against a real push, where the empty result read exactly like a clean diff.

## chunk4-24

- `id`: chunk4-24
- `entry`: 1402
- `claim`: RM-313's fence claimed that coercing `championId` risks breaking JS consumers that currently strict-compare strings.
- `quote`: `That census was run, and it inverted the expected risk.`
- `refuter`: The slice's census over the `web/js` consumers - zero unsafe-on-int, two unsafe-on-string.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk1-34

- `id`: chunk1-34
- `entry`: 1370
- `claim`: the first draft's assertion about the gate-tag census trap, which named a suffix relation as a prefix.
- `quote`: `RC's first draft asserted the second as a prefix and was wrong`
- `refuter`: the session, before the answer shipped.

## chunk3-27

- `id`: chunk3-27
- `entry`: 1392
- `claim`: The tracer is an outside observer of the tree it polices.
- `quote`: `the default report path sat in `ops/runtime/`, making the instrument a writer in the tree it polices and excluded from its own count`
- `refuter`: An adversarial slice.

## chunk2-29

- `id`: chunk2-29
- `entry`: 1383
- `claim`: that a literal sentinel config could be spelled in the tests, as the first draft did.
- `quote`: `A literal SENTINEL config cannot be spelled either, which the first draft missed`
- `refuter`: the build, on the test that asserts this file is clean under the sentinel config.

## chunk1-37

- `id`: chunk1-37
- `entry`: 1369
- `claim`: the session's first enumeration of the affected directory-creation sites.
- `quote`: `my first enumeration was incomplete and the verifier corrected it`
- `refuter`: the independent adversarial verifier.

## chunk4-27

- `id`: chunk4-27
- `entry`: 1403
- `claim`: RM-318's acceptance scope - the six detectors - covered the severe case.
- `quote`: `THE SEAM REACHES ONE SITE THE FILED ROW DID NOT ASK FOR, AND THAT SITE IS THE SEVERE ONE.`
- `refuter`: The slice reading `DecisionLoop._loop`, whose `gameTime` read sits outside the per-detector try/except and kills the whole tick.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk3-31

- `id`: chunk3-31
- `entry`: 1390
- `claim`: The in-process LCU path is a 1 Hz hot path producing about 3600 log lines an hour, which sizes the throttle.
- `quote`: `That comment is **pre-existing stale prose**: the real cadence is `RC_STATE_CADENCE_SEC`, default **0.5 s** with a 0.1 floor`
- `refuter`: An independent verifier, deriving the cadence from the setting rather than the comment.

## chunk1-41

- `id`: chunk1-41
- `entry`: 1368
- `claim`: the assembled reply body names the file the sender actually sent.
- `quote`: `so the counterparty read their own filename truncated in the one line written for a human`
- `refuter`: reading the assemble call site - it was reusing the row's 80-character projection.

## chunk2-33

- `id`: chunk2-33
- `entry`: 1383
- `claim`: that the structural arm's false positives could be handled by widening the allowlist.
- `quote`: `SIX live hits came from exactly that shape`
- `refuter`: the live run, where a JSON ability description parsed as a drive letter followed by a newline the drive-letter lookbehind cannot reach.

## chunk4-30

- `id`: chunk4-30
- `entry`: 1404
- `claim`: RM-295a's fence claimed `dashboard/routes_duo_synergy.py` and the UI badge both read `source()`.
- `quote`: `BOTH HALVES ARE FALSE AT HEAD`
- `refuter`: The merger's independent re-probe - zero `source()` calls there and no non-test caller repo-wide.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk3-34

- `id`: chunk3-34
- `entry`: 1390
- `claim`: The 7 citation offsets in the new guard file are correct.
- `quote`: `the build's own +83-line edit invalidated all 7 offsets in the citation block inside its OWN new test file`
- `refuter`: In-slice re-derivation before commit.

## chunk1-44

- `id`: chunk1-44
- `entry`: 1367
- `claim`: the spec's section 15 fence putting the admission module out of scope.
- `quote`: `that fence expired with the build and this item took it`
- `refuter`: this session, reading the fence against the build it was scoped to.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk2-36

- `id`: chunk2-36
- `entry`: 1384
- `claim`: the mechanism probe's counter-headline that the RED-state population is zero.
- `quote`: `the probe's counter-headline "the RED-state population is ZERO" is ITSELF REFUTED`
- `refuter`: the independent adjudicator, naming at least 9 of the 28 flagged sentences asserting a count inside an explicitly non-green state.

## chunk4-34

- `id`: chunk4-34
- `entry`: 1406
- `claim`: The filed rows recited the transcript corpus size as 90 / 91 / 92 / 93.
- `quote`: `the rows above recite 90 / 91 / 92 / 93 and every one of them is now stale`
- `refuter`: This run's re-derivation - 123 frozen transcripts, 0 parse errors.

## chunk1-47

- `id`: chunk1-47
- `entry`: 1367
- `claim`: the 106-entry seed figure carried into this entry.
- `quote`: `so the 106/2 split is not recoverable from the artifact`
- `refuter`: the adversarial verifier, raising it as its one soft spot - the live record is a flat sorted list of 108 names with no seed marker.

## chunk3-37

- `id`: chunk3-37
- `entry`: 1389
- `claim`: The docstring text as it appears in the source file is what an operator should paste.
- `quote`: `pasting from the source file rather than from `help()` yields doubled backslashes`
- `refuter`: The slice, comparing the non-raw source form against the rendered form.

## chunk2-39

- `id`: chunk2-39
- `entry`: 1384
- `claim`: the gate's implied handling of a quoted executable path, which collapsed only POSIX spellings to a basename.
- `quote`: `pre-existing at HEAD, untouched by this diff, found incidentally by the final verifier`
- `refuter`: the final verifier on the RM-398 wrap.

## chunk1-51

- `id`: chunk1-51
- `entry`: 1366
- `claim`: an unwritable hold record clears the bounce target.
- `quote`: ``is true of the four held stages only, not of a `destination` refusal, which takes no hold``
- `refuter`: the independent read-only verifier.

## chunk4-37

- `id`: chunk4-37
- `entry`: 1406
- `claim`: A retraction always self-flags by re-spelling the figure.
- `quote`: `The first draft asserted that a retraction always self-flags by re-spelling the figure; it was RED against the real gate`
- `refuter`: The real gate - `CLAIM_COUNT` wants `passed`, so only a retraction that QUOTES the figure self-flags.

## chunk3-41

- `id`: chunk3-41
- `entry`: 1388
- `claim`: The dispatch's own warning that RM-403 must not appear in any tracked `.md` or the registry guard would break.
- `quote`: `It already appeared - `docs/DS_SWEEP_TRACKER.md:72`, pre-existing from the RM-402 filing - and the guard was green with it present`
- `refuter`: The verifier, correcting the dispatcher.

## chunk2-42

- `id`: chunk2-42
- `entry`: 1385
- `claim`: the entry's first draft, which wrote out the newly advanced next-free id numeral in prose.
- `quote`: `the registry's rule 3 grades a BARE MENTION as ALLOCATED, so naming the next-free id in prose is what TAKES it`
- `refuter`: the docs-guards run going red.

## chunk1-54

- `id`: chunk1-54
- `entry`: 1365
- `claim`: the filed cause of the first armed tick's grammar refusal was the note-name length cap.
- `quote`: `Raising the named cap alone would have fixed ZERO of them.`
- `refuter`: a re-measurement across all five inboxes deduplicated - 208 unique notes, 34 regex failures, all 34 on the topic group and only 11 over the length cap.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk4-40

- `id`: chunk4-40
- `entry`: 1406
- `claim`: The verifier claimed the mid-run modified-file movement came from another session.
- `quote`: `it reported the tree going 3 -> 6 modified files mid-run and attributed it to another session. It was this one.`
- `refuter`: The merger, recording the process caveat rather than smoothing it over.

## chunk3-44

- `id`: chunk3-44
- `entry`: 1387
- `claim`: The `!agents/state/resolved_decisions.json` negation protects that file from the ignore rule above it.
- `quote`: `The `!` line was present, read as protection, and did nothing`
- `refuter`: The ignored-tracked probe plus hand verification in both directions.

## chunk2-45

- `id`: chunk2-45
- `entry`: 1386
- `claim`: RM-402's own suggested evidence-derived alternative, a bash-window discriminator around the claim.
- `quote`: `THE ROW'S OWN SUGGESTED EVIDENCE-DERIVED ALTERNATIVE MEASURED WORSE IN BOTH DIRECTIONS`
- `refuter`: measurement - 5 of 15 non-git uses have a push in the window anyway and 98 of 415 genuine uses have none, because the budget idiom is written during the wrap, which is exactly when pushes happen.
- `uncertain`: yes (body withheld - see Blinding above)

## chunk1-57

- `id`: chunk1-57
- `entry`: 1365
- `claim`: the max-turns constant of 12 was sufficient.
- `quote`: `so the old limit would have failed a third time and hit the attempt cap - now 30`
- `refuter`: the delivering cycle, which used 21 turns.
- `uncertain`: yes (body withheld - see Blinding above)

