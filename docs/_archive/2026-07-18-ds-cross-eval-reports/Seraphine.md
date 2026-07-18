# DS Cross-Eval: Seraphine

**Verdict: MISMATCH**

Scorer: hps | Archetype: enchanter (primary) / mage (secondary) | Anchor: ARAM
Evidence: outcome_all (ARAM n=136, baseline wr=56.6%; SR n=86, baseline wr=65.1%)

---

## Axis 1 - archetype_ok: TRUE

hps scorer maps to enchanter archetype (AP-axis), which matches primary=enchanter. The
archetype assignment itself is not wrong per scorer rules. However, secondary=mage is
notable: empirically the dominant build in ARAM is full AP mage (Malignance n=71,
Liandry n=70), not enchanter support. The archetype axis is correct for the declared
primary, so this passes - but the secondary mage path drives the outcome failure below.

---

## Axis 2 - comp_ok: TRUE

scorer=hps -> enchanter/healer class. Comp invariance is EXPECTED: heal throughput does
not scale with enemy damage type or target resist in the same way DPS/EHP scorers do.
Confirmed: all 5 comp cells (ad_squishy / bal_squishy / ap_squishy / ad_tanky / ap_tanky)
are fully identical with d_ehp=0.0, d_dps=0.0 everywhere, max_positive_shift=0 on both
responsiveness axes, and comp_blind=true on both. This is correct behavior for hps.

---

## Axis 3 - outcome_ok: FALSE

Using outcome_all (ARAM n=136, baseline wr=56.6%). Empirical items above baseline:
  Shadowflame      (4645) n=21  wr=61.9
  Malignance       (3118) n=71  wr=59.2
  Amplifying Tome  (1052) n=20  wr=60.0
  Ionian Boots     (3158) n=58  wr=58.6

Scorer top-8: Echoes of Helia (rank1), Ardent Censer (rank2), Staff of Flowing Water
(rank3), Knight's Vow (rank4), Locket of Iron Solari (rank5), Redemption (rank6),
Imperial Mandate (rank7), Mikael's Blessing (rank8).

Zero overlap. Not a single scorer top-8 item appears in the empirical ARAM top items.
Echoes of Helia (scorer rank1, score 21.4) does not appear in empirical ARAM at all.
Moonstone Renewer (scorer rank9, score 0.1342) appears in ARAM empirical at wr=38.1 -
well below baseline, a losing item. The AP mage build (Malignance, Liandry, Shadowflame,
Blackfire Torch n=41 wr=53.7) is entirely absent from the scorer pool. Malignance alone
appears in 52% of all 136 tracked ARAM games at above-baseline wr. This is a pool miss
of the entire dominant empirical build path, not just a staple gap.

SR cross-check (outcome_all n=86, baseline 65.1%): Liandry (wr=93.8), Blackfire Torch
(wr=82.4), Doran's Ring (wr=85.0) all far above baseline - all pure AP items. Moonstone
Renewer appears in SR empirical at wr=68.2 (above baseline), but scorer ranks it near
zero (0.1342). Echoes of Helia (scorer rank1) posts SR wr=47.6 - below baseline.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add AP mage item layer to Seraphine's hps scorer or promote secondary=mage archetype
to a co-scorer (mage scorer alongside hps). At minimum, AP-scaling items (Malignance,
Liandry, Shadowflame, Blackfire Torch) should appear in the scorer pool given Seraphine's
secondary mage archetype and their empirical dominance (Malignance n=71/136 ARAM games,
wr=59.2; Liandry n=70, wr=51.4; Shadowflame wr=61.9). Moonstone Renewer should not score
near-zero when it posts SR wr=68.2.

Suggested approach: dual-scorer dispatch for Seraphine (hps + mage weighted by comp),
or add a mage item bonus layer inside the hps scorer for champions with secondary=mage.
