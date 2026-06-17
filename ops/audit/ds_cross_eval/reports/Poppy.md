# DS Cross-Eval: Poppy

**Verdict: MINOR**

Archetype: tank (secondary bruiser) | Scorer: ehp | Anchor: ARAM
Evidence tier ARAM: outcome_self (n=13, wr=38.5)

---

## Axis 1 - archetype_ok: TRUE

tank -> ehp scorer is the correct neutral-axis pairing. Poppy's kit is pure frontline/engage
(W wall stun, E dash, R ult displacement) with no significant carry or AP-scaling elements.
No mismatch vs kit or vs empirical: top empirical items (Fimbulwinter, Heartsteel, Unending
Despair) are all tank items consistent with ehp scoring.

---

## Axis 2 - comp_ok: TRUE

scorer=ehp, primary_axis=enemy_damage_type, comp_blind=false.
The scorer is responsive: max_positive_shift=27 rank positions when enemy is AP-heavy.
Top risers vs AP: Abyssal Mask (+27), Hollow Radiance (+24), Kaenic Rookern (+22),
Spirit Visage (+22), Force of Nature (+22).
Top fallers vs AD: Iceborn Gauntlet (-28), Dead Man's Plate (-26), Sunfire Aegis (-24).
Cells differ meaningfully between ad_squishy and ap_squishy (e.g., Kaenic Rookern jumps
from absent in ad_squishy to rank 2 in ap_squishy). Not comp-blind. No defect.

target_resist axis is comp_blind (max_positive_shift=0) but that is expected for ehp -
Poppy does not scale off enemy resist, so target_resist invariance is correct behavior.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gap)

Using outcome_self (n=13 >= 8). Baseline wr=38.5.
Empirical items with wr above baseline (self):
  - Fimbulwinter: n=11, wr=45.5  -- ABSENT from scorer top-8 in all 5 comp cells
  - Unending Despair: n=7, wr=42.9 -- present (rank 4 ad_squishy, rank 8 bal_squishy)

outcome_all (n=99, wr=49.5) corroborates: Fimbulwinter 54.0 wr on n=63 -- still absent.
Thornmail 60.0 wr on n=25 -- scorer rank 9 in ad_squishy (just outside top-8).
Plated Steelcaps 59.1 wr on n=22 -- not in scorer lists (boots not in item pool).
Spirit Visage 85.7 wr on n=14 -- present in MR cells (rank 4-8 in ap/bal comps).

Flag: Fimbulwinter (id 3121) is empirically the most reliable above-baseline item
(n=11 self / n=63 all, both above baseline wr) but scores outside the top-8 in every
comp cell. The scorer does not surface it at all in the recommendation pool.
Heartsteel (rank 4-7 in scorer) posts wr=30.0 (self) / 49.3 (all) -- near-baseline,
not a losing build but not a strong pick either. Not flagging Heartsteel alone.

Pool gap severity: MINOR (not wrong-axis; one staple missing, not a systemic fail).

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Fimbulwinter (id 3121) to the ehp scorer's item pool for Poppy so it can be scored
and ranked. It builds from Sheen-line + HP components, provides mana-scaling HP amplifier
passive, and has the highest above-baseline win rate in self (45.5) and all (54.0) ARAM
data with adequate sample size. The scorer currently has no pathway to recommend it.
