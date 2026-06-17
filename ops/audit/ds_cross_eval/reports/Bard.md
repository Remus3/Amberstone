# DS Cross-Eval: Bard

**VERDICT: MISMATCH**

Scorer: hps | Archetype: enchanter/mage | Anchor: ARAM | Evidence tier: outcome_all (n=98, baseline wr=54.1%)

---

## Axis 1 - archetype_ok: TRUE (with caveat)

hps maps to enchanter; Bard primary=enchanter is technically correct. Kit has Shrine heal,
meep-passive utility, Cosmic Binding CC - enchanter framing is defensible.

Caveat: ARAM empirical evidence (all items with wr > 54.1%) is entirely AP/carry:
- Statikk Shiv (n=23, wr=65.2%)
- Nashor's Tooth (n=20, wr=60.0%)
- Needlessly Large Rod (n=17, wr=58.8%)
- Rapid Firecannon (n=34, wr=55.9%)
- Lich Bane (n=50, wr=54.0%)

Secondary=mage is registered but the scorer is pure hps with no mage influence.
The enchanter scorer axis is not wrong per se, but it is misaligned with what actually wins.

---

## Axis 2 - comp_ok: TRUE

Scorer=hps/enchanter. Comp invariance is expected for this archetype - the scorer does not
depend on enemy damage type or target resist. All 5 comp cells are byte-identical
(scores, ranks, d_ehp=0, d_dps=0). comp_blind=true confirmed. This is correct behavior
for an enchanter scorer. No defect.

---

## Axis 3 - outcome_ok: FALSE (DEFECT)

Using outcome_all (ARAM, n=98, baseline wr=54.1%).

Scorer top-8 (identical across all comp cells):
  rank1 Echoes of Helia (score=32.6) - NOT in empirical top-10 at all
  rank2 Ardent Censer (score=16.0) - NOT in empirical top-10
  rank3 Staff of Flowing Water (score=12.8) - NOT in empirical top-10
  rank4 Locket of the Iron Solari (score=11.3) - NOT in ARAM empirical; appears SR at wr=33.3% (below baseline)
  rank5 Redemption (score=10.2) - NOT in empirical top-10
  rank6 Knight's Vow (score=10.0) - NOT in empirical top-10
  rank7 Imperial Mandate (score=7.4) - NOT in empirical top-10
  rank8 Mikael's Blessing (score=4.3) - NOT in empirical top-10

Zero overlap between scorer top-8 and empirical above-baseline ARAM items.
Every empirical winner above baseline is an AP/attack-speed/mage item - none scored
by hps. Moonstone Renewer (rank9, score=0.54) is the only enchanter item even near
the scorer and it barely scores.

The scorer recommends a full enchanter support kit that empirically underperforms the
54.1% baseline, while the builds that actually win (Statikk Shiv 65.2%, Nashor's 60.0%,
NLR 58.8%) are invisible to the scorer.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add mage-scorer contribution to Bard ARAM scoring, or swap archetype primary to mage/
secondary enchanter for ARAM anchor. The scorer should surface Lich Bane, Nashor's Tooth,
and Statikk Shiv which are the empirically winning items (all wr > 54.1% baseline).
Suggested approach: blend hps + mage scorer weighted by secondary archetype, or override
anchor_mode archetype for ARAM only.

If enchanter primary must be kept, at minimum investigate why none of the top enchanter
items (Echoes of Helia, Ardent Censer) appear in the empirical top-10 - it is possible
Bard players are not building support in ARAM and the scorer is coaching a playstyle that
does not reflect the observed winning pattern.
