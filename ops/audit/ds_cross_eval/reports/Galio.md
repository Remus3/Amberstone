# DS Cross-Eval: Galio

**Verdict: MINOR**
Scorer: ehp | Archetype: tank/mage | Evidence: outcome_all (ARAM, n=95, baseline wr=58.9%)

---

## Axis 1 - archetype_ok: PASS

tank is scorer-neutral; ehp is the correct axis. No mismatch.

---

## Axis 2 - comp_ok: PASS

ehp scorer is expected to respond to enemy damage type, and it does:
- comp_blind=false at top level and enemy_damage_type level
- max_positive_shift=29 rank positions when enemy team is AP-heavy
- MR items rise correctly: Abyssal Mask +29, Spirit Visage +25, Force of Nature +25,
  Kaenic Rookern +22, Hollow Radiance +22
- Armor items fall correctly: Dead Man's Plate -27, Iceborn Gauntlet -27, Sunfire Aegis -25,
  Randuin's Omen -23

target_resist.comp_blind=true with shift=0 is expected - Galio does not deal physical/magic damage
in a way that depends on enemy resistances, so the ehp scorer ignoring target resist is correct.

---

## Axis 3 - outcome_ok: MINOR FLAG

ARAM empirical baseline wr=58.9% (n=95 games, using outcome_all per evidence_tier).

Items above baseline wr (>58.9%):
  Fimbulwinter    n=44 wr=61.4%  - ABSENT from all scorer cells (top-8)
  Plated Steelcaps n=39 wr=61.5% - ABSENT from all scorer cells
  Heartsteel      n=39 wr=64.1%  - present (rank 9 ad/ad_tanky, rank 5 bal_squishy, rank 9 ap cells)
  Hollow Radiance n=37 wr=62.2%  - present (rank 8 ap_squishy/ap_tanky)
  Unending Despair n=23 wr=60.9% - present (rank 4 ad_squishy/ad_tanky, rank 8 bal_squishy)
  Riftmaker       n=18 wr=61.1%  - absent (AP/omnivamp item; absence acceptable for pure EHP scorer)
  Tear of Goddess n=14 wr=64.3%  - absent (component, not a completed item)

Primary pool gap: Fimbulwinter (id=3121) is the most-purchased item in the sample (n=44) with
above-baseline wr (61.4%) and is completely absent from all 5 scorer cell top-8 lists. It is a
tank-appropriate HP+mana shield item that Galio's secondary mage profile naturally builds.

Secondary gap: Plated Steelcaps (id=3047, n=39, wr=61.5%) absent. Boots are sometimes excluded
from scorer pools by design, but worth noting.

Scorer top-8 (ad_squishy) items not in empirical top-10 at all: Void Immolation (#1 rank,
score=4254) has zero empirical appearances - likely only available in specific ARAM pots; its
dominance at rank 1 with no empirical grounding is a separate calibration note.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter (id=3121) to the EHP item pool for Galio. It is a high-HP mana-shield defensive
item consistent with tank/mage profile, is the single most-purchased item in the ARAM sample
(n=44), and wins at 61.4% vs 58.9% baseline. Its absence from all scorer cells is the primary
actionable gap.

Secondary: verify whether Plated Steelcaps and boots-class items are intentionally excluded from
the pool or just missing.
