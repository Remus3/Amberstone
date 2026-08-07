#!/usr/bin/env python
# arch: RM-158 data half - SR-derived ARENA precompute detector + provenance flagger over the HZ-C1 shadow corpus | section=tools | frozen=no
"""RM-158 DATA HALF - flag SR-derived ``mode=arena`` PRECOMPUTE in the HZ-C1
precomputed-choice shadow corpus (``data/hz_choice_shadow.jsonl``).

WHY THE PRECOMPUTE IS WRONG
    ``core.hz_choice_shadow`` records, per real in-game tick, what the
    PRECOMPUTED laning table would have offered. For ARENA it read
    ``laning_scenarios_arena.json``. RM-158 root-caused that file: ARENA had no
    gross-income row in ``core.lead_projection``, so at schema v3 (itemless) the
    generator had ZERO mode-differentiating inputs left and wrote the SR content
    under an arena header. Measured on both shipped patches - the ``scenarios``
    payload of the arena table is byte-identical to the sibling SR table at
    16.13.1 and at 16.12.1 - so the arena precompute column is SR content.

FLAG, DO NOT DELETE. THE ROW IS TWO HALVES.
    Each record carries a PRECOMPUTE half (``choices``, ``covered``,
    ``verdict_blocks``) and a NATIVE half (``native_action``, champion, enemy,
    band, level, ``game_time_s``, ``item_count``). Only the precompute half is
    SR content. The native half is a genuine Arena observation and deleting it
    destroys data that was never contaminated - measured: 504 of the 1148 arena
    rows are coverage misses with ``choices == []``, i.e. ZERO precompute
    content and nothing to correct. Relabelling ``mode`` to ``sr`` would be
    worse still (it would inject Arena game states into the SR bucket), but
    nothing about the defect requires touching ``mode`` at all.

    So: ``mode`` is left alone, every row is kept, and the rows whose precompute
    column is SR-derived get ``precompute_source: "sr_copy_rm158"``. A consumer
    excludes the poisoned column with one key test and keeps the observation.

THE PINNED DETECTABLE SIGNATURE (content-level, positive proof)
    The corrected ARENA income row (600/min vs SR 450/min) moves the ``economy``
    block, and the reader surfaces all three of its fields into the record:

      * ``gold_at_band`` - the leading "9000g banked" of the recall choice, but
        ONLY in the no-next-item render form (``_recall_outcome``). Strongest
        axis where present: it differs at every band and both mana states.
      * ``next_spike`` - the ``"... toward <spike>"`` / ``"... next spike
        <spike>"`` tail of the recall choice (``_recall_outcome``).
      * ``recall`` - the recall choice LABEL, "Recall now" / "Back soon"
        (``_RECALL_LABELS`` in ``core.precomputed_laning_coach``).

    Reading only ``next_spike`` under-detects: it agrees at L2 and L11.
    ``recall`` decides at every full-mana band. Measured over the generated
    bands at ``mana_state="full"`` (every covered arena row in the corpus is
    full-mana):

        band  next_spike SR / ARENA        recall SR / ARENA
        L2    component  / component       back_soon  / hold
        L6    two_item   / first_item      recall_now / back_soon
        L11   three_item / three_item      back_soon  / recall_now
        L16   not generated - reads the L11 cell (item-370 descend-only
              fallback, core/precomputed_laning_coach.py:511)

    That table is NOT hand-maintained - ``economy_expectation`` calls the
    generator's own ``economy_cell``, so it tracks the model. It moved once, on
    2026-08-06, when the RM-158 RESIDUAL landed: the band MINUTE became per-mode
    alongside the income RATE (ARENA spawns at level 3 and levels at 0.70/min,
    so it reaches every band far sooner and has banked LESS gold at it, where
    the old mode-blind SR curve charged it the SR minute). The axes swapped
    roles - next_spike used to decide at L2/L11 and agree at L6, now the
    reverse - but the detector is strictly stronger: recall now decides at all
    three bands instead of one. RE-MEASURED against the live corpus after the
    change: the SAME 644 rows are proven, ``arena_unflagged_sr`` 0 and
    ``arena_undecided_with_precompute`` 0, so the flagging already applied to
    the corpus stays exactly correct and no re-flag is owed.

    A row is PROVEN SR-derived when either field equals the SR value at a band
    and mana state where SR and ARENA disagree. Between them the two axes cover
    every covered row in the corpus; ``low`` mana collapses ``recall`` to
    ``recall_now`` under both modes, so a low-mana L11 row would be undecidable
    on the label axes - none exist today, ``gold_at_band`` still decides where
    the row rendered it, and the detector reports an undecided row as undecided
    rather than guessing.

USAGE
    python tools/hz_shadow_arena_contamination.py --report
    python tools/hz_shadow_arena_contamination.py --flag --source <backup> --backup <path>

Writes are atomic (tmp + os.replace) and byte-preserving for every row that is
not flagged: binary line IO, original CRLF kept, unparseable lines passed
through untouched. A flagged row is re-serialised with ``json.dumps`` defaults,
which is byte-identical to the writer's own format (verified over all 1148 arena
rows) plus the one new key.
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

from core import laning_scenario_precompute as _gen  # noqa: E402
from core.hz_choice_shadow import (  # noqa: E402
    PRECOMPUTE_SOURCE_KEY,
    SR_COPY_TAG,
)
from core.precomputed_laning_coach import _RECALL_LABELS  # noqa: E402

ARENA_MODE = "arena"

# Bands actually generated into the table (L16 is not - see the fallback below).
GENERATED_BANDS: tuple = tuple(_gen.GEN_BANDS)
# item-370 descend-only fallback: an L16 tick reads the L11 cell.
BAND_FALLBACK: dict = {"L16": "L11"}

# "buy Runaan's Hurricane (2500g) toward component" / "900g banked; next spike component"
_SPIKE_RE = re.compile(r"(?:toward|next spike) ([a-z_]+)")
# The no-next-item render form leads with gold_at_band: "9000g banked; ...".
_GOLD_RE = re.compile(r"^(\d+)g banked")
# "Recall now" -> "recall_now", "Back soon" -> "back_soon".
_LABEL_TO_RECALL: dict = {v: k for k, v in _RECALL_LABELS.items()}

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


def effective_band(band: object) -> Optional[str]:
    """The band whose CELL a tick at ``band`` actually reads, or None."""
    b = str(band or "")
    b = BAND_FALLBACK.get(b, b)
    return b if b in GENERATED_BANDS else None


def economy_expectation(band: str, mana_state: str) -> dict:
    """``{"sr": economy_cell(...SR), "arena": economy_cell(...ARENA)}``.

    Calls the generator's own ``economy_cell``, so the expectation cannot drift
    away from what a regenerated table would actually contain.
    """
    mana = str(mana_state or "full")
    return {
        "sr": _gen.economy_cell(band, mana, mode="SR"),
        "arena": _gen.economy_cell(band, mana, mode="ARENA"),
    }


def row_spike_label(row: dict) -> Optional[str]:
    """The ``next_spike`` token carried by the row's recall choice, or None."""
    for choice in row.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        match = _SPIKE_RE.search(str(choice.get("expected_outcome") or ""))
        if match:
            return match.group(1)
    return None


def row_gold_at_band(row: dict) -> Optional[float]:
    """``gold_at_band`` when the recall choice used the no-next-item render form.

    ``_recall_outcome`` prints the raw banked gold only when the build layer
    supplied no next item ("9000g banked; next spike three_item"); with an item
    it prints the item cost instead and the gold is not recoverable. Present on
    179 of the corpus's arena choice lines - and it discriminates at EVERY band
    and BOTH mana states, which neither other axis does.
    """
    for choice in row.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        match = _GOLD_RE.match(str(choice.get("expected_outcome") or "").strip())
        if match:
            return float(match.group(1))
    return None


def row_recall_label(row: dict) -> Optional[str]:
    """The ``recall`` verdict behind the row's recall choice LABEL, or None."""
    for choice in row.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        recall = _LABEL_TO_RECALL.get(str(choice.get("label") or ""))
        if recall:
            return recall
    return None


def sr_derived_reason(row: object) -> Optional[str]:
    """The axis that PROVES ``row`` carries SR economy content, or None.

    Returns ``"next_spike"`` / ``"recall"`` (whichever decides first), or None
    when the row is not arena, carries no precompute, or sits at a band+mana
    where SR and ARENA agree on both axes. Positive proof only - None means
    "not proven", never "proven clean".
    """
    if not isinstance(row, dict) or row.get("mode") != ARENA_MODE:
        return None
    band = effective_band(row.get("band"))
    if band is None:
        return None
    if not (row.get("choices") or []):
        return None
    try:
        exp = economy_expectation(band, row.get("mana_state"))
    except Exception:  # noqa: BLE001 - unknown band/mana -> undecided
        return None
    for axis, reader in (("gold_at_band", row_gold_at_band),
                         ("next_spike", row_spike_label),
                         ("recall", row_recall_label)):
        sr_value = exp["sr"].get(axis)
        arena_value = exp["arena"].get(axis)
        if sr_value == arena_value:
            continue                      # this axis cannot decide here
        if reader(row) == sr_value:
            return axis
    return None


def is_sr_derived_arena_row(row: object) -> bool:
    """True when ``row``'s precompute column is proven SR content."""
    return sr_derived_reason(row) is not None


def is_flagged(row: object) -> bool:
    """True when ``row`` already carries the RM-158 provenance tag."""
    return (isinstance(row, dict)
            and row.get(PRECOMPUTE_SOURCE_KEY) == SR_COPY_TAG)


def scan(corpus: Path) -> dict:
    """Census the corpus, including the flagged / unflagged arena split."""
    stats = {
        "total_lines": 0,
        "unparseable": 0,
        "by_mode": {},
        "arena_rows": 0,
        "arena_with_precompute": 0,
        "arena_native_only": 0,
        "arena_proven_sr": 0,
        "arena_proven_by_axis": {},
        "arena_proven_by_band": {},
        "arena_undecided_with_precompute": 0,
        "arena_flagged": 0,
        "arena_unflagged_sr": 0,
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
            has_precompute = bool(row.get("choices"))
            stats["arena_with_precompute" if has_precompute
                  else "arena_native_only"] += 1
            if is_flagged(row):
                stats["arena_flagged"] += 1
            reason = sr_derived_reason(row)
            if reason is None:
                if has_precompute:
                    stats["arena_undecided_with_precompute"] += 1
                continue
            stats["arena_proven_sr"] += 1
            stats["arena_proven_by_axis"][reason] = (
                stats["arena_proven_by_axis"].get(reason, 0) + 1)
            band = str(row.get("band"))
            stats["arena_proven_by_band"][band] = (
                stats["arena_proven_by_band"].get(band, 0) + 1)
            if not is_flagged(row):
                stats["arena_unflagged_sr"] += 1
    return stats


def flag_rows(src: Path, dst: Path, backup: Optional[Path] = None) -> dict:
    """Write ``dst`` from ``src``, tagging every proven SR-derived arena row.

    Byte-preserving for every line that is NOT newly tagged, including torn
    appends and CRLF. Atomic (tmp + os.replace). Idempotent - a row that already
    carries the tag is left byte-identical.
    """
    if backup is not None and dst.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dst, backup)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tagged = 0
    already = 0
    untouched = 0
    with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
        for raw in fsrc:
            line = raw.strip()
            row = None
            if line:
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 - pass a torn append through
                    row = None
            if isinstance(row, dict) and sr_derived_reason(row) is not None:
                if is_flagged(row):
                    already += 1
                    fdst.write(raw)
                    continue
                row[PRECOMPUTE_SOURCE_KEY] = SR_COPY_TAG
                eol = raw[len(raw.rstrip(b"\r\n")):]
                fdst.write(json.dumps(row).encode("utf-8") + eol)
                tagged += 1
                continue
            untouched += 1
            fdst.write(raw)
    os.replace(tmp, dst)
    return {"tagged": tagged, "already_tagged": already, "untouched": untouched,
            "backup": str(backup) if backup else None}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="", help="Shadow jsonl (default: the live path).")
    ap.add_argument("--flag", action="store_true",
                    help="Tag proven SR-derived arena rows (default: report only).")
    ap.add_argument("--source", default="",
                    help="Read from here instead of the corpus (restore + flag).")
    ap.add_argument("--backup", default="",
                    help="Copy the corpus here before rewriting it.")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus) if args.corpus else live_corpus_path()
    source = Path(args.source) if args.source else corpus
    if not source.exists():
        print(f"source not found: {source}")
        return 2

    print(f"corpus            {corpus}")
    print(f"source            {source}")
    print(f"source_bytes      {source.stat().st_size}")
    for band in GENERATED_BANDS:
        exp = economy_expectation(band, "full")
        print(f"expect {band:4s} full  SR {exp['sr']['next_spike']:>10s}/"
              f"{exp['sr']['recall']:<10s}  ARENA {exp['arena']['next_spike']:>10s}/"
              f"{exp['arena']['recall']}")
    stats = scan(source)
    for key in sorted(stats):
        print(f"{key:32s} {stats[key]}")

    if args.flag:
        result = flag_rows(source, corpus,
                           Path(args.backup) if args.backup else None)
        print(f"flagged           {result}")
        after = scan(corpus)
        for key in ("total_lines", "unparseable", "by_mode", "arena_rows",
                    "arena_flagged", "arena_unflagged_sr"):
            print(f"after {key:26s} {after[key]}")
        if after["arena_unflagged_sr"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
