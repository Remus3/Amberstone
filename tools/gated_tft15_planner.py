"""gated_tft15_planner.py - TFT-15 read-back: planner code format and planner propagation.

TFT-15 (``docs/TFT_PROGRAM.md`` section 7; section 6 path A / path B) asks two
things a live TFT session must answer before TFT-14 can pick a path:

  1. The team-code FORMAT, so path A can copy a code without an LCU write.
     Measured so far: the legacy Set 17 probe (``scripts/discover_champion_codes.py``
     ``legacy_probe``) read ``code[2:5]`` of a one-unit team's code as that
     unit's ``team_planner_code`` in hex, "000" meaning empty; the 63 Set 17
     codes it produced agree with the client's game data (LT-03 / LT-04). The
     rest of the grammar is a CANDIDATE, ``H1``: a 2-character prefix, then
     3-hex-digit slots, then an optional ``TFTSet<N>`` tail. ``decode`` tests
     H1 against ONE code the client itself produced (the operator's own Copy
     button in the client planner - an in-client act, no RC write) for a team
     whose units the operator names with ``--expect``.
  2. Whether a planner change PROPAGATES between the client (LCU) planner and
     the in-game planner during a match. ``snapshot`` reads the LCU planner
     with GETs only (``/v1/previous-context``, ``/v1/sets/dirty``) and scans
     ``TFT.log`` for the allowlisted ``TFTPlannerSubsystem`` lines (data
     received / saved, set loaded); ``diff`` compares two snapshots taken
     around the change.

The write that the LCU-to-game case needs (path B's route) is NOT made here:
it belongs to an operator-present session under TFT-14's explicit-click rule.
The game-to-LCU case needs no RC write at all (the operator edits a team in
the in-game planner; the client's own sync is what is measured).

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md TFT-15 before any game):
  decode  PASS iff H1 parses the code, every filled slot maps to a unit in the
          set's codes file, re-encoding gives the code back, and the decoded
          units equal ``--expect`` (as a multiset; ``order`` is reported, not
          judged). FAIL iff H1 does not parse it, a slot is unknown, the
          round trip differs, or the units differ. No ``--expect`` = INCOMPLETE.
  diff    INCOMPLETE unless both snapshots read a recognised planner shape
          holding at least one team, both were taken ``InProgress``, and (for
          game-to-lcu) ``--edit-at`` is given. Then PROPAGATED_LOG iff the LCU
          planner changed between the snapshots and a signal line for
          ``--direction`` is stamped after the BEFORE snapshot and the edit
          time (lcu-to-game: ``data_received``; game-to-lcu: ``data_saved``);
          NO_LOG_SIGNAL iff it changed and none is; NO_CHANGE iff the LCU
          planner did not change. The log line is never
          the render half: the in-game planner showing the team is the
          operator's observation and is recorded beside this verdict.

READ-ONLY: the only LCU call is ``_lcu_get`` (method "GET", pinned by
``tests/test_gated_tft15_planner.py``); it writes, moves, locks or deletes
nothing and never ticks a row. Its output prints NO team title, NO team id and
NO TFT.log line text: counts, unit ids, digests and UTC stamps only.

USAGE
    python tools/gated_tft15_planner.py decode <code> --expect "Ahri,Akali" [--set TFTSet18] [--json]
    python tools/gated_tft15_planner.py snapshot [--since 2026-10-27T18:00] --json > before.json
    python tools/gated_tft15_planner.py diff before.json after.json --direction game-to-lcu --edit-at 2026-10-27T18:20:30 [--json]
Exit 0 = PASS / PROPAGATED_LOG, 1 = INCOMPLETE / NO_CHANGE / NO_LCU, 2 = FAIL / NO_LOG_SIGNAL.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

META_DIR = _ROOT / "data" / "meta"
CONTEXT_EP = "/lol-tft-team-planner/v1/previous-context"
DIRTY_EP = "/lol-tft-team-planner/v1/sets/dirty"
PHASE_EP = "/lol-gameflow/v1/gameflow-phase"
EMPTY_SLOT = "000"

_SET_TAIL = re.compile(r"(TFTSet\d{1,3})$")
_HEX3 = re.compile(r"^[0-9A-Fa-f]{3}$")
_STAMP = re.compile(r"^\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):(\d{3})\]\[ *\d{1,6}\]")
_PLANNER = "TFT: [Client] TFTPlannerSubsystem_"
# Allowlist: (kind, pattern after the subsystem id). Only these kinds are kept,
# and only their kind and stamp (plus the set name) leave this module.
_LOG_KINDS = (
    ("data_received", re.compile(r"^\d{1,12}: Player TeamPlanner Data received$")),
    ("data_saved", re.compile(r"^\d{1,12}: Player TeamPlanner data saved\.$")),
    ("prefs_saved", re.compile(r"^\d{1,12}: Saved TeamPlanner PlayerPreferences\.$")),
    ("set_loaded", re.compile(r"^\d{1,12}: Set dat loaded for DefaultSet: (TFTSet\d{1,3}), EventSet: .{0,40}$")),
)
# Which log line is the sync signal depends on the direction. Baseline over the
# seven 2026-10-25 TFT.log files: exactly one ``data_received`` per file (the
# match-start load), and 0 to 7 ``data_saved`` lines per match with no RC
# planner write, so a save is the GAME writing out, never the LCU writing in.
SIGNAL_KINDS = {"lcu-to-game": frozenset({"data_received"}),
                "game-to-lcu": frozenset({"data_saved"})}


# -- decode (offline) ----------------------------------------------------------

def load_codes(set_id: str, meta_dir: Path | None = None) -> dict[str, int]:
    """The tracked ``tft_set<N>_champion_codes.json`` (name -> planner code)."""
    m = re.fullmatch(r"TFTSet(\d{1,3})", set_id)
    if not m:
        raise ValueError(f"not a planner set id: {set_id!r}")
    path = (meta_dir or META_DIR) / f"tft_set{int(m.group(1))}_champion_codes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data.items()}


def parse_h1(code: str) -> dict[str, Any]:
    """Split ``code`` by candidate grammar H1; ``ok`` False names the reason."""
    code = code.strip().strip('"')
    tail_m = _SET_TAIL.search(code)
    tail = tail_m.group(1) if tail_m else ""
    body = code[:len(code) - len(tail)] if tail else code
    out: dict[str, Any] = {"ok": False, "prefix": body[:2], "slots": [], "tail": tail,
                           "length": len(code)}
    if len(body) < 5:
        out["reason"] = "shorter than prefix plus one slot"
        return out
    rest = body[2:]
    if len(rest) % 3:
        out["reason"] = f"slot body length {len(rest)} is not a multiple of 3"
        return out
    slots = [rest[i:i + 3] for i in range(0, len(rest), 3)]
    if not all(_HEX3.match(s) for s in slots):
        out["reason"] = "a slot is not 3 hex digits"
        return out
    out.update(ok=True, slots=slots)
    return out


def encode_h1(prefix: str, codes: list[int], width: int, tail: str, upper: bool = False) -> str:
    """Inverse of ``parse_h1``: ``width`` slots, empty ones "000"."""
    slots = [f"{c:03x}" for c in codes] + [EMPTY_SLOT] * (width - len(codes))
    body = "".join(slots)
    return prefix + (body.upper() if upper else body) + tail


def decode(code: str, set_id: str | None, expect: list[str] | None,
           meta_dir: Path | None = None) -> dict[str, Any]:
    parsed = parse_h1(code)
    res: dict[str, Any] = {"tool": "gated_tft15_planner", "mode": "decode", "grammar": "H1",
                           "h1": parsed, "read_at": _now_iso()}
    if not parsed["ok"]:
        return _verdict(res, "FAIL", f"H1 refuted: {parsed['reason']}")
    sid = set_id or parsed["tail"]
    if not sid:
        return _verdict(res, "INCOMPLETE", "no TFTSet tail in the code; pass --set")
    try:
        names_by_code = {v: k for k, v in load_codes(sid, meta_dir).items()}
    except (OSError, ValueError) as exc:
        return _verdict(res, "INCOMPLETE", f"no codes file for {sid}: {type(exc).__name__}")
    filled = [s for s in parsed["slots"] if s != EMPTY_SLOT]
    vals = [int(s, 16) for s in filled]
    units = [names_by_code.get(v) for v in vals]
    gap = any(s == EMPTY_SLOT for s in parsed["slots"][:len(filled)])
    body = "".join(parsed["slots"])
    again = encode_h1(parsed["prefix"], vals, len(parsed["slots"]), parsed["tail"],
                      upper=body != body.lower())
    res.update(set=sid, slot_count=len(parsed["slots"]), filled=len(filled),
               empty_between=gap, units=units,
               unknown_codes=[v for v, u in zip(vals, units) if u is None],
               round_trip=again == code.strip().strip('"'))
    if res["unknown_codes"]:
        return _verdict(res, "FAIL", "a filled slot maps to no unit of the set")
    if not res["round_trip"]:
        # The candidate encoder writes filled slots first, so a code with an
        # empty slot between units (``empty_between``) fails here too.
        return _verdict(res, "FAIL", "re-encoding under H1 does not give the code back")
    if not expect:
        return _verdict(res, "INCOMPLETE", "no --expect unit list to compare")
    res["expect"] = expect
    res["order_matches"] = units == expect
    if Counter(units) != Counter(expect):
        return _verdict(res, "FAIL", "decoded units differ from --expect")
    return _verdict(res, "PASS", "H1 holds for this code")


# -- snapshot (LCU GETs + TFT.log) ---------------------------------------------

def _lcu_get_factory() -> Callable[[str], Any]:
    """RC's own LCU client, GET only. With no client, ``connect`` leaves it
    unconnected and every GET returns None, which ``snapshot`` reports as NO_LCU."""
    from lcu.lcu_client import LcuClient  # noqa: PLC0415 - lazy: offline modes need none
    client = LcuClient()
    client.connect()

    def _lcu_get(endpoint: str) -> Any:
        return client._request("GET", endpoint)
    return _lcu_get


def _team_rows(dirty: Any) -> tuple[dict[str, list[dict]], str]:
    """Normalise ``/v1/sets/dirty`` to {set: [team dict]}; the shape is unmeasured."""
    if isinstance(dirty, dict):
        out: dict[str, list[dict]] = {}
        for sid, raw_val in dirty.items():
            val = raw_val
            if isinstance(raw_val, dict) and isinstance(raw_val.get("teams"), list):
                val = raw_val["teams"]
            if isinstance(val, list):
                out[str(sid)] = [t for t in val if isinstance(t, dict)]
        return out, "by_set" if out else "unrecognised"
    if isinstance(dirty, list):
        return {"?": [t for t in dirty if isinstance(t, dict)]}, "flat_list"
    return {}, "unrecognised"


def _unit_ids(team: dict) -> list[str]:
    ids = []
    champions = team.get("champions")
    for c in champions if isinstance(champions, list) else []:
        cid = c.get("championId") if isinstance(c, dict) else c
        if isinstance(cid, (str, int)) and str(cid):
            ids.append(str(cid))
    return ids


def _team_key(team: dict, canon: str) -> str:
    """A hash of the team id; with no id, of the whole team (an edit then reads
    as removed plus added, never as a change to a neighbour's key)."""
    raw = team.get("id")
    raw = f"id:{raw}" if raw not in (None, "") else f"noid:{canon}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def summarise_planner(context: Any, dirty: Any) -> dict[str, Any]:
    """Counts, unit ids and digests only - never a title or a raw team id."""
    rows, shape = _team_rows(dirty)
    sets = {}
    for sid, teams in rows.items():
        summary = {}
        for team in teams:
            units = _unit_ids(team)
            canon = json.dumps(team, sort_keys=True, separators=(",", ":"), default=str)
            summary[_team_key(team, canon)] = {
                "units": units, "unit_count": len(units),
                "digest": hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]}
        sets[sid] = {"team_count": len(teams), "teams": summary}
    ctx = context if isinstance(context, dict) else {}
    return {"context_set": ctx.get("setId"),
            "context_has_team": bool(ctx.get("optionalTeamId")),
            "dirty_shape": shape, "dirty_type": type(dirty).__name__, "sets": sets}


def _stamp_epoch(m: re.Match) -> float:
    y, mo, d, h, mi, s, ms = (int(x) for x in m.groups())
    return calendar.timegm((y, mo, d, h, mi, s)) + ms / 1000.0


def scan_log_lines(lines, since: float | None = None) -> list[dict[str, Any]]:
    """Allowlisted planner events from TFT.log lines: kind, UTC stamp, set."""
    events = []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        m = _STAMP.match(line)
        if not m:
            continue
        rest = line[m.end():]
        if not rest.startswith(_PLANNER):
            continue
        tail = rest[len(_PLANNER):]
        for kind, rx in _LOG_KINDS:
            km = rx.match(tail)
            if km:
                ts = _stamp_epoch(m)
                if since is None or ts >= since:
                    ev = {"kind": kind, "ts": ts, "iso": _iso(ts)}
                    if kind == "set_loaded":
                        ev["set"] = km.group(1)
                    events.append(ev)
                break
    return events


def scan_log(path: Path | None, since: float | None) -> dict[str, Any]:
    if path is None:
        from tft.sources.tft_log import tft_log_path  # noqa: PLC0415
        path = tft_log_path()
    try:
        from tft.sources.tft_log import _open_shared  # noqa: PLC0415 - FILE_SHARE_DELETE open
        with _open_shared(path) as fh:
            events = scan_log_lines(fh, since)
    except OSError as exc:
        return {"readable": False, "error": type(exc).__name__, "events": [], "counts": {}}
    return {"readable": True, "events": events,
            "counts": dict(Counter(e["kind"] for e in events))}


def snapshot(get: Callable[[str], Any] | None, log_path: Path | None,
             since: float | None) -> dict[str, Any]:
    res: dict[str, Any] = {"tool": "gated_tft15_planner", "mode": "snapshot",
                           "read_at": _now_iso(), "read_ts": time.time()}
    if get is None:
        try:
            get = _lcu_get_factory()
        except Exception as exc:  # noqa: BLE001 - any client failure is NO_LCU
            get = None
            res["lcu_error"] = type(exc).__name__
    context = dirty = phase = None
    if get is not None:
        context, dirty, phase = get(CONTEXT_EP), get(DIRTY_EP), get(PHASE_EP)
    res["gameflow_phase"] = phase if isinstance(phase, str) else None
    res["lcu"] = dirty is not None
    res["planner"] = summarise_planner(context, dirty) if dirty is not None else None
    res["log"] = scan_log(log_path, since)
    if not res["lcu"]:
        return _verdict(res, "NO_LCU", "no planner read (client closed or GET refused)")
    return _verdict(res, "SNAPSHOT", "planner read")


# -- diff (offline) ------------------------------------------------------------

def _readable(planner: dict | None) -> bool:
    """A recognised ``/v1/sets/dirty`` shape with at least one team: anything
    less cannot tell "unchanged" from "unparsed"."""
    return bool(planner) and planner.get("dirty_shape") != "unrecognised" and sum(
        s.get("team_count", 0) for s in planner.get("sets", {}).values()) > 0


def diff(before: dict, after: dict, direction: str,
         edit_at: float | None = None) -> dict[str, Any]:
    """``edit_at``: the operator's noted edit / write time (epoch); the signal
    line must follow it. game-to-lcu needs it (saves happen with no edit)."""
    signal = SIGNAL_KINDS[direction]
    res: dict[str, Any] = {"tool": "gated_tft15_planner", "mode": "diff", "read_at": _now_iso(),
                           "direction": direction, "edit_at": _iso(edit_at) if edit_at else None,
                           "before_at": before.get("read_at"), "after_at": after.get("read_at"),
                           "phase_before": before.get("gameflow_phase"),
                           "phase_after": after.get("gameflow_phase")}
    pb, pa = before.get("planner"), after.get("planner")
    if not _readable(pb) or not _readable(pa):
        return _verdict(res, "INCOMPLETE",
                        "a snapshot has no planner read, an unrecognised shape or no team")
    if res["phase_before"] != "InProgress" or res["phase_after"] != "InProgress":
        return _verdict(res, "INCOMPLETE", "both snapshots must be taken mid-match (InProgress)")
    if direction == "game-to-lcu" and edit_at is None:
        return _verdict(res, "INCOMPLETE", "game-to-lcu needs --edit-at (saves occur unedited)")
    changes = []
    for sid in sorted(set(pb["sets"]) | set(pa["sets"])):
        tb = pb["sets"].get(sid, {}).get("teams", {})
        ta = pa["sets"].get(sid, {}).get("teams", {})
        for key in sorted(set(tb) | set(ta)):
            b, a = tb.get(key), ta.get(key)
            if b is None or a is None or b["digest"] != a["digest"]:
                changes.append({"set": sid, "team": key,
                                "change": "added" if b is None else "removed" if a is None
                                else "edited",
                                "units_before": (b or {}).get("units"),
                                "units_after": (a or {}).get("units")})
    t0 = before.get("read_ts")
    seen = {(e["kind"], e["ts"]) for e in before.get("log", {}).get("events", [])}
    new = [e for e in after.get("log", {}).get("events", [])
           if (e["kind"], e["ts"]) not in seen and (t0 is None or e["ts"] >= t0)]
    res.update(changes=changes, new_log_events=new)
    if not changes:
        return _verdict(res, "NO_CHANGE", "the LCU planner did not change")
    if any(e["kind"] in signal and (edit_at is None or e["ts"] >= edit_at) for e in new):
        return _verdict(res, "PROPAGATED_LOG",
                        f"planner changed and TFT.log logged {sorted(signal)} after BEFORE"
                        " and the edit time")
    return _verdict(res, "NO_LOG_SIGNAL",
                    f"planner changed; no {sorted(signal)} line after BEFORE and the edit time")


# -- shared ----------------------------------------------------------------------

_EXIT = {"PASS": 0, "PROPAGATED_LOG": 0, "SNAPSHOT": 0, "INCOMPLETE": 1, "NO_CHANGE": 1,
         "NO_LCU": 1, "FAIL": 2, "NO_LOG_SIGNAL": 2}


def _verdict(res: dict, verdict: str, why: str) -> dict:
    res["verdict"], res["why"] = verdict, why
    return res


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _since(text: str | None) -> float | None:
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.timestamp()


def _print(res: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(res, indent=2, sort_keys=True))
        return
    print(f"{res['mode']}: {res['verdict']} - {res['why']}")
    for key in ("set", "slot_count", "filled", "units", "unknown_codes", "round_trip",
                "order_matches", "gameflow_phase", "changes", "new_log_events"):
        if key in res:
            print(f"  {key}: {res[key]}")
    if res.get("mode") == "snapshot":
        p = res.get("planner") or {}
        print(f"  dirty_shape: {p.get('dirty_shape')}  sets: "
              f"{ {k: v['team_count'] for k, v in (p.get('sets') or {}).items()} }")
        print(f"  log: {res['log'].get('counts')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help="test candidate grammar H1 on one client code")
    d.add_argument("code")
    d.add_argument("--set", dest="set_id", help="planner set id, e.g. TFTSet18")
    d.add_argument("--expect", help="comma list of the team's unit display names")
    s = sub.add_parser("snapshot", help="LCU planner (GET) plus TFT.log planner lines")
    s.add_argument("--since", help="local ISO time; older log lines are dropped")
    s.add_argument("--log", type=Path, help="TFT.log path (default: the client's)")
    f = sub.add_parser("diff", help="compare two snapshot JSON files")
    f.add_argument("before", type=Path)
    f.add_argument("after", type=Path)
    f.add_argument("--direction", required=True, choices=sorted(SIGNAL_KINDS),
                   help="lcu-to-game: a client planner write; game-to-lcu: an in-game edit")
    f.add_argument("--edit-at", help="local ISO time of the edit / write (game-to-lcu: required)")
    for p in (d, s, f):
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        since = _since(getattr(a, "since", None) or getattr(a, "edit_at", None))
    except ValueError:
        ap.error("--since / --edit-at must be an ISO time, e.g. 2026-10-27T18:00")
    if a.cmd == "decode":
        expect = [x.strip() for x in a.expect.split(",") if x.strip()] if a.expect else None
        res = decode(a.code, a.set_id, expect)
    elif a.cmd == "snapshot":
        res = snapshot(None, a.log, since)
    else:
        res = diff(json.loads(a.before.read_text(encoding="utf-8")),
                   json.loads(a.after.read_text(encoding="utf-8")), a.direction, since)
    _print(res, a.json)
    return _EXIT[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
