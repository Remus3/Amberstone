"""DSV5 RC_COMP_HP_LEAN ground-truth probe (verify-the-premise before the flip).

Measures coach_integration.enemy_stats.compute_enemy_stats hp_scale/max_hp for:
  1. no-comp-info call (enemy_champions=None / []) with the seam ON   - the champ-select
     ds-preview/ds-knobs/ds-relscore/ds-statcheck fallback shape.
  2. the live SR enemy comp with the seam OFF vs ON                   - the in-game coach shape.
  3. an all-squishy comp with the seam ON                             - the intended 0.90 discount.

Run: python ops/audit/ds_perm_swarm/dsv5_lean_probe.py
Read-only; no engine call, no :8893, no env mutation (passes comp_hp_lean explicitly).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coach_integration.enemy_stats import compute_enemy_stats  # noqa: E402

LIVE_COMP = ["Lucian", "Sion", "Wukong", "Pantheon", "Soraka"]  # captured live 2026-06-22
SQUISHY = ["Lucian", "Caitlyn", "Lux", "Ezreal", "Jinx"]
LEVEL = 11.0


def row(label, enemy, lean):
    es = compute_enemy_stats("sr", level=LEVEL, enemy_champions=enemy, comp_hp_lean=lean)
    print(f"  {label:<34} lean={str(lean):<5} -> max_hp={es.max_hp:>7}  "
          f"hp_scale={es.hp_scale:<6} tanky_count={es.tanky_count}")
    return es


def main():
    print(f"DSV5 RC_COMP_HP_LEAN probe (level={LEVEL}, sr)")
    print("\n[1] no-comp-info (champ-select/preview fallback shape):")
    n_off = row("enemy=None", None, False)
    n_on = row("enemy=None", None, True)
    e_off = row("enemy=[]", [], False)
    e_on = row("enemy=[]", [], True)

    print(f"\n[2] live SR comp (in-game coach shape) {LIVE_COMP}:")
    c_off = row("live comp", LIVE_COMP, False)
    c_on = row("live comp", LIVE_COMP, True)

    print(f"\n[3] all-squishy comp {SQUISHY}:")
    s_off = row("squishy comp", SQUISHY, False)
    s_on = row("squishy comp", SQUISHY, True)

    print("\nFINDINGS:")
    print(f"  no-info ON hp_scale       = {n_on.hp_scale}  (docstring claims 1.0; "
          f"{'MATCHES' if n_on.hp_scale == 1.0 else 'DISCREPANCY -> 0.90 discount on preview routes'})")
    print(f"  live-comp OFF->ON max_hp  = {c_off.max_hp} -> {c_on.max_hp}  "
          f"(tanky_count={c_on.tanky_count}, uplift x{round(c_on.max_hp / c_off.max_hp, 4)})")
    print(f"  squishy ON hp_scale       = {s_on.hp_scale}  (intended 0.90 all-squishy discount)")


if __name__ == "__main__":
    main()
