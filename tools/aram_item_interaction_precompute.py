"""Offline precompute for the RM-111 ARAM item-interaction snapshot.

Runs ``core.aram_item_interaction.compute_aram_item_interaction_from_db`` over
the local corpus (~2000 ARAM matches) and writes the result to
``data/coaching/aram_item_interaction.json``, which
``core/aram_item_interaction_context.py`` reads at import time. The aggregation
walks every timeline frame of every match and is orders of magnitude too slow
for a live coach tick, hence the offline hop.

Usage::

    python tools/aram_item_interaction_precompute.py
    python tools/aram_item_interaction_precompute.py --min-n 20
    python tools/aram_item_interaction_precompute.py --db data/rewind_history.db \
        --out data/coaching/aram_item_interaction.json

Writes ATOMICALLY (tmp.write_text then tmp.replace - CLAUDE.md hard rule) so a
consumer polling the file never observes a half-written payload. The payload
carries NO wall-clock timestamp: every field is reproducible from the corpus,
so a re-run over an unchanged db yields a byte-identical file. ASCII only.

Exits non-zero with a plain one-line message when the db is missing or the
aggregation reports a failure.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.aram_item_interaction import (  # noqa: E402
    ARAM_MAP_ID,
    MIN_BUCKET_N,
    compute_aram_item_interaction_from_db,
)

SCHEMA = "aram_item_interaction/v1"

DEFAULT_DB = _PROJECT_ROOT / "data" / "rewind_history.db"
DEFAULT_OUT = _PROJECT_ROOT / "data" / "coaching" / "aram_item_interaction.json"

_GENERATED_NOTE = (
    "offline precompute of core.aram_item_interaction; descriptive corpus "
    "evidence only, never an input to daemon_slayer rank"
)


def _patch_sort_key(patch: str) -> tuple:
    """Order a "major.minor" patch string NUMERICALLY, not lexically.

    A lexical sort is WRONG for patch strings: "15.9" sorts AFTER "15.13" as
    text but is the older patch. Returns ``(major, minor)`` ints; a component
    that does not parse becomes ``-1`` so a malformed string sorts first
    instead of raising.
    """
    parts = str(patch or "").split(".")
    out = []
    for part in parts[:2]:
        try:
            out.append(int(part))
        except (TypeError, ValueError):
            out.append(-1)
    while len(out) < 2:
        out.append(-1)
    return (out[0], out[1])


def patch_range(db_path: Path, patch: str | None = None) -> tuple:
    """Return ``(patch_min, patch_max)`` for the ARAM-with-timeline corpus.

    Reads the ``matches.patch`` column DIRECTLY (read-only uri connection, the
    same discipline the aggregator uses), filtering NULL / empty, and orders
    with ``_patch_sort_key`` so 15.9 precedes 15.13. When ``patch`` pins a
    single patch both ends are that patch. ``(None, None)`` on any failure -
    this is a provenance nicety, never a reason to fail the precompute.
    """
    if patch:
        return (patch, patch)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return (None, None)
    try:
        rows = conn.execute(
            "SELECT DISTINCT patch FROM matches "
            "WHERE map_id=? AND has_timeline=1",
            (ARAM_MAP_ID,),
        ).fetchall()
    except sqlite3.Error:
        return (None, None)
    finally:
        conn.close()
    seen = sorted(
        {str(r[0]).strip() for r in rows if r[0] is not None and str(r[0]).strip()},
        key=_patch_sort_key,
    )
    if not seen:
        return (None, None)
    return (seen[0], seen[-1])


def build_payload(result: dict, patch_min: str | None = None,
                  patch_max: str | None = None) -> dict:
    """Reshape an aggregator result into the schema-versioned snapshot payload.

    Only fields the aggregator actually produced are carried forward - no
    wall-clock timestamp is invented here, so the output is reproducible.
    ``patch_min`` / ``patch_max`` come from ``patch_range`` and let the
    consumer render an honest patch-RANGE provenance tag (the corpus is a
    historical blend, not the current patch).
    """
    return {
        "schema": SCHEMA,
        "patch": result.get("patch"),
        "patch_min": patch_min,
        "patch_max": patch_max,
        "matches": int(result.get("matches") or 0),
        "min_n": result.get("min_n"),
        "map_id": result.get("map_id"),
        "pressure_window_s": result.get("pressure_window_s"),
        "cells_dropped_below_min_n": result.get("cells_dropped_below_min_n"),
        "generated_note": _GENERATED_NOTE,
        "cells": result.get("cells") or [],
    }


def write_atomic(payload: dict, out_path: Path) -> None:
    """Serialise ``payload`` to ``out_path`` via a tmp file + replace."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    tmp.replace(out_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Precompute the ARAM comp-conditioned item-interaction "
                    "snapshot for the live coach loader.",
    )
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="path to rewind_history.db (default: data/rewind_history.db)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output JSON path (default: data/coaching/aram_item_interaction.json)")
    ap.add_argument("--min-n", type=int, default=MIN_BUCKET_N,
                    help=f"hard per-cell sample gate (default: {MIN_BUCKET_N})")
    ap.add_argument("--patch", default=None,
                    help="restrict the corpus to one patch (default: all)")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    try:
        result = compute_aram_item_interaction_from_db(
            db_path, min_n=args.min_n, patch=args.patch
        )
    except Exception as exc:  # noqa: BLE001 - a CLI reports, it does not traceback
        print(f"ERROR: aggregation failed: {exc}", file=sys.stderr)
        return 3

    if not result.get("ok"):
        print(f"ERROR: {result.get('error') or 'aggregation returned not-ok'}",
              file=sys.stderr)
        return 3

    p_min, p_max = patch_range(db_path, args.patch)
    payload = build_payload(result, patch_min=p_min, patch_max=p_max)
    out_path = Path(args.out)
    try:
        write_atomic(payload, out_path)
    except OSError as exc:
        print(f"ERROR: write failed: {exc}", file=sys.stderr)
        return 4

    print(
        f"wrote {out_path} cells={len(payload['cells'])} "
        f"matches={payload['matches']} min_n={args.min_n} "
        f"patch={payload['patch']} "
        f"patches={payload['patch_min']}-{payload['patch_max']} "
        f"dropped={payload['cells_dropped_below_min_n']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
