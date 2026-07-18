# Vladimir - DS Scorer Cross-Eval

## Verdict: MINOR

Scorer: ability | Archetype: mage/bruiser | Evidence: ARAM=outcome_all(n=93,wr=45.2) SR=outcome_self(n=125,wr=61.6)

---

## Axis 1 - archetype_ok: TRUE

Primary=mage, scorer=ability (AP axis). Vladimir is pure AP - all abilities (Q/W/E/R) scale AP only, no AD scaling. Empirical top items are uniformly AP: Riftmaker (SR wr 69.4), Rabadon's (SR wr 64.9), Cosmic Drive (SR wr 60.6), Liandry's (ARAM wr 54.1), Shadowflame (SR wr 91.3 small-n). Scorer axis = AP = correct match.

---

## Axis 2 - comp_ok: TRUE

Scorer=ability; rule: ability/mage -> target_resist should move vs tanky. Enemy damage type comp_blind=true for ability scorer - this is EXPECTED (ability scorer keys on target's resistances, not incoming damage type).

target_resist responds:
- max_positive_shift = 3 (Void Staff rank 2->... +3, Cryptbloom +3, Bloodletter's Curse +3 when target is tanky/AP)
- comp_blind=false on target_resist axis

Penetration items (Void Staff, Cryptbloom, Bloodletter's Curse) correctly rise vs tanky targets. Shadowflame/Stormsurge fall -3 vs tanky (crit-pen vs armored is expected). Responsiveness is coherent and correct for this scorer type.

---

## Axis 3 - outcome_ok: MINOR FLAG

ARAM baseline wr=45.2 (outcome_all, n=93).

Scorer top-8 (ad_squishy / bal_squishy cells): Wooglet's (rank 1), Liandry's (rank 2), Blackfire Torch (rank 3), Rabadon's (rank 4), Shadowflame (rank 5), Void Staff (rank 6), Stormsurge (rank 7), Riftmaker (rank 8).

Above-baseline ARAM empirical winners:
- Cosmic Drive: wr 47.1, n=51 - NOT in scorer top 8 (absent from pool)
- Sorcerer's Shoes: wr 50.0, n=46 - boots, not item pool
- Liandry's Torment: wr 54.1, n=37 - rank 2 scorer - PRESENT
- Spirit Visage: wr 48.4, n=31 - NOT in scorer top 8 (absent from pool)
- Zhonya's: wr 56.2, n=16 - rank 12 scorer (low n in empirical)

Cosmic Drive (n=51, wr 47.1) is the clearest gap: high-sample above-baseline ARAM winner absent from scorer top 8 in all comp cells. Spirit Visage (n=31, wr 48.4) also absent - Vladimir's W self-heal makes Spirit Visage's heal amplification genuinely valuable.

SR: SR baseline wr=61.6. Rabadon's (64.9), Riftmaker (69.4), Shadowflame (91.3 small-n) all present in scorer. Mejai's (88.9, n=27) absent but that is a snowball item, expected gap.

Pool gap is real on ARAM: Cosmic Drive missing, Spirit Visage missing.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Cosmic Drive to ability scorer pool for Vladimir (AP+HP hybrid that benefits from Vladimir's natural sustain playstyle; ARAM empirical: n=51, wr 47.1 > baseline 45.2). Evaluate Spirit Visage for inclusion as a heal-amp item that synergizes with Vladimir W passive self-heal (n=31, wr 48.4 > baseline 45.2).
