# Orianna - DS Scorer Cross-Eval Verdict

**Severity: MINOR**
**Scorer: ability (mage/AP axis)**
**Evidence tier (ARAM): outcome_self (n=57, baseline wr=49.1%)**

---

## Axis 1 - archetype_ok: TRUE

Mage primary / enchanter secondary -> ability scorer is the correct AP axis.
Orianna's full kit (Q/W/E/R) is AP-scaling ability damage; no AA reliance.
Empirical confirmation: above-baseline items in ARAM self are all AP items
(Stormsurge wr=62.5, Blackfire Torch wr=55.6, Needlessly Large Rod wr=57.1).
No AD build pattern present. Axis correct.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability -> target_resist responsiveness expected, enemy_damage_type
invariance expected.

- target_resist: comp_blind=false, max_positive_shift=3.
  Risers vs ap_tanky: Bloodletter's Curse +3, Cryptbloom +2, Void Staff +1,
  Liandry's +1. Penetration/shred items rise correctly vs armor/MR tanks.
  Fallers: Shadowflame -2 (crit-pen less useful vs tank), Stormsurge -2.
  Responsiveness is meaningful and directionally correct.

- enemy_damage_type: comp_blind=true, max_positive_shift=0, no risers/fallers.
  Ability scorer does not gate on enemy damage mix. This is expected behavior,
  not a defect.

Top-level comp_blind=false (target_resist axis drives differentiation).

---

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=57 >= 8). Baseline wr=49.1%.

Above-baseline empirical items (self):
- Stormsurge n=24 wr=62.5 -> scorer rank 7 ad_squishy (IN pool, ok)
- Needlessly Large Rod n=14 wr=57.1 -> NOT in scorer pool (component item,
  plausible exclusion, but empirically winning)
- Blackfire Torch n=9 wr=55.6 -> scorer rank 3 (IN pool, ok)

Pool gap flags:
- Luden's Echo (id=6655): most-built item in ARAM self (n=43, wr=46.5, just
  under baseline) and ARAM all (n=105, wr=41.9) - ABSENT from scorer pool
  entirely. The #1 built item for Orianna is not in the ability scorer pool.
- Seraph's Embrace (id=3040): ARAM all n=35 wr=57.1 (above all baseline
  47.0%) - ABSENT from scorer pool.
- Malignance (id=3118): ARAM all n=44 wr=50.0 (above all baseline) - ABSENT
  from scorer pool.

Three relevant items with meaningful empirical volume and above-baseline wr
are outside the scorer pool. Luden's Echo in particular as the single
highest-n item for this champion represents the worst gap.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Luden's Echo (6655), Seraph's Embrace (3040), and Malignance (3118) to
the ability scorer item pool for Orianna. Luden's is the highest priority
(n=43 most-built, absent entirely). Seraph's and Malignance are above-baseline
in the larger all-player sample and also absent.
