# arch: in-game "mark this moment" store + post-game attach (RM-638) | section=core | frozen=no
"""core/moment_marks.py - RM-638 (directive X-38, external reference C).

The player presses Ctrl+Shift+K in game (tools/hotkey_listener.py slot 5); the
listener reads :2999 /liveclientdata/gamestats and appends one row here:

    {"game_id": "<LCU gameId>" | null, "game_time_s": <float>, "wall_ts": <epoch>}

to ``ops/runtime/moment_marks.jsonl`` (gitignored under ``ops/runtime/``). The
append goes through the Win32 FILE_APPEND_DATA helper core/operator_notify.py
already owns (``_win32_append``), so a press never races another writer.

After the game the post-game collector calls ``attach_for_game`` with the
just-ended gameId; the marks for that game - exact gameId, or gameId null and
wall_ts inside the game's wall window - go to one per-game pin file
``ops/runtime/moment_marks_by_game/<gameId>.json``. The Replay and PGR routes
read it back through ``pins_for_match`` as an additive ``you_flagged`` list.

Useful WITHOUT recording: nothing here touches OBS. ``request_replay_buffer_save``
is the named hook for the SaveReplayBuffer call RM-637 will add; it is a no-op.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from core.polled_json import atomic_write_text

_log = logging.getLogger("rc.moment_marks")

_ROOT = Path(__file__).resolve().parent.parent
MARKS_ENV = "RC_MOMENT_MARKS_JSONL"
ATTACHED_ENV = "RC_MOMENT_MARKS_DIR"
_DEFAULT_MARKS = _ROOT / "ops" / "runtime" / "moment_marks.jsonl"
_DEFAULT_ATTACHED = _ROOT / "ops" / "runtime" / "moment_marks_by_game"

PIN_LABEL = "you flagged"

# Our own choice, not measured from any external source: a null-gameId mark
# attaches to a game when its wall_ts lies in
#   [ended_at - game_length_s - ATTACH_SLACK_S, ended_at + ATTACH_SLACK_S].
# ended_at is the collector's trigger time (game end) and game_length_s the
# EOG gameLength, which starts at the end of the loading screen, so the lower
# slack covers that skew; the upper slack covers a late trigger. 300 s matches
# the collector's own _HISTORY_PIN_SLACK_S reasoning (a previous game ended at
# least one champ select + load + remake window earlier, so it stays out).
ATTACH_SLACK_S = 300.0

# Our own choice: the longest game length the attach window trusts. The EOG
# gameLength / history gameDuration fallback is SECONDS today, but Match-V5
# gameDuration was MILLISECONDS before patch 11.20; a length in ms would open a
# window weeks wide and pin every null-gameId mark ever pressed to this game.
# 4 h is far beyond any real League / Arena / TFT game, so clamping costs no
# real mark.
MAX_GAME_LENGTH_S = 4 * 3600.0

_DIGITS = re.compile(r"[0-9]{1,20}")


def marks_path() -> Path:
    """The marks jsonl, resolved at CALL time so tests / env can redirect it."""
    env = os.environ.get(MARKS_ENV)
    return Path(env) if env else _DEFAULT_MARKS


def attached_dir() -> Path:
    env = os.environ.get(ATTACHED_ENV)
    return Path(env) if env else _DEFAULT_ATTACHED


def _norm_game_id(game_id: Any) -> Optional[str]:
    if game_id is None or isinstance(game_id, bool):
        return None
    s = str(game_id).strip()
    if not _DIGITS.fullmatch(s) or int(s) == 0:
        return None
    return s


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def build_mark(gamestats: Any, game_id: Any, wall_ts: Any) -> Optional[dict]:
    """One mark row from a :2999 gamestats payload, or None when gameTime is
    missing / non-numeric / non-finite / negative, or wall_ts is not a finite
    number (a NaN / Infinity row is one the readers reject)."""
    if not isinstance(gamestats, dict):
        return None
    gt = _finite(gamestats.get("gameTime"))
    wt = _finite(wall_ts)
    if gt is None or gt < 0 or wt is None:
        return None
    return {
        "game_id": _norm_game_id(game_id),
        "game_time_s": round(gt, 3),
        "wall_ts": round(wt, 3),
    }


def _canonical_row(mark: Any) -> dict:
    """The {game_id, game_time_s, wall_ts} row the readers accept, or
    ValueError. Same field rule as read_marks_strict (_finite on both
    times), and the values are written back as floats, so nothing written
    here can poison a later strict read."""
    if not isinstance(mark, dict):
        raise ValueError(f"mark is not a dict: {type(mark).__name__}")
    gt, wt = _finite(mark.get("game_time_s")), _finite(mark.get("wall_ts"))
    if gt is None or wt is None:
        raise ValueError("mark needs finite game_time_s and wall_ts")
    return {"game_id": _norm_game_id(mark.get("game_id")),
            "game_time_s": gt, "wall_ts": wt}


def append_mark(mark: dict, path: Optional[os.PathLike] = None) -> None:
    """Append one JSON line (ASCII, LF). Windows: the shared FILE_APPEND_DATA
    helper; elsewhere one os.write on an O_APPEND fd.

    Only the canonical row is written (extra keys dropped, game_id
    normalised). Raises ValueError, before touching disk, for a row the
    readers would reject - one such line makes read_marks_strict raise on
    every later read - and OSError on a write failure."""
    from core.operator_notify import _on_windows, _portable_append, _win32_append

    row = _canonical_row(mark)
    data = (json.dumps(row, ensure_ascii=True) + "\n").encode("ascii")
    p = Path(path) if path is not None else marks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if _on_windows():
        _win32_append(p, data)
    else:
        _portable_append(p, data)


def read_marks(path: Optional[os.PathLike] = None) -> list[dict]:
    """Every well-formed mark row; malformed lines are skipped, never fatal."""
    p = Path(path) if path is not None else marks_path()
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        gt, wt = _finite(row.get("game_time_s")), _finite(row.get("wall_ts"))
        if gt is None or wt is None:
            continue
        out.append({"game_id": _norm_game_id(row.get("game_id")),
                    "game_time_s": gt, "wall_ts": wt})
    return out


def select_marks_for_game(marks: Iterable[dict], game_id: str,
                          window_start: float, window_end: float) -> list[dict]:
    """Exact gameId match, or gameId null with wall_ts in the window. A row
    that is not a dict, or a null-gameId row without a finite wall_ts, is
    skipped rather than raising."""
    picked = []
    for m in marks:
        if not isinstance(m, dict):
            continue
        gid = m.get("game_id")
        if gid is not None:
            if gid == game_id:
                picked.append(m)
            continue
        wt = _finite(m.get("wall_ts"))
        if wt is not None and window_start <= wt <= window_end:
            picked.append(m)
    return picked


def _pin(m: dict) -> dict:
    return {"clock_s": int(m["game_time_s"]), "game_time_s": m["game_time_s"],
            "wall_ts": m["wall_ts"], "label": PIN_LABEL}


def attach_for_game(game_id: Any, game_length_s: Any, ended_at: Any, *,
                    marks_file: Optional[os.PathLike] = None,
                    out_dir: Optional[os.PathLike] = None) -> list[dict]:
    """Attach the just-ended game's marks to its per-game pin file.

    Returns the pins (clock-ascending). Writes NOTHING when there are no
    marks for the game, or the gameId is not a plain positive integer (the id
    becomes a file name). The write is atomic (tmp + replace)."""
    gid = _norm_game_id(game_id)
    if gid is None:
        return []
    length = min(max(_finite(game_length_s) or 0.0, 0.0), MAX_GAME_LENGTH_S)
    end = _finite(ended_at)
    if end is None:
        end = time.time()
    picked = select_marks_for_game(
        read_marks(marks_file), gid,
        end - length - ATTACH_SLACK_S, end + ATTACH_SLACK_S)
    if not picked:
        return []
    pins = sorted((_pin(m) for m in picked),
                  key=lambda p: (p["game_time_s"], p["wall_ts"]))
    d = Path(out_dir) if out_dir is not None else attached_dir()
    target = d / f"{gid}.json"
    doc = {"game_id": gid, "attached_at": round(time.time(), 3), "pins": pins}
    atomic_write_text(target, json.dumps(doc, ensure_ascii=True, indent=1) + "\n")
    _log.info("moment marks: attached %d pin(s) to game %s", len(pins), gid)
    return pins


def _game_id_from_match_id(match_id: Any) -> Optional[str]:
    """'NA1_7001' or '7001' -> '7001'; anything else -> None."""
    if not isinstance(match_id, str):
        return None
    s = match_id.strip()
    if "_" in s:
        prefix, _, s = s.partition("_")
        if not prefix.isalnum():
            return None
    return _norm_game_id(s)


def pins_for_match(match_id: Any, out_dir: Optional[os.PathLike] = None) -> list[dict]:
    """The "you flagged" pins for a Replay / PGR match_id; [] on any miss.

    Each pin is rebuilt from its finite game_time_s / wall_ts and any other
    pin is dropped: json.loads accepts NaN / Infinity, and the routes'
    default json.dumps would write them back as bare NaN - invalid JSON that
    makes the browser reject the whole payload."""
    gid = _game_id_from_match_id(match_id)
    if gid is None:
        return []
    d = Path(out_dir) if out_dir is not None else attached_dir()
    try:
        doc = json.loads((d / f"{gid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pins = doc.get("pins") if isinstance(doc, dict) else None
    if not isinstance(pins, list):
        return []
    out = []
    for p in pins:
        if not isinstance(p, dict):
            continue
        gt, wt = _finite(p.get("game_time_s")), _finite(p.get("wall_ts"))
        if gt is not None and wt is not None:
            out.append(_pin({"game_time_s": gt, "wall_ts": wt}))
    return out


class MarksUnreadable(Exception):
    """A strict read could not PROVE the mark state (corrupt or unreadable)."""


def read_marks_strict(path: Optional[os.PathLike] = None) -> list[dict]:
    """Like read_marks, but never mistakes "unreadable" for "no marks".

    RM-640 additive variant for callers that delete on a zero count. A
    MISSING file is a real zero (no mark was ever pressed) and returns [].
    Any other OSError, and any line that is not a well-formed mark row,
    raises MarksUnreadable - the caller must then treat marks as unknown.
    """
    p = Path(path) if path is not None else marks_path()
    try:
        raw = p.read_text(encoding="utf-8", errors="strict")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise MarksUnreadable(f"{p}: {exc}") from exc
    out: list[dict] = []
    for n, raw_line in enumerate(raw.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise MarksUnreadable(f"{p}:{n}: not JSON") from exc
        gt = _finite(row.get("game_time_s")) if isinstance(row, dict) else None
        wt = _finite(row.get("wall_ts")) if isinstance(row, dict) else None
        if gt is None or wt is None:
            raise MarksUnreadable(f"{p}:{n}: not a mark row")
        out.append({"game_id": _norm_game_id(row.get("game_id")),
                    "game_time_s": gt, "wall_ts": wt})
    return out


def pins_for_match_strict(match_id: Any,
                          out_dir: Optional[os.PathLike] = None) -> Optional[list[dict]]:
    """The per-game pins, or None when NO pin file exists for the game.

    RM-640 additive variant: unlike pins_for_match (which returns [] on any
    miss), a match id that is not a real gameId, an unreadable file, bad JSON
    or a malformed pin list raises MarksUnreadable.
    """
    gid = _game_id_from_match_id(match_id)
    if gid is None:
        raise MarksUnreadable(f"not a gameId: {match_id!r}")
    d = Path(out_dir) if out_dir is not None else attached_dir()
    try:
        raw = (d / f"{gid}.json").read_text(encoding="utf-8", errors="strict")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise MarksUnreadable(f"pin file for {gid}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise MarksUnreadable(f"pin file for {gid}: not JSON") from exc
    pins = doc.get("pins") if isinstance(doc, dict) else None
    if not isinstance(pins, list) or not all(isinstance(p, dict) for p in pins):
        raise MarksUnreadable(f"pin file for {gid}: malformed pins")
    return pins


def request_replay_buffer_save(mark: dict) -> bool:
    """RM-637 HOOK - future obs-websocket SaveReplayBuffer on a mark press.

    Deliberately a no-op returning False: RM-638 must not depend on OBS. When
    RM-637 (ADR-016 recording) is live, this is the one place to call
    SaveReplayBuffer, under ADR-016's opt-in and ownership rules."""
    return False
