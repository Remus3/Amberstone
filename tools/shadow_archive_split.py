#!/usr/bin/env python
# arch: archive-split test-leaked rows out of a live shadow jsonl (data-fix doctrine) | section=tools | frozen=no
"""Archive-split test-leaked rows out of a live ``data/*_shadow.jsonl``.

RM-859. RM-852 (35b2524f3) attributed 669 enemy-less Kai'Sa rows in the live
``data/aram_coach_shadow.jsonl`` to build_state test harnesses and excluded
them at READ time only (``tools/aram_shadow_report.has_enemy_comp``). This
helper moves such rows out of the live file under the data-fix doctrine - the
RM-867 (d37e806c1) / RM-872 (f103226d0) shape - without deleting anything:

1. Refuse while a game is live: ``GET https://127.0.0.1:8888/api/state``;
   a live ``mode_key`` or a non-empty ``liveclient`` aborts, and so does an
   unreachable or malformed state (fail closed). Re-checked right before the
   replace.
2. Hash (sha256) and count the live file; split it into LINES with their own
   end-of-line bytes kept, so both outputs are byte-exact slices of it.
3. Write the matching rows to the archive and the rest to a tmp file beside
   the live file, then ``os.replace`` (atomic) the archive into place and the
   kept tmp onto the live file. An existing archive is never clobbered.
4. Grow-merge: a shadow writer appends during a game. If the live file grew
   by a pure append since the snapshot, the new bytes are appended to the
   kept tmp before the replace (re-checked until stable); any other change
   aborts with the live file untouched.
5. Verify: kept + archived == original row count, the archive is exactly the
   matched rows in order, and re-interleaving the archive back at the recorded
   positions reproduces the original bytes (its sha256 is reported).

The leaked rows can be INTERLEAVED with real ones (the ARAM file holds 21
runs), so the original is reproduced by position, not by concatenation; the
positions are reported as ``archived_runs`` ([start, length] pairs over the
original line index) so they can be recorded with the act.

Residual: an append that lands in the microseconds between the final re-read
and the replace would go to the old inode. The game gate is the guard - every
shadow writer is gated on a live tick - and on Windows a writer holding the
file open makes the replace fail and retry.

USAGE
    python tools/shadow_archive_split.py --live data/aram_coach_shadow.jsonl \\
        --archive data/aram_coach_rm859_test_leak_2026-06_2026-09_shadow.jsonl \\
        [--dry-run] [--json]

There is no default live or archive path on purpose: a test cannot reach the
live tree through this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.aram_shadow_report import has_enemy_comp  # noqa: E402

STATE_URL = "https://127.0.0.1:8888/api/state"
# The in-game dashboard modes (the game-monitor skill's gate set).
LIVE_MODES = frozenset({"sr", "arena", "aram", "tft", "brawl"})
MAX_ROUNDS = 10
REPLACE_RETRY_S = 0.2
# Bounds a runaway /api/state body (measured ~2 KB idle on 2026-10-25); a
# truncated read fails to parse, which fails closed.
_STATE_MAX_BYTES = 16 * 1024 * 1024


class SplitAborted(RuntimeError):
    """The split stopped before changing the live file. ``reason`` is a code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_lines(data: bytes) -> list[bytes]:
    """Lines with their own end-of-line bytes kept (b"".join round-trips)."""
    return data.splitlines(keepends=True)


def is_enemy_less_row(line: bytes) -> bool:
    """True for a JSON-object row that RM-852's reader excludes (no named enemy).

    The predicate IS ``aram_shadow_report.has_enemy_comp`` negated, so the
    split moves exactly the rows the report already drops. A blank, malformed
    or non-object line is NOT matched: it is not this helper's to classify and
    stays in the live file where the reader already skips it."""
    text = line.strip()
    if not text:
        return False
    try:
        rec = json.loads(text)
    except ValueError:
        return False
    if not isinstance(rec, dict):
        return False
    return not has_enemy_comp(rec)


PREDICATES: dict[str, Callable[[bytes], bool]] = {
    "aram-enemy-less": is_enemy_less_row,
}


def partition(lines: list[bytes], is_leak: Callable[[bytes], bool]
              ) -> tuple[list[bytes], list[bytes], list[int]]:
    """(kept lines, archived lines, archived positions) in original order."""
    kept: list[bytes] = []
    archived: list[bytes] = []
    positions: list[int] = []
    for i, line in enumerate(lines):
        if is_leak(line):
            archived.append(line)
            positions.append(i)
        else:
            kept.append(line)
    return kept, archived, positions


def reinterleave(kept: list[bytes], archived: list[bytes],
                 positions: list[int]) -> bytes:
    """Rebuild the original bytes: archived[k] back at positions[k]."""
    if len(archived) != len(positions):
        raise ValueError("archived rows and positions differ in length")
    out: list[bytes] = []
    total = len(kept) + len(archived)
    slots = dict(zip(positions, archived))
    it = iter(kept)
    for i in range(total):
        if i in slots:
            out.append(slots[i])
        else:
            out.append(next(it))
    return b"".join(out)


def runs(positions: list[int]) -> list[list[int]]:
    """[start, length] pairs for a sorted position list."""
    out: list[list[int]] = []
    for p in positions:
        if out and p == out[-1][0] + out[-1][1]:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    return out


def positions_from_runs(pairs: list[list[int]]) -> list[int]:
    return [s + k for s, n in pairs for k in range(n)]


def window_months(lines: list[bytes]) -> str:
    """"YYYY-MM_YYYY-MM" from the rows' ``ts`` (the RM-872 archive naming)."""
    months: list[str] = []
    for line in lines:
        try:
            ts = json.loads(line).get("ts")
        except (ValueError, AttributeError):
            continue
        if isinstance(ts, str) and len(ts) >= 7:
            months.append(ts[:7])
    if not months:
        return ""
    return f"{min(months)}_{max(months)}"


def game_is_live(state: dict) -> bool:
    """A live game: an in-game ``mode_key`` OR a non-empty ``liveclient``.

    Either signal aborts (the safe direction for a write)."""
    if not isinstance(state, dict):
        return True
    return state.get("mode_key") in LIVE_MODES or bool(state.get("liveclient"))


def _fetch_state(url: str = STATE_URL, timeout: float = 5.0) -> object:
    from core.tls_policy import client_context_noverify  # local mkcert dashboard

    ctx = client_context_noverify()
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read(_STATE_MAX_BYTES).decode("utf-8"))


def probe_game_live(fetch: Optional[Callable[[], object]] = None) -> bool:
    """True unless the dashboard state is readable AND shows no live game."""
    try:
        state = (fetch or _fetch_state)()
    except Exception:  # noqa: BLE001 - fail closed on any probe failure
        return True
    if not isinstance(state, dict):
        return True
    return game_is_live(state)


def _write_tmp(path: Path, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def plan_split(live: Path, is_leak: Callable[[bytes], bool] = is_enemy_less_row
               ) -> dict:
    """Read-only: what a split of ``live`` would move. Never writes."""
    original = Path(live).read_bytes()
    lines = split_lines(original)
    kept, archived, positions = partition(lines, is_leak)
    return {
        "live": str(live),
        "sha256_before": sha256_hex(original),
        "bytes_before": len(original),
        "rows_before": len(lines),
        "rows_kept": len(kept),
        "rows_archived": len(archived),
        "archived_runs": runs(positions),
        "window": window_months(archived),
    }


def archive_split(live: Path, archive: Path,
                  is_leak: Callable[[bytes], bool] = is_enemy_less_row, *,
                  game_live: Callable[[], bool] = probe_game_live,
                  max_rounds: int = MAX_ROUNDS,
                  _before_replace: Optional[Callable[[int], None]] = None,
                  ) -> dict:
    """Move the ``is_leak`` rows of ``live`` byte-exact into ``archive``.

    Returns the verification report. Raises SplitAborted (live file unchanged,
    no archive, no tmp left) on: a live game, an existing archive, a missing
    live file, no matching row, a torn last line, a non-append change to the
    live file, or a replace that keeps failing."""
    live = Path(live)
    archive = Path(archive)
    if game_live():
        raise SplitAborted("game_live", "a game is live (or state unreadable)")
    if archive.exists():
        raise SplitAborted("archive_exists", str(archive))
    if not live.is_file():
        raise SplitAborted("live_missing", str(live))

    original = live.read_bytes()
    if original and not original.endswith(b"\n"):
        raise SplitAborted("no_trailing_newline", "torn last line")
    lines = split_lines(original)
    kept, archived, positions = partition(lines, is_leak)
    if not archived:
        raise SplitAborted("nothing_to_archive", str(live))
    if reinterleave(kept, archived, positions) != original:
        raise SplitAborted("self_check_failed", "re-interleave mismatch")

    kept_bytes = b"".join(kept)
    archived_bytes = b"".join(archived)
    archive_tmp = archive.with_name(archive.name + ".split.tmp")
    kept_tmp = live.with_name(live.name + ".split.tmp")
    source = original
    tail = b""
    done = False
    try:
        _write_tmp(archive_tmp, archived_bytes)
        _write_tmp(kept_tmp, kept_bytes)
        for round_no in range(max_rounds):
            if _before_replace is not None:
                _before_replace(round_no)
            if game_live():
                raise SplitAborted("game_live", "a game started mid-split")
            current = live.read_bytes()
            if current != source:
                if not current.startswith(source):
                    raise SplitAborted("live_changed_not_append", str(live))
                tail += current[len(source):]
                source = current
                _write_tmp(kept_tmp, kept_bytes + tail)
                continue  # re-check until the live file is stable
            if archive.exists():
                raise SplitAborted("archive_exists", str(archive))
            os.replace(archive_tmp, archive)
            try:
                os.replace(kept_tmp, live)
            except OSError:
                # Writer holds the file (Windows) - put the archive back and
                # retry the round; the live file is unchanged.
                os.replace(archive, archive_tmp)
                time.sleep(REPLACE_RETRY_S)
                continue
            done = True
            break
        if not done:
            raise SplitAborted("replace_failed",
                               f"live file not stable/replaceable in {max_rounds} rounds")
    finally:
        if not done:
            _unlink_quiet(archive_tmp)
            _unlink_quiet(kept_tmp)

    live_after = live.read_bytes()
    archive_after = archive.read_bytes()
    expected_live = kept_bytes + tail
    archive_lines = split_lines(archive_after)
    back = (reinterleave(kept, archive_lines, positions)
            if len(archive_lines) == len(positions) else b"")
    checks = {
        "live_starts_with_kept_plus_tail": live_after.startswith(expected_live),
        "archive_is_matched_rows": archive_after == archived_bytes,
        "rows_add_up": len(kept) + len(archived) == len(lines),
        "reinterleave_matches": back == original,
    }
    return {
        "live": str(live),
        "archive": str(archive),
        "sha256_before": sha256_hex(original),
        "bytes_before": len(original),
        "rows_before": len(lines),
        "rows_kept": len(kept),
        "rows_archived": len(archived),
        "tail_rows_merged": len(split_lines(tail)),
        "sha256_live_after": sha256_hex(live_after),
        "bytes_live_after": len(live_after),
        "rows_live_after": len(split_lines(live_after)),
        "sha256_archive": sha256_hex(archive_after),
        "bytes_archive": len(archive_after),
        "archived_positions": positions,
        "archived_runs": runs(positions),
        "reinterleave_sha256": sha256_hex(back),
        "window": window_months(archived),
        "checks": checks,
        "verified": all(checks.values()),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", required=True, help="the live shadow jsonl")
    ap.add_argument("--archive", required=True,
                    help="the gitignored archive path (must not exist)")
    ap.add_argument("--predicate", default="aram-enemy-less",
                    choices=sorted(PREDICATES))
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)
    is_leak = PREDICATES[args.predicate]
    try:
        if args.dry_run:
            out = plan_split(Path(args.live), is_leak)
            out["archive"] = args.archive
            out["dry_run"] = True
        else:
            out = archive_split(Path(args.live), Path(args.archive), is_leak,
                                game_live=probe_game_live)
            out.pop("archived_positions", None)
            out["dry_run"] = False
    except SplitAborted as exc:
        print(json.dumps({"aborted": exc.reason, "detail": exc.detail}))
        return 2
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        for key in sorted(out):
            print(f"{key}: {out[key]}")
    if not args.dry_run and not out.get("verified"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
