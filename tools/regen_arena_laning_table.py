#!/usr/bin/env python
# arch: RM-158 data half - patch-pinned ARENA laning-table regen runner | section=tools | frozen=no
"""RM-158 DATA HALF - regenerate ``laning_scenarios_arena.json`` for a PINNED patch.

THE GENERATOR IS core/laning_scenario_precompute.py - identified by what WRITES
the path, not by filename: ``atomic_write`` at ``core/laning_scenario_precompute.py:909``,
the output path built at ``:922`` / ``:943``, driven from ``main`` at ``:1133``.
(``core/build_order_precompute.py`` writes the BUILD-ORDER artifact and is the
name-alike decoy; it never touches ``laning_scenarios_*.json``.)

WHY A RUNNER AND NOT JUST THE CLI
    ``python -m core.laning_scenario_precompute --mode arena`` is the shipped
    invocation, but it is pinned to the CURRENT patch in three places at once:
    ``DataSnapshot.load()`` with no argument reads ``data/daemon_slayer/current.txt``,
    ``resolve_patch()`` stamps ``payload["version"]`` from the same pointer, and
    ``out_dir_for`` targets ``.../laning_scenarios/<current>/``. The two arena
    tables that actually shipped are 16.13.1 and 16.12.1, and the live patch is
    16.15.1 - so the CLI physically cannot rebuild them. It would compute
    16.15.1 champion stats and file them under a 16.13.1 label.

    Both historical DS data sets are still on disk
    (``data/daemon_slayer/16.13.1/``, ``data/daemon_slayer/16.12.1/``) and
    ``DataSnapshot.load`` takes an explicit ``patch``, so a FAITHFUL rebuild is
    possible: load that patch's snapshot, generate with mode=ARENA, restamp
    ``version`` to the pinned patch, write.

WHAT CHANGES vs THE SHIPPED FILE
    * The economy block is finally ARENA's: income 600/min (was SR's 450), which
      moves ``gold_at_band`` / ``next_spike`` / ``recall`` at every band.
    * SCHEMA MOVES v3 -> v4. The generator advanced (item-state axis +
      kill_threshold_met + cooldown_window + spike_timing) after those tables
      shipped, and it has no v3 emit path. The rebuilt arena table is therefore
      NOT a like-for-like replacement: it is ~5x the leaf bytes and its sibling
      sr / aram tables in the same patch dir stay v3. Measure ``--dry-run``
      before landing one - see RM-155, which defers the full v4 regen.
    * The itemless (``item_state == "none"``) combat scalars still equal SR's:
      ``burst.py`` has no ARENA branch. Documented residual, not fixed here.

USAGE
    python tools/regen_arena_laning_table.py --patch 16.13.1 --dry-run
    python tools/regen_arena_laning_table.py --patch 16.13.1 --out <dir>

``--out`` is mandatory for a real write unless ``--in-place`` is given, so a
measurement run cannot silently overwrite a shipped artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import laning_scenario_precompute as gen  # noqa: E402

MODE = "arena"
DS_MODE = "ARENA"


def shipped_roster(patch: str) -> list:
    """Champion ids the SHIPPED table for ``patch`` covered, sorted.

    Rebuilding with the generator's 10-champion SEED sample would silently
    shrink a 173-champion artifact, so the roster is taken from the artifact
    being replaced. Falls back to the snapshot roster when no table shipped.
    """
    path = gen.table_path(patch, MODE) if hasattr(gen, "table_path") else (
        gen._DS_DIR / gen._OUT_SUBDIR / patch / f"laning_scenarios_{MODE}.json"
    )
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        names = sorted((payload.get("scenarios") or {}).keys())
        if names:
            return names
    except Exception:  # noqa: BLE001 - no shipped table -> caller falls back
        pass
    return []


def sha_and_size(path: Path) -> tuple:
    """(sha256[:16], bytes) read in BINARY - never round-trip text on Windows."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16], len(data)


def payload_fingerprint(payload: dict) -> str:
    """Hash of the ``scenarios`` block alone - the mode-content identity.

    The header (``mode`` / ``generated_at``) always differs between two tables,
    so a whole-file hash cannot answer "is this the SR table again". This can.
    """
    blob = json.dumps(payload.get("scenarios") or {}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()[:16]


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--patch", required=True, help="Patch to pin (e.g. 16.13.1).")
    ap.add_argument("--out", default="", help="Output DIRECTORY for the rebuilt table.")
    ap.add_argument("--in-place", action="store_true",
                    help="Overwrite the shipped table in its own patch dir.")
    ap.add_argument("--dry-run", action="store_true", help="Generate but do not write.")
    ap.add_argument("--champions", default="",
                    help="CSV roster override (default: the shipped table's roster).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Use only the first N champions (cost measurement).")
    args = ap.parse_args(argv)

    if not args.dry_run and not args.out and not args.in_place:
        print("refusing to write: pass --out <dir> or --in-place")
        return 2

    if not gen._lead.gold_income_is_registered(DS_MODE):
        print(f"refusing: no gross-income row for {DS_MODE} in core.lead_projection")
        return 2

    started = time.time()
    snapshot = gen.DataSnapshot.load(patch=args.patch)
    load_s = time.time() - started
    print(f"snapshot patch={args.patch} loaded in {load_s:.1f}s "
          f"champions={len(snapshot.champions)}")

    roster = [c.strip() for c in args.champions.split(",") if c.strip()]
    if not roster:
        roster = shipped_roster(args.patch) or sorted(snapshot.champions.keys())
    if args.limit > 0:
        roster = roster[:args.limit]
    print(f"roster={len(roster)} bands={list(gen.GEN_BANDS)} "
          f"income_per_min={gen._lead.gold_income_per_min(DS_MODE)}")

    t0 = time.time()
    payload = gen.generate_table(snapshot, roster, roster, mode=DS_MODE,
                                 bands=list(gen.GEN_BANDS))
    gen_s = time.time() - t0
    # generate_table stamps version from current.txt; this run is pinned.
    payload["version"] = args.patch
    leaves = gen._count_leaves(payload)
    print(f"generated {leaves} leaf cells in {gen_s:.1f}s "
          f"({leaves / max(gen_s, 1e-9):.0f} leaves/s)")
    print(f"scenarios fingerprint {payload_fingerprint(payload)}")
    print(f"economy {payload['dimensions']['economy']}")

    sr_path = (gen._DS_DIR / gen._OUT_SUBDIR / args.patch /
               "laning_scenarios_sr.json")
    if sr_path.is_file():
        sr_fp = payload_fingerprint(json.loads(sr_path.read_bytes()))
        same = sr_fp == payload_fingerprint(payload)
        print(f"sr fingerprint        {sr_fp}  ->  "
              f"{'STILL AN SR COPY' if same else 'DISTINCT from SR (fixed)'}")
        if same:
            print("REFUSING to write an SR copy under an arena header (RM-158).")
            return 1

    if args.dry_run:
        blob = json.dumps(payload, ensure_ascii=True, separators=(",", ":"),
                          sort_keys=True).encode("ascii")
        print(f"[dry-run] would write {len(blob)} bytes (not written)")
        return 0

    out_dir = Path(args.out) if args.out else (
        gen._DS_DIR / gen._OUT_SUBDIR / args.patch)
    out_path = out_dir / f"laning_scenarios_{MODE}.json"
    if out_path.is_file():
        before = sha_and_size(out_path)
        print(f"before sha/size {before[0]} {before[1]}")
    gen.atomic_write(payload, out_path)
    after = sha_and_size(out_path)
    print(f"wrote {out_path}")
    print(f"after  sha/size {after[0]} {after[1]}")
    print(f"total {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
