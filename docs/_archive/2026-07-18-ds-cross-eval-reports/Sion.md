# DS Cross-Eval: Sion

VERDICT: MINOR

## 1. Archetype

Primary=tank, secondary=bruiser, scorer=ehp.
EHP scorer is neutral/correct for tanks. Sion kit: passive stacks max HP permanently, making raw EHP the right primary axis.
Empirical above-baseline (ARAM all, baseline 53.9%): Heartsteel 55.8% (n=86) ranks #4 in ad_squishy scorer - aligned. Unending Despair 56.2% (n=48) ranks #5 in ad_squishy - aligned. Hollow Radiance 60.9% (n=23) appears at rank 8 in ap_squishy/ap_tanky - aligned.
archetype_ok: true

## 2. Comp responsiveness

EHP scorer with enemy_damage_type as primary_axis. comp_blind=false.
max_positive_shift=24 ranks on enemy AP: Abyssal Mask +24, Hollow Radiance +23, Kaenic Rookern +22, Force of Nature +22, Spirit Visage +21. When AD: Iceborn Gauntlet -27, Randuin's Omen -25, Dead Man's Plate -23, Sunfire Aegis -22. Responsiveness is strong and directionally correct.
target_resist comp_blind=true (max_positive_shift=0) - expected for a tank EHP scorer that does not model outgoing DPS; Sion's contribution is absorption not burst, so target-resist invariance is correct behavior.
comp_ok: true

## 3. Outcome overlap

ARAM evidence_tier=outcome_all (n=102, baseline wr=53.9%). Self n=1 so using all.
Scorer top-8 in ad_squishy (primary squishy-AD comp): Void Immolation, Randuin's Omen, Warmog's Armor, Heartsteel, Unending Despair, Dead Man's Plate, Jak'Sho, Sunfire Aegis.
Empirical items above baseline:
- Heartsteel 55.8% (n=86) - rank 4 scorer, aligned
- Unending Despair 56.2% (n=48) - rank 5 scorer, aligned
- Plated Steelcaps 61.3% (n=31) - boots, not in scorer item pool (expected exclusion)
- Hollow Radiance 60.9% (n=23) - rank 8 ap-comp cells, aligned

Empirical items in scorer top-8 BELOW baseline:
- Jak'Sho, The Protean: rank 7 ad_squishy (score 1318), rank 5 bal_squishy (score 1336) - empirical wr 42.1% (n=19), baseline 53.9%. 11.8 pp below baseline.

Additional below-baseline items in scorer pool:
- Thornmail: rank 9 ad_squishy - empirical wr 44.2% (n=43). Not top-8 but notably weak.
- Titanic Hydra: empirical wr 42.9% (n=14) - not in top scorer pool, but worth noting.

Jak'Sho in scorer top-7/8 positions across two comp cells while empirically losing is the key gap. High theoretical EHP from its scaling passive, but real outcomes are below baseline.
outcome_ok: false

## 4. Rune

rune_relevant=false -> n/a

## Nominated retune

Apply a downward empirical-outcome weight to Jak'Sho (empirical wr 42.1% vs 53.9% baseline, n=19) in the EHP tank scorer. Also apply a mild penalty to Thornmail (44.2%, n=43). Consider a small bonus for Hollow Radiance given its strong AP-comp rank rise AND above-baseline empirical wr (60.9%).
