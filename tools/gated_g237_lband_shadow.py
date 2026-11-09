"""gated_g237_lband_shadow.py - read-only grader for G2-37 (LBAND1 live band).

G2-37 asks for a live eyeball of the LBAND1 personal-percentile benchmark band
(``core.live_benchmark_band``) on the deterministic-coaching surface and the
overlay. Three facts shape what can be graded (measured at source, s144 lane
gated c42):

- There is no surface. The only served-code consumer of the bander is the
  shadow writer ``dashboard/_deterministic_coaching.py``
  ``shadow_log_live_benchmark_band`` (called from ``dashboard/_state_builder.py``
  inside the deterministic block); no web/, rc-shell/ or overlay.py file reads a band. The
  eyeball half waits on a surface BUILD, which is headless work, not a drain.
- The only live record of the band is ``data/live_benchmark_band_shadow.jsonl``
  (``core/live_benchmark_band_shadow.py``). Its last live row predates the s144
  true-audit rewrite of the writer (``0ca196762``: one lock over the dedup check,
  the append and the sig update, plus strict field vocabularies), so whether the
  rewritten writer still appends clean, non-duplicated rows in a real SR game is
  UNMEASURED. That is the gradeable live half.
- A row proves the band COMPUTED and was LOGGED. It never proves that anything
  RENDERED (nothing can), so a PASS here is not a tick of the eyeball half.

Sub-command (READ-ONLY: no network, no write, no tick):

  shadow FILE --since ISO [--champion NAME] [--json]
      Grade the rows at or after --since (an ISO time WITH a UTC offset,
      compared as a time, not as text). Verdicts: NO_RESULT (no row since
      --since: no SR game reached a 10:00 / 15:00 window, the champion has
      fewer than 5 personal games, or the writer did not append), PASS (at
      least one row, at least one at checkpoint 10, every row clean, no
      consecutive duplicate), FAIL (any violation; reasons listed).

Exit 0 = PASS; 3 = NO_RESULT / FAIL; 2 = the file is missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Field vocabulary, restated from core/live_benchmark_band.py (_CHECKPOINTS,
# _TOLERANCE_S, _SOURCE_TAG), core/benchmarks.py rank_value and
# core/live_benchmark_band_shadow.py (_MAX_*); pinned by
# tests/test_gated_g237_lband_shadow.py.
CHECKPOINTS = {"10": (600.0, ("cs_at_10", "level_at_10")),
               "15": (900.0, ("cs_at_15",))}
TOLERANCE_S = 45.0
SOURCE_TAG = "live-bench"
BAND_VOCAB = frozenset({"below-p25", "p25-p50", "p50-p75", "above-p75"})
MAX_CHAMPION_CHARS = 64
MAX_CS = 10 ** 5
MIN_LEVEL, MAX_LEVEL = 1, 30

# Dashboard mode_keys the shadow writer treats as SR (restates
# dashboard/_deterministic_coaching.py _MODE_KEY_TO_LOWER, pinned by the tests).
SR_MODE_KEYS = frozenset({"sr", "client", "game"})

_MAX_REASONS = 20


def parse_since(text: str) -> datetime:
    """An ISO time that carries a UTC offset (a naive one is refused)."""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("--since needs a UTC offset, e.g. 2026-01-02T18:00:00-05:00")
    return dt


def _record_time(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _reject_constant(name: str):
    raise ValueError(f"non-strict JSON constant {name}")


def read_lines(path: Path) -> list[tuple[Optional[dict], bool]]:
    """Each non-blank line as (record or None, strict). Raises OSError."""
    out: list[tuple[Optional[dict], bool]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line, parse_constant=_reject_constant)
            strict = True
        except ValueError:
            try:
                rec = json.loads(line)
            except ValueError:
                rec = None
            strict = False
        out.append((rec if isinstance(rec, dict) else None, strict))
    return out


def _int_in(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def record_problems(rec: dict) -> list[str]:
    """Every way one row breaks the writer / bander contract (empty = clean)."""
    bad: list[str] = []
    if rec.get("mode") not in SR_MODE_KEYS:
        bad.append(f"mode {rec.get('mode')!r} is not SR-family")
    champ = rec.get("champion")
    if not (isinstance(champ, str) and champ.strip() == champ
            and 1 <= len(champ) <= MAX_CHAMPION_CHARS):
        bad.append("champion missing or out of vocabulary")
    cs, level = rec.get("cs"), rec.get("level")
    if cs is not None and not _int_in(cs, 0, MAX_CS):
        bad.append(f"cs {cs!r} out of vocabulary")
    if level is not None and not _int_in(level, MIN_LEVEL, MAX_LEVEL):
        bad.append(f"level {level!r} out of vocabulary")
    gt = _num(rec.get("game_time_s"))
    bands = rec.get("bands")
    if not isinstance(bands, list) or not bands:
        bad.append("no bands")
        return bad
    for b in bands:
        if not isinstance(b, dict):
            bad.append("a band is not an object")
            continue
        label = b.get("checkpoint")
        cp = CHECKPOINTS.get(label) if isinstance(label, str) else None
        if cp is None:
            bad.append(f"checkpoint {label!r} unknown")
            continue
        center, metrics = cp
        if b.get("metric") not in metrics:
            bad.append(f"metric {b.get('metric')!r} not at checkpoint {label}")
        if b.get("band") not in BAND_VOCAB:
            bad.append(f"band {b.get('band')!r} out of vocabulary")
        if b.get("source_tag") != SOURCE_TAG:
            bad.append("source_tag is not live-bench")
        value = _num(b.get("value"))
        if value is None:
            bad.append("band value not a finite number")
        else:
            # The bander bands the row's own live cs / level (band_metrics).
            live = cs if str(b.get("metric", "")).startswith("cs_") else level
            if live is not None and value != float(live):
                bad.append(f"band {b.get('metric')!r} value {value!r} is not the row's {live!r}")
        if gt is None or abs(gt - center) > TOLERANCE_S:
            bad.append(f"game_time_s {rec.get('game_time_s')!r} outside the {label}:00 window")
    return bad


def sig(rec: dict) -> str:
    """The writer's dedup identity (restates log_live_bands' sig)."""
    gt = _num(rec.get("game_time_s"))
    bucket = None if gt is None else int(gt // 5)
    bands = rec.get("bands") if isinstance(rec.get("bands"), list) else []
    key = tuple((b.get("checkpoint"), b.get("metric"), b.get("band"))
                for b in bands if isinstance(b, dict))
    return str((rec.get("mode"), rec.get("champion"), bucket,
                rec.get("cs"), rec.get("level"), key))


def grade(lines: list[tuple[Optional[dict], bool]], since: datetime,
          champion: Optional[str] = None) -> dict:
    """Grade the rows at or after ``since``. Pure; never raises on row content."""
    rows: list[dict] = []
    reasons: list[str] = []
    non_strict = 0
    times = [_record_time(rec.get("ts")) if rec is not None else None for rec, _ in lines]
    # The writer stamps each row with the real clock as it appends, so the file
    # is in time order. The window starts just after the last pre-since row
    # that comes BEFORE the first in-window row; from there on, a line the
    # writer could not have written whole (unparseable, not an object, or no
    # usable ts - a torn or interleaved append) is charged to the window, and
    # so is any ts that steps backward (a later pre-since row included).
    first_in = next((i for i, t in enumerate(times) if t is not None and t >= since),
                    len(times))
    start = 1 + max((i for i, t in enumerate(times[:first_in]) if t is not None),
                    default=-1)
    torn = backward = 0
    prev_t: Optional[datetime] = None
    for i in range(start, len(lines)):
        rec, strict = lines[i]
        when = times[i]
        if when is None:
            torn += 1
            continue
        if prev_t is not None and when < prev_t:
            backward += 1
        prev_t = when
        if when < since:
            continue
        if not strict:
            non_strict += 1
        rows.append(rec)
    if non_strict:
        reasons.append(f"{non_strict} row(s) are not strict JSON")
    if torn:
        reasons.append(f"{torn} line(s) in the window are unparseable or carry no ts")
    if backward:
        reasons.append(f"{backward} row(s) in the window step back in time")
    dups = 0
    checkpoints: dict[str, int] = {}
    champions: dict[str, int] = {}
    prev = None
    for i, rec in enumerate(rows):
        for p in record_problems(rec):
            reasons.append(f"row {i}: {p}")
        if champion is not None and rec.get("champion") != champion:
            reasons.append(f"row {i}: champion {rec.get('champion')!r} is not {champion!r}")
        s = sig(rec)
        if s == prev:
            dups += 1
        prev = s
        c = rec.get("champion")
        if isinstance(c, str):
            champions[c] = champions.get(c, 0) + 1
        for b in rec.get("bands") or []:
            if isinstance(b, dict) and isinstance(b.get("checkpoint"), str):
                checkpoints[b["checkpoint"]] = checkpoints.get(b["checkpoint"], 0) + 1
    if dups:
        reasons.append(f"{dups} consecutive duplicate row(s) (same writer sig)")
    if not rows:
        verdict = "NO_RESULT"
    elif reasons or not checkpoints.get("10"):
        verdict = "FAIL"
        if not checkpoints.get("10"):
            reasons.append("no band at checkpoint 10")
    else:
        verdict = "PASS"
    total = len(reasons)
    return {"verdict": verdict, "rows": len(rows), "duplicates": dups,
            "checkpoints": checkpoints, "champions": champions,
            "reasons": reasons[:_MAX_REASONS], "reasons_total": total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("shadow", help="grade the LBAND1 shadow rows since a time")
    sp.add_argument("file", type=Path)
    sp.add_argument("--since", required=True, type=parse_since)
    sp.add_argument("--champion", default=None)
    sp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        lines = read_lines(args.file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"UNREADABLE {args.file}: {exc.__class__.__name__}")
        return 2
    result = grade(lines, args.since, args.champion)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['verdict']} rows={result['rows']} "
              f"duplicates={result['duplicates']} checkpoints={result['checkpoints']}")
        for r in result["reasons"]:
            print(f"  - {r}")
        if result["reasons_total"] > len(result["reasons"]):
            print(f"  ... {result['reasons_total'] - len(result['reasons'])} more")
    return 0 if result["verdict"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
