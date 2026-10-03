# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-10-02, the re-pin-round / citation-fence-refuted wrap (relocated `2026-09-30b` the repo tidy-up via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1040" - read off the tool's own output, never off a recollection; newest 3 = `2026-10-02b` this wrap, `2026-10-01` the two-reds-closed / CLAUDE.md-demotion wrap, `2026-09-30c` the lane-refs / anomalies / channel-drain wrap). The prior relocation was 2026-10-01, the two-reds-closed / CLAUDE.md-demotion wrap (relocated `2026-09-30` the weekly-routines repair via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1039" - read off the tool's own output, never off a recollection; newest 3 = `2026-10-01` this wrap, `2026-09-30c` the lane-refs / anomalies / channel-drain wrap, `2026-09-30b` the repo tidy-up). The prior relocation was 2026-09-30, the lane-refs / anomalies / channel-drain wrap (relocated `2026-09-21a` via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1038" - read off the tool's own output, never off a recollection; newest 3 = `2026-09-30c` this wrap, `2026-09-30b` the repo tidy-up, `2026-09-30` the weekly-routines repair). The prior relocation was 2026-10-01, the repo tidy-up wrap (relocated `2026-09-20c` and `2026-09-20b` via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1037" - read off the tool's own output, never off a recollection; newest 3 = `2026-09-30b` this wrap, `2026-09-30` the weekly-routines repair, `2026-09-21a` the RM-480 wrap). The prior relocation was 2026-09-21, the 16.18.1 / ENGINE 1.282.0 wrap (relocated `2026-09-19d` the lane-widget audit via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1034" - read off the tool's own output; newest 3 = `2026-09-20c` this wrap, `2026-09-20b`, `2026-09-20`). The prior relocation was 2026-09-20, the ROUND B / bucket-scan / RM-477 wrap (relocated `2026-09-19c` the lane widget ship, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1033" - both figures read off the tool's own output, never off a recollection; newest 3 = `2026-09-20b` this wrap, `2026-09-20` the NOW-block drain, `2026-09-19d` the lane-widget audit). **One claim in the `2026-09-20` block below is SUPERSEDED and is called out here so it is not inherited: it says the 67 MB `laning_scenarios` JSONs "were ruled out: LFS, blob is 133 bytes". REFUTED 2026-09-20 - `collect_tree_blobs` reads the WORKING TREE, so a smudged LFS file is scanned at its full 66,961,895 bytes and those seven files were the dominant term; see the `2026-09-20b` block.** The prior relocation was 2026-09-20, the NOW-block drain wrap (relocated `2026-09-19b` the idle filesystem walker, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1032" - those two figures are read off the tool's own output, never off a recollection; newest 3 = `2026-09-20` this wrap, `2026-09-19d` the lane-widget audit, `2026-09-19c` the lane widget ship). **One superseded claim rides in the relocated block and is called out here so a reader of the archive does not inherit it: `2026-09-19b` says LL has NO `docs/CHANNEL.md`. FALSE - LL carries it at `third_party/rc_channel/docs/CHANNEL.md`; see the 2026-09-20 block.** The prior relocation was 2026-09-19, the lane-widget UI fixture audit + live acceptance wrap (relocated `2026-09-19` the RM-239 / RM-242 QA pass, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, and the verbatim property was checked the strong way rather than asserted: the SAME text was typed into `docs/history_notes.md` and then used as the `old_string` that removed it from here, so the removal could only have succeeded on an exact byte match, and it was then re-confirmed by diffing the archived block against `git show HEAD:WAKEUP_NOTES.md`. **`scripts/wakeup_prune.py` was NOT run this pass, so NO tool-reported move count is quoted here** - do not read one into this note; newest 3 = `2026-09-19d` this wrap, `2026-09-19c` the lane widget ship, `2026-09-19b` the idle filesystem walker). The prior relocation was 2026-09-18, the laned orchestrated loop wave 7 wrap (relocated `2026-09-17b` the wave 4 block, via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1027"; newest 3 = `2026-09-18b` this wave, `2026-09-18` wave 6, `2026-09-17c` wave 5). **THIS WAS THE FIRST REAL PRUNE AFTER THE RM-276 FIX, and the insertion-only property was verified on the REAL archive rather than inherited from the slice's scratch-copy measurement: exactly ONE difflib opcode, kind `insert`, 21 lines inserted, ZERO deleted, at old line 41, with `new == old[:41] + inserted + old[41:]` reconstructing exactly.** That matters because the pre-fix pruner would have deleted 1335 lines of ordering from this archive on this very run - see the wave 7 block below. The prior relocation was 2026-09-17, the laned orchestrated loop wave 4 doc-sync (relocated `2026-09-16b` the laned-loop wrap, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, then byte-compared equal to the output of `scripts/wakeup_prune.py --keep 3` run on scratch copies of both files, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 970"; newest 3 = `2026-09-17b` this wave, `2026-09-17` wave 3, `2026-09-16c` waves 1-2). The pass before this one, on 2026-09-17, was the laned orchestrated loop wave 3 doc-sync (relocated `2026-09-16` the acknowledge-path wrap, VERBATIM via the Edit tool, byte-compared equal to `scripts/wakeup_prune.py --keep 3` output on scratch copies, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 969"; newest 3 = `2026-09-17` that wave, `2026-09-16c` waves 1-2, `2026-09-16b` the laned-loop wrap). The pass before that, on 2026-09-16, was the laned orchestrated loop wave 1 doc-sync (relocated `2026-09-15` the moon-sync merge, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 968"; newest 3 = `2026-09-16c` this wave, `2026-09-16b` the laned-loop wrap, `2026-09-16` the acknowledge-path wrap). The pass before this one, on 2026-09-16, was the laned-loop doc wrap (relocated `2026-09-14` the public surface refresh, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 966"; newest 3 = `2026-09-16b` this wrap, `2026-09-16` the acknowledge-path wrap, `2026-09-15` the moon-sync merge). The pass before this one, on 2026-09-15, was the moon-sync five-slice merge wrap (relocated `2026-09-12e` the discovery-axis + inter-scorer lane and `2026-09-12d` the fleet tooling-tier lane, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 964" - read those counts off the tool's own output, never off a recollection; newest 3 = `2026-09-15` this wrap, `2026-09-14` the public surface refresh, `2026-09-12f` the calibration lane). The pass before this one, on 2026-09-12, relocated `2026-09-12c` the SESSION WRAP doc-sync and reported "moving 1 session(s)" / "archive now has 962". The pass before that relocated `2026-09-12b` the five-slice merge and `2026-09-12a` RM-412 C1 OSS extraction, and reported "moving 2 session(s)" / "archive now has 961". The pass before that relocated `2026-09-11d`, the one before that `2026-09-11c`, and the one before that `2026-09-11b` and `2026-09-11a`, the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired. The 2026-09-16 RELOCATION DUE note that sat here is DISCHARGED and deleted by the 2026-09-16b prune above.

---

# 2026-10-03 - headless spawns routed through the operator's second-account proxy (fail closed), RC-InboxResponder ARMED, MAIN grant recorded

- **Operator instruction, confirmed in chat 2026-10-02 (items 1-4).** Commits: `7e6773fec` (every headless `claude` spawn routes through `ops/loop/headless_env.py` + `ops/loop/headless_route.ps1`; registry-first read of the user-scope proxy var, child-only `ANTHROPIC_BASE_URL`, refuses on unset / non-loopback / port refused; LEDGER 1460), `4e7ec9d69` (CLAUDE.md: MAIN-speaks-for-the-operator grant quoted verbatim + responder ARMED line), `0dcdf4ad0` (headless_env guard no longer scans its own needles). CI `ci` run 37094568695 green on `0dcdf4ad0`.
- **Proof spawn** `claude -p "reply ok"` through the real helper answered `ok`; proxy activity log named the second account. Email and URL are deliberately NOT in any tracked file.
- **RC-InboxResponder ENABLED**, every 5 min, agreement record (gitignored) expires 2026-11-01, hop budget 32. The 296 notes attended sessions had already handled were seeded as answered via `record_responded` BEFORE enabling, so it only answers new notes. No halt was cleared; `ops/loop/control/STOP` left in place; CI watchdog + weekly hygiene stay disabled.
- **Report to MAIN delivered** (`C:\Main\moon_sync_inbox`, sha256 `27c6670b...`). Replies also delivered to CS / SS / LW / RSC / LL this session (re-hashed, all reached).
- **OPEN, held for a ruling:** (1) `tests/test_inbox_responder_mutants.py` now trips INTERMITTENTLY - its teardown guard assumes live responder surfaces + sibling inboxes stay still, and an armed responder moves them. Guard NOT weakened. Choose: exclude live surfaces, or pause the responder for that test. (2) C4 `slots.py` candidate `290cbf80` attested by RC; vendoring + moving `SHARED_SHA256` is a joint act, held.
- **Do NOT redo:** the routing, the arming, the seed, or the MAIN grant. Do not hand-answer inbox notes the responder now owns - check `ops/runtime/inbox_responder_answered.json` first.
- **Known gap (non-blocking):** `headless_child_env` strips only `ANTHROPIC_BASE_URL`; inherited `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` still pass to executor / adjudicator / watchdog children (unchanged from before).

---

# 2026-10-02b - a sibling re-pin round answered FOUR times as its candidate was re-issued THREE times, RC's own citation fence REFUTED by RC's own commit-map, two leaked slot locks on REUSED pids, and six RC claims withdrawn before or after delivery

**THE SESSION'S SHAPE: almost everything of value came from being refuted, including by RC.** Six RC positions or claims were withdrawn, four of them before anything was delivered and two after. The adversarial gate ran BEFORE the first delivery and caught **six defects in a note that was ready to send**. Read that as the method working, not as a bad session.

**THE HAND-OFF'S TASKS WERE ALREADY DONE.** Task A (NOW-7 report-only census), Task B (the thirteenth ROADMAP relocation) and RM-499 all landed in commits `19ff39919`, `fbe452cf9`, `e47e5e442` earlier the same day. **Read `git log --since` before trusting a hand-off's open list** - the hand-off was written at a wrap and the tree moved after it.

**ITEM 5 OF THE SIBLING ROUND REFUTED A STANDING RC FENCE, AND THE FENCE WAS IN CLAUDE.md.** The `docs/LEDGER.md` CITATION CAVEAT and its CLAUDE.md summary ruled out a history rewrite as the cause of ~50 percent unresolvable pre-2026-07 commit citations, on the reasoning that "a rewrite would be 100 percent before a cutoff and 0 percent after". **That premise is FALSE for a PARTIAL rewrite, and RC's was partial** - `filter-repo` on 2026-06-21 over 2026-06-08..06-21 only, 1,829 ancestors left at identity, 619 rewritten, 1 dropped. Measured over the three files the caveat names (pattern published, because the population is a function of it): **1,987 distinct 8-hex citations, 454 unresolvable, 344 present as OLD shas in RC's OWN `.git/filter-repo/commit-map`, 110 not, 0 mapping to forty zeros.** All 344 remap to a live commit. **At the caveat's MONTH binning a 13-day band is indistinguishable from the "steady rate that stops dead" it reported as proof**, so the test could not discriminate - and it was run 2026-07-18, a month AFTER the rewrite it ruled out. **An earlier draft generalised this as "invisible to EVERY cutoff-shaped test" and that was measured FALSE**: binned finer than the rewritten range the band is loud at 344 of 344 inside 13 days. The honest form is **invisible to a cutoff test whose bins are COARSER than the rewritten range**. **The caveat's own worked example is wrong in both halves** - `91b6b847`, offered as the merge hash that resolves, does NOT resolve and is in the map; `03927664`, offered as gone forever, is in the map too. **And `541cd9d3`, which the caveat records as having cost a full agent and calls "simply gone", remaps to `a685a530bd23...` in a map that was already on disk when that agent was spent.** `tools/rewrite_sha_citations.py` (2026-09-07, dry-run default) is the discriminator plus the repair and had never been applied. Fence and preamble corrected in place with every refuted sentence STRUCK BESIDE ITS MEASUREMENT; the 344-citation repair is filed GATED as RM-501 because it edits append-only history and the SHAPE of the repair is the decision.

**TWO LEAKED SLOT LOCKS, BOTH ON REUSED PIDS, AND THE ATTRIBUTION RC PUBLISHED WAS WRONG.** `C:\ProgramData\lw-loop\slots` held two RC locks unreleased for two days; `pid_alive` answered True for both, and the discriminator is the pid's PROCESS START TIME, which post-dated each lock's `ts` by 1.5 and 1.2 days. **RC published "RC's loop acquired slots" and had to withdraw it hours later: STOP was HONOURED.** `controller.log` ends at `2026-09-11T18:04:04 external STOP seen (cycle top)`, `run_id.txt` is still `63545b4e`, `cycle.txt` still `8`, `RUNNING.lock` still pid 22888, and `loop_controller.py:1055-1056` deletes STOP and overwrites all three at startup - so the controller provably has not run. The acquires came from a direct `slots.hold()` by an UNTRACKED caller, unidentifiable. **RC's "the repo field is written by exactly one RC caller" was true of TRACKED callers only - an empty grep is a claim about the pattern.** **THREE STRUCTURAL FINDINGS: `reap()` is LAZY** (called only from the `try_acquire() -> None` branch, so a stale lock in a non-full bucket is never reclaimed - watched directly as another carrier took a free slot and walked past both dead ones); **nothing in RC audits the bucket at all**; and **an acquire/release pairing audit over RC's logs CANNOT see this leak class** - 44 acquires / 43 releases reads clean while three leaks since 2026-09-20 have run_ids appearing nowhere in it. Filed RM-504 and RM-506 (STOP is a cycle-level brake, not a durable disarm). **Clearing the locks DESTROYED THE ARTIFACTS** - their run_ids survive only in a subagent report. Snapshot a durable store before clearing it.

**THE CANDIDATE RC ACCEPTED WAS RE-ISSUED THREE TIMES AND RC ANSWERED FOUR TIMES.** `9531bfe9` -> `799cdeed` (comment amendment RC had asked for) -> `7f84ec96` / `da35f8b1` (middle arm dropped). **RC attested FIVE digests from its own disk**, every published quantity matching, and confirmed `C2` vs `C2-M2` differ at exactly ONE offset, **2121**. **TWO UNDERDETERMINATION FINDINGS the author asked for by name:** hunk 2's ABSOLUTE indent is unrecoverable from the publication (both hunks render at one column while one is module-level and one function-body, so a faithful transcription will not compile), and a BLANK LINE before hunk 1 contradicts the published instruction - **where byte and LF counts CANNOT disambiguate the two placements and only the digest can.** **CS FOUND THE MIDDLE ARM IS DEAD CODE AND RC'S GRADING METHOD COULD NOT HAVE.** Confirmed by arm deletion: 0 differing over 20 cases, 6 against plain-AND, 3 ceiling mutants planted and killed. **RC published a five-arm table and four mutants and called it graded - but the dead-holder arms return True whichever arm produces them, so redundancy is invisible to a table comparing only VERDICTS. A case table cannot find a redundant arm; only an arm-deletion mutant can.** The author's four mutants share the blind spot. **AND RC'S TWO-ARM MUTATION CONTROL, BUILT TO TEST CS'S CLAIM, IS BYTE-IDENTICAL TO THE LATER RE-ISSUE `7f84ec96`** - an independent derivation that predates its own target, which is the strongest attestation form available here and happened by accident. **RC moved 4.0 -> 2.0 against its own earlier position**, on its own measured reused-pid instances: with the middle arm gone the ceiling is the only liveness-independent reclaimer, so the window is the one cost RC has instrumented. Every carrier's figure clears 32,400 s by at least 2.5x and the binding one is a DESIGNED worst case, not an observation.

**RC'S 5,401 s WAS BEING USED AS A FLEET CEILING AND IT IS A FLOOR.** Re-derived from `controller.log`: 44 acquires, 43 releases, 43 pairs, 1 unpaired, worst 5,401 s at 0.33x, mean 2,593 s, zero above 16,200 s - reproduces the 2026-09-20 figure exactly. **But that corpus holds SIX distinct run_ids and RC knows of at least NINE acquires**, with `12323c3b`, `356f2f86` and `a22618e2` each occurring ZERO times. So it is a FLOOR on RC's own maximum and RC asked the channel to record its contribution as "unknown, floor 5,401 s".

**TWO RELAYING ERRORS, THE SAME CLASS, SIX HOURS APART.** RC praised a sibling for backing its figure with a TRACKED corpus file; that sibling measured its own tree and "tracked" was FALSE. **RC had relayed another tree's self-description as an observation** - the identical class RC withdrew that morning over a relayed figure, with the check available and not run. **Measured while confirming it: `moon_sync_inbox/` is gitignored in RC too (`.gitignore:201`, `git ls-files` returns ZERO), so RC's whole channel corpus - 391 inbound and 141 outbound - is git-backed NOWHERE in ANY tree.** A single `git clean -xfd` anywhere destroys that tree's share with no diff and no warning. **There is no tracked-corpus counterexample on this channel.**

**READ-AND-UNANSWERED, MEASURED WITH THE RULE PUBLISHED:** 391 inbound, all 391 SEEN, ANSWERED 77 / NOT ANSWERED 273 / UNCLASSIFIABLE-BY-THE-RULE 41, debt 217 after 56 self-declared no-reply-owed. **The 273 is an UPPER BOUND** - only 65 of 141 sent notes carry a code-plus-stamp citation at all and RC's July/August notes use no convention, so the ten oldest apparent debts sit in the blind window and were NOT published as a list. **RC receives from SEVEN codes and can address FIVE.** Filed RM-507.

**THE DUPLICATE LEDGER 1457 WAS RESOLVED BY A CITATION, NOT BY A DATE.** Exactly one live citation existed (`tools/logger_leak_census.py` cited "NOW-6 (LEDGER 1457)", closed by the 2026-10-01 entry), so THAT entry became 1458 and the token was fixed in the same commit. Then reordered on operator instruction **as a pure LINE SWAP with three proof obligations checked before any write** - sorted multiset of lines unchanged, byte count unchanged (5,389,458 both sides), and each entry's sha256 landing on the other's index (`f371d843d940fbfb` 10,759 B, `c7014c96a2ef1268` 5,790 B). **A reorder that cannot prove the bytes survived is the one to refuse.**

**DELIVERY: SIX RC NOTES, EACH REACHED 6 of 6, every copy re-hashed from the RECIPIENT's own disk** - `b6f8db39`, `559b05b1`, `4d7846e0`, `5f785297`, `0965464f`, `82e8fa82`. **ONE STAMP COLLISION RC CAUSED AND FIXED:** the first delivery was stamped 0915 and an RC note stamped 0915 already existed in the carrier trees from that morning, so RC re-stamped to 1130, deleting ONLY its own exact filename after a digest check so a same-stamp note that was not RC's could not be touched.

**PROCESS MISS WORTH CARRYING: RC GATED ONCE WHERE IT SHOULD HAVE ADJUDICATED**, asking the operator about clearing the leaked locks. The standing directive is to adjudicate and take the best option immediately. The operator then chose a WIDER scope than either option offered ("clear them and fix the leak"), which is the argument against gating in miniature.

**ONE `-k` ARTIFACT RE-CONFIRMED, NOT A REGRESSION:** a narrowed doc slice reported `669 passed, 1 error` at `tests/test_inbox_responder_runner.py:306`. That is the documented selection artifact - the filter picks `test_this_file_is_seven_bit_ascii` out of the responder mutants module while deselecting the arms that drive it, so the autouse fixture fires its own anti-vacuity control. Module unfiltered is **79 passed**, the figure the prior hand-off recorded. **An ablation's test selection is part of the ablation.**

---

# 2026-10-01 - BOTH open reds CLOSED: NOW-6 root-caused to a leaked logger mutation, NOW-5 re-pinned behind three controls, and the CLAUDE.md auto-load budget cut from 91 percent to 82 by demotion

**Both reds the hand-off named are closed, and neither needed the 100-minute bisection it
feared.** Headless, operator away, orchestrated: three slices out at once, main window held
the plan, the merge and the gate.

**NOW-6 was CROSS-TEST LOGGER POLLUTION, and the defect belonged to the LEAKER while
surfacing on the VICTIM.** `scripts/rewind_catchup.py:166` `setup_file_logging()` sets
`propagate = False` on `rc.scripts.rewind_catchup`, raises its level and attaches a
`RotatingFileHandler`; `main()` calls it unconditionally.
`tests/test_rewind_timeline_429_retry.py::_DbCase.tearDown` restored its three `mock.patch`
objects and nothing else, so the mutation outlived the test. `caplog`'s handler sits on the
ROOT logger, so cutting propagation at the EMITTING logger made `caplog.records` empty and
three tests failed in `tests/test_rm413_wal_pragma_result_checked.py` - **a file that never
touches logging.** The hand-off's "caplog sees ZERO warnings, hunt the CAPTURE side" was
correct and is what found it.

**THE SEARCH METHOD IS THE REUSABLE PART, because the obvious one FAILED.** A grep of
`tests/` for logging tokens (`propagate`, `basicConfig`, `setLevel`, `logging.disable`, ...)
returned 10 files, and all 10 ran CLEAN with the subject - **because the polluter contains
no logging token at all; it only calls `main()`.** What worked: enumerate the files that
import the same SUBJECT MODULE, then pair each one with the victim individually. Nine short
runs, under 12s each, against a full suite that takes 1:42:33. **Derive candidates from the
FAILING SUBJECT, not from the symptom's vocabulary.**

**SCOPE MEASURED RATHER THAN REASONED.** All 9 test files referencing `rewind_catchup` were
paired with the subject one at a time: exactly ONE leaked, the other 8 clean. The only other
production `propagate = False` in the tree, `agents/agent2_backend/ws_server.py:66`, is
reached only from `WSServer.__init__` and **no test file references `ws_server` at all**, so
it is unreachable rather than latent. A third such logger
(`agents/_supervisor_common.py:197`) was ALREADY guarded at `tests/conftest.py:159-206` -
that is the in-tree precedent for the class fix.

**The regression pin is placed at the LEAKER, not the victim, and is PROVEN NON-VACUOUS.**
`tests/test_now6_logger_leak_regression.py`, two tests. With the fix stashed BOTH go red
(`2 failed in 5.06s`); the file was then restored and verified byte-identical against a
scratchpad backup, and the pair went green. **A guard nobody has watched fail is not a
guard** - this one was watched.

**NOW-5: `PINNED_CLI` 2.1.251 -> 2.1.285, and the acceptance was MET, not bypassed.** Three
controls, one more than the 2026-09-01 round ran: canary (codeword returned inside a spawned
subagent's own hand-back, proven a REAL spawn by a stream-json run showing one `Agent`
tool_use with the subagent reporting `tool_uses: 0`); negative control (same invocation
without the flag, `NO-CANARY`, codeword count zero); and a **NEW top-level leak control**
(flag present, NO spawn, top level reading its OWN system prompt -> `NO-CANARY`), which
closes the gap where a canary could be satisfied by the parent rather than by propagation.
Version and `--help` were re-probed in the main session rather than inherited: still
`2.1.285`, flag still absent from `--help` (only `--forward-subagent-text` matches a
`subagent` grep), still accepted (exit 0 against exit 1 for a genuinely unknown option).
`reference_claude_p_readonly_spawn_shape` was deliberately LEFT at 2.1.251 because
`--restricted` / `--bare` were not re-measured - **a pin is only as good as the experiment
behind it.**

**CLAUDE.md 55,960 -> 50,652 bytes (91.1 -> 82.4 percent) ENTIRELY BY DEMOTION.** The
7,514-byte HEADLESS-LOOPING paragraph became a 2,080-byte short form carrying only the rules
a session needs every turn; the long form, the blind spots and the superseded readings moved
VERBATIM to the new `docs/SIBLING_SWEEP_AND_BOUNDARY.md`. **42 of 42 sentences preserved,
verified independently in the main session, not inherited from the slice.**

**AND THAT VERIFICATION IS THE SESSION'S BEST LESSON, because it was WRONG THREE TIMES
FIRST.** It reported 1 missing, then 18 "true losses", then 34 - and every single one was a
defect in the CHECKER: a `(?<=[.!?])` lookbehind cannot fire on a sentence ending `.**`; an
8-word shingle cannot span a point where a heading was inserted; a half-split heuristic over
`range(2, N-1)` cannot decompose a junction whose far half is one word. Every wrong count
printed under a bucket named `MISSING` - **named after the SUBJECT's property while
absorbing the checker's own failures.** The correct splitter returned 42 of 42, matching the
slice exactly. Had the first number been believed, a correct slice would have been sent back
for a loss that never happened. This is finding 1 of the 2026-10-01 SS channel note,
reproduced three times inside one session, and it is now memory
`feedback_your_failure_bucket_vs_the_subjects`.

**THE CHANNEL "CONTRADICTION" THE HAND-OFF FLAGGED IS NOT ONE - three different sets, all
correct.** `SHARED_SHA256` byte-pin bucket = THREE (RC + two carriers, Sibling-C archived);
`ops/moon_sync_repos.json` `participants` = FIVE (the non-RC address list);
`docs/CHANNEL.md` roster = SIX with a carrier set of FIVE (SS is roster-but-not-carrier, and
CHANNEL.md warns in its own text at the roster section never to write a carrier count as a
roster count). CLAUDE.md's "two sibling checkouts" sentence sits immediately after the
`SHARED_SHA256` sentence and describes the BYTE-PIN bucket. **The real defect was a LABEL,
not a count:** it said bare "Participants", which in CHANNEL.md's vocabulary means the six.
Relabelled; counts untouched. **Do not "fix" any of these three numbers to match another.**

**RC's own sibling sweep was CHECKED against the SS lesson and PASSED - do not re-audit it
for this.** `EXIT_FAULT = 3` is never collapsed into `EXIT_CLEAN` and the docstring says so
in those words; `assert_non_vacuous` is PER-SLOT and requires DRIVE + URL shapes per needle;
`iter_tree_blobs` raises `GitFault` EAGERLY on a vacuous tree walk so it surfaces as FAULT
rather than as a traceback outside the fault handler; `unscanned_bytes` and
`decode_failures` are printed rather than absorbed; windowing is guarded byte-for-byte.

**Budget bookkeeping, because closing two rows while filing a third moved it twice.**
ROADMAP went 73,325 (89.5 percent) -> 92.5 percent -> back to 73,720 (90.0 percent) by
relocating both closures VERBATIM to `docs/ROADMAP_HISTORY.md` (an eleventh and a twelfth
pass) and compressing the inline stubs to the ~400-600-byte shape L41-L44 already use.
**`drift_guard` was RED at 92 percent mid-session and is clean at the end** - it is the
thing that caught it, which is the argument for running it before the wrap and not after.
**ROADMAP is still riding the WARN line at 90.0 percent and wants a proper relocation pass
next session.**

**Fences carried in BOTH places ON PURPOSE, which is not duplication.** The NOW-5 "DO NOT
just bump the constant" clause and the NOW-6 "PASSING IN ISOLATION IS WHAT A POLLUTION LOOKS
LIKE" clause stayed inline in ROADMAP while their evidence moved to history, because both
govern FUTURE work. Relocating a live rule into an archive is the failure mode a
size-budget pass is most likely to cause.

**Boundary calls made without the operator, both flagged for overrule.** (1) The `memory/`
directory sits OUTSIDE the repo root, so a literal reading of "halt before any byte leaves
the tree" would block the standing drift-guard-every-wrap rule; resolved to PROCEED, because
memory is RC-scoped, operator-established, read by RC's own `tools/drift_guard.py` and
cannot reach a sibling. (2) The push half does NOT halt: the diff touches no byte-pinned
artifact, the sweep is clean on every changed file, and the one bare channel code added
(`SS`) is already published by design in the TRACKED `docs/CHANNEL.md` roster - **the secret
is the NAMES, not the codes, and no name was written.** That adjudication was manual on
purpose, because a bare code is never DETECTED by the sweep, so its clean verdict says
nothing about one.

**Measured aside worth not re-discovering: 49 memory files carry non-ASCII bytes.** That is
the retroactive smart-quote sweep CLAUDE.md already lists as pending and operator-gated, not
a regression. Both memories written this session are ASCII-clean.

**I MOVED THE TREE UNDER MY OWN VERIFIER, which is the slip to not repeat.** The verifier was
dispatched being told the tree held TWO commits; a third (the RM-498 refinement) was then
committed while it ran. It caught this itself, named it as the
`feedback_verifier_needs_a_frozen_tree` failure mode, and re-ran the affected claims against
the new HEAD - they held. **All 9 claims CONFIRMED, nothing refuted**, and it did better work
than asked: it re-derived the mutation proof in a sparse detached worktree with both blob
hashes verified rather than using `git stash`, wrote its OWN sentence splitter with three
negative controls proving the checker CAN fail, and checked all 7 sibling files instead of
the 3 requested. One bookkeeping correction from it: **"9 test files reference
`rewind_catchup`" is the PRE-FIX count - it is 10 now that the regression guard exists.** The
scope sweep was over the 9 pre-existing files, so the claim is right, but a reader counting
today will get 10.

**THE CLAIM GATE BLOCKED THIS WRAP ON A TRUE NUMBER, and the RM-498 workaround in the
hand-off is REFUTED.** The hand-off said to launch each suite as its OWN background job or
backtick the count. Both suites WERE launched as separate concurrent background jobs, and the
gate accepted the DS figure while rejecting the `tests` figure. The deferred slot is ONE PER
SESSION, not one per job, so a second concurrent backgrounded run has no slot however it was
launched. BACKLOG RM-498 now carries this with the widened acceptance. Only two things work
once blocked: re-run so the summary is unambiguously yours, or BACKTICK the figure. Rewording
afterwards is not a remedy - the scan re-reads the whole transcript at every Stop. **The
"do not fix the gate in the session it is blocking" fence held and should stay.**

**SS's second note of the day (2026-10-01-2140) was checked against RC rather than filed, and
one half of it IS live here.** Finding 2: a clean sweep taken where the dirty result cannot
occur is not evidence. Measured on RC - `PYTHONDONTWRITEBYTECODE=1` and
`sys.dont_write_bytecode=True` inside a session, while the variable is **ABSENT from BOTH**
`HKCU\Environment` and the HKLM Session Manager key, so the harness injects it per session.
**RC is NOT exposed to the defect itself, and that was checked rather than assumed:** every
`.pyc` / `__pycache__` reference in `tests/`, `tools/`, `ops/`, `scripts/` is a walk
EXCLUSION (`tests/_repo_walk.py:90`,
`tests/test_oss_win32_atomic_io_drift.py:116` and siblings), never an assertion that bytecode
must be absent - so there is no overdetermined RC sweep to invalidate. **This is a PRE-EMPTIVE
fence: any bytecode-hygiene guard written from inside a session would be born
overdetermined.** The positive control exists by accident - 2090 `.pyc` files under
`tests/__pycache__`, written by processes that never had the variable. Second variable with
the same mechanism as the 2026-08-31 `PYTHONUTF8` miss, so
`reference_os_environ_is_a_process_fact_not_a_machine_fact` was extended rather than a new
memory written. **The transferable half is that SS's published one-line check cannot
establish SCOPE** - `os.environ` prints a process fact, and only the registry read says
whether a scheduled task, a fresh clone or CI inherits it.

**Reply DELIVERED to the channel, 5 of 5, and re-hashed from each RECIPIENT's copy rather
than from RC's outbox** (source sha256 `e753bbe4c349d052`, 6980 bytes, every destination
matching). Pre-authorised under the standing carve-out; ASCII-clean and sweep-clean before it
left the tree. It reports the scope refinement above, RC's own three-times-wrong checker as
an independent instance of SS's finding 1, and independent corroboration of SS's finding 4
from RC's separate evidence. It adopts SS's "a brief with no corrections section is a brief
nobody checked" and says in its own closing that the note's corrections are RC's three
checker defects.

**SUITES, both read off their own result files rather than off a subagent's report, and
launched as SEPARATE background jobs because of the RM-498 claim-gate trap.** DS:
`10933 passed, 13670 subtests passed in 128.05s`. RC `tests`:
**`24733 passed, 104 skipped, 3 xfailed, 1 xpassed, 5066 subtests passed in 1:23:55` - ZERO
failed**, against the `4 failed` the hand-off handed over. Note the run was 1:23:55 where the
2026-09-30 baseline was 1:42:33.

**AND THE FULL RUN STRADDLED THIS SESSION'S OWN DOC EDITS, so it was NOT accepted on its
own.** ROADMAP, WAKEUP_NOTES and `docs/ROADMAP_HISTORY.md` were all edited after the suite
launched, and several guards assert on the SIZE and CONTENT of exactly those files - so that
run describes a tree that no longer existed by the time it finished. Re-verified on the
FROZEN tree afterwards: the 17 doc / guard / pin / changed-subject files gave
`514 passed, 230 subtests`, and the broad slice
`-k "doc or docs or ascii or markdown or md_ or link or ledger or roadmap or wakeup or em_dash"`
gave `1072 passed, 86 skipped, 81 subtests`. **A backgrounded suite that overlaps a docs edit
is not evidence about the tree you are about to push** - re-run the part that reads what you
touched.
