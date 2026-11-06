"""gated_g418_jhin_lethality.py - read-only grader for G4-18 (Jhin lethality render).

G4-18 asks for the in-game eyeball that Jhin's lethality-crit core (LEDGER 870,
merge ``c904ddae``: AS-lock ENGINE 1.204.0 plus the fight_length 0.5 burst blend
ENGINE 1.205.0) RENDERS on the overlay BUILD panel in a real Jhin game. The Boots
of Swiftness half was live-confirmed by the operator; the lethality half is open.

Facts measured at source (s144 lane gated c75) that shape the check:

- The three painted rows of ``#am-build-body`` are read exactly as G4-17 reads
  them (``tools/gated_g417_onhit_render.py``: "Daemon Slayer" ``.bm-live`` =
  ``POST /api/ds-preview`` ``ranked``; "Meta Build" ``.bm-meta`` and "Ultimate
  Build" ``.bm-ult`` = ``POST /api/build-order`` ``order``). This tool reuses that
  DOM snippet, the client-body port and the Daemon Slayer row derivation (family
  dedupe, 7 cap), so the two graders cannot drift apart on the row reader.
- The burst blend is applied only on the CARRY branch of
  ``core.daemon_slayer_client.rank_for_primary_archetype``
  (``champion_fight_length(champion)``, ``core/ds_champion_fight_length.py``
  ``"jhin": 0.5``), which serves scorer ``dps``. Jhin's default primary is
  ``carry``, but a persisted operator pick in gitignored
  ``data/cs_archetype_picks.json`` wins, so only a served scorer ``dps`` proves
  the branch that carries the blend ran (``SCORER_DRIFT`` otherwise).
- "Lethality item" = an item whose engine record carries ``lethality > 0``
  (``agents/daemon_slayer/_effects_data.py`` ``ITEM_EFFECTS``): the same field the
  engine scores, read-only, so a patch that moves an item in or out of the class
  moves it here too. The core NAMED by the shipped claim
  (``core/ds_champion_fight_length.py`` docstring: Infinity Edge, Serylda's,
  The Collector, Hubris, Axiom Arc, Youmuu's) is reported as context, never
  graded: Infinity Edge and Serylda's carry no lethality.
- An owned lethality item is not in the preview's ranked rows (it ranks open
  slots), so the Daemon Slayer row is compared on NON-owned tiles only.
- The Meta / Ultimate requests echo an ``incumbent`` that a curl cannot
  reproduce, so their comparison is ADVISORY, as in G4-17.

Sub-commands (READ-ONLY: reads the files named; no network, no write, no tick):

  snippet                 the G4-17 DOM snippet (save its JSON as the --dom file)
  bodies --state FILE     the three request bodies the client posts
  grade --state FILE --dom FILE --preview FILE [--order FILE] [--ultimate FILE]
        [--state-ts EPOCH] [--json]
      Verdicts and exit codes:
        RENDER_MATCH (0)        scorer dps served, the Daemon Slayer row paints
                                exactly the preview's non-owned lethality items
                                in the shown 7, every painted lethality tile is
                                visible and unclipped, and at least one row
                                paints one; the operator eyeball is STILL owed
        ROSTER_BAD (3)          no coach champion, or not my roster row's
        UNMAPPED (3)            Jhin no longer has a fight_length (the row's
                                premise is gone: re-read LEDGER 870 first)
        PANE_ABSENT (3)         ``#am-build-body`` is not in the captured DOM
        PLAN_ERROR (3)          a supplied reply is ok:false
        SCORER_DRIFT (3)        a supplied reply's scorer is not ``dps``
        RENDER_MISMATCH (3)     the Daemon Slayer row's lethality set differs
                                from the preview's, or a painted lethality tile
                                is hidden or clipped
        PLAN_NO_LETHALITY (3)   no reply ranks a lethality item in its shown 7
                                and no row paints one (a DS question at this
                                state, not a render defect)
        LETHALITY_DARK (3)      no row paints one though a reply ranks one
        NO_GAME (4)             LCU phase not exactly InProgress, empty
                                liveclient, or mode_key not sr / aram
        STALE_DOM (4)           DOM and state captures more than MAX_SKEW_S apart
        NOT_JHIN (4)            the coach champion is not Jhin
        FULL_BUILD (4)          the preview answered build_complete
        EMPTY_ROWS (4)          all three rows empty (DS down or not landed)

RENDER_MATCH never ticks G4-18: render == compute is the SUBSTITUTION half, and a
headless dashboard page is not the Electron overlay widget (``w-build``). Only the
operator's overlay read of the lethality icons answers the row. Prints champion
names and item ids only, never a player name, game id or player id.
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

from tools.gated_g417_onhit_render import (  # noqa: E402
    DOM_SNIPPET,
    LIVE_MODES,
    MAX_SKEW_S,
    ROWS,
    SLOT_CAP,
    _expected_order,
    _finite,
    _key,
    _load,
    _me_row,
    canonical,
    client_bodies,
    expected_live,
)

TOOL = "gated_g418_jhin_lethality"
CHAMPION = "Jhin"
SCORER = "dps"
SWIFTNESS_ID = "3009"
RUNAANS_ID = "3085"
# The core named by the shipped claim (core/ds_champion_fight_length.py
# docstring), reported as context only: IE 3031 and Serylda's 6694 carry no
# lethality, so they are not part of the graded set.
NAMED_CORE = {"3031": "Infinity Edge", "6694": "Serylda's Grudge",
              "6676": "The Collector", "6697": "Hubris", "6696": "Axiom Arc",
              "3142": "Youmuu's Ghostblade"}
EXIT = {"RENDER_MATCH": 0, "ROSTER_BAD": 3, "UNMAPPED": 3, "PANE_ABSENT": 3,
        "PLAN_ERROR": 3, "SCORER_DRIFT": 3, "RENDER_MISMATCH": 3,
        "PLAN_NO_LETHALITY": 3, "LETHALITY_DARK": 3}


def lethality_ids() -> dict:
    """{item id: name} for every engine record with lethality > 0 (read-only)."""
    from agents.daemon_slayer._effects_data import ITEM_EFFECTS
    return {str(k): str(getattr(v, "name", "") or "") for k, v in ITEM_EFFECTS.items()
            if (getattr(v, "lethality", 0.0) or 0.0) > 0}


def _tile_id(item: dict, by_name: dict) -> str:
    """A tile's item id; a fallback tile (no icon) is resolved by its name."""
    return str(item.get("id") or "") or by_name.get(_key(item.get("name")), "")


def fight_length(champion: str) -> Optional[float]:
    from core.ds_champion_fight_length import champion_fight_length
    return champion_fight_length(champion)


def _leth(ids: Optional[list], leth: dict) -> Optional[list]:
    if ids is None:
        return None
    return [i for i in ids if i in leth]


def grade(state: dict, dom: dict, state_ts: float, preview: dict,
          order: Optional[dict] = None, ultimate: Optional[dict] = None,
          leth: Optional[dict] = None,
          fl: Any = "resolve") -> dict:
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    lcu = state.get("lcu") if isinstance(state.get("lcu"), dict) else {}
    ctx: dict = {"tool": TOOL, "mode_key": state.get("mode_key"),
                 "lcu_phase": lcu.get("phase"), "game_time_s": lc.get("game_time_s"),
                 "state_ts": state_ts, "dom_ts": dom.get("ts")}

    def out(verdict: str, **kw) -> dict:
        return {"verdict": verdict, **ctx, **kw}

    if lcu.get("phase") != "InProgress" or not lc \
            or str(state.get("mode_key") or "") not in LIVE_MODES:
        return out("NO_GAME")
    if not _finite(dom.get("ts")) or not _finite(state_ts) \
            or abs(float(dom["ts"]) - float(state_ts)) > MAX_SKEW_S:
        return out("STALE_DOM")
    bodies = client_bodies(state)
    champion = bodies["ds_preview"]["champion"]
    row = _me_row(lc)
    ctx.update(posted_champion=champion,
               my_champion=str((row or {}).get("championName") or ""))
    if not champion:
        return out("ROSTER_BAD", problems=["no coach champion"])
    if row is not None and _key(row.get("championName")) != _key(champion):
        return out("ROSTER_BAD", problems=["coach champion != my roster row champion"])
    canon = canonical(champion)
    ctx["canonical"] = canon
    if _key(canon) != _key(CHAMPION):
        return out("NOT_JHIN")
    fl_val = fight_length(canon) if fl == "resolve" else fl
    ctx["fight_length"] = fl_val
    if fl_val is None:
        return out("UNMAPPED", problems=["champion_fight_length('Jhin') is None"])
    if not dom.get("present"):
        return out("PANE_ABSENT")
    replies = {"ds_preview": preview, "build_order": order, "ultimate": ultimate}
    bad = [k for k, v in replies.items() if v is not None and not v.get("ok")]
    if bad:
        return out("PLAN_ERROR", problems=[f"{k} reply ok:false" for k in bad])
    if preview.get("reason") == "build_complete":
        return out("FULL_BUILD")
    ctx["scorers"] = {k: v.get("scorer") for k, v in replies.items() if v is not None}
    drift = {k: s for k, s in ctx["scorers"].items() if s != SCORER}
    if drift:
        return out("SCORER_DRIFT", problems=[f"{k} scorer {s!r} != {SCORER!r}"
                                             for k, s in drift.items()])
    leth = lethality_ids() if leth is None else dict(leth)
    # Shortest id per name: the SR id, not a mode-prefixed variant (226676).
    by_name: dict = {}
    for i, n in sorted(leth.items(), key=lambda kv: (len(kv[0]), kv[0])):
        by_name.setdefault(_key(n), i)
    painted = {v: [] for v in ROWS}
    for r in dom.get("rows") or []:
        if isinstance(r, dict) and r.get("variant") in painted:
            painted[r["variant"]] = [i for i in r.get("items") or [] if isinstance(i, dict)]
    ctx["painted"] = {v: [str(i.get("id") or i.get("name") or "") for i in items]
                      for v, items in painted.items()}
    if not any(painted.values()):
        return out("EMPTY_ROWS", problems=["all three build rows empty: no evidence"])
    expect = {"bm-live": expected_live(preview, order, ultimate),
              "bm-meta": _expected_order(order),
              "bm-ult": _expected_order(ultimate)}
    ctx["expected"] = {k: v for k, v in expect.items() if v is not None}
    want = {k: _leth(v, leth) for k, v in expect.items()}
    got = {k: [dict(i, id=_tile_id(i, by_name)) for i in items
               if _tile_id(i, by_name) in leth]
           for k, items in painted.items()}
    ctx["lethality_painted"] = {k: [str(i.get("id")) for i in v] for k, v in got.items()}
    ctx["lethality_expected"] = {k: v for k, v in want.items() if v is not None}
    shown = {str(i.get("id") or "") for items in painted.values() for i in items}
    ctx["named_core_painted"] = sorted(n for i, n in NAMED_CORE.items() if i in shown)
    ctx["swiftness_rows"] = [k for k in ROWS
                             if any(str(i.get("id")) == SWIFTNESS_ID for i in painted[k])]
    live = expect["bm-live"]
    advisory = []
    if RUNAANS_ID in live and want["bm-live"] \
            and live.index(RUNAANS_ID) < min(live.index(i) for i in want["bm-live"]):
        advisory.append("Daemon Slayer preview ranks Runaan's above every lethality "
                        "item (the shipped claim puts it below the core)")
    for k in ("bm-meta", "bm-ult"):
        if want[k] is not None and set(want[k]) != {str(i.get("id")) for i in got[k]}:
            advisory.append(f"{k}: reply lethality {sorted(want[k])} != painted "
                            f"{sorted(str(i.get('id')) for i in got[k])} "
                            "(incumbent hysteresis or owned tiles)")
    ctx["advisory"] = advisory
    rows_with = [k for k in ROWS if got[k]]
    ctx["rows_with_lethality"] = rows_with
    if not rows_with:
        if not any(want[k] for k in ROWS if want[k] is not None):
            return out("PLAN_NO_LETHALITY")
        return out("LETHALITY_DARK")
    probs = []
    live_painted = {str(i.get("id")) for i in got["bm-live"] if not i.get("owned")}
    if live_painted != set(want["bm-live"]):
        probs.append(f"Daemon Slayer row: preview lethality in the shown {SLOT_CAP} "
                     f"{sorted(want['bm-live'])}, row paints {sorted(live_painted)}")
    for k in rows_with:
        for i in got[k]:
            if not i.get("visible") or i.get("clipped"):
                probs.append(f"{k}: lethality {i.get('id')} painted but hidden or clipped")
    if probs:
        return out("RENDER_MISMATCH", problems=probs)
    return out("RENDER_MATCH", operator_eyeball_owed=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    b = sub.add_parser("bodies")
    b.add_argument("--state", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--state", required=True)
    g.add_argument("--dom", required=True)
    g.add_argument("--preview", required=True)
    g.add_argument("--order")
    g.add_argument("--ultimate")
    g.add_argument("--state-ts", type=float)
    g.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    if args.cmd == "snippet":
        print(DOM_SNIPPET)
        return 0
    if args.cmd == "bodies":
        print(json.dumps(client_bodies(_load(args.state))))
        return 0
    state, dom, preview = _load(args.state), _load(args.dom), _load(args.preview)
    order = _load(args.order) if args.order else None
    ult = _load(args.ultimate) if args.ultimate else None
    ts = args.state_ts if args.state_ts is not None else Path(args.state).stat().st_mtime
    result = grade(state, dom, ts, preview, order, ult)
    print(json.dumps(result, indent=2 if args.json else None))
    return EXIT.get(result["verdict"], 4)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
