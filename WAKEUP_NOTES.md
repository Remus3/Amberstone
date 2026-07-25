# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-27 - five open-item slices, parallel in-repo agents (ENGINE 1.244.0)

HEAD after this session: see `git log -1`. ENGINE **1.244.0**, patch 16.14.1,
DS **9369** / RC suite re-run this session, DS `:8893` bounced and serving 1.244.0.
Full narrative: `docs/LEDGER.md` 1043.

## What shipped

1. **C-06 / RM-26** - vision-profile seeds were dead on disk. New `resolution_seed`
   tier in `core/vision_profiles.py` between the exact-`config_key` hit and
   `legacy_seed`. The ultrawide accuracy caveat is preserved verbatim; no parity
   claim across aspect ratios.
2. **B-01b** - `is_augment_select` re-homed into ARAM + Arena `TIERED_FIELDS`
   (brawl deliberately excluded - zero augment references in that coach).
   `RC_VISION_MERGE_STRICT` is still **NOT** default-ON; see below.
3. **A-01b + A-01c** - `widen_carry_pool` seam-forwarded through
   `core/daemon_slayer_client.py` AND `coach_integration/archetype_dispatch.py`.
   It was broken in two places, not one.
4. **C-17** - filed cause refuted, real cause fixed. Seven DS cards plus the L4
   capability-gap chip were dead in **every real game**, not just headless.
5. **RM-98** - cast-propensity prior, DEFAULT-OFF `apply_cast_rate_propensity_prior`.

## Three things that would have shipped wrong

- **C-17's filed cause was false.** "Gates on `isLive`" - it does not; `?ui_mock=1`
  sets `lcuPhase: "InProgress"`. Had that been built as filed, the actual bug (a
  slug fed to `parseInt`) would have survived, and it was a LIVE bug, not a
  headless one. The operator tagging the row SOURCE-READ is what caught this.
- **The RM-98 brief's formula was the identity.** `theoretical * (measured/theoretical)`
  is a no-op; the agent said so instead of building it, and introduced the p90
  reference the construction actually needs.
- **A DEFAULT-OFF seam was almost assumed to be a no-op.** It was PROVEN instead:
  regen against the restarted 1.244.0 server returned all three tables
  byte-identical except `generated_at`.

## Standing hazards for the next session

- ENGINE bump ritual order is bump -> RESTART `:8893` -> regen -> measure. The
  generator computes over live HTTP; a stale server returns a confident, wrong
  "0 changed". Verified live this session (`/health` read 1.244.0 before regen).
- 372 test files carry the ENGINE literal pin. Bump them by quoted-literal
  replace; `.pyc` files will still grep-match and are noise.
- `tools/daemon_slayer_build_orders_generate.py` takes `--mode`, NOT `--champions`.
- **The build-order tables live in TWO keyspaces and last session only regenerated
  ONE.** `tools/daemon_slayer_build_orders_generate.py --mode all` writes
  `data/daemon_slayer/16.14.1/`. The `build_order_precompute/v1` artifacts under
  `data/daemon_slayer/build_orders/16.14.1/` come from
  `python -m core.build_order_precompute --static --mode all --champions all`.
  At HEAD `b23b5f16` that second keyspace still carried the denied Arena Golden
  Spatula `224403` **331 times** and Mejai's `3041` **17 times**, a full session
  after both fixes "landed" - and it is the keyspace `next_buy_fallback.py`
  reads. A regen is not done until BOTH are re-run, and "0 changed" in one says
  nothing about the other. **It is actually THREE families:**
  `build_order_variants_<mode>.json` has its own entrypoint
  (`python -m core.build_order_variants --static --mode all --champions all`) and
  carried the same pollution independently (arena `224403` x165, sr `3041` x50).
  **563 stale rows total were being served live.** Run the FULL `tests/` suite
  after a bump - each family has its own stamp guard and that is what found them.
- `tools/ds_feed_index.py` `KNOWN_STAMP_LAG` is not the source of truth the test
  reads. Edit the `.py`, then `python tools/ds_feed_index.py --write` to
  regenerate `tools/ds_feed_index.json`, or the guard stays red.
- **ROADMAP.md is now 76108 bytes / 3892 headroom** against its 80KB budget.
  That is tight. Relocate before adding a long row.
- Never run `tools/ds_share_sync.py` while a suite is in flight.

---

# 2026-07-26 - five open-item slices, parallel worktrees (ENGINE 1.243.0)

HEAD after this session: see `git log -1`. ENGINE **1.243.0**, patch 16.14.1,
DS **9353** / RC **12849**, DS `:8893` bounced and serving 1.243.0.
Full narrative: `docs/LEDGER.md` 1042.

## What shipped

| id | outcome |
|---|---|
| A-27b | **REAL, item-213 recurred.** Golden Spatula `224403` (Arena) was the FIRST BUY in 104 of 246 branch-instances across 82/173 Arena champions. Item 213 denied only the map-12 id. Now denies `224403` + `4403` + `443064`. Arena regen 82/173 changed, 246 -> 0. |
| A-25 / RM-94 | **REAL, wrong constant.** Mejai's `bonus_ap_stacked` 125.0 -> 25.0. Mage rank 9 -> 33/34/35, Riftmaker fills the slot. **Build orders UNCHANGED in all three modes** - it was already outside the 6-slot order. |
| B-01b | **REAL, shipped DEFAULT-OFF.** `vision_routing.py:118` scope filter behind `RC_VISION_MERGE_STRICT`. 104/232 shadow records change. |
| D-01b | **REAL, closed end to end.** Producer + consumer + a 572-row backfill. Games joined 41 -> 50, observations 378 -> 462, first ARENA cell ever. |
| A-02b | **REAL but MIS-COUNTED.** Two unmarked artifacts, not six. Guard DEFAULT-OFF on measurement. |

## Three things that would have shipped wrong

1. **The first table regen was a false negative.** 0/173 changed in every mode.
   `daemon_slayer_build_orders_generate.py` routes through `daemon_slayer_client`
   to the LIVE `:8893` server, which is NOT supervisor-watched and was still on
   1.242.0. **Ritual order is bump -> RESTART `:8893` -> regen -> measure.**
2. **The first backfill was a silent no-op.** It wrote the full `NA1_<id>` while
   `_game_key()` indexes on the bare numeric suffix. Joins stayed at 41. Redone
   with the bare key -> 50.
3. **B-01b default-ON would have been a live regression.** `shared_vision.py:418`
   aliases `is_augment_select` -> `augment_select` AFTER the merge, and it is in
   NO coach's `TIERED_FIELDS`.

## Standing hazards for the next session

- `ROADMAP.md` is **74778 bytes / 7142 headroom** after two prunes this session.
  Comfortable, but the 80KB `tests/test_doc_size_budget.py` ceiling is real.
- **Do NOT flip `RC_VISION_MERGE_STRICT` on** until `is_augment_select` is
  re-homed into a `TIERED_FIELDS` list. Also unmeasured: the same scope shrinks
  `_log_fusion_shadow`'s `cv_reads` payload.
- **Never re-run `tools/daemon_slayer_extract.py` in the same commit as a
  build-order regen.** It re-fetches the MUTABLE Meraki / CDragon `latest`
  endpoints and destroys attribution between the two changes.
- `ds_share_sync.py` must NOT run while the RC suite is in flight - it produced
  9 false failures this session.
- ARAM's 5257 keyless calibration rows are **permanently unrecoverable** (Mayhem
  is queue 2400 / `KIWI`, Match-V5 403s). Do not plan a recovery pass for them.

## Next 5 (see the closing handoff for the full framing)

C-06 / RM-26 vision-profile seeds unwired; A-01b `daemon_slayer_client` seam
forwarding; C-17 `ds_matchup` unreachable under `?ui_mock=1`; the RM-92
ability-haste residual (SIZED, verdict DEFER - re-read the scope doc before
re-opening); RM-98 cast-propensity prior.

---

# 2026-07-25 - open-item review + 6-slice orchestrated build (ENGINE 1.242.0)

Operator asked for ONE categorical inventory of every open item, then said build the
top 5 plus the runner-up in orchestrated parallel. LEDGER 1041. ZERO API / ZERO LLM.
Deliverable: `docs/OPEN_ITEMS_REVIEW_2026-07-25.md`.

**THE LESSON, and it is about the review method rather than any slice.** Every
inventory row carries a VERIFICATION TIER - PROBED / SOURCE-READ / AS-FILED. Three of
the six build targets turned out to be already shipped, and **all three were tagged
SOURCE-READ or AS-FILED. Nothing tagged PROBED collapsed.** Tag your rows, and treat
ROADMAP prose as a claim rather than a fact: 13 rows read open and are not, including
one (the champ-select brief Haiku flip) that survived in THREE separate docs eight
weeks after the flip actually happened.

**Built, real:**
- **B-01 RM-01 Lane E** - `data/fusion_shadow.jsonl` accrued 230 real-game records and
  **41 of 41 CV overrides in its whole history were garbage** (all `gold`, all the
  literal value `1`). Two causes: `core/vision_routing.py:118` merges unrequested keys
  from the Sonnet escalation, and `core/vision_fusion.py` had no plausibility check.
  Fixed at the fusion layer. Upstream half deferred - it changes served coach dicts.
- **D-01 RM-32** - data block cleared; built the pick-vs-outcome aggregator. First
  result is **instrumentation, not a verdict**: 41 joinable games cannot separate a
  +0.0677 shrunk delta from noise. 100 pct of ARAM + Arena rows have no `game_id`.
- **A-27 RM-114** - NEXT BUY coverage 6/173 -> 173/173, curated 6 byte-identical.
- **A-01 RM-04** - built DEFAULT-OFF, and **the premise is half-refuted**: the pool is
  108 not 111, and widening it changes ZERO top-8 entries for any of seven marksmen.
  Re-file as RM-86 scorer work.

**Already closed (do not re-dispatch):** RM-81 P0 (`4cd3c4c6` + `544d6362`),
competitor-lift F1 + F5 (`533e7e47`). Both slices found real defects nearby instead -
a stale docstring set, and a `hide-on-data-absence` reflow bug in the shipped grid.

**TWO PROCESS CATCHES WORTH KEEPING.** (1) I nearly shipped a one-line `game_id=`
kwarg "fix" on a subagent's framing; checking the source first showed
`coaches/aram_coach.py:599` hardcodes `""` and the Live Client never surfaces one, so
it would have been a no-op reported as a fix. (2) A slice flagged "Golden Spatula in
Miss Fortune's SR order" - wrong twice. `3600` is Kalista's Black Spear, SR carries
zero, and the real number is **`224403` in 82 of 173 ARENA orders**. Verify subagent
specifics, not just their direction.

**Carry-forward hazard:** `ROADMAP.md` blew its 80KB budget during the docs pass and
is back at 81905 bytes with **15 bytes of headroom**. The next session that touches it
must prune to `docs/ROADMAP_HISTORY.md` FIRST.

---

# 2026-07-24b - R190 kit-intrinsic penetration lane (ENGINE 1.241.0, commit `349d833a`)

gemini-loop DIRECTOR REFILL, rotation source 1 (DS sweep). Tier-2: new engine
module + a narrow `effects.py` signature extension + ENGINE bump + Share re-sync
+ DS `:8893` bounce. LEDGER 1040. ZERO API / ZERO LLM.

**The stated scope was already closed; the real gap was next to it.** R152 /
R153 / R160 / R161 had already swept every ITEM-side penetration magnitude, and
`effective_target_armor` / `effective_target_mr` already implement League's
two-rule split correctly. What was missing is a SOURCE: both pipelines accept
`ItemEffect` objects only, so CHAMPION-KIT penetration never entered the damage
math - it lived solely as a row in the standalone opt-in anti-tank RANKING axis,
which feeds no resist computation.

NEW `agents/daemon_slayer/_kit_penetration.py`, DEFAULT-OFF: Darius E 40 pct,
Gangplank E 40 pct, Nilah Q 33 pct, Ambessa R 30 pct, Pantheon R 30 pct, each
row carrying its verbatim `champion_abilities.json` tooltip.
`effective_target_armor` gains `kit_pen_pct` / `kit_pen_flat` appended at the
END with 0.0 defaults; the kit fraction joins the SAME `_composed_keep_factor`
product as item percent pen so they can never sum. Zero production call sites
pass either argument - the live flip stays operator-gated.

Magic side is a REFUTE made machine-enforced: 14 kit-intrinsic magic-side
grants, 13 already credited, the lone hole Annie R (15/17.5/20 pct, absent from
the anti-tank registry entirely) now pinned as known-uncredited.

**Carry-forward for the next engine bump.** The DS dir went green at 9290 while
the RC suite was still RED in three classes a DS-only gate cannot see: the HZ-B
build-order tables are patch-keyed STATIC data and need BOTH generators re-run
(`core.build_order_precompute` AND `core.build_order_variants`,
`--static --mode all --champions all` - variants alone leaves the precompute set
stale), `docs/DAEMON_SLAYER.md` pins ENGINE + test count in its status line, and
`Share/README.md`'s release-history list must NAME the live engine version.

DS 9290 passed / 1 skipped / 4331 subtests. RC `tests/` 12769 passed / 22
skipped / 406 subtests. ruff clean. `ds_share_sync --check` in sync (466 files).
DS `:8893` re-probed live at 1.241.0 / patch 16.14.1.
