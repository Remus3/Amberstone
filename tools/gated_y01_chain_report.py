"""gated_y01_chain_report.py - Y-01 (G4-30) read-back: did each game end's rewind chain pin ITS OWN game?

G4-30 (RM-526 / Y-01 Step 0) asks, over the next 5 real League game ends, what
the target-pinned rewind live writer (``lib/rewind_live_writer.py``) did: target
id, final status, attempts, and whether any game reported the PREVIOUS game's
id. Answering it by hand means walking three logs and two runtime files per
game. This tool joins them in ONE command:

  - game ends: ``rc.app.lifecycle`` "Game ended" lines in ``logs/*.log*``
    (``app/_game_lifecycle.py``); a TFT end is marked by the "TFT game end:
    League rewind live-writer skipped" line and never counts.
  - the game's OWN id: the post-game collector's "postgame: saved match <id>"
    / "postgame: match <id> already stored - skip" line (``lcu/
    lcu_postgame_collector.py`` ``_save_eog``), the EOG ``gameId`` - the same
    value the collector pins, and NOT the writer's Match-V5 id list, which is
    where the Y-01 defect lived (``ids[0]`` = the previous game).
  - the chain end: "rewind_live_writer: chain <chain> attempt <n> ended
    <status> (<target>)"; the chain id embeds ``scheduled_at`` (epoch), which
    joins it to the game end that scheduled it.
  - the Y-08 receipt (``ops/runtime/rewind_ingest_receipts.jsonl``): attempts,
    elapsed_s, pinned, fallback, parked - joined on scheduled_at = ts -
    elapsed_s.
  - the pin (``ops/runtime/last_game_end.json``): the LATEST game only; it
    answers "does the LCU EOG block carry queueId" for that game. The Riot ID
    it carries is NEVER read into the output.
  - the downstream artifact: an ``ok`` target must be a row in
    ``data/rewind_history.db`` ``matches`` (opened ``mode=ro``, only when an
    ingested target exists; ``--no-db`` skips it).

PREDICATE (stated in docs/LIVE_GAME_GATED_SYNC.md G4-30 before any game):
  PASS iff at least ``--need`` (5) League game ends since ``--since`` and every
  one of them has a chain-end line with a joined receipt, pinned and not
  fallback, its target == ``<PLATFORM>_<its own EOG gameId>``, and it ends
  either ``ok`` with a DB row or ``event_mode_excluded``; at least one of each
  kind; and no target repeats an earlier game's. FAIL on any violated game
  (a wrong target fails whatever the status).
  Anything short of a verdict (too few games, a chain still inside its
  ~21 min window, no own-id line, no receipt, DB unreadable, ``already_present``
  / ``short_game``) is INCOMPLETE - never PASS.

IDS: real match ids are redacted by default to ``id:<8 hex of sha256>`` (stable,
so a repeat is still visible) - the output is pasteable into a tracked doc under
RM-906. ``--show-ids`` prints them raw for the operator's console only.

READ-ONLY: files are opened for reading; the DB with ``mode=ro``. It never
writes, moves, locks or deletes anything, and it never ticks a row - its output
is the INPUT to the four-part evidence contract, never the evidence by itself.

USAGE (from a worktree it reads the MAIN checkout's logs / ops/runtime / data)
    python tools/gated_y01_chain_report.py --since 2026-10-27T18:00
    python tools/gated_y01_chain_report.py --since <iso> --json
Exit 0 = PASS, 1 = INCOMPLETE, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import ingest_receipt  # noqa: E402
from lib import rewind_live_writer as rlw  # noqa: E402
from tools.gated_frame_readback import main_checkout  # noqa: E402

NEED_GAMES = 5
# A chain's last attempt runs DEFAULT_DELAY_S + sum(STAGED_DELAYS_S) after the
# game end (1170 s today); past that plus slack, no chain end is a FAIL.
CHAIN_WINDOW_S = rlw.DEFAULT_DELAY_S + sum(rlw.STAGED_DELAYS_S) + 120.0
# schedule_live_insert runs right after the "Game ended" line, same call.
SCHEDULE_SLACK_S = (-2.0, 30.0)
RECEIPT_JOIN_S = 0.05
# A never-scheduled line is written synchronously right after "Game ended".
# Kept tight: a RUNNING chain's retry staging can also log the cap line, and
# that must not read as the next game's refusal.
SCHED_FAIL_SLACK_S = (0.0, 5.0)

_LINE = re.compile(
    r"^(\d\d):(\d\d):(\d\d)(?:\.(\d{3}))?\s+([A-Z]+)\s+(\S+)\s+(?:\[[^\]]*\]\s)?(.*)$")
_FILE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.log(?:\.(\d+))?$")
_CHAIN = re.compile(
    r"^rewind_live_writer: chain (\S+) attempt (\d+) ended (\S+) \((.*)\)$")
_CHAIN_AT = re.compile(r"^chain-(\d+(?:\.\d+)?)-")
_EOG_SAVED = re.compile(r"^postgame: saved match (\S+)\s+mode=(\S+)")
_EOG_STORED = re.compile(r"^postgame: match (\S+) already stored - skip$")
_TRIGGERED = re.compile(r"^PostgameCollector: triggered for mode=(\S+)$")
_RC_START = re.compile(r"^PostgameCollector started \((?:async|thread)\)$")
# The chain was never scheduled: the Timer cap refused it, schedule_live_insert
# swallowed an error (debug), or the lifecycle trigger itself raised.
_SCHED_FAIL = re.compile(
    r"^(?:rewind_live_writer: \d+ staged Timers pending \(cap\); not staging another"
    r"|rewind_live_writer schedule error: .*"
    r"|rewind live-writer trigger error: .*)$")
GAME_ENDED = "Game ended"
TFT_SKIP = "TFT game end: League rewind live-writer skipped"
INGESTED_OK = "ok"
EVENT_EXCLUDED = "event_mode_excluded"


def _events(logs_dir: Path, since: float | None) -> list[dict[str, Any]]:
    """Every line this report needs, oldest first. Never raises."""
    out: list[tuple[float, int, int, dict[str, Any]]] = []
    try:
        files = sorted(p for p in logs_dir.iterdir() if _FILE.match(p.name))
    except OSError:
        return []
    for rank, path in enumerate(files):
        y, mo, d, _n = _FILE.match(path.name).groups()
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for lineno, raw in enumerate(fh):
                m = _LINE.match(raw.rstrip("\r\n"))
                if not m:
                    continue
                hh, mm, ss, ms, _lvl, logger, msg = m.groups()
                ev = _classify(logger, msg)
                if ev is None:
                    continue
                try:
                    ts = time.mktime((int(y), int(mo), int(d), int(hh), int(mm),
                                      int(ss), 0, 0, -1)) + int(ms or 0) / 1000.0
                except (OverflowError, ValueError):
                    continue
                if since is not None and ts < since:
                    continue
                ev["ts"] = ts
                out.append((ts, rank, lineno, ev))
    out.sort(key=lambda t: t[:3])
    return [t[3] for t in out]


def _classify(logger: str, msg: str) -> dict[str, Any] | None:
    if msg == GAME_ENDED and logger == "rc.app.lifecycle":
        return {"kind": "game_end"}
    if msg == TFT_SKIP:
        return {"kind": "tft_skip"}
    if logger == "rc.postgame":
        m = _TRIGGERED.match(msg)
        if m:
            # Before S134 N3 a TFT end logged no TFT_SKIP line; the collector's
            # trigger hint is then the only TFT marker.
            return {"kind": "tft_skip"} if m.group(1).upper() == "TFT" else None
        if _RC_START.match(msg):
            return {"kind": "rc_start"}
    m = _CHAIN.match(msg)
    if m:
        chain, attempt, status, target = m.groups()
        at = _CHAIN_AT.match(chain)
        return {"kind": "chain_end", "chain": chain, "attempt": int(attempt),
                "status": status,
                "target": None if target == "no target" else target,
                "scheduled_at": float(at.group(1)) if at else None}
    if _SCHED_FAIL.match(msg):
        return {"kind": "sched_fail"}
    if logger == "rc.postgame":
        m = _EOG_SAVED.match(msg)
        if m:
            return {"kind": "eog_id", "game_id": m.group(1)}
        m = _EOG_STORED.match(msg)
        if m:
            # The id was saved BEFORE this game ended, so it cannot vouch for
            # this game's own id (a stale EOG reads exactly like this).
            return {"kind": "eog_stored", "game_id": m.group(1)}
    return None


def _redact(match_id: str | None, show: bool) -> str | None:
    if match_id is None or show:
        return match_id
    return "id:" + hashlib.sha256(match_id.encode("utf-8")).hexdigest()[:8]


def _read_pin(path: Path) -> dict[str, Any]:
    """The pin's non-identifying fields only (never game_name / tag_line)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"present": False}
    if not isinstance(data, dict):
        return {"present": False}
    qid = data.get("queue_id")
    written = data.get("written_at")
    return {
        "present": True,
        "game_id": str(data.get("game_id") or "") or None,
        "queue_id": qid if isinstance(qid, int) and not isinstance(qid, bool) else None,
        "queue_id_present": isinstance(qid, int) and not isinstance(qid, bool),
        "game_mode": str(data.get("game_mode") or "")[:16],
        "written_at": written if isinstance(written, (int, float)) else None,
    }


def _db_has(db: Path, match_id: str) -> bool | None:
    """True / False for a row in ``matches``; None when unreadable. Read-only."""
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT 1 FROM matches WHERE match_id = ? LIMIT 1",
                           (match_id,)).fetchone()
        return row is not None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def build_report(*, logs_dir: Path, receipts: Path, pin: Path, db: Path | None,
                 since: float | None = None, now: float | None = None,
                 need: int = NEED_GAMES, platform: str | None = None,
                 show_ids: bool = False) -> dict[str, Any]:
    now = time.time() if now is None else now
    plat = platform if platform is not None else _platform(None)
    evs = _events(logs_dir, since)
    rows = ingest_receipt.read_receipts(receipts, limit=10_000)
    ends = [e for e in evs if e["kind"] == "game_end"]
    games: list[dict[str, Any]] = []
    seen_targets: list[str] = []
    for i, g in enumerate(ends):
        t0 = g["ts"]
        t1 = ends[i + 1]["ts"] if i + 1 < len(ends) else float("inf")
        window = [e for e in evs if t0 <= e["ts"] < t1]
        chain = next((e for e in evs if e["kind"] == "chain_end"
                      and e["scheduled_at"] is not None
                      and SCHEDULE_SLACK_S[0] <= e["scheduled_at"] - t0
                      <= SCHEDULE_SLACK_S[1]), None)
        sched = chain["scheduled_at"] if chain else None
        rec = None
        for r in rows:
            at = _num(r.get("ts"))
            el = _num(r.get("elapsed_s"))
            if at is None or el is None:
                continue
            start = at - el
            if (sched is not None and abs(start - sched) <= RECEIPT_JOIN_S) or (
                    sched is None and SCHEDULE_SLACK_S[0] <= start - t0
                    <= SCHEDULE_SLACK_S[1]):
                rec = r
                break
        joined = chain is not None or rec is not None
        tft_marker = any(e["kind"] == "tft_skip" and e["ts"] - t0 <= 5.0
                         for e in window)
        # A TFT marker never hides a game that a chain joined: that chain is a
        # League writer verdict and is judged like any other.
        game: dict[str, Any] = {"ended_at": _iso(t0), "tft": tft_marker and not joined,
                                "tft_marker": tft_marker}
        if game["tft"]:
            game["verdict"] = "SKIP"
            game["why"] = "TFT end - no League rewind chain (Match-V5 is League-only)"
            games.append(game)
            continue
        restart = next((e for e in evs if e["kind"] == "rc_start"
                        and t0 < e["ts"] <= t0 + CHAIN_WINDOW_S), None)
        own = next((e["game_id"] for e in window if e["kind"] == "eog_id"), None)
        own_target = f"{plat}_{own}" if own else None
        stored_only = own is None and any(e["kind"] == "eog_stored" for e in window)
        sched_fail = next((e for e in evs if e["kind"] == "sched_fail"
                           and e["ts"] < t1
                           and SCHED_FAIL_SLACK_S[0] <= e["ts"] - t0
                           <= SCHED_FAIL_SLACK_S[1]), None)
        status = chain["status"] if chain else (rec or {}).get("status")
        target = chain["target"] if chain else (rec or {}).get("target")
        game.update({
            "own_target": _redact(own_target, show_ids),
            "status": status,
            "class": ingest_receipt.classify(status) if status else None,
            "target": _redact(target, show_ids),
            "attempts": (chain["attempt"] + 1) if chain else (rec or {}).get("attempts"),
            "chain_line": chain is not None,
            "receipt": rec is not None,
            "pinned": (rec or {}).get("pinned"),
            "fallback": (rec or {}).get("fallback"),
            "parked": (rec or {}).get("parked"),
            "elapsed_s": (rec or {}).get("elapsed_s"),
        })
        game["db_row"] = None
        if not joined and sched_fail is not None:
            # Never scheduled at all: a writer failure, restart or not.
            game["verdict"] = "FAIL"
            game["why"] = "the chain was never scheduled (Timer cap or schedule error)"
            games.append(game)
            continue
        if not joined and restart is not None:
            # Every staged Timer is a daemon: a restart drops the chain by
            # design and the weekly catchup owns that game. Not a writer
            # verdict either way, so it does not count toward --need. A chain
            # that DID end is always judged, restart or not.
            game["verdict"] = "VOID"
            game["why"] = (f"RC restarted at {_iso(restart['ts'])}, inside the "
                           "chain window - chain dropped by design, does not count")
            games.append(game)
            continue
        verdict, why = _judge(game, status=status, target=target,
                              own_target=own_target, now=now, t0=t0,
                              seen=seen_targets)
        if verdict == "INCOMPLETE" and stored_only and status is not None:
            why = "own id only from an 'already stored' line (saved before this game) - review by hand"
        if verdict == "PASS" and status == INGESTED_OK:
            game["db_row"] = _db_has(db, target) if db is not None else None
            if game["db_row"] is False:
                verdict, why = "FAIL", "ended ok but the target is not in rewind_history.db matches"
            elif game["db_row"] is None:
                verdict, why = "INCOMPLETE", "ended ok; DB row not checked (--no-db or unreadable)"
        if target:
            seen_targets.append(target)
        game["verdict"], game["why"] = verdict, why
        games.append(game)
    league = [g for g in games if not g["tft"] and g["verdict"] != "VOID"]
    verdict, why = _overall(league, need)
    return {"tool": "gated_y01_chain_report", "verdict": verdict, "why": why,
            "since": _iso(since) if since is not None else None,
            "now": _iso(now), "need": need, "league_game_ends": len(league),
            "tft_game_ends": sum(1 for g in games if g["tft"]),
            "void_game_ends": sum(1 for g in games if g["verdict"] == "VOID"),
            "receipts_rows": len(rows), "pin": _pin_view(_read_pin(pin), show_ids, plat),
            "games": games}


def _judge(game: dict[str, Any], *, status: str | None, target: str | None,
           own_target: str | None, now: float, t0: float,
           seen: list[str]) -> tuple[str, str]:
    if status is None:
        if now - t0 < CHAIN_WINDOW_S:
            return "INCOMPLETE", "chain still inside its window - re-run later"
        return "FAIL", f"no chain end within {int(CHAIN_WINDOW_S)} s of the game end"
    if target and target in seen:
        return "FAIL", "target repeats an earlier game's target (the Y-01 defect)"
    # Whatever the status, a chain that names a target names THIS game's.
    if own_target is not None and target is not None and target != own_target:
        return "FAIL", f"ended {status} for a target that is NOT this game's EOG id"
    if not game["chain_line"]:
        return "INCOMPLETE", "a receipt but no chain-end log line - review by hand"
    if not game["receipt"]:
        return "INCOMPLETE", "no Y-08 receipt joined - pinned / fallback unknown"
    if game["pinned"] is not True or game["fallback"] is True:
        return "FAIL", "chain ran unpinned or took the fallback path"
    if status in (EVENT_EXCLUDED, INGESTED_OK):
        if own_target is None:
            return "INCOMPLETE", "no collector own-id line for this game"
        if target != own_target:
            return "FAIL", f"ended {status} with no target"
        if status == INGESTED_OK:
            return "PASS", "ok for its own id"
        # Attempt > 1 = the pin arrived after the 90 s delay (the writer
        # retries awaiting_pin), not a missing queueId: a pin with neither
        # queueId nor KIWI never excludes, it parks target_not_indexed.
        late = "" if game["attempts"] == 1 else " (pin arrived late)"
        return "PASS", f"event mode excluded on attempt {game['attempts']}{late}"
    if status in ("already_present", "short_game"):
        return "INCOMPLETE", f"ended {status} - not an ok / excluded end; review by hand"
    return "FAIL", f"ended {status} ({ingest_receipt.classify(status)})"


def _overall(league: list[dict[str, Any]], need: int) -> tuple[str, str]:
    fails = [g for g in league if g["verdict"] == "FAIL"]
    if fails:
        return "FAIL", f"{len(fails)} game end(s) failed the predicate"
    if len(league) < need:
        return "INCOMPLETE", f"{len(league)} of {need} League game ends recorded"
    if any(g["verdict"] != "PASS" for g in league):
        return "INCOMPLETE", "a game end has no verdict yet"
    if not any(g["status"] == EVENT_EXCLUDED for g in league):
        return "INCOMPLETE", "no ARAM Mayhem (event_mode_excluded) end yet"
    if not any(g["status"] == INGESTED_OK for g in league):
        return "INCOMPLETE", "no Match-V5-eligible ok end yet"
    return "PASS", f"{len(league)} League game ends, every one pinned to its own id"


def _pin_view(p: dict[str, Any], show: bool, plat: str) -> dict[str, Any]:
    if not p.get("present"):
        return {"present": False}
    gid = p.get("game_id")
    return {"present": True,
            "target": _redact(f"{plat}_{gid}" if gid else None, show),
            "queue_id": p.get("queue_id"),
            "queue_id_present": p.get("queue_id_present"),
            "game_mode": p.get("game_mode"),
            "written_at": _iso(p["written_at"]) if p.get("written_at") else None}


def _platform(root: Path | None = None) -> str:
    """``core.operator_identity.platform()``'s rule, read from ``root``'s config.

    Env ``RC_RIOT_PLATFORM``, then the ``platform`` key of the READ checkout's
    ``config/operator_identity.json`` (not this worktree's), then the default.
    Only that key is read. The value test is the module's own
    ``normalize_platform`` (never a re-rolled copy, which drifted once: a BOM
    file read as absent and ``true`` became "TRUE"), and the file is read as
    UTF-8 with or without a BOM, exactly as the module reads it.
    """
    from core import operator_identity
    cfg = (root or _ROOT) / "config" / "operator_identity.json"
    try:
        blob = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        blob = {}
    file_val = blob.get("platform") if isinstance(blob, dict) else None
    for raw in (os.environ.get("RC_RIOT_PLATFORM", ""), file_val):
        val = operator_identity.normalize_platform(raw)
        if val:
            return val
    return operator_identity.DEFAULT_PLATFORM


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _parse_since(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return datetime.fromisoformat(text).timestamp()


def render(rep: dict[str, Any]) -> str:
    lines = [f"Y-01 verdict: {rep['verdict']} - {rep['why']}",
             f"since: {rep['since']}  now: {rep['now']}  League ends: "
             f"{rep['league_game_ends']}/{rep['need']}  TFT ends: {rep['tft_game_ends']}  "
             f"void ends: {rep['void_game_ends']}  "
             f"receipts: {rep['receipts_rows']}"]
    pin = rep["pin"]
    if pin.get("present"):
        lines.append(f"pin (latest game only): target {pin['target']}  queue_id "
                     f"{pin['queue_id']}  game_mode {pin['game_mode'] or '-'}  "
                     f"written {pin['written_at']}")
    else:
        lines.append("pin: absent")
    for g in rep["games"]:
        if g["tft"] or g["verdict"] == "VOID":
            lines.append(f"- {g['ended_at']}: {g['verdict']} - {g['why']}")
            continue
        lines.append(
            f"- {g['ended_at']}: {g['verdict']} - {g['why']} | status {g['status']}"
            f" attempts {g['attempts']} target {g['target']} own {g['own_target']}"
            f" pinned {g['pinned']} fallback {g['fallback']} db_row {g['db_row']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="ISO local time or epoch; game ends before it are ignored")
    ap.add_argument("--root", type=Path, default=None,
                    help="checkout to read (default: the main checkout of this worktree)")
    ap.add_argument("--need", type=int, default=NEED_GAMES)
    ap.add_argument("--no-db", action="store_true", help="skip the rewind_history.db row check")
    ap.add_argument("--show-ids", action="store_true", help="print raw match ids (console only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = args.root or main_checkout() or _ROOT
    try:
        since = _parse_since(args.since)
    except ValueError:
        ap.error(f"--since not ISO or epoch: {args.since!r}")
    rep = build_report(
        logs_dir=root / "logs",
        receipts=root / "ops" / "runtime" / ingest_receipt.RECEIPT_PATH.name,
        pin=root / "ops" / "runtime" / rlw.PIN_PATH.name,
        db=None if args.no_db else root / "data" / rlw.DB_PATH.name,
        since=since, need=args.need, platform=_platform(root),
        show_ids=args.show_ids)
    text = json.dumps(rep, indent=2, ensure_ascii=True) if args.json else render(rep)
    sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    return {"PASS": 0, "INCOMPLETE": 1}.get(rep["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
