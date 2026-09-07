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

HOW the ranking works (DE-BIASED relative strength)
---------------------------------------------------
``compute_matchup(snapshot, A, B, ...).net_swing`` is positive when champion A is
favored over B. A RAW net_swing ranking collapses every champion's counters list
onto the same few globally-strong duelists (a champ that beats EVERYONE shows up
as everyone's counter), which is nearly useless as a per-champ counter signal.

So the ranking de-biases by each champ's global dominance baseline
``colmean(B)`` (mean of B's swing over the whole roster):

* ``counters`` for A     = champs B that BEAT A, ranked by
  ``rel = swing(B, A) - colmean(B)`` (most positive first). Subtracting B's
  global strength surfaces the champ that ESPECIALLY beats A over a bully that
  beats everyone - so the list is A-SPECIFIC.
* ``good_against`` for A  = champs B that A beats, ranked by
  ``rel = swing(A, B) + colmean(B)`` (most positive first). Adding B's strength
  surfaces "you are favored into this STRONG champ" over "you beat a champ
  everyone beats".

Each list is sign-filtered (B genuinely beats / loses to A) then top-K
(default 8). The de-bias is in the SORT, not a hard ``rel`` cut, so a champ that
loses to anyone still gets its most-specific counters rather than an empty list.
Each entry is ``{"champion": "<id>", "net_swing": <raw A-vs-B, rounded>,
"rel": <de-biased, rounded>}`` (net_swing stays A-vs-B, NEGATIVE for a counter -
the reader's documented contract; rel is the value the list is sorted by).

What it produces (atomic write)
-------------------------------
``data/daemon_slayer/<patch>/pickban_targets.json``::

    {
      "patch": "<patch>",
      "mode": "sr",
      "level": 9,
      "top_k": 8,
      "ranking": "debiased_relative",
      "targets": {
        "<ChampId>": {
          "counters":     [{"champion": "<id>", "net_swing": <float>, "rel": <float>}, ...],
          "good_against": [{"champion": "<id>", "net_swing": <float>, "rel": <float>}, ...]
        },
        ...
      }
    }

Champion keys are the DDragon id form the engine accepts (e.g. ``Kaisa``,
``MonkeyKing``) - the keys of ``data/daemon_slayer/<patch>/champions.json``.

Usage
-----
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_pickban_targets_generate.py [--limit N] [--check]
        [--top-k 8] [--out <dir>]

* ``--limit N`` caps the roster to the first N champs (fast dev iteration).
* ``--check`` regenerates to a temp + diffs against the committed file = the CI
  drift guard (mirrors the build_orders generator convention). Exits 1 on drift.
* ``--top-k`` overrides the per-list slice length (default 8).
* ``--out`` overrides the output directory (default resolves from current.txt).

The matchup engine reads only local data files (NOT the :8860 server), so this
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
from agents.daemon_slayer.mode_variants import canonical_champions

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
    exact id form ``compute_matchup`` takes (e.g. ``Kaisa``, ``MonkeyKing``) -
    minus the DDragon THROWBACK-MODE rows.

    The snapshot on disk is extracted verbatim, so from 16.15.1 it carries 60
    ``Jade_<Champion>`` rows that ``DataSnapshot.load`` partitions out. Reading
    the file raw put them in the roster and every one of their 233 x 233 pairs
    then failed with "Unknown champion id" - a matrix the engine cannot score.
    Partition here with the same predicate the engine uses.
    """
    champs_path = _DS_DIR / patch / "champions.json"
    raw = json.loads(champs_path.read_text(encoding="utf-8"))
    data = raw.get("data", raw) or {}
    return sorted(str(k) for k in canonical_champions(data))


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


def build_matrix(
    snapshot: DataSnapshot,
    roster: list[str],
    *,
    verbose: bool = True,
) -> dict[str, dict[str, float]]:
    """Full pairwise swing matrix ``m[A][B] = swing(A, B)`` (A favored > 0).

    One ``compute_matchup`` call per ordered pair; engine-None pairs are simply
    absent from the inner dict (fail-soft). This is the single source the
    de-biased ranking reads - colmeans + per-champ ranking both derive from it.
    """
    m: dict[str, dict[str, float]] = {a: {} for a in roster}
    total = len(roster)
    for i, champ_a in enumerate(roster):
        for champ_b in roster:
            if champ_b == champ_a:
                continue
            sw = _swing(snapshot, champ_a, champ_b)
            if sw is not None:
                m[champ_a][champ_b] = sw
        if verbose and (i + 1) % _PROGRESS_EVERY == 0:
            print(f"  ... {i + 1}/{total} rows computed", file=sys.stderr)
    return m


def _colmean(m: dict[str, dict[str, float]], champ: str) -> float:
    """Champ's global duel dominance baseline: mean of its swing over all foes.

    A globally-strong duelist (beats everyone) has a high colmean; a weak one
    is negative. Subtracting it from a pairwise swing isolates the matchup that
    is ESPECIALLY (un)favorable, removing the global-strength skew that made
    every champ's raw counters list collapse onto the same few bullies.
    """
    row = m.get(champ) or {}
    vals = list(row.values())
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def targets_from_matrix(
    m: dict[str, dict[str, float]],
    champ_a: str,
    roster: list[str],
    top_k: int,
    colmeans: dict[str, float],
) -> dict:
    """De-biased ``{"counters": [...], "good_against": [...]}`` for ``champ_a``.

    counters     = champs B that BEAT champ_a (swing(B, A) > 0), ranked by the
                   de-biased counter strength ``rel = swing(B, A) - colmean(B)``
                   (most positive first). Subtracting B's global dominance means
                   a champ that ESPECIALLY beats champ_a outranks a global bully
                   that beats everyone - so the list is champ_a-SPECIFIC, not the
                   same 5 duelists for every champ.
    good_against = champs B that champ_a beats (swing(A, B) > 0), ranked by
                   ``rel = swing(A, B) + colmean(B)`` (most positive first).
                   Adding B's dominance surfaces "you are favored into this
                   STRONG champ" above "you beat a champ everyone beats".

    Each entry keeps the raw ``net_swing`` (champ_a-vs-B, so NEGATIVE for a
    counter - the reader's documented contract) PLUS the de-biased ``rel`` it is
    sorted by. Self is excluded; only the swing SIGN filters (B genuinely beats
    / loses to champ_a) - the de-bias is in the SORT, so a champ that loses to
    anyone still gets its most-specific counters rather than an empty list.
    """
    a_mean = colmeans.get(champ_a, 0.0)
    counters: list[tuple[str, float, float]] = []
    good: list[tuple[str, float, float]] = []
    for champ_b in roster:
        if champ_b == champ_a:
            continue
        sw_ba = m.get(champ_b, {}).get(champ_a)  # B-vs-A (B beats A when > 0)
        if sw_ba is not None and sw_ba > 0.0:
            rel = sw_ba - colmeans.get(champ_b, 0.0)
            # net_swing kept as champ_a-vs-B (negative); fall back to -sw_ba
            # when the A-vs-B cell is absent (engine asymmetry / a skipped pair).
            net = m.get(champ_a, {}).get(champ_b, -sw_ba)
            counters.append((champ_b, net, rel))
        sw_ab = m.get(champ_a, {}).get(champ_b)  # A-vs-B (A beats B when > 0)
        if sw_ab is not None and sw_ab > 0.0:
            rel = sw_ab + colmeans.get(champ_b, 0.0)
            good.append((champ_b, sw_ab, rel))

    counters.sort(key=lambda t: t[2], reverse=True)
    good.sort(key=lambda t: t[2], reverse=True)
    counters = counters[:top_k]
    good = good[:top_k]

    return {
        "counters": [
            {"champion": c, "net_swing": round(net, _ROUND), "rel": round(rel, _ROUND)}
            for c, net, rel in counters
        ],
        "good_against": [
            {"champion": c, "net_swing": round(net, _ROUND), "rel": round(rel, _ROUND)}
            for c, net, rel in good
        ],
    }


def targets_for_champion(
    snapshot: DataSnapshot,
    champ_a: str,
    roster: list[str],
    top_k: int,
) -> dict:
    """Convenience single-champ view: build the matrix + return champ_a's entry.

    Rebuilds the full matrix for ``roster`` (fine for small rosters / tests);
    the real generator calls ``build_matrix`` once via ``generate_payload``.
    """
    m = build_matrix(snapshot, roster, verbose=False)
    colmeans = {x: _colmean(m, x) for x in roster}
    return targets_from_matrix(m, champ_a, roster, top_k, colmeans)


def generate_payload(
    snapshot: DataSnapshot,
    roster: list[str],
    patch: str,
    top_k: int,
    *,
    verbose: bool = True,
) -> dict:
    """Build the full de-biased pick/ban targets payload for the roster."""
    m = build_matrix(snapshot, roster, verbose=verbose)
    colmeans = {x: _colmean(m, x) for x in roster}
    targets: dict[str, dict] = {
        champ_a: targets_from_matrix(m, champ_a, roster, top_k, colmeans)
        for champ_a in roster
    }
    return {
        "patch": patch,
        "mode": _MODE_KEY,
        "level": _LEVEL,
        "top_k": top_k,
        "ranking": "debiased_relative",
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
                  f"Re-run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_pickban_targets_generate.py`.",
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
