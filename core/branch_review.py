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
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.hz_choice_shadow import PRECOMPUTE_SOURCE_KEY, SHADOW_PATH

log = logging.getLogger("rc.branch_review")

# Tail window. A record is roughly 1 KB and a long game logs a few hundred of
# them, so 4 MB covers a full game with a wide margin while keeping a request
# bounded regardless of how large the corpus grows.
DEFAULT_TAIL_BYTES = 4_000_000


def _tail_lines(path: Path, tail_bytes: int) -> tuple[list[str], bool]:
    """Return (lines, truncated) from the last ``tail_bytes`` of ``path``.

    A byte-offset seek lands mid-record, so the first (partial) line is
    discarded whenever the file was actually clipped. ``truncated`` is True
    only when bytes were skipped - a file that fits entirely is not truncated.
    """
    size = path.stat().st_size
    if size <= tail_bytes:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines(), False
    with path.open("rb") as fh:
        fh.seek(size - tail_bytes)
        blob = fh.read()
    lines = blob.decode("utf-8", errors="replace").splitlines()
    # Drop the leading fragment left by the mid-record seek.
    return lines[1:], True


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
    Fail-soft throughout: a missing corpus, an unparseable line or a bad row
    yields an empty-but-shaped result with a ``reason``, never an exception.
    """
    target = Path(path) if path is not None else SHADOW_PATH
    try:
        if not target.exists():
            return _empty("no-corpus")
        lines, truncated = _tail_lines(target, tail_bytes)
    except Exception:  # noqa: BLE001
        log.debug("branch_review: tail read failed", exc_info=True)
        return _empty("no-corpus")

    rows: list[dict] = []
    legacy_skipped = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue  # a corrupt line is not fatal - skip it
        if not isinstance(row, dict):
            continue
        if not row.get("game_run_id"):
            # Pre-B4-d record: ungroupable, so counted rather than guessed at.
            legacy_skipped += 1
            continue
        rows.append(row)

    if not rows:
        return _empty("no-corpus" if not legacy_skipped else "legacy-only",
                      legacy_rows_skipped=legacy_skipped, truncated=truncated)

    run_id = game_run_id or rows[-1].get("game_run_id")
    series = [r for r in rows if r.get("game_run_id") == run_id]
    if not series:
        return _empty("run-not-found", legacy_rows_skipped=legacy_skipped,
                      truncated=truncated)

    def _gt(row: dict) -> float:
        gt = row.get("game_time_s")
        return float(gt) if isinstance(gt, (int, float)) else 0.0

    # The jsonl is append-ordered, but a mid-game RC restart can interleave, so
    # order on the game clock rather than trusting file order.
    series.sort(key=_gt)

    branches: list[dict] = []
    any_excluded = False
    for row in series:
        poisoned = bool(row.get(PRECOMPUTE_SOURCE_KEY))
        any_excluded = any_excluded or poisoned
        choices = [] if poisoned else list(row.get("choices") or [])
        if not choices:
            # A coverage miss (or a poisoned column) leaves no branch to show.
            # The tick still counted toward ticks_total above.
            if not poisoned:
                continue
        branches.append({
            "game_time_s": _gt(row),
            "band": row.get("band"),
            "level": row.get("level"),
            "item_count": row.get("item_count"),
            "choices": choices,
            "native_action": row.get("native_action"),
            "cv_override": row.get("cv_override"),
            "covered": bool(row.get("covered")),
            "precompute_excluded": poisoned,
        })

    head = series[0]
    return {
        "game_run_id": run_id,
        "game_id": head.get("game_id"),
        "mode": head.get("mode"),
        "my_champion": head.get("my_champion"),
        "enemy": head.get("enemy"),
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
    enemy, ticks}. Feeds the review view's match picker.
    """
    target = Path(path) if path is not None else SHADOW_PATH
    try:
        if not target.exists():
            return []
        lines, _ = _tail_lines(target, tail_bytes)
    except Exception:  # noqa: BLE001
        return []
    seen: dict[str, dict] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(row, dict):
            continue
        rid = row.get("game_run_id")
        if not rid:
            continue
        entry = seen.get(rid)
        if entry is None:
            seen[rid] = {
                "game_run_id": rid, "game_id": row.get("game_id"),
                "mode": row.get("mode"), "my_champion": row.get("my_champion"),
                "enemy": row.get("enemy"), "ticks": 1,
            }
        else:
            entry["ticks"] += 1
    # Insertion order follows file order, so newest-first is a reversal.
    return list(reversed(list(seen.values())))[:max(1, limit)]
