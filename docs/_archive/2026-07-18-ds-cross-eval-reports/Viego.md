# Viego DS Scorer Cross-Eval Verdict

**Champion:** Viego
**Scorer:** hybrid
**Archetype:** bruiser / assassin
**Anchor mode:** ARAM
**Evidence tier (ARAM):** outcome_self (n=9)
**Severity:** MINOR

---

## Verdict

MINOR - scorer axis and comp-responsiveness are correct; pool has 3 above-baseline empirical
staples absent from the top 8, and Manamune + Runaan's are over-ranked vs empirical signal.

---

## Axis 1 - archetype_ok: TRUE

Viego is an AD melee bruiser/assassin. Hybrid scorer blends dps and ehp on the AD axis -
correct. No AP items appear in kit, no AP empirical signal.

Empirical check (ARAM outcome_self n=9 >= 8, baseline wr=44.4%): Trinity Force wr=57.1%
appears at scorer rank 4 in ad_squishy - aligned.

---

## Axis 2 - comp_ok: TRUE

Scorer = hybrid (ehp + dps blend). comp_blind=false on both axes. EHP component responds to
enemy_damage_type (max_positive_shift=12, Wit's End rises 12 ranks when enemy is AP). DPS
component responds to target_resist (max_positive_shift=23, Liandry's rises 23 when enemies
are tanky). Both axes are live; no DEFECT. Responsiveness on enemy_damage_type is moderate
(only Wit's End has a double-digit shift; most other risers move 2 ranks) but the signal is
present and non-zero.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gaps)

ARAM outcome_self baseline wr=44.4%, n=9. outcome_all baseline wr=39.7%, n=116 (used for
broader item coverage since self has only 1 item entry).

Scorer top 8 (ad_squishy): Void Immolation (#1), Manamune (#2), BotRK (#3), Trinity Force
(#4), Runaan's Hurricane (#5), Kraken Slayer (#6), Heartsteel (#7), Essence Reaver (#8).

Above-baseline empirical items ABSENT from scorer top 8:
- Sundered Sky (6610): n=81, wr=43.2% (above 39.7%) - most-built item, not in top 8
- Death's Dance (6333): n=43, wr=44.2% (above 39.7%) - not in top 8
- Wit's End (3091): n=15, wr=53.3% (highest ARAM wr, well above baseline) - not in top 8

Scorer top-8 items absent or weak empirically:
- Manamune (#2 scorer): not in empirical top-10 items at all
- Runaan's Hurricane (#5 scorer): not in empirical top-10 items at all
- Void Immolation (#1 scorer): not in empirical items (likely too expensive/rare in n=116)

These are pool gaps, not a wrong-axis problem. Severity = MINOR.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Investigate why Sundered Sky, Death's Dance, and Wit's End score outside the top 8 for Viego
in the hybrid scorer. Sundered Sky is the most-built item (n=81) with above-baseline wr and
Wit's End has the highest ARAM wr (53.3%) - both should compete for top-8 placement.
Manamune (#2) and Runaan's Hurricane (#5) appear over-ranked relative to empirical prevalence
and win-rate signal.

Proposed retune: audit hybrid dps/ehp weight for Viego's passive-reset playstyle where
on-hit / proc items (Wit's End) and sustain/survivability items (Death's Dance, Sundered Sky)
are systematically under-valued vs raw stat-stick items.
