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
