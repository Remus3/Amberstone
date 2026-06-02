"""tools/daemon_slayer_pickban_targets_generate.py - precomputed pick/ban targets.

Generates a per-champion pick/ban targets table the champ-select coach reads at
request time INSTEAD of invoking Claude Haiku for a counter suggestion. Advances
the PRIMARY north star (drive live Haiku usage to ZERO): for every champion the
roster is ranked by the Daemon Slayer 1v1 matchup engine, so the coach can serve
ban candidates (counters) + good_against picks from a dict lookup, no LLM call.

WHAT v1 IS (honest scope)
-------------------------
This is a precomputed substitute for the LLM's counter suggestion, NOT a claim
of perfect draft theory. The signal is a single itemless level-9 1v1 duel
verdict from ``agents.daemon_slayer.matchup.compute_matchup`` (the SHIPPED,
deterministic, pure engine). That is a SOFT counter signal - "this champ wins
the itemless lvl-9 duel" - with NO synergy / team-comp / role-context / rune
modelling. It is an honest deterministic proxy for the kind of "who counters
whom" hint a coach would otherwise ask Haiku for, and it is reproducible.

HOW the ranking works
---------------------
``compute_matchup(snapshot, A, B, ...).net_swing`` is positive when champion A is
favored over B (and is anti-symmetric: swing(A,B) == -swing(B,A)). For champion
A we score every other champion B by ``net_swing`` of A-vs-B:

* ``counters`` for A   = the B with the most NEGATIVE A-vs-B swing (B beats A) -
  these are the champs to BAN against / be wary of when you pick A.
* ``good_against`` for A = the B with the most POSITIVE A-vs-B swing (A beats B) -
  the matchups A is favored into.

Each list is sign-filtered then top-K (default 8), sorted strongest-first, as
``[{"champion": "<id>", "net_swing": <rounded>}, ...]``. A champ that loses no
itemless lvl-9 duel has an EMPTY ``counters`` list (and vice versa) - that is
the honest contract, NOT a degenerate row.

What it produces (atomic write)
-------------------------------
``data/daemon_slayer/<patch>/pickban_targets.json``::

    {
      "patch": "<patch>",
      "mode": "sr",
      "level": 9,
      "top_k": 8,
      "targets": {
        "<ChampId>": {
          "counters":     [{"champion": "<id>", "net_swing": <float>}, ...],
          "good_against": [{"champion": "<id>", "net_swing": <float>}, ...]
        },
        ...
      }
    }

Champion keys are the DDragon id form the engine accepts (e.g. ``Kaisa``,
``MonkeyKing``) - the keys of ``data/daemon_slayer/<patch>/champions.json``.

Usage
-----
    py tools/daemon_slayer_pickban_targets_generate.py [--limit N] [--check]
        [--top-k 8] [--out <dir>]

* ``--limit N`` caps the roster to the first N champs (fast dev iteration).
* ``--check`` regenerates to a temp + diffs against the committed file = the CI
  drift guard (mirrors the build_orders generator convention). Exits 1 on drift.
* ``--top-k`` overrides the per-list slice length (default 8).
* ``--out`` overrides the output directory (default resolves from current.txt).

The matchup engine reads only local data files (NOT the :8893 server), so this
runs offline. The ~172x171 ~= 29k calls take a few minutes at most.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# Project root: tools/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer.matchup import DataSnapshot, compute_matchup

_DATA_DIR = _ROOT / "data"
_DS_DIR = _DATA_DIR / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"

# Patch fallback when current.txt is missing (guards a fresh checkout only).
_FALLBACK_PATCH = "16.11.1"

# v1 matchup parameters: itemless, representative mid-game level, Summoner's Rift.
_LEVEL = 9
_MODE = "SR"
_MODE_KEY = "sr"

# Default per-list slice length (counters + good_against each take top-K).
_DEFAULT_TOP_K = 8

# Round net_swing to keep the file compact + deterministic across runs.
_ROUND = 4

# Progress print cadence (every N champion rows).
_PROGRESS_EVERY = 10


def resolve_patch() -> str:
    """Read the active patch from current.txt; fall back to _FALLBACK_PATCH."""
    try:
        txt = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 - fail-soft to fallback
        print(f"WARN: current.txt read failed ({exc}); using {_FALLBACK_PATCH}",
              file=sys.stderr)
    return _FALLBACK_PATCH


def out_dir_for(patch: str, override: Optional[str]) -> Path:
    """Output directory for ``patch`` (or the override path verbatim)."""
    if override:
        return Path(override)
    return _DS_DIR / patch


def load_roster(patch: str) -> list[str]:
    """Return the sorted DDragon-id roster the engine accepts.

    Keys of ``data/daemon_slayer/<patch>/champions.json`` ``data`` dict - the
    exact id form ``compute_matchup`` takes (e.g. ``Kaisa``, ``MonkeyKing``).
    """
    champs_path = _DS_DIR / patch / "champions.json"
    raw = json.loads(champs_path.read_text(encoding="utf-8"))
    data = raw.get("data", raw) or {}
    return sorted(str(k) for k in data.keys())


def _swing(snapshot: DataSnapshot, champ_a: str, champ_b: str) -> Optional[float]:
    """A-vs-B net_swing (positive = A favored), or None on engine failure."""
    try:
        result = compute_matchup(
            snapshot, champ_a, champ_b, level_a=_LEVEL, level_b=_LEVEL,
            mode=_MODE,
        )
    except Exception as exc:  # noqa: BLE001 - one bad pair never sinks the run
        print(f"WARN: compute_matchup raised for {champ_a} vs {champ_b}: {exc}",
              file=sys.stderr)
        return None
    if result is None:
        return None
    return float(result.net_swing)


def targets_for_champion(
    snapshot: DataSnapshot,
    champ_a: str,
    roster: list[str],
    top_k: int,
) -> dict:
    """Return ``{"counters": [...], "good_against": [...]}`` for ``champ_a``.

    ``counters``     = champs with the most NEGATIVE A-vs-B swing (B beats A).
    ``good_against`` = champs with the most POSITIVE A-vs-B swing (A beats B).
    Each entry is ``{"champion": <id>, "net_swing": <rounded>}``, strongest
    first. Self is excluded; pairs the engine fails on are skipped.
    """
    scored: list[tuple[str, float]] = []
    for champ_b in roster:
        if champ_b == champ_a:
            continue
        sw = _swing(snapshot, champ_a, champ_b)
        if sw is None:
            continue
        scored.append((champ_b, sw))

    # good_against: A favored -> POSITIVE swing only, most positive first.
    # counters: A unfavored -> NEGATIVE swing only, most negative first.
    # Sign-filtering keeps the contract honest: "counters = champs that BEAT
    # this champ" should be empty for a champ that loses no itemless duel,
    # rather than padding the list with its least-favorable wins.
    good = sorted((t for t in scored if t[1] > 0.0),
                  key=lambda t: t[1], reverse=True)[:top_k]
    counters = sorted((t for t in scored if t[1] < 0.0),
                      key=lambda t: t[1])[:top_k]

    return {
        "counters": [
            {"champion": c, "net_swing": round(s, _ROUND)} for c, s in counters
        ],
        "good_against": [
            {"champion": c, "net_swing": round(s, _ROUND)} for c, s in good
        ],
    }


def generate_payload(
    snapshot: DataSnapshot,
    roster: list[str],
    patch: str,
    top_k: int,
    *,
    verbose: bool = True,
) -> dict:
    """Build the full pick/ban targets payload for the roster."""
    targets: dict[str, dict] = {}
    total = len(roster)
    for i, champ_a in enumerate(roster):
        targets[champ_a] = targets_for_champion(snapshot, champ_a, roster, top_k)
        if verbose and (i + 1) % _PROGRESS_EVERY == 0:
            print(f"  ... {i + 1}/{total} champions scored", file=sys.stderr)
    return {
        "patch": patch,
        "mode": _MODE_KEY,
        "level": _LEVEL,
        "top_k": top_k,
        "targets": targets,
    }


def _serialize(payload: dict) -> str:
    """Deterministic ASCII-only JSON text for ``payload`` (also used by --check)."""
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def atomic_write(payload: dict, out_path: Path) -> None:
    """Write ``payload`` to ``out_path`` via tmp + os.replace (atomic).

    Mirrors ``tools/daemon_slayer_build_orders_generate.atomic_write``: a reader
    (the coach) polling mid-write must never see a partial file. ASCII-only JSON.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{out_path.stem}.", suffix=".tmp", dir=str(out_path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(_serialize(payload))
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap the roster to the first N champs (dev iteration).")
    ap.add_argument("--top-k", type=int, default=_DEFAULT_TOP_K,
                    help=f"Per-list slice length (default {_DEFAULT_TOP_K}).")
    ap.add_argument("--check", action="store_true",
                    help="Regenerate to memory + diff vs the committed file; "
                         "exit 1 on drift (CI guard). Writes nothing.")
    ap.add_argument("--out", default="",
                    help="Override output dir (default data/daemon_slayer/<patch>).")
    args = ap.parse_args()

    if args.top_k <= 0:
        print("--top-k must be positive", file=sys.stderr)
        return 2

    patch = resolve_patch()
    out_dir = out_dir_for(patch, args.out or None)
    out_path = out_dir / "pickban_targets.json"

    roster = load_roster(patch)
    if args.limit and args.limit > 0:
        roster = roster[:args.limit]

    print(f"pickban-targets gen patch={patch} roster={len(roster)} "
          f"top_k={args.top_k} level={_LEVEL} mode={_MODE_KEY} "
          f"check={args.check} out={out_path}", file=sys.stderr)

    snapshot = DataSnapshot.load()
    payload = generate_payload(snapshot, roster, patch, args.top_k)

    if args.check:
        new_text = _serialize(payload)
        try:
            cur_text = out_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"DRIFT: {out_path} does not exist (run the generator).",
                  file=sys.stderr)
            return 1
        if new_text != cur_text:
            print(f"DRIFT: {out_path} differs from a fresh generation. "
                  f"Re-run `py tools/daemon_slayer_pickban_targets_generate.py`.",
                  file=sys.stderr)
            return 1
        print(f"OK: {out_path.name} in sync ({len(payload['targets'])} champs).",
              file=sys.stderr)
        return 0

    atomic_write(payload, out_path)
    n = len(payload["targets"])
    print(f"wrote {out_path.name}: {n} champions -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
