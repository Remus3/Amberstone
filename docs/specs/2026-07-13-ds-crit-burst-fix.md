# DS Crit-Burst Fix - Coordinated Spec (surface the crit-burst core for crit ADCs)

Grounded against code + in-process sims + the live API by the a4362a investigation
(2026-07-13). Follows Step 1a (the coherence artifact-removal, main 77f56d70,
`docs/specs/2026-07-13-ds-build-coherence-refactor.md`). This is the DEEPER fix:
the sustained-DPS scorer systematically hands crit ADCs an ON-HIT build.

## Goal
Crit ADCs (Twitch, Caitlyn, Jinx, Draven, Samira, Miss Fortune, ...) surface
their crit-burst core (Infinity Edge 3031, The Collector 6676, Yun Tal 3032) over
on-hit stat-sticks. METRIC-based (kit + item stats + fight-timing), NOT win-rate,
NOT a name blacklist. Clean scorers (mage/tank/enchanter) + genuine on-hit champs
(Vayne) stay correct.

## Root cause (verified, evidence-backed)
The carry scorer `compute_dps` optimizes SUSTAINED DPS integrated over a LONG
fight vs a TANKY target. Crit ADCs' real value is SHORT-TTK BURST (crit one-shots
+ execute + Runaan-AoE-through-ult pentas) vs SQUISHY carries, amplified when FED.
Operator evidence: the crit build (Collector/IE/Yun Tal/Runaan/BT) got 3 pentas +
2 quadras in one game; the on-hit build did not. Caitlyn/Jinx are crit-burst-AS
champs by design. Investigation confirmed the on-hit lean is SYSTEMATIC: 7/7 crit
ADCs lead BORK+Runaan+Kraken; Collector absent 7/7; IE absent/buried 6/7; Vayne
(real on-hit) served correctly -> one on-hit-optimal answer applied to every AD
carry, kit-blind.

## Three structural obstacles (why fight_length alone is a no-op)
1. `coherence_rerank` (Step 1a, `core/build_planner/coherence.py:61`) sorts by
   raw `delta_dps` and NEVER reads `effective_score`, so in the live chokepoint
   (`core/daemon_slayer_client.py:1293-1322`) it re-sorts the top-40 by sustained
   DPS and NEUTRALIZES `fight_length`. Proven byte-identical across FL. => the
   coherence re-rank must respect the burst score.
2. The Collector execute (5% max-HP true) is gated on `assume_takedown`
   (`agents/daemon_slayer/burst.py:1051`), and `_safe_burst` (`rank.py:759-770`)
   calls the burst with `assume_takedown=False`, so Collector NEVER surfaces
   through the burst term regardless of fight_length.
3. BORK (3153) stays #1 even under short fight_length - its 12% current-HP on-hit
   is front-loaded (full value on the first auto). Only a SQUISHY target demotes
   it: the live target resolves to the tanky mode-curve average (armor 158 / HP
   3260, `dashboard/routes_state.py:762-855`), which inflates on-hit %HP +
   armor-pen. The operator deletes squishy carries, not the tank.

## Levers (sequenced; L1 before L3 is mandatory)

### L1 - coherence_rerank respects the burst score (core-side, PREREQUISITE)
`core/build_planner/coherence.py`: when `fight_length` is engaged for the champ,
sort the re-rank by a burst-inclusive score (respect `effective_score`), not raw
`delta_dps`. Options: (a) accept the engine rows' `effective` field and re-rank on
it; (b) fold a burst term into `_coherence_adj`. Keep the artifact dock + the
caster-marksman exclusion. RED test: with fight_length engaged, coherence_rerank
output is NOT byte-identical across FL (the current bug), and IE rises. Tier-1
core-side.

### L2 - arm the execute in the burst term (engine-side, Tier-2)
`agents/daemon_slayer/rank.py` `_safe_burst`: pass `assume_takedown=True` to
`compute_burst_damage` so the execute + kill-state credit (Collector 6676, Hubris)
enters the burst term. Verify non-crit-ADC burst outputs are unaffected or
justified. ENGINE_VERSION bump (1.207.0 -> 1.208.0), Share mirror, :8893 restart
(LEDGER-872 ritual). RED test: Collector enters a crit ADC's burst-weighted top-N.

### L3 - fight_length allow-map for crit ADCs (core-side)
`core/ds_champion_fight_length.py`: add the crit ADCs at FL ~0.5-0.75 (Jhin pilot
= 0.5). Sweep per champ (investigation: IE surfaces at FL>=0.3; >=1.5 the
sustained term re-dominates; Draven/Samira tolerate 0.3). Overrides the documented
"these are sustained crit" exclusion (operator's penta evidence). Per-champion
validated (the repo habit). Tier-1 core-side (but gated on L1 to take live effect).

### L4 - squishy-target scenario (core-side)
`dashboard/routes_state.py:762-855` `_resolve_ds_target_stats`: the mode-curve
target is tanky. Add a squishy-carry target scenario (lower armor/HP, the carry
the operator deletes) OR blend toward it, so BORK's front-loaded %HP stops
dominating and crit-burst wins. Also consider `target_current_hp_pct < 1.0` for
the execute window (currently always 1.0, `rank.py:831`). Tier-1 core-side.

### L5 - fed-conditional fight_length (FOLLOW-UP, bigger)
Plumb the `core/lead_projection.py` ahead/even/behind verdict into
`rank_for_primary_archetype` at the `champion_fight_length(champion)` consult
(`daemon_slayer_client.py:1284`): ahead/snowball -> SHORT fight_length (close out
with burst); even/behind -> LONG (safe sustained scaling). Blocked on L1. This is
the fed axis the operator named (the snowball game the sustained model cannot see).

### L6 - hygiene: stale catalog
Stormrazor (3097) is offered in nearly every crit-ADC top-6 but was reworked/
removed from live LoL (6 appearances in 30k rewind rows). Confirm against Meraki /
the live item catalog and exclude if dead. Separate hygiene slice.

## Validation (TDD, per-champion)
- RED tests drive the LIVE path fidelity this time (the Step-1a lesson): assert
  against `rank_for_primary_archetype` (or a faithful adapter) at the LIVE default
  target resolution, not just an in-process fixed cell. Champ set: Twitch,
  Caitlyn, Jinx, Draven, Samira. Assert IE (3031) + Collector (6676) enter top-6;
  on-hit ramp items (Guinsoo 3124) drop; BORK behavior justified vs the chosen
  target. Controls: Vayne (on-hit) stays on-hit; Lux/Ornn byte-identical.
- Backfill: regenerate `data/daemon_slayer/build_orders/<patch>/` after the fix.
- Live-verify in-game (do-not-flip-blind) on the next crit-ADC game.

## Tier + order
L1 (Tier-1) -> L2 (Tier-2, engine bump + Share + :8893) -> L3 (Tier-1) -> L4
(Tier-1) as the core coordinated fix; L5 + L6 follow-ups. L1 must precede L3 (else
fight_length is discarded live). L2 must precede any Collector assertion.

## Scope guards
Metric/stat/fight-timing only - no win-rate, no rewind, no name blacklist. Do NOT
touch mage/tank/enchanter scorers. Keep the Step-1a caster-marksman exclusion.
Widen from crit ADCs to lethality champs (Zed/Kha'Zix/Talon, a DIFFERENT scorer)
only on separate test evidence.
