# TwistedFate DS Scorer Cross-Eval

**Verdict: MINOR**

Archetype: mage/carry, scorer: ability (AP axis). Pool gap - Luden's Echo is the #1
empirical above-baseline item but absent from scorer top-8. Rabadon's Deathcap ranks
scorer #4 yet wins at only 43.2% ARAM (well below 55.8% baseline).

---

## Axis 1 - archetype_ok: TRUE

Archetype primary=mage, secondary=carry, scorer=ability. Mage -> AP axis. Kit confirmed:
AP stacked-spell damage (cards Q/W/E + R all AP-scaling). Empirical ARAM all (n=147,
baseline 55.8%): top items are Luden's Echo, Sorcerer's Shoes, Lich Bane, Rapid
Firecannon - all AP/hybrid. Scorer AP axis matches kit and empirical profile. No axis
mismatch.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability uses target_resist as primary axis. responsiveness.target_resist:
max_positive_shift=7, comp_blind=false. Bloodletter's Curse rises +7 rank positions vs
tanky, Void Staff +2, Cryptbloom +2 - scorer responds correctly to high-MR targets.
responsiveness.enemy_damage_type: max_positive_shift=0, comp_blind=true - no shift on
enemy AD/AP mix. This is expected for a pure AP damage dealer whose kit does not change
regardless of whether enemies deal AD or AP. Overall comp responsiveness is structurally
correct for this scorer type.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Evidence tier ARAM = outcome_all (self n=6, too small). ARAM all: n=147, baseline 55.8%.

Scorer top-8 (ad_squishy = bal_squishy, both identical):
  rank 1 Liandry's Torment (no empirical data)
  rank 2 Wooglet's Witchcap (no empirical data)
  rank 3 Blackfire Torch (no empirical data)
  rank 4 Rabadon's Deathcap - empirical wr 43.2%, well BELOW 55.8% baseline
  rank 5 Shadowflame - empirical wr 50.0%, below baseline
  rank 6 Void Staff (no empirical data)
  rank 7 Stormsurge - empirical wr 47.8%, below baseline
  rank 8 Cryptbloom (no empirical data)

Empirical items above baseline (55.8%):
  Luden's Echo: wr 55.9%, n=102 - ABSENT from scorer top-8 (pool miss)
  Sorcerer's Shoes: wr 55.0% - below baseline, boots not expected in scorer pool

Rabadon's Deathcap scoring at rank 4 while winning at 43.2% is an overvaluation signal.
Luden's Echo at n=102 with 55.9% wr being completely absent from scorer top-8 is the
primary pool gap. Lich Bane (53.0%) and Rapid Firecannon (53.2%) are both below baseline
so their absence from top-8 is less critical, but they represent the actual empirical
build pattern (poke burst + auto-reset playstyle).

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo to TwistedFate ability scorer item pool with appropriate AP burst
weighting. Review Rabadon's Deathcap scoring weight - currently over-ranked vs its 43.2%
empirical wr. Lich Bane and Rapid Firecannon scoring weight review warranted given they
represent the dominant empirical build pattern.
