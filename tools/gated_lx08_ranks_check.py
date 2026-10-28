"""gated_lx08_ranks_check.py - grade captured Live Client payloads for the LX-08 drain.

LX-08 (RM-603, skill points) asks four things of real Live Client reads: does
``/allgamedata`` ``activePlayer.abilities`` carry an ``abilityLevel`` per
Q/W/E/R slot, does the free R rank of Jayce / Elise / Nidalee / Karma read 1
at level 1, what do Aphelios's slots report, and do the ranks follow the same
level-point rule in ARAM, Arena and URF as on the Rift. RC reads the ranks two
ways: ``dashboard/_liveclient.py`` feeds ``activePlayer.abilities`` to
``core.skill_point_tracker.read_skill_snapshot`` (the ``ability_ranks`` field),
and ``game_reader/snapshot_normalizer.py`` ``_read_my_abilities`` reads the
separate ``/activeplayerabilities`` endpoint and DROPS a slot whose
``displayName`` is empty, which makes the tracker read None for the whole
state. This tool grades both shapes in ONE command.

It is READ-ONLY: it parses the capture files and prints. It never writes,
moves, locks or deletes a capture, it makes no network call, and it never
ticks a row - its output is the INPUT to the four-part evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. A hand-built
payload passes these checks just as well; that is the substitution the LX-08
row names, and why a real game's capture is the only thing that closes it.

NO PLAYER NAME IS EVER PRINTED (RM-906). The only roster value printed is the
active player's ``championName`` (a fixed Riot string that picks the kit
rules); summoner names, Riot ids and ability display names are never echoed.

INPUTS (any mix in one directory; the LX-02 capture set is reused as is):
  - ``allgamedata``: a relay wrapper ``{"ts", "data": {...}}`` from
    ``:8889/latest-liveclient`` or a raw ``/allgamedata`` body (has
    ``activePlayer`` or ``gameData``).
  - ``apa``: a raw ``/activeplayerabilities`` body (top-level ``Q`` / ``W`` /
    ``E`` / ``R`` objects, no ``gameData``). It carries no level and no
    champion, so it grades the normalizer's slot read only.

WHAT IT REPORTS:
  - payloads per kind, synthetic (``gated_lx02_payload_check`` rule) and
    byte-identical duplicate counts, game modes, the relay ``ts`` span.
  - ``ranks``: per allgamedata payload, whether each of Q/W/E/R is an object
    with an integer ``abilityLevel`` (``abilityLevel_types`` counts the JSON
    type seen per slot), whether ``read_skill_snapshot`` (the dashboard call,
    run for real) returns a reading, and a verdict PRESENT (every payload
    reads) / PARTIAL / ABSENT / NO_RESULT (no allgamedata payload).
  - ``self``: how the active player's roster row was found (``exact`` =
    raw ``summonerName`` equality, the dashboard rule; ``folded`` = tag-strip
    lower-case match on any player field; ``none``), since the kit rules hang
    on that row's ``championName``.
  - ``free_r``: level-1 payloads of a free-R kit (``SPECIAL_KITS`` with
    ``free_r`` > 0): the R rank seen and a verdict READS_1 / READS_0 /
    MIXED / NO_RESULT.
  - ``fenced``: per payload of a kit with ``supported=False`` (Aphelios), the
    level and the four ranks as read, recorded only (never graded).
  - ``per_mode``: per ``gameMode``, over supported-kit payloads with a
    reading, the min / max of ``unspent`` (tracker rule) and how many fall
    outside ``0 <= unspent <= level`` or hold a rank above the slot cap; a
    verdict CONSISTENT / INCONSISTENT per mode and ``modes_agree``.
  - ``apa``: per ``/activeplayerabilities`` capture, slots with an integer
    ``abilityLevel`` and slots the normalizer would drop (empty
    ``displayName``); a verdict READABLE / DROPS_SLOT / NO_RANK / NO_RESULT.

USAGE (the capture is the drain's act; this tool only reads it)
    python tools/gated_lx08_ranks_check.py ops/runtime/liveclient_captures/
    python tools/gated_lx08_ranks_check.py <capture.json> --json

Exit 2 = nothing loadable at the path (no file, no ``*.json``, no payload).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import skill_point_tracker as spt  # noqa: E402
from tools.gated_lx02_payload_check import (  # noqa: E402
    PLAYER_FIELDS, _jtype, _looks_synthetic, _norm, load,
)

SLOTS = ("Q", "W", "E", "R")
FREE_R_KITS = tuple(sorted(k for k, r in spt.SPECIAL_KITS.items() if r.free_r > 0))
FENCED_KITS = tuple(sorted(k for k, r in spt.SPECIAL_KITS.items() if not r.supported))


def kind(payload: dict) -> str:
    """``allgamedata`` / ``apa`` / ``other`` for one unwrapped capture."""
    if "activePlayer" in payload or "gameData" in payload:
        return "allgamedata"
    if any(isinstance(payload.get(s), dict) or isinstance(payload.get(s.lower()), dict)
           for s in SLOTS):
        return "apa"
    return "other"


def _int_rank(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def self_row(payload: dict) -> tuple[str, Optional[dict]]:
    """(how, row) for the active player's roster row."""
    ap = payload.get("activePlayer") if isinstance(payload.get("activePlayer"), dict) else {}
    roster = payload.get("allPlayers")
    rows = [p for p in roster if isinstance(p, dict)] if isinstance(roster, list) else []
    me_name = ap.get("summonerName", "")
    for p in rows:
        if me_name and p.get("summonerName") == me_name:
            return "exact", p
    keys = {_norm(ap.get(k)) for k in PLAYER_FIELDS} - {""}
    for p in rows:
        if keys & ({_norm(p.get(k)) for k in PLAYER_FIELDS} - {""}):
            return "folded", p
    return "none", None


def _champion(row: Optional[dict]) -> str:
    c = row.get("championName") if isinstance(row, dict) else None
    return c if isinstance(c, str) else ""


def grade_allgamedata(payload: dict) -> dict:
    """One allgamedata payload reduced to the LX-08 fields (no names)."""
    ap = payload.get("activePlayer") if isinstance(payload.get("activePlayer"), dict) else {}
    gd = payload.get("gameData") if isinstance(payload.get("gameData"), dict) else {}
    abilities = ap.get("abilities")
    slot_ok, types = {}, {}
    for s in SLOTS:
        entry = abilities.get(s) if isinstance(abilities, dict) else None
        has = isinstance(entry, dict) and "abilityLevel" in entry
        types[s] = _jtype(entry.get("abilityLevel")) if has else "missing"
        slot_ok[s] = has and _int_rank(entry.get("abilityLevel"))
    reading = spt.read_skill_snapshot({"level": ap.get("level"), "abilities": abilities})
    how, row = self_row(payload)
    champ = _champion(row)
    rules = spt.kit_rules(champ)
    out = {
        "mode": gd.get("gameMode") if isinstance(gd.get("gameMode"), str) else "",
        "level": reading.level if reading else None,
        "champion": champ,
        "self": how,
        "slots_ok": slot_ok,
        "types": types,
        "reads": reading is not None,
        "ranks": dict(reading.ranks) if reading else None,
        "supported": rules.supported,
        "unspent": spt.unspent(reading, champ) if reading else None,
        "over_cap": None,
    }
    if reading is not None and rules.supported:
        out["over_cap"] = [s for s in spt.SLOTS
                           if reading.ranks[s] > spt._slot_cap(rules, reading.level, s)]
    return out


def grade_apa(payload: dict) -> dict:
    """One /activeplayerabilities body: rank presence and the normalizer drop."""
    ranked, dropped = [], []
    for s in SLOTS:
        entry = payload.get(s) or payload.get(s.lower())
        if not isinstance(entry, dict):
            dropped.append(s)
            continue
        name = entry.get("displayName") or entry.get("name") or ""
        if not name:
            dropped.append(s)
        # Same fallback as the normalizer: abilityLevel, else level.
        lvl = entry.get("abilityLevel") if "abilityLevel" in entry else entry.get("level")
        if _int_rank(lvl):
            ranked.append(s)
    if dropped:
        verdict = "DROPS_SLOT"
    elif len(ranked) == len(SLOTS):
        verdict = "READABLE"
    else:
        verdict = "NO_RANK"
    return {"ranked": ranked, "dropped": dropped, "verdict": verdict}


def _verdict_set(values: list, one: str, zero: str) -> str:
    if not values:
        return "NO_RESULT"
    if all(v == 1 for v in values):
        return one
    if all(v == 0 for v in values):
        return zero
    return "MIXED"


def check(loaded: list[tuple[dict, Optional[float], str]]) -> dict:
    agd = [p for p, _ts, _h in loaded if kind(p) == "allgamedata"]
    apa = [p for p, _ts, _h in loaded if kind(p) == "apa"]
    shas = [h for _p, _ts, h in loaded]
    ts = [t for _p, t, _h in loaded if t is not None]
    rows = [grade_allgamedata(p) for p in agd]

    reads = sum(1 for r in rows if r["reads"])
    types: dict = {s: {} for s in SLOTS}
    for r in rows:
        for s in SLOTS:
            types[s][r["types"][s]] = types[s].get(r["types"][s], 0) + 1
    if not rows:
        rv = "NO_RESULT"
    elif reads == len(rows) and all(all(r["slots_ok"].values()) for r in rows):
        rv = "PRESENT"
    elif reads or any(any(r["slots_ok"].values()) for r in rows):
        rv = "PARTIAL"
    else:
        rv = "ABSENT"

    free_seen = [r["ranks"]["r"] for r in rows
                 if r["reads"] and r["level"] == 1 and r["champion"] in FREE_R_KITS]
    free_champs = sorted({r["champion"] for r in rows
                          if r["reads"] and r["level"] == 1 and r["champion"] in FREE_R_KITS})

    per_mode: dict = {}
    for r in rows:
        if not r["reads"] or not r["supported"]:
            continue
        m = per_mode.setdefault(r["mode"], {"payloads": 0, "unspent_min": None,
                                            "unspent_max": None, "out_of_range": 0,
                                            "over_cap": 0})
        m["payloads"] += 1
        u = r["unspent"]
        m["unspent_min"] = u if m["unspent_min"] is None else min(m["unspent_min"], u)
        m["unspent_max"] = u if m["unspent_max"] is None else max(m["unspent_max"], u)
        if u < 0 or u > r["level"]:
            m["out_of_range"] += 1
        if r["over_cap"]:
            m["over_cap"] += 1
    for m in per_mode.values():
        m["verdict"] = ("CONSISTENT" if m["out_of_range"] == 0 and m["over_cap"] == 0
                        else "INCONSISTENT")

    apa_rows = [grade_apa(p) for p in apa]
    apa_verdicts = {r["verdict"] for r in apa_rows}
    if not apa_rows:
        av = "NO_RESULT"
    elif "DROPS_SLOT" in apa_verdicts:
        av = "DROPS_SLOT"
    elif apa_verdicts == {"READABLE"}:
        av = "READABLE"
    else:
        av = "NO_RANK"

    return {
        "payloads": len(loaded),
        "kinds": {"allgamedata": len(agd), "apa": len(apa),
                  "other": len(loaded) - len(agd) - len(apa)},
        "synthetic": sum(1 for p, _ts, _h in loaded if _looks_synthetic(p)),
        "duplicates": len(shas) - len(set(shas)),
        "relay_ts_span_s": round(max(ts) - min(ts), 3) if len(ts) >= 2 else 0.0,
        "game_modes": sorted({r["mode"] for r in rows}),
        "ranks": {"verdict": rv, "reads": reads, "payloads": len(rows),
                  "abilityLevel_types": types},
        "self": {how: sum(1 for r in rows if r["self"] == how)
                 for how in ("exact", "folded", "none")},
        "champions": sorted({r["champion"] for r in rows if r["champion"]}),
        "free_r": {"verdict": _verdict_set(free_seen, "READS_1", "READS_0"),
                   "level1_payloads": len(free_seen), "r_ranks": free_seen,
                   "champions": free_champs, "kits": list(FREE_R_KITS)},
        "fenced": [{"champion": r["champion"], "level": r["level"], "ranks": r["ranks"]}
                   for r in rows if r["champion"] in FENCED_KITS],
        "per_mode": per_mode,
        "modes_agree": bool(per_mode) and all(
            m["verdict"] == "CONSISTENT" for m in per_mode.values()),
        "apa": {"verdict": av, "captures": len(apa_rows),
                "dropped_slots": sorted({s for r in apa_rows for s in r["dropped"]})},
    }


def render(s: dict) -> str:
    lines = [
        f"payloads={s['payloads']} kinds={s['kinds']} synthetic={s['synthetic']} "
        f"duplicates={s['duplicates']} relay_ts_span_s={s['relay_ts_span_s']}",
        f"game_modes={s['game_modes']} champions={s['champions']} self={s['self']}",
        f"ranks: {s['ranks']['verdict']} reads={s['ranks']['reads']}/"
        f"{s['ranks']['payloads']} types={s['ranks']['abilityLevel_types']}",
        f"free_r: {s['free_r']['verdict']} level1={s['free_r']['level1_payloads']} "
        f"r_ranks={s['free_r']['r_ranks']} champions={s['free_r']['champions']}",
        f"fenced: {s['fenced']}",
    ]
    for mode, m in sorted(s["per_mode"].items()):
        lines.append(f"mode {mode or '-'}: {m['verdict']} payloads={m['payloads']} "
                     f"unspent={m['unspent_min']}..{m['unspent_max']} "
                     f"out_of_range={m['out_of_range']} over_cap={m['over_cap']}")
    lines.append(f"modes_agree={s['modes_agree']}")
    lines.append(f"apa: {s['apa']['verdict']} captures={s['apa']['captures']} "
                 f"dropped_slots={s['apa']['dropped_slots']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Grade captured Live Client payloads for LX-08 (read-only).")
    ap.add_argument("path", help="a captured JSON file or a directory of them")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    p = Path(args.path)
    if not p.exists():
        print(f"no such path: {p}", file=sys.stderr)
        return 2
    loaded = load(p)
    if not loaded:
        print(f"no loadable payload at: {p}", file=sys.stderr)
        return 2
    print(json.dumps(check(loaded), indent=2, sort_keys=True) if args.json
          else render(check(loaded)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
