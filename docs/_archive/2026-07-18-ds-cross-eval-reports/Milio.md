# DS Cross-Eval: Milio
Verdict: MINOR

## Archetype axis
OK.
Milio archetype=enchanter/mage, scorer=hps. HPS is the correct AP-axis scorer for a
heal/shield support. Kit alignment confirmed.

## Comp axis
OK (expected invariance).
HPS/enchanter scorer - comp invariance is expected by design; the scorer evaluates
heal/shield throughput, not self-survival. All 5 comp cells (ad_squishy, bal_squishy,
ap_squishy, ad_tanky, ap_tanky) show d_ehp=0 and d_dps=0 with identical per-item
scores. comp_blind=true and max_positive_shift=0 on both enemy_damage_type and
target_resist axes. For an enchanter hps scorer this is not a defect; the scorer is
not supposed to shift on enemy composition.

## Outcome axis
MINOR - high-wr staple (Seraph's Embrace) absent from scorer pool.
Evidence source: ARAM all (n=83, baseline wr=53.0; self n=5, insufficient).

Items above baseline wr in empirical ARAM all:
- Seraph's Embrace (3040): wr=70.0, n=20 - NOT in scorer top-8, not in scorer list
- Ardent Censer (3504): wr=62.5, n=32 - scorer rank 2, score 16.3 (OK)
- Forbidden Idol (3114): wr=56.2, n=16 - not in scorer output at all
- Moonstone Renewer (6617): wr=54.5, n=55 - scorer rank 9, score 0.735 (very low for
  most-built item)
- Ionian Boots (3158): wr=54.7, n=53 - boots, expected outside scorer pool

Scorer top-8 (all cells identical): Echoes of Helia (26.2) > Ardent Censer (16.3) >
Staff of Flowing Water (13.0) > Locket (10.2) > Knight's Vow (10.0) > Redemption (8.5)
> Imperial Mandate (7.9) > Mikael's Blessing (3.8).

Seraph's Embrace at wr=70.0 (n=20) is the strongest empirical signal in the pool and
is completely absent from scorer output. Moonstone Renewer is the most-built item (n=55)
but sits at scorer rank 9 with score 0.735, a 35x gap vs #1 Echoes (26.2). These are
pool gaps / weight mismatches, not a wrong-axis or empirically-losing top build.

Luden's Echo (6655) appearing in empirical ARAM all at wr=42.9 (below baseline) is a
noise signal from off-meta mage builds; not scorer concern.

## Rune axis
n/a (rune_relevant=false)

## Nominated retune
Add Seraph's Embrace to the HPS scorer item pool (it amplifies heal output via mana/AP
scaling, directly relevant to Milio kit). Audit Moonstone Renewer weight - score 0.735
vs 26.2 for Echoes seems underweighted for the most-played item.
