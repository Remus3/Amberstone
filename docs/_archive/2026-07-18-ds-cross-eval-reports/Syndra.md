# DS Cross-Eval: Syndra

VERDICT: MINOR

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_self (n=12, wr=66.7%)

---

## Axis 1 - archetype_ok: PASS

Mage primary maps correctly to the ability scorer (AP axis). All above-baseline empirical items
in ARAM self are AP: Shadowflame wr=70.0%, Rabadon's wr=88.9%, Stormsurge wr=80.0%,
Amplifying Tome wr=100.0%. No AD items appear in empirical. Axis alignment confirmed.

## Axis 2 - comp_ok: PASS

Scorer=ability -> primary_axis should be target_resist, not enemy_damage_type. Confirmed:
responsiveness.primary_axis = "target_resist", comp_blind = false (top-level).

enemy_damage_type.comp_blind = true with max_positive_shift = 0 is EXPECTED for an ability
scorer -- Syndra does not change her build based on whether the enemy team is AD or AP, so
this invariance is correct, not a defect.

target_resist responds correctly: Bloodletter's Curse +3 ranks, Void Staff +2, Cryptbloom +2
all rise vs tanky comps. Shadowflame -2, Stormsurge -2 fall vs tanky (they reward low-armor
squishies). max_positive_shift = 3. Behavior is sensible and non-blind.

## Axis 3 - outcome_ok: PASS (with pool gap note)

Using ARAM self (n=12 >= 8). Baseline wr = 66.7%.

Scorer top-8 (ad_squishy): Wooglet's Witchcap R1, Liandry's R2, Blackfire Torch R3,
Rabadon's R4, Void Staff R5, Shadowflame R6, Stormsurge R7, Cryptbloom R8.

Empirical items above 66.7% baseline wr that overlap scorer top-8:
- Shadowflame (R6 scorer, wr 70.0%) -- aligned
- Rabadon's (R4 scorer, wr 88.9%) -- strongly aligned
- Stormsurge (R7 scorer, wr 80.0%) -- aligned

No scorer-top item appears to be empirically losing. Outcome OK.

POOL GAP: Luden's Echo (id 6655) appears in empirical self with n=9, wr=55.6% and in
empirical all with n=123, wr=51.2% (below baseline but high frequency). It does not appear in
scorer top-8 for any comp cell. As a core first-item staple for Syndra, its absence from the
scorer pool means the engine never recommends it -- a real gap even if its wr is below baseline.
Not a MISMATCH (it is not winning above baseline), but worth fixing.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Luden's Echo to Syndra's ability scorer item pool so it can surface in recommendations.
It is the most-bought item in ARAM all (n=123) and a frequent pick in SR (n=36), but absent
from all comp-cell top-8 lists. The engine currently cannot recommend it.

---

## Summary

Syndra's ability scorer is correctly axis-aligned (AP/mage), comp-responsive in the right
dimension (target_resist vs tanky), and the top scorer items that appear in empirical data are
all winning. The sole issue is Luden's Echo being entirely absent from the scorer pool despite
being the most-purchased item empirically. Severity: MINOR.
