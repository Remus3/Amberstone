# RekSai DS Scorer Cross-Eval

**Verdict: MINOR**
Scorer axis correct (AD hybrid for bruiser/tank). Pool gap: Heartsteel top-4 in scorer but 28.6 wr empirically; Eclipse (80.0 wr) and Sundered Sky (61.5 wr) rank 12+ in squishy cells.

---

## Axis 1 - archetype_ok: TRUE

Rek'Sai is bruiser (primary)/tank (secondary), AD scaling throughout. Hybrid scorer (EHP+DPS blend) is the right archetype for a melee bruiser jungler who needs both to function. Scorer is wired to AD axis. No axis mismatch.

## Axis 2 - comp_ok: TRUE

Hybrid scorer includes EHP; enemy_damage_type responsiveness is confirmed active (comp_blind=false).
- enemy_damage_type max_positive_shift=11 (Wit's End rises 11 ranks when AP heavy)
- target_resist max_positive_shift=20 (Liandry's rises 20 ranks vs tanky targets)
- Both sub-axes comp_blind=false

Comp responsiveness is working correctly. No defect here.

## Axis 3 - outcome_ok: FALSE

Empirical baseline (ARAM outcome_all, n=29): wr=48.3

Items above baseline:
- Mercury's Treads: wr=55.6 (n=18) - not in scorer pool (boots, expected)
- Sundered Sky (id 6610): wr=61.5 (n=13) - rank 12 in ad_squishy (score 0.6137), rank 12 in ap_squishy (score 0.6137), rank 12 in ap_tanky absent. Buried.
- Eclipse (id 6692): wr=80.0 (n=5) - rank 5 in ad_tanky (score 0.8698) and ap_tanky, but does NOT appear in top-8 of ad_squishy or bal_squishy cells (the anchor comp cells).
- Spirit Visage: wr=50.0 (at baseline, not flagged)

Items in scorer top-8 that are empirically weak or absent:
- Heartsteel (rank 4, score 0.8641): empirical wr=28.6 (n=14), well below 48.3 baseline. A top-4 recommended item that empirically loses.
- Runaan's Hurricane (rank 5), Essence Reaver (rank 6), Kraken Slayer (rank 7), Stormrazor (rank 8): all have d_ehp=0.0, zero empirical presence in ARAM data. These are pure ADC crit/AS items that do not fit a bruiser kit.

Summary: Heartsteel is a confirmed loser in the top-4 scorer pool. Eclipse and Sundered Sky are high-wr empirical staples that rank 5/12 in the anchor comp cells. Outcome misalignment is real.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Demote Heartsteel in the hybrid scorer pool for Rek'Sai (its large d_ehp inflates score but empirically loses at 28.6 wr). Elevate Eclipse and Sundered Sky: both carry meaningful d_ehp AND d_dps and are the empirical high-wr staples. Consider capping the pure-ADC crit/AS items (Runaan's, Essence Reaver, Kraken Slayer, Stormrazor) for bruiser archetype - they have 0 d_ehp and zero empirical representation on Rek'Sai, inflating pool noise in ranks 5-8.
