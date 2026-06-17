# DS Cross-Eval: Cassiopeia

**VERDICT: MINOR**

Scorer: ability (mage/AP axis). archetype_ok=true, comp_ok=true, outcome_ok=false (pool gap), rune_ok=n/a.

---

## Axis 1 - archetype_ok: TRUE

primary=mage, scorer=ability -> AP axis. Correct for kit: sustained AP damage via Twin Fang spam + poison.

Empirical ARAM all (n=80, baseline wr=48.8%): above-baseline items are all AP:
- Liandry's Torment 58.1% (n=62)
- Blackfire Torch 53.8% (n=13)
- Rabadon's Deathcap 54.5% (n=11)
- Seraph's Embrace 53.4% (n=58)
- Rylai's Crystal Scepter 53.3% (n=45)

No AD/hybrid items in the above-baseline set. Axis confirmed.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability. primary_axis=target_resist.

- target_resist: comp_blind=false, max_positive_shift=+5. Risers vs AP tanky: Bloodletter's Curse +5, Void Staff +3, Cryptbloom +2. Correct responsiveness for an AP DPS scorer: pen items promote when facing tanky.
- enemy_damage_type: comp_blind=true (max_positive_shift=0, no risers/fallers). For a mage/ability scorer this is expected - survivability item selection is not part of the ability scorer's primary logic. Not a defect.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Using ARAM all (n=80 >= 8, baseline wr=48.8%).

Scorer top-8 (bal_squishy): Wooglet's (r1 57.14), Liandry's (r2 34.24), Blackfire Torch (r3 24.56), Rabadon's (r4 21.46), Shadowflame (r5 19.52), Void Staff (r6 19.46), Stormsurge (r7 16.70), Cryptbloom (r8 14.58).

Empirical above-baseline items vs scorer top-8:
- Liandry's (emp wr 58.1%): scorer r2 - ALIGNED
- Blackfire Torch (emp wr 53.8%): scorer r3 - ALIGNED
- Rabadon's (emp wr 54.5%): scorer r4 - ALIGNED
- Seraph's Embrace (emp wr 53.4%, n=58): NOT in scorer top-8 - POOL GAP (3rd most-built empirically, above baseline)
- Rylai's Crystal Scepter (emp wr 53.3%, n=45): NOT in scorer top-8 - POOL GAP (4th most-built empirically, above baseline)
- Wooglet's Witchcap: scorer r1 but absent from empirical list (low n, likely ARAM-specific item; not penalized but unvalidated)
- Shadowflame, Void Staff, Stormsurge, Cryptbloom: scorer r5-r8, absent from empirical list - neutral (low n in data)

Two high-volume empirical staples beat the baseline and are missing from the scorer's top-8 recommendation pool.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Seraph's Embrace (emp wr 53.4%, n=58) and Rylai's Crystal Scepter (emp wr 53.3%, n=45) are both above baseline and represent the 3rd/4th most-built items empirically but do not appear in scorer top-8.

Likely cause: ability scorer underweights mana-scaling value (Seraph's large mana+AP contribution via Archangel synergy) and utility/slow-amplifier value (Rylai's slows synergize with Cassiopeia's poison uptime but are not ability-damage items in the scorer's model).

Retune candidate: add mana-scaling bonus weight in ability scorer for sustained-damage mages (AP primary + high mana usage pattern), and consider a slow/utility multiplier for AP mages with high-AP-ratio abilities. This would lift both items into the recommended range.
