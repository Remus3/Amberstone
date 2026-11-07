"""gated_g416_counter_chips.py - read-only grader for G4-16 (counter-hint chips).

G4-16 asks for the in-game eyeball of the BUILD-pane COUNTER chips. Three of the
five were seen lit on 2026-07-20 (C3 fed, C5 pen_type, C6 tenacity); C2 antiheal
and C4 hp_vs_pen are still owed. The chips are painted by
``web/js/panels/active_match.js`` ``_counterChip`` into ``.counter-strip`` inside
the BUILD pane ``#am-build-body``, from the ``counter_hints`` of
``POST /api/build-plan`` (``dashboard/routes_build_plan.py``, projected by
``core/build_planner/situational.py`` ``counter_build_hints``).

Facts measured at source (s144 lane gated c73) that shape the check:

- The CLIENT builds the body it posts (``_buildPlanPostBody``): ``champion`` and
  ``level`` from the coach payload (``/api/state`` ``coach``), ``items`` from
  ``liveclient.owned_item_ids`` (else my roster row's items below slot 6),
  ``enemies`` / ``enemy_items`` / ``enemy_scores`` / ``enemy_levels`` from every
  ``allPlayers`` row off my team (nameless rows skipped), ``ally_items`` from
  every row ON my team, MY OWN ROW INCLUDED. When ``_resolveMyTeam`` finds no
  activePlayer name match it returns null: then all 10 players are posted as
  enemies and ``ally_items`` is empty, so my own sustain and pen items feed C2 and
  C4. This grader names that (ROSTER_BAD) before it grades any chip.
- counter_hints do not depend on the champion or the mode (both only feed the
  DS plan), only on the roster, the items, the scores, the levels and ``level``.
  An empty champion answers ``no_champion`` with no hints at all.
- C2 is warranted at ``heal_sources >= 2`` (curated sustain champions plus
  distinct enemy heal items, ``core/heal_threat.py`` ``count_heal_sources``) and
  only while no MY-TEAM item applies Grievous Wounds (``ally_has_antiheal``).
  While ``_resolveMyTeam`` resolves my team, my own items ride in
  ``ally_items``, and every BASE-id antiheal item the chip's ``satisfied`` test
  knows is also in the Grievous set, so the C2 chip does not paint in its
  satisfied (``--ok``) state: buying the counter makes the chip VANISH. ``--ok``
  stays reachable when the team is unresolved (``ally_items`` empty while
  ``items`` still holds my Grievous item; refused here as ROSTER_BAD) or if the
  feed ever reports a 22-prefixed alias id (``_ANTIHEAL_NAMES`` matches those by
  name, the Grievous set holds base ids only). A vanished C2 chip with
  ``heal_sources >= 2`` and a my-team Grievous item is the dedup case this
  grader reports as ``antiheal_dedup``, not a failure.
- C4 is warranted at ``enemy_pen >= 0.5`` (two or more enemy lethality / percent
  pen items, saturating at 4) AND only when MY build already holds armor or MR;
  ``satisfied`` = my total item HP >= 300.
- The pane repaints only while the LCU phase is InProgress: off it,
  ``renderActiveMatch`` returns at the CALL pane, before the BUILD pane, so the
  COUNTER row keeps its last paint after the game ends. The fetch fires at once
  on a roster / item / score key change (unless one is in flight), re-fires
  every 4 s with no change, and lands on the next render, so a capture taken
  right after a purchase can be one fetch behind.
- ``_shouldRetainBuild``: while the Daemon Slayer, Meta and Ultimate rows are
  all empty (DS down or empty) and the pane already holds a paint,
  ``_renderAmBuildBody`` returns before the COUNTER row, so hints that land
  after the first paint never show. The snippet counts the filled row items
  (``build_items``); expected hints, no COUNTER row and zero items grade
  RETAINED, not a mismatch. That covers a freeze over an empty-row or
  static-placeholder pane only:
  a freeze over an earlier FILLED paint (every row cache later overwritten by an
  ok-but-empty reply) still shows filled rows and grades RENDER_MISMATCH, so the
  READY block's one re-capture uses a freshly opened page.
- The BUILD pane's repaint signature keys the hints on ``criterion:satisfied``
  only, so a hint whose DETAIL changes alone (C2's heal-source count after an
  enemy heal-item buy) may not repaint until another signature input moves.
  Chips that agree on label, ok and high but not on detail grade DETAIL_LAG.
- The in-process path cannot see the route's outer fail-soft (a raise in the
  plan tick answers ok:false with no hints, and the client then paints none);
  the optional served cross-check (--plan) does, as PLAN_ERROR.

Sub-commands (READ-ONLY: reads the files named; no network, no write, no tick):

  snippet
      Print the JS expression a HEADLESS Chromium page on the dashboard evaluates
      to capture the COUNTER row as JSON (save it as the --dom file).
  body --state FILE
      Print the /api/build-plan body the client would post for that state (for
      the optional served cross-check).
  grade --state FILE --dom FILE [--plan FILE] [--state-ts EPOCH] [--json]
      --state is a saved ``/api/state`` body; --plan a saved ``POST
      /api/build-plan`` reply for the ``body`` output (else the expected hints
      are computed in-process through the route's own helpers, and the output
      says so). Verdicts and exit codes:
        RENDER_MATCH (0)       every expected chip painted in order with its
                               label, detail, ok / gap and high state, and at
                               least one owed case (antiheal, hp_vs_pen,
                               antiheal_dedup) holds; the operator eyeball is
                               STILL owed
        ROSTER_BAD (3)         team unresolved, enemy count not 5, no coach
                               champion or not my row's, or client and server
                               rosters disagree
        PANE_ABSENT (3)        ``#am-build-body`` is not in the captured DOM
        RENDER_MISMATCH (3)    the painted chips differ from the expected list
        DETAIL_LAG (3)         same chips, label, ok and high, but a detail text
                               differs (the repaint signature ignores detail)
        PLAN_ERROR (3)         the --plan reply is ok:false
        NO_GAME (4)            no roster, mode_key not sr / aram, or an LCU phase
                               other than exactly InProgress (the client keeps
                               the last paint off it, an empty phase included)
        STALE_DOM (4)          DOM and state captures more than MAX_SKEW_S apart
        RETAINED (4)           hints expected, no COUNTER row, BUILD rows empty:
                               the retain guard froze the pane (fix DS first)
        NO_HINT_CONSISTENT (4) no hint expected and no COUNTER row painted
        NO_OWED_CHIP (4)       the render matches but this comp warrants neither
                               owed chip (re-sample in a sustain / pen comp)

RENDER_MATCH never ticks G4-16: render == compute is the SUBSTITUTION half. Only
the operator's overlay read of the chip plus a yes / no that it is right for the
comp on screen answers the row. Prints champion names and item ids only, never a
player name, game id or player id.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g416_counter_chips"
PANE_ID = "am-build-body"
MAX_SKEW_S = 5.0
SR_ENEMIES = 5
LIVE_MODES = ("sr", "aram")
OWED = ("antiheal", "hp_vs_pen")
EXIT = {"RENDER_MATCH": 0, "ROSTER_BAD": 3, "PANE_ABSENT": 3,
        "RENDER_MISMATCH": 3, "DETAIL_LAG": 3, "PLAN_ERROR": 3}

DOM_SNIPPET = (
    "(() => { const b = document.getElementById('" + PANE_ID + "');"
    " const ts = Date.now() / 1000;"
    " if (!b) return {ts: ts, present: false};"
    " const vis = (e) => { if (!e) return false;"
    " const r = e.getBoundingClientRect();"
    " return getComputedStyle(e).display !== 'none' && r.width > 0"
    " && r.height > 0 && e.offsetParent !== null; };"
    " const t = (c, s) => { const e = c.querySelector(s);"
    " return e ? e.textContent.trim() : ''; };"
    " const s = b.querySelector('.counter-strip');"
    " const chips = s ? Array.from(s.querySelectorAll('.counter-chip')).map((c) =>"
    " ({label: t(c, '.counter-chip-label'), detail: t(c, '.counter-chip-detail'),"
    " ok: c.classList.contains('counter-chip--ok'),"
    " high: c.classList.contains('counter-chip--high'), visible: vis(c)})) : [];"
    " return {ts: ts, present: true, strip: !!s, strip_visible: vis(s),"
    " build_items: b.querySelectorAll("
    "'.bm-module .bm-strip[data-rc-zone] > *').length,"
    " chips: chips}; })()"
)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split())


def _key(name: Any) -> str:
    """Name-form-blind compare key ("Kai'Sa" == "KaiSa" == "kaisa")."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _me_name(lc: dict) -> str:
    ap = lc.get("activePlayer") if isinstance(lc.get("activePlayer"), dict) else {}
    return str(ap.get("summonerName") or ap.get("riotIdGameName") or "")


def _is_me(pl: dict, me: str) -> bool:
    rid = str(pl.get("riotIdGameName") or pl.get("summonerName") or "")
    return rid == me or me.startswith(rid + "#") or rid == me.split("#", 1)[0]


def _me_row(lc: dict) -> Optional[dict]:
    """Port of active_match.js _resolveMyTeam's match: the first row naming me."""
    me = _me_name(lc)
    if not me:
        return None
    for pl in lc.get("allPlayers") or []:
        if isinstance(pl, dict) and _is_me(pl, me):
            return pl
    return None


def _item_ids(pl: dict, below_slot_6: bool = False) -> list:
    out = []
    for it in pl.get("items") if isinstance(pl.get("items"), list) else []:
        if not isinstance(it, dict):
            continue
        if below_slot_6 and isinstance(it.get("slot"), int) and it["slot"] >= 6:
            continue
        iid = str(it.get("itemID") or it.get("itemId") or "")
        if iid and iid != "0":
            out.append(iid)
    return out


def _int(v: Any) -> int:
    """active_match.js _bpInt: a finite number truncated and floored at 0."""
    if isinstance(v, bool):
        return int(v)
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    return max(0, math.trunc(n)) if math.isfinite(n) else 0


def _coach(state: dict) -> dict:
    """``(st.coach || st)`` (main.js coachPayload); any object is truthy in JS,
    an empty one included."""
    coach = state.get("coach")
    return coach if isinstance(coach, dict) else state


def client_body(state: dict) -> dict:
    """The /api/build-plan body _renderAmBuildBody posts for this state."""
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    p = _coach(state)
    roster = [pl for pl in lc.get("allPlayers") or [] if isinstance(pl, dict)]
    row = _me_row(lc)
    team = (row or {}).get("team") or None
    raw_owned = lc.get("owned_item_ids")
    owned = [s for s in (str("" if i is None else i).strip()
                         for i in (raw_owned if isinstance(raw_owned, list) else []))
             if s]
    if not owned and row:
        owned = _item_ids(row, below_slot_6=True)
    try:
        level = int(float(p.get("level") or 0)) or 1
    except (TypeError, ValueError, OverflowError):
        level = 1
    enemies, enemy_items, scores, levels, ally_items = [], [], [], [], []
    for pl in roster:
        if team and pl.get("team") == team:
            ally_items.extend(_item_ids(pl))
            continue
        name = str(pl.get("championName") or pl.get("rawChampionName") or "")
        if not name:
            continue
        enemies.append(name)
        enemy_items.append(_item_ids(pl))
        sc = pl.get("scores") if isinstance(pl.get("scores"), dict) else {}
        scores.append({k: _int(sc.get(k)) for k in ("kills", "deaths", "assists")})
        levels.append(_int(pl.get("level")))
    body = {"champion": str(p.get("champion") or ""),
            "mode": str(state.get("mode") or state.get("mode_key") or "").upper(),
            "level": level, "items": owned, "enemies": enemies,
            "enemy_items": enemy_items, "ally_items": ally_items}
    if scores:
        body["enemy_scores"] = scores
        body["enemy_levels"] = levels
    return {"team": team, "my_champion": str((row or {}).get("championName") or ""),
            "body": body}


def roster_problems(lc: dict, posted: dict) -> list:
    body = posted["body"]
    out = []
    if not body["champion"]:
        out.append("no coach champion: the route answers no_champion, no hints")
    elif _key(body["champion"]) != _key(posted["my_champion"]):
        out.append("posted coach champion != my roster row champion")
    if not posted["team"]:
        out.append("team unresolved: the client would post all players as enemies")
    if len(body["enemies"]) != SR_ENEMIES:
        out.append(f"enemy count {len(body['enemies'])} != {SR_ENEMIES}")
    served = lc.get("enemy_team")
    if isinstance(served, list) and sorted(map(str, served)) != sorted(body["enemies"]):
        out.append("client roster != server enemy_team")
    return out


def expected_in_process(body: dict) -> list:
    """The route's counter_hints steps (routes_build_plan._serve_build_plan),
    through its own coerce / profile / hint helpers. Pinned equal to the full
    route's reply by tests/test_gated_g416_counter_chips.py."""
    from core.build_planner.fed_threat import assess_fed_threat
    from core.build_planner.situational import AllyState
    from core.cc_threat import compute_cc_score
    from core.heal_threat import ally_has_antiheal, count_heal_sources
    from dashboard import routes_build_plan as r
    if not str(body.get("champion") or "").strip():
        return []
    raw_level = body.get("level")
    try:
        level = (11 if isinstance(raw_level, bool)
                 else max(1, min(18, int(raw_level or 11))))
    except (TypeError, ValueError, OverflowError):
        level = 11
    raw_items = body.get("items")
    owned = ([str(i) for i in raw_items if str(i).strip()]
             if isinstance(raw_items, list) else [])
    raw_enemies = body.get("enemies")
    enemies = ([str(x) for x in raw_enemies if x]
               if isinstance(raw_enemies, list) else [])
    enemy_items = r._coerce_enemy_items(body.get("enemy_items"))
    ally_items = r._coerce_ally_items(body.get("ally_items"))
    enemy_scores = r._coerce_enemy_scores(body.get("enemy_scores"))
    enemy_levels = r._coerce_enemy_levels(body.get("enemy_levels"))
    enemy_profile = r._resolve_enemy_profile(enemies, level)
    flat = [i for pl in (enemy_items or []) for i in pl]
    heal_sources = count_heal_sources(enemies, flat)
    cc_score = compute_cc_score(enemies)
    fed_info = assess_fed_threat(enemies, enemy_items, enemy_scores,
                                 enemy_levels, owned, level)
    ally_state = AllyState(has_antiheal=ally_has_antiheal(ally_items))
    hint_profile = (
        r._resolve_enemy_profile(enemies, level, enemy_items=enemy_items,
                                 heal_sources=heal_sources, cc_score=cc_score,
                                 fed=fed_info is not None)
        if (enemy_items or heal_sources or cc_score or fed_info)
        else enemy_profile)
    return r._enrich_fed_hint(
        r._resolve_counter_hints(hint_profile, owned, ally_state), fed_info)


def comp_inputs(body: dict) -> dict:
    """The C2 / C4 gate inputs for the operator's yes / no (ids and counts)."""
    from core.build_planner.situational import classify_item
    from core.heal_threat import ally_has_antiheal, count_heal_sources
    flat = [str(i) for pl in body.get("enemy_items") or [] for i in pl or []]
    pen = [i for i in flat if (p := classify_item(i)).is_lethality or p.is_percent_armor_pen
           or p.is_percent_magic_pen]
    mine = [classify_item(i) for i in body.get("items") or []]
    return {"heal_sources": count_heal_sources(body.get("enemies") or [], flat),
            "ally_has_antiheal": ally_has_antiheal(body.get("ally_items") or []),
            "enemy_pen_item_ids": pen,
            "my_has_resist": any(p.is_armor or p.is_magic_resist for p in mine),
            "my_item_hp": sum(p.hp for p in mine)}


def _want(h: dict) -> dict:
    return {"label": _norm(h.get("label")), "detail": _norm(h.get("detail")),
            "ok": bool(h.get("satisfied")), "high": h.get("severity") == "high"}


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def grade(state: dict, dom: dict, state_ts: float,
          expected_fn: Callable[[dict], Optional[list]]) -> dict:
    """Grade one state + DOM pair. ``expected_fn`` maps a body to the hint list
    (None = the served plan was ok:false)."""
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    lcu = state.get("lcu") if isinstance(state.get("lcu"), dict) else {}
    ctx = {"tool": TOOL, "mode_key": state.get("mode_key"),
           "lcu_phase": lcu.get("phase"), "game_time_s": lc.get("game_time_s"),
           "state_ts": state_ts, "dom_ts": dom.get("ts")}

    def out(verdict: str, **kw) -> dict:
        return {"verdict": verdict, **ctx, **kw}

    # renderActiveMatch: isLive = (phase === "InProgress"); anything else keeps
    # the last paint, so only an exact InProgress capture is graded.
    if lcu.get("phase") != "InProgress":
        return out("NO_GAME")
    if not lc or not lc.get("allPlayers") \
            or str(state.get("mode_key") or "") not in LIVE_MODES:
        return out("NO_GAME")
    if not _finite(dom.get("ts")) or not _finite(state_ts) \
            or abs(float(dom["ts"]) - float(state_ts)) > MAX_SKEW_S:
        return out("STALE_DOM")
    posted = client_body(state)
    body = posted["body"]
    ctx.update(my_champion=posted["my_champion"], posted_champion=body["champion"],
               enemies=body["enemies"])
    probs = roster_problems(lc, posted)
    if probs:
        return out("ROSTER_BAD", problems=probs)
    if not dom.get("present"):
        return out("PANE_ABSENT")
    hints = expected_fn(body)
    if hints is None:
        return out("PLAN_ERROR")
    inputs = comp_inputs(body)
    want = [_want(h) for h in hints if isinstance(h, dict)]
    got = [{"label": _norm(c.get("label")), "detail": _norm(c.get("detail")),
            "ok": bool(c.get("ok")), "high": bool(c.get("high"))}
           for c in dom.get("chips") or [] if isinstance(c, dict)]
    criteria = [str(h.get("criterion") or "") for h in hints if isinstance(h, dict)]
    ctx.update(inputs=inputs, expected=want, painted=got, criteria=criteria)
    # _shouldRetainBuild: with the Daemon Slayer / Meta / Ultimate rows all
    # empty and the pane already painted, _renderAmBuildBody returns before the
    # COUNTER row, so hints that land after the first paint never show.
    if want and not dom.get("strip") and dom.get("build_items") == 0:
        return out("RETAINED", problems=["BUILD rows empty: the pane is frozen "
                                         "by the retain guard, no evidence"])
    if not want:
        if dom.get("strip") or got:
            return out("RENDER_MISMATCH", problems=["COUNTER row painted, no hint expected"])
        return out("NO_HINT_CONSISTENT")
    probs = []
    if not dom.get("strip_visible"):
        probs.append("COUNTER row not visible")
    hidden = [c.get("label") for c in dom.get("chips") or []
              if isinstance(c, dict) and not c.get("visible")]
    if hidden:
        probs.append(f"chip(s) not visible: {hidden}")
    strip_d = [{k: v for k, v in c.items() if k != "detail"} for c in got]
    want_d = [{k: v for k, v in c.items() if k != "detail"} for c in want]
    if not probs and got != want and strip_d == want_d:
        return out("DETAIL_LAG", problems=["detail text differs; label, ok and high match"])
    if got != want:
        probs.append("painted chips != expected chips")
    if probs:
        return out("RENDER_MISMATCH", problems=probs)
    owed = [c for c in OWED if c in criteria]
    if "antiheal" not in criteria and inputs["heal_sources"] >= 2 \
            and inputs["ally_has_antiheal"]:
        owed.append("antiheal_dedup")
    if not owed:
        return out("NO_OWED_CHIP")
    return out("RENDER_MATCH", owed_cases=owed, operator_eyeball_owed=True)


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{Path(path).name}: not a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    b = sub.add_parser("body")
    b.add_argument("--state", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--state", required=True)
    g.add_argument("--dom", required=True)
    g.add_argument("--plan")
    g.add_argument("--state-ts", type=float)
    g.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    if args.cmd == "snippet":
        print(DOM_SNIPPET)
        return 0
    if args.cmd == "body":
        print(json.dumps(client_body(_load(args.state))["body"]))
        return 0
    state, dom = _load(args.state), _load(args.dom)
    ts = args.state_ts if args.state_ts is not None else Path(args.state).stat().st_mtime
    if args.plan:
        plan = _load(args.plan)
        source = "plan"

        def fn(_b: dict) -> Optional[list]:
            if not plan.get("ok"):
                return None
            ch = plan.get("counter_hints")
            return ch if isinstance(ch, list) else []
    else:
        source, fn = "in_process", expected_in_process
    result = grade(state, dom, ts, fn)
    result["expected_source"] = source
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
