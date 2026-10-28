"""gated_lx03_session_check.py - read one live-session recording for the LX-03 drain.

LX-03 (RM-605) asks whether a REAL match, with ``RC_SESSION_RECORDER=1`` set in
the RC process, lands ``logs/sessions/<gameId>.jsonl`` carrying the real
gameId, the ``config_key`` from game.cfg and fresh vision_state. Checking that
by hand means re-deriving the header, the seq run and the game_time run every
pass; this tool prints it in ONE command.

It is READ-ONLY: it parses the file through the recorder's own reader
(``core.live_session_recorder.read_session``) and prints. It never writes,
moves, locks or deletes anything under ``logs/sessions/``, and it never ticks a
row - its output is the INPUT to the four-part evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. A replayed or
hand-built file passes these checks just as well; that is the substitution the
LX-03 row names, and why a real match is the only thing that closes it.

WHAT IT REPORTS:
  - the file stem kind: ``nogameid`` (the recorder had no LCU game id and wrote
    ``nogameid-<unix_s>``) or ``gameid``; with ``--expect-game-id`` whether the
    stem equals the game id the drain read from the LCU. The stem itself is
    printed only with ``--show-id`` (RM-906: a real game id never goes into a
    tracked file, so the default output is safe to paste).
  - the header: schema, config_key, patch, ENGINE_VERSION, mode_key; with
    ``--expect-config-key`` (or ``--live-config-key``, which reads
    ``core.hud_settings.read_hud_settings()`` now) whether config_key matches,
    and whether it is the ``unknown`` fallback.
  - frames: count, whether seq runs 0..n-1 with no gap, game_time first / last,
    how many steps went backwards and how many were null, the captured_at span,
    how many frames carry a non-empty snapshot and how many carry vision_state.

USAGE
    python tools/gated_lx03_session_check.py logs/sessions/<file>.jsonl
    python tools/gated_lx03_session_check.py <file> --live-config-key --json
    python tools/gated_lx03_session_check.py <file> --expect-game-id <id>

Exit 2 = not a file or not a readable session (bad header, newer schema);
exit 3 = a value too deeply nested to print.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live_session_recorder import SessionFormatError, read_session  # noqa: E402

NOGAMEID_PREFIX = "nogameid-"
UNKNOWN_CONFIG_KEY = "unknown"
HEADER_FIELDS = ("schema", "config_key", "patch", "ENGINE_VERSION", "mode_key")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def live_config_key() -> Optional[str]:
    """config_key as core.hud_settings reads it right now, None on failure."""
    try:
        from core.hud_settings import read_hud_settings
        v = read_hud_settings().get("config_key")
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, str) else None


def check(path: Path, expect_game_id: Optional[str] = None,
          expect_config_key: Optional[str] = None) -> dict:
    """Summarise one session file. Raises SessionFormatError on a bad file."""
    header, frames = read_session(path)
    stem = path.stem
    out: dict = {
        "stem": stem,
        "stem_kind": "nogameid" if stem.startswith(NOGAMEID_PREFIX) else "gameid",
        "game_id_match": None if expect_game_id is None else stem == expect_game_id,
        "header": {k: header.get(k) for k in HEADER_FIELDS},
    }
    ck = header.get("config_key")
    out["config_key_unknown"] = ck is None or ck == UNKNOWN_CONFIG_KEY
    out["config_key_expected"] = expect_config_key
    out["config_key_match"] = (None if expect_config_key is None
                               else ck == expect_config_key)

    seqs = [f.get("seq") for f in frames]
    out["frames"] = len(frames)
    out["seq_contiguous"] = seqs == list(range(len(frames)))
    times = [_num(f.get("game_time")) for f in frames]
    known = [t for t in times if t is not None]
    out["game_time_null"] = len(times) - len(known)
    out["game_time_first"] = known[0] if known else None
    out["game_time_last"] = known[-1] if known else None
    out["game_time_backsteps"] = sum(1 for a, b in zip(known, known[1:]) if b < a)
    caps = [c for c in (_num(f.get("captured_at")) for f in frames) if c is not None]
    out["captured_span_s"] = (max(caps) - min(caps)) if caps else None
    out["frames_with_snapshot"] = sum(
        1 for f in frames if isinstance(f.get("snapshot"), dict) and f["snapshot"])
    out["frames_with_vision_state"] = sum(
        1 for f in frames if isinstance(f.get("vision_state"), dict))
    return out


def render(s: dict, show_id: bool = False) -> str:
    """Human-readable text summary. The stem is shown only with show_id."""
    h = s.get("header") or {}
    lines = [
        f"file stem_kind={s['stem_kind']}"
        + (f" stem={s['stem']}" if show_id else "")
        + f" game_id_match={s['game_id_match']}",
        "header " + " ".join(f"{k}={h.get(k)}" for k in HEADER_FIELDS),
        f"config_key_unknown={s['config_key_unknown']} "
        f"expected={s['config_key_expected']} match={s['config_key_match']}",
        f"frames {s['frames']} seq_contiguous={s['seq_contiguous']} "
        f"with_snapshot={s['frames_with_snapshot']} "
        f"with_vision_state={s['frames_with_vision_state']}",
        f"game_time {s['game_time_first']} .. {s['game_time_last']} "
        f"null={s['game_time_null']} backsteps={s['game_time_backsteps']} "
        f"captured_span_s={s['captured_span_s']}",
    ]
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="read-only LX-03 check of one live-session recording")
    ap.add_argument("session", help="logs/sessions/<gameId>.jsonl")
    ap.add_argument("--expect-game-id", default=None,
                    help="the LCU game id the drain read; reports stem equality")
    ck = ap.add_mutually_exclusive_group()
    ck.add_argument("--expect-config-key", default=None)
    ck.add_argument("--live-config-key", action="store_true",
                    help="compare against core.hud_settings.read_hud_settings() now")
    ap.add_argument("--show-id", action="store_true",
                    help="print the file stem (a real game id: never paste it into a tracked file)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    p = Path(args.session)
    if not p.is_file():
        print("not a file (path not echoed: its stem may be a real game id)", file=sys.stderr)
        return 2
    expect_ck = live_config_key() if args.live_config_key else args.expect_config_key
    try:
        s = check(p, args.expect_game_id, expect_ck)
    except (SessionFormatError, OSError, RecursionError) as exc:
        detail = "" if isinstance(exc, OSError) else f": {exc}"  # OSError text repeats the path
        print(f"not a readable session: {type(exc).__name__}{detail}", file=sys.stderr)
        return 2
    if not args.show_id:
        s["stem"] = None
    try:
        out = (json.dumps(s, indent=1, ensure_ascii=True) if args.json
               else render(s, show_id=args.show_id))
    except (ValueError, RecursionError):
        print("summary not printable (pathologically nested value)", file=sys.stderr)
        return 3
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
