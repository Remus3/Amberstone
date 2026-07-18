# Taric DS Scorer Cross-Eval

**Verdict: MISMATCH**

Scorer: hps | Archetype: enchanter (primary) / tank (secondary) | Evidence: outcome_all (ARAM n=36, wr=58.3%)

---

## Axis 1 - archetype_ok: FAIL

hps scorer maps to enchanter (AP axis). Taric heals/shields do scale with AP so the axis is kit-defensible. However empirical winning builds (outcome_all, n=36) are entirely tank items - Fimbulwinter(n=33,wr=57.6%), Mercury's Treads(n=27,wr=55.6%), Heartsteel(n=17,wr=52.9%), Spirit Visage(n=11,wr=63.6%), Unending Despair(n=11,wr=72.7%), Thornmail(n=10,wr=60.0%), Plated Steelcaps(n=8,wr=62.5%), Guardian's Horn(n=6,wr=66.7%). None of the hps scorer's enchanter pool items appear empirically. The enchanter axis does not reflect how Taric is played or wins in ARAM.

## Axis 2 - comp_ok: PASS

hps/enchanter scorer expects comp invariance. responsiveness.comp_blind=true and all 5 comp cells return identical rankings (Echoes of Helia r1=26.548 in every cell, d_ehp=0.0 throughout). Comp blindness is the expected and correct behavior for this scorer type. No defect.

## Axis 3 - outcome_ok: FAIL

Using outcome_all (self.n=0 < 8). Baseline wr=58.3%. Above-baseline empirical items (wr > 58.3%): Unending Despair(72.7%), Guardian's Horn(66.7%), Spirit Visage(63.6%), Plated Steelcaps(62.5%), Thornmail(60.0%). Scorer top-8: Echoes of Helia(r1), Ardent Censer(r2), Staff of Flowing Water(r3), Locket of the Iron Solari(r4), Knight's Vow(r5), Redemption(r6), Imperial Mandate(r7), Mikael's Blessing(r8). Overlap = 0. Moonstone Renewer (r9) scores 0.0 and is also absent empirically. The five above-baseline empirical staples are all tank items not present in scorer pool. Critical gap: Unending Despair(72.7%) and Spirit Visage(63.6%) are the strongest performers and are invisible to the scorer.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Taric plays as a tank-support in ARAM, not a traditional enchanter. The hps scorer should either: (a) add Fimbulwinter, Heartsteel, Spirit Visage, Unending Despair, Thornmail, and Plated Steelcaps to the hps item pool with tank-hybrid scoring weights, or (b) route Taric through the tank scorer as primary (secondary=enchanter) to surface the empirically winning build path. The enchanter-only pool misses the entire winning item set. Recommend archetype flip to tank primary + hps secondary weighting, or a blended enchanter/tank pool.
