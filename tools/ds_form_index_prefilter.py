"""DS form_index coverage pre-filter (Phase 5.9.x batch tooling).

The form_index registry (`champion_form_index.json`) selects WHICH form
of a multi-form ability the engine evaluates; default is form 0. Far
less scrutinized than block_index (~9 champs vs block_index's 25+
batches). This pre-filter, for every multi-DAMAGE-form (champion, key)
NOT already in the form_index registry, runs ground-truth A/B
`compute_ability_dps` forced to form 0 vs each later form, and prints
the ratio + each form's name so the operator/agent can judge whether a
later form is the canonical operator-commit form (cougar, cannon,
spider, empowered-recast ...) the engine is wrongly defaulting away from.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_form_index_prefilter.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.daemon_slayer.abilities import load_default as load_abilities
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot

LVL = 11
ARMOR, MR, HP = 80.0, 30.0, 2000.0


def _ab(snap, champ, key, form_idx, hp_pct=1.0):
    out = compute_ability_dps(
        snap, champ, level=LVL, item_ids=[], mode="SR",
        target_armor=ARMOR, target_mr=MR, target_max_hp=HP,
        target_current_hp_pct=hp_pct,
        form_index_overrides={key: form_idx},
    )
    s = next((p for p in out.per_spell if p.key == key), None)
    return s.raw_damage_per_cast if s else 0.0


def main() -> int:
    snap = DataSnapshot.load()
    reset_block_index_cache()
    reset_form_index_cache()
    reg = json.loads(
        Path("agents/daemon_slayer/champion_form_index.json")
        .read_text(encoding="utf-8")
    )["champions"]
    asnap = load_abilities()

    rows: list[tuple] = []
    for champ in sorted(asnap.champions):
        mapped = {k.upper() for k in reg.get(champ, {})}
        for key in ("Q", "W", "E", "R"):
            if key in mapped:
                continue
            forms = asnap.champions[champ].get(key) or ()
            dmgforms = [f for f in forms if f.damage_blocks_only()]
            if len(dmgforms) < 2:
                continue
            names = [f"{i}:{f.name!r}" for i, f in enumerate(forms)]
            try:
                vals = []
                for i in range(len(forms)):
                    if not forms[i].damage_blocks_only():
                        vals.append(None)
                        continue
                    # also probe at 40% HP for missing/current-HP forms
                    v_full = _ab(snap, champ, key, i, 1.0)
                    v_lo = _ab(snap, champ, key, i, 0.4)
                    vals.append(max(v_full, v_lo))
            except Exception as e:  # noqa: BLE001
                rows.append((champ, key, f"ERR {e}", names))
                continue
            base = vals[0] if vals and vals[0] else None
            if base is None:
                # form 0 has no damage - any later damage form is a strong signal
                later = [(i, v) for i, v in enumerate(vals)
                         if i > 0 and v]
                if later:
                    bi, bv = max(later, key=lambda t: t[1])
                    rows.append((champ, key, f"form0=NO-DMG best=form{bi}({bv:.0f})", names))
                continue
            best_i = max(range(len(vals)),
                         key=lambda i: vals[i] if vals[i] else -1)
            if best_i > 0 and vals[best_i] and vals[best_i] > base * 1.15:
                rows.append((
                    champ, key,
                    f"form{best_i} {vals[best_i]/base:.2f}x form0 "
                    f"(f0={base:.0f} f{best_i}={vals[best_i]:.0f})",
                    names,
                ))

    print(f"unmapped multi-form (champ,key) flagged: {len(rows)}")
    for c, k, verdict, names in rows:
        print(f"  {c}.{k}: {verdict}")
        print(f"      forms: {' | '.join(names)}")
    print("\nFLAGGED=" + ",".join(f"{c}.{k}" for c, k, *_ in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
