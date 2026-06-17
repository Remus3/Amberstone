## LeeSin scorer cross-eval - MISMATCH

**Verdict:** MISMATCH - comp_blind hybrid EHP scorer; outcome pool dominated by ADC items Lee Sin does not build empirically.

---

### 1. archetype_ok: TRUE

Scorer = hybrid (AD-axis). Archetype = bruiser/assassin (user_cs override). Lee Sin is a physical AD melee bruiser - AD axis is correct. No kit mismatch.

---

### 2. comp_ok: FALSE (DEFECT)

Scorer = hybrid. Primary axis = enemy_damage_type. comp_blind = TRUE.

Per rubric, a hybrid EHP scorer with comp_blind=True is a DEFECT candidate. The data confirms: max_positive_shift = 2 across the full top-40 when enemy damage flips to AP. Top risers when AP: Titanic Hydra +2, Mortal Reminder +2 - trivial rank shifts of 2 positions. The scorer does not meaningfully reorder recommendations when facing heavy AP vs heavy AD comps. An EHP-weighted scorer on a bruiser should penalize/favor items based on enemy damage type; a shift of only 2 ranks is functionally comp-blind.

Nominated fix: increase enemy_damage_type weight in hybrid scorer so AP-heavy comps surface MR items higher (e.g. Maw of Malmortius, Sterak's Gage with MR component) and deprioritize pure-phys items.

---

### 3. outcome_ok: MINOR

Evidence tier: ARAM outcome_self (n=16, baseline wr=43.8%).

Above-baseline empirical items (self):
- Mercury's Treads: wr 66.7% (n=6) - boots, scorer agnostic
- Death's Dance: wr 50.0% (n=8) - NOT in scorer top-12
- Eclipse: wr 46.2% (n=13) - scorer rank 10 (outside top-8)

Scorer top-8 (ad_squishy cell): BotRK(1), Void Immolation(2), Runaan's Hurricane(3), Trinity Force(4), Essence Reaver(5), Kraken Slayer(6), Infinity Edge(7), Stormrazor(8).

Items ranked 3-8 (Runaan's Hurricane, Essence Reaver, Kraken Slayer, Infinity Edge, Stormrazor) are crit/on-hit ADC items that do not appear in Lee Sin empirical builds at all. Eclipse (empirically wr 46.2%, the most-built item at n=13) ranks only 10th. Death's Dance (wr 50.0%, n=8) is absent from top-12 entirely.

The scorer pool is ADC-item dominated; Lee Sin's actual bruiser-pattern items (Eclipse, Death's Dance) are underranked or absent.

---

### 4. rune_ok: N/A

rune_relevant = false. Non-burst scorer. No rune assessment.

---

### Nominated retune

1. hybrid scorer: increase enemy_damage_type responsiveness weight - target max shift >= 5 for MR-granting items when AP share > 60%.
2. hybrid item pool: investigate why Eclipse (rank 10) and Death's Dance (absent) underperform vs ADC items (Runaan's, Essence Reaver) that Lee Sin never builds - likely a DPS-component over-weight pulling crit/attack-speed items up.
