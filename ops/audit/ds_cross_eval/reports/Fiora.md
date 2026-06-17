# DS Cross-Eval Verdict: Fiora

**Severity: MINOR**
**Scorer: hybrid | Archetype: bruiser/assassin | Anchor: ARAM | Evidence: outcome_self (n=13, wr=53.8%)**

---

## Axis 1 - archetype_ok: TRUE

Hybrid scorer (blends EHP + DPS) is correct for Fiora. She is an AD melee duelist who
needs both durability (Riposte, Vital heals, passive sustain) and damage output. The
hybrid axis is the right home for this kit. Empirical top builds (Ravenous Hydra,
Trinity Force, Sundered Sky) are all AD physical - no AP or wrong-damage-type signal.

---

## Axis 2 - comp_ok: TRUE

Scorer primary_axis = enemy_damage_type, comp_blind = false. The EHP component responds
to enemy damage type: Hollow Radiance rises +6 positions when enemy comp is AP-heavy.
Dead Man's Plate falls -5 when AP (armor-stack loses value vs AP enemies). The
target_resist axis also moves: Eclipse +10, Mortal Reminder +9, Liandry's Torment +9
when facing tanky enemies. Both sub-axes are active and plausible for a hybrid scorer.
No comp-blind defect.

---

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=13 >= 8). Baseline wr = 53.8%.

Above-baseline empirical items (ARAM self):
- Mercury's Treads: 60.0% wr, n=10 (boots - not in scorer pool, expected)
- Sundered Sky: 60.0% wr, n=5

Below-baseline empirical items:
- Trinity Force: 42.9% wr, n=7 (BELOW 53.8% baseline)
- Ravenous Hydra: 50.0% wr, n=12 (most-built item, below baseline but closest)
- Death's Dance: 20.0% wr, n=5

Scorer top-8 vs empirical (ad_squishy / bal_squishy cells):

| Rank | Item | Score (ad_sq) | Empirical wr |
|------|------|---------------|--------------|
| 1 | Void Immolation | 2.1358 | NOT in empirical |
| 2 | Trinity Force | 1.3294 | 42.9% - BELOW baseline |
| 3 | Heartsteel | 1.2154 | NOT in empirical |
| 4 | BotRK | 1.1149 | NOT in empirical |
| 5 | Essence Reaver | 1.0721 | NOT in empirical |
| 6 | Iceborn Gauntlet | 0.9806 | NOT in empirical |
| 7 | Dusk and Dawn | 0.9788 | NOT in empirical |
| 8 | Dead Man's Plate | 0.8476 | NOT in empirical |

Issues flagged:
1. Trinity Force scorer rank 2 (score 1.3294) but empirical wr 42.9% - below the 53.8%
   baseline. Scorer overvalues it for Fiora.
2. Sundered Sky empirically 60.0% wr (n=5) but scorer rank 11 in ad_squishy,
   rank 11 in bal_squishy. Scorer undervalues it.
3. Ravenous Hydra is the most-built item (n=12, wr 50.0%) and is entirely absent from
   the scorer pool across all 5 comp cells. A staple that never surfaces is a pool gap.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

1. Add Ravenous Hydra to Fiora scorer pool - most-built item (n=12 ARAM self), absent
   from all comp cells. Its hydra-passive sustain is a core Fiora mechanic.
2. Recalibrate Trinity Force score downward - scorer rank 2 but 42.9% empirical wr
   (below baseline). The Spellblade/Fury proc contribution may be overcounted vs
   Fiora's actual usage pattern.
3. Lift Sundered Sky - scorer rank 11 but empirically 60.0% wr. The Cruelty proc
   (true damage on low-hp targets) aligns directly with Fiora's Vital-finish playstyle;
   the scorer is not capturing that synergy.
