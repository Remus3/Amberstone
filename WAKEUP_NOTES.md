# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-01b - lane 6 Headless-DS: RM-323 / RM-324 / RM-325 batch (ENGINE 1.279.0)

Branch `lane/ds`, **NOT merged** - a merge to main is a deployment and landing is
the merger session's call. Ledger entry: `docs/LEDGER.md` **1317**.

**Shipped the three LANE 6 rows the lane-5 refill filed the same morning, and all
three filed specs turned out to need correction.** That is the durable finding, not
the code:

- **RM-323** asked for `mirror == base` equality. Reading DDragon 16.15.1 for all
  six ids showed it carries **NO proc magnitude for any of them, SR twins
  included** - the `<stats>` block is base stats only. Doctrine B ("Arena mirrors
  credit their OWN line") therefore cannot be settled from DDragon here, so each
  mirror is credited from its own `note` and equality is a MEASURED CONSEQUENCE.
  The row's acceptance EXAMPLE was also vacuous: `burst(with) > burst(without)`
  passes at HEAD because `226655` carries 85 AP and the total rises on the stat
  block alone.
- **RM-325's site list named four NOTE sites and missed the real multiplier
  resolvers** (`ehp.py:932`/`:1728`, `ability_dps.py:654`, `hps.py:265`). Fixing
  exactly what was filed would have left the arithmetic wrong with the notes
  reading correct - `feedback_resolver_fix_is_not_a_consumer_fix`, in a row that
  itself cited that memory.
- **RM-324's proposed `parse_constant` class-fix was rejected on a measurement**:
  `1e400` is an ordinary JSON float literal that overflows inside `parse_float`
  and never reaches `parse_constant`, so it would have looked class-level while
  leaving the bug reachable.

**THE LANE-WORKTREE / :8860 SEAM IS THE THING TO CARRY FORWARD.** `RC-DaemonSlayer`
runs `pythonw.exe` against `C:\Riot Commander\tools\start_daemon_slayer.py` - the
MAIN checkout - so the shared port serves main's version no matter what a lane
pins. The headless-ds ritual says "bounce :8860 and confirm it serves the NEW
version", which is unachievable from a lane worktree and would be actively harmful
if forced: it would push unmerged lane code onto the port RC and four other live
lanes read. The regen was run through `_install_static_transport()` instead
(in-process via the DS server's own POST handlers, documented as identical to the
live path by construction). **Owed AT MERGE, in main:** bounce `:8860`, then re-run
`tools/ds_share_sync.py` because `dist/` is gitignored and never survives a merge.

**Consequence, expected and not a defect:** `test_sr_draft_profile_engine.py::
TestLiveEngineIntegration::test_live_three_profiles` is RED on this branch
(`'1.278.1' != '1.279.0'`) and stays red until the merge AND the restart. A merge
without the restart leaves it failing.

**A gitignored orphan nearly poisoned the provenance.** The ingest dist bundle
already read `1.279.0` at session start, built by a prior aborted attempt whose
commits never landed. It MATCHED the new constant while encoding different code,
so a green `--check` would have proved nothing; it was force-rebuilt.

**Gates, fresh on a frozen tree:** DS **10722 passed / 13530 subtests / 0 failed**
(repo root); RC `tests/ -q -n 8` **20300 passed / 136 skipped / 1 failed** (the
structural skew above); four ritual guards 28 passed; ruff clean; sync `--check`
exit 0. Verifier: **11 claims, 11 CONFIRM / 0 REFUTE**. Anchors 4/4; 149
`ENGINE_VERSION` pins swept across 127 files.

**Still open in this lane:** RM-208 (DS doc route-list guard is regex-blind to the
two `/v2/*` routes and checks one direction only) and RM-220 (109 label
comparisons never run). Both Tier-1, both untouched this run.

---

# 2026-09-01 - lane 5 Headless-Research REFILL (lane/research, docs-only)

Branch `lane/research`, NOT merged - left ready for the merger per the standing
worktree rule (an interactive session holds `C:/Riot Commander`).

**Which lanes were starved was MEASURED, not guessed.** `LANE N` tag counts across
ROADMAP + BACKLOG at run start: lane 8 = 103, lane 7 = 47, lane 4 = 10, lane 6 = 8.
So the refill targeted 4 and 6. Seven rows filed or corrected, **RM-322 through
RM-328**; next free id is now **RM-329** (`docs/DS_SWEEP_TRACKER.md:72`).

**The recall gate changed the run's shape and that is the headline.** A dispatched
census of unrun test trees was REDIRECTED mid-flight because `perseus_recall`
surfaced LEDGER 1215 / RM-170 (CLOSED 2026-08-06), which had already measured that
exact population into `docs/OPERATIONS.md`. Re-tasking the slice from "derive the
census" to "is the recorded census still true" is where the real defect was.

**Filed (bodies + acceptance in `BACKLOG.md`, compact pointers in `ROADMAP.md`):**
- **RM-322** (LANE 7) - the self-labelled AUTHORITATIVE test-scope table at
  `docs/OPERATIONS.md:27` is stale 4 ways. Re-measured: `tests` 18820 -> 20410,
  DS 10463 -> 10687, agent3 360 -> 359, root 29998 -> 31811. Its own invariant
  still closes exactly. `benchmarks` IS run by `codspeed.yml:51`, so CI-unrun is
  TWO trees / 707, not three; CI has NINE pytest sites, not two. **Acceptance
  deliberately FORBIDS a count guard** and points at the existing structural guard
  (`test_skip_condition_hygiene.py:1431`).
- **RM-323 / 324 / 325** (LANE 6, DS) - Arena mirrors `223118`/`224646`/`226655`
  credit 0.00 magic burst while their own notes state the SR magnitudes their twins
  return; `level: Infinity` returns HTTP 500 where the float sibling returns 400;
  `mode="ARAM"` gives multiplier 0.87 but `mode="aram"` gives 0.92 and `"FOO"` is
  accepted with 200. All three PROBED live or in-process by the merger.
- **RM-326 / 327 / 328** (LANE 4, UI) - the lobby view is the only polled panel with
  no idempotent-render gate (2 s timer, two unconditional `innerHTML` clears, focus
  dies invisibly); Top-8 reorder buttons re-index on click so a second click undoes
  the first; `renderTeamContext` returns at its second line every call because
  `cs-team-context-block` is in no HTML. RM-328 is DECIDE-THEN-ACT with no
  prescribed resolution.

**Corrected in place, not struck:**
- **RM-314** constructor census 12 -> **17**. A verifier reached 17 independently,
  and `tests/test_anthropic_base_url_pin.py:23-40` already lists exactly those 17
  behind a passing exhaustiveness guard - the repo had said 17 all along. The row's
  substantive claim (no client sets `timeout=`) is UNAFFECTED and true. My own
  opening hypothesis, that RM-314 and RM-302 were duplicate mints, was WRONG and is
  recorded as refuted.
- **RM-294b** DOWNGRADED. Its discovery is a rediscovery of what OPERATIONS.md:41
  and ROADMAP_HISTORY.md:128 recorded 25 days earlier, and 3 of its cites are wrong.
  Its ACTION half survives, re-scoped to two trees. Striking it entirely would have
  destroyed real lane-7 work.

**New closed negatives (do NOT re-run these sweeps):** undefined-CSS-custom-property
is EXHAUSTED at RM-209's seven; the banned non-ASCII glyph set is EMPTY across
`web/**` and `rc-shell/**`; DS route-seam transport-vs-flag is well guarded by
`test_ds_parity_map.py`; all 32 route-facing DEFAULT-OFF seams ARE exercised ON;
per-map `ITEM_EFFECTS` coverage complete on all 6 live maps; `DAEMON_SLAYER.md`'s
108/89 CC and 34-route claims both re-measure CORRECT.

**Method trap that cost real time twice in one run:** `grep -P` aborts under this
Git Bash locale ("supports only unibyte and UTF-8 locales") and with stderr unread
that reads as a clean sweep. It produced a false zero for the merger AND for one
slice independently. A `git ls-files | xargs grep` also returned empty for its
CONTROL as well as its target (exit 123) and was discarded rather than believed.
Every sweep here was re-run with a proven control. See
`feedback_empty_grep_is_a_claim_about_the_pattern`.

**Next session:** `C:/Users/Administrator/Desktop/RC-NEXT-SESSION.txt`.

---


# 2026-09-01b - lane 4 headless-uiux: ELECTRON OVERLAY only (LEDGER 1316)

Operator scoped the entire run to the Electron overlay (rc-shell + the in-game dock)
and split the mandate: SHIP the text-verifiable through the 5-phase audit, PREPARE
anything ending in a rendered-pixel judgement (RM-122 fences those to operator-present).
Branch `lane/uiux`, baseline `30156a0b`. NOT merged to main - that is a deployment and
belongs to the merger session.

**SHIPPED (all measured in real headless Chromium, not read off source):**
1. The in-game overlay layout menu was **silently mouse-only**. `_renderMenu` does
   `menu.innerHTML = ""` and both the toggle handler and "Reset all panels" call it,
   destroying the control just activated - Enter on any of the 10 toggles dropped
   `document.activeElement` to `BODY`. Fixed with a stable-key capture/restore
   (`data-ovx-ctl`); focus now survives AND the toggle still flips.
2. **B-OVL-4 closed.** The draft-elo chip computed a full payload every tick and painted
   a 0x0 box in-game (`checkVisibility()` false under a `display:none` pane head).
   Re-parented into a new `.am-pane-chips` row; the hide rule untouched, per the fence.
3. The 2026-07-06 overlay-drag revert had **three** stale sites, not one. All corrected,
   anti-drift test added. The third was found by the audit, not by the slice.
4. `overlay_layout.drag.test.mjs` had been RED since 2026-08-11 and **nothing ran it** -
   CI has no `node --test` at all. Repaired + mutation-checked; node suite 20/21 -> 21/21.
5. The lane doctrine's own trap-2 citation was FALSE (`dev.js` has no focus code; it is an
   OPEN instance of the defect). Corrected + pinned by a new 4-test guard.
6. `tools/pseudo_screen_out/` was not gitignored - the harness had been writing commitable
   PNGs all along.

**THE 5-PHASE AUDIT EARNED ITS KEEP:** an independent auditor returned **2 MUST-FIX**
against my own re-parent - the chips row did not collapse in `init`/`empty` (new 18x8
litter on the HUD in the default state), and the chip carried a dashboard **lethal red**
into an AMBIENT-tier widget, against doctrine rule 4. Both fixed in-slice. Lesson worth
keeping: a newly-PAINTING element inherits the overlay's rules, not its origin surface's.

**PREPARED-for-operator (NOT done):** DS3 in-game legibility - spec + render harness +
24 renders at 2560x1440 (4 variants x 3 backdrop proxies) + 11 mutation-checked tests.
Stated plainly: no client, no game, no frame archive on this box, so nothing was rendered
over real game pixels and the proxies can ELIMINATE a variant but not ELECT one.

**The biggest thing found and deliberately NOT fixed:** `#view-active-match .am-pane`
(specificity 1,1,0) BEATS the overlay's own `body[data-shell="overlay"] .ovx-widget.am-pane`
(0,3,1), so `w-call`/`w-build`/`w-ovds` paint an OPAQUE dashboard purple in-game. The
PRIMARY in-game widget is not see-through. Text-verifiable diagnosis, but the fix flips it
translucent over live gameplay = RM-122 class. Filed F-OV-1, specified in all 3 variants.

**Gates (fresh, frozen tree, after the last edit):** RC 20296 passed / 137 skipped / 4750
subtests / 1 failed; rc-shell 329/329; node 21/21; ruff clean; snapshot_panels 424.
The 1 failure is the KNOWN fenced `test_cli_version_still_matches_the_pin` (CLI 2.1.251 vs
pin 2.1.220), untouched here, skips on CI - LEDGER 1273. Verifier gate: 15/15 CONFIRMED.
CI does not run on a lane branch (`push: branches: [main]`), so no CI signal is claimed.

**Next session:** F-OV-1 through F-OV-11 in `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md` are
the queue. F-OV-3 (three more unfixed focus-destruction sites) is the cheapest real win and
reuses the pattern shipped here.

---

# 2026-09-01 - merger: lane 8 true-audit (61 commits) LANDED on main

Operator was given the framed decision (review+merge vs resume the loop) and chose
**merge**. lane/true-audit was the LAST unmerged lane (lane/repo already on main;
lane/ds + lane/research empty), so the "ships last" precondition was met.

**Landed: `main` @ `a41a2ad9`** (was `0779188f`). Two commits: the merge `e2a8f960`
(main folded into the branch in the worktree, then main FF'd to it) + a doc fix
`a41a2ad9`. Pushed to `Remus3/amberstone`.

- **Code: zero code conflicts.** Branch hardening vs main's advances (DS 16.17.1,
  ports, run_lane, dead-ops) are disjoint by file.
- **Docs: 6 conflicts, parallel-landing renumber.** LEDGER branch 1270-1306 -> +7 ->
  1277-1313; RM-221/222/223/227/228 (dual-allocations) -> 317-321; next-free = RM-322
  (authoritative in `docs/DS_SWEEP_TRACKER.md`). WAKEUP+history took main's canonical.
- **Review: 6 parallel adversarial slices, ZERO MUST-FIX.** SHOULDs all pre-existing/
  filed (RM-302/314 TFT timeouts, RM-294 warm_session lock).
- **Suite on merged tree:** DS 10687/0; RC 20272 pass + the known CLI-pin fail only.
  Fixed one net-new broken citation (BACKLOG -> WAKEUP:174, from main's shorter WAKEUP).
- **Follow-ups DONE:** RC restarted (pid 29904, code live); match_db repair dry-run
  0/8395 (already backfilled during the loop; `--apply` is a no-op; DB backed up).

**NEXT (do first):**
1. **ROADMAP size-budget relocation.** ROADMAP is 81757 bytes = 99.7 pct of the 81920
   budget (drift_guard WARN; main was a clean 86.7 pct before this merge). The branch
   carried it at 99.6 pct. Relocate CLOSED-row stubs from the active ROADMAP to
   `docs/ROADMAP_HISTORY.md` (their bodies are already there) to get back under 90 pct.
   NOT done inline at merge because the active list interleaves open rows with
   load-bearing do-not-re-open fences - it is the recurring operator-gated pass.
2. `restart_trigger.txt` did NOT self-clear after the restart (pid stable, no loop, so
   benign - the supervisor is content-keyed), but confirm it is gone / harmless.
3. `data/match_history.db.premerge-bak-20260901` (16.5 MB, gitignored) can be deleted.
4. Confirm the `a41a2ad9` CI `ci` job went green (docs-guards/CodSpeed already green).

Loop tooling was ephemeral (prior session scratchpad); to resume lane 8, restart via
Mission Control. ~27 orphaned claude.exe from the loop still linger (reboot or reap).

---

# 2026-08-31 - lane-8 true-audit loop: run_lane.ps1 opus-5 + bg-ceiling, 61 branch commits

Ran the Headless-True-Audit lane (lane 8) as a continuous autonomous loop from an
interactive session. Two main-tree fixes shipped + pushed:
- `a9ff183e` run_lane.ps1 reads the model from `ops/loop/config.json:executor_model`
  (claude-opus-5), not the hardcoded `claude-opus-4-8`. Governs all 7 lanes.
- `40f2a45d` run_lane.ps1 sets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=2400000` (40 min)
  so a worker's background verifier gate finishes before the CLI reaps it. MEASURED:
  at the default 600s the verifier was killed mid-run and the worker exited 0 having
  committed NOTHING - a lost cycle.

Loop produced 61 commits on `lane/true-audit` (`39b63ebb` -> `246af97d`), ~41 spawn
cycles, 14+ files hardened (riot_api, _handler, match_db, polled_json, routes_state/
diag, snapshot_normalizer, performance_tracker, sr_user_builds, _supervisor_http,
decision_detector, vision_server). Branch is UNMERGED - lane ships last, merger's
call. Independently re-verified `2eed2421` (polled_json per-writer scratch-name
concurrency fix) myself: 33 tests pass, and reverting the fix reds 4 guard tests.

Loop tooling lives in the session scratchpad (loop_driver.py + loop_spawn.py +
watch_lane8.py + lane8_loop_state.json), NOT committed - to resume, restart
loop_driver.py. Loop is STOPPED (operator wrapped).

Do NOT redo: the run_lane.ps1 fixes are shipped; lane commits are real (verify by
merge/file/test, never a worktree slice hash). Watch: headless workers can
hang-after-commit (~27 subagent children; taskkill /F /T reaps; the driver
auto-reaps on commit+clean+idle now); ~26 orphaned claude.exe subagents linger.
