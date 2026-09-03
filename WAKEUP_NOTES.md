# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-02 - lane 5 Headless-Research REFILL (lane/research, docs-only, NOT merged)

Detached headless, operator away, full authority. Branch `lane/research` was 0 ahead
/ 13 behind `main` at start, fast-forwarded to `ca1e6447b` before any probing so the
worktree matched live DS (its `ENGINE_VERSION` read 1.278.1 against `:8860`'s 1.279.0
until the ff - do NOT probe a lane worktree without checking that first).

**Filed RM-329..RM-336, next free id RM-337** (registry `docs/DS_SWEEP_TRACKER.md:72`).
Six LANE 6, two LANE 7. Bodies + acceptance in `BACKLOG.md`, pointer in `ROADMAP.md`,
LEDGER 1319.

**Why lane 6:** it was the starved lane and the tracker was UNDERSTATING it. Its
ROADMAP-visible open work was ONE row. RM-323/324/325 were filed by the 2026-09-01
refill and closed by lane 6 within a day; RM-118's wireable debt is zero at both tiers
(RE-MEASURED here: `STRANDED_TODAY` 5, `STRANDED_DEPTH1` 0); and RM-220 - actionable,
LANE 6 - had no ROADMAP entry at all. Pointer added.

**The refutation pass earned its cost - it changed three of nine candidates.**
- **RM-332 killed as a defect**, kept as a Tier-0 note fix. `unique_passive_key` is a
  DEDUP family, not a shield family (`effects.py:256-260`, `ehp.py:2966-2972`), and
  DDragon 2525 grants "maximum Health ... then heal", not a shield - so `shield=None`
  is CORRECT. Only the two note strings are wrong. The row now FENCES the guard it
  resembled: `test_lifeline_target_shield_r59.py:54`'s hardcoded set is a TARGET-SIDE
  assumption (`_lifeline_target_shield.py:34`), and deriving it would invent EHP.
- **RM-330's live-defect claim refuted twice**, so it is filed DECIDE-THEN-ACT rather
  than as a bug. The cited chain dies at `cc_blended_ehp_context.py` (zero DS
  dispatch); the fallback chain dies too - `build_capability_gap` is spelling-
  insensitive, byte-identical for `Chogath`/`Cho'Gath` and `MonkeyKing`/`Wukong`. An
  id-only contract is already written at `routes_cc_blended_ehp_threat.py:33-38`.
- **RM-329's framing corrected** - nothing is "dropped"; `ehp.py` has zero
  `MODE_MAP_ID` occurrences and no mode-note lane at all. Severity capped: no live
  caller can send an unconstrained mode.

**Doc drift fixed in place, and it was a repeat offence.** ROADMAP's first NOW content
row carried RM-203 as OPEN while BACKLOG had it CLOSED 2026-08-15 - and
`docs/LEDGER.md:669` (LEDGER 1270) had already logged "Quick win: ROADMAP RM-203 was
OPEN against LEDGER 1265" on 2026-08-16 and never applied it. Struck in place with the
cite. A sweep of all 73 ROADMAP ids against 141 BACKLOG ids found this was the ONLY
divergence, so it is a single miss, not rot.

**MEMORY.md sub-index counts DELETED, not refreshed** (the LEDGER 1270 precedent).
All four were stale - 79 / 20 / 31 / 59 actual against 73 / 19 / 30 / 41 recited, ops
off by 18 - and nothing guards them.

**New probe trap, found by falling into it** - memory
`reference_ds_probe_flag_needs_its_scoring_axis`. A DS flag probe reads INERT unless
the request also selects the axis the flag moves: `/rank-tank` + `apply_build_tenacity`
returns identical arms until you add `score_by="cc_blended"`. Nearly shipped an
"inert everywhere" framing. Two siblings recorded: `apply_rune_offense_grants` is
+0.00 on Jinx (AS-locked, `dps.py:1321-1333`), and the `/dps` build key is `items`,
not the output echo `item_ids`.

**No external lift, deliberately.** The competitor-lift category is DRAINED (LEDGER
880). No `COMPETITOR_LIFT_<date>.md`, no license gate triggered, nothing external read
or quoted.

**Gates:** doc size budget 2 passed; citation + drift guards 58 passed / 92 subtests;
roadmap/backlog-selected 5 passed; `tools/drift_guard.py` 0 breaches; zero non-ASCII in
every authored line, gated BEFORE insert. ROADMAP 75299 of 81920 bytes.

**NEXT:** branch is READY and UNMERGED per the worktree rule - the merger takes it.
Lane 6 now has 8 actionable rows (RM-208, RM-220, RM-329..334); lane 4 still holds
RM-326/327/328 + RM-209 unworked from the previous refill.

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

