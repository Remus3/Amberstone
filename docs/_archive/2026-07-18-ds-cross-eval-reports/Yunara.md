# DS Cross-Eval: Yunara

**Verdict: MINOR**

Scorer=dps, archetype=carry/bruiser, anchor=ARAM, evidence_tier_ARAM=outcome_all (n=17, baseline wr=52.9%).

---

## Axis 1 - archetype_ok: TRUE

DPS scorer is AD-axis. Yunara is a crit/attack-speed carry - kit aligns with AD scaling. Empirically dominant items are Infinity Edge (wr 75.0%), Runaan's Hurricane (wr 61.5%), Yun Tal Wildarrows (wr 60.0%) - all AD crit items. Scorer axis is correct.

## Axis 2 - comp_ok: TRUE

DPS scorer requires target_resist responsiveness. responsiveness.target_resist.max_positive_shift=13, comp_blind=false. Tanky comps surface Liandry's Torment (+13), Serylda's Grudge (+9), Lord Dominik's (+8). Responsiveness is working. enemy_damage_type is comp_blind=true (max_positive_shift=0) but that is expected for a dps scorer - incoming damage type does not gate outgoing DPS recommendations.

## Axis 3 - outcome_ok: FALSE

Using ARAM.all (n=17 >= 8, baseline 52.9%).

Above-baseline empirical items:
- Infinity Edge: wr 75.0% (n=12) - scorer rank 11, OUTSIDE top-8
- Runaan's Hurricane: wr 61.5% (n=13) - scorer rank 9, OUTSIDE top-8
- Berserker's Greaves: wr 60.0% (n=10) - not in scorer pool
- Yun Tal Wildarrows: wr 60.0% (n=10) - scorer rank 6, inside top-8 (ok)
- Blade of The Ruined King: wr 40.0% (n=5) - scorer rank 1, BELOW baseline (40.0 < 52.9)

BotRK is the scorer's top pick but empirically loses (wr 40.0% vs baseline 52.9%). The two highest-wr staples (IE rank 11, Runaan's rank 9) are pushed outside the top-8. Pool ordering is inverted for crit-scaling context.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Reduce BotRK score weight for crit-carry archetypes (carry primary), or apply a crit-synergy bonus that pulls Infinity Edge and Runaan's Hurricane into top-8. BotRK %-max-hp passive is overweighted relative to Yunara's crit scaling payoff. Target: IE into top-3, Runaan's into top-5 for crit-carry dps scoring path.
