#!/usr/bin/env python
# arch: RM-158 data half - SR-contaminated ARENA row detector + purge over the HZ-C1 shadow corpus | section=tools | frozen=no
"""RM-158 DATA HALF - detect and purge SR-derived ``mode=arena`` rows from the
HZ-C1 precomputed-choice shadow corpus (``data/hz_choice_shadow.jsonl``).

WHY THE ROWS ARE WRONG
    ``core.hz_choice_shadow`` records, per real in-game tick, what the
    PRECOMPUTED laning table would have offered. For ARENA it read
    ``laning_scenarios_arena.json``. RM-158 root-caused that file: ARENA had no
    gross-income row in ``core.lead_projection``, so at schema v3 (itemless) the
    generator had ZERO mode-differentiating inputs left and wrote the SR content
    under an arena header. Measured on both shipped patches - the ``scenarios``
    payload of the arena table is byte-identical to the sibling SR table at
    16.13.1 and at 16.12.1 - so every arena row in this corpus carries an SR
    precompute answer. Averaging them into any "arena" figure reports SR.

THE PINNED DETECTABLE SIGNATURE (content-level, not provenance-level)
    The one cell field the corrected ARENA income row actually moves is the
    ``economy`` block: gold at band = ``minutes_for_level(level) * income``, and
    the spike label is that gold read off the shared spike ladder. The shadow
    row surfaces exactly that label through ``_recall_outcome`` in
    ``core.precomputed_laning_coach`` - the ``"... toward <spike>"`` /
    ``"... next spike <spike>"`` tail of the recall choice.

    At SR income 450/min vs ARENA income 600/min the labels DIFFER at two of the
    generated bands:

        L2   SR "component"   vs ARENA "first_item"
        L11  SR "three_item"  vs ARENA "complete"

    and AGREE at L6 ("two_item"), so L6 rows are not decidable by content. L16
    is not generated; the reader applies the item-370 descend-only L16 -> L11
    fallback (``core/precomputed_laning_coach.py:511``), so an L16 row carries
    the L11 cell and IS decidable.

    A row is therefore PROVEN SR-derived when its spike label equals the SR
    label for its effective band at a band where SR and ARENA disagree. This is
    a positive content proof: no correctly-generated arena table can emit it.

DROP, NOT RELABEL
    Relabelling these rows ``mode=sr`` is indefensible. Only the PRECOMPUTE half
    of each row is SR content; the native half (``native_action`` - e.g.
    "SPECTATE ROUND" - plus the champion / band / game-time state) came from a
    real Arena game. Moving them to the sr bucket would inject Arena game states
    into the SR measurement, trading one contamination for a worse one. They
    also cannot be repaired in place: repairing them needs a correct arena
    table, which does not exist yet (that is the other, still-open half of
    RM-158). DROP is the honest action, and the whole ``mode=arena`` bucket goes
    - not only the content-proven subset - because every row in it was served by
    a table whose payload is hash-proven identical to SR's.

USAGE
    python tools/hz_shadow_arena_contamination.py --report
    python tools/hz_shadow_arena_contamination.py --purge --backup <path>

The purge is byte-preserving for every kept line (binary line IO, original CRLF
kept, unparseable lines passed through untouched) and atomic (tmp + os.replace).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import lead_projection as _lead  # noqa: E402

ARENA_MODE = "arena"

# The generated bands (L16 is not generated - see the descend-only fallback).
GENERATED_BANDS: tuple = ("L2", "L6", "L11")
BAND_LEVELS: dict = {"L2": 2, "L6": 6, "L11": 11, "L16": 16}
# item-370 descend-only fallback: an L16 tick reads the L11 cell.
BAND_FALLBACK: dict = {"L16": "L11"}

# "buy Runaan's Hurricane (2500g) toward component" / "900g banked; next spike component"
_SPIKE_RE = re.compile(r"(?:toward|next spike) ([a-z_]+)")


def effective_band(band: object) -> Optional[str]:
    """The band whose CELL a tick at ``band`` actually reads, or None."""
    b = str(band or "")
    b = BAND_FALLBACK.get(b, b)
    return b if b in GENERATED_BANDS else None


def spike_label_for(band: str, mode: str) -> Optional[str]:
    """The economy spike label the generator writes for ``band`` under ``mode``.

    Reproduces core.laning_scenario_precompute.economy_cell's gold path:
    expected_gold_earned(minutes_for_level(level), mode) -> next_spike label.
    """
    level = BAND_LEVELS.get(str(band))
    if level is None:
        return None
    gold = _lead.expected_gold_earned(_lead.minutes_for_level(level), mode)
    return str(_lead.next_spike(gold)[0])


def discriminating_bands() -> dict:
    """{band: (sr_label, arena_label)} for bands where the two labels differ."""
    out: dict = {}
    for band in GENERATED_BANDS:
        sr = spike_label_for(band, "SR")
        arena = spike_label_for(band, "ARENA")
        if sr is not None and arena is not None and sr != arena:
            out[band] = (sr, arena)
    return out


def row_spike_label(row: dict) -> Optional[str]:
    """The spike label carried by the row's recall choice, or None."""
    for choice in row.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        match = _SPIKE_RE.search(str(choice.get("expected_outcome") or ""))
        if match:
            return match.group(1)
    return None


def is_sr_derived_arena_row(row: object) -> bool:
    """True when ``row`` is a mode=arena row proven to carry SR economy content.

    Positive proof only: returns False for a row whose band cannot discriminate
    (L6) or that carries no spike label (an uncovered tick). Such rows are still
    unfit as arena measurements - see the module docstring - but this predicate
    deliberately claims only what the content proves.
    """
    if not isinstance(row, dict) or row.get("mode") != ARENA_MODE:
        return False
    band = effective_band(row.get("band"))
    if band is None:
        return False
    pair = discriminating_bands().get(band)
    if pair is None:
        return False
    sr_label, _arena_label = pair
    return row_spike_label(row) == sr_label


def scan(corpus: Path) -> dict:
    """Census the corpus. Returns counts + the per-band proven breakdown."""
    stats = {
        "total_lines": 0,
        "unparseable": 0,
        "by_mode": {},
        "arena_rows": 0,
        "arena_proven_sr": 0,
        "arena_proven_by_band": {},
        "arena_undecidable": 0,
    }
    with open(corpus, "rb") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            stats["total_lines"] += 1
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001 - a torn append is data, not a crash
                stats["unparseable"] += 1
                continue
            mode = str(row.get("mode"))
            stats["by_mode"][mode] = stats["by_mode"].get(mode, 0) + 1
            if mode != ARENA_MODE:
                continue
            stats["arena_rows"] += 1
            if is_sr_derived_arena_row(row):
                stats["arena_proven_sr"] += 1
                band = str(row.get("band"))
                stats["arena_proven_by_band"][band] = (
                    stats["arena_proven_by_band"].get(band, 0) + 1
                )
            else:
                stats["arena_undecidable"] += 1
    return stats


def purge(corpus: Path, backup: Optional[Path] = None) -> dict:
    """Drop every mode=arena line, atomically. Every kept line is byte-identical.

    Returns {"dropped": n, "kept": n, "backup": str|None}.
    """
    if backup is not None:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(corpus, backup)
    tmp = corpus.with_suffix(corpus.suffix + ".tmp")
    dropped = 0
    kept = 0
    with open(corpus, "rb") as src, open(tmp, "wb") as dst:
        for raw in src:
            line = raw.strip()
            drop = False
            if line:
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 - pass a torn append through
                    row = None
                if isinstance(row, dict) and row.get("mode") == ARENA_MODE:
                    drop = True
            if drop:
                dropped += 1
                continue
            kept += 1
            dst.write(raw)
    os.replace(tmp, corpus)
    return {"dropped": dropped, "kept": kept,
            "backup": str(backup) if backup else None}


CORPUS_ENV = "RC_HZ_SHADOW_CORPUS"
CORPUS_RELPATH = ("data", "hz_choice_shadow.jsonl")


def live_corpus_path() -> Path:
    """The live HZ-C1 corpus, resolved WITHOUT reading a patchable constant.

    ``tests/conftest.py`` autouse-monkeypatches ``SHADOW_PATH`` on every module
    that defines one, to a tmp dir, for EVERY test - so importing
    ``core.hz_choice_shadow.SHADOW_PATH`` here would make the corpus guard skip
    itself unconditionally under pytest (measured: it did). This recomputes the
    same location from the repo root, which is exactly how
    ``core.hz_choice_shadow`` derives it. ``RC_HZ_SHADOW_CORPUS`` overrides, so
    a run from a worktree can point at the main checkout's machine-local file.
    """
    override = os.environ.get(CORPUS_ENV, "").strip()
    if override:
        return Path(override)
    return _ROOT.joinpath(*CORPUS_RELPATH)


def _default_corpus() -> Path:
    return live_corpus_path()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="", help="Shadow jsonl (default: the live path).")
    ap.add_argument("--purge", action="store_true",
                    help="Drop every mode=arena row (default: report only).")
    ap.add_argument("--backup", default="",
                    help="Copy the corpus here before purging.")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus) if args.corpus else _default_corpus()
    if not corpus.exists():
        print(f"corpus not found: {corpus}")
        return 2

    bands = discriminating_bands()
    print(f"corpus            {corpus}")
    print(f"size_bytes        {corpus.stat().st_size}")
    print(f"income SR/ARENA   {_lead.gold_income_per_min('SR')} / "
          f"{_lead.gold_income_per_min('ARENA')}")
    print(f"discriminating    {bands}")
    stats = scan(corpus)
    for key in ("total_lines", "unparseable", "by_mode", "arena_rows",
                "arena_proven_sr", "arena_proven_by_band", "arena_undecidable"):
        print(f"{key:22s} {stats[key]}")

    if args.purge:
        if not bands:
            print("REFUSING to purge: no discriminating band, so the SR/ARENA "
                  "income rows are not distinct - check core.lead_projection.")
            return 2
        result = purge(corpus, Path(args.backup) if args.backup else None)
        print(f"purged            {result}")
        after = scan(corpus)
        print(f"after arena_rows  {after['arena_rows']}")
        print(f"after total_lines {after['total_lines']}")
        print(f"after unparseable {after['unparseable']}")
        if after["arena_rows"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
