# DSP11 (kit-axis) revert gate diff - 2026-07-13

Gate artifact for `docs/specs/2026-07-13-ds-build-coherence-refactor.md` Step 0b
(the operator-gated DSP11 coach revert). READ-ONLY: no engine change, no flag
persist, no :8893 restart.

## Method

Two passes, both at the LIVE coach chokepoint (post-Step-1a):

1. First pass: `rank_for_primary_archetype` OFF vs ON, top-8, one neutral comp.
2. Tightened (operator-requested): `dispatch_for_coach` (the true coach entry ->
   picks_str), **top-5** (coach default), **real per-champ comps** (frontline-heavy
   + squishy-poke, SR L14 + ARAM L16) via `compute_enemy_stats`, plus an
   **independent `rewind_history.db` per-item WR re-query** (not the baked table).

ON = `prefer_kit_axis_by_win=True` (the C4 2026-07-04 live default).
OFF = `False` (the proposed 0b revert).

## Result (tightened, top-5, coach fidelity)

| Champ | arch | DSP11 effect (all 4 cells unless noted) | Rewind cross-ref of surfaced item(s) | Verdict |
|---|---|---|---|---|
| **Pyke** | assassin | ADD Axiom Arc #1 + Youmuu's #2; drop ER/Serylda/Sundered | Axiom 51.9%/n133, Youmuu's 55.7%/n61, Opp 61.1%/n36 - all > 50.2% base | **KEEP (strong, rewind-justified)** |
| **Corki** | carry | ADD The Collector; drop Stormrazor | Collector 47.1%/n68 vs 46.2% base (marginal +) | keep (weak-moderate) |
| **Naafiri** | assassin | ADD Hubris/Collector; drop IE/Eclipse (ARAM) | Hubris 42.9%/n28, Collector 44.4%/n27 - both <= 45.9% base | WEAK (rewind does not justify) |
| **Ezreal** | carry | reorder only (ER #4->#1); SAME item set at top-5 | ER 40.9%/n22 - well below 47.4% base (table's 56.2%/n16 was small-sample) | reorder anti-justified, low-harm (ER in build anyway via Step-1a) |
| **Quinn** | carry | INERT (identical top-5) | WIN items strong but rank below top-5 | inert |
| **Senna** | carry | INERT | Black Cleaver 55.4%/n74 strong but not surfaced | inert |
| **Nilah** | bruiser | INERT (DSP11 n/a on bruiser) | - | inert (matches spec) |

## Findings

1. **The spec 0b premise is false.** "Step 1a makes DSP11 redundant (no coverage
   gap)" holds only for CRIT ADCs (what Step 1a targets). These champs are
   lethality/assassin/manamune - Step 1a does not surface their kit-axis items.
   DSP11 OFF drops them. A blind revert = a live regression, worst for Pyke.
2. **Tightening reversed confidence on 2 entries** (the baked table lied):
   - **Ezreal ER**: table 56.2%/n16 -> fresh rewind 40.9%/n22. The n=16 anchor the
     spec flagged is a small-sample artifact; ER does not deserve promotion.
   - **Naafiri Hubris/Collector**: at/below her 45.9% baseline in fresh data.
3. **Half the table is inert** at coach fidelity (Quinn/Senna/Nilah) - revert-safe
   but pointless there.

## Recommendation

- **Do NOT execute Step 0b (DSP11 mechanism revert).** It is load-bearing +
  rewind-justified for Pyke (strong) and Corki (moderate).
- **Better action the tightening exposed:** refresh `kit_axis_item_credit.json`
  against the current `rewind_history.db` (rebuild via
  `ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py`) to drop the
  anti-justified entries (Ezreal ER, Naafiri's marginal pair) and keep the
  justified ones (Pyke, Corki). Data-only refresh, not a mechanism change.
- **Correct the spec** Status/0b premise accordingly.
