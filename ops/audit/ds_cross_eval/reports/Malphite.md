# Malphite DS Cross-Eval Report

**Verdict: MISMATCH**

Scorer: ehp | Archetype: tank (secondary mage) | Anchor: ARAM | Evidence: outcome_all (n=180, baseline wr=46.7%)

---

## Axis 1 - archetype_ok: TRUE

Malphite is primary tank, scorer=ehp. Tank -> ehp is the correct neutral-axis scorer. Kit confirms: passive rock-shield, high base HP, armor scaling on W, AP ratio on Q/R. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE (with a d_ehp export gap noted)

Scorer is ehp. Enemy damage type MUST drive rank shifts. comp_blind=false, primary_axis=enemy_damage_type. Rank shifts are present and large:
- Kaenic Rookern: ap_squishy rank 2, absent from ad_squishy top-8 -> shift +22
- Force of Nature: ap_squishy rank 3 vs absent AD -> shift +22
- Abyssal Mask: ap_squishy rank 9 vs absent AD -> shift +28
- Iceborn Gauntlet: ad_squishy rank 10, drops out completely in AP -> shift -28
- Dead Man's Plate: ad_squishy rank 6, drops out in AP -> shift -25

Ranking is comp-responsive. However d_ehp=0.0 on every item in every cell - the delta-EHP is not being exported to the cross-eval payload. This is a data-export gap (score moves, d_ehp field does not); it does not indicate the scorer is comp-blind. comp_ok=true; flag the d_ehp zero-export as a minor data issue.

---

## Axis 3 - outcome_ok: FALSE (MISMATCH)

Using outcome_all (self n=1, all n=180). Baseline wr=46.7%.

Above-baseline items from empirical ARAM (wr > 46.7%):
- Mercury's Treads (id 3111): n=55, wr=54.5% -- BEST performer
- Sorcerer's Shoes (id 3020): n=61, wr=50.8%
- Rabadon's Deathcap (id 3089): n=37, wr=51.4%
- Stormsurge (id 4646): n=55, wr=49.1%
- Malignance (id 3118): n=82, wr=47.6%

These are all AP/mage items. None appear in scorer top-8 for any cell.

Scorer top-8 (ad_squishy): Void Immolation, Randuin's Omen, Warmog's, Unending Despair, Heartsteel, Dead Man's Plate, Jak'Sho, Sunfire Aegis.
Scorer top-8 (bal_squishy): Void Immolation, Warmog's, Jak'Sho, Kaenic Rookern, Heartsteel, Randuin's Omen, Force of Nature, Spirit Visage.

Randuin's Omen (rank 2 ad_squishy): zero empirical presence in the win data.
Dead Man's Plate (rank 6 ad_squishy): zero empirical presence.
Sunfire Aegis (rank 8 ad_squishy): n=11 SR wr=36.4% (below baseline), zero ARAM presence.

Heartsteel (rank 5 ad_squishy, n=49 ARAM, wr=49.0%) is the ONE scorer-top item that is also empirically above baseline.

The mismatch is systematic: Malphite empirically wins with AP mage builds (Malignance, Sorcerer's Shoes, Rabadon's, Stormsurge) but the ehp scorer surfaces pure tank items with no empirical support. Secondary archetype mage is not contributing to the scorer pool at all.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Wire Malphite secondary=mage scorer contribution into the item pool. When secondary=mage, the item-scoring pass should include an AP-scaled path so mage-tank hybris items (Malignance, Shadowflame, Stormsurge, Rabadon's) can surface in ranked results. The pure-ehp scorer correctly ranks armor/HP items; the gap is that AP carry items which win empirically have no scoring path at all. Option: dual-scorer blend (ehp primary, mage secondary at reduced weight) gated on secondary=mage; items scoring above threshold on either path enter the pool.
