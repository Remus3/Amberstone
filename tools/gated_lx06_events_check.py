"""gated_lx06_events_check.py - record and grade the /api/events stream for the LX-06 drain.

LX-06 (RM-604) asks whether a REAL game's death, level-up, completed-item and
objective events (with ``stolen``) REACH a live ``/api/events`` EventSource
client, and whether a reconnect resumes with Last-Event-ID across the real
600 s connection cap and across a dashboard restart (a ``gap``, then a re-read
of /api/state). Nothing in web/ subscribes to /api/events, so the drain needs
its own client; this tool is that client plus a grader.

Two subcommands:

  record  An EventSource-semantics SSE client (stdlib only). It connects to
          ``<base>/api/events`` with ``Accept: text/event-stream``, writes
          every frame to a NEW JSONL capture file the caller names, and on any
          close reconnects after the server's ``retry`` with ``Last-Event-ID``
          set to the last id it saw, exactly as a browser EventSource does. On
          a ``gap`` frame it re-reads /api/state once and logs the status. With
          ``--final-url`` it also polls the Live Client ``allgamedata`` every
          ``--final-every`` s and keeps the last non-empty body in
          ``<out>.final.json`` (atomic replace), the independent source the
          grader cross-checks. It only issues GETs. The capture and the final
          file hold whatever the game holds (riot ids in allPlayers): write
          them to a gitignored path, never a tracked one (RM-906).
  check   Pure and read-only: grades one capture (and optionally its final
          file) and prints. Champion names only, never a riot id.

WHAT check GRADES:
  - kinds seen (death / respawn / level_up / item_completed / objective_taken)
    and how many objective_taken carried ``stolen=true``;
  - id continuity over the whole capture: every event id is exactly
    cursor + 1, where the cursor is the hello head, the last event id or a gap
    end; a skip, a duplicate or a backwards id is a hole, and a ring-overflow
    gap is a LOST gap (the server said so, but the events never arrived);
    ``stream_ok`` also needs one connection that answered 200 with a frame;
  - resume: every reconnect sent Last-Event-ID = the cursor, and no reconnect
    got a ``hello`` (that means the server read it as a fresh client);
  - the 600 s cap: a connection that ended at EOF after >= CAP_MIN_S and whose
    successor resumed without a hole;
  - the restart: a reconnect whose first frame is a gap spanning more than
    RESTART_GAP_MIN ids (the hub seeds its ids from the wall clock in ms, so a
    new process reads as a huge gap; a ring overflow is at most RING_MAX), and
    a /api/state re-read answering 200 after it;
  - with the final file: every objective in ``events.Events`` inside the
    capture window has an objective_taken with the same ``event_id`` and the
    same ``stolen``; per-champion ChampionKill victims inside the window equal
    the death events; each champion's level_up chain is continuous and ends
    at its final level; and how VictimName was spelled (champion name or a
    player-name field; shared with LX-02 / RM-673).

It never ticks a row: its output is the INPUT to the four-part evidence
contract in docs/LIVE_GAME_GATED_SYNC.md. A capture of a replay server
(tools/replay_session.py) passes every check just as well; that is the
substitution the LX-06 row names, and why only a real game closes it.

USAGE
    python tools/gated_lx06_events_check.py record --out <gitignored dir>/lx06.jsonl \
        --final-url https://127.0.0.1:2999/liveclientdata/allgamedata --minutes 45
    python tools/gated_lx06_events_check.py check <dir>/lx06.jsonl [--final <file>] [--json]

Exit 2 = bad arguments, an existing --out, or an unreadable capture.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import http.client
import json
import math
import ssl
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live_event_deriver import EMITTED_KINDS, OBJECTIVE_EVENT_NAMES  # noqa: E402
from core.live_event_hub import RING_MAX  # noqa: E402

DEFAULT_BASE = "https://127.0.0.1:8888"
CAP_S = 600.0            # dashboard/routes_events.py _SSE_MAX_DURATION_S
CAP_MIN_S = 595.0        # our tolerance: a cap close lands a slice after 600 s of server time
RESTART_GAP_MIN = 10 * RING_MAX  # a gap this wide is a new id seed, not a ring overflow
EDGE_MARGIN_S = 5.0      # kills / deaths this close to the capture window's edges are not graded
POLL_LAG_S = 3.0         # our tolerance: an RC-derived event trails the Live Client by <= one relay poll plus jitter
READ_TIMEOUT_S = 45.0    # 3 server heartbeats (HEARTBEAT_S_DEFAULT 15 s) without a byte = dead
RETRY_DEFAULT_MS = 2000  # the server sends "retry: 2000"
_ID_KEYS = ("summonerName", "riotId", "riotIdGameName")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE  # loopback mkcert dashboard and the Riot :2999 cert, same as curl -k


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ---------------------------------------------------------------- SSE parsing

class SseParser:
    """Incremental text/event-stream parser (WHATWG rules, no ``event:`` use).

    ``feed(line)`` takes one line without its terminator and returns a list of
    ("frame", id_or_None, data_str) / ("comment", text) / ("retry", ms) items.
    The id rule follows the spec: ``id:`` sets the last-event-id BUFFER, which
    persists across frames; ``last_id`` (what a reconnect sends as
    Last-Event-ID) takes the buffer only when a frame is dispatched at its
    blank line, so a connection cut mid-frame never claims that frame. The
    frame's own id is the ``id:`` line of its block, None without one.
    """

    def __init__(self) -> None:
        self.last_id: Optional[str] = None
        self._buf: Optional[str] = None
        self._data: List[str] = []
        self._frame_id: Optional[str] = None

    def seed(self, last_id: Optional[str]) -> None:
        """Start a new connection from a known last id (no partial frame)."""
        self.last_id = self._buf = last_id
        self._data, self._frame_id = [], None

    def feed(self, line: str) -> List[tuple]:
        if line == "":
            self.last_id = self._buf
            if not self._data:
                self._frame_id = None
                return []
            out = [("frame", self._frame_id, "\n".join(self._data))]
            self._data, self._frame_id = [], None
            return out
        if line.startswith(":"):
            return [("comment", line[1:].strip())]
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "data":
            self._data.append(value)
        elif field == "id" and "\x00" not in value:
            self._buf = value
            self._frame_id = value
        elif field == "retry" and value.isascii() and value.isdigit():
            return [("retry", int(value))]
        return []


# ------------------------------------------------------------------- record

def _connect(url: str, headers: Dict[str, str], timeout: float):
    u = urlsplit(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    kw = {"timeout": timeout}
    if u.scheme == "https":
        kw["context"] = _SSL
    conn = cls(u.hostname, u.port, **kw)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    conn.request("GET", path, headers=headers)
    return conn, conn.getresponse()


def _get_json(url: str, timeout: float = 5.0) -> tuple:
    """(status, body or None). Never raises."""
    try:
        conn, resp = _connect(url, {"Accept": "application/json"}, timeout)
        try:
            raw = resp.read()
            status = resp.status
        finally:
            conn.close()
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return status, None
    except (OSError, http.client.HTTPException) as exc:
        return f"error:{type(exc).__name__}", None


def record(out: Path, base: str = DEFAULT_BASE, minutes: float = 45.0,
           final_url: Optional[str] = None, final_every: float = 20.0,
           drop_after: Optional[int] = None,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep,
           connect: Callable = _connect, get_json: Callable = _get_json) -> int:
    """Capture /api/events into ``out`` until ``minutes`` pass. Returns frames seen.

    The deadline is checked between lines, so an idle stream can overrun it
    by one server heartbeat (15 s).

    ``drop_after`` closes the FIRST connection after that many event frames, a
    client-side reconnect test that does not wait for the 600 s cap.
    """
    final_path = out.with_name(out.name + ".final.json")
    deadline = clock() + minutes * 60.0
    last_id: Optional[str] = None
    retry_ms = RETRY_DEFAULT_MS
    conn_no = 0
    frames = 0
    next_final = clock()

    with out.open("x", encoding="utf-8", newline="\n") as fh:
        def emit(obj: dict) -> None:
            fh.write(json.dumps(dict(obj, wall=_now_iso()), separators=(",", ":")) + "\n")
            fh.flush()

        def poll_final() -> None:
            nonlocal next_final
            if final_url is None or clock() < next_final:
                return
            next_final = clock() + final_every
            status, body = get_json(final_url)
            if status == 200 and isinstance(body, dict) and body.get("allPlayers"):
                # RM-258: per-writer scratch, fsync, bounded WinError 5 retry,
                # no scratch left on failure (the atomic-write guard's rule).
                from core import polled_json
                polled_json.atomic_write_text(final_path, json.dumps(body))

        emit({"t": "meta", "tool": "gated_lx06_events_check", "base": base,
              "final_url": final_url})
        while clock() < deadline:
            conn_no += 1
            headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
            if last_id is not None:
                headers["Last-Event-ID"] = last_id
            started = clock()
            parser = SseParser()
            parser.seed(last_id)
            reason = "eof"
            conn = None
            opened = False
            try:
                conn, resp = connect(base.rstrip("/") + "/api/events", headers, READ_TIMEOUT_S)
                emit({"t": "conn", "conn": conn_no, "last_event_id": last_id,
                      "status": resp.status, "ctype": resp.getheader("Content-Type"),
                      "replay": resp.getheader("X-RC-Replay")})
                opened = True
                if resp.status != 200:
                    reason = f"status:{resp.status}"
                else:
                    events_this_conn = 0
                    while True:
                        poll_final()
                        if clock() >= deadline:
                            reason = "deadline"
                            break
                        raw = resp.fp.readline()
                        if not raw:
                            break
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        for item in parser.feed(line):
                            if item[0] == "retry":
                                retry_ms = item[1]
                            elif item[0] == "comment":
                                emit({"t": "hb", "conn": conn_no})
                            else:
                                _, fid, data = item
                                try:
                                    obj = json.loads(data)
                                except ValueError:
                                    obj = {"kind": "unparsed"}
                                emit({"t": "frame", "conn": conn_no,
                                      "id": int(fid) if fid and fid.isascii() and fid.isdigit() else None,
                                      "data": obj})
                                frames += 1
                                if isinstance(obj, dict) and obj.get("kind") == "gap":
                                    status, st = get_json(base.rstrip("/") + "/api/state")
                                    emit({"t": "state", "conn": conn_no, "status": status,
                                          "mode_key": st.get("mode_key") if isinstance(st, dict) else None})
                                elif isinstance(obj, dict) and obj.get("kind") != "hello":
                                    events_this_conn += 1
                        last_id = parser.last_id
                        if (drop_after is not None and conn_no == 1
                                and events_this_conn >= drop_after):
                            reason = "drop"
                            break
            except (OSError, http.client.HTTPException) as exc:
                reason = f"error:{type(exc).__name__}"
                if not opened:
                    emit({"t": "conn", "conn": conn_no, "last_event_id": last_id,
                          "status": None})
            finally:
                last_id = parser.last_id
                if conn is not None:
                    try:
                        conn.close()
                    except OSError:
                        pass
            emit({"t": "end", "conn": conn_no, "reason": reason,
                  "dur_s": round(clock() - started, 3)})
            if reason == "deadline":
                break
            sleep(retry_ms / 1000.0)
            poll_final()
    return frames


# -------------------------------------------------------------------- check

def load_capture(path: Path) -> List[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"line {n}: not JSON") from exc
        if not isinstance(row, dict) or "t" not in row:
            raise ValueError(f"line {n}: not a capture row")
        rows.append(row)
    return rows


def _player_index(final: dict) -> Dict[str, tuple]:
    """name form -> (championName, form). Unique names only."""
    seen: Dict[str, List[tuple]] = {}
    for p in final.get("allPlayers") or []:
        if not isinstance(p, dict) or not isinstance(p.get("championName"), str):
            continue
        champ = p["championName"]
        seen.setdefault(champ, []).append((champ, "champion"))
        for k in _ID_KEYS:
            v = p.get(k)
            if isinstance(v, str) and v:
                seen.setdefault(v, []).append((champ, "player"))
    return {k: v[0] for k, v in seen.items() if len({c for c, _ in v}) == 1}


def check(rows: Iterable[dict], final: Optional[dict] = None) -> dict:
    rows = list(rows)
    conns: List[dict] = []
    cur: Optional[dict] = None
    cursor: Optional[int] = None
    kinds: Counter = Counter()
    holes: List[dict] = []
    bad_gaps: List[dict] = []
    events: List[dict] = []
    restart_conns: List[int] = []
    state_after_gap: List[Any] = []
    pending_gap_conn: Optional[int] = None
    bases: List[Any] = []
    replay_conns: List[Any] = []
    non_sse_conns: List[Any] = []
    lost_gaps: List[dict] = []

    for r in rows:
        t = r.get("t")
        if t == "meta":
            bases.append(r.get("base"))
        elif t == "conn":
            if r.get("replay"):
                replay_conns.append(r.get("conn"))
            if r.get("status") == 200 and "text/event-stream" not in str(r.get("ctype") or ""):
                non_sse_conns.append(r.get("conn"))
            cur = {"conn": r.get("conn"), "sent": r.get("last_event_id"),
                   "status": r.get("status"), "first": None, "hello": False,
                   "events": 0, "frames": 0, "end": None, "dur_s": None, "hole": False}
            sent = r.get("last_event_id")
            cur["sent_ok"] = (cursor is None and sent is None) or (
                cursor is not None and sent == str(cursor))
            # a RESUME is a connection that sent Last-Event-ID; a retry after a
            # first connect that never got a frame is still a fresh client
            cur["resumed"] = sent is not None
            conns.append(cur)
        elif t == "end" and cur is not None and r.get("conn") == cur["conn"]:
            cur["end"], cur["dur_s"] = r.get("reason"), _num(r.get("dur_s"))
        elif t == "state":
            if pending_gap_conn is not None:
                state_after_gap.append(r.get("status"))
        elif t == "frame" and cur is not None:
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            kind = d.get("kind")
            fid = _int(r.get("id"))
            cur["frames"] += 1
            if cur["first"] is None:
                cur["first"] = kind
            if kind == "hello":
                cur["hello"] = True
                cursor = _int(d.get("head")) if _int(d.get("head")) is not None else fid
            elif kind == "gap":
                a, b = _int(d.get("from")), _int(d.get("to"))
                if a is None or b is None:
                    bad_gaps.append({"conn": cur["conn"], "why": "non-int"})
                elif cursor is not None and a == cursor + 1 and b >= a:
                    first_of_reconnect = cur["frames"] == 1 and cur["resumed"]
                    if first_of_reconnect and b - a + 1 > RESTART_GAP_MIN:
                        restart_conns.append(cur["conn"])
                        pending_gap_conn = cur["conn"]
                    else:
                        # ids a..b fell off the ring: the server says so honestly,
                        # but those events never reached this client
                        lost_gaps.append({"conn": cur["conn"], "from": a, "to": b})
                    cursor = b
                elif cursor is not None and b < cursor and cur["frames"] == 1 and cur["resumed"]:
                    # the client is ahead of a NEW process's head (its clock seed
                    # ran behind): only a reconnect's first frame can say that
                    restart_conns.append(cur["conn"])
                    pending_gap_conn = cur["conn"]
                    cursor = b
                else:
                    bad_gaps.append({"conn": cur["conn"], "from": a, "to": b, "cursor": cursor})
                    cursor = b
            else:
                kinds[kind] += 1
                cur["events"] += 1
                if fid is None or _int(d.get("id")) != fid:
                    holes.append({"conn": cur["conn"], "why": "id mismatch", "id": fid})
                elif cursor is not None and fid != cursor + 1:
                    holes.append({"conn": cur["conn"], "why": "skip" if fid > cursor else "repeat",
                                  "expected": cursor + 1, "got": fid})
                    cur["hole"] = True
                if fid is not None:
                    cursor = fid if cursor is None else max(cursor, fid)
                events.append(d)

    reconnects = conns[1:]
    reconnect_hello = [c["conn"] for c in conns if c["resumed"] and c["hello"]]
    sent_bad = [c["conn"] for c in conns if not c["sent_ok"]]
    cap_ok = []
    for i, c in enumerate(conns[:-1]):
        nxt = conns[i + 1]
        if (c["end"] == "eof" and (c["dur_s"] or 0) >= CAP_MIN_S and nxt["status"] == 200
                and nxt["frames"] and nxt["resumed"] and not nxt["hello"]
                and not nxt["hole"] and nxt["sent_ok"]):
            cap_ok.append(c["conn"])
    stolen = sum(1 for e in events if e.get("kind") == "objective_taken" and e.get("stolen") is True)
    obj_ids = Counter(e.get("event_id") for e in events if e.get("kind") == "objective_taken")
    dup_objectives = sorted((k for k, n in obj_ids.items() if n > 1), key=str)

    out: Dict[str, Any] = {
        "bases": bases,
        "replay_conns": replay_conns,
        "non_sse_conns": non_sse_conns,
        "connections": len(conns),
        "reconnects": len(reconnects),
        "end_reasons": dict(Counter(str(c["end"]) for c in conns)),
        "kinds": dict(sorted(kinds.items())),
        "missing_kinds": sorted(k for k in ("death", "level_up", "item_completed", "objective_taken")
                                if not kinds.get(k)),
        "unknown_kinds": sorted(str(k) for k in kinds if k not in EMITTED_KINDS),
        "stolen_objectives": stolen,
        "duplicate_objective_ids": dup_objectives,
        "holes": holes,
        "bad_gaps": bad_gaps,
        "reconnect_hello": reconnect_hello,
        "last_event_id_mismatch": sent_bad,
        "cap_resumes": cap_ok,
        "lost_gaps": lost_gaps,
        "answered_conns": [c["conn"] for c in conns if c["status"] == 200 and c["frames"]],
        "restart_resumes": restart_conns,
        "state_reread_after_restart": state_after_gap,
    }
    out["stream_ok"] = (bool(out["answered_conns"]) and not holes and not bad_gaps
                        and not lost_gaps and not reconnect_hello and not dup_objectives
                        and not sent_bad and not replay_conns and not non_sse_conns)
    if final is not None:
        out["final"] = _cross_check(events, final)
    return out


def _cross_check(events: List[dict], final: dict) -> dict:
    gts = [g for g in (_num(e.get("game_time")) for e in events) if g is not None]
    if not gts:
        return {"window": None, "note": "no timed events captured"}
    ws, we = min(gts), max(gts)
    # the final file is the LAST poll, up to --final-every s before the end:
    # grade nothing it cannot have seen
    gd = final.get("gameData") if isinstance(final.get("gameData"), dict) else {}
    fgt = _num(gd.get("gameTime"))
    if fgt is not None:
        we = min(we, fgt)
    idx = _player_index(final)
    raw = (final.get("events") or {}).get("Events") if isinstance(final.get("events"), dict) else None
    evlist = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []

    taken = {e.get("event_id"): e for e in events if e.get("kind") == "objective_taken"}
    obj_missing, obj_stolen_diff, obj_seen = [], [], 0
    for e in evlist:
        if e.get("EventName") not in OBJECTIVE_EVENT_NAMES:
            continue
        at = _num(e.get("EventTime"))
        if at is None or at < ws or at > we:
            continue
        obj_seen += 1
        eid = _int(e.get("EventID"))
        got = taken.get(eid)
        if got is None:
            obj_missing.append({"event_id": eid, "objective": OBJECTIVE_EVENT_NAMES[e["EventName"]]})
        elif bool(got.get("stolen")) != (str(e.get("Stolen")).lower() == "true"):
            obj_stolen_diff.append(eid)
    # the other direction: an objective_taken the game never logged (one that
    # landed after the final poll cannot be judged and is skipped)
    known = {_int(e.get("EventID")) for e in evlist if e.get("EventName") in OBJECTIVE_EVENT_NAMES}
    obj_unexpected = sorted(
        (e.get("event_id") for e in events if e.get("kind") == "objective_taken"
         and e.get("event_id") not in known
         and (fgt is None or (_num(e.get("game_time")) or 0.0) < fgt - POLL_LAG_S)), key=str)

    kills: List[tuple] = []
    forms: Counter = Counter()
    for e in evlist:
        if e.get("EventName") != "ChampionKill":
            continue
        at = _num(e.get("EventTime"))
        if at is None:
            continue
        hit = idx.get(e.get("VictimName")) if isinstance(e.get("VictimName"), str) else None
        if hit is None:
            if ws + EDGE_MARGIN_S <= at <= we - EDGE_MARGIN_S:
                forms["unmapped"] += 1
            continue
        forms[hit[1]] += 1
        kills.append((hit[0], at))
    deaths = [(str(e.get("champion")), _num(e.get("game_time"))) for e in events
              if e.get("kind") == "death" and _num(e.get("game_time")) is not None]
    # pair each death with one kill of the same champion at most POLL_LAG_S
    # earlier (the deriver sees isDead on the next relay poll); only the
    # interior of the window is graded, so an edge pair cut in half never counts
    used = [False] * len(kills)
    unmatched_deaths: Counter = Counter()
    for champ, gt in sorted(deaths, key=lambda x: x[1]):
        hit = None
        for i, (kc, at) in enumerate(kills):
            if not used[i] and kc == champ and gt - POLL_LAG_S <= at <= gt + 0.5:
                hit = i
                break
        if hit is not None:
            used[hit] = True
        elif ws + EDGE_MARGIN_S <= gt <= we - EDGE_MARGIN_S:
            unmatched_deaths[champ] += 1
    unmatched_kills: Counter = Counter(
        kc for i, (kc, at) in enumerate(kills)
        if not used[i] and ws + EDGE_MARGIN_S <= at <= we - EDGE_MARGIN_S)
    death_diff = {c: {"unmatched_deaths": unmatched_deaths.get(c, 0),
                      "unmatched_kills": unmatched_kills.get(c, 0)}
                  for c in sorted(set(unmatched_deaths) | set(unmatched_kills))}

    finals = {p["championName"]: _int(p.get("level")) for p in final.get("allPlayers") or []
              if isinstance(p, dict) and isinstance(p.get("championName"), str)}
    chains: Dict[str, List[dict]] = {}
    for e in events:
        if e.get("kind") == "level_up":
            chains.setdefault(str(e.get("champion")), []).append(e)
    level_breaks, level_final_diff, level_final_skipped = [], {}, []
    for champ, evs in sorted(chains.items()):
        for a, b in zip(evs, evs[1:]):
            if a.get("to") != b.get("from"):
                level_breaks.append(champ)
                break
        if champ not in finals or finals[champ] is None:
            continue
        # the final file is the last poll, up to --final-every s old: compare it
        # with the chain as of that poll, and skip a champion with a level-up
        # within POLL_LAG_S of it (either side may hold that one)
        if fgt is not None:
            if any(abs((_num(e.get("game_time")) or 0.0) - fgt) <= POLL_LAG_S for e in evs):
                level_final_skipped.append(champ)
                continue
            upto = [e for e in evs if (_num(e.get("game_time")) or 0.0) < fgt]
            if not upto:
                continue
            last_to = upto[-1].get("to")
        else:
            last_to = evs[-1].get("to")
        if last_to != finals[champ]:
            level_final_diff[champ] = {"last_to": last_to, "final": finals[champ]}

    return {
        "window": [ws, we],
        "objectives_in_window": obj_seen,
        "objectives_missing": obj_missing,
        "objectives_stolen_mismatch": obj_stolen_diff,
        "objectives_unexpected": obj_unexpected,
        "victim_name_form": dict(forms),
        "death_mismatch": death_diff,
        "level_chain_breaks": level_breaks,
        "level_final_mismatch": level_final_diff,
        "level_final_skipped": level_final_skipped,
        "ok": not obj_missing and not obj_stolen_diff and not obj_unexpected and not death_diff
        and not level_breaks and not level_final_diff and not forms.get("unmapped"),
    }


def render(s: dict) -> str:
    lines = [
        f"connections {s['connections']} (reconnects {s['reconnects']}); ends {s['end_reasons']}",
        f"kinds {s['kinds']}; missing {s['missing_kinds'] or 'none'}; "
        f"unknown {s['unknown_kinds'] or 'none'}; stolen objectives {s['stolen_objectives']}; "
        f"repeated objective ids {s['duplicate_objective_ids'] or 'none'}",
        f"answered conns {len(s['answered_conns'])}; holes {len(s['holes'])}; "
        f"bad gaps {len(s['bad_gaps'])}; lost gaps {s['lost_gaps'] or 'none'}; hello on reconnect "
        f"{s['reconnect_hello'] or 'none'}; Last-Event-ID mismatch {s['last_event_id_mismatch'] or 'none'}",
        f"cap resumes {s['cap_resumes'] or 'none'}; restart resumes {s['restart_resumes'] or 'none'}; "
        f"/api/state re-read after restart {s['state_reread_after_restart'] or 'none'}",
        f"bases {s['bases']}; replay-marked conns {s['replay_conns'] or 'none'}; "
        f"non-SSE conns {s['non_sse_conns'] or 'none'}",
        f"stream_ok {s['stream_ok']}",
    ]
    f = s.get("final")
    if f is not None:
        lines.append(f"final: {json.dumps(f, sort_keys=True)}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="LX-06 /api/events capture and grader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="capture the SSE stream (GETs only)")
    rec.add_argument("--out", required=True, help="NEW capture file in a gitignored dir")
    rec.add_argument("--base", default=DEFAULT_BASE)
    rec.add_argument("--minutes", type=float, default=45.0)
    rec.add_argument("--final-url", default=None,
                     help="Live Client allgamedata URL to poll for the cross-check source")
    rec.add_argument("--final-every", type=float, default=20.0)
    rec.add_argument("--drop-after", type=int, default=None,
                     help="close the first connection after N events (reconnect test)")
    ck = sub.add_parser("check", help="grade one capture (read-only)")
    ck.add_argument("capture")
    ck.add_argument("--final", default=None, help="allgamedata JSON (default <capture>.final.json if present)")
    ck.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "record":
        out = Path(a.out)
        if out.exists():
            print(f"refusing: {out.name} exists (a capture is never overwritten)", file=sys.stderr)
            return 2
        if a.minutes <= 0 or a.final_every <= 0:
            print("minutes and --final-every must be positive", file=sys.stderr)
            return 2
        n = record(out, a.base, a.minutes, a.final_url, a.final_every, a.drop_after)
        print(f"frames {n} -> {out.name}")
        return 0

    path = Path(a.capture)
    try:
        rows = load_capture(path)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"unreadable capture: {exc}", file=sys.stderr)
        return 2
    final = None
    fpath = Path(a.final) if a.final else path.with_name(path.name + ".final.json")
    if a.final or fpath.exists():
        try:
            final = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            print(f"unreadable final: {exc}", file=sys.stderr)
            return 2
        if not isinstance(final, dict):
            print("unreadable final: not an object", file=sys.stderr)
            return 2
    s = check(rows, final)
    print(json.dumps(s, sort_keys=True) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
