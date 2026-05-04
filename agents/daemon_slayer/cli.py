"""Daemon Slayer CLI — Phase 2 step 1 + step 2.

Subcommands:
  stats   resolve a champion's stats at a level with items equipped
  dps     auto-attack DPS over lolmath rotation scenarios
  rank    (Phase 2 step 3 — not shipped)

Usage:
  python -m agents.daemon_slayer stats Aatrox --level 11 --items 6692,3006
  python -m agents.daemon_slayer dps Aatrox --level 11 --items 6692,3006,3072,3031
  python -m agents.daemon_slayer dps Aatrox --level 11 --mode ARAM --target-armor 80
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .data_loader import DataSnapshot, SnapshotNotFound
from .dps import compute_dps
from .engine import build_champion


def _cmd_stats(args: argparse.Namespace) -> int:
    try:
        snap = DataSnapshot.load(patch=args.patch, data_root=Path(args.data_root) if args.data_root else None)
    except SnapshotNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    item_ids: list[str] = []
    if args.items:
        item_ids = [s.strip() for s in args.items.split(",") if s.strip()]

    try:
        resolved = build_champion(
            snap,
            champion_id=args.champion,
            level=args.level,
            item_ids=item_ids,
            mode=args.mode,
        )
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(resolved.to_dict(), indent=2))
    else:
        print(resolved.format_table())
    return 0


def _cmd_dps(args: argparse.Namespace) -> int:
    try:
        snap = DataSnapshot.load(patch=args.patch, data_root=Path(args.data_root) if args.data_root else None)
    except SnapshotNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    item_ids: list[str] = []
    if args.items:
        item_ids = [s.strip() for s in args.items.split(",") if s.strip()]

    try:
        result = compute_dps(
            snap,
            champion_id=args.champion,
            level=args.level,
            item_ids=item_ids,
            mode=args.mode,
            target_armor=args.target_armor,
            target_mr=args.target_mr,
            phase=args.phase,
        )
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.format_table())
    return 0


def _cmd_not_implemented(name: str, phase: str):
    def _run(_args: argparse.Namespace) -> int:
        print(f"{name}: not implemented yet — scheduled for {phase}", file=sys.stderr)
        return 64
    return _run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daemon_slayer", description="Daemon Slayer engine CLI")
    p.add_argument("--patch", default=None, help="patch version (default: read current.txt)")
    p.add_argument("--data-root", default=None, help="override data/daemon_slayer root")
    sub = p.add_subparsers(dest="cmd", required=True)

    stats = sub.add_parser("stats", help="resolve champion stats at level + items")
    stats.add_argument("champion", help="DDragon champion id (e.g. Aatrox, MonkeyKing)")
    stats.add_argument("--level", type=int, default=1, help="champion level 1-18 (default 1)")
    stats.add_argument("--items", default="", help="comma-separated item IDs")
    stats.add_argument("--mode", default="SR", help="game mode: SR | ARAM | ARENA (default SR)")
    stats.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    stats.set_defaults(func=_cmd_stats)

    dps = sub.add_parser("dps", help="auto-attack DPS over lolmath rotation scenarios")
    dps.add_argument("champion", help="DDragon champion id (e.g. Aatrox, MonkeyKing)")
    dps.add_argument("--level", type=int, default=1, help="champion level 1-18 (default 1)")
    dps.add_argument("--items", default="", help="comma-separated item IDs")
    dps.add_argument("--mode", default="SR", help="game mode: SR | ARAM | ARENA (default SR)")
    dps.add_argument("--target-armor", type=float, default=0.0, help="target armor (default 0)")
    dps.add_argument("--target-mr", type=float, default=0.0, help="target MR (default 0)")
    dps.add_argument(
        "--phase",
        choices=("early", "mid", "late"),
        default=None,
        help="rotation phase override (default: derived from --level)",
    )
    dps.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    dps.set_defaults(func=_cmd_dps)

    rank = sub.add_parser("rank", help="(Phase 2 step 3 — not shipped)")
    rank.set_defaults(func=_cmd_not_implemented("rank", "Phase 2 step 3"))

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
