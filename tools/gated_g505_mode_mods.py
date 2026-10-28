"""gated_g505_mode_mods.py - G5-05 read-back: Arena ``ar`` growth addends, stat half and coach half.

Row G5-05 in docs/LIVE_GAME_GATED_SYNC.md asks two questions about the RM-172
ARENA growth-ADDEND seam (``agents/daemon_slayer/engine.py``
``_resolve_mode_addends``, applied by ``build_champion(...,
apply_mode_modifiers=True)``):

  CHECK A (stat)   Does a live Arena game really apply the wiki ``ar`` addends?
                   The live Live Client ``championStats`` is compared with the
                   DS stat line computed flag OFF and flag ON for the same
                   champion, level, items and augments.
  CHECK B (coach)  Did the live Arena coach send the flag? (RM-875, DEFAULT-OFF
                   behind ``RC_ARENA_MODE_MODIFIERS``, read once at import in
                   ``coaches/arena_coach.py``.) A ``data/ds_calibration.jsonl``
                   ARENA row's ``ds_picks`` order is compared with a re-run of
                   ``dispatch_for_coach`` flag ON and flag OFF.

WHY NOT THE COMPUTE HALF ALONE (the SUBSTITUTION trap). ON and OFF differing
in-process proves the engine COMPUTES an addend; only the game's own
``championStats`` says whether Arena APPLIES it (A), and only a row the live
coach WROTE says whether the flag reached the wire (B). A re-run that agrees
with itself is not evidence; the row's own order is the observed value.

PREDICATES (stated in the G5-05 row before any game):
  stat    NO_RESULT first: level under 6, no ``ar`` block for the champion, an
          owned item unknown to the snapshot, or no axis left after dropping
          each axis whose gap |ON - OFF| is under 10 HP or 1.5 AD (HP axis =
          ``maxHealth``, AD axis = ``attackDamage``; armor and attack speed are
          not read). Then FAIL iff on any axis |live - OFF| <= gap / 4; PASS iff
          on every axis |live - ON| <= gap / 4 and |live - OFF| > gap / 2; else
          NO_RESULT. The tool cannot see a Stat Anvil, a timed buff or a stat
          DS does not model, so a PASS or FAIL is capped at INCOMPLETE until the
          operator asserts all three absent with ``--clean``.
  coach   over ARENA rows at or after the cutoff (and of ``--champion`` when
          given): a row WITHOUT ``apply_mode_modifiers`` is pre-RM-875 code and
          is never re-run; ``false`` is flag OFF; both are NO_RESULT. A ``true``
          row whose ``engine_version`` differs from the checkout's is NO_RESULT.
          With ``--rerun``: PASS iff the row's order equals the ON order and
          differs from the OFF order; FAIL iff it equals the OFF order (and ON
          differs); NO_RESULT if ON and OFF agree, a re-run returns nothing, or
          the row matches neither (the row records no self-HP: first suspect).
          Verdict: FAIL if any row FAILS, PASS if one PASSES and none FAILS.

READ-ONLY: it reads files only, plus, with ``--rerun``, stateless compute
POSTs to the DS ``:8860`` engine (no write anywhere). It prints champion and
item ids only, never a Riot id, game id or match key, and never ticks a row -
its output is the INPUT to the four-part evidence contract.

USAGE
    # in an Arena game, level >= 6, out of combat, full HP, no buff icons:
    curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-liveclient > <scratch>/g505_lc.json
    python tools/gated_g505_mode_mods.py stat --lc <scratch>/g505_lc.json --augments <apiName,...> [--clean]
    # after an Arena game played with RC started under RC_ARENA_MODE_MODIFIERS=1:
    python tools/gated_g505_mode_mods.py coach --since <game load time> --champion <id> --rerun
Exit 0 = PASS, 1 = INCOMPLETE (a NO_RESULT check or an unasserted precondition), 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout  # noqa: E402
from tools.gated_g5_focus_layout import (  # noqa: E402
    liveclient_of,
    load_champions,
    load_json,
)
from tools.gated_g717_arena_readback import (  # noqa: E402
    load_jsonl,
    parse_utc,
    resolve_cutoff,
)

CALIBRATION_REL = Path("data") / "ds_calibration.jsonl"
FLAG_KEY = "apply_mode_modifiers"
MIN_LEVEL = 6
# Axis -> (Live Client championStats key, DS stats key, smallest usable gap).
AXES = {
    "hp": ("maxHealth", "hp", 10.0),
    "ad": ("attackDamage", "ad", 1.5),
}
_RAW_PREFIX = "game_character_displayname_"

# compute(champion, level, item_ids, augments, flag) -> DS stats dict.
StatCompute = Callable[[str, int, list, list, bool], Mapping[str, float]]
# rerun(row, flag) -> ordered item ids, or None when the engine gave nothing.
Rerun = Callable[[Mapping[str, Any], bool], "list[str] | None"]


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- CHECK A: stat half ---------------------------------------------------------

def own_player(lc: Mapping[str, Any]) -> dict:
    """My ``allPlayers`` row (matched on riotId, then summonerName); {} if none."""
    me = lc.get("activePlayer") if isinstance(lc.get("activePlayer"), dict) else {}
    players = [p for p in (lc.get("allPlayers") or []) if isinstance(p, dict)]
    for key in ("riotId", "summonerName"):
        mine = me.get(key)
        if isinstance(mine, str) and mine:
            for p in players:
                if p.get(key) == mine:
                    return p
    return {}


def champion_id(player: Mapping[str, Any], champions: Mapping[str, Any]) -> str | None:
    """Snapshot champion id from ``rawChampionName``, else by display name."""
    raw = player.get("rawChampionName")
    if isinstance(raw, str) and raw.startswith(_RAW_PREFIX):
        cid = raw[len(_RAW_PREFIX):]
        if cid in champions or not champions:
            return cid
    name = player.get("championName")
    for cid, rec in champions.items():
        if isinstance(rec, dict) and rec.get("name") == name:
            return cid
    return None


def stat_sample(lc_doc: Any, champions: Mapping[str, Any]) -> dict:
    """The live values CHECK A grades, or ``{"why": ...}`` when unusable."""
    lc = liveclient_of(lc_doc)
    me = lc.get("activePlayer") if isinstance(lc.get("activePlayer"), dict) else {}
    stats = me.get("championStats") if isinstance(me.get("championStats"), dict) else {}
    player = own_player(lc)
    if not me or not player:
        return {"why": "no activePlayer / own allPlayers row in the capture"}
    cid = champion_id(player, champions)
    if cid is None:
        return {"why": "champion not resolved to a snapshot id"}
    level = me.get("level")
    items = [str(i.get("itemID")) for i in (player.get("items") or [])
             if isinstance(i, dict) and i.get("itemID") is not None]
    game = lc.get("gameData") if isinstance(lc.get("gameData"), dict) else {}
    return {"champion": cid, "level": level if isinstance(level, int) else None,
            "items": items, "game_time": _num(game.get("gameTime")),
            "game_mode": game.get("gameMode"),
            "live": {axis: _num(stats.get(lc_key)) for axis, (lc_key, _d, _g) in AXES.items()}}


def grade_axes(live: Mapping[str, float | None], on: Mapping[str, float],
               off: Mapping[str, float], axes: Iterable[str]) -> dict:
    """The CHECK A predicate over the axes the champion's ``ar`` block moves."""
    rows: dict = {}
    for axis in axes:
        _lc_key, ds_key, min_gap = AXES[axis]
        v_on, v_off, v_live = on.get(ds_key), off.get(ds_key), live.get(axis)
        if v_on is None or v_off is None or v_live is None:
            rows[axis] = {"dropped": "missing value"}
            continue
        gap = abs(v_on - v_off)
        row = {"live": round(v_live, 3), "on": round(v_on, 3), "off": round(v_off, 3),
               "gap": round(gap, 3)}
        if gap < min_gap:
            row["dropped"] = f"gap under {min_gap}"
        rows[axis] = row
    kept = {a: r for a, r in rows.items() if "dropped" not in r}
    if not kept:
        return {"status": "NO_RESULT", "axes": rows, "why": "no axis left"}
    d_on = {a: abs(r["live"] - r["on"]) for a, r in kept.items()}
    d_off = {a: abs(r["live"] - r["off"]) for a, r in kept.items()}
    if any(d_off[a] <= kept[a]["gap"] / 4 for a in kept):
        return {"status": "FAIL", "axes": rows, "why": "live sits on the OFF value"}
    if all(d_on[a] <= kept[a]["gap"] / 4 and d_off[a] > kept[a]["gap"] / 2 for a in kept):
        return {"status": "PASS", "axes": rows}
    return {"status": "NO_RESULT", "axes": rows, "why": "live matches neither ON nor OFF"}


def _ds_compute() -> tuple[StatCompute, Callable[[str], Any]]:
    from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: PLC0415
    from agents.daemon_slayer.engine import (  # noqa: PLC0415
        _resolve_mode_addends,
        build_champion,
    )
    snap = DataSnapshot.load()

    def compute(champ: str, level: int, items: list, augments: list, flag: bool):
        return build_champion(snap, champ, level, item_ids=items, mode="ARENA",
                              augments=augments or None, apply_mode_modifiers=flag).stats

    return compute, lambda champ: _resolve_mode_addends(snap, champ, "ARENA")


def check_stat(lc_doc: Any, augments: list, clean: bool, champions: Mapping[str, Any],
               compute: StatCompute | None = None,
               addends_of: Callable[[str], Any] | None = None) -> dict:
    sample = stat_sample(lc_doc, champions)
    out: dict = {"sample": {k: v for k, v in sample.items() if k != "why"},
                 "augments": list(augments), "clean_asserted": clean}
    if "why" in sample:
        return {**out, "status": "NO_RESULT", "why": sample["why"]}
    if sample["level"] is None or sample["level"] < MIN_LEVEL:
        return {**out, "status": "NO_RESULT", "why": f"level under {MIN_LEVEL}"}
    if compute is None or addends_of is None:
        compute, addends_of = _ds_compute()
    addends = addends_of(sample["champion"]) or {}
    axes = [a for a in AXES if a in addends]
    out["addend_axes"] = axes
    if not axes:
        return {**out, "status": "NO_RESULT", "why": "no ar block on the HP / AD axes"}
    try:
        on = compute(sample["champion"], sample["level"], sample["items"], augments, True)
        off = compute(sample["champion"], sample["level"], sample["items"], augments, False)
    except KeyError as exc:
        return {**out, "status": "NO_RESULT", "why": f"unknown id {exc}"}
    graded = grade_axes(sample["live"], on, off, axes)
    out.update(graded)
    if graded["status"] in ("PASS", "FAIL") and not clean:
        out["would_be"] = graded["status"]
        out["status"] = "INCOMPLETE"
        out["why"] = "owed: assert no Stat Anvil, no timed buff, no unmodelled stat (--clean)"
    return out


# -- CHECK B: coach half --------------------------------------------------------

def row_time(row: Mapping[str, Any]) -> datetime | None:
    """A calibration row's ``ts`` (epoch seconds, as log_ds_run writes it, or ISO)."""
    ts = row.get("ts")
    num = _num(ts)
    if num is not None:
        try:
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return parse_utc(ts)


def vintage(row: Mapping[str, Any]) -> str:
    if FLAG_KEY not in row:
        return "pre_rm875"
    return "flag_on" if row.get(FLAG_KEY) is True else "flag_off"


def picks_order(row: Mapping[str, Any]) -> list[str]:
    return [str(p.get("item_id")) for p in (row.get("ds_picks") or []) if isinstance(p, dict)]


def grade_order(row_ids: list[str], on_ids: list[str] | None,
                off_ids: list[str] | None) -> dict:
    if not on_ids or not off_ids:
        return {"status": "NO_RESULT", "why": "a re-run returned nothing"}
    if on_ids == off_ids:
        return {"status": "NO_RESULT", "why": "ON and OFF agree"}
    if row_ids == on_ids:
        return {"status": "PASS"}
    if row_ids == off_ids:
        return {"status": "FAIL", "why": "row matches the OFF order"}
    return {"status": "NO_RESULT", "why": "row matches neither order (no self-HP recorded)"}


def _ds_rerun(row: Mapping[str, Any], flag: bool) -> list[str] | None:
    from coach_integration.archetype_dispatch import dispatch_for_coach  # noqa: PLC0415
    from coach_integration.enemy_stats import EnemyStats  # noqa: PLC0415
    es = row.get("enemy_stats") if isinstance(row.get("enemy_stats"), dict) else {}
    res = dispatch_for_coach(
        str(row.get("champion") or ""), mode_engine="ARENA", level=int(row.get("level") or 1),
        item_ids=[str(i) for i in (row.get("owned_items") or [])],
        enemy_stats=EnemyStats(**es), augments=list(row.get("augments") or []) or None,
        top=5, apply_mode_modifiers=flag)
    if res is None:
        return None
    return [str(r.get("id")) for r in res.display_rows]


def check_coach(rows: list[dict], cutoff: datetime | None, champion: str | None,
                engine_version: str, rerun: Rerun | None = None) -> dict:
    if cutoff is None:
        return {"status": "NO_RESULT", "rows": 0, "why": "no cutoff (pass --since)"}
    picked = []
    for r in rows:
        t = row_time(r)
        if t is None or t < cutoff or str(r.get("mode") or "").upper() != "ARENA":
            continue
        if champion and str(r.get("champion") or "").lower() != champion.lower():
            continue
        picked.append(r)
    counts = {"pre_rm875": 0, "flag_off": 0, "flag_on": 0}
    outcomes: dict = {}
    graded = []
    for r in picked:
        v = vintage(r)
        counts[v] += 1
        if v != "flag_on":
            continue
        if str(r.get("engine_version")) != engine_version:
            res = {"status": "NO_RESULT", "why": "engine_version differs"}
        elif rerun is None:
            res = {"status": "NO_RESULT", "why": "re-run owed (--rerun)"}
        else:
            res = grade_order(picks_order(r), rerun(r, True), rerun(r, False))
        outcomes[res["status"]] = outcomes.get(res["status"], 0) + 1
        graded.append({"level": r.get("level"), "champion": r.get("champion"), **res})
    if outcomes.get("FAIL"):
        status = "FAIL"
    elif outcomes.get("PASS"):
        status = "PASS"
    else:
        status = "NO_RESULT"
    out = {"status": status, "rows": len(picked), "vintage": counts, "outcomes": outcomes,
           "graded": graded[:20], "engine_version": engine_version}
    if not picked:
        out["why"] = "no ARENA row in the window"
    elif not counts["flag_on"]:
        out["why"] = ("rows predate RM-875 (RC not restarted onto it)" if counts["pre_rm875"]
                      else "flag OFF (RC not started with RC_ARENA_MODE_MODIFIERS=1)")
    return out


def _verdict(status: str) -> str:
    return status if status in ("PASS", "FAIL") else "INCOMPLETE"


def render(name: str, rep: dict) -> str:
    lines = [f"G5-05 {name}: {_verdict(rep['status'])} ({rep['status']}) {rep.get('why', '')}".rstrip()]
    if name == "stat":
        s = rep.get("sample", {})
        lines.append(f"- sample: champion {s.get('champion')} level {s.get('level')}"
                     f" game_time {s.get('game_time')} mode {s.get('game_mode')}"
                     f" items {s.get('items')} augments {rep.get('augments')}")
        for axis, row in (rep.get("axes") or {}).items():
            lines.append(f"- {axis}: {row}")
        if rep.get("would_be"):
            lines.append(f"- would be {rep['would_be']} once --clean is asserted")
    else:
        lines.append(f"- rows {rep['rows']} vintage {rep.get('vintage')}"
                     f" outcomes {rep.get('outcomes')} engine {rep.get('engine_version')}")
        for g in rep.get("graded", []):
            lines.append(f"- {g}")
    lines.append("Not a tick: record value + source + ts + predicate in the G5-05 row.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_stat = sub.add_parser("stat", help="CHECK A: live championStats vs DS ON / OFF")
    a_stat.add_argument("--lc", required=True, help="relay /latest-liveclient capture (JSON)")
    a_stat.add_argument("--augments", default="", help="picked augment apiNames, comma list")
    a_stat.add_argument("--clean", action="store_true",
                        help="operator asserts: no Stat Anvil, no timed buff, no unmodelled stat")
    a_coach = sub.add_parser("coach", help="CHECK B: calibration rows vs dispatch ON / OFF")
    a_coach.add_argument("--since", default=None,
                         help="window start, any ISO time (default: health.json started_at)")
    a_coach.add_argument("--champion", default=None)
    a_coach.add_argument("--rerun", action="store_true",
                         help="re-run dispatch_for_coach ON / OFF (compute POSTs to DS :8860)")
    a_coach.add_argument("--data-root", default=None, help="checkout whose data/ is read")
    for p in (a_stat, a_coach):
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "stat":
        augs = [x.strip() for x in a.augments.split(",") if x.strip()]
        rep = check_stat(load_json(Path(a.lc)), augs, a.clean, load_champions(_ROOT))
    else:
        from core.ds_calibration import current_engine_version  # noqa: PLC0415
        data_root = Path(a.data_root) if a.data_root else (main_checkout(_ROOT) or _ROOT)
        cutoff, _source = resolve_cutoff(a.since, data_root)
        rep = check_coach(load_jsonl(data_root / CALIBRATION_REL), cutoff, a.champion,
                          current_engine_version(), _ds_rerun if a.rerun else None)
    print(json.dumps(rep, indent=2) if a.json else render(a.cmd, rep))
    return {"PASS": 0, "FAIL": 2}.get(rep["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
