# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-25c - 5 rows named, 3 dissolved, 4 seams shipped (ENGINE 1.247.0)

ENGINE **1.247.0**, patch 16.14.1, DS **9546 passed / 1 skipped / 4547 subtests**,
RC `tests/` **13061 passed / 106 skipped / 448 subtests / 0 failed** (fresh re-run
after the mirror fix). DS `:8893` bounced and `/health` re-read as 1.247.0 BEFORE any
regen. All 9 build-order tables regenerated across BOTH keyspaces and corroborated
STAMP-ONLY by a stamp-stripped payload diff, not by the generator's silent exit 0.
Share mirror 479 files. Full narrative: `docs/LEDGER.md` 1046 + DS CHANGELOG 1.247.0
+ `docs/OPEN_ITEMS_REVIEW_2026-07-25.md` PART 6.

## What shipped (all DEFAULT-OFF, all byte-identical OFF)

- **A-18 / RM-87** resist-to-damage coupling in `ds.ehp`. NEW
  `agents/daemon_slayer/_resist_damage_coupling.py`, 6 machine-swept rows, SORT-ONLY
  credit in `_base_key`. Ornn Thornmail #16 -> #11, Kaenic #6 -> #3, Warmog's #2 -> #7.
  Poppy negative control byte-identical ON.
- **A-31 / R67** Terminus SR `3302` Light-side resists, 18 / 21 / 24 at L1 / L11 / L14.
  Arena `223302` REFUSED - no on-disk feed carries its magnitude.
- **A-08 / RM-35 clause 2** `exclude_off_axis_items` extended to the CARRY route.
- **A-39** boot-utility CC input replaces the AP-share proxy.

## The headline: the mis-file rate did not fall, and the reason changed

Three of the five rows the prompt named dissolved under probe (A-27 and A-30 already
shipped, A-11 unfalsifiable), so two replacements were pulled. **9 mis-files caught
before code across three sessions.** These were not bad research - they were STALE
research: A-27 was closed 1 day before the row was written, A-30 thirteen days before,
and A-31's "needs a schema lift" blocker had been false for eight. A tier records how
well a row was probed, never how recently.

## Two traps that bit again

- The `item_ids=[]` artifact manufactured its FOURTH false headline (A-08's "BotRK #1
  for Miss Fortune"; at real depth the leads are Runaan's / LDR / Terminus).
- A slice reported "+1 line in `ehp.py`" and the 3-line anchor matched TWICE in the
  file. Merging by file copy would have been wrong either way - the fix was to confirm
  only one real `item_resist_grants` call site exists before applying it.

---

# 2026-07-25 - five open-item rows probed, three built, three mis-filed (ENGINE 1.245.0)

HEAD after this session: see `git log -1`. ENGINE **1.245.0**, patch 16.14.1,
DS **9446** / `tests/` **12987**, DS `:8893` bounced and verified serving 1.245.0
BEFORE any regen. Full narrative: `docs/LEDGER.md` 1044.

## What shipped

- **A-04 / RM-99b Heartsteel cadence, SR ON / Arena OFF** (operator call). SR 3084
  corrected to the real 30s per-target gate directly in `_effects_data.py`; Arena
  223084 held at 3.5 because 30s is unsourced on its own feed. Filed 8.5714x was
  EXACT. The over-credit was supplying **13-32 pct of total credited auto DPS** on
  shipped bruiser builds. SR occurrences 135 -> 6, ARAM 156 -> 27.
- **A-29 / R129 Viego R** surplus-block MERGE, DEFAULT-OFF `apply_cdragon_surplus_ad`.
  0.000 -> 1.169 DPS. Population is **1 champion, not 6**.
- **A-01d seam forwarding.** `/api/ds-preview` reached zero of nine seams; and the
  `with_build_order` branch RANKED with `prefer_kit_axis_by_win` ON and PLANNED with
  it OFF. Both sides now pinned to agree.
- **A-40(1): the first Family A staleness guard** - which immediately caught a live
  bug (below). The row's "OPEN DESIGN Q" was stale; already answered in LEAP-04.
- **Arena mirror-id dock gap, DEFAULT-ON.** `kit_synergy.py` matched spellblade items
  by SR id only, so the carry coherence dock was **inert in Arena**: Essence Reaver's
  mirror 223508 sat at slot 1 for 6 carries. 18 -> 0.

## Three things that would have shipped wrong

1. **Three of five rows were mis-filed, in two recurring classes.** A row whose answer
   already existed on disk (A-40's design Q, answered in LEAP-04 with
   `UNVERIFIED-SKIP count: 0`), and a row describing INTENDED behavior as a bug
   (A-24 / RM-93 - the deny is deliberate and test-pinned, and the "modelled damage
   formulas" the row cites as evidence are the REASON for it). Both closed with no
   code. **Probe the row before building it.**
2. **The A-04 fix invalidated its own test.** The magnitude test anchored on Aatrox's
   shipped SR build and asserted Heartsteel was in it - then the fix evicted Heartsteel
   from that build (Aatrox now takes Randuin's 3143). The guard fired correctly; the
   anchor was self-defeating. Never anchor a measurement on the engine still
   recommending the thing you are about to demote.
3. **The ENGINE literal count read 1442, not ~372.** The excess was five live agent
   worktrees, each a full repo copy. A blind repo-wide replace would have rewritten
   `ENGINE_VERSION` inside all of them. Real count excluding `.claude` is 241.

## Standing hazards for the next session

- **Keyspace 2 was MORE stale than keyspace 1** (195 vs 135 Heartsteel occurrences),
  vindicating LEDGER 1043's doctrine one session later. A regen is not done until all
  three families across BOTH keyspaces have run.
- **Share sync must run AFTER the CHANGELOG entry**, not before. It ran twice this
  session because of that ordering; the determinism test caught it.
- **`3131` Sword of the Divine is a NEW open residual:** `every_n_seconds=15.0` against
  a 90s active cooldown in its own DDragon text, uncited 6x over-credit, absent from
  Meraki. Same operator-gated class as A-04. Not yet filed to a row.
- **Zeri's Arena cell is flagged, not accepted:** the dock fix changes 4 of 6 slots and
  trades the ER artifact for Liandry's + Dusk and Dawn, which is the AP-on-AD-marksman
  class `coherence.py:138-139` already defers. The eviction is right; the replacement
  is not clearly better.
- CLAUDE.md's **"20,190 tests" is stale** against the measured `tests/` count (12987).

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
