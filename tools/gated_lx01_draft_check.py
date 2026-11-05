"""gated_lx01_draft_check.py - read the champ-select draft log for the LX-01 drain.

LX-01 (RM-609) asks whether ONE real draft champ select, with the LCU agent
running, lands rows in ``rewind_history.db`` table ``draft_log``; whether the
session's gameId was set at FINALIZATION or the gameflow fallback fired;
whether trades show in ``final_champion_id``; whether the Match-V5 row joins on
game_id and ``attach_draft_log`` names the right lane opponent; whether a
no-pick session (ARAM / Arena) writes no rows and reads ``draft_source='none'``;
and whether the agent's writes coexist with the post-game ingest without lock
errors. Checking that by hand is a SQL session per question; this tool prints
it in ONE command.

It is READ-ONLY. ``grade`` opens the DB with a ``mode=ro`` URI and calls only
``lcu.draft_log``'s SELECT-only readers (``load_draft``, ``attach_draft_log``).
``tape`` reads the same DB ``mode=ro`` once (its BASELINE row: is there a
``draft_log`` table, how many rows, before the pop), only GETs ``/api/state``,
and writes ONE new file it is told to create (``open("x")``: it never
overwrites; missing parent directories are created). A ``mode=ro`` open of a
WAL database may still create its ``-wal`` / ``-shm`` sidecars when they are
absent (SQLite's own behaviour); the live DB already has both, and the
database file's content is never written.

THE WITNESS. While the phase is ChampSelect, ``tape`` also records each change
of ``/api/state`` ``lcu.champ_select`` as cell -> locked champion over both
teams (ids only). ``grade`` compares the stored pick finals with the LAST
witness taken no later than ``WITNESS_LAG_S`` (2 s) after the write: what
``/api/state`` showed live against what the agent stored.
With the path, the baseline and ``captured_after_tape_start``, it separates the
live sink's write from a row written by hand after the first game phase plus
the slack (that reads LATE, and a LATE write never passes the doc's WRITE
half). It CANNOT separate a hand-written row from the same session written
between all picks being locked and that point; the doc's substitution check
names it.
Neither subcommand ticks a row: the output is the INPUT to the four-part
evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. Rows written by
``lcu.draft_log.store_draft`` from a synthetic session pass every check just as
well; that is the substitution the LX-01 row names.

THE PATH QUESTION. A draft row carries no "which path wrote me" field. The
only witness is time: the recorder writes at the first finalized tick when the
session carries a gameId (champ select, before GameStart), and at the first
GameStart / InProgress / Reconnect tick otherwise (``lcu/snapshot_shape.py``
``note_game_id``). ``tape`` records the LCU phase from ``/api/state``
(``lcu.phase`` / ``lcu.ts``; the agent sends them every 1 s through the :8889
``/latest-lcu`` relay, ``dashboard/_liveclient.py``, unless ``RC_LCU_INPROCESS=1``
lets the dashboard read LCU itself) so ``grade --phase-tape`` can place
``captured_at`` against the first game phase: FINALIZATION when it is at
least ``--path-slack`` seconds earlier, FALLBACK when within the slack, LATE
when later (a retried write after a refused one, or a write by hand), UNKNOWN
without a tape transition.

``--log`` takes a file or a glob (``*``, ``?`` or ``[``; e.g.
``logs/<day>.log*``), because both the agent log and the RC day log rotate by
size inside a day. A missing file, or a glob that matches nothing, is
reported as one ``missing`` entry (exit 0), never skipped silently.

THE JOIN. ``attach_draft_log`` derives the ally team from the draft's own local
pick. The tool cross-checks it against the Match-V5 row's OWN
``matches.tracked_team_id`` / ``tracked_champion_id`` and ``participants``:
ally pick finals must be the tracked team's champions, enemy finals the other
team's, the local final the tracked champion, and the lane opponent the enemy
whose ``team_position`` equals the tracked player's.

Game ids and match ids print only with ``--show-id`` (RM-906: never paste them
into a tracked file); games are ``g1``.. otherwise. Player names are never read.

USAGE
    python tools/gated_lx01_draft_check.py tape --out ops/runtime/lx01/phase_<n>.jsonl
    python tools/gated_lx01_draft_check.py grade --since <epoch|iso> --until <epoch|iso>
        --phase-tape <tape> --log 'logs/lcu_agent.log*' --log 'logs/<day>.log*' --json

Exit 2 = the database or the named tape is missing or unreadable, a log file
exists but cannot be read, --since / --until does not parse, ``tape --out``
already exists, or an argparse usage error.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lcu import draft_log as dl  # noqa: E402

DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
DEFAULT_STATE_URL = "https://127.0.0.1:8888/api/state"
GAME_PHASES = frozenset({"GameStart", "InProgress", "Reconnect"})
WITNESS_LAG_S = 2.0
# The recorder's own failure lines (lcu/draft_log.py, tools/lcu_agent.py) and
# SQLite's lock error from any writer, the post-game ingest included.
LOG_PATTERNS = {
    "sink_failed": "draft_log sink failed",
    "observe_failed": "draft_log observe failed",
    "note_game_id_failed": "draft_log note_game_id failed",
    "sink_not_installed": "[draft-log] sink not installed",
    "database_locked": "database is locked",
}
_LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_CLOCK_TS = re.compile(r"^(\d{2}:\d{2}:\d{2})\.\d{3} ")
_DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.log")
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE  # loopback mkcert dashboard, same as curl -k


def _ro(path: Path) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise FileNotFoundError("database not found")
    uri = "file:" + quote(Path(path).resolve().as_posix(), safe="/:") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10.0)


def parse_when(s: Any) -> Optional[float]:
    """ISO 8601 (naive = local time, 'Z' or an offset honoured) or a bare
    ``date +%s`` epoch -> epoch s."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip()
    if t.isascii() and t.isdigit():
        # An epoch is at most 12 digits. A longer all-digit string is neither
        # an epoch nor ISO 8601: fromisoformat would take its ninth digit as
        # the date / time separator (CI run 41218770716), so refuse it.
        return float(t) if len(t) <= 12 else None
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return d.timestamp() if d.tzinfo else d.astimezone().timestamp()
    except (ValueError, OSError, OverflowError):  # OSError: a year Windows cannot localise
        return None


def _in(t: Optional[float], since: Optional[float], until: Optional[float]) -> bool:
    if t is None:
        return False
    return (since is None or t >= since) and (until is None or t <= until)


def _table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


# -- draft rows ---------------------------------------------------------------

def draft_games(conn: sqlite3.Connection, since: Optional[float] = None,
                until: Optional[float] = None) -> dict:
    """game_id -> the raw draft_log rows whose captured_at is in the window."""
    if not _table(conn, "draft_log"):
        return {}
    out: dict = {}
    for row in conn.execute(
            "SELECT game_id, action_index, turn, actor_cell_id, side, assigned_position, "
            "action_type, champion_id, completed, final_champion_id, is_local, queue_id, "
            "draft_source, captured_at FROM draft_log ORDER BY game_id, action_index"):
        if _in(parse_when(row[13]), since, until):
            out.setdefault(row[0], []).append(row)
    return out


def grade_rows(rows: list) -> dict:
    """Shape checks on one game's stored rows (no join, no clock)."""
    idx = [r[1] for r in rows]
    turns = [r[2] for r in rows]
    types = Counter(r[6] for r in rows)
    picks = [r for r in rows if r[6] == "pick"]
    sides = Counter(r[4] for r in picks)
    problems = []
    if idx != list(range(len(rows))):
        problems.append("action_index not 0..n-1")
    if any(b < a for a, b in zip(turns, turns[1:])):
        problems.append("turn decreases")
    # Only pick / ban rows must belong to a team: LCU may also list actions
    # with no actor cell (actorCellId -1, e.g. a ban-reveal step); those are
    # counted as unowned_actions, never a problem.
    if any(r[4] not in ("ally", "enemy") for r in rows if r[6] in ("pick", "ban")):
        problems.append("a pick/ban row outside ally/enemy")
    if {r[12] for r in rows} != {dl.DRAFT_SOURCE_LCU}:
        problems.append("draft_source not all 'lcu'")
    if len({r[13] for r in rows}) != 1:
        problems.append("more than one captured_at")
    if len({r[11] for r in rows}) != 1:
        problems.append("more than one queue_id")
    local_picks = [r for r in picks if r[10] == 1]
    if len(local_picks) != 1:
        problems.append(f"{len(local_picks)} local pick rows (want 1)")
    if any(r[8] != 1 for r in picks):
        problems.append("an incomplete pick at finalize")
    if any(r[9] <= 0 for r in picks):
        problems.append("a pick with no final champion")
    return {
        "actions": len(rows), "types": dict(sorted(types.items())),
        "picks_ally": sides.get("ally", 0), "picks_enemy": sides.get("enemy", 0),
        "swaps": sum(1 for r in picks if r[7] != r[9]),
        "enemy_position_hidden": sum(1 for r in picks if r[4] == "enemy" and not r[5]),
        "unowned_actions": sum(1 for r in rows if r[4] not in ("ally", "enemy")),
        # 0 = the session carried no gameData.queue at finalize; the recorder
        # has no gameflow fallback (lcu/draft_log.session_queue_id).
        "queue_id": rows[0][11] if rows else None,
        "captured_at": rows[0][13] if rows else None,
        "problems": problems,
    }


# -- the Match-V5 join ----------------------------------------------------------

def match_for(conn: sqlite3.Connection, game_id: int) -> Optional[tuple]:
    """(match_id, queue_id, tracked_team_id, tracked_champion_id) or None."""
    if not _table(conn, "matches"):
        return None
    for row in conn.execute(
            "SELECT match_id, queue_id, tracked_team_id, tracked_champion_id FROM matches "
            "WHERE match_id LIKE ? ESCAPE '\\'", ("%\\_" + str(int(game_id)),)):
        if dl.game_id_from_match_id(row[0]) == game_id:
            return row
    return None


def check_join(conn: sqlite3.Connection, game_id: int, rows: list) -> dict:
    m = match_for(conn, game_id)
    if m is None:
        return {"verdict": "NO_MATCH_ROW"}
    match_id, mqueue, team, champ = m
    att = dl.attach_draft_log(conn, match_id)
    roster = conn.execute(
        "SELECT team_id, champion_id, team_position FROM participants WHERE match_id=?",
        (match_id,)).fetchall() if _table(conn, "participants") else []
    ally = sorted(c for t, c, _p in roster if t == team)
    enemy = sorted(c for t, c, _p in roster if t != team)
    picks = [r for r in rows if r[6] == "pick"]
    local = next((r[9] for r in picks if r[10] == 1), 0)
    my_pos = next((p for t, c, p in roster if t == team and c == champ), "") or ""
    want_opp = next((c for t, c, p in roster if t != team and my_pos and p == my_pos), 0)
    got_opp = (att.get("lane_opponent") or {}).get("champion_id", 0)
    mism = []
    if att.get("draft_source") != dl.DRAFT_SOURCE_LCU:
        mism.append("attach_draft_log draft_source != 'lcu'")
    if sorted(r[9] for r in picks if r[4] == "ally") != ally:
        mism.append("ally pick finals != tracked team champions")
    if sorted(r[9] for r in picks if r[4] == "enemy") != enemy:
        mism.append("enemy pick finals != other team champions")
    if local != champ:
        mism.append("local final != matches.tracked_champion_id")
    if got_opp != want_opp:
        mism.append("lane_opponent != enemy at the tracked team_position")
    if rows and rows[0][11] and mqueue != rows[0][11]:
        mism.append("draft queue_id != matches.queue_id")
    return {"verdict": "JOIN_MISMATCH" if mism else "JOIN_OK", "mismatches": mism,
            "match_queue_id": mqueue, "tracked_position": my_pos or None,
            "lane_opponent_champion_id": got_opp or None,
            "expected_opponent_champion_id": want_opp or None,
            "local_picked_before_opponent": att.get("local_picked_before_opponent"),
            "match_id": match_id}


def no_draft_matches(conn: sqlite3.Connection, games: dict, since: Optional[float],
                     until: Optional[float]) -> list:
    """Match rows created in the window with no captured draft: each must read
    draft_source 'none' with no actions and no derived fields."""
    if since is None or not _table(conn, "matches"):
        return []
    out = []
    for match_id, queue_id, created in conn.execute(
            "SELECT match_id, queue_id, game_creation_ts FROM matches ORDER BY game_creation_ts"):
        t = created / 1000.0 if isinstance(created, (int, float)) else None
        gid = dl.game_id_from_match_id(match_id)
        if not _in(t, since, until) or gid is None or gid in games:
            continue
        att = dl.attach_draft_log(conn, match_id)
        clean = (att["draft_source"] == dl.DRAFT_SOURCE_NONE and att["actions"] == []
                 and att["lane_opponent"] is None
                 and att["local_picked_before_opponent"] is None)
        out.append({"queue_id": queue_id, "draft_source": att["draft_source"],
                    "clean_none": clean, "match_id": match_id})
    return out


# -- the path witness -----------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        return float(v)
    return None


def load_tape(path: Path) -> dict:
    """A ``tape`` file -> {"start", "baseline", "phases": [(t, phase)],
    "witness": [(t, {cell: champion})]}, oldest first; torn lines skipped."""
    out: dict = {"start": None, "baseline": None, "phases": [], "witness": []}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        t = _num(d.get("lcu_ts")) or _num(d.get("t"))
        if t is None:
            continue
        if "baseline" in d:
            out["start"], out["baseline"] = t, d["baseline"]
        elif isinstance(d.get("witness"), dict):
            picks = d["witness"].get("picks")
            if isinstance(picks, dict):
                out["witness"].append((t, {str(k): v for k, v in picks.items()}))
        elif "phase" in d:
            out["phases"].append((t, d.get("phase")))
    for k in ("phases", "witness"):
        out[k].sort(key=lambda x: x[0])
    return out


def check_witness(rows: list, captured: Optional[float], witness: list,
                  lag: float = WITNESS_LAG_S) -> dict:
    """Stored pick finals against the LAST champ-select witness taken no later
    than ``lag`` s after the write: what /api/state showed while the draft
    was live, an independent read of the same session. ``captured_at`` is
    whole seconds and a witness row is stamped with the relay's ``lcu.ts``,
    so the write's own tick can carry a stamp just after ``captured_at``."""
    seen = [w for t, w in witness if captured is not None and t <= captured + lag]
    if not seen:
        return {"witness": "NONE"}
    last = seen[-1]
    picks = [r for r in rows if r[6] == "pick"]
    diff = [r[3] for r in picks if last.get(str(r[3])) != r[9]]
    return {"witness": "MISMATCH" if diff or not picks else "MATCH",
            "cells_differing": len(diff), "witness_cells": len(last)}


def classify_path(captured: Optional[float], tape: list, slack: float = 10.0) -> dict:
    """Place captured_at against the first game phase after the last champ
    select. ``tape`` is the (t, phase) list of ``load_tape(...)["phases"]``."""
    if captured is None:
        return {"path": "UNKNOWN", "why": "captured_at unparsable"}
    cs = [t for t, p in tape if p == "ChampSelect" and t <= captured + slack]
    start = cs[-1] if cs else None
    game = next((t for t, p in tape if p in GAME_PHASES
                 and (start is None or t >= start)), None)
    if game is None:
        return {"path": "UNKNOWN", "why": "no GameStart/InProgress/Reconnect on the tape"}
    delta = round(captured - game, 1)
    if delta <= -slack:
        path = "FINALIZATION"
    elif delta <= slack:
        path = "FALLBACK"
    else:
        path = "LATE"
    return {"path": path, "captured_minus_first_game_phase_s": delta,
            "champ_select_on_tape": start is not None}


# -- logs -------------------------------------------------------------------------

def _line_time(line: str, day: Optional[str]) -> Optional[float]:
    m = _LOG_TS.match(line)
    if m:
        return parse_when(m.group(1).replace(" ", "T"))
    m = _CLOCK_TS.match(line)
    return parse_when(f"{day}T{m.group(1)}") if m and day else None


def expand_logs(specs: list) -> list:
    """Each ``--log`` value as itself, or, when it holds ``*`` / ``?`` / ``[``, as its
    sorted glob matches (the pattern itself when nothing matches, so
    scan_logs reports it ``missing``)."""
    out: list = []
    for spec in specs:
        if any(ch in str(spec) for ch in "*?["):
            hits = sorted(glob.glob(str(spec)))
            out.extend(hits or [spec])
        else:
            out.append(spec)
    return out


def scan_logs(paths: list, since: Optional[float], until: Optional[float]) -> dict:
    """Counts of each LOG_PATTERNS line whose local timestamp is in the window.

    Two line shapes: ``lcu_agent.log`` stamps ``YYYY-MM-DD HH:MM:SS,mmm``; the
    RC day log ``logs/YYYY-MM-DD.log`` stamps ``HH:MM:SS.mmm`` and the day comes
    from the file name. A line with neither is not counted. Each file is
    reported on its own (``files[]``, by file NAME only) beside the totals, so
    a log with no line in the window cannot hide behind another's count."""
    counts = dict.fromkeys(LOG_PATTERNS, 0)
    files = []
    for p in paths:
        day = Path(p).name[:10] if _DAY_NAME.match(Path(p).name) else None
        own = dict.fromkeys(LOG_PATTERNS, 0)
        lines = 0
        if not Path(p).is_file():  # e.g. no rotated lcu_agent.log.1 yet
            files.append({"name": Path(p).name, "missing": True, "lines_in_window": 0,
                          "counts": own})
            continue
        for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            t = _line_time(line, day)
            if t is None:
                continue
            if (since is not None or until is not None) and not _in(t, since, until):
                continue
            lines += 1
            for k, pat in LOG_PATTERNS.items():
                if pat in line:
                    own[k] += 1
                    counts[k] += 1
        files.append({"name": Path(p).name, "lines_in_window": lines, "counts": own})
    return {"lines_in_window": sum(f["lines_in_window"] for f in files),
            "counts": counts, "files": files}


# -- grade --------------------------------------------------------------------------

def grade(conn: sqlite3.Connection, since: Optional[float] = None,
          until: Optional[float] = None, tape: Optional[dict] = None,
          slack: float = 10.0) -> dict:
    """``tape`` is ``load_tape(...)``: it adds the tape's pre-pop DB baseline,
    and per game the path, the witness check and whether the write came after
    the tape started."""
    games = draft_games(conn, since, until)
    out = {"table_present": _table(conn, "draft_log"), "games": [],
           "no_draft_matches": no_draft_matches(conn, games, since, until)}
    if tape is not None:
        out["tape_baseline"] = tape.get("baseline")
    for gid, rows in games.items():
        g = {"game_id": gid, **grade_rows(rows), "join": check_join(conn, gid, rows)}
        if tape is not None:
            cap = parse_when(g["captured_at"])
            g["path"] = classify_path(cap, tape["phases"], slack)
            g["witness"] = check_witness(rows, cap, tape["witness"])
            g["captured_after_tape_start"] = (None if cap is None or tape["start"] is None
                                              else cap >= tape["start"])
        out["games"].append(g)
    return out


def redact(s: dict) -> dict:
    s = json.loads(json.dumps(s))
    for i, g in enumerate(s.get("games", []), 1):
        g["game_id"] = f"g{i}"
        g.get("join", {}).pop("match_id", None)
    for i, m in enumerate(s.get("no_draft_matches", []), 1):
        m["match_id"] = f"m{i}"
    return s


def render(s: dict) -> str:
    lines = [f"draft_log table present: {s['table_present']}"]
    if not s["games"]:
        lines.append("no draft_log game in the window")
    for g in s["games"]:
        j = g["join"]
        lines.append(
            f"{g['game_id']}: queue={g['queue_id']} actions={g['actions']} types={g['types']} "
            f"picks ally/enemy={g['picks_ally']}/{g['picks_enemy']} swaps={g['swaps']} "
            f"enemy_pos_hidden={g['enemy_position_hidden']} captured_at={g['captured_at']}")
        lines.append(f"  problems: {g['problems'] or 'none'}")
        lines.append(f"  join: {j['verdict']} {j.get('mismatches') or ''}".rstrip())
        if "path" in g:
            lines.append(f"  path: {g['path']}")
            lines.append(f"  witness: {g['witness']} after_tape_start: "
                         f"{g['captured_after_tape_start']}")
    if "tape_baseline" in s:
        lines.append(f"tape baseline: {s['tape_baseline']}")
    for m in s["no_draft_matches"]:
        lines.append(f"{m['match_id']}: no draft, queue={m['queue_id']} "
                     f"draft_source={m['draft_source']} clean_none={m['clean_none']}")
    if "logs" in s:
        lines.append(f"logs: {s['logs']}")
    return "\n".join(lines)


# -- tape -------------------------------------------------------------------------

def _fetch_state(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=5, context=_SSL) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - a missed poll is a gap, never a crash
        return None
    return d if isinstance(d, dict) else None


def db_baseline(db: Path) -> dict:
    """Read-only: does draft_log exist, and how many rows, BEFORE the pop."""
    try:
        conn = _ro(Path(db))
    except (OSError, sqlite3.Error) as exc:
        return {"error": type(exc).__name__}
    try:
        present = _table(conn, "draft_log")
        rows = conn.execute("SELECT COUNT(*) FROM draft_log").fetchone()[0] if present else 0
        return {"table_present": present, "rows": rows}
    except sqlite3.Error as exc:
        return {"error": type(exc).__name__}
    finally:
        conn.close()


def _witness(cs: Any) -> Optional[dict]:
    """cell -> locked champion over both teams of ``lcu.champ_select``, plus
    its timer phase. Ids only: no name, puuid or summonerId is kept."""
    if not isinstance(cs, dict):
        return None
    picks = {}
    for team in ("my_team", "their_team"):
        for p in cs.get(team) or []:
            if isinstance(p, dict) and isinstance(p.get("cellId"), int):
                picks[str(p["cellId"])] = p.get("champion_locked")
    return {"timer": cs.get("phase"), "queue_id": cs.get("queue_id"), "picks": picks}


def record_tape(out: Path, url: str = DEFAULT_STATE_URL, interval: float = 1.0,
                max_s: float = 3600.0, fetch: Callable[[str], Optional[dict]] = _fetch_state,
                clock: Callable[[], float] = time.time,
                sleep: Callable[[float], None] = time.sleep,
                db: Optional[Path] = DEFAULT_DB) -> int:
    """Write a read-only DB baseline row, then one row per LCU phase CHANGE and
    one witness row per CHANGE of ``lcu.champ_select`` (timer phase, queue, the
    locked champion per cell), until a game phase has been seen for
    ``interval`` * 5 s or ``max_s`` elapses. Returns phase + witness rows."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0, last, last_w, n, game_seen = clock(), object(), None, 0, None
    with out.open("x", encoding="utf-8", newline="\n") as fh:
        base = db_baseline(db) if db is not None else {"error": "no db"}
        fh.write(json.dumps({"t": round(t0, 3), "baseline": base}) + "\n")
        fh.flush()
        while clock() - t0 < max_s:
            d = fetch(url)
            lcu = d.get("lcu") if isinstance(d, dict) else None
            if isinstance(lcu, dict):
                phase = lcu.get("phase")
                ts = _num(lcu.get("ts"))
                if phase != last:
                    fh.write(json.dumps({"t": round(clock(), 3), "phase": phase,
                                         "lcu_ts": ts}) + "\n")
                    fh.flush()
                    n, last = n + 1, phase
                w = _witness(lcu.get("champ_select")) if phase == "ChampSelect" else None
                if w is not None and w != last_w:
                    fh.write(json.dumps({"t": round(clock(), 3), "witness": w,
                                         "lcu_ts": ts}) + "\n")
                    fh.flush()
                    n, last_w = n + 1, w
                if phase in GAME_PHASES and game_seen is None:
                    game_seen = clock()
            if game_seen is not None and clock() - game_seen >= interval * 5:
                break
            sleep(interval)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only LX-01 check of the champ-select draft log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--db", default=str(DEFAULT_DB))
    g.add_argument("--since", default=None, help="ISO time; naive = local")
    g.add_argument("--until", default=None)
    g.add_argument("--phase-tape", default=None, help="a file written by the tape subcommand")
    g.add_argument("--path-slack", type=float, default=10.0)
    g.add_argument("--log", action="append", default=[],
                   help="a log file or glob to scan (repeatable)")
    g.add_argument("--show-id", action="store_true", help="print real game / match ids (never paste)")
    g.add_argument("--json", action="store_true")
    t = sub.add_parser("tape")
    t.add_argument("--out", required=True, help="a NEW file (never overwritten)")
    t.add_argument("--url", default=DEFAULT_STATE_URL)
    t.add_argument("--interval", type=float, default=1.0)
    t.add_argument("--max-s", type=float, default=3600.0)
    t.add_argument("--db", default=str(DEFAULT_DB), help="read-only baseline source")
    a = ap.parse_args(argv)
    if a.cmd == "tape":
        try:
            n = record_tape(Path(a.out), a.url, a.interval, a.max_s, db=Path(a.db))
        except FileExistsError:
            print("tape: --out already exists; name a new file", file=sys.stderr)
            return 2
        print(f"tape: {n} phase / witness rows")
        return 0
    since, until = parse_when(a.since), parse_when(a.until)
    for flag, raw, val in (("--since", a.since, since), ("--until", a.until, until)):
        if raw is not None and val is None:
            print(f"{flag}: not an ISO time", file=sys.stderr)
            return 2
    try:
        tape = load_tape(Path(a.phase_tape)) if a.phase_tape else None
        conn = _ro(Path(a.db))
        try:
            s = grade(conn, since, until, tape, a.path_slack)
        finally:
            conn.close()
        if a.log:
            s["logs"] = scan_logs(expand_logs(a.log), since, until)
    except (OSError, sqlite3.Error) as exc:
        print(f"unreadable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if not a.show_id:
        s = redact(s)
    print(json.dumps(s, indent=2, sort_keys=True) if a.json else render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
