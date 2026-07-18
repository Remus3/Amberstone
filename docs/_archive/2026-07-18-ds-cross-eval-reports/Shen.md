# DS Cross-Eval: Shen

**VERDICT: MINOR**
Scorer (ehp/tank) axis is correct. Comp responsiveness is working. Pool has gaps: Titanic Hydra
absent despite 52.4% wr (n=21); Sunfire Aegis (scorer rank 8, empirical 42.1% wr),
Unending Despair (scorer rank 4, empirical 44.7% wr), and Randuin's Omen (scorer rank 2,
absent from empirical top-10) all land below the 48.1% ARAM baseline.

---

## 1. Archetype OK: true

scorer=ehp, archetype=tank/bruiser. Tank -> ehp is the correct neutral axis. Shen kit is
pure engage tank (Ki Barrier shield, Spirit's Refuge block, global Stand United ult, Twilight
Assault taunt). No meaningful AP scaling. Empirical above-baseline ARAM items (baseline 48.1%,
outcome_all n=106): Heartsteel 54.0% (n=87), Warmog's 58.5% (n=41), Giant's Belt 57.9% (n=19),
Ruby Crystal 57.1% (n=14), Titanic Hydra 52.4% (n=21), Mercury's Treads 52.1% (n=71). All are
HP-stack/tank items -> consistent with ehp scorer axis.

---

## 2. Comp OK: true

scorer=ehp -> enemy_damage_type MUST move (comp_blind=false required, and it is false).
max_positive_shift=27 (Abyssal Mask +27, Hollow Radiance +23, Kaenic Rookern +22,
Force of Nature +22, Spirit Visage +21 when AP). Fallers when AP: Iceborn Gauntlet -28,
Dead Man's Plate -25, Randuin's Omen -25. Grid confirms: ad_squishy has Randuin's rank 2
(1819), Dead Man's Plate rank 5 (1488); ap_squishy has Kaenic rank 2 (1944),
Force of Nature rank 3 (1520), Spirit Visage rank 5 (1435). Responsiveness is real and correct.
target_resist is comp_blind (max_positive_shift=0) but that is expected for an ehp scorer
on a tank - target resist is not the primary axis.

---

## 3. Outcome OK: false

Using outcome_all (self n=0). Baseline wr=48.1% (ARAM, n=106).

Above-baseline empirical items and scorer presence:
- Heartsteel 54.0% (n=87): scorer rank 6 (ad_squishy), rank 5 (bal), rank 7 (ap). PRESENT.
- Warmog's 58.5% (n=41): scorer rank 3 (ad), rank 2 (bal), rank 4 (ap). PRESENT.
- Titanic Hydra 52.4% (n=21): NOT in scorer top-12 any cell. POOL GAP.
- Mercury's Treads 52.1% (n=71): boots, not in item scorer pool. Acceptable absence.
- Giant's Belt 57.9% (n=19): component/starter item. Acceptable absence.
- Ruby Crystal 57.1% (n=14): component. Acceptable absence.

Scorer top-8 items in ad_squishy/bal_squishy vs empirical wr:
- Void Immolation rank 1 both: not in empirical top-10 (small n or not completed). Uncertain.
- Randuin's Omen rank 2 (ad, score 1819): ABSENT from empirical top-10. Below-baseline signal.
- Unending Despair rank 4 (ad, score 1508): empirical 44.7% (n=47). BELOW BASELINE.
- Sunfire Aegis rank 8 (ad, score 1405): empirical 42.1% (n=19). BELOW BASELINE.
- Dead Man's Plate rank 5 (ad, score 1488): ABSENT from empirical top-10.

Heartsteel and Warmog's both present and winning - the HP-stack core is correct. But three
scorer-prominent items (Unending Despair, Sunfire Aegis, Randuin's Omen) are either below
baseline or absent empirically, and Titanic Hydra (above-baseline winner) is missing from pool.

---

## 4. Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

1. Add Titanic Hydra to Shen's scorer pool. It is a known Shen staple (HP-stack + cleave),
   empirically 52.4% wr (n=21, above 48.1% baseline), and absent from all comp cells.
2. Audit Unending Despair, Sunfire Aegis, and Randuin's Omen scoring weights for Shen.
   All three appear in scorer top-8 (AD cells) but underperform empirically (42-45% wr or
   absent). Likely over-rewarded by raw-EHP math that does not account for Shen's passive
   (Ki Barrier uses ability damage to scale shield, not armor stacking).
   Possible fix: check whether Shen's passive shield credit is applied correctly in ehp
   numerator, and whether armor-stacking items (Randuin's, Sunfire) are over-credited
   relative to HP items for this champ.
