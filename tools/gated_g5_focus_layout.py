"""gated_g5_focus_layout.py - GATE 5 read-back: does the focus board see the Arena team layout?

The RM-844 / RM-854 focus-board shadow column (``core/arena_coach_shadow.py``
``_focus_board_column``) is SHADOW-ONLY until a GATE 5 row verifies it live.
Its one live-unverified premise is the team layout: ``core/focus_board_live.py``
``roster_from_lc`` reads the Live Client ``allPlayers[].team`` and calls every
player on my ``team`` (minus me) an ally and every other non-blank team an
enemy, and its docstring says "In Arena that makes my partner the one ally ...
NOT live-verified yet: the gated GATE 5 row owns that." This tool checks that
premise against a source the rule does not read: the LCU champ-select subteam
roster (``lcu/champ_select_shape.py`` ``arena_teams``, served at ``/api/state``
-> ``lcu.champ_select.arena_teams``, one entry per subteam, ``is_me`` on mine).

WHY NOT THE SHADOW ROW ALONE (the SUBSTITUTION trap). A ``focus_board`` column
with ``status`` ``ok`` proves the board COMPUTED. Its ``allies`` list is made by
the same ``team`` rule this row is testing, so agreement between the column and
the Live Client grouping is circular. Only the subteam roster is independent.

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md G5-11 before any game):
  subteams  OK iff the champ-select capture has exactly one ``is_me`` subteam
            and at least one other, no subteam is empty, every cell is picked
            (championId != 0) and my live champion is in mine; partners = my
            subteam's champions minus me (once); enemy cells = every other
            subteam's champions. Else
            NO_RESULT (an unrevealed lobby, or captures from two games).
  layout    one test, applied to a list of allies and a list of enemies (as
            snapshot ids), checked in this order. NO_RESULT if an id is not a
            known champion (unresolved), or if an id is in no subteam at all
            (another game; my own champion counts as known). FAIL iff a player
            is on the WRONG SIDE: an ally that is not a partner (me included),
            or an enemy beyond the enemy cells' multiset (a
            partner counted as an enemy; a mirror champion on an enemy subteam
            is not one). NO_RESULT if a partner is merely missing (not listed,
            or skipped by the board for a missing level - not a layout fault).
            Else PASS.
  roster    the layout test on ``roster_from_lc`` (the adapter's own mapping)
            run over the in-game capture; NO_RESULT when a capture is missing,
            the roster is empty, or the Live Client lists more players than the
            subteams hold. The team-value histogram is printed whatever the
            outcome (the layout as Riot spelled it).
  shadow    over the ``data/arena_coach_shadow.jsonl`` rows inside the window
            (``--since`` .. ``--until``) whose ``champ`` is my champion and that
            carry a ``focus_board`` dict: the layout test on each ``ok``
            column's ``allies`` / ``kill_order``. PASS iff at least one column
            PASSES and none FAILS; FAIL iff any column FAILS; else NO_RESULT
            (status counts and per-outcome counts are printed).

READ-ONLY: it reads files only; it never writes, moves, locks or deletes
anything, prints no Riot id or game id (champion ids only), and never ticks a
row - its output is the INPUT to the four-part evidence contract.

USAGE (from a worktree it reads the MAIN checkout's data/ for the shadow file)
    # in champ select (after every pick locks):
    curl -sk https://127.0.0.1:8888/api/state > <scratch>/g511_cs.json
    # in game, after round 1 starts:
    curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-liveclient > <scratch>/g511_lc.json
    # after the game (or mid-game):
    python tools/gated_g5_focus_layout.py --cs <scratch>/g511_cs.json \\
        --lc <scratch>/g511_lc.json --since <game load time> --until <game end>
Exit 0 = PASS, 1 = INCOMPLETE (a NO_RESULT check), 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import focus_board_live as fbl  # noqa: E402
from tools.gated_frame_readback import main_checkout  # noqa: E402
from tools.gated_g717_arena_readback import (  # noqa: E402
    after,
    load_jsonl,
    parse_utc,
    resolve_cutoff,
)

SHADOW_REL = Path("data") / "arena_coach_shadow.jsonl"
DS_DATA_REL = Path("data") / "daemon_slayer"


def load_json(path: Path | None) -> Any:
    """A JSON file's value, or None when it is missing or unreadable."""
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def load_champions(root: Path = _ROOT) -> dict:
    """DDragon ``data`` (id -> record with ``key`` / ``name``) for the pinned patch."""
    try:
        patch = (root / DS_DATA_REL / "current.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    doc = load_json(root / DS_DATA_REL / patch / "champions.json")
    data = doc.get("data") if isinstance(doc, dict) else None
    return data if isinstance(data, dict) else {}


def _key_index(champions: Mapping[str, Any]) -> dict:
    """Numeric DDragon key (as int) -> snapshot champion id."""
    out: dict = {}
    for cid, rec in champions.items():
        key = rec.get("key") if isinstance(rec, dict) else None
        try:
            out[int(str(key))] = cid
        except (TypeError, ValueError):
            continue
    return out


def arena_teams_of(cs_doc: Any) -> list:
    """``arena_teams`` from an /api/state capture, an ``lcu`` dict, a
    ``champ_select`` dict or a bare list; [] when absent."""
    node = cs_doc
    for key in ("lcu", "champ_select"):
        if isinstance(node, dict) and isinstance(node.get(key), dict):
            node = node[key]
    if isinstance(node, dict):
        node = node.get("arena_teams")
    return [t for t in node if isinstance(t, dict)] if isinstance(node, list) else []


def liveclient_of(lc_doc: Any) -> dict:
    """The allgamedata dict from a relay capture (``{"ts", "data"}``), an
    /api/state capture (``liveclient``) or a bare allgamedata dict."""
    if not isinstance(lc_doc, dict):
        return {}
    for key in ("data", "liveclient"):
        inner = lc_doc.get(key)
        if isinstance(inner, dict) and isinstance(inner.get("allPlayers"), list):
            return inner
    return lc_doc if isinstance(lc_doc.get("allPlayers"), list) else {}


def check_subteams(teams: list, me_id: str, champions: Mapping[str, Any]) -> dict[str, Any]:
    keys = _key_index(champions)
    sizes = sorted(len(t.get("cells") or []) for t in teams)
    out: dict[str, Any] = {"status": "NO_RESULT", "subteams": len(teams), "sizes": sizes,
                           "partners": [], "enemy_cells": []}
    mine = [t for t in teams if t.get("is_me") is True]
    if len(mine) != 1:
        out["why"] = f"{len(mine)} is_me subteams in the champ-select capture"
        return out
    if len(teams) < 2 or 0 in sizes:
        out["why"] = "a subteam is missing or empty in the capture (lobby not revealed)"
        return out
    partners: list = []
    enemies: list = []
    for t in teams:
        for c in t.get("cells") or []:
            cid = c.get("championId") if isinstance(c, dict) else None
            if not isinstance(cid, int) or isinstance(cid, bool) or cid == 0:
                out["why"] = "a subteam cell has no locked champion"
                return out
            (partners if t is mine[0] else enemies).append(keys.get(cid, f"key:{cid}"))
    if not me_id or me_id not in partners:
        out["why"] = "my live champion is not in my subteam (captures from two games?)"
        return out
    partners.remove(me_id)
    out.update(status="OK", me=me_id, partners=sorted(partners), enemy_cells=sorted(enemies))
    return out


def layout(allies: list, enemies: list, sub: dict,
           champions: Mapping[str, Any]) -> tuple[str, str]:
    """The layout test (module docstring): ``(PASS | FAIL | NO_RESULT, why)``."""
    unknown = sorted({x for x in allies + enemies if x not in champions})
    if unknown:
        return "NO_RESULT", f"unresolved champion(s) {unknown}"
    partners, cells = Counter(sub["partners"]), Counter(sub["enemy_cells"])
    known = set(partners) | set(cells) | {sub.get("me")}
    outside = sorted({x for x in allies + enemies if x not in known})
    if outside:
        return "NO_RESULT", f"champion(s) in no subteam {outside} (another game?)"
    wrong_ally = Counter(allies) - partners
    wrong_enemy = Counter(enemies) - cells
    if wrong_ally or wrong_enemy:
        return "FAIL", (f"wrong side: allies not partners {sorted(wrong_ally.elements())},"
                        f" enemies beyond the other subteams {sorted(wrong_enemy.elements())}")
    missing = partners - Counter(allies)
    if missing:
        return "NO_RESULT", f"partner(s) missing from allies {sorted(missing.elements())}"
    return "PASS", ""


def check_roster(lc: dict, sub: dict, champions: Mapping[str, Any]) -> dict[str, Any]:
    hist = Counter(fbl._team(p) for p in lc.get("allPlayers") or [] if isinstance(p, dict))
    out: dict[str, Any] = {"status": "NO_RESULT", "team_values": dict(sorted(hist.items())),
                           "players": sum(hist.values())}
    roster, notes = fbl.roster_from_lc(lc, champions) if lc else (None, ["no capture"])
    if roster is None:
        out["why"] = "; ".join(notes) or "no roster"
        return out
    allies = [a[0] for a in roster.allies]
    enemies = [e[0] for e in roster.enemies]
    out.update(me=roster.me[0], allies=sorted(allies), enemies=len(enemies))
    if sub.get("status") != "OK":
        out["why"] = "subteam truth unavailable"
        return out
    cells = len(sub["partners"]) + 1 + len(sub["enemy_cells"])
    if out["players"] > cells:
        out["why"] = f"Live Client lists {out['players']} players, the subteams hold {cells}"
        return out
    out["status"], why = layout(allies, enemies, sub, champions)
    if why:
        out["why"] = why
    return out


def _is_me_row(row: dict, me_id: str, champions: Mapping[str, Any]) -> bool:
    """The row's ``champ`` (a display name) names my champion."""
    rec = champions.get(me_id)
    name = rec.get("name") if isinstance(rec, dict) else None
    want = {fbl._norm(me_id), fbl._norm(name)} - {""}
    return fbl._norm(row.get("champ")) in want


def check_shadow(rows: list[dict], sub: dict,
                 champions: Mapping[str, Any]) -> dict[str, Any]:
    cols = [r["focus_board"] for r in rows if isinstance(r.get("focus_board"), dict)]
    status = Counter(str(c.get("status")) for c in cols)
    oks = [c for c in cols if c.get("status") == fbl.STATUS_OK]
    out: dict[str, Any] = {"status": "NO_RESULT", "rows": len(rows), "columns": len(cols),
                           "column_status": dict(sorted(status.items())),
                           "relogs": sum(1 for r in rows if r.get("focus_board_relog") is True),
                           "kill_order_lengths": dict(sorted(Counter(
                               len(c.get("kill_order") or []) for c in oks).items()))}
    if not oks:
        out["why"] = "no ok focus_board column for my champion in the window"
        return out
    if sub.get("status") != "OK":
        out["why"] = "subteam truth unavailable"
        return out
    outcomes: Counter = Counter()
    first: dict = {}
    for c in oks:
        state, why = layout([str(a) for a in c.get("allies") or []],
                            [str(k) for k in c.get("kill_order") or []], sub, champions)
        outcomes[state] += 1
        first.setdefault(state, why)
    out["ok_columns"] = len(oks)
    out["outcomes"] = dict(sorted(outcomes.items()))
    if outcomes["FAIL"]:
        out["status"] = "FAIL"
        out["why"] = f"{outcomes['FAIL']} ok column(s) fail; first: {first['FAIL']}"
    elif outcomes["PASS"]:
        out["status"] = "PASS"
    else:
        out["why"] = f"no ok column passes; first: {first.get('NO_RESULT', '')}"
    return out


def report(cs_doc: Any, lc_doc: Any, shadow_rows: list[dict], cutoff: datetime | None,
           champions: Mapping[str, Any], until: datetime | None = None) -> dict[str, Any]:
    lc = liveclient_of(lc_doc)
    me_id = ""
    if lc:
        roster, _ = fbl.roster_from_lc(lc, champions)
        me_id = roster.me[0] if roster is not None else ""
    sub = check_subteams(arena_teams_of(cs_doc), me_id, champions)
    rows = after(shadow_rows, cutoff) if cutoff is not None else []
    if until is not None:
        late = {id(r) for r in after(rows, until)}
        rows = [r for r in rows if id(r) not in late]
    rows = [r for r in rows if _is_me_row(r, me_id, champions)] if me_id else []
    checks = {
        "subteams": sub,
        "roster": check_roster(lc, sub, champions),
        "shadow": check_shadow(rows, sub, champions),
    }
    if cutoff is None:
        checks["shadow"]["why"] = "no cutoff (pass --since)"
    states = [checks["roster"]["status"], checks["shadow"]["status"]]
    if "FAIL" in states:
        verdict = "FAIL"
    elif states == ["PASS", "PASS"]:
        verdict = "PASS"
    else:
        verdict = "INCOMPLETE"
    return {"schema": "gated_g5_focus_layout/v1", "verdict": verdict,
            "cutoff_utc": cutoff.isoformat() if cutoff else None,
            "until_utc": until.isoformat() if until else None, "checks": checks}


def render(rep: dict[str, Any]) -> str:
    c = rep["checks"]
    s, r, h = c["subteams"], c["roster"], c["shadow"]
    lines = [f"G5-11 focus-board layout: {rep['verdict']}"
             f" (window {rep['cutoff_utc']} .. {rep['until_utc']})"]
    lines.append(f"- subteams: {s['status']} {s['subteams']} subteams sizes {s['sizes']}"
                 f" partners {s['partners']} {s.get('why', '')}".rstrip())
    lines.append(f"- roster: {r['status']} team values {r['team_values']} me {r.get('me')}"
                 f" allies {r.get('allies')} enemies {r.get('enemies')} {r.get('why', '')}".rstrip())
    lines.append(f"- shadow: {h['status']} rows {h['rows']} columns {h['columns']}"
                 f" status {h['column_status']} outcomes {h.get('outcomes', {})}"
                 f" relogs {h['relogs']} kill_order lengths {h['kill_order_lengths']}"
                 f" {h.get('why', '')}".rstrip())
    lines.append("Not a tick: record value + source + ts + predicate in the G5-11 row.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cs", default=None, help="champ-select /api/state capture (JSON file)")
    ap.add_argument("--lc", default=None, help="in-game relay /latest-liveclient capture")
    ap.add_argument("--since", default=None,
                    help="shadow window start, any ISO time (default: health.json started_at)")
    ap.add_argument("--until", default=None,
                    help="shadow window end, any ISO time (default: none; set it to the game end)")
    ap.add_argument("--data-root", default=None, help="checkout whose data/ is read")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    data_root = Path(a.data_root) if a.data_root else (main_checkout(_ROOT) or _ROOT)
    cutoff, _source = resolve_cutoff(a.since, data_root)
    rep = report(load_json(Path(a.cs)) if a.cs else None,
                 load_json(Path(a.lc)) if a.lc else None,
                 load_jsonl(data_root / SHADOW_REL), cutoff, load_champions(_ROOT),
                 until=parse_utc(a.until) if a.until else None)
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "INCOMPLETE": 1}.get(rep["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
