"""gated_tft_qa_summary.py - summarise one tft_qa recorder match directory.

The interactive TFT QA recorder writes one directory per match under
``ops/runtime/tft_qa/<yyyymmdd-hhmmss>/`` (MATCH_START.json, states.jsonl,
events.jsonl, frames.jsonl, game_id.txt). Lane 9 (Headless-Gated) reads that
evidence mid-game to answer what RC showed while a real TFT game was up. Doing
it by hand means re-deriving the same timeline every pass; this tool prints it
in ONE command.

It is READ-ONLY: it opens the recorder files for reading and prints. It never
writes, moves, locks or deletes anything under the match directory, and it
never ticks a row - a summary is the INPUT to the four-part evidence contract
in ``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself.

WHAT IT REPORTS:
  - game id + queue (the recorder's ``game_id`` event, else MATCH_START.json
    ``game_id`` / ``session_queue`` or the ``match_start`` event), start time and
    whether the recorder joined late.
  - the RC pid timeline from ``state.health.pid``: every pid change mid-match
    is an RC restart, which is exactly when a joined-late mode detect can miss.
  - a mode timeline: one row per change of (mode_key, health.tft_mode,
    health.has_game, liveclient non-empty, lcu.phase, coach.mode).
  - in-progress samples (lcu phase InProgress) and how many of them RC did NOT
    read as tft, plus the callout tags RC served in those samples (an SR
    objective tag such as ``dragon`` during a TFT game is the visible symptom).
  - event counts by ``ev`` and frame counts by ``kind``.

USAGE
    python tools/gated_tft_qa_summary.py <match_dir>          # text to stdout
    python tools/gated_tft_qa_summary.py <match_dir> --json   # machine-readable

Fail-soft: a missing file reads as empty and a malformed line is counted in
``bad_lines``, never raised. Output is 7-bit ASCII (non-ASCII is escaped).
Exit 2 = not a directory; exit 3 = a value too deeply nested to print.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

IN_PROGRESS = "InProgress"
TFT_MODE_KEY = "tft"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path, bad: Counter) -> Iterator[dict]:
    try:
        fh = path.open("r", encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, RecursionError):
                bad[path.name] += 1
                continue
            if isinstance(rec, dict):
                yield rec
            else:
                bad[path.name] += 1


def _dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _state_key(state: dict) -> tuple:
    health = _dict(state.get("health"))
    return (
        state.get("mode_key"),
        health.get("tft_mode"),
        health.get("has_game"),
        bool(state.get("liveclient")),
        _dict(state.get("lcu")).get("phase"),
        _dict(state.get("coach")).get("mode"),
    )


def summarize(match_dir: Path) -> dict:
    """Summarise one recorder match directory. Never raises on bad input."""
    match_dir = Path(match_dir)
    bad: Counter = Counter()
    start = _read_json(match_dir / "MATCH_START.json")

    pids: list[dict] = []
    modes: list[dict] = []
    n_states = 0
    n_in_progress = 0
    n_not_tft = 0
    callout_tags: Counter = Counter()
    first_iso = last_iso = None
    prev_key = None
    for rec in _read_jsonl(match_dir / "states.jsonl", bad):
        state = _dict(rec.get("state"))
        iso = rec.get("iso")
        n_states += 1
        first_iso = first_iso or iso
        last_iso = iso
        pid = _dict(state.get("health")).get("pid")
        if pid is not None and (not pids or pids[-1]["pid"] != pid):
            pids.append({"iso": iso, "pid": pid})
        key = _state_key(state)
        if key != prev_key:
            modes.append({
                "iso": iso, "mode_key": key[0], "tft_mode": key[1],
                "has_game": key[2], "liveclient": key[3], "lcu_phase": key[4],
                "coach_mode": key[5],
            })
            prev_key = key
        if key[4] == IN_PROGRESS:
            n_in_progress += 1
            if key[0] != TFT_MODE_KEY:
                n_not_tft += 1
                callouts = state.get("callouts")
                for c in callouts if isinstance(callouts, list) else []:
                    if isinstance(c, dict) and c.get("tag"):
                        callout_tags[str(c["tag"])] += 1

    events: Counter = Counter()
    game: dict = {}
    start_event_game_id = None
    for rec in _read_jsonl(match_dir / "events.jsonl", bad):
        ev = rec.get("ev")
        events[str(ev)] += 1
        if ev == "game_id" and not game:
            game = {"game_id": rec.get("game_id"), "queue": _dict(rec.get("queue"))}
        elif ev == "match_start" and start_event_game_id is None:
            start_event_game_id = rec.get("game_id")

    # The s134-2 recorder writes no ev=game_id event: the game id rides the
    # match_start event and MATCH_START.json, the queue rides MATCH_START.json
    # ``session_queue`` (its ``queue`` key is an all-None dict there).
    fallback_id = start.get("game_id") or start_event_game_id
    if not game.get("game_id") and fallback_id:
        game["game_id"] = fallback_id
    if not game.get("queue") and _dict(start.get("session_queue")):
        game["queue"] = _dict(start.get("session_queue"))

    frames: Counter = Counter()
    for rec in _read_jsonl(match_dir / "frames.jsonl", bad):
        frames[str(rec.get("kind"))] += 1

    if not game.get("game_id"):
        try:
            txt = (match_dir / "game_id.txt").read_text(
                encoding="utf-8-sig", errors="replace").strip()
        except OSError:
            txt = ""
        if txt:
            game["game_id"] = txt

    return {
        "match_dir": match_dir.name,
        "start_iso": start.get("start_iso"),
        "joined_late": start.get("joined_late"),
        "start_mode_key": start.get("mode_key"),
        "game": game,
        "states": n_states,
        "first_iso": first_iso,
        "last_iso": last_iso,
        "rc_pids": pids,
        "rc_restarts": max(len(pids) - 1, 0),
        "mode_timeline": modes,
        "in_progress_samples": n_in_progress,
        "in_progress_not_tft": n_not_tft,
        "callout_tags_while_not_tft": dict(callout_tags),
        "events": dict(events),
        "frames": dict(frames),
        "bad_lines": dict(bad),
    }


def render(s: dict) -> str:
    """Human-readable text summary."""
    q = _dict(_dict(s.get("game")).get("queue"))
    lines = [
        f"match {s.get('match_dir')}  start {s.get('start_iso')}  "
        f"joined_late={s.get('joined_late')}  start_mode_key={s.get('start_mode_key')}",
        f"game_id {_dict(s.get('game')).get('game_id')}  queue {q.get('id')} "
        f"{q.get('gameMode')} {q.get('type')}",
        f"states {s.get('states')}  {s.get('first_iso')} .. {s.get('last_iso')}",
        f"rc restarts {s.get('rc_restarts')}  pids "
        + " ".join(f"{p['pid']}@{p['iso']}" for p in s.get("rc_pids") or []),
        f"in-progress samples {s.get('in_progress_samples')}  "
        f"read as NOT tft {s.get('in_progress_not_tft')}",
        f"callout tags while not tft {s.get('callout_tags_while_not_tft')}",
        "mode timeline (iso mode_key tft_mode has_game liveclient lcu_phase coach_mode):",
    ]
    for m in s.get("mode_timeline") or []:
        lines.append(
            f"  {m['iso']} {m['mode_key']} {m['tft_mode']} {m['has_game']} "
            f"{m['liveclient']} {m['lcu_phase']} {m['coach_mode']}"
        )
    lines.append(f"events {s.get('events')}")
    lines.append(f"frames {s.get('frames')}")
    if s.get("bad_lines"):
        lines.append(f"bad_lines {s.get('bad_lines')}")
    text = "\n".join(lines)
    return text.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="read-only summary of one tft_qa recorder match directory")
    ap.add_argument("match_dir", help="ops/runtime/tft_qa/<yyyymmdd-hhmmss> directory")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    d = Path(args.match_dir)
    if not d.is_dir():
        print(f"not a directory: {d}", file=sys.stderr)
        return 2
    s = summarize(d)
    try:
        out = json.dumps(s, indent=1, ensure_ascii=True) if args.json else render(s)
    except (ValueError, RecursionError):
        # A recorder value nested deep enough to load but not to re-emit.
        print("summary not printable (pathologically nested value)", file=sys.stderr)
        return 3
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
