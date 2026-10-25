#!/usr/bin/env python
# arch: G5-01 anvil-shadow probe - one verdict line, never a traceback | section=tools | frozen=no
"""anvil_shadow_probe.py - the GATE 5 DRAIN CARD's G5-01 anvil probe (RM-873).

The card in docs/LIVE_GAME_GATED_SYNC.md gave this probe as a ``python -c``
one-liner that ``open()``-ed ``data/anvil_shadow.jsonl`` unguarded. Since
RM-867 archive-split the 30 leaked fixture rows, an absent file is the NORMAL
pre-game state (core.anvil_shadow recreates it on the first real anvil row),
so the one-liner printed FileNotFoundError where a verdict belongs.

This prints ONE line:
  - file absent       -> ``FAIL: data/anvil_shadow.jsonl absent (no real anvil row yet)``, exit 1
  - no row / bad row  -> ``FAIL: ...`` naming the cause, exit 1
  - rows present      -> the card's summary of the LAST row, exit 0:
                         ``<n rows> <ts> <champion> <round> <offered> <native take>``

READ-ONLY: it never writes, and it is not the verdict. The card's predicate
still decides PASS (a row whose ``ts`` is after this game's start, mode arena,
the live champion, ``offered`` naming the cards on screen); file existence or
byte growth alone is not evidence.

USAGE (main checkout root)
    python tools/anvil_shadow_probe.py
    python tools/anvil_shadow_probe.py --path <other jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
# Same file core.anvil_shadow.SHADOW_PATH appends to (pinned by
# tests/test_anvil_shadow_probe_rm873.py); not imported, so the probe runs
# without the repo root on sys.path.
SHADOW_PATH: Path = _REPO / "data" / "anvil_shadow.jsonl"
_DEFAULT_LABEL = "data/anvil_shadow.jsonl"


def probe(path: Path, label: str | None = None) -> tuple[int, str]:
    """Return (exit code, the one line to print) for the shadow file at path."""
    name = label if label is not None else str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 1, f"FAIL: {name} absent (no real anvil row yet)"
    rows = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            return 1, f"FAIL: {name} line {lineno} is not a JSON object"
        rows.append(row)
    if not rows:
        return 1, f"FAIL: {name} has no rows"
    last = rows[-1]
    native = last.get("native")
    take = native.get("take") if isinstance(native, dict) else None
    fields = (len(rows), last.get("ts"), last.get("champion"), last.get("round"),
              last.get("offered"), take)
    return 0, " ".join(str(f) for f in fields)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G5-01 anvil-shadow probe (read-only).")
    ap.add_argument("--path", type=Path, default=None,
                    help="shadow jsonl to read (default: data/anvil_shadow.jsonl)")
    args = ap.parse_args(argv)
    if args.path is None:
        code, line = probe(SHADOW_PATH, label=_DEFAULT_LABEL)
    else:
        code, line = probe(args.path)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
