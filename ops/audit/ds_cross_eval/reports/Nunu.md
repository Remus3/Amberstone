# DS Cross-Eval: Nunu

**Verdict: MISMATCH**

Scorer: ehp | Archetype: tank/mage | Anchor: ARAM | Evidence: outcome_all (n=87, wr=40.2%)

---

## Axis 1 - archetype_ok: TRUE

Scorer=ehp, archetype primary=tank. Tank is neutral-axis - EHP scorer is the correct
assignment. Nunu kit (HP-scaling Q heal, R hard CC) supports tank primary. No axis fault.

---

## Axis 2 - comp_ok: TRUE

EHP scorer with comp_blind=false, primary_axis=enemy_damage_type,
max_positive_shift=24.

The scorer does respond to damage type:
- Abyssal Mask shifts +24 rank when enemy is AP
- Kaenic Rookern shifts +22
- Randuin's Omen drops -25 when enemy is AP

target_resist is comp_blind=true with shift=0. This is EXPECTED for an EHP scorer:
EHP maximizes your own durability, it does not model your damage output against
enemy resists. No defect here.

---

## Axis 3 - outcome_ok: FALSE

Scorer top-8 across ad_squishy/bal_squishy (the canonical test cells):
  Rank 1: Void Immolation (4562 / 4426)
  Rank 2: Randuin's Omen (2036) / Warmog's Armor (1830)
  Rank 3: Warmog's Armor (1880) / Heartsteel (1647)
  Rank 4: Unending Despair (1694) / Kaenic Rookern (1619)
  Rank 5: Heartsteel (1692) / Jak'Sho (1613)
  Rank 6: Dead Man's Plate (1669) / Randuin's Omen (1451)
  Rank 7: Jak'Sho (1582) / Force of Nature (1342)
  Rank 8: Sunfire Aegis (1577) / Spirit Visage (1286)

All 8 are armor/HP/tank items.

Empirical ARAM (outcome_all, n=87, baseline wr=40.2%), above-baseline items:
  Luden's Echo       n=42  wr=47.6%  (+7.4 above baseline)
  Shadowflame        n=38  wr=42.1%  (+1.9 above baseline)
  Sorcerer's Shoes   n=54  wr=40.7%  (+0.5 above baseline)

Zero overlap. Not one scorer top-8 item appears in the above-baseline empirical set.
Empirical winners are all AP mage items. The anchor mode (ARAM) Nunu is played and won
as a mage (Luden's 47.6%), not as a tank bruiser. The scorer recommends the wrong build
pool for ARAM Nunu.

Note: SR outcome_all n=21 too small for strong conclusions, but Liandry's Torment
(wr=53.8%, n=13) and Thornmail (71.4%, n=7) suggest mixed AP+tank in SR - Liandry's
also absent from scorer pool.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add secondary=mage scorer weighting to Nunu's ARAM anchor. Option A: blend mage scorer
(AP power, Luden's/Shadowflame/Liandry's pool) with ehp at ~0.4/0.6 split for ARAM.
Option B: promote mage to primary for ARAM-mode dispatch, keep tank/ehp for SR.
The simplest fix is to confirm Nunu secondary=mage triggers a mage scorer pass and that
Luden's Echo, Shadowflame, and Liandry's Torment enter the candidate pool for ARAM.
