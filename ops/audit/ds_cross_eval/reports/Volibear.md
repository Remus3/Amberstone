# DS Cross-Eval: Volibear

**Verdict: MINOR**

Scorer = hybrid. Archetype = bruiser/tank. Hybrid axis is correct for a bruiser/tank.
Comp responsiveness is functional. Pool gap: scorer top-8 is flooded with pure-ADC items
that have no empirical presence; high-wr tank staples are absent from the pool.

---

## Axis 1 - archetype_ok: PASS

Scorer hybrid is appropriate for bruiser/tank. Volibear is an AA-heavy melee bruiser
with % max-HP passive damage; hybrid (EHP + AD DPS blend) maps correctly to his kit.
No scorer-axis mismatch.

## Axis 2 - comp_ok: PASS

Scorer = hybrid; primary_axis = enemy_damage_type; comp_blind = false (confirmed).
EHP arm responds: Dead Man's Plate falls -11 vs AP, Iceborn Gauntlet falls -6.
target_resist also moves: Liandry's +18 vs tanky targets, Eclipse +10, Black Cleaver +9.
Neither sub-axis is comp_blind. Hybrid behavior is correct.

## Axis 3 - outcome_ok: FAIL

ARAM baseline wr = 48.1% (n=79, using outcome_all).
Above-baseline items (wr > 48.1%):
  - Fimbulwinter    57.1% (n=14)
  - Unending Despair 54.5% (n=44)
  - Spirit Visage   54.5% (n=33)
  - Heartsteel      51.3% (n=39)
  - Mercury's Treads 52.2% (n=46)

Scorer top-8 (ad_squishy / bal_squishy):
  r1 Void Immolation, r2 BotRK, r3 Trinity Force, r4 Runaan's Hurricane,
  r5 Essence Reaver, r6 Heartsteel, r7 Kraken Slayer, r8 Stormrazor.

Overlap with above-baseline: only Heartsteel (r6, wr 51.3%).

Missing from scorer top-8 entirely:
  - Unending Despair (54.5%, n=44) - not in scorer pool top-12 in any cell
  - Spirit Visage (54.5%, n=33) - not in scorer pool top-12 in any cell
  - Fimbulwinter (57.1%, n=14) - not in scorer pool top-12 in any cell
  - Mercury's Treads (52.2%, n=46) - boots, not in item pool (expected)

Scorer surfaces Runaan's Hurricane (r4, 0 empirical presence), Essence Reaver (r5,
0 empirical), Kraken Slayer (r7, 0 empirical), Stormrazor (r8, 0 empirical) - all
pure-ADC ranged-oriented items. Void Immolation holds r1 across all cells but has
zero empirical representation. The scorer is recommending an ADC-skew build that does
not appear in winning Volibear games.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Boost HP-scaling bruiser/tank items (Unending Despair, Spirit Visage, Fimbulwinter)
in the hybrid scorer EHP arm for Volibear; apply a ranged-item penalty or explicit
melee-only flag to Runaan's Hurricane and Essence Reaver which have zero empirical
presence and are architecturally misfit for a melee bruiser.
