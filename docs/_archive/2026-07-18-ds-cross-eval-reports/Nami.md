# Nami DS Scorer Cross-Eval Report

**Verdict: MINOR**
Scorer: hps | Archetype: enchanter/mage | Anchor: ARAM | Evidence: outcome_all (n=126, baseline wr=46.8%)

---

## Axis 1 - archetype_ok: PASS

Nami is enchanter/mage. hps scorer is the correct axis for an enchanter - heal/shield throughput
is her primary function (W heal, R wave, passive empowered autos). Empirical above-baseline
ARAM items are all enchanter/AP support: Ardent Censer 52.4% (n=42), Redemption 53.1% (n=32),
Dawncore 52.2% (n=23), Staff of Flowing Water 50.0% (n=30). These align with an AP enchanter
scorer pool. No axis mismatch.

---

## Axis 2 - comp_ok: PASS

Scorer = hps. For an enchanter, comp invariance is expected behavior - heal/shield value is
independent of enemy damage type. All 5 comp cells (ad_squishy, bal_squishy, ap_squishy,
ad_tanky, ap_tanky) are fully identical: same ranks, same scores, d_ehp=0, d_dps=0.
responsiveness.comp_blind=true and both enemy_damage_type and target_resist show
max_positive_shift=0. This is correct enchanter behavior, not a defect.

---

## Axis 3 - outcome_ok: FAIL (MINOR)

Scorer top-8 (ad_squishy cell, representative):
  #1 Echoes of Helia (6620) score=27.64
  #2 Ardent Censer (3504) score=16.40
  #3 Staff of Flowing Water (6616) score=13.09
  #4 Locket of the Iron Solari (3190) score=11.31
  #5 Knight's Vow (3109) score=10.00
  #6 Redemption (3107) score=8.94
  #7 Imperial Mandate (4005) score=8.03
  #8 Mikael's Blessing (3222) score=3.92

Empirical ARAM above-baseline (wr > 46.8%):
  Ardent Censer: 52.4% (n=42) - scorer #2 - ALIGNED
  Redemption: 53.1% (n=32) - scorer #6 - ALIGNED
  Dawncore: 52.2% (n=23) - NOT IN SCORER POOL (absent from all cells) - POOL GAP
  Dawncore: 52.2% (n=23) - MISSING
  Imperial Mandate: 48.8% (n=86) - scorer #7 - ALIGNED
  Staff of Flowing Water: 50.0% (n=30) - scorer #3 - ALIGNED

Flags:
  1. Echoes of Helia is scorer #1 (score=27.64) but empirical wr=42.9% (n=84) is BELOW baseline
     46.8%. The top scorer recommendation is a below-average performer empirically.
  2. Dawncore (6621) has 52.2% wr (n=23) and is entirely absent from the scorer item pool
     across all 5 comp cells. This is a pool gap - a winning item not considered by the scorer.
  3. Moonstone Renewer (#9, lowest scorer) also shows 42.9% wr (n=84) - below baseline.

Note: Ionian Boots (3158) is highest-n empirical item (n=103, 48.5%) but boots are typically
excluded from DS item pools - absence expected.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Dawncore (6621) to the hps scorer item pool - it has 52.2% ARAM wr (n=23) and is entirely
absent from all comp cells. Investigate why Echoes of Helia scores 27.64 (top rank) despite
42.9% empirical wr; likely selection-bias (built by losing teams chasing healing) but the gap
vs Ardent Censer (52.4% wr, scorer #2) suggests hps weighting may over-reward Helia's passive
heal proc relative to its actual win contribution.
