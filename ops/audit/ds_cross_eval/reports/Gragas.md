# DS Cross-Eval: Gragas

**Verdict: MINOR**
Archetype + comp responsiveness aligned; scorer pool misses Cosmic Drive (65.0% ARAM wr, n=20) and Luden's Echo (53.3%, n=30).

---

## Axis 1 - archetype_ok: PASS

- Primary archetype: mage; secondary: bruiser; scorer: ability (AP axis). Correct.
- Gragas kit is fully AP: all damaging abilities deal magic damage. AP scorer axis matches kit.
- Empirical ARAM above-baseline (>52.3%) AP items dominate: Rod of Ages 60.0% (n=35), Cosmic Drive 65.0% (n=20), Stormsurge 61.9% (n=21), Shadowflame 58.6% (n=29), Rabadon's 56.0% (n=25). No AD staples in high-wr pool.
- archetype_ok = true

---

## Axis 2 - comp_ok: MINOR FLAG

- Scorer = ability; primary_axis = target_resist. Expected behavior for an ability scorer.
- target_resist responsive: max_positive_shift=3, comp_blind=false. Bloodletter's Curse +3, Void Staff +2, Cryptbloom +2 vs AP-tanky. Correct.
- enemy_damage_type.comp_blind = true. max_positive_shift=0, no risers or fallers. The scorer produces identical rankings regardless of whether enemies are AD-heavy or AP-heavy.
- For a pure damage-output (ability) scorer this is less severe than for an EHP scorer, but it means the engine gives no signal on whether Banshee's Veil or Zhonya's becomes higher priority when enemies are AP. The top-level comp_blind=false only because target_resist moves; the damage-type sub-axis is fully blind.
- comp_ok = minor concern, not a MISMATCH-grade EHP comp-blind defect

---

## Axis 3 - outcome_ok: FAIL (pool gap)

Evidence: ARAM outcome_all, n=107, baseline wr=52.3%.

Scorer top-8 (ad_squishy cell):
  #1 Wooglet's Witchcap   - absent from empirical top-10
  #2 Liandry's Torment    - absent from empirical top-10
  #3 Blackfire Torch      - absent from empirical top-10
  #4 Rabadon's Deathcap   - YES wr=56.0% (n=25), above baseline
  #5 Void Staff           - absent from empirical top-10
  #6 Shadowflame          - YES wr=58.6% (n=29), above baseline
  #7 Stormsurge           - YES wr=61.9% (n=21), above baseline
  #8 Cryptbloom           - absent from empirical top-10

High-wr empirical items absent from scorer pool (top-12):
  Cosmic Drive   wr=65.0% n=20 - NOT in scorer top-12 at all
  Rod of Ages    wr=60.0% n=35 - scorer rank #9 (just outside top-8)
  Luden's Echo   wr=53.3% n=30 - NOT in scorer top-12 at all
  Fimbulwinter   wr=52.8% n=36 - NOT in scorer top-12 at all

Cosmic Drive is the single highest ARAM win-rate item (65.0%) with meaningful sample (n=20) and is completely absent from the scorer pool. Luden's Echo (n=30) also absent.

The scorer items that ARE present do win (Shadowflame, Stormsurge, Rabadon's all above baseline), so the pool is not actively recommending losers - but the coverage miss on Cosmic Drive is significant.

outcome_ok = false

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Cosmic Drive (4629) and Luden's Echo (6655) to the ability scorer item candidate pool for Gragas. Rod of Ages (6657) is already in pool at rank #9; consider promoting it within top-8 given 60% wr (n=35). Wooglet's Witchcap dominates scorer rank #1 but is absent from empirical data - verify if it is an ARAM-unavailable item or just rarely built.
