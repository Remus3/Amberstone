# DS Cross-Eval: AurelionSol

**Verdict: MINOR**

Scorer: ability | Archetype: mage/assassin | Evidence: ARAM outcome_all n=155 baseline wr=52.3%

---

## Axis 1 - archetype_ok: PASS

Mage primary -> ability scorer -> AP axis. Kit is entirely AP-scaling (star Q, stardust W stacking,
R big AP nuke). All above-baseline empirical items are AP. Scorer axis is correct.

## Axis 2 - comp_ok: PASS

Primary axis = target_resist. Responsiveness is present: max_positive_shift +8 via Bloodletter's
Curse, Cryptbloom +3, Void Staff +2, Liandry +1. Tanky comps correctly elevate MR-penetration items.

enemy_damage_type is comp_blind (max_positive_shift=0, no risers/fallers). For an ability/mage
scorer this is expected - enemy damage type does not change the AS damage output or the recommended
offense build. No defect.

## Axis 3 - outcome_ok: FAIL

Above-baseline empirical items (wr > 52.3%, ARAM outcome_all):
- Seraph's Embrace: wr=56.4%, n=78 -> NOT in scorer top-12
- Rod of Ages:      wr=54.2%, n=59 -> NOT in scorer top-12
- Liandry's:        wr=53.8%, n=117 -> scorer rank 2 (OK)
- Needlessly Large Rod: wr=54.5%, n=22 (component, expected absent)

Seraph's and RoA are the two highest-wr items with large sample sizes and both are entirely
absent from the scorer pool. These are mana-scaling/HP-scaling items that suit AS's stardust
mechanic (large mana pool amplifies W stacking potential). The ability scorer has no pathway to
credit mana-to-AP or mana-to-survivability conversions, so it misses them entirely.

Scorer top-8 items that are below baseline empirically:
- Rabadon's (rank 4): wr=51.4% (<52.3 baseline)
- Shadowflame (rank 5): wr=50.0% (<52.3 baseline)
- Void Staff (rank 6): not in top empirical items
- Stormsurge (rank 7): not in top empirical items
- Banshee's Veil (rank 8): not in top empirical items

## Axis 4 - rune_ok: n/a

rune_relevant=false

## Nominated Retune

Add mana-pool credit to the ability scorer for AurelionSol: items that provide large mana (Seraph's,
RoA) should receive bonus scoring weight reflecting stardust W scaling. Alternatively, add a
champion-specific mana-scaling multiplier that surfaces mana items into the scorer pool when the
champion has a documented mana-to-power conversion.
