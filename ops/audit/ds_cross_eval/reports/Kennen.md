# DS Cross-Eval: Kennen

**VERDICT: MINOR**

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_all (n=89, baseline wr=58.4%)

---

## Axis 1 - archetype_ok: PASS

Primary archetype = mage, secondary = assassin. Both are AP-axis archetypes.
Scorer = ability (AP-axis scorer). Kit is entirely AP (W AoE, E stun proc, R AoE AP).
Empirical top items are all AP items (Shadowflame, Stormsurge, Rabadon's, Void Staff).
Axis alignment is correct.

## Axis 2 - comp_ok: PASS (design note)

Primary axis = target_resist. Ability scorer responds to tanky enemies:
max_positive_shift = 5. Top risers vs tanky: Bloodletter's Curse +5 ranks,
Void Staff +2, Cryptbloom +2, Liandry's +1. This is correct behavior.

Enemy damage type sub-field is comp_blind (max_positive_shift=0, no top_risers_when_ap).
All 5 comp cells show d_ehp=0.0 across every item - no EHP component adapts to
enemy AD/AP split. For a pure ability/mage DPS scorer this is expected: the scorer
models outgoing damage, not survivability. It is not an EHP or hybrid scorer, so
comp-blindness on enemy damage type is by design, not a defect. comp_ok=true.

## Axis 3 - outcome_ok: MINOR POOL GAP

Above-baseline empirical items (wr > 58.4%):
- Sorcerer's Shoes      n=73  wr=61.6%  (boots, not in item scorer pool - expected)
- Shadowflame           n=62  wr=61.3%  scorer rank 5 (ad_squishy) - PRESENT
- Stormsurge            n=42  wr=69.0%  scorer rank 7 - PRESENT (highest empirical wr)
- Rabadon's Deathcap    n=36  wr=61.1%  scorer rank 4 - PRESENT
- Needlessly Large Rod  n=21  wr=61.9%  (component, not full item - expected absent)
- Void Staff            n=15  wr=60.0%  scorer rank 6 - PRESENT
- Amplifying Tome       n=11  wr=63.6%  (component - expected absent)
- Malignance            n=11  wr=63.6%  NOT in scorer top-12 - POOL GAP

Malignance (id 3118) posts 63.6% wr (n=11) and is entirely absent from the
scorer top-12. That is a minor pool gap.

Separately, scorer ranks 1-3 (Wooglet's Witchcap, Liandry's Torment, Blackfire Torch)
have zero empirical presence in this dataset. The dataset is small (n=89) so this
is inconclusive, but these top-3 scorer picks have no empirical validation here.
Wooglet's at rank 1 is a 6000g ARAM-exclusive item so limited sample is expected;
Liandry's and Blackfire Torch at rank 2-3 with no empirical appearance is a mild
concern but below MISMATCH threshold given n=89.

outcome_ok = true, flagging as MINOR for Malignance pool absence.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Malignance (id 3118) to Kennen's ability scorer item pool. It is an above-baseline
empirical item (63.6% wr, n=11) with no scorer representation.

Consider verifying Liandry's and Blackfire Torch empirical absence is sample-size
driven, not a scorer mis-valuation, once a larger dataset is available.
