# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-01c - MERGER session: ROADMAP trim + 3-lane merge + gist-sync fix

Interactive merger session; everything below is on main + CI-green, all five lane
branches 0 commits ahead of main.

**Shipped:** ROADMAP trim 100 pct -> 89 pct (24 closed stubs + the RM-192..202
compact-open-row split relocated to ROADMAP_HISTORY; the RM-171 ROADMAP.md
line-231 citation baseline re-added as its DISCHARGED note predicted). Three hygiene fixes:
augment-source `-n 8` flake `30156a0b`, CLI pin 2.1.220 -> 2.1.251 after a canary
re-run `f0c847f8`, TFT debounce made hermetic `6ac142f1`. MERGED all three lane
branches: research (RM-322..328), uiux (overlay focus + chip paint), ds
(RM-323/324/325 + ENGINE 1.279.0). DS DEPLOYED live: `:8860` bounced -> 1.279.0,
`test_live_three_profiles` green.

**Gist-sync corruptor FIXED `01e6530bb`:** `tools/gist_share_sync.py` `_git` left
the hook-injected `GIT_DIR` inherited, so `git -C CLONE_DIR` operated on the
committing worktree - corrupting `lane/ds` and force-pushing to the wrong remote.
Now scrubs the env; 3 regression tests; validated 3x under real Share commits. Full
mechanism in LEDGER 1318.

**Do NOT redo:** all three merges landed; DS 1.279.0 is deployed + live; the gist
bug is fixed. **Still open (flagged):** rc-shell overlay needs an operator Electron
relaunch; uiux PREPARE items (legibility variants + opaque-widget defect) are RM-122
operator-present; lane-6 RM-208/RM-220 + research RM-328 open in BACKLOG.

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
