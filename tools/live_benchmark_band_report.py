#!/usr/bin/env python
# arch: LBAND1 validation report over the live-benchmark-band shadow log | section=tools | frozen=no
"""LBAND1 shadow-validation report - the flip-readiness gate for the live
personal-percentile benchmark bander (charter 4b "do not flip blind").

LBAND1 (``core.live_benchmark_band`` banded, ``core.live_benchmark_band_shadow``
logged -> data/live_benchmark_band_shadow.jsonl) records, on every real in-game
SR tick where a checkpoint band actually fired, what band the player's live
CS / level fell into versus their OWN historical percentile distribution on the
same champion. Before any coach surfaces those bands, the operator needs to know:

  * VOLUME - how many real-game band firings have accrued (a thin sample is not
    enough to judge the band's usefulness; LBAND1 only fires in a ~90s window
    per game, so this accrues slowly).
  * CHECKPOINT / METRIC split - which checkpoints (10 / 15) and metrics
    (cs_at_10 / level_at_10 / cs_at_15) are exercised by real games.
  * BAND DISTRIBUTION - the spread across below-p25 / p25-p50 / p50-p75 /
    above-p75. A degenerate distribution (e.g. always above-p75) means the band
    is uninformative - the player always sits in one bucket vs their own median -
    and a flip would surface a constant, useless line. ``top_band_skew`` flags it.
  * PER-CHAMPION firings - which champions real games exercised, so coverage
    gaps are visible.

READ-ONLY (no engine, no network, no write). Fail-soft: a missing / empty /
malformed log yields a zeroed summary, never an exception - the same robustness
the shadow writer promises. Mirrors tools/hz_shadow_report.py.

USAGE
    python tools/live_benchmark_band_report.py            # human summary
    python tools/live_benchmark_band_report.py --json     # machine-readable
    python tools/live_benchmark_band_report.py --path X   # explicit log path
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _ROOT / "data" / "live_benchmark_band_shadow.jsonl"

# Canonical band order, worst-to-best, for a stable human + JSON rendering.
_BAND_ORDER = ("below-p25", "p25-p50", "p50-p75", "above-p75")


def load_jsonl(path: Path) -> list[dict]:
    """Read a jsonl file into a list of dicts (fail-soft to []).

    A missing file or any unreadable / malformed line is skipped, never raised."""
    out: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def summarize(records: list[dict]) -> dict:
    """Volume + checkpoint/metric split + band distribution + per-champion +
    a top-band-skew degeneracy flag, over the LBAND1 shadow records."""
    by_checkpoint: Counter = Counter()
    by_metric: Counter = Counter()
    by_band: Counter = Counter()
    by_champ: Counter = Counter()
    with_native = 0

    for r in records:
        champ = r.get("champion")
        if champ:
            by_champ[str(champ)] += 1
        if r.get("native_action"):
            with_native += 1
        for b in (r.get("bands") or []):
            if not isinstance(b, dict):
                continue
            cp = b.get("checkpoint")
            metric = b.get("metric")
            band = b.get("band")
            if cp is not None:
                by_checkpoint[str(cp)] += 1
            if metric:
                by_metric[str(metric)] += 1
            if band:
                by_band[str(band)] += 1

    band_fires = sum(by_band.values())
    skew: Optional[dict] = None
    if band_fires:
        top_band, top_n = by_band.most_common(1)[0]
        skew = {"band": top_band, "pct": round(100.0 * top_n / band_fires, 1)}

    ordered_bands: dict = {k: by_band.get(k, 0) for k in _BAND_ORDER}
    for k, v in by_band.items():
        if k not in ordered_bands:
            ordered_bands[k] = v

    return {
        "records": len(records),
        "band_fires": band_fires,
        "with_native_action": with_native,
        "by_checkpoint": dict(by_checkpoint),
        "by_metric": dict(by_metric),
        "by_band": ordered_bands,
        "by_champion": dict(by_champ),
        "top_band_skew": skew,
    }


def _human(summary: dict) -> str:
    lines = ["LBAND1 shadow-validation report (do-not-flip-blind)"]
    lines.append(f"  records: {summary['records']}  band fires: {summary['band_fires']}"
                 f"  with native action: {summary['with_native_action']}")
    if not summary["records"]:
        lines.append("  (no real-game band firings accrued yet - play SR games to populate)")
        return "\n".join(lines)
    lines.append(f"  by checkpoint: {summary['by_checkpoint']}")
    lines.append(f"  by metric:     {summary['by_metric']}")
    lines.append(f"  by band:       {summary['by_band']}")
    skew = summary["top_band_skew"]
    if skew:
        flag = "  <- DEGENERATE (uninformative band)" if skew["pct"] >= 80.0 else ""
        lines.append(f"  top-band skew: {skew['band']} {skew['pct']}%{flag}")
    champs = summary["by_champion"]
    lines.append(f"  champions exercised: {len(champs)} -> {champs}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LBAND1 shadow-validation report.")
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help="shadow jsonl path (default data/live_benchmark_band_shadow.jsonl)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON")
    args = ap.parse_args(argv)

    summary = summarize(load_jsonl(Path(args.path)))
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(_human(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
