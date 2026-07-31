# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-30b - DDRAGON PATCH REFRESH 16.14.1 -> 16.15.1 + the throwback-mode partition.

**1 commit pushed, `f9f134a4` -> HEAD `9df58480`. LEDGER 1130. ENGINE 1.268.0 UNCHANGED
(patch is not an engine version). DS `:8893` live at `patch 16.15.1, champions 173,
items 706`. Suites: DS 10234 / 5913 subtests, RC 17441 / 1370 subtests, 0 failed.**

## Start here next session

1. **The dirty-tree suite trap is GONE.** The 8 dirty `data/meta/ddragon_*` files were a
   half-finished 16.15.1 pipeline run; this session consumed them. The 76 untracked
   `Jade_*.png` icons were throwback-mode icons the pipeline no longer requests - deleted.
   `git status` is clean and the MAIN tree gives a usable suite signal again. The standing
   "do not touch those files" instruction is RETIRED, and so is memory
   `reference_dirty_ddragon_tree_fakes_49_failures` (verify before trusting it).
2. **16.15.1 shipped a THROWBACK-MODE registry and RC now partitions it.** Read
   `agents/daemon_slayer/mode_variants.py` before touching any roster or item derivation.
   The prior session's read that these are `Jade_<Champion>` ALIASES was WRONG in a way
   that mattered: they carry their own older-patch stat line, and the same drop added 162
   items in `[770000, 780000)` plus 16 `modes:["JADE"]` spells. The dedupe guard that
   landed last run defused champion inflation but could not have caught the item half.
3. **When a JADE mode appears in mode detection, revisit the partition rather than extend
   it.** The live Flash row already advertises a `KIWI_JADE` mode, so an ARAM-Mayhem-Jade
   variant on the Howling Abyss is the likely first contact - that is exactly why 151 of
   the 162 throwback items claim `maps["12"]`.

## What shipped

- **Full refresh chain**: DDragon meta + mirror, DS extract, abilities extract, FRESH
  CDragon spell + ratio sidecars, curated/wiki copy-forward with patch restamps, Lane B
  build orders (173 champs x 3 modes, 519 cells each), HZ precompute + variants, pickban
  targets, Share mirror (517 files), 20-file parity with 16.14.1.
- **The partition** at every PRODUCER - `data_pipeline` on download, `daemon_slayer_extract`
  for the snapshot and its manifest counts, three further raw-snapshot roster derivations,
  and `DataSnapshot.load` + `full_roster` again at load. Champions test on the KEY, items on
  a CLOSED id band, never a name prefix; both predicates fail SAFE (unparseable = KEPT).
- **Two real defects, not pin churn.** The ARAM resolver handed the coach the Arena
  Heartsteel stat line (700 HP instead of 900) once Riot flagged mirror `223084` map-12
  legal, because collisions resolved first-write-wins = lexicographic; now
  lowest-numeric-id-wins. That same fix CLOSED the reachability half of R144. And the
  CDragon stale-copy guard fired as designed on a copied-forward ratio sidecar, after both
  table families had already been built with ratios DROPPED.

## Lessons worth keeping

- **A "duplicate row" reading is not a partition policy.** The champion half looked like
  aliases and got a dedupe; the item half had no display-name collision at all and would
  have sailed straight into the ARAM pool. Measure every axis a drop touches, not the one
  that surfaced first.
- **The stale-copy guard paid for itself.** Its docstring predicted the exact failure
  ("only bites if a future patch-refresh copies a sidecar forward again") and it caught two
  silently-degraded table families. Copy-forward is safe ONLY for artifacts nothing gates.
- **Digest controls need a fixed substrate.** 26 rm91 controls broke on pure upstream drift.
  Recomputing them against 16.14.1 - all 13 byte-exact - is what separated drift from
  regression BEFORE anything was re-pinned. Pin the data, not the code.
- **The `--force` ban was honored.** The snapshot was made canonical by applying the same
  predicate in place, with no Meraki re-fetch, rather than re-extracting against a mutable
  `latest`.

---

# 2026-07-30a - HEADLESS ORCHESTRATOR RUN 2026-07-30-01: 9 slices, ENGINE 1.268.0, rc-shell green.

**10 commits pushed, base `31a7e722` -> HEAD `aef8a159`: `1a70f313` `69404dcc` `71df01fb`
`5d590a4f` `408e99ea` `a6886dc3` `42295aa2` `9b004331` `a0aef8a1` `aef8a159`.
LEDGER 1120-1129. ENGINE 1.266.0 -> 1.268.0, patch 16.14.1 unchanged. Every merge passed a
read-only verifier gate; the gates CORRECTED a slice claim twice, in opposite directions.**

## Start here next session

1. **The DDragon 16.15.1 patch refresh is STILL owed and is STILL its own session.** Carried over
   from 2026-07-29h and now with a second reason: slice S9 measured the uncommitted 16.15.1
   registry at **233 entries / 173 distinct**, the 60 duplicates being `Jade_<Champion>` alias
   rows. The dedupe guard landed, so the phantom-inflation bomb is defused - but the refresh
   itself is untouched and it also permanently fixes the dirty-tree suite artifact below.
   4-step chain + 3 hand-curated copy-forward artifacts; memory `reference_patch_refresh_workflow`.
2. **The main working tree still cannot produce a usable suite signal** (unchanged from
   2026-07-29h): 8 dirty `data/meta/ddragon_*` files + 76 untracked `Jade_*.png` icons fake tens
   of failures. Worktrees are unaffected. Memory `reference_dirty_ddragon_tree_fakes_49_failures`.
   **Do not touch those files** - the operator is holding them deliberately.
3. **`rc-shell` `npm test` is a usable gate again - 326/326, exit 0.** It had been red at HEAD for
   at least a session. Use it before any overlay work.

## What shipped

- **`1a70f313` S2 - the ARAM item-interaction corpus is TRACKED**, closing the carry-forward risk
  LEDGER 1115 disclosed. It degraded SILENTLY at three stacked fail-soft layers, so an absent
  corpus read as "no evidence" rather than "corpus missing". Regeneration is IMPOSSIBLE (sole
  input `data/rewind_history.db` is 1.87 GB and gitignored), so tracking was the only route:
  300745 bytes, pure ASCII, 776 cells, zero player identifiers, byte-identical on re-run.
- **`69404dcc` S4 - the `docs/ELECTRON_OVERLAY.md` section-5 window-state table is now PARSED**
  by `rc-shell/test/overlay_state_contract.test.js` and drives its assertions, so the doc alone
  can turn the suite red. Two rows were prose defects fixed in the DOC: champ-select is plain
  hidden, and there is NO post-game fade anywhere in `rc-shell/src`. `Alt+Shift+R` was missing.
- **`71df01fb` S1 - RM-118, the THREE rune lanes reach their routes. ENGINE 1.267.0,
  `STRANDED_TODAY` 19 -> 16.**
- **`5d590a4f` S5 - `rc-shell` `npm test` unstuck.** The TEST was stale, not the source. Root
  defect: two suites asserted OPPOSITE results for one call because `rc-shell/package.json`
  omitted `enemy_spells_timer.test.mjs` from the gate.
- **`408e99ea` S6 - RM-118, the TWO vamp lanes. ENGINE 1.268.0, `STRANDED_TODAY` 16 -> 14.**
- **`a6886dc3` S7 - precomputed build-order coverage measured at 4671/4671 cells, 100.00
  percent**, across THREE artifact families and TWO champion keyspaces. Mayhem maps onto the
  aram tables via `district_config`, so it is not a fourth keyspace.
- **`42295aa2` S9 - the build-order producers now FAIL LOUD.** `full_roster()` fell back to a
  10-name seed on a registry error and exited 0; the sweep found 3 more, two worse (a
  ZERO-champion table exiting 0; a full-size table of EMPTY orders on mid-sweep engine death).
- **`9b004331` S8 - `docs/COMPETITOR_LIFT_2026-07-30.md`, TFT-lane teardown.** Category rotated
  by measurement: 25 prior lift files hold ONE TFT mention, graded "new data domain, NO" - and
  that grade was wrong, because RC already ships a 3117-line `tft/` lane.
- **`a0aef8a1` + `aef8a159` S10 - TFT meta mojibake + deterministic roll odds.** See below.
- **S3 cost/latency 7-lever sweep: ALL SEVEN CLEAN, no commit** (LEDGER 1129). This lever set is
  now drained twice running - rotate elsewhere unless a specific regression signal points here.

## The three findings worth more than their slices

- **A guard's universe must come from the AUTHORITY on the artifact, never from what is sitting
  in the directory.** Three instances this run. S7: the pre-existing build-order tests enumerate
  the ARTIFACT, so a 10-champion regen defines its own universe as 10 and passes - the new tool
  derives from PRODUCER constants. S10 `aef8a159`: a fresh ASCII guard globbed `data/meta/*.json`
  off DISK, so it passed in CI and FAILED on the operator's machine (a gitignored 24 MB CDragon
  dump); universe is now `git ls-files`.
- **The repo's own no-em-dash drift check was blind to the case that had already happened.**
  `tools/strip_em_dashes.py` prefiltered on raw `E2 80 94`, which no MANGLED form contains, so it
  never opened `data/meta/tft_set17_meta.json` (294 non-ASCII bytes, most TRIPLE-encoded, in
  fields feeding a live Haiku prompt) and reported the repo clean. Now fixed via a latin-1
  mis-decode ladder sharing one function between detection and repair.
- **Measure route ownership off `inspect.signature`; never inherit it from a sibling docstring.**
  Learned TWICE this run in OPPOSITE directions. S1: the survivability rune lanes ALSO live on
  `compute_ehp` + `rank_items_by_ehp`, which the brief omitted. S6: `compute_ehp` is the SOLE
  owner of both vamp lanes, so the dps/hybrid family the brief named owns neither. Corollary:
  check the TRANSPORT too - `/dps` had no `rune_ids` and `/ehp` had no `targets_in_rotation`, so
  a flag-only wire would have been settable and arithmetically inert.

## Verification state at wrap

- DS suite: **10234 passed / 5912 subtests / 0 failed** (at `408e99ea`).
- RC suite: **14196 passed / 146 skipped / 1369 subtests / 0 failed** (in a clean worktree).
- Both Share release-entry sites carry 1.268.0 - the trap `ds_share_sync --check` cannot see.
- `rc-shell` `npm test`: **326/326, exit 0**.

## Owed / FUTURE, in priority order

1. **DDragon 16.15.1 patch refresh** - its own session (BACKLOG).
2. **Set 17 TFT constants need a LIVE IN-CLIENT read.** `tft/tft_data.py` declares Set 14, both
   set modules ship byte-identical odds, `tft_pbe_data.py` has no `UNITS_PER_COST` at all, and
   the repo's own Set 17 patch notes contradict `TIER_ODDS[7][3]`. Both modules now carry
   `CONSTANTS_SET_VERIFIED = False` and a guard hard-fails if one is marked verified while stale.
   **Do NOT let a future session "fix" these from a third-party table.**
3. **`tft/tft_roll_odds.py` is wired into NO coach.** Wiring it is the actual Haiku retirement
   and needs live validation.
4. **RM-118 next batch: exactly 4 wireable seams remain** - `apply_ability_hsp_amp`,
   `apply_cast_rate_propensity_prior`, `apply_crit_chance_overrides`, `assume_ms_utility`. The
   other 10 of the 14 are declined by design.
5. **ARAM Mayhem augment on-screen confirm** (G3-13), carried from 2026-07-29h - still owed.
6. **MEMORY.md compaction** - measured 20129 bytes / 120 lines; a mechanical hook-strip saves
   ZERO because the bytes are all pointers, so it is curation and wants its own session.
7. **`tft/tft_pbe_data.py` still carries 18 `U+2192` arrows** - out of scope for the dash rule,
   flagged by the verifier.

---

# 2026-07-29h - HEADLESS ORCHESTRATOR RUN 2026-07-29-01: 6 slices, CI repaired, ENGINE 1.266.0.

**9 commits pushed: `f69a15c7` `1ec67d0c` `f6e8c11c` `0dffb844` `b4919236` `cff8d678` `85e7fb67`
`a5fe1ea7` `635f8f3f`. LEDGER 1113-1119. CI GREEN - full dual suite success on `cff8d678`.
Every merge passed a read-only verifier gate; 3 of the 5 gates corrected a claim the slice got wrong.**

## Start here next session

Two things are load-bearing and neither is code:

1. **THE MAIN WORKING TREE CANNOT PRODUCE A USABLE SUITE SIGNAL.** Full RC suite here: **53 failed**.
   With the 8 dirty 16.15.1 ddragon files stashed: **4 failed**. So **49 failures are uncommitted-DATA
   artifacts**, and they masquerade as real regressions (build-order routes, seam forwarding,
   AP-assassin override, precomputed laning coach). 3 of the remaining 4 are the **76 untracked
   `Jade_*.png` icons** inflating the champion catalog to 233 against the atlas's 173. The prior
   hand-off recorded this as "the 3 magic-pen failures are pre-existing"; the real number is 52.
   A worktree is unaffected (it inherits neither the dirty tracked files nor the untracked icons),
   which is why slice baselines read 2 failed while the main tree read 53. When main-tree and
   worktree counts disagree by tens, suspect this FIRST. Memory
   `reference_dirty_ddragon_tree_fakes_49_failures`. The data was stashed for the measurement and
   RESTORED - the tree is as the operator left it.
2. **A full patch refresh to DDragon 16.15.1 is owed and is its own session.** Upstream is 16.15.1 /
   meraki 25.15 / cdragon 16.15.7996036 (`ops/runtime/upstream_drift.json`, 2026-07-29T08:45Z) while
   `current.txt` and live `:8893` are pinned 16.14.1. The chain is 4 steps + 3 hand-curated
   copy-forward artifacts (skipping any breaks ~100 DS tests) + full table regen + DS restart, so it
   does not belong inside a multi-slice run. Memory `reference_patch_refresh_workflow`.

## What shipped

- **`f69a15c7` pre-flight CI repair.** `docs-guards` was RED on FOUR consecutive pushes: the 1.265.0
  bump restamped the Share README header but never prepended the public release entry.
  **`ds_share_sync --check` cannot catch this by design**, so it read green throughout. This pin site
  is the standing ENGINE-bump trap - `Share/CHANGELOG.md` AND `Share/README.md` both need touching.
- **`1ec67d0c` cost/latency sweep, 3 SHIP / 4 CLEAN.** Headline: `lcu/lcu_client.py` logged
  "LCU lockfile not found" at 1 Hz - **20144 of 21082 lines, 95.6 percent, 2.4 MB** of one day's log.
  Fixed as a transition latch (frozen-file edit under the run's grant, which does NOT carry forward).
  Also `tests/test_anthropic_base_url_pin.py` was worktree-blind and goes red during ANY orchestrator
  run; only SET-EQUALITY guards break that way, verified by sweep (memory
  `reference_repo_root_guard_worktree_blind`).
- **`f6e8c11c` ARAM deterministic shadow field gaps (Haiku-to-ZERO Lane C).** Three root causes, none
  where the filed row pointed. Best finding: `choices` both=0 was NOT a coach gap but a shadow READER
  carrying a hardcoded 6-key tuple that had drifted behind the writer's 9 keys - a column the reader
  never reads can never appear. Both readers now derive from the writer.
- **`0dffb844` RM-118 residual, ENGINE 1.265.0 -> 1.266.0.** 4 EHP survivability seams wired
  engine->route->client. `STRANDED_TODAY` **23 -> 19** (the ROADMAP's "22" was never right at either
  endpoint). 10 of the remaining 19 are declined by design, not debt.
- **`b4919236` served next-item callout.** Same raw-slot-count root cause as `f6e8c11c`, served side.
  Kalista with 4 legendaries + trinket + potion: old index 6 -> None, corrected 4 -> Kraken Slayer.
  **SR-ONLY** user-visible change (`_RECALL_MODES == frozenset({"sr"})`).
- **`cff8d678` ARAM Mayhem augment cadence.** An OPEN bug closed in code. Bounded four ways because
  it makes a PAID vision call fire more often; worst case +4 scans/game against a hard +6 ceiling,
  and plain ARAM pays zero. **LIVE ON-SCREEN CONFIRM IS OWED - not verified fixed.**
- **`a5fe1ea7` context management folded into the headless-upgrade skill** (operator-directed): new
  section 10c plus four ritual wire-ins, so every future run carries the discipline instead of
  rediscovering it. Both the tracked `tools/headless-upgrade.md` and the gitignored live copy under
  `.claude/commands/` were patched to byte-identical; NO parity guard was added on purpose, because
  the live copy is absent in CI so a guard would have to skip when missing - the exact masking-skip
  pattern this repo audited out.
- **`635f8f3f` item-spike legendary count** - the third and last consumer of the slot-count root
  cause, and the run's largest served-output change (all three modes). See LEDGER 1119.

## Verification state at wrap

- DS suite from repo root: **10162 passed / 0 failed / 5776 subtests**.
- RC suite: **14187 passed**, 3 failed - all three are the untracked-Jade-icon artifacts above.
- DS `:8893` live at **1.266.0** (patch 16.14.1, 173 champs / 706 items). RC pid 21244, reload_ok.
- `ds_share_sync --check` green at 1.266.0 / 516 files.

## Three filed rows probed and found STALE - no work was manufactured

- **`roadmap work.txt`** (the last RM-121 desktop item): its task is RM-119's RC half, CLOSED
  2026-07-28. Its "also open" `wakeup_prune.py` note (blind to `## ` headers, 12 sessions invisible,
  61KB) is stale too - this file is 6.5KB, 3 sessions, all `# ` headers, `--check` clean.
- **ROADMAP skip-audit class B5** ("~22 sites remain OPEN"): machine-closed.
  `tests/test_skip_condition_hygiene.py` passes 22/22 with exactly ONE reviewed exemption.
- **RM-122** was correctly NOT picked up - it is operator-present by its own gate.

## Owed / FUTURE, in priority order

1. **ARAM Mayhem augment on-screen confirm** (G3-13). The RM-25 hold-25s workaround is retired.
2. **The item-spike twin - DONE at wrap, `635f8f3f` (LEDGER 1119).** It also fixed a SECOND bug: at 6
   used slots the old count passed every threshold, so the active spike row was silently DELETED late
   game. It counts completed LEGENDARIES, not build-order progress - 171 of 173 champions carry boots
   at build index 1, so a build-order count would have called Berserker's Greaves a 1-item spike. NOT
   mode-gated, so SR + ARAM + Arena all change. Residual FUTURE: the restored rows now compete in the
   existing `max_n=3` advisory cap, which is pre-existing priority policy, not a new defect.
3. **`data/coaching/aram_item_interaction.json` is gitignored** - deterministic `item_build_reasons`
   coverage is machine-local and absent in CI. Must be tracked or regenerable before any Haiku flip.
4. **RM-118 next batch**: the 3 rune lanes across `/dps` + `/hybrid` + `/rank-bruiser` (one server.py
   pass), then `assume_crit_weighted_vamp`, then `assume_ms_utility`.
5. **Mayhem multi-stage augments**: a `game_seconds` ceiling covers stage 1 only. Wait for item 1.
6. **MEMORY.md compaction** declined deliberately: 20129 bytes over 120 lines, and a mechanical
   hook-strip saves ZERO because the bytes are all pointers. Reaching the threshold means dropping
   pointers, which is curation. Wants a dedicated pass, not a hasty mid-run trim.
