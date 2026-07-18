# DS Cross-Eval: Janna

**Verdict: MINOR**
Scorer (hps / enchanter) axis is correct; comp invariance is expected. Pool gap: high-wr AP-mage build path (Tear 65.2%, Luden's Echo 60.0%) missing from scorer pool.

---

## Axis 1 - archetype_ok: TRUE

Janna archetype = enchanter/mage, scorer = hps. Enchanter -> hps is the correct axis: heal+shield throughput is the value driver. Kit confirms (W shield, passive-empowered heals, R knock + heal). No wrong-axis issue.

## Axis 2 - comp_ok: TRUE

Scorer = hps. Enchanter/hps scorers are expected to be comp-invariant: heal/shield output does not scale with enemy damage type or target resistances. All five comp cells (ad_squishy / bal_squishy / ap_squishy / ad_tanky / ap_tanky) produce identical rankings (Echoes #1 24.97, Ardent #2 16.39, Staff #3 13.08, Locket #4 11.31, Knight's Vow #5 10.00). comp_blind=true on both responsiveness axes is CORRECT behavior for hps, not a defect.

## Axis 3 - outcome_ok: FALSE (MINOR)

Using outcome_all (ARAM n=124, baseline wr=57.3%).

Above-baseline empirical items (wr > 57.3%):
- Ionian Boots of Lucidity (id 3158): 58.1% wr, n=86 - NOT in scorer pool
- Imperial Mandate (id 4005): 57.7% wr, n=78 - scorer rank 7 (present, OK)
- Redemption (id 3107): 60.9% wr, n=46 - scorer rank 6 (present, OK)
- Tear of the Goddess (id 3070): 65.2% wr, n=23 - NOT in scorer pool
- Luden's Echo (id 6655): 60.0% wr, n=20 - NOT in scorer pool

Scorer top-8 problems:
- Ardent Censer ranks #2 (score 16.39) but empirical wr = 54.5%, below baseline 57.3%.
- Staff of Flowing Water #3, Knight's Vow #5, Mikael's Blessing #8 not in empirical top-10 at all.
- Tear (65.2%) and Luden's Echo (60.0%) are high-wr wins with reasonable n that the hps scorer cannot see; they signal a viable AP-scaling mage build path.
- Ionian Boots (58.1%, n=86 - highest n of any single item) absent from scorer pool entirely.

This is a pool gap, not a wrong-axis: hps correctly ranks enchanter items but excludes the AP-mage build path Janna can win with in ARAM.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Add Tear of the Goddess, Seraph's Embrace, Luden's Echo, Dawncore, and Ionian Boots of Lucidity to the hps scorer's eligible item pool for Janna (or via a secondary mage scorer weight blended in). Tear/Seraph path wins at 65.2%/49.0% with meaningful n; Luden's at 60.0%. The enchanter pool should not be exclusive when empirical data shows AP items winning above baseline.
