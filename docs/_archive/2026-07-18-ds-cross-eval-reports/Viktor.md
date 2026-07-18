# Viktor - DS Scorer Cross-Eval Verdict

**Verdict: OK**
Scorer: ability | Archetype: mage (primary) / assassin (secondary) | ARAM evidence tier: outcome_self (n=14)

---

## Axis 1 - archetype_ok: PASS

Scorer = ability. Rule: mage/enchanter -> AP axis. Viktor is a pure AP mage; every ability (Q/W/E/R) deals AP magic damage. AP axis is correct.

Empirical check (ARAM self, n=14 >= 8, baseline wr=50.0): above-baseline items are Liandry's Torment (wr 60.0) and Shadowflame (wr 57.1). Both are AP mage items. No AD or hybrid-damage item with above-baseline wr contradicts the AP ability axis. Archetype aligned.

---

## Axis 2 - comp_ok: PASS

Scorer = ability (pure-offense AP mage). Primary axis = target_resist.

target_resist.comp_blind = false. max_positive_shift = +6. Top risers vs tanky/AP-resist enemies: Bloodletter's Curse (+6), Void Staff (+3), Cryptbloom (+2). Meaningful rank movement when facing high-MR targets - correct behavior for a mage scorer.

enemy_damage_type.comp_blind = true (max_positive_shift = 0). This is EXPECTED for a pure-offense scorer. Viktor does not weight defensive items based on whether enemies deal AD or AP, so no EHP-driven shift on that axis is correct. Not a defect.

---

## Axis 3 - outcome_ok: PASS

Using ARAM self (n=14, baseline wr=50.0). Above-baseline empirical items: Liandry's Torment (wr 60.0, self rank n=10), Shadowflame (wr 57.1, n=7).

Scorer top-8 (ad_squishy cell): Wooglet's (1), Liandry's (2), Blackfire Torch (3), Rabadon's (4), Shadowflame (5), Void Staff (6), Stormsurge (7), Cryptbloom (8).

Both above-baseline empirical items (Liandry's rank 2, Shadowflame rank 5) are in the scorer top-8. No empirical above-baseline staple is absent.

Wooglet's Witchcap at rank 1 does not appear in empirical self data - likely sample-size limited (n=14 total, gold 6000 ARAM item rarely completed in small sample). Not a clear defect.

Lich Bane appears in empirical all (n=43, wr 53.5, above all-baseline 50.3) but is absent from scorer top-8. However evidence_tier for ARAM is outcome_self and Lich Bane does not appear in self items - this is a minor pool signal at most, not a top-8 miss under the primary evidence tier.

---

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Summary

All four axes pass. The ability scorer correctly places Liandry's and Shadowflame in the empirical winning zone (top-5). Target-resist responsiveness is healthy (+6 max shift). Enemy-damage-type blindness is expected for a pure-offense scorer. No retune nominated.

**Nominated retune: none**
