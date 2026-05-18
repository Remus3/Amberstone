"""Daemon Slayer CLI - Phase 2 (stats/dps/rank/beam) + Phase 3 (serve).

Subcommands:
  stats   resolve a champion's stats at a level with items equipped
  dps     auto-attack DPS over lolmath rotation scenarios
  rank    score every legal purchasable item by DPS contribution
  beam    beam-search top-N complete builds (Phase 2 step 4)
  serve   start the local HTTP engine on :8893

Usage:
  python -m agents.daemon_slayer stats Aatrox --level 11 --items 6692,3006
  python -m agents.daemon_slayer dps Aatrox --level 11 --items 6692,3006,3072,3031
  python -m agents.daemon_slayer dps Aatrox --level 11 --mode ARAM --target-armor 80
  python -m agents.daemon_slayer rank Aatrox --level 11 --target-armor 80
  python -m agents.daemon_slayer rank Aatrox --level 11 --items 3006 --budget 3500 --top 10
  python -m agents.daemon_slayer beam Aatrox --level 11 --target-armor 80 --beam-width 10 --top 5
  python -m agents.daemon_slayer beam MissFortune --level 13 --mode ARAM --total-budget 14000
  python -m agents.daemon_slayer serve --host 0.0.0.0 --port 8893
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .beam import (
    DEFAULT_BEAM_WIDTH as BEAM_DEFAULT_WIDTH,
    DEFAULT_TOP_N as BEAM_DEFAULT_TOP_N,
    beam_search_build,
)
from .data_loader import DataSnapshot, SnapshotNotFound
from .dps import compute_dps
from .engine import build_champion
from .rank import SORT_KEYS, rank_items
from .server import DEFAULT_HOST, DEFAULT_PORT, serve_forever


def _cmd_stats(args: argparse.Namespace) -> int:
    try:
        snap = DataSnapshot.load(patch=args.patch, data_root=Path(args.data_root) if args.data_root else None)
    except SnapshotNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    item_ids: list[str] = []
    if args.items:
        item_ids = [s.strip() for s in args.items.split(",") if s.strip()]

    augments: list[str] = []
    if getattr(args, "augments", ""):
        augments = [s.strip() for s in args.augments.split(",") if s.strip()]

    try:
        resolved = build_champion(
            snap,
            champion_id=args.champion,
            level=args.level,
            item_ids=item_ids,
            mode=args.mode,
            augments=augments,
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


def _cmd_rank(args: argparse.Namespace) -> int:
    try:
        snap = DataSnapshot.load(patch=args.patch, data_root=Path(args.data_root) if args.data_root else None)
    except SnapshotNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    item_ids: list[str] = []
    if args.items:
        item_ids = [s.strip() for s in args.items.split(",") if s.strip()]

    only_ids: list[str] | None = None
    if args.only:
        only_ids = [s.strip() for s in args.only.split(",") if s.strip()]

    try:
        result = rank_items(
            snap,
            champion_id=args.champion,
            level=args.level,
            current_item_ids=item_ids,
            mode=args.mode,
            target_armor=args.target_armor,
            target_mr=args.target_mr,
            phase=args.phase,
            budget=args.budget,
            slot_count=args.slots,
            top_n=args.top,
            include_components=args.include_components,
            only_item_ids=only_ids,
            sort_by=args.sort,
        )
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.format_table())
    return 0


def _cmd_beam(args: argparse.Namespace) -> int:
    try:
        snap = DataSnapshot.load(patch=args.patch, data_root=Path(args.data_root) if args.data_root else None)
    except SnapshotNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    item_ids: list[str] = []
    if args.items:
        item_ids = [s.strip() for s in args.items.split(",") if s.strip()]

    only_ids: list[str] | None = None
    if args.only:
        only_ids = [s.strip() for s in args.only.split(",") if s.strip()]

    try:
        result = beam_search_build(
            snap,
            champion_id=args.champion,
            level=args.level,
            current_item_ids=item_ids,
            mode=args.mode,
            target_armor=args.target_armor,
            target_mr=args.target_mr,
            phase=args.phase,
            slot_count=args.slots,
            beam_width=args.beam_width,
            top_n=args.top,
            total_budget=args.total_budget,
            include_components=args.include_components,
            only_item_ids=only_ids,
            boots_unique=not args.no_boots_unique,
        )
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.format_table())
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    return serve_forever(
        host=args.host,
        port=args.port,
        patch=args.patch,
        data_root=Path(args.data_root) if args.data_root else None,
    )


def _cmd_not_implemented(name: str, phase: str):
    def _run(_args: argparse.Namespace) -> int:
        print(f"{name}: not implemented yet - scheduled for {phase}", file=sys.stderr)
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
    stats.add_argument("--augments", default="", help="comma-separated arena augment apiNames (e.g. TheBrutalizer,WitchfulThinking)")
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

    rank = sub.add_parser("rank", help="rank items by DPS delta when added to current build")
    rank.add_argument("champion", help="DDragon champion id (e.g. Aatrox, MonkeyKing)")
    rank.add_argument("--level", type=int, default=1, help="champion level 1-18 (default 1)")
    rank.add_argument("--items", default="", help="comma-separated current item IDs (the build so far)")
    rank.add_argument("--mode", default="SR", help="game mode: SR | ARAM | ARENA (default SR)")
    rank.add_argument("--target-armor", type=float, default=0.0, help="target armor (default 0)")
    rank.add_argument("--target-mr", type=float, default=0.0, help="target MR (default 0)")
    rank.add_argument(
        "--phase",
        choices=("early", "mid", "late"),
        default=None,
        help="rotation phase override (default: derived from --level)",
    )
    rank.add_argument("--budget", type=int, default=None, help="max gold per candidate (default unlimited)")
    rank.add_argument("--slots", type=int, default=6, help="max items in a build (default 6)")
    rank.add_argument("--top", type=int, default=20, help="rows to show (default 20, 0=all)")
    rank.add_argument(
        "--sort",
        choices=SORT_KEYS,
        default="delta",
        help="rank by 'delta' DPS gained or 'efficiency' DPS per 1k gold (default delta)",
    )
    rank.add_argument(
        "--include-components",
        action="store_true",
        help="include items with an upgrade path (Long Sword etc.)",
    )
    rank.add_argument(
        "--only",
        default="",
        help="comma-separated item ID whitelist; restricts ranking to these",
    )
    rank.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    rank.set_defaults(func=_cmd_rank)

    beam = sub.add_parser("beam", help="beam-search top-N complete builds")
    beam.add_argument("champion", help="DDragon champion id (e.g. Aatrox, MonkeyKing)")
    beam.add_argument("--level", type=int, default=1, help="champion level 1-18 (default 1)")
    beam.add_argument("--items", default="", help="comma-separated current item IDs (pinned in every result)")
    beam.add_argument("--mode", default="SR", help="game mode: SR | ARAM | ARENA (default SR)")
    beam.add_argument("--target-armor", type=float, default=0.0, help="target armor (default 0)")
    beam.add_argument("--target-mr", type=float, default=0.0, help="target MR (default 0)")
    beam.add_argument(
        "--phase",
        choices=("early", "mid", "late"),
        default=None,
        help="rotation phase override (default: derived from --level)",
    )
    beam.add_argument("--slots", type=int, default=6, help="max items in a build (default 6)")
    beam.add_argument(
        "--beam-width", type=int, default=BEAM_DEFAULT_WIDTH,
        help=f"survivors per generation (default {BEAM_DEFAULT_WIDTH})",
    )
    beam.add_argument(
        "--top", type=int, default=BEAM_DEFAULT_TOP_N,
        help=f"final builds returned (default {BEAM_DEFAULT_TOP_N})",
    )
    beam.add_argument(
        "--total-budget", type=int, default=None,
        help="max total gold per complete build (default unlimited)",
    )
    beam.add_argument(
        "--include-components", action="store_true",
        help="include items with an upgrade path (Long Sword etc.)",
    )
    beam.add_argument(
        "--only", default="",
        help="comma-separated item ID whitelist; restricts search to these",
    )
    beam.add_argument(
        "--no-boots-unique", action="store_true",
        help="allow multiple Boots-tagged items in a build",
    )
    beam.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    beam.set_defaults(func=_cmd_beam)

    serve = sub.add_parser("serve", help="start the local HTTP engine on :8893")
    serve.add_argument("--host", default=DEFAULT_HOST,
                       help=f"bind host (default {DEFAULT_HOST}; use 0.0.0.0 to expose on LAN)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT,
                       help=f"bind port (default {DEFAULT_PORT})")
    serve.set_defaults(func=_cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
