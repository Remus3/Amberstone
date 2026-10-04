# arch: keep-on-condition VOD retention over RC recording sidecars | section=core | frozen=no
"""core/vod_retention.py - report-first retention for RC match recordings.

RM-640 (directive X-40; provenance: external references E and G, behaviour
only, re-implemented here). The binding design is the "Retention" and
"No RC-owned folder" bullets of docs/adr/ADR-016-local-match-recording.md.

SCOPE
-----
Only paths RECORDED IN RC SIDECARS are in scope: `data/recordings/<matchId>.json`
(ADR-016 "Sidecar is the source of truth") names the StopRecord output path,
the death reel and any clips RC made. OBS writes wherever the operator's
profile points, so no video folder is ever listed or globbed. The only
directory listing here is RC's own sidecar directory, which IS the index.

SIDECAR CONTRACT (the RM-637 recorder's writer, core/obs_recorder.py
`_write_sidecar`; mirrored in RECORDER_SIDECAR_KEYS / RECORDER_WALL_KEYS and
pinned by a parity test so drift reds)
------------------------------------------------------------------------
  status            only "final" sidecars are eligible; "recording" = HELD
  owner             "rc" or "operator"
  obs_output_path   the StopRecord path (null for operator-owned recordings)
  wall.{record_stop, game_end, record_start}
                    created_at = the first present, in that order. All
                    missing -> UNDATED (never a candidate, never evicted).
                    wall.attach is NOT a recording time and is not used.
  queue_id          ranked check (core.replay_roster.RANKED_QUEUES)
  death_count       zero deaths lets a recording go without a reel
  bookmarks         Live Client EVENTS (`name`), never operator marks
Keys no writer emits yet, read when present: death_reel.path (X-39; the reel
must read back non-empty on disk), clips[].path, pinned, pgr_score.
From outside the sidecar (read-only):
  marks   RM-638 store via core.moment_marks' STRICT readers: the per-game
          pin file ops/runtime/moment_marks_by_game/<gameId>.json, else the
          raw ops/runtime/moment_marks.jsonl matched by gameId or by wall_ts
          in the recording window. Only a PROVEN count is used; anything
          unprovable -> UNKNOWN -> KEEP (see moment_marks_count).
  result  data/rewind_history.db `matches.tracked_win` (the tracked = the
          operator's row, as core/aftergame_summary._match_meta reads it),
          matched on the gameId inside the sidecar match_id. Unknown result
          on a ranked or unknown queue -> KEEP (fail safe).

DECISION (pure: `select_for_deletion(rows, policy, now)`)
------------------------------------------------------
Per row, first match wins:
  PROTECTED  owner is not "rc" (owner=operator, or missing - fail closed),
             or the row is pinned. Never a candidate, never evicted.
  ABSENT     the recorded path is not on disk. Reported, not counted.
  UNDATED    no usable wall time. Counted, never a candidate or evicted.
  HELD       a recording still in progress, or one whose death reel has not
             been read back non-empty while the sidecar does not record zero
             deaths. Never removed, not even over the cap (the reel is what
             survives the VOD).
  KEEP       any keep reason holds - mark pressed, ranked loss, PGR below
             threshold, or an unknown mark count / ranked result (fail safe);
             clips RC made are kept as the distilled product - and the file
             is younger than keep_days.
  CANDIDATE  otherwise: not kept, or kept but aged out.
Then the cap: if the RC-recorded bytes left after removing candidates exceed
cap_bytes, KEEP rows are evicted oldest first until under. `pinned_fill_cap`
is raised when pinned bytes alone reach the cap (ADR-016: recording then
refuses to start; that refusal belongs to the disk guard, not here).

Constants (our own, per the directive's rule on numbers):
  keep_days 14 and cap 60 GB are ADR-016's adjudicated values (decimal GB,
  matching ADR-016's decimal MB/s measurements). pgr_keep_below 40.0 is a
  PLACEHOLDER: the s220 PGR 0-100 score does not exist yet (deferred to
  ROADMAP-S3), so the rule is inert until a sidecar carries `pgr_score`;
  re-measure the threshold against real scores when S3 ships.

IO (thin)
---------
`plan()` reads sidecars and stats the recorded paths (read-only). `apply()`
is DRY-RUN BY DEFAULT and stays dry until the operator turns it off: it
returns `would_recycle` and touches nothing. The real path needs
dry_run=False AND CONFIRM_TOKEN, re-checks every fence on each row, removes
ONLY via core.recycle_bin.recycle_checked (never unlink; refuses rather than
fall back to a permanent delete; confirms the item landed in the bin) and
halts on the first detected nuke. Sidecars are never written or removed. As
with core/data_retention.py, NOTHING in RC calls apply() and the CLI has no
apply flag.

Run:
    python -m core.vod_retention
    python -m core.vod_retention --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.replay_roster import RANKED_QUEUES

KIND_RECORDING = "recording"
KIND_CLIP = "clip"

OWNER_RC = "rc"

ACTION_PROTECTED = "protected"
ACTION_ABSENT = "absent"
ACTION_UNDATED = "undated"
ACTION_HELD = "held"
ACTION_KEEP = "keep"
ACTION_CANDIDATE = "candidate"

DEFAULT_KEEP_DAYS = 14.0
DEFAULT_CAP_BYTES = 60 * 10**9
DEFAULT_PGR_KEEP_BELOW = 40.0  # placeholder, see module docstring

CONFIRM_TOKEN = "yes-recycle-vod-candidates"

# The RM-637 recorder's sidecar body keys (core/obs_recorder.py
# `_write_sidecar`). tests/test_vod_retention.py parses the recorder source
# and asserts equality, so a writer change reds a test instead of silently
# starving this reader.
RECORDER_SIDECAR_KEYS = (
    "schema", "status", "match_id", "queue_id", "game_mode", "mode", "owner",
    "obs_output_path", "ownership_token", "game_time_offset_s", "alignment",
    "start_game_time_s", "wall", "stop_reason", "death_count", "bookmarks",
    "diagnostics",
)
RECORDER_WALL_KEYS = ("attach", "record_start", "record_stop", "game_end")
# created_at precedence; wall.attach is deliberately absent.
_CREATED_AT_WALL_KEYS = ("record_stop", "game_end", "record_start")
STATUS_FINAL = "final"

DEFAULT_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

_DAY = 86400.0


@dataclass(frozen=True)
class VodRow:
    """One file in scope. None means UNKNOWN for marks / win / created_at."""
    match_id: str
    path: str
    kind: str = KIND_RECORDING
    owner: str = OWNER_RC
    size_bytes: Optional[int] = 0
    created_at: Optional[float] = None
    deaths: Optional[int] = None
    marks: Optional[int] = 0
    pinned: bool = False
    queue_id: Optional[int] = None
    win: Optional[bool] = None
    pgr_score: Optional[float] = None
    death_reel_ok: bool = False
    sidecar_path: str = ""
    final: bool = True


@dataclass(frozen=True)
class Policy:
    keep_days: float = DEFAULT_KEEP_DAYS
    cap_bytes: int = DEFAULT_CAP_BYTES
    pgr_keep_below: float = DEFAULT_PGR_KEEP_BELOW
    ranked_queues: tuple = RANKED_QUEUES


@dataclass(frozen=True)
class Decision:
    row: VodRow
    action: str
    reasons: tuple


@dataclass
class RetentionDecisions:
    decisions: list = field(default_factory=list)
    cap_bytes: int = DEFAULT_CAP_BYTES
    total_bytes: int = 0
    bytes_after: int = 0
    pinned_bytes: int = 0
    over_cap_after: bool = False
    pinned_fill_cap: bool = False

    @property
    def candidates(self) -> list:
        return [d for d in self.decisions if d.action == ACTION_CANDIDATE]

    def to_dict(self) -> dict:
        return {
            "cap_bytes": self.cap_bytes,
            "total_bytes": self.total_bytes,
            "bytes_after": self.bytes_after,
            "pinned_bytes": self.pinned_bytes,
            "over_cap_after": self.over_cap_after,
            "pinned_fill_cap": self.pinned_fill_cap,
            "decisions": [
                {**asdict(d.row), "action": d.action, "reasons": list(d.reasons)}
                for d in self.decisions
            ],
        }


# -- pure decision -------------------------------------------------------------


def _validate(policy: Policy) -> None:
    # RM-363 shape: a cap or age at 0 or below inverts the predicate and
    # makes everything a candidate, so reject before deciding anything.
    if not policy.cap_bytes or policy.cap_bytes < 1:
        raise ValueError(f"cap_bytes must be >= 1, got {policy.cap_bytes}")
    if not policy.keep_days or policy.keep_days <= 0:
        raise ValueError(f"keep_days must be > 0, got {policy.keep_days}")


def _keep_reasons(r: VodRow, policy: Policy) -> list:
    reasons = []
    if r.kind == KIND_CLIP:
        reasons.append("rc clip")
        return reasons
    if r.marks is None:
        reasons.append("mark count unknown (fail safe)")
    elif r.marks > 0:
        reasons.append(f"mark pressed x{r.marks}")
    ranked_or_unknown = r.queue_id is None or r.queue_id in policy.ranked_queues
    if r.queue_id in policy.ranked_queues and r.win is False:
        reasons.append(f"ranked loss (queue {r.queue_id})")
    elif ranked_or_unknown and r.win is None:
        reasons.append(f"result unknown on queue {r.queue_id} (fail safe)")
    if r.pgr_score is not None and r.pgr_score < policy.pgr_keep_below:
        reasons.append(f"PGR {r.pgr_score:g} < {policy.pgr_keep_below:g}")
    return reasons


def select_for_deletion(rows: Iterable[VodRow], policy: Policy,
                        now: float) -> RetentionDecisions:
    """Pure. Never touches the filesystem."""
    _validate(policy)
    out = RetentionDecisions(cap_bytes=policy.cap_bytes)
    staged: list = []  # [row, action, reasons]
    for r in rows:
        if (r.owner or "").strip().lower() != OWNER_RC:
            staged.append([r, ACTION_PROTECTED,
                           [f"owner={r.owner or 'unknown'}: never a candidate"]])
            continue
        if r.size_bytes is None:
            staged.append([r, ACTION_ABSENT, ["recorded path not on disk"]])
            continue
        if r.pinned:
            staged.append([r, ACTION_PROTECTED, ["pinned"]])
            continue
        if r.created_at is None:
            staged.append([r, ACTION_UNDATED,
                           ["no wall.record_stop / game_end / record_start"]])
            continue
        if not r.final:
            staged.append([r, ACTION_HELD, ["recording not finalized"]])
            continue
        if (r.kind == KIND_RECORDING and not r.death_reel_ok
                and r.deaths != 0):
            staged.append([r, ACTION_HELD,
                           ["death reel not read back non-empty"
                            f" (deaths={r.deaths})"]])
            continue
        keep = _keep_reasons(r, policy)
        age_days = (now - r.created_at) / _DAY
        if keep and age_days < policy.keep_days:
            staged.append([r, ACTION_KEEP, keep])
        elif keep:
            staged.append([r, ACTION_CANDIDATE,
                           keep + [f"aged out ({age_days:.1f} d >="
                                   f" {policy.keep_days:g} d)"]])
        else:
            staged.append([r, ACTION_CANDIDATE, ["no keep condition"]])

    counted = [s for s in staged
               if s[1] not in (ACTION_ABSENT,)
               and (s[0].owner or "").strip().lower() == OWNER_RC]
    out.total_bytes = sum(s[0].size_bytes or 0 for s in counted)
    out.pinned_bytes = sum(s[0].size_bytes or 0 for s in counted
                           if s[0].pinned)
    remaining = sum(s[0].size_bytes or 0 for s in counted
                    if s[1] != ACTION_CANDIDATE)
    if remaining > policy.cap_bytes:
        evictable = sorted((s for s in counted if s[1] == ACTION_KEEP),
                           key=lambda s: (s[0].created_at, s[0].path))
        for s in evictable:
            if remaining <= policy.cap_bytes:
                break
            s[1] = ACTION_CANDIDATE
            s[2] = list(s[2]) + ["over cap: oldest unpinned evicted first"]
            remaining -= s[0].size_bytes or 0
    out.bytes_after = remaining
    out.over_cap_after = remaining > policy.cap_bytes
    out.pinned_fill_cap = out.pinned_bytes >= policy.cap_bytes
    out.decisions = [Decision(s[0], s[1], tuple(s[2])) for s in staged]
    return out


# -- sidecar parse ---------------------------------------------------------------


def _int_or_none(v) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _epoch(v) -> Optional[float]:
    """A positive finite epoch, or None. 0 / negative / junk are NOT times."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f > 0 and f == f and f != float("inf") else None


def created_at_from_wall(doc: dict) -> Optional[float]:
    wall = doc.get("wall") if isinstance(doc, dict) else None
    if not isinstance(wall, dict):
        return None
    for k in _CREATED_AT_WALL_KEYS:
        t = _epoch(wall.get(k))
        if t is not None:
            return t
    return None


def game_id_from_match_id(match_id) -> Optional[str]:
    """'NA1_7001' or '7001' -> '7001'; anything else -> None.

    Same rule as core.moment_marks._game_id_from_match_id (RM-638): the
    recorder's match_id is the sanitized LCU gameId.
    """
    if not isinstance(match_id, str):
        return None
    s = match_id.strip()
    if "_" in s:
        prefix, _, s = s.partition("_")
        if not prefix.isalnum():
            return None
    if not s.isdigit() or len(s) > 20 or int(s) == 0:
        return None
    return s


def rows_from_sidecar(doc: dict, sidecar_path,
                      stat_size: Callable[[str], Optional[int]],
                      marks_for: Optional[Callable] = None,
                      result_for: Optional[Callable] = None) -> list:
    """Rows for one recorder sidecar (see SIDECAR CONTRACT above).

    `stat_size(path)` -> bytes, or None if absent. `marks_for(match_id,
    window)` -> pressed-mark count or None (unknown); window is
    mark_window(doc). `result_for(match_id)` -> True /
    False (operator won / lost) or None (unknown). Missing callables mean
    UNKNOWN, which keeps the file (fail safe).
    """
    if not isinstance(doc, dict):
        return []
    sidecar = str(sidecar_path)
    mid = str(doc.get("match_id") or Path(sidecar).stem)
    owner = str(doc.get("owner") or "")
    created = created_at_from_wall(doc)
    final = doc.get("status") == STATUS_FINAL
    pinned = bool(doc.get("pinned"))
    deaths = _int_or_none(doc.get("death_count"))
    pgr = doc.get("pgr_score")
    pgr = float(pgr) if isinstance(pgr, (int, float)) and not isinstance(pgr, bool) else None

    reel = doc.get("death_reel")
    reel_path = reel.get("path") if isinstance(reel, dict) else None
    reel_size = stat_size(str(reel_path)) if reel_path else None
    reel_ok = bool(reel_size) and reel_size > 0

    rows = []
    video = doc.get("obs_output_path")
    if video:
        rows.append(VodRow(
            match_id=mid, path=str(video), kind=KIND_RECORDING, owner=owner,
            size_bytes=stat_size(str(video)), created_at=created,
            deaths=deaths,
            marks=_safe_call(marks_for, (mid, mark_window(doc)), _int_or_none),
            pinned=pinned, queue_id=_int_or_none(doc.get("queue_id")),
            win=_safe_call(result_for, (mid,),
                           lambda v: v if isinstance(v, bool) else None),
            pgr_score=pgr, death_reel_ok=reel_ok, sidecar_path=sidecar,
            final=final,
        ))

    # Clips RC itself produced (the death reel included). RC made them, so
    # they are RC-owned even when the source recording was the operator's.
    clip_paths = []
    if reel_path:
        clip_paths.append((str(reel_path), created, pinned))
    for c in doc.get("clips") or []:
        if isinstance(c, dict) and c.get("path"):
            ts = _epoch(c.get("created_at"))
            clip_paths.append((str(c["path"]),
                               ts if ts is not None else created,
                               pinned or bool(c.get("pinned"))))
    seen = set()
    for path, ts, pin in clip_paths:
        if path in seen:
            continue
        seen.add(path)
        rows.append(VodRow(
            match_id=mid, path=path, kind=KIND_CLIP, owner=OWNER_RC,
            size_bytes=stat_size(path), created_at=ts, pinned=pin,
            sidecar_path=sidecar, final=final,
        ))
    return rows


def _safe_call(fn, args: tuple, coerce):
    if fn is None:
        return None
    try:
        return coerce(fn(*args))
    except Exception:  # noqa: BLE001 - any reader failure is UNKNOWN (fail safe)
        return None


# -- outside-the-sidecar readers (read-only) ----------------------------------------


def mark_window(doc: dict) -> Optional[tuple]:
    """(record_start, record_stop) from the sidecar wall block, or None."""
    wall = doc.get("wall") if isinstance(doc, dict) else None
    if not isinstance(wall, dict):
        return None
    start, stop = _epoch(wall.get("record_start")), _epoch(wall.get("record_stop"))
    if start is None or stop is None or stop < start:
        return None
    return (start, stop)


def moment_marks_count(match_id, window: Optional[tuple] = None) -> Optional[int]:
    """Pressed marks for a match, or None unless the count is PROVEN.

    Proven = the match id is a real gameId AND either
      (a) a readable, well-formed pin file exists (its pin count), or
      (b) no pin file exists, the raw marks jsonl reads cleanly, and the
          count of raw marks with that gameId OR a wall_ts inside the
          recording window (widened by core.moment_marks.ATTACH_SLACK_S)
          is taken - so marks whose attach failed still keep the file.
    An `unknown-*` match id, a corrupt / unreadable pin file or jsonl, no
    recording window, or the reader missing -> None -> KEEP (fail safe).
    pins_for_match is NOT used: it returns [] on every miss.
    """
    gid = game_id_from_match_id(match_id)
    if gid is None:
        return None
    try:
        from core.moment_marks import (ATTACH_SLACK_S, MarksUnreadable,
                                       pins_for_match_strict, read_marks_strict)
    except ImportError:
        return None
    try:
        pins = pins_for_match_strict(match_id)
        if pins is not None:
            return len(pins)
        if window is None:
            return None
        lo, hi = window[0] - ATTACH_SLACK_S, window[1] + ATTACH_SLACK_S
        raw = read_marks_strict()
    except MarksUnreadable:
        return None
    return sum(1 for m in raw
               if m.get("game_id") == gid or lo <= m["wall_ts"] <= hi)


class RewindResultLookup:
    """Operator win/loss from rewind_history.db, opened READ-ONLY.

    `matches.tracked_win` is the tracked (operator's) row, the same column
    core/aftergame_summary._match_meta reads. The sidecar carries only the
    gameId, so rows are matched on the part after the platform prefix.
    Any miss, NULL or DB error -> None (unknown).
    """

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DEFAULT_REWIND_DB
        self._cache: dict = {}

    def __call__(self, match_id) -> Optional[bool]:
        gid = game_id_from_match_id(match_id)
        if gid is None:
            return None
        if gid in self._cache:
            return self._cache[gid]
        val = None
        if self.db_path.exists():
            import sqlite3
            try:
                conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro",
                                       uri=True)
                try:
                    rows = conn.execute(
                        "SELECT tracked_win FROM matches WHERE match_id = ?"
                        " OR substr(match_id, instr(match_id, '_') + 1) = ?",
                        (gid, gid)).fetchall()
                finally:
                    conn.close()
                wins = {r[0] for r in rows if r[0] is not None}
                if len(wins) == 1:  # two platforms disagreeing = unknown
                    val = bool(wins.pop())
            except sqlite3.Error:
                val = None
        self._cache[gid] = val
        return val


# -- thin IO ----------------------------------------------------------------------


def _stat_size(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_size
    except OSError:
        return None


def default_sidecar_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "recordings"


_DEFAULT = object()


def load_rows(sidecar_dir, stat_size=_stat_size, marks_for=_DEFAULT,
              result_for=_DEFAULT) -> list:
    """Read-only. Lists RC's OWN sidecar index; never a video folder."""
    d = Path(sidecar_dir)
    if not d.is_dir():
        return []
    if marks_for is _DEFAULT:
        marks_for = moment_marks_count
    if result_for is _DEFAULT:
        result_for = RewindResultLookup()
    rows = []
    for sc in sorted(d.glob("*.json")):
        try:
            doc = json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.extend(rows_from_sidecar(doc, sc, stat_size, marks_for, result_for))
    return rows


def plan(sidecar_dir=None, policy: Optional[Policy] = None,
         now: Optional[float] = None, *, marks_for=_DEFAULT,
         result_for=_DEFAULT) -> RetentionDecisions:
    import time
    return select_for_deletion(
        load_rows(sidecar_dir or default_sidecar_dir(),
                  marks_for=marks_for, result_for=result_for),
        policy or Policy(),
        time.time() if now is None else now,
    )


def _fence_violation(d: Decision) -> Optional[str]:
    r = d.row
    if d.action != ACTION_CANDIDATE:
        return f"action={d.action}"
    if (r.owner or "").strip().lower() != OWNER_RC:
        return f"owner={r.owner or 'unknown'}"
    if r.pinned:
        return "pinned"
    if r.created_at is None:
        return "undated"
    if not r.final:
        return "not finalized"
    if r.kind == KIND_RECORDING and not r.death_reel_ok and r.deaths != 0:
        return "death reel not read back"
    if r.sidecar_path and os.path.normcase(os.path.abspath(r.path)) == \
            os.path.normcase(os.path.abspath(r.sidecar_path)):
        return "path is the sidecar itself"
    return None


def apply(res: RetentionDecisions, *, dry_run: bool = True,
          confirm: Optional[str] = None, recycler=None) -> dict:
    """Enforcement arm. DRY-RUN BY DEFAULT; NOTHING in RC calls it.

    Real removal needs dry_run=False AND confirm == CONFIRM_TOKEN, and goes
    only through the checked Recycle Bin path. Never raises for a per-file
    failure; halts on the first detected permanent delete.
    """
    out = {"dry_run": dry_run, "would_recycle": [], "recycled": [],
           "failed": [], "refused": [], "halted": False}
    todo = []
    for d in res.candidates:
        bad = _fence_violation(d)
        if bad:
            out["refused"].append({"path": d.row.path, "why": bad})
        else:
            todo.append(d)
    out["would_recycle"] = [d.row.path for d in todo]
    if dry_run or confirm != CONFIRM_TOKEN:
        return out
    if recycler is None:
        from core.recycle_bin import recycle_checked as recycler
    for d in todo:
        r = recycler(d.row.path)
        entry = {"path": d.row.path, "detail": r.detail,
                 "bytes": d.row.size_bytes or 0}
        if r.ok:
            out["recycled"].append(entry)
        else:
            out["failed"].append(entry)
            if getattr(r, "nuked", False):
                out["halted"] = True
                break
    return out


# -- rendering --------------------------------------------------------------------


def _fmt(b: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(b)
    i = 0
    while f >= 1000 and i < len(units) - 1:
        f /= 1000
        i += 1
    return f"{f:.1f} {units[i]}"


def render_report(res: RetentionDecisions) -> str:
    """Human-readable dry-run report. ASCII only. Read-only."""
    lines = ["VOD retention plan (dry-run) - sidecar-recorded paths only",
             "-" * 72,
             f"RC-recorded bytes: {_fmt(res.total_bytes)}"
             f"  cap {_fmt(res.cap_bytes)}"
             f"  after plan {_fmt(res.bytes_after)}"
             f"  pinned {_fmt(res.pinned_bytes)}"]
    if res.over_cap_after:
        lines.append("  WARNING: still over cap after plan"
                     " (pinned / held files cannot be evicted)")
    if res.pinned_fill_cap:
        lines.append("  WARNING: pinned files alone fill the cap;"
                     " recording should refuse to start")
    lines.append("")
    order = (ACTION_CANDIDATE, ACTION_HELD, ACTION_UNDATED, ACTION_KEEP,
             ACTION_PROTECTED, ACTION_ABSENT)
    for act in order:
        group = [d for d in res.decisions if d.action == act]
        if not group:
            continue
        lines.append(f"{act} (n={len(group)}):")
        for d in group:
            size = _fmt(d.row.size_bytes) if d.row.size_bytes is not None else "-"
            lines.append(f"  {size:>10}  {d.row.kind:<9} {d.row.match_id:<20}"
                         f" {d.row.path}")
            lines.append(f"              {'; '.join(d.reasons)}")
    lines.append("")
    lines.append("candidate = would go to the Recycle Bin (checked, never")
    lines.append("  unlinked). Nothing in RC calls apply(); sidecars survive.")
    text = "\n".join(lines)
    return text.encode("ascii", "replace").decode("ascii")


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Dry-run VOD retention report. Removes nothing.")
    ap.add_argument("--sidecar-dir", default=str(default_sidecar_dir()))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    res = plan(args.sidecar_dir)
    print(json.dumps(res.to_dict(), indent=2) if args.json
          else render_report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
