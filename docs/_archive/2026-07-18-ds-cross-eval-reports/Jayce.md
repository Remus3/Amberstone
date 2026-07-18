# Jayce - DS Cross-Eval Report

**Verdict: MISMATCH**
Scorer pool (Trinity Force, Heartsteel, Essence Reaver, Iceborn Gauntlet, BotRK) is entirely absent from Jayce empirical builds. Empirical staples (Muramana, Eclipse, Serylda's Grudge, Hubris) are absent from scorer top-8 or missing from grid entirely.

---

## 1. Archetype OK: true

Scorer: hybrid. Archetype: bruiser (primary), carry (secondary). Jayce is an AD caster with poke and melee combo patterns. Hybrid scorer (EHP + DPS blend, AD-weighted) is appropriate for this archetype. No axis mismatch.

Note: empirical ARAM self (n=18, baseline wr=27.8) shows no item beating baseline. Outcome_all (n=153, wr=51.0) confirms Hubris 58.3% (n=84), Serylda's Grudge 60.9% (n=69), Eclipse 52.9% (n=68) - all AD lethality items, consistent with AD axis. Archetype direction is correct.

---

## 2. Comp OK: true

Hybrid scorer has EHP component. comp_blind=false on both axes (enemy_damage_type and target_resist). Enemy damage type max_positive_shift=9 (Hollow Radiance rises 9 slots AD->AP). Dead Man's Plate falls 4 slots AP vs AD (correct - lower value vs AP-heavy comps). Target resist max_positive_shift=10 (Eclipse +10 vs tanky). Scorer is responsive as expected for a hybrid. No comp-blind defect.

---

## 3. Outcome OK: false

Evidence tier = outcome_self (n=18 >= 8). Baseline wr = 27.8.
No self items beat baseline - all empirical items wr <= 27.8. Self pool is small and low-wr; outcome_all used for pool cross-check.

Outcome_all baseline wr = 51.0. Above-baseline items in empirical data:
- Hubris (126697): n=84, wr=58.3 - NOT in scorer grid
- Serylda's Grudge (6694): n=69, wr=60.9 - NOT in scorer grid
- Eclipse (6692): n=68, wr=52.9 - appears at rank 11 in ad_tanky/ap_tanky only, absent from top-8
- Mercury's Treads (3111): n=23, wr=60.9 - NOT in scorer grid
- Long Sword (1036): n=24, wr=54.2 - NOT in scorer grid

Scorer top-8 (ad_squishy): Void Immolation (223069), Trinity Force (3078), Heartsteel (3084), Essence Reaver (3508), Dusk and Dawn (2510), Iceborn Gauntlet (6662), BotRK (3153), Dead Man's Plate (3742).

Of these, Muramana (3042) - Jayce's near-universal build item (n=18/18 in self, n=132/153 in all) - is completely absent from the comp grid. Trinity Force, Heartsteel, Essence Reaver, Iceborn Gauntlet, BotRK have zero empirical representation in the data. Scorer is recommending an off-meta fighter/bruiser item pool for a champion that actually builds lethality (Eclipse, Serylda's, Hubris, Muramana).

**Flag: scorer top-8 is entirely absent from empirical builds; empirical high-wr staples absent from scorer pool (Muramana missing from grid entirely).**

---

## 4. Rune OK: n/a

rune_relevant=false.

---

## Nominated Retune

Add Muramana (3042), Hubris (126697), Serylda's Grudge (6694) to Jayce's item pool in the DS registry. Audit why Trinity Force, Heartsteel, and Iceborn Gauntlet score so highly for Jayce - these are likely misfires from bruiser archetype passive benefits that do not match Jayce's actual kit usage pattern (poke/ability-spam lethality build, not AA-heavy bruiser). Consider whether bruiser primary archetype is correct given the lethality-dominant empirical build pattern, or whether the pool should be manually curated to exclude items with zero empirical representation.
