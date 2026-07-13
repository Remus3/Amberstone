# DS Build-Reco + In-Game Overlay QA (2026-07-13)

Read-only 3-front QA of the Daemon Slayer build recommendation + the in-game
overlay item-choice display. Triggered by an operator observation: an effective
Twitch crit build was never offered, and DS offers Essence Reaver / Eclipse on
crit ADCs that no one builds. All findings are code-traced or live-API-probed;
file:line cites are from the audit agents.

## Goal (operator, 2026-07-13)

The overlay shows the operator's NEXT item toward the game's OPTIMAL ULTIMATE
build, computed to counter the live ENEMY comp + their items and synergize with
ALLY comp, re-evaluated as the game progresses - and it NEVER offers an item the
champion / archetype would never build. Personal win-rate with an item is
IRRELEVANT to the optimal build.

## Findings

### A. Anchor is already correct; the win-rate seams are the wrong direction

- The live build reco is anchored to PURE SIMULATION (`sort_by="delta"`,
  archetype scorers), NOT win-rate. Trace: `dashboard/routes_state.py:612-619`
  (ds-preview) + `:963-971` (build-order) -> `plan_build_order`
  (`core/build_order.py:473`) -> `rank_items` (`agents/daemon_slayer/rank.py`
  scores by `compute_dps` delta only). This ALIGNS with the operator's
  optimal-build goal (confirms memory `reference_ds_simulation_default_not_winrate_hybrid`).
- EVERY win-rate / rewind seam is DEFAULT-OFF and UNWIRED in live serving:
  `exempt_offclass_by_win` (DSP2), `prefer_kit_axis_by_win` (DSP11),
  `prefer_survivability_by_win` (RF1/2/3), `cost_ceiling` (F2). No non-test,
  non-audit path passes any of them True (`core/daemon_slayer_client.py:1198,1286`;
  `agents/daemon_slayer/server.py` body-parsed default False).
- The DSP11 kit-axis table (`agents/daemon_slayer/kit_axis_item_credit.json`)
  itself REINFORCES personal-rewind artifacts: sub-50%-WR rows (Corki x3,
  Naafiri x2), a negative-lift row (Ezreal Trinity), thin n=16-20 noise rows
  (Ezreal Essence Reaver n=16, Nilah Shieldbow n=20). Nilah's entry is INERT
  (routes through the hybrid scorer, which has no such param).
- VERDICT: flipping the kit-axis seam ("#3") would bake in exactly the
  personal-win-rate basis the operator rejects. It is a band-aid over the real
  defect. DO NOT flip it. `core/build_planner/kit_synergy.py` already exists as
  the intended metric-based lever.

### B. The real defect: the sim produces incoherent AD builds (systemic)

- Roster probe (19 champs x 2 modes) vs the 30,562-row `data/rewind_history.db`:
  Essence Reaver (3508) is offered to 10/19 champs at a 0-1.9% playerbase build
  rate; Eclipse (6692) on 3 crit ADCs (0-0.4%); Runaan's / BORK on champs that
  never build them (Jhin, Rengar, Camille).
- 58% of sampled champs get >=1 cross-archetype artifact in their top-6. The
  problem is CONCENTRATED on AD carry / crit / on-hit champs; the AP-mage,
  enchanter and tank scorers come out CLEAN - the fault is in the AD
  sustained-DPS path.
- Root cause (two layers):
  1. Full-catalog candidate pool with the ONLY filter being
     `filter_shared_uniques` (`core/daemon_slayer_client.py:959`,
     `core/build_order.py:611`) - NO archetype-coherence gate, NO real-build prior.
  2. Greedy per-slot argmax over single-item `delta_dps`
     (`core/build_order.py:597,661,681`; scorer `agents/daemon_slayer/hybrid.py:737,1065`).
     Essence Reaver's AD+crit and Eclipse's AD+lethality feed the DPS formula
     with no coherence penalty, so any high-DPS-per-gold AD stat-stick surfaces
     for a crit ADC the playerbase never itemizes that way.
- SEPARATE HYGIENE FLAG: stale catalog - Stormrazor (3097) is still offered
  (Jinx/Ashe/Zeri) but has only 6 appearances in 30k rows (reworked/removed
  era). Needs a live item-catalog staleness check vs Meraki.

### C. Overlay comp-awareness is half-real; a rich engine is built-but-dormant

- Display (`web/js/panels/active_match.js:563-724`): three rows (Daemon Slayer
  adaptive / Meta / Ultimate), per-item `+Ndps` badge, NEXT pip, next/swap/partial
  state badge, a "vs N armor / M mr / K hp" caption, a threat-mix donut.
  Reasoning is QUANTITATIVE ONLY - no natural-language "why item X over Y."
- Comp-awareness, AXIS 1 (target armor/MR/HP -> EHP/pen math): REAL + LIVE. The
  server reads live ENEMY owned items itself (`core/enemy_aware_stats.py:295-306`
  reads `allPlayers[].items`) and derives target stats
  (`dashboard/routes_state.py:800-829`), so the ranking DOES shift as enemies buy
  armor/MR. Dynamic within ~4-8s (`active_match.js:575-585`).
- Comp-awareness, AXIS 2 (rich counter-build: ad/ap split, antiheal, tenacity
  vs CC, kill-target pen TYPE, fed override): BUILT BUT DORMANT. Lives in
  `core/build_planner/situational.py` + `replan.py`, reached only via
  `/api/build-plan` -> `_resolve_enemy_profile(enemies,...)`
  (`routes_build_plan.py:394-408`). The overlay never sends `enemies`, so
  `enemy_profile=None` -> the situational term is forced to 0.0
  (`replan.py:501-502`) -> DPS-only. Doubly stubbed: even if `enemies` were
  passed, `build_enemy_profile` is fed no enemy items so kill-target pen-type is
  dead. The whole ReplanLoop swap/pivot is vestigial live (contributes only a
  state pip).
- ALLY synergy: ABSENT. `AllyState` (`situational.py:138`) is never populated.
  `kit_synergy.py` is operator-kit-vs-item fit, not ally-team.

## Re-orientation proposal (prioritized)

1. FIX THE SIM COHERENCE (root cause, highest value). Make the AD/carry path
   produce archetype-coherent builds so Essence Reaver/Eclipse/off-class
   stat-sticks stop surfacing on crit ADCs. Candidate mechanisms: an
   archetype-coherence weight in the scorer, an archetype-restricted candidate
   pool per champ, or wiring the existing `core/build_planner/kit_synergy.py`.
   Metric-based, not win-rate. Validated per-champion (per the DS methodology),
   AD path only (mages/tanks/enchanters are clean - do not touch).
2. WIRE OR PRUNE the dormant situational counter-build (Axis 2). Either thread
   live `enemies` + enemy items into the overlay's build path so antiheal /
   tenacity / pen-type / fed-override actually fire, OR prune situational.py +
   replan.py swap/pivot + AllyState as vestigial. Operator decides.
3. ALLY-COMP SYNERGY: build (new) or drop from the goal.
4. NL REASONING: add a short "why X" line to the overlay ("+Ndps, shreds their
   armor stack") or accept the quantitative-only badges.
5. HYGIENE: live item-catalog staleness check (Stormrazor 3097); decide the fate
   of the kit-axis / offclass-exempt win-rate tables (leave dormant vs delete,
   since they are off + wrong-basis).

## Do NOT

- Do NOT flip `prefer_kit_axis_by_win` live (confirmed wrong basis).
- Do NOT add a personal-rewind Twitch entry (paused; personal win-rate is not
  the anchor).
- Do NOT touch the mage/tank/enchanter scorers (clean).

## Open decisions (operator)

- Priority 1 mechanism: coherence-weight vs restricted-pool vs kit_synergy.
- Axis 2: wire the situational counter-build into the overlay, or prune it?
- Ally synergy + NL reasoning: in scope or out?
