"""core/branch_review.py - read one match's decision-branch series back out of
the HZ-C1 shadow corpus.

B4 (RM-189). Riot's third-party rules ban in-game notifications that dictate
player action, so RC computes the multi-path choice set DURING the game, writes
it to ``data/hz_choice_shadow.jsonl`` (``core.hz_choice_shadow``) and renders
nothing live. This module is the other half: it turns a ``game_run_id`` back
into "here is the branch you were at, here is what each path was worth".

Three constraints shape the implementation, each measured rather than assumed:

1. **Bounded read.** The corpus is 68 MB and this serves an HTTP route, so it
   reads a TAIL rather than the file. When the window may have clipped the
   series it reports ``truncated`` instead of quietly serving a short series as
   if it were complete.
2. **Legacy rows.** Almost all of that 68 MB predates B4-d and carries no
   ``game_run_id``. Those rows cannot be grouped into a match; they are skipped
   and COUNTED. Guessing a grouping would invent matches that never happened.
3. **RM-158 Arena poison.** A record whose precompute column is really SR
   content is tagged ``precompute_source``. That COLUMN is dropped and the
   native observation kept - the ROADMAP fence is explicit that purging the
   whole row was wrong, since 504 of 1148 such rows carry real Arena telemetry
   and no precompute content at all.

s144 true-audit cycle 121: both routes send STRICT JSON (allow_nan=False) and
turn any raise into an error envelope, so one junk row used to take the whole
review down. Every row is now read defensively: a run id must be a non-empty
string, NaN / Infinity / 1e400 parse to None, ``choices`` must be a list of
objects, identity and context fields must be scalars, and only an OSError on
the corpus read is absorbed (as ``read-failed``, logged at WARNING).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from core.hz_choice_shadow import PRECOMPUTE_SOURCE_KEY, SHADOW_PATH

log = logging.getLogger("rc.branch_review")

# Tail window. A record is roughly 1 KB and a long game logs a few hundred of
# them, so 4 MB covers a full game with a wide margin while keeping a request
# bounded regardless of how large the corpus grows.
DEFAULT_TAIL_BYTES = 4_000_000


def _tail_size(tail_bytes) -> int:
    """A positive int window, else the default (0, negatives, bools, floats
    and strings are not a byte count)."""
    if isinstance(tail_bytes, int) and not isinstance(tail_bytes, bool) \
            and tail_bytes > 0:
        return tail_bytes
    return DEFAULT_TAIL_BYTES


def _tail_lines(path: Path, tail_bytes: int) -> tuple[list[str], bool]:
    """Return (lines, truncated) from the last ``tail_bytes`` of ``path``.

    A byte-offset seek usually lands mid-record, so the first line is a
    fragment and is discarded - unless the byte just before the window is a
    newline, in which case the window starts on a whole record and keeps it.
    ``truncated`` is True only when bytes were skipped - a file that fits
    entirely is not truncated.
    """
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size <= tail_bytes:
            blob, truncated, starts_whole = fh.read(), False, True
        else:
            fh.seek(size - tail_bytes - 1)
            blob = fh.read()
            starts_whole = blob[:1] == b"\n"
            blob, truncated = blob[1:], True
    lines = blob.decode("utf-8", errors="replace").splitlines()
    if not starts_whole:
        lines = lines[1:]  # the leading fragment left by the mid-record seek
    return lines, truncated


def _no_constant(_token: str) -> None:
    # NaN / Infinity / -Infinity: valid to Python's json, fatal to the route's
    # strict encoder, meaningless as a clock or a count.
    return None


def _finite_float(text: str) -> float | None:
    value = float(text)
    return value if math.isfinite(value) else None  # 1e400 parses to inf


def _rows(lines: list[str]):
    """Yield every line that parses to a JSON object, non-finite numbers
    already read as None. A corrupt or pathologically nested line is not
    fatal - it is skipped."""
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line, parse_constant=_no_constant,
                             parse_float=_finite_float)
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict):
            yield row


def _run_id(row: dict) -> str | None:
    """The row's match id: a non-empty string, else None (ungroupable)."""
    rid = row.get("game_run_id")
    if isinstance(rid, str):
        rid = rid.strip()
        return rid or None
    return None


def _scalar(value):
    """A JSON scalar the panel can print: a string or a non-bool number,
    else None. Nested lists / objects never reach a text field."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int, float)):
        return value
    return None


def _choices(value) -> list[dict]:
    """The row's choice set: only a list, only its object elements (the
    panel's _choiceHtml reads ``c.key`` and throws on a null element)."""
    if not isinstance(value, list):
        return []
    return [c for c in value if isinstance(c, dict)]


def _clock(row: dict) -> float | None:
    gt = row.get("game_time_s")
    if isinstance(gt, bool) or not isinstance(gt, (int, float)):
        return None
    try:
        value = float(gt)  # a 401-digit int token parses fine, then overflows
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _wanted_run(game_run_id) -> str | None:
    """Normalise the caller's selector: a stripped non-empty string, an int
    (the writer stamps ``str(game_id)``), else None for the most recent."""
    if isinstance(game_run_id, int) and not isinstance(game_run_id, bool):
        return str(game_run_id)
    if isinstance(game_run_id, str):
        return game_run_id.strip() or None
    return None


def _read(target: Path, tail_bytes) -> tuple[list[str], bool] | None:
    """The corpus tail, or None when it cannot be read. Only an OSError is
    absorbed (logged at WARNING); anything else is a bug and raises."""
    try:
        return _tail_lines(target, _tail_size(tail_bytes))
    except OSError:
        log.warning("branch_review: tail read failed for %s", target.name,
                    exc_info=True)
        return None


def _empty(reason: str, **extra) -> dict:
    out = {
        "game_run_id": None, "game_id": None, "mode": None,
        "my_champion": None, "enemy": None,
        "branches": [], "branch_count": 0, "ticks_total": 0,
        "legacy_rows_skipped": 0, "precompute_excluded": False,
        "truncated": False, "reason": reason,
    }
    out.update(extra)
    return out


def load_branch_series(game_run_id: str | None = None, *,
                       path: Path | None = None,
                       tail_bytes: int = DEFAULT_TAIL_BYTES) -> dict:
    """Return the decision-branch series for one match.

    ``game_run_id`` None selects the most recent run present in the tail.
    Fail-soft on DATA: a missing or unreadable corpus, an unparseable line or
    a bad row yields an empty-but-shaped result with a ``reason`` (never a
    non-finite number, never a nested value in a text field). A bug that is
    not an OSError raises, so the route logs it instead of hiding it.
    """
    target = Path(path) if path is not None else SHADOW_PATH
    if not target.exists():
        return _empty("no-corpus")
    read = _read(target, tail_bytes)
    if read is None:
        return _empty("read-failed")
    lines, truncated = read

    rows: list[tuple[str, dict]] = []
    legacy_skipped = 0
    for row in _rows(lines):
        rid = _run_id(row)
        if rid is None:
            # Pre-B4-d (or junk-id) record: ungroupable, so counted rather
            # than guessed at.
            legacy_skipped += 1
            continue
        rows.append((rid, row))

    if not rows:
        return _empty("no-corpus" if not legacy_skipped else "legacy-only",
                      legacy_rows_skipped=legacy_skipped, truncated=truncated)

    run_id = _wanted_run(game_run_id) or rows[-1][0]
    series = [r for rid, r in rows if rid == run_id]
    if not series:
        return _empty("run-not-found", legacy_rows_skipped=legacy_skipped,
                      truncated=truncated)

    # The jsonl is append-ordered, but a mid-game RC restart can interleave, so
    # order on the game clock rather than trusting file order. An unknown
    # clock sorts first and is served as None (strict JSON null; the panel's
    # fmtClock reads Number(null) as 0, the same "0:00" the old 0.0 gave).
    series.sort(key=lambda r: _clock(r) or 0.0)

    branches: list[dict] = []
    any_excluded = False
    for row in series:
        poisoned = bool(row.get(PRECOMPUTE_SOURCE_KEY))
        any_excluded = any_excluded or poisoned
        choices = [] if poisoned else _choices(row.get("choices"))
        # A coverage miss (or a poisoned column) leaves no branch to show.
        # The tick still counted toward ticks_total above.
        if not choices and not poisoned:
            continue
        cv = row.get("cv_override")
        branches.append({
            "game_time_s": _clock(row),
            "band": _scalar(row.get("band")),
            "level": _scalar(row.get("level")),
            "item_count": _scalar(row.get("item_count")),
            "choices": choices,
            "native_action": _scalar(row.get("native_action")),
            "cv_override": cv if isinstance(cv, dict) else None,
            "covered": row.get("covered") is True,
            "precompute_excluded": poisoned,
        })

    head = series[0]
    return {
        "game_run_id": run_id,
        "game_id": _scalar(head.get("game_id")),
        "mode": _scalar(head.get("mode")),
        "my_champion": _scalar(head.get("my_champion")),
        "enemy": _scalar(head.get("enemy")),
        "branches": branches,
        "branch_count": len(branches),
        "ticks_total": len(series),
        "legacy_rows_skipped": legacy_skipped,
        "precompute_excluded": any_excluded,
        "truncated": truncated,
        "reason": None,
    }


def list_recent_runs(*, path: Path | None = None,
                     tail_bytes: int = DEFAULT_TAIL_BYTES,
                     limit: int = 20) -> list[dict]:
    """Return the most recent runs in the tail, newest first.

    One entry per ``game_run_id``: {game_run_id, game_id, mode, my_champion,
    enemy, ticks}. Feeds the review view's match picker. "Recent" is by a
    run's LAST row, so a run resumed after a restart interleaved another one
    ranks newest - the same run ``load_branch_series`` picks by default.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        limit = 20
    target = Path(path) if path is not None else SHADOW_PATH
    if not target.exists():
        return []
    read = _read(target, tail_bytes)
    if read is None:
        return []
    seen: dict[str, dict] = {}
    for row in _rows(read[0]):
        rid = _run_id(row)
        if rid is None:
            continue
        entry = seen.pop(rid, None)
        if entry is None:
            entry = {
                "game_run_id": rid, "game_id": _scalar(row.get("game_id")),
                "mode": _scalar(row.get("mode")),
                "my_champion": _scalar(row.get("my_champion")),
                "enemy": _scalar(row.get("enemy")), "ticks": 0,
            }
        entry["ticks"] += 1
        seen[rid] = entry  # re-inserted: dict order is last-appearance order
    return list(reversed(list(seen.values())))[:max(1, limit)]
