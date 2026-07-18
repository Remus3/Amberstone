# DS Cross-Eval: Morgana

**Verdict: MISMATCH**

Scorer=hps (enchanter) recommends a pure support item pool with zero overlap against the empirically winning AP mage build path in ARAM.

---

## Axis 1: archetype_ok - TRUE

- primary=enchanter, secondary=mage, scorer=hps
- hps scorer is the enchanter/AP axis scorer. Morgana has ally-shield (Black Shield) and passive lifesteal, so enchanter classification is defensible from kit.
- Scorer axis (AP/enchanter=hps) matches kit. No wrong-axis flag on the scorer choice itself.

## Axis 2: comp_ok - TRUE (invariance expected)

- scorer=hps is an enchanter scorer. HPS scorers do NOT key on enemy damage type or target resistance - comp invariance is EXPECTED behavior for this scorer class.
- All 5 comp cells (ad_squishy / bal_squishy / ap_squishy / ad_tanky / ap_tanky) show identical rankings and scores. d_ehp=0.0, d_dps=0.0 across all cells. responsiveness.comp_blind=true confirmed.
- This is correct. No defect.

## Axis 3: outcome_ok - FALSE (pool gap / archetype drift)

Evidence tier ARAM = outcome_self, self.n=9 (>=8, so use self). Baseline wr=44.4%.

Scorer top-8 (ad_squishy / bal_squishy, identical across all cells):
  rank 1  Echoes of Helia       score=27.16
  rank 2  Ardent Censer         score=15.79
  rank 3  Staff of Flowing Water score=12.61
  rank 4  Locket of the Iron Solari score=11.31
  rank 5  Knight's Vow          score=10.0
  rank 6  Redemption            score=8.53
  rank 7  Imperial Mandate      score=7.14
  rank 8  Mikael's Blessing     score=3.92

Empirical ARAM self (n=9, wr=44.4%):
  Blackfire Torch   n=8  wr=37.5%  (below baseline)
  Liandry's Torment n=8  wr=37.5%  (below baseline)
  Sorcerer's Shoes  n=5  wr=20.0%  (below baseline)

Self sample is small and all below baseline - no above-baseline signal to contradict scorer.
Checking outcome_all for broader signal (n=250, wr=52.0%):
  Blackfire Torch   n=142 wr=54.2%  (above baseline +2.2pp)
  Ionian Boots      n=51  wr=52.9%  (above baseline +0.9pp)
  Needlessly Large Rod n=41 wr=53.7% (above baseline +1.7pp)
  Shadowflame       n=40  wr=52.5%  (above baseline +0.5pp)
  Sorcerer's Shoes  n=167 wr=51.5%  (near baseline)
  Zhonya's Hourglass n=96 wr=50.0%  (below baseline)

NONE of the above-baseline empirical items (Blackfire Torch, Needlessly Large Rod, Shadowflame, Ionian Boots) appear anywhere in the scorer's 9-item pool. The scorer pool is entirely enchanter support items. The empirical record (n=250) shows Morgana is being played and winning as AP mage. Total pool overlap = 0/8.

Flag: scorer top-8 is entirely absent from the empirical win-positive builds. Major pool gap.

## Axis 4: rune_ok - N/A

rune_relevant=false.

---

## Nominated Retune

Switch ARAM anchor scorer from hps to mage (or ability). Morgana's secondary=mage is the empirically winning path in ARAM: Blackfire Torch (n=142, wr=54.2%), Blackfire + Liandry dot-build, Needlessly Large Rod (n=41, wr=53.7%), Shadowflame (n=40, wr=52.5%). The enchanter/hps scorer correctly prices support items but those builds do not appear in this player's ARAM data nor in the above-baseline all-player pool. Adding mage as a co-scorer or promoting secondary=mage to primary for ARAM mode would surface the winning item pool.
