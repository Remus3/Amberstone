"""P6 G4 boots-pool refresh - HZ-B1 + HZ-B2 table regeneration.

Regenerates the precompute build-order tables (HZ-B1 = build_orders_<mode>.json,
HZ-B2 = build_order_variants_<mode>.json) for all 3 modes at the live patch and
the current ENGINE_VERSION, using the EXACT 172-champion display-name roster
already committed in the HZ-B1 SR table (so the regen reproduces the G1 roster
byte-for-roster; the generator CLIs otherwise default to the 10-champ seed -
item 388). The flat tables (data/daemon_slayer/<patch>/build_orders_<mode>.json)
are regenerated separately via tools/daemon_slayer_build_orders_generate.py
--mode all, whose CLI auto-loads the full roster.

Requires the live DS engine at 127.0.0.1:8893 (ranking is byte-identical
between 1.122.0 and 1.123.0 - this slice changes only the RC-side boots slot).

Usage:
  python ops/audit/p6g4_regen.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.build_order_precompute as bop
import core.build_order_variants as bov

_PATCH = bop.resolve_patch()
_ROSTER_TABLE = (
    Path(bop._DS_DIR) / bop._OUT_SUBDIR / _PATCH / "build_orders_sr.json"
)


def _roster() -> list[str]:
    payload = json.loads(_ROSTER_TABLE.read_text(encoding="utf-8"))
    champs = list((payload.get("build_orders") or {}).keys())
    if len(champs) < 100:
        raise SystemExit(
            f"roster table {_ROSTER_TABLE} has only {len(champs)} champions - "
            "refusing to regen against a seed-sized roster"
        )
    return champs


def main() -> int:
    champs = _roster()
    print(f"P6 G4 regen patch={_PATCH} engine={bop.engine_version()} "
          f"champions={len(champs)}")
    modes = bop._MODE_KEYS  # ("sr", "aram", "arena")

    b1_dir = bop.out_dir_for(_PATCH)
    b2_dir = bov.out_dir_for(_PATCH)
    for mk in modes:
        ds_mode = bop.DS_MODE_BY_KEY.get(mk, "SR")
        b1 = bop.generate_table(champs, mode=ds_mode)
        bop.atomic_write(b1, b1_dir / f"build_orders_{mk}.json")
        c1 = bop._count_cells(b1)
        b2 = bov.generate_table(champs, mode=ds_mode)
        bov.atomic_write(b2, b2_dir / f"build_order_variants_{mk}.json")
        print(f"  {mk:5s}: HZ-B1 {c1[0]}ch/{c1[1]}cells -> build_orders_{mk}.json"
              f" | HZ-B2 {len(b2.get('variants') or b2.get('build_orders') or {})}"
              f"ch -> build_order_variants_{mk}.json")
    print("HZ-B1 + HZ-B2 regen complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
