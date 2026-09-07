# DS Build-Coherence Refactor - Plan (Steps 0-1)

Grounded against code by two read-only Plan agents (2026-07-13). Motivating QA:
`ops/audit/DS_BUILD_RECO_OVERLAY_QA.md`. Goal: the overlay shows the NEXT item
toward the OPTIMAL ULTIMATE build (metric-based sim, comp-aware, dynamic), never
an item the archetype never builds. Personal win-rate is NOT the anchor.

## Two load-bearing reframes (verify-first corrections)

1. DSP11 is NOT dead code - it is LIVE-ON in the COACH path. The QA missed
   `coach_integration/archetype_dispatch.py:215`, where the C4 flip (2026-07-04,
   commit 523206d6, LEDGER 776/778) set `prefer_kit_axis_by_win=True`. All four
   coaches call `dispatch_for_coach` without overriding it (SR `_coach.py:314`,
   ARAM `aram_coach.py:784`, Arena `arena_coach.py:676`, Brawl `brawl_coach.py:401`).
   So DSP11 IS live in the coach LLM-picks path (picks_str + display_rows), just
   NOT in the overlay (ds-preview / build-order / build-plan are pure-sim).
   => Pruning DSP11 = REVERTING a live, operator-validated coach behavior for 6
   tabled champs (Nilah inert). This must be operator-confirmed + coach-eyeball
   gated, not a silent delete. The other 3 seams (DSP2, F2, RF1/2/3) ARE
   genuinely unwired live (byte-identical deletion).

2. The Step 1 coherence fix is CORE-side, effectively TIER-1 (not Tier-2). The
   recommended mechanism lives in `core/build_planner/kit_synergy.py` +
   `core/daemon_slayer_client.py` (the dashboard process), NOT the :8893 engine.
   So NO ENGINE_VERSION bump, NO Share mirror, NO :8893 restart - it takes effect
   on a dashboard reload. Only backfill: regenerate the precomputed build_order
   tables (they call `plan_build_order` -> the core chokepoint).

## Step 0: prune + decide

### 0a. Byte-identical hygiene prune (DSP2 + F2 + RF1/2/3) - safe, zero behavior change
All three confirmed unwired live (only tests + `ops/audit/ds_perm_swarm/*` pass
them True; `archetype_dispatch.py:214/216/217` default them off/None).
- DSP2 `exempt_offclass_by_win`: drop the inline loader `rank.py:345-390`, param
  `:828`, usage `:1024-1027`; DELETE `marksman_offclass_exempt.json` + Share twin
  + builder `ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py`; client
  `daemon_slayer_client.py:136,192-193,998,1286`; `server.py:448,452,481`.
- F2 `cost_ceiling` + RF1/2/3 `prefer_survivability_by_win`: larger cross-scorer
  surface (F2 spans rank/ehp/hybrid; RF lives in the tank/enchanter/bruiser
  scorers the operator said do-not-TOUCH - removal is byte-identical plumbing but
  edits protected files). RECOMMEND a separate clearly-scoped hygiene slice, or
  leave dormant. Not required for Step 1.
- The base deny-set `OFFCLASS_MARKSMAN_ITEM_NAMES` (`rank.py:1019`) STAYS (it is
  the default off-class stripping, not a seam).
- Tests deleted with the seams (else TypeError reds): `test_rank_offclass_win_exempt.py`,
  (F2/RF) `test_cost_aware_top_f2.py`, `test_survivability_item_credit_rf{1,2,3,6}.py`;
  EDIT the multi-seam `test_rank_route_seam_passthrough.py`,
  `test_archetype_dispatch_seam.py`, `test_daemon_slayer_client_seam_forward.py`.
- Tier: mechanically Tier-2 (Share + :8893 restart) but byte-identical output.

### 0b. DSP11 revert (kit-axis) - RESOLVED 2026-07-13: DO NOT REVERT (see Status)
The gate ran (`ops/audit/ds_perm_swarm/report/dsp11_gate_diff.md`) and REFUTED the
premise below. The mechanism stays; the DATA table was refreshed instead. Original
plan (kept for context):

~~Do this AFTER Step 1 (the metric coherence fix covers the crit core in the coach
path too - the same `rank_for_primary_archetype` chokepoint - so removing DSP11
leaves NO coverage gap for the 6 champs; it removes a redundant, wrong-basis,
rewind-artifact-laden hack).~~ **FALSE for lethality/assassin/manamune champs** -
Step 1a fixes CRIT-ADC coherence only; it does not surface Pyke's lethality core /
Naafiri's Hubris / Corki's Collector. The coach-fidelity gate diff
(`dispatch_for_coach` top-5, real comps, independent rewind cross-ref) shows DSP11
OFF DROPS those, and rewind justifies keeping them (Pyke Axiom/Youmuu's/Opp all
above baseline, big N). A blind revert would be a live regression. Gate: an offline
coach-picks OFF-vs-current diff for the 6 champs + operator sign-off (mirrors the
original C4 flip on the LIVE_GAME_GATED_SYNC track). Deletion surface (engine +
Share twins + client + `archetype_dispatch.py:215,278-279` + `kit_axis_credit.py` +
`.json` + builder + `test_kit_axis_item_credit_dsp11.py` + the obsolete
`test_twitch_crit_kit_axis.py`).

### situational counter-build => WIRE (keep), do NOT prune
`situational.py` + `replan.py` are load-bearing on the live build-plan path
(`replan.py:54` imports `classify_item` at module load; ReplanLoop.tick runs it).
Dormant only because the overlay sends no `enemies`. Wiring surface (Step 2):
`active_match.js:226-231` add enemies + enemy item-ids to the POST;
`routes_build_plan.py:299,314,394-405` forward `enemy_items` into
`build_enemy_profile`. Only C1/C4/C5 (resist/HP/pen-type) fire from live data;
C2 antiheal / C3 fed / C6 tenacity have no live source yet. `AllyState`
(`situational.py:137`) is the only genuinely-dead piece - keep dormant unless
ally synergy is formally cut.

### Obsolete test => DELETE `agents/daemon_slayer/tests/test_twitch_crit_kit_axis.py`
Tests the abandoned kit-axis direction; will TypeError once DSP11's param is
removed. The correct inverse (assert ER 3508 + Eclipse 6692 NOT in Twitch top-6)
ships WITH Step 1, not here.

## Step 1: fix sim coherence (the payload) - core-side, Tier-1 live

### Root cause (confirmed, empirical)
The AD/carry path scores by pure `delta_dps` (`rank.py:1081`) over the full
catalog with no coherence term. Essence Reaver (3508) floats to #1-4 for crit
ADCs: its Spellblade proc is modeled at `every_n_seconds=3.0`
(`_effects_data.py:730-738`), an ability-cast tempo a pure auto-attacker lacks
(over-credited), and its 20 AH + mana are DPS-invisible but unpenalized. Eclipse
(6692) rides flat AD + lethality + a 6% max-HP proc. The greedy per-slot argmax
(`build_order.py:597,661,681`) then buries the crit AMPLIFIERS (IE 3031 at rank
6-9) because they pay proportional to accumulated crit a stat-stick-first build
never accrues.

### kit_synergy.py: the metric lever, but it needs a refinement (load-bearing)
`core/build_planner/kit_synergy.py` computes a per-champion, metric-based (from
`champions.json` via `derive_kit_weights`, NOT win-rate) item-vs-kit fit. BUT in
its current tuning it ranks Essence Reaver #1 for crit ADCs - its effect-flag
bonuses (spellblade +0.2, bonusAD-match +0.4, on-hit vector credit) reward
proc-heavy stat-sticks over flag-less pure-stat cores (IE gets zero bonus). A
naive blend would REINFORCE the bug. REQUIRED refinement: ability-charged
Spellblade items (`_SPELLBLADE_IDS`, kit_synergy.py:89) must NOT get per-auto
on-hit / bonusAD credit for a non-spellblade-user kit
(`champ_kit_traits(champ)["spellblade_user"]` already derived, kit_synergy.py:367-373).
With that, ER's stat-only fit ranks below IE; Eclipse is already clean.

### Mechanism: soft coherence re-rank at the carry chokepoint
Insert at `core/daemon_slayer_client.py` `rank_for_primary_archetype`, the carry
fall-through (~:1293-1302, beside the existing `CARRY_RANGED_OFFCLASS` post-rank
filter - the established precedent). Request a wider window (top~40) so the buried
crit core is present, then re-score each row:
`adj = delta_dps - MU*wasted_stat_penalty(item,champ) + W*stat_fit(item,champ)`
(both from kit_synergy primitives, DPS-equivalent + delta-dominated so clean
builds barely move), re-sort, truncate to the caller's top. NOT a hand-blacklist
(the name deny-sets must not grow); a continuous metric dock.

Clean scorers stay byte-identical BY CONTROL FLOW: the re-rank lives only in the
carry branch; tank/bruiser/mage/assassin/enchanter branches `return` before it.
Lux/Ornn/Soraka never execute it - no seam flag needed.

### TDD (per-champion, server-free)
- RED `tests/test_carry_coherence_rerank.py`: champs Twitch/Jinx/Caitlyn/Ashe,
  ARAM + SR cells. Assert 3508 + 6692 NOT in top-6; assert 3031 IN top-6 + >=1 of
  {6676,3032,6673}; control (coherence OFF) asserts >=1 of {3508,6692} IS in top-6.
- Byte-identical control: Lux (mage) + Ornn (tank) top-8 pinned unchanged.
- kit_synergy refinement test: `synergy_score(IE,Jinx) > synergy_score(ER,Jinx)`
  and `> synergy_score(Eclipse,Jinx)`; existing AP/AD profile orderings unchanged.
- Integration: `plan_build_order("Jinx","carry",...)` order surfaces IE/crit core,
  excludes ER/Eclipse.

### Tier + backfill
Core-side = Tier-1 live (no ENGINE bump / Share / :8893 restart). REGENERATE the
precompute tables `data/daemon_slayer/build_orders/<patch>/` (via
`core.build_order_precompute`, which routes through the fixed chokepoint). Verify
whether `tools/daemon_slayer_build_orders_generate.py` bypasses the core client
(POSTs raw to :8893); if so it needs an engine variant or a re-route.
Per-champion validation habit: siblings Camille (bruiser) + Rengar (assassin) are
follow-up slices; do NOT touch mage/tank/enchanter (clean).

## Refined execution order

1. STEP 1 coherence fix (payload, core-side Tier-1, low-risk) - fixes artifacts
   across BOTH the overlay and the coach path. TDD-first.
2. STEP 0a byte-identical hygiene prune (DSP2; F2/RF optional/deferred).
3. STEP 0b DSP11 revert (now redundant after Step 1; coach-eyeball gated).
4. STEP 2 wire the situational counter-build (enemies + items into the overlay).
5. STEP 3 ally synergy + NL reasoning + catalog hygiene (Stormrazor 3097).

## Status (2026-07-13)

- STEP 2 SHIPPED (partial) = the dormant situational counter-build is WIRED to
  the live overlay (2026-07-13, R102, main `6059882e`/`4ae67f25`/`4707b47e`). NEW
  pure `counter_build_hints()` (situational.py) surfaces the C1-C7 criteria an
  EnemyProfile warrants as structured hints; `/api/build-plan` gained a fail-soft
  `counter_hints[]` payload key (always present); `active_match.js` now SENDS
  `enemies` so `build_enemy_profile` fires live + renders a COUNTER chip row
  (honest no-data hide; ok=solid-green / gap=dashed-cyan / high=2px, WCAG 1.4.1).
  The previously-dormant enemy-profile builder is now on the live overlay path -
  the `situational.py` "genuinely-dead piece" note above is SUPERSEDED. 14 backend
  tests + snapshot green, 5-phase UI audit NO-MUST-FIX. FOLLOW-UP (FUTURE): the
  overlay sends enemy CHAMPIONS only, not enemy ITEMS, so C1 resist-split + the
  champ-derived hints fire live now, but the enemy-items enrichment that feeds
  kill_target_armor/mr (C5 pen-type) + enemy_pen (C4 hp-vs-pen) is not yet plumbed
  through the fetch; each extra criterion lights up automatically once it is.
- STEP 0b RESOLVED = DO-NOT-REVERT + kit-axis table refreshed (2026-07-13). The
  operator-gated coach-picks diff ran at true coach fidelity (`dispatch_for_coach`
  top-5, frontline/squishy comps SR L14 + ARAM L16, independent rewind_history.db
  re-query) - report `ops/audit/ds_perm_swarm/report/dsp11_gate_diff.md`. Finding:
  DSP11 is LOAD-BEARING (not redundant) - it surfaces Pyke's Axiom Arc #1 +
  Youmuu's #2, Naafiri's Hubris/Collector, Corki's Collector, none of which Step 1a
  (crit-only) covers; a blind revert = live regression. BUT the tightened rewind
  cross-ref exposed 2 anti-justified table entries the baked report hid: Ezreal
  Essence Reaver (table 56.2%/n16 -> fresh 40.9%/n22) and Naafiri Hubris/Collector
  (at/below her 45.9% baseline). ACTION: keep the mechanism, refresh the DATA table.
  `build_kit_axis_item_credit.py` gained a fresh-DB re-validation gate (buried-winner
  floats must clear the current all-mode baseline; off-class un-strip staples keep
  within a band); rebuilt table drops Ezreal ER + Naafiri entirely + Corki Muramana
  / Quinn Collector+Mortal (all live-inert below-baseline), keeps Pyke/Corki-Collector
  /Nilah/Senna + Ezreal Trinity. Data-only Tier-2 (no ENGINE bump - engine default-OFF
  is byte-identical; Share sync + :8893 restart). DS suite 8404 + dispatch consumers
  106 green. The DSP11 mechanism DELETION (original 0b) is CANCELLED.
- STEP 1a SHIPPED (core-side Tier-1, main 77f56d70): the coherence re-rank +
  kit_synergy spellblade refinement + derive_kit_weights marksman-precedence fix.
  NEW `core/build_planner/coherence.py`. Deleted the obsolete
  `test_twitch_crit_kit_axis.py`. PROTECTED byte-identical: Ezreal, Corki
  (caster-marksmen, Marksman+Mage tag - excluded from the dock after
  verification caught a v1 regression that stripped their legit Essence Reaver
  core).
- LIVE-VERIFIED REALITY (post-restart ds-preview, the overlay's actual reco row -
  supersedes the in-process test claims):
  - WIN: Essence Reaver (3508) + Eclipse (6692) are REMOVED for the crit ADCs
    (Twitch/Jinx/Caitlyn live-confirmed no ER, no Eclipse). The operator's core
    complaint (ER on Twitch) is fixed live. No regressions.
  - PARTIAL / CORRECTION: the crit core (Infinity Edge) does NOT reliably lead
    live - Twitch/Caitlyn show a pure on-hit build (BORK/Runaan/Kraken/Terminus/
    LDR), IE absent; only Jinx surfaces IE (#5). The earlier "IE in top-6" claim
    was from a single in-process test cell (target_armor=60) that does NOT match
    the live ds-preview path (different target-stat resolution + filtering), so
    the tests passed while live is more mixed. The greedy-crit-blindness the QA
    identified is NOT fully resolved by the soft re-rank.
  - VERIFICATION-FIDELITY GAP (owed): the tests exercise `rank_items` +
    `coherence_rerank` at a fixed cell, NOT the live `rank_for_primary_archetype`
    / ds-preview path. Tighten the tests to the live path + the live default
    target resolution before claiming a champ "fixed".
  - RESIDUAL artifacts live: AP-on-AD (Liandry's on Jinx) - distinct class;
    Ezreal keeps ER + Eclipse (caster-marksman exclusion also spares his Eclipse).
- KNOWN GAPS (next widening, per "narrow first, widen on evidence"):
  - RESOLVED 2026-07-13 (Step 1b, this slice): the Mage-tag gate no longer
    OVER-EXCLUDES dual-tagged non-caster marksmen. is_caster_marksman
    (champ_kit_data.py) now gates the Marksman+Mage tag on an ability-AP-scaling
    floor (_ability_agg "ap" >= 2.0): genuine hybrid casters Ezreal 4.25 /
    Corki 2.50 / Smolder 2.55 stay exempt; crit / on-hit ADCs Jhin 1.60 /
    Kai'Sa 1.40 / Varus 1.25 / Miss Fortune 1.20 flip to DOCKED, so their
    Essence Reaver (+ Eclipse where present) artifact is removed. Live-verified
    via ds-preview. Core-side Tier-1 (no ENGINE bump / Share / :8893 restart);
    RC dashboard reload. Tests: tests/test_champ_kit_data.py::CasterMarksmanGate
    + tests/test_carry_coherence_rerank.py::...::test_mage_tagged_crit_adcs_now_docked.
  - Zeri surfaces Lich Bane / Liandry's (a DISTINCT AP-on-AD-marksman artifact
    class this fix does not target).
  - KogMaw untouched (arch=mage -> the non-carry early-return); Azir / Twisted
    Fate likewise arch=mage (exempt via the early-return regardless of the gate).
- BACKFILL OWED: regenerate the precompute build_order tables
  (`data/daemon_slayer/build_orders/<patch>/`) - they read plan_build_order. The
  LIVE overlay + coach are UNAFFECTED (they compute live through the fixed
  chokepoint); only the HZ-shadow / display-keyed precompute consumers are stale.

## Open decisions (operator)
- Confirm the refined order (Step 1 before the DSP11 revert).
- Step 1 Tier: core-side (recommended, Tier-1) vs an in-engine seam (Tier-2).
- F2/RF hygiene: fold in, separate slice, or leave dormant.
