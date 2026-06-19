"""P7 Arena boots 22-mirror refresh - Arena-only table regeneration.

The P6-G4 deferred tail (the SR tier-3 sibling shipped item 423): the
Arena (map 30) build-order tables carried the BARE 3xxx tier-2 boots ids
(e.g. 3111 Mercury's Treads), which are map30=False - illegal on the Arena
map. core.build_order._select_boots now remaps the resolved tier-2 boot to
its 22-prefixed map30-legal Arena mirror (_BOOTS_ARENA_MIRROR) when the mode
is Arena/CHERRY. This regenerates ONLY the three Arena tables so SR + ARAM
stay byte-identical on disk (ARAM 3xxx boots are map12-legal; SR uses tier-3):

  1. flat (display-keyed):
       data/daemon_slayer/<patch>/build_orders_arena.json
  2. HZ-B1 (canonical-keyed):
       data/daemon_slayer/build_orders/<patch>/build_orders_arena.json
  3. HZ-B2 variants (canonical-keyed):
       data/daemon_slayer/build_orders/<patch>/build_order_variants_arena.json

Requires the live DS engine at 127.0.0.1:8893. The ranker is byte-identical
across the ENGINE bump (this slice changes only the RC-side boots slot); the
only build-order delta is the boots id 3xxx -> 22xxxx on Arena (plus any
legitimate ranking shift the live engine already reflects).

Usage:
  python ops/audit/p7_arena_boots_regen.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop
import core.build_order_variants as bov


def _load_flatgen():
    """Import tools/daemon_slayer_build_orders_generate.py by path (the
    module name is not an importable package path)."""
    path = _ROOT / "tools" / "daemon_slayer_build_orders_generate.py"
    spec = importlib.util.spec_from_file_location("_ds_flatgen", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical_roster() -> list[str]:
    """Canonical-name roster from the committed HZ-B1 SR table (172)."""
    patch = bop.resolve_patch()
    table = Path(bop._DS_DIR) / bop._OUT_SUBDIR / patch / "build_orders_sr.json"
    payload = json.loads(table.read_text(encoding="utf-8"))
    champs = list((payload.get("build_orders") or {}).keys())
    if len(champs) < 100:
        raise SystemExit(f"roster {table} has only {len(champs)} - refusing")
    return champs


def main() -> int:
    patch = bop.resolve_patch()
    print(f"P7 Arena boots regen patch={patch} engine={bop.engine_version()}")

    # (1) flat display-keyed table - its own full DDragon roster.
    flatgen = _load_flatgen()
    flat_champs = flatgen.load_champions()
    flat_payload = flatgen.generate_mode("arena", flat_champs, patch)
    flat_out = flatgen.out_dir_for(patch, None) / "build_orders_arena.json"
    flatgen.atomic_write(flat_payload, flat_out)
    fc, fcells = flatgen._count_cells(flat_payload)
    print(f"  flat : {fc}ch/{fcells}cells -> {flat_out}")

    # (2)+(3) HZ-B1 + HZ-B2 canonical-keyed Arena tables.
    champs = _canonical_roster()
    b1 = bop.generate_table(champs, mode="ARENA")
    bop.atomic_write(b1, bop.out_dir_for(patch) / "build_orders_arena.json")
    c1 = bop._count_cells(b1)
    b2 = bov.generate_table(champs, mode="ARENA")
    bov.atomic_write(b2, bov.out_dir_for(patch) / "build_order_variants_arena.json")
    n2 = len(b2.get("variants") or b2.get("build_orders") or {})
    print(f"  HZ-B1: {c1[0]}ch/{c1[1]}cells -> build_orders_arena.json")
    print(f"  HZ-B2: {n2}ch -> build_order_variants_arena.json")
    print("Arena regen complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
