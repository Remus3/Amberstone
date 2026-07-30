# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-29g - RM-118 wielder HSP item-amp reaches the HYBRID (bruiser) RANKER (ENGINE 1.264.0 -> 1.265.0).

**Commit `fb72d0f9`, pushed. Tier-2: engine-signature change + new route seam, ENGINE bump, Share resync, DS :8893 restarted -> 1.265.0.**
The remaining open half after 2026-07-29f (which did the EHP/tank ranker). RM-124 live validation
(G2-39) still blocked - no SR game (mode=client, LCU Offline, relay empty). Probe live state first.

What shipped:
- `assume_hsp_amp` now reaches the HYBRID ranker (`compute_hybrid`/`rank_items_by_hybrid`, a SEPARATE
  module from the EHP ranker). Three gates: engine (kwarg at END -> baseline + candidate `compute_ehp`,
  3 call sites), route `_route_rank_bruiser` -> `/rank-bruiser`, client `rank_bruiser_for` (emitted via
  `_emit_ehp_family_seams`). DEFAULT-OFF, byte-identical OFF; INERT unless a self-shield item
  (Sterak's 3053 / Shieldbow 6673) is in the build.
- TDD RED-first `tests/test_rank_hybrid_hsp_amp_rm118.py` (11 tests). DS suite CLEAN 10138 passed / 0 failed.
- `test_rune_resist_signature_convention_r134.py` gained `_RM118_TAIL` on the two hybrid fns (expected END-shift).

Two things worth not re-learning:
- **The dirty 16.15.1 ddragon working-tree data poisons any build-table regen.** First regen showed a
  958-line CONTENT diff (item 6653 added) that was NOT my DEFAULT-OFF seam - it was the dirty ddragon
  data. Fix: `git stash push` the `data/meta/ddragon_*.json` + `web/data/*_index.json`, regen against
  clean HEAD (tables then diff ONLY the version stamp + timestamp), `git stash pop` to restore.
  Those data files stay do-not-refresh.
- **The 3 magic-pen `773020` (Sorcerer's Shoes) DS failures are PRE-EXISTING** and dirty-ddragon driven,
  not any code change - confirmed by re-running that file with the ddragon data stashed (9 passed / 0 failed).

STILL OPEN in RM-118: the 22 ledgered seams in `test_stranded_hsp_seam_r197.py::STRANDED_TODAY`.

---

# 2026-07-29f - RM-118 wielder HSP item-amp reaches the EHP RANKER (ENGINE 1.263.0 -> 1.264.0).

**Commit `e075a221`, pushed. Tier-2: engine ranker-signature change, ENGINE bump, Share resync, DS :8893 restarted -> 1.264.0.**
Picked as the next headless-safe NOW item because RM-124 live validation (G2-39) was blocked - no SR
game (LCU Offline, relay empty). Probe live state first every session.

What shipped:
- `assume_hsp_amp` (Redemption 3107 = 0.10 + Mikael 3222 = 0.12 wielder HSP amp) reached only the
  SCALAR lanes (`/ehp`, `/sustain`) after R197. `rank_items_by_ehp` - where a tank item CHOICE is
  decided - never accepted it. Threaded through all THREE gates (R194 slice A precedent): engine
  `rank_items_by_ehp`, route `_route_rank_tank`, client `rank_tank_for`. DEFAULT-OFF, byte-identical
  OFF. INERT unless a self-shield item (Sterak's 3053 / Shieldbow 6673 / Maw 3156) is in the build -
  the amp scales the ItemShield pool, empty on the HSP pair alone (honest R197 finding).
- TDD RED-first `tests/test_rank_ehp_hsp_amp_rm118.py` (11 tests). DS suite 10127 passed (10116 + 11).

Two things worth not re-learning:
- **RM-118's "three assumed-share seams parsed but never forwarded" sub-claim was STALE AT FILING** -
  they were wired 2026-07-25 (`e6b7b238`), two days before the R197 filing said they were not. Verify
  filed rows on disk; do not rebuild a filing's prose. (ROADMAP RM-118 UPDATE + LEDGER 1111.)
- **A new DS test importing `core.daemon_slayer_client` MUST be added to `ds_share_sync.py`'s
  exclusion list** or the pre-commit hook mirrors a collection-error into Share and breaks its
  standalone suite. Bit me this session; caught + fixed in the amend. Memory
  `reference_ds_share_sync_exclude_client_tests`.

STILL OPEN in RM-118: the HYBRID ranker half (`compute_hybrid`/`rank_items_by_hybrid`, separate
module - narrow-then-widen), + the 22 ledgered seams in `test_stranded_hsp_seam_r197.py::STRANDED_TODAY`.
PRE-EXISTING (not mine, do not chase in an RM-118 context): the Share standalone
`test_antitank_axis_score_invariance_r196` fails because `_REPO_ROOT=parents[3]=Share/src` has 5
antitank consumers < the 15 the repo-wide scan expects - a mirror-subset structural failure at HEAD.
