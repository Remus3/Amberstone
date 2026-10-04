"""Per-game champ-select draft log (RM-609, directive X-09, external reference A).

Match-V5 carries side (teams.team_id), team_position, win and bans, and
rewind_history.db already stores all of them (scripts/rewind_scraper.py
participants.team_position at :146, teams.ban1..ban5 at :266-283). What
Match-V5 does NOT carry is pick ORDER. Only the LCU champ-select session has
it, and only while the client is in champ select, so it must be captured live
or it is gone. This module captures it.

What is snapshotted at finalize (``timer.phase == "FINALIZATION"``): one row
per action, in GLOBAL action order (the flattened ``session.actions`` groups):

  action_index       0-based position in the flattened action list
  turn               index of the action group (simultaneous actions share it)
  actor_cell_id      the acting cell
  side               'ally' | 'enemy' (membership in myTeam / theirTeam)
  assigned_position  the cell's assignedPosition ('' for enemies in solo
                     queue, where LCU hides it)
  action_type        'ban' | 'pick' | whatever LCU sent
  champion_id        championId ON THE ACTION (what was locked at the time)
  completed          0 | 1
  final_champion_id  the cell's championId in myTeam/theirTeam at finalize,
                     i.e. AFTER any trades; differs from champion_id on a swap
  is_local           1 for the local player's cell

Storage: a NEW sibling table ``draft_log`` in rewind_history.db, the DB the
post-game Match-V5 ingest already writes (lib/rewind_live_writer.py:85 DB_PATH
-> scripts/rewind_catchup.record_hydrated). Additive only; no existing table is
altered. Keyed by the numeric Riot gameId, which is the suffix of the Match-V5
match_id ("NA1_<gameId>"), so the ingest join is on game_id.

A game with no capture reads ``draft_source = 'none'`` and NOTHING is
fabricated: no rows, no opponent, no pick-order verdict.

The live half: ``lcu/champ_select_shape.shape_champ_select`` feeds every raw
session it fetches to the module recorder, and ``lcu/snapshot_shape`` passes
the gameflow gameId on. The recorder holds the snapshot in memory and writes
only through a sink that the LCU agent installs at startup
(``tools/lcu_agent.loop``), so the pure shapers and every test that calls them
never touch a real DB. Stdlib only, so the standalone agent can import it.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_log = logging.getLogger("rc.lcu.draft_log")

DRAFT_SOURCE_LCU = "lcu"
DRAFT_SOURCE_NONE = "none"

FINALIZE_TIMER_PHASES = frozenset({"FINALIZATION"})
# Gameflow phases in which a captured-but-unpersisted draft is still the
# draft of the game about to start. Any other phase (Lobby, None,
# Matchmaking...) means champ select ended without a game: a dodge.
_KEEP_PENDING_PHASES = frozenset({"ChampSelect", "GameStart", "InProgress"})

DRAFT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_log (
    game_id           INTEGER NOT NULL,
    action_index      INTEGER NOT NULL,
    turn              INTEGER DEFAULT 0,
    actor_cell_id     INTEGER DEFAULT -1,
    side              TEXT DEFAULT '',
    assigned_position TEXT DEFAULT '',
    action_type       TEXT DEFAULT '',
    champion_id       INTEGER DEFAULT 0,
    completed         INTEGER DEFAULT 0,
    final_champion_id INTEGER DEFAULT 0,
    is_local          INTEGER DEFAULT 0,
    queue_id          INTEGER DEFAULT 0,
    draft_source      TEXT DEFAULT 'lcu',
    captured_at       TEXT DEFAULT '',
    PRIMARY KEY (game_id, action_index)
);
CREATE INDEX IF NOT EXISTS idx_draft_log_game ON draft_log(game_id);
"""

_ROW_COLS = (
    "action_index", "turn", "actor_cell_id", "side", "assigned_position",
    "action_type", "champion_id", "completed", "final_champion_id", "is_local",
)


def _as_int(value, default):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


# -- pure parsing --------------------------------------------------------------

def is_finalized(sess) -> bool:
    """True when the session's timer says champ select has finalized."""
    return str(_as_dict(_as_dict(sess).get("timer")).get("phase") or "") \
        in FINALIZE_TIMER_PHASES


def session_game_id(sess) -> int:
    """The session's gameId, or 0 when absent / unusable."""
    gid = _as_int(_as_dict(sess).get("gameId"), 0)
    return gid if gid > 0 else 0


def session_queue_id(sess) -> int:
    q = _as_dict(_as_dict(_as_dict(sess).get("gameData")).get("queue"))
    return max(_as_int(q.get("id"), 0), 0)


def _cells(team) -> dict:
    """cellId -> team entry, for the dict entries with a usable cellId."""
    out = {}
    for entry in _as_list(team):
        if not isinstance(entry, dict):
            continue
        cell = _as_int(entry.get("cellId"), None)
        if cell is not None:
            out[cell] = entry
    return out


def parse_draft(sess) -> list[dict]:
    """Flatten ``sess.actions`` into ordered draft rows (see module doc).

    Pure: no I/O, never raises on a malformed session (returns what parses).
    """
    sess = _as_dict(sess)
    ally = _cells(sess.get("myTeam"))
    enemy = _cells(sess.get("theirTeam"))
    local_cell = _as_int(sess.get("localPlayerCellId"), -1)
    rows: list[dict] = []
    for turn, group in enumerate(_as_list(sess.get("actions"))):
        for action in _as_list(group):
            if not isinstance(action, dict):
                continue
            cell = _as_int(action.get("actorCellId"), -1)
            if cell in ally:
                side, entry = "ally", ally[cell]
            elif cell in enemy:
                side, entry = "enemy", enemy[cell]
            else:
                side, entry = "", {}
            rows.append({
                "action_index": len(rows),
                "turn": turn,
                "actor_cell_id": cell,
                "side": side,
                "assigned_position": str(entry.get("assignedPosition") or ""),
                "action_type": str(action.get("type") or ""),
                "champion_id": max(_as_int(action.get("championId"), 0), 0),
                "completed": 1 if action.get("completed") is True else 0,
                "final_champion_id": max(_as_int(entry.get("championId"), 0), 0),
                "is_local": 1 if cell >= 0 and cell == local_cell else 0,
            })
    return rows


def game_id_from_match_id(match_id) -> int | None:
    """Match-V5 'NA1_<gameId>' (or a bare numeric id) -> int gameId."""
    tail = str(match_id or "").rsplit("_", 1)[-1]
    if not tail.isdigit():
        return None
    gid = int(tail)
    return gid if gid > 0 else None


# -- storage -------------------------------------------------------------------

def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(DRAFT_LOG_SCHEMA)


def store_draft(conn: sqlite3.Connection, game_id, rows, *,
                queue_id: int = 0) -> int:
    """Replace the stored draft for ``game_id`` with ``rows``. Returns rows
    written (0 when refused: no usable game id or nothing to store). Commits.
    """
    gid = _as_int(game_id, 0)
    rows = [r for r in _as_list(rows) if isinstance(r, dict)]
    if gid <= 0 or not rows:
        return 0
    ensure_table(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute("DELETE FROM draft_log WHERE game_id = ?", (gid,))
        conn.executemany(
            "INSERT INTO draft_log (game_id, " + ", ".join(_ROW_COLS)
            + ", queue_id, draft_source, captured_at) VALUES ("
            + ", ".join("?" * (len(_ROW_COLS) + 4)) + ")",
            [(gid,) + tuple(r.get(c) for c in _ROW_COLS)
             + (_as_int(queue_id, 0), DRAFT_SOURCE_LCU, now) for r in rows])
    return len(rows)


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def load_draft(conn: sqlite3.Connection, game_id) -> list[dict]:
    """Stored rows for ``game_id`` in action order; [] when none. Read-only."""
    gid = _as_int(game_id, 0)
    if gid <= 0 or not _table_exists(conn, "draft_log"):
        return []
    cur = conn.execute(
        "SELECT " + ", ".join(_ROW_COLS)
        + " FROM draft_log WHERE game_id = ? ORDER BY action_index", (gid,))
    return [dict(zip(_ROW_COLS, r)) for r in cur.fetchall()]


def _match_roster(conn, match_id: str) -> list[tuple]:
    if not _table_exists(conn, "participants"):
        return []
    return conn.execute(
        "SELECT team_id, champion_id, team_position FROM participants "
        "WHERE match_id = ?", (match_id,)).fetchall()


def attach_draft_log(conn: sqlite3.Connection, match_id: str) -> dict:
    """Ingest join: attach the draft log to a Match-V5 match row on game_id.

    Returns ``{"match_id", "game_id", "draft_source", "actions",
    "lane_opponent", "local_picked_before_opponent"}``. With no capture,
    draft_source is 'none', actions is [] and both derived fields are None.

    Enemy positions are hidden in solo queue, so each enemy row gets a
    ``resolved_position`` from Match-V5 participants.team_position (matched by
    final champion on the enemy team), and the lane opponent is the enemy
    whose team_position equals the local player's.
    """
    gid = game_id_from_match_id(match_id)
    out = {"match_id": match_id, "game_id": gid,
           "draft_source": DRAFT_SOURCE_NONE, "actions": [],
           "lane_opponent": None, "local_picked_before_opponent": None}
    rows = load_draft(conn, gid) if gid else []
    if not rows:
        return out
    out["draft_source"] = DRAFT_SOURCE_LCU

    roster = _match_roster(conn, match_id)
    local_pick = next((r for r in rows if r["is_local"]
                       and r["action_type"] == "pick"), None)
    local_champ = local_pick["final_champion_id"] if local_pick else 0
    ally_team = next((t for t, c, _p in roster if c and c == local_champ), None)
    my_pos = next((p for t, c, p in roster
                   if t == ally_team and c == local_champ), "") or ""
    enemy_pos = {c: (p or "") for t, c, p in roster
                 if ally_team is not None and t != ally_team and c}

    for r in rows:
        r["resolved_position"] = (
            enemy_pos.get(r["final_champion_id"], "") if r["side"] == "enemy"
            else (r["assigned_position"] or "").upper())
    out["actions"] = rows

    if my_pos:
        opp_champ = next((c for c, p in enemy_pos.items() if p == my_pos), 0)
        opp_pick = next((r for r in rows if r["side"] == "enemy"
                         and r["action_type"] == "pick"
                         and r["final_champion_id"] == opp_champ), None)
        if opp_champ and opp_pick is not None:
            out["lane_opponent"] = {
                "champion_id": opp_champ, "team_position": my_pos,
                "actor_cell_id": opp_pick["actor_cell_id"],
                "action_index": opp_pick["action_index"],
            }
            out["local_picked_before_opponent"] = (
                local_pick["action_index"] < opp_pick["action_index"])
    return out


# -- live recorder ---------------------------------------------------------------

Sink = Callable[[int, list, int], object]


def sqlite_sink(db_path) -> Sink:
    """A sink that stores each finalized draft into ``db_path``."""
    path = Path(db_path)

    def _sink(game_id: int, rows: list, queue_id: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10)
        try:
            store_draft(conn, game_id, rows, queue_id=queue_id)
        finally:
            conn.close()
    return _sink


class DraftRecorder:
    """Holds the latest finalized draft and writes it once a game id is known.

    Without a sink it only keeps memory state, so it is safe to call from the
    pure shapers in any process. Never raises.
    """

    def __init__(self, sink: Sink | None = None) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self._rows: list[dict] | None = None
        self._queue_id = 0
        self._game_id = 0
        self._written_sig = None

    def set_sink(self, sink: Sink | None) -> None:
        with self._lock:
            self._sink = sink

    def observe_session(self, sess) -> None:
        try:
            if not isinstance(sess, dict) or not is_finalized(sess):
                return
            rows = parse_draft(sess)
            if not rows:
                return
            with self._lock:
                self._rows = rows
                self._queue_id = session_queue_id(sess)
                gid = session_game_id(sess)
                if gid:
                    self._game_id = gid
            self._flush()
        except Exception as exc:  # noqa: BLE001
            _log.warning("draft_log observe failed: %s", exc)

    def note_game_id(self, game_id) -> None:
        try:
            gid = _as_int(game_id, 0)
            if gid <= 0:
                return
            with self._lock:
                if self._rows is None or self._game_id:
                    return
                self._game_id = gid
            self._flush()
        except Exception as exc:  # noqa: BLE001
            _log.warning("draft_log note_game_id failed: %s", exc)

    def observe_phase(self, phase) -> None:
        """Drop an unpersisted draft once the client leaves champ select
        without starting a game (dodge), so it can never attach to a later,
        unrelated game id."""
        if phase in _KEEP_PENDING_PHASES:
            return
        with self._lock:
            self._rows = None
            self._game_id = 0
            self._queue_id = 0

    def _flush(self) -> None:
        with self._lock:
            sink = self._sink
            rows, gid, qid = self._rows, self._game_id, self._queue_id
            if sink is None or rows is None or not gid:
                return
            sig = (gid, tuple(tuple(r[c] for c in _ROW_COLS) for r in rows))
            if sig == self._written_sig:
                return
        try:
            sink(gid, rows, qid)
        except Exception as exc:  # noqa: BLE001
            _log.warning("draft_log sink failed for game %s: %s", gid, exc)
            return
        with self._lock:
            self._written_sig = sig


_RECORDER = DraftRecorder()


def observe_session(sess) -> None:
    _RECORDER.observe_session(sess)


def observe_phase(phase) -> None:
    _RECORDER.observe_phase(phase)


def note_game_id(game_id) -> None:
    _RECORDER.note_game_id(game_id)


def install_sink(sink: Sink | None) -> None:
    _RECORDER.set_sink(sink)
