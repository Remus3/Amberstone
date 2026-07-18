# DS Cross-Eval: Aphelios

VERDICT: MISMATCH

Scorer: dps | Archetype: carry (secondary: bruiser) | Anchor: ARAM | Evidence tier (ARAM): outcome_self (n=22)

---

## Axis 1: archetype_ok - PASS

Aphelios is an AD marksman. Kit is entirely auto-attack and physical-damage-based gun autos (Calibrum, Severum, Gravitum, Infernum, Crescendum). dps scorer on the AD/carry axis is correct. Secondary bruiser tag is unusual but not the primary concern here.

archetype_ok: true

---

## Axis 2: comp_ok - FAIL

Scorer is dps. A dps scorer MUST respond to target_resist (tanky vs squishy enemies should shift recommendations toward armor-pen items). The responsiveness block shows:

- primary_axis: target_resist
- target_resist.max_positive_shift: 0
- target_resist.comp_blind: true
- enemy_damage_type.max_positive_shift: 0
- enemy_damage_type.comp_blind: true

Both axes are fully comp-blind. This is a DEFECT: a dps scorer that cannot distinguish ad_squishy from ad_tanky or ap_tanky enemies will never recommend Lord Dominik's Regards or armor-pen items preferentially. The comp grid confirms: every item across all 5 comp cells scores 0.0 with d_dps=0.0. The scorer is producing zero output entirely.

comp_ok: false

---

## Axis 3: outcome_ok - FAIL

Evidence source: ARAM outcome_self (n=22 >= 8). Baseline wr: 54.5%.

Above-baseline empirical items (wr > 54.5%):
- The Collector (id 6676): n=11, wr=81.8%
- Runaan's Hurricane (id 3085): n=9, wr=66.7%
- Lord Dominik's Regards (id 3036): n=6, wr=66.7%
- Infinity Edge (id 3031): n=15, wr=60.0%
- Berserker's Greaves (id 3006): n=19, wr=57.9%

Scorer top-8 across all comp cells (all score 0.0):
rank 1: Doran's Shield (1054)
rank 2: Doran's Blade (1055)
rank 3: Doran's Ring (1056)
rank 4: Doran's Bow (1086)
rank 5: Doran's Helm (1120)
rank 6: Rite of Ruin (123430)
rank 7: Sword of Blossoming Dawn (124011)
rank 8: Hubris (126697)

Zero overlap between scorer top-8 and empirically winning items. None of The Collector, Runaan's Hurricane, Lord Dominik's Regards, Infinity Edge, or Berserker's Greaves appear in the scorer pool output. The entire scorer output is zeroed out - this is a complete pool/scoring engine failure for Aphelios, not just a pool-gap.

outcome_ok: false

---

## Axis 4: rune_ok - N/A

rune_relevant: false

---

## Nominated Retune

Investigate why the dps scorer produces all-zero scores for Aphelios across every comp cell. The zeroed d_dps/d_ehp/score values suggest a data-registration failure (Aphelios may be missing from the dps scorer's champion registry, or its base-stat / attack-damage profile is not resolving). Once scoring output is non-zero, verify target_resist responsiveness: the dps scorer must shift armor-pen items (Lord Dominik's Regards 3036, Last Whisper 3035) upward vs tanky-armor enemy comps. Expected top-8 pool after fix should include The Collector, Runaan's Hurricane, Infinity Edge, Berserker's Greaves.

nominated_retune: "Fix all-zero dps scorer output for Aphelios (registration/base-stat failure); then verify target_resist shifts armor-pen items vs tanky comps"
