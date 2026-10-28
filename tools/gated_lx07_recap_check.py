"""gated_lx07_recap_check.py - grade live death-recap rows for the LX-07 drain.

LX-07 (RM-608) asks three things of ONE real game played with
``RC_DEATH_RECAP=1`` in the RC process: does an own death write a row to
``data/coaching/death_recaps.jsonl`` holding champion names only, what FORM do
the live ``VictimName`` / ``KillerName`` fields carry (shared with LX-02 /
RM-673), and is the estimated physical / magic / true split sane per mode
(SR, ARAM / KIWI, Arena). Checking that by hand means a join of every recap
row against the wire's ChampionKill events per pass; this tool prints it in
ONE command.

It is READ-ONLY: it reads the recap log line by line and, when given, the
LX-02 capture set (``ops/runtime/liveclient_captures/``) through the LX-02
loader. It never writes, moves, locks or deletes anything, it makes no network
call (the DS /burst call is the writer's, never this tool's), and it never
ticks a row - its output is the INPUT to the four-part evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. Rows written by
``core.death_recap.process_kill`` from a hand-built payload pass every row
check just as well; that is the substitution the LX-07 row names.

WHAT IT REPORTS:
  - the log itself: exists, lines, rows, torn lines, rows inside the
    ``--since`` / ``--until`` window (``recorded_at``, epoch seconds; the rows
    carry NO game id, so the window is the only per-game key).
  - per row (``rows_verdict``): ``schema`` equals ``ROW_SCHEMA``,
    ``provenance`` is ``estimated``, ``mode`` is SR / ARAM / ARENA, the
    ``shares`` are three values in [0, 1] summing to 1 (or null with no
    contributor), ``basis`` agrees with the contributors' ``source`` values,
    each contributor holds only the writer's keys and a champion that is a
    DDragon champion (``names_only``), and - with captures - no string in the
    row equals a roster player name (``player_name_leaks``; only the count is
    printed). PASS / FAIL / NO_RESULT (no row in the window).
  - ``per_mode``: rows, basis counts, mean shares, the count of
    ``ds_burst`` contributors, and ``divergent``: a
    ``ds_burst`` contributor whose physical share differs from the writer's own
    DDragon fallback (``split_from_local`` at the row's resists) by
    ``DIVERGENCE`` or more. Recorded for the sanity read, never a FAIL.
  - with captures (``join_verdict``): every own death on the wire, found two
    ways - the writer's own ``is_self_death`` (player-name keys) and an
    independent read (``VictimName`` equal to the active player's name OR to
    its champion name) - the VictimName / KillerName FORM of each (LX-02
    ``name_form``; no name printed), whether a recap row carries its
    ``EventID`` at the same ``EventTime``, and whether the row's contributor
    champions and roles equal ``resolve_contributors`` over the first capture
    holding that event. Captures whose relay wrapper ``ts`` falls outside the
    ``--since`` / ``--until`` window are dropped (``captures_outside_window``),
    so an earlier game in a shared capture directory is not joined.
    MATCH / MISSING (an own death with no row) /
    TAP_BLIND (an own death the writer's ``is_self_death`` cannot see - the
    tap would never fire on it) / NO_RESULT (no own death in the captures).

NO PLAYER NAME IS EVER PRINTED (RM-906). Champion names, modes, event ids and
game times are printed; they are not player-identifying.

USAGE
    python tools/gated_lx07_recap_check.py --since <epoch> --until <epoch>
    python tools/gated_lx07_recap_check.py --since <epoch> --captures ops/runtime/liveclient_captures/ --json

Exit 2 = a ``--captures`` path is missing or holds no loadable payload, or a
window bound is not a number.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import death_recap as dr  # noqa: E402
from tools.gated_lx02_payload_check import (  # noqa: E402
    PLAYER_FIELDS, _looks_synthetic, _norm, _roster, load, name_form,
)

DDRAGON_CHAMPIONS = _ROOT / "data" / "meta" / "ddragon_champions.json"
MODES = ("SR", "ARAM", "ARENA")
BASES = ("ds", "mixed", "local", "none")
CONTRIB_KEYS = frozenset({"role", "champion", "level", "items", "source", "split", "weight"})
SOURCES = ("ds_burst", "local_ddragon")
SHARE_KEYS = ("physical", "magic", "true")
SUM_TOL = 1e-3
# The writer's own fixed strings and item ids are never a player name.
_FIXED = frozenset({"estimated", "sr", "aram", "arena", "ds", "mixed", "local", "none",
                    "champion", "other", "killer", "assister", "dsburst", "localddragon"})
TIME_TOL_S = 0.5
DIVERGENCE = 0.5


def _f(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def champion_keys(path: Path = DDRAGON_CHAMPIONS) -> set:
    """dr._norm keys of every DDragon champion id and display name."""
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    except (OSError, ValueError, AttributeError):
        return set()
    out: set = set()
    for cid, row in data.items():
        out.add(dr._norm(cid))
        if isinstance(row, dict):
            out.add(dr._norm(row.get("name")))
    out.discard("")
    return out


def read_log(path: Path) -> dict:
    """Lines, parsed rows and torn lines of the recap log (read only)."""
    out = {"exists": path.is_file(), "lines": 0, "torn": 0, "rows": []}
    if not out["exists"]:
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        out["exists"] = False
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        out["lines"] += 1
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            out["torn"] += 1
            continue
        if isinstance(obj, dict):
            out["rows"].append(obj)
        else:
            out["torn"] += 1
    return out


def _strings(obj: Any) -> list:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def grade_row(row: dict, champs: set, players: set) -> dict:
    """The per-row checks; ``problems`` lists every failed one by name."""
    problems: list = []
    if row.get("schema") != dr.ROW_SCHEMA:
        problems.append("schema")
    if row.get("provenance") != dr.PROVENANCE:
        problems.append("provenance")
    if row.get("mode") not in MODES:
        problems.append("mode")
    raw = row.get("contributors")
    contribs = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else None
    if contribs is None:
        problems.append("contributors")
        contribs = []
    names_only = not isinstance(raw, list) or len(contribs) == len(raw)
    shares = row.get("shares")
    if not contribs:
        if shares is not None:
            problems.append("shares")
    else:
        vals = [_f(shares.get(k)) for k in SHARE_KEYS] if isinstance(shares, dict) else [None]
        if (any(v is None or v < 0 or v > 1 for v in vals)
                or abs(sum(vals) - 1.0) > SUM_TOL):
            problems.append("shares")
    sources = {c.get("source") if isinstance(c.get("source"), str) else "?" for c in contribs}
    basis = row.get("basis")
    want = ("none" if not contribs else "ds" if sources == {"ds_burst"}
            else "local" if sources == {"local_ddragon"}
            else "mixed" if sources == set(SOURCES) else None)
    if basis not in BASES or basis != want:
        problems.append("basis")
    for c in contribs:
        if (set(c) - CONTRIB_KEYS or c.get("source") not in SOURCES
                or c.get("role") not in ("killer", "assister")
                or dr._norm(c.get("champion")) not in champs):
            names_only = False
    if not names_only:
        problems.append("names_only")
    leaks = sum(1 for s in _strings(row)
                if _norm(s) in players and dr._norm(s) not in champs
                and dr._norm(s) not in _FIXED and not s.strip().isdigit()) if players else 0
    if leaks:
        problems.append("player_name_leak")
    return {"problems": problems, "player_name_leaks": leaks, "contributors": contribs}


def _divergent(row: dict, contribs: list) -> list:
    out = []
    resists = row.get("our_resists") if isinstance(row.get("our_resists"), dict) else {}
    for c in contribs:
        split = c.get("split") if isinstance(c.get("split"), dict) else {}
        ds_phys = _f(split.get("physical"))
        if c.get("source") != "ds_burst" or ds_phys is None:
            continue
        local_phys = dr.split_from_local(str(c.get("champion") or ""), resists)[0]
        if abs(ds_phys - local_phys) >= DIVERGENCE:
            out.append({"champion": c.get("champion"), "role": c.get("role"),
                        "ds_physical": round(ds_phys, 4),
                        "local_physical": round(local_phys, 4)})
    return out


def _self_keys(payload: dict) -> tuple[set, str]:
    """(player-name keys, champion key) of the active player, LX-02 fold."""
    ap = payload.get("activePlayer") if isinstance(payload.get("activePlayer"), dict) else {}
    keys = {_norm(ap.get(k)) for k in PLAYER_FIELDS} - {""}
    champ = ""
    for p in payload.get("allPlayers") or []:
        if isinstance(p, dict) and keys & ({_norm(p.get(k)) for k in PLAYER_FIELDS} - {""}):
            champ = _norm(p.get("championName"))
            break
    return keys, champ


def own_deaths(loaded: list) -> list:
    """Every own-death ChampionKill across the captures, de-duplicated on
    (EventID, EventTime), with the first capture that holds it."""
    seen: dict = {}
    for payload, _ts, _sha in loaded:
        if not isinstance(payload.get("events"), dict):
            continue
        keys, champ = _self_keys(payload)
        champs, players = _roster(payload)
        mirror = champ and sum(
            1 for p in payload.get("allPlayers") or []
            if isinstance(p, dict) and _norm(p.get("championName")) == champ) > 1
        for ev in dr._events(payload):
            if ev.get("EventName") != "ChampionKill":
                continue
            key = (repr(ev.get("EventID")), repr(ev.get("EventTime")))
            if key in seen:
                continue
            victim = _norm(ev.get("VictimName"))
            tap = dr.is_self_death(ev, payload)
            by_player = bool(victim) and victim in keys
            by_champ = bool(victim) and victim == champ and not mirror
            if not (tap or by_player or by_champ):
                continue
            seen[key] = {
                "event_id": ev.get("EventID"), "event_time": _f(ev.get("EventTime")),
                "tap_sees": tap,
                "victim_form": name_form(ev.get("VictimName"), champs, players),
                "killer_form": name_form(ev.get("KillerName"), champs, players),
                "event": ev, "payload": payload,
            }
    return sorted(seen.values(), key=lambda d: (d["event_time"] or 0.0))


def in_window(loaded: list, since: Optional[float],
              until: Optional[float]) -> tuple[list, int]:
    """Captures whose relay wrapper ``ts`` (epoch seconds) is inside the window.
    A capture with no wrapper ts is kept: the window cannot place it."""
    keep, out = [], 0
    for item in loaded:
        ts = item[1]
        if ts is not None and ((since is not None and ts < since)
                               or (until is not None and ts > until)):
            out += 1
            continue
        keep.append(item)
    return keep, out


def _bump(d: dict, k: str) -> None:
    d[k] = d.get(k, 0) + 1


def check(log: dict, loaded: Optional[list] = None, since: Optional[float] = None,
          until: Optional[float] = None, champs: Optional[set] = None) -> dict:
    champs = champion_keys() if champs is None else champs
    given = bool(loaded)
    loaded, cap_outside = in_window(loaded or [], since, until)
    players: set = set()
    for payload, _ts, _sha in loaded:
        players |= _roster(payload)[1]
    rows, outside = [], 0
    for r in log["rows"]:
        t = _f(r.get("recorded_at"))
        if (since is not None and (t is None or t < since)) or (
                until is not None and (t is None or t > until)):
            outside += 1
            continue
        rows.append(r)
    graded, failed, leaks, per_mode = [], [], 0, {}
    for i, r in enumerate(rows, 1):
        g = grade_row(r, champs, players)
        leaks += g["player_name_leaks"]
        if g["problems"]:
            failed.append({"row": i, "problems": g["problems"]})
        m = per_mode.setdefault(str(r.get("mode")), {
            "rows": 0, "basis": {}, "mean_shares": None, "_acc": [0.0, 0.0, 0.0, 0],
            "ds_contributors": 0, "divergent": []})
        m["rows"] += 1
        m["ds_contributors"] += sum(1 for c in g["contributors"] if c.get("source") == "ds_burst")
        _bump(m["basis"], str(r.get("basis")))
        sh = r.get("shares") if isinstance(r.get("shares"), dict) else None
        if sh and "shares" not in g["problems"]:
            for j, k in enumerate(SHARE_KEYS):
                m["_acc"][j] += _f(sh.get(k)) or 0.0
            m["_acc"][3] += 1
        m["divergent"] += _divergent(r, g["contributors"])
        graded.append((r, g))
    for m in per_mode.values():
        acc = m.pop("_acc")
        if acc[3]:
            m["mean_shares"] = {k: round(acc[j] / acc[3], 4) for j, k in enumerate(SHARE_KEYS)}
    times = [_f(r.get("recorded_at")) for r in rows]
    times = [t for t in times if t is not None]
    out = {
        "log_exists": log["exists"], "log_lines": log["lines"], "torn_lines": log["torn"],
        "rows_total": len(log["rows"]), "rows_in_window": len(rows),
        "rows_outside_window": outside,
        "recorded_at_first": min(times) if times else None,
        "recorded_at_last": max(times) if times else None,
        "rows_failed": failed, "player_name_leaks": leaks,
        "modes": sorted(per_mode), "per_mode": per_mode,
        "rows_verdict": "NO_RESULT" if not rows else ("FAIL" if failed else "PASS"),
        "payloads": len(loaded), "captures_outside_window": cap_outside,
        "synthetic": sum(1 for p, _t, _s in loaded if _looks_synthetic(p)),
        "join": None,
    }
    if given:
        out["join"] = join(rows, loaded)
    return out


def join(rows: list, loaded: list) -> dict:
    deaths = own_deaths(loaded)
    max_gt = max((_f((p.get("gameData") or {}).get("gameTime")) or 0.0
                  for p, _t, _s in loaded if isinstance(p.get("gameData"), dict)),
                 default=0.0)
    used: set = set()
    victim_forms, killer_forms = {}, {}
    out_deaths, missing, blind, contrib_bad = [], 0, 0, 0
    for d in deaths:
        _bump(victim_forms, d["victim_form"])
        _bump(killer_forms, d["killer_form"])
        hit = None
        for i, r in enumerate(rows):
            if i in used or r.get("event_id") != d["event_id"]:
                continue
            rt, et = _f(r.get("game_time_s")), d["event_time"]
            if rt is not None and et is not None and abs(rt - et) <= TIME_TOL_S:
                hit = i
                break
        want = [(c["role"], c["champion"]) for c in dr.resolve_contributors(
            d["event"], d["payload"])]
        got = None
        if hit is not None:
            used.add(hit)
            raw = rows[hit].get("contributors")
            got = [(c.get("role"), c.get("champion"))
                   for c in (raw if isinstance(raw, list) else []) if isinstance(c, dict)]
        same = None if got is None else got == want
        if not d["tap_sees"]:
            blind += 1
        if hit is None:
            missing += 1
        if same is False:
            contrib_bad += 1
        out_deaths.append({
            "event_id": d["event_id"], "event_time": d["event_time"],
            "tap_sees": d["tap_sees"], "victim_form": d["victim_form"],
            "killer_form": d["killer_form"], "recap_row": hit is not None,
            "contributors_match": same, "expected_contributors": [c for _r, c in want]})
    after, orphan = 0, 0
    for i, r in enumerate(rows):
        if i in used:
            continue
        rt = _f(r.get("game_time_s"))
        if rt is not None and rt > max_gt:
            after += 1
        else:
            orphan += 1
    verdict = ("NO_RESULT" if not deaths else "TAP_BLIND" if blind
               else "MISSING" if missing else "MATCH")
    return {"own_deaths": len(deaths), "tap_blind": blind, "deaths_without_row": missing,
            "contributors_mismatch": contrib_bad, "victim_forms": victim_forms,
            "killer_forms": killer_forms, "rows_after_last_capture": after,
            "rows_without_wire_death": orphan, "game_time_max": max_gt,
            "deaths": out_deaths, "join_verdict": verdict}


def render(s: dict) -> str:
    lines = [
        f"log_exists={s['log_exists']} lines={s['log_lines']} torn={s['torn_lines']} "
        f"rows={s['rows_total']} in_window={s['rows_in_window']} "
        f"outside={s['rows_outside_window']}",
        f"recorded_at {s['recorded_at_first']} .. {s['recorded_at_last']}",
        f"rows_verdict={s['rows_verdict']} failed={s['rows_failed']} "
        f"player_name_leaks={s['player_name_leaks']}",
    ]
    for mode, m in sorted(s["per_mode"].items()):
        lines.append(f"  mode={mode} rows={m['rows']} basis={m['basis']} "
                     f"mean_shares={m['mean_shares']} ds_contributors={m['ds_contributors']} "
                     f"divergent={m['divergent']}")
    j = s.get("join")
    if j is None:
        lines.append("join not run (no --captures)")
    else:
        lines.append(f"payloads={s['payloads']} synthetic={s['synthetic']} "
                     f"captures_outside_window={s['captures_outside_window']} "
                     f"game_time_max={j['game_time_max']}")
        lines.append(f"join_verdict={j['join_verdict']} own_deaths={j['own_deaths']} "
                     f"tap_blind={j['tap_blind']} without_row={j['deaths_without_row']} "
                     f"contributors_mismatch={j['contributors_mismatch']} "
                     f"rows_after_last_capture={j['rows_after_last_capture']} "
                     f"rows_without_wire_death={j['rows_without_wire_death']}")
        lines.append(f"victim_forms={j['victim_forms']} killer_forms={j['killer_forms']}")
        for d in j["deaths"]:
            lines.append(f"  event {d['event_id']} t={d['event_time']} tap={d['tap_sees']} "
                         f"victim={d['victim_form']} killer={d['killer_form']} "
                         f"row={d['recap_row']} contributors_match={d['contributors_match']}")
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")


def _bound(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("bound")
    return f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Grade live death-recap rows for LX-07 (read-only).")
    ap.add_argument("--recaps", default=str(dr.DEFAULT_RECAPS_PATH))
    ap.add_argument("--since", default=None, help="window start, epoch seconds")
    ap.add_argument("--until", default=None, help="window end, epoch seconds")
    ap.add_argument("--captures", default=None,
                    help="the LX-02 capture file or directory (enables the join)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    try:
        since, until = _bound(args.since), _bound(args.until)
    except ValueError:
        print("--since / --until must be epoch seconds", file=sys.stderr)
        return 2
    loaded = None
    if args.captures:
        p = Path(args.captures)
        if not p.exists():
            print(f"no such path: {p}", file=sys.stderr)
            return 2
        loaded = load(p)
        if not loaded:
            print(f"no loadable payload at: {p}", file=sys.stderr)
            return 2
    s = check(read_log(Path(args.recaps)), loaded, since, until)
    print(json.dumps(s, indent=1, sort_keys=True, ensure_ascii=True) if args.json
          else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
