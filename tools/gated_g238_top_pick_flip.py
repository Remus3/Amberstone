"""gated_g238_top_pick_flip.py - read-only helper for G2-38 (PD <-> Kraken flip).

G2-38 asks, in a live game, on one level-up tick where the top two build items
sit within the incumbent band, whether the RENDERED top pick of the in-game
"Meta Build" row stays put instead of flipping (PD <-> Kraken in the original
report). Facts that shape the check (measured at source, s144 lane gated c43):

- The hysteresis lives in ``core/build_order.py`` ``_pick_top_safe``: a shown
  incumbent is kept while ``top_delta <= inc_delta * (1 + incumbent_margin)``
  and ``inc_delta > 0``; ``plan_build_order`` defaults the margin to 0.03.
- The incumbent is NOT server state. ``web/js/panels/active_match.js``
  ``_incumbentIds`` echoes the order that client last received
  (``_BUILD_ORDER.order``) back to ``POST /api/build-order``. A page reload, an
  ADR-008 asset hot reload or an overlay restart empties it, so the first plan
  after one is greedy: a flip there is NOT a hysteresis failure.
- ``/api/build-order`` returns only the CHOSEN delta per slot, never the
  runner-up, so the band (how close the top two are) cannot be read from the
  route or the panel. It needs the slot-1 ranked rows, which ``capture`` gets by
  running the production ``plan_build_order`` with a recording ``rank_fn``.
- A second client (a headless browser, a second dashboard tab) holds its OWN
  incumbent chain, so reading its DOM grades a different chain from the one on
  the operator's screen. The rendered top pick is the operator's glance at the
  overlay, recorded per tick.

Sub-commands:

  band RANK_JSON [--incumbent ID] [--margin M] [--json]
      OFFLINE. RANK_JSON is a saved slot-1 response (``{"ranked": [...]}`` or a
      bare list of rows). Prints the greedy top, the runner-up, the gap, the pick
      the production hysteresis makes for --incumbent, and whether this tick is
      IN BAND (the incumbent is eligible, is not the greedy top, and the greedy
      top beats it by no more than the margin).

  grade GLANCES_JSONL [--margin M] [--json]
      OFFLINE. One JSON object per line: ``ts`` (ISO), ``level`` (int),
      ``rendered_top`` (item id the operator SAW first among unowned items in
      the Meta Build row), ``ranked`` (the slot-1 rows captured at that tick),
      ``rows_match`` (true only when capture's re-run equals the route's plan),
      optional ``items`` (owned ids) and ``reload`` (true when the page, an
      asset hot reload or RC restarted since the previous glance). Consecutive
      glances with a level rise, the same owned items, no reload and a
      later glance with ``rows_match`` true and ``since_levelup_s`` at or past
      MIN_SETTLE_S form a graded TICK; the earlier glance's
      ``rendered_top`` is the incumbent. Verdicts:
      PASS (at least one in-band tick, every in-band tick HELD), FAIL (any
      in-band tick rendered the challenger or an unexplained item), NO_RESULT
      (no in-band tick - the 2026-07-20 outcome, tightest gap 9.02 pct).

  capture --rendered ID --since-levelup-s N
      NETWORK, compute only (GET /api/state, one POST /api/build-order on the
      running RC with the panel's own body minus the incumbent, then DS :8860
      rank calls; no RC state write, no LCU call). For the drain session only,
      never PREP. Reads the panel's inputs off /api/state as the panel does,
      takes the enemy target stats from the route's response, re-runs the
      production ``plan_build_order`` with them and a recording rank_fn, and
      prints ONE glance line (stdout; the caller redirects it to its own
      evidence file) with ``rows_match``. --since-levelup-s is the seconds
      since the overlay's HEADER level pill (the coach level) changed, as the
      drain measured it; a glance under MIN_SETTLE_S is never graded. The
      tool writes no file.

Exit 0 = PASS (grade) or success (band / capture); 3 = NO_RESULT / FAIL;
2 = input missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Restates core/build_order.py plan_build_order(incumbent_margin=0.03); pinned
# to the production default by tests/test_gated_g238_top_pick_flip.py.
DEFAULT_MARGIN = 0.03


def _pick(rows: list[dict], incumbent: Optional[str], margin: float):
    from core.build_order import _pick_top_safe
    chosen, _fam, _ex = _pick_top_safe(rows, incumbent_id=incumbent,
                                       incumbent_margin=margin)
    return chosen


def _delta(row: dict) -> float:
    # Same read as core/build_order.py _pick_top_safe.
    return float(row.get("delta", row.get("delta_dps", 0.0)) or 0.0)


def _rows(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        obj = obj.get("ranked")
    if not isinstance(obj, list):
        return []
    return [r for r in obj if isinstance(r, dict) and r.get("item_id")]


def band(rows: list[dict], incumbent: Optional[str] = None,
         margin: float = DEFAULT_MARGIN) -> dict:
    """Describe one slot-1 decision. Pure; uses the production picker."""
    rows = _rows(rows)
    greedy = _pick(rows, None, margin)
    if greedy is None:
        return {"greedy_top": None, "runner_up": None, "gap_pct": None,
                "incumbent": incumbent, "held_pick": None, "in_band": False,
                "reason": "no eligible row"}
    eligible = [r for r in rows if not r.get("shares_dead_unique")]
    others = [r for r in eligible if str(r.get("item_id")) != str(greedy.get("item_id"))]
    runner = max(others, key=_delta) if others else None
    top_d = _delta(greedy)
    gap = None
    if runner is not None and _delta(runner) > 0.0:
        gap = round((top_d - _delta(runner)) / _delta(runner) * 100.0, 3)
    held = _pick(rows, incumbent, margin) if incumbent else greedy
    in_band = False
    reason = "no incumbent"
    if incumbent:
        inc = next((r for r in eligible if str(r.get("item_id")) == str(incumbent)), None)
        if str(incumbent) == str(greedy.get("item_id")):
            reason = "incumbent is the greedy top"
        elif inc is None:
            reason = "incumbent not an eligible row"
        elif _delta(inc) <= 0.0:
            reason = "incumbent delta not positive"
        elif top_d <= _delta(inc) * (1.0 + margin):
            in_band, reason = True, "challenger within margin"
        else:
            reason = "challenger beats margin"
    return {
        "greedy_top": str(greedy.get("item_id")),
        "greedy_delta": round(top_d, 3),
        "runner_up": str(runner.get("item_id")) if runner is not None else None,
        "runner_delta": round(_delta(runner), 3) if runner is not None else None,
        "gap_pct": gap,
        "incumbent": incumbent,
        "held_pick": str(held.get("item_id")) if held is not None else None,
        "in_band": in_band,
        "reason": reason,
    }


def _ts(raw: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


def _settled(value: Any) -> bool:
    # NaN compares False against everything, so test finiteness first.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= MIN_SETTLE_S)


def grade(glances: list[dict], margin: float = DEFAULT_MARGIN) -> dict:
    """Grade a glance log. Pure."""
    bad = [i for i, g in enumerate(glances)
           if not isinstance(g, dict) or _ts(g.get("ts")) is None
           or not isinstance(g.get("level"), int) or isinstance(g.get("level"), bool)
           or not str(g.get("rendered_top") or "")]
    if bad:
        return {"verdict": "FAIL", "reasons": [f"malformed glance at line(s) {bad}"],
                "ticks": [], "in_band": 0, "held": 0, "tightest_gap_pct": None}
    seq = sorted(glances, key=lambda g: _ts(g["ts"]))
    ticks: list[dict] = []
    reasons: list[str] = []
    tightest: Optional[float] = None
    for prev, cur in zip(seq, seq[1:]):
        if cur["level"] <= prev["level"]:
            continue
        rec = {"ts": cur["ts"], "from_level": prev["level"], "to_level": cur["level"],
               "incumbent": str(prev["rendered_top"]),
               "rendered": str(cur["rendered_top"])}
        if cur.get("reload"):
            rec["skip"] = "reload since previous glance (incumbent lost)"
        elif sorted(map(str, prev.get("items") or [])) != sorted(map(str, cur.get("items") or [])):
            rec["skip"] = "owned items changed (slot alignment moved)"
        elif cur.get("rows_match") is not True:
            rec["skip"] = "rows not matched to the route's plan (re-take)"
        elif not _settled(cur.get("since_levelup_s")):
            rec["skip"] = "glance before the settle floor (panel may not have repainted)"
        if "skip" in rec:
            ticks.append(rec)
            continue
        b = band(cur.get("ranked") or [], rec["incumbent"], margin)
        rec.update({k: b[k] for k in ("greedy_top", "gap_pct", "held_pick", "in_band", "reason")})
        if b["gap_pct"] is not None:
            tightest = b["gap_pct"] if tightest is None else min(tightest, b["gap_pct"])
        if b["in_band"]:
            if rec["rendered"] == rec["incumbent"]:
                rec["outcome"] = "HELD"
            elif rec["rendered"] == b["greedy_top"]:
                rec["outcome"] = "FLIPPED"
                reasons.append(f"{cur['ts']}: in-band tick rendered the challenger "
                               f"{rec['rendered']} over incumbent {rec['incumbent']}")
            else:
                rec["outcome"] = "OTHER"
                reasons.append(f"{cur['ts']}: in-band tick rendered {rec['rendered']}, "
                               f"neither incumbent nor challenger")
        ticks.append(rec)
    in_band = [t for t in ticks if t.get("in_band")]
    held = [t for t in in_band if t.get("outcome") == "HELD"]
    if reasons:
        verdict = "FAIL"
    elif held:
        verdict = "PASS"
    else:
        verdict = "NO_RESULT"
        reasons.append("no in-band level-up tick (top two never within the margin "
                       "of the shown incumbent); stability here proves nothing")
    return {"verdict": verdict, "reasons": reasons, "ticks": ticks,
            "in_band": len(in_band), "held": len(held), "tightest_gap_pct": tightest,
            "margin": margin}


RC_BASE = "https://127.0.0.1:8888"
ROUTE_URL = RC_BASE + "/api/build-order"
STATE_URL = RC_BASE + "/api/state"
TARGET_KEYS = ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp")
# Settle floor before a glance counts, timed from the coach-level change (the
# header level pill): the route makes up to 5 engine calls (6 slots, boots
# injected without one) at timeout 2.0 s each; _maybeRefreshBuildOrder does not
# re-fire while an older POST is in flight, so the worst case is the rest of
# that call plus a full new one (2 x 10 s), then the next onState repaint (a
# coaching-file push / SSE frame, with the 2 s pollIfStale as the fallback),
# allowed 10 s. A floor for the panel's own latency, not a proven bound.
MIN_SETTLE_S = 30.0


def _ctx():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False   # loopback mkcert cert, 127.0.0.1 only
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get_state() -> dict:
    import urllib.request
    with urllib.request.urlopen(STATE_URL, timeout=10, context=_ctx()) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _post_build_order(body: dict) -> dict:
    """POST the panel's own body (no incumbent) to the running RC route.
    Compute only: the route plans and returns, it writes nothing."""
    import urllib.request
    req = urllib.request.Request(ROUTE_URL, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15, context=_ctx()) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def panel_inputs(state: dict) -> dict:
    """The Meta Build row's own inputs, read off /api/state the way the panel
    reads them (web/js/main.js: payload = st.coach, ctx.mode = st.mode_key;
    web/js/panels/active_match.js _renderAmBuildBody: champion = p.champion,
    level = parseInt(p.level) || 1, mode upper-cased or "SR";
    _amOwnedItemIds: liveclient.owned_item_ids when non-empty). The panel's
    level is the COACH payload's level, which can lag the Live Client level.
    When owned_item_ids is empty the panel falls back to allPlayers[].items
    and then the coach payload's items_display, which this tool does not
    replicate: items_source is then "none" and the glance is never graded.
    The panel's mode is main.js state.mode (health / message tag); mode_key
    is the closest /api/state read of it."""
    coach = state.get("coach") if isinstance(state.get("coach"), dict) else {}
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    champion = str(coach.get("champion") or "")
    if not champion:
        raise RuntimeError("no coach champion in /api/state (not in game?)")
    try:
        level = int(float(coach.get("level") or 0)) or 1
    except (TypeError, ValueError):
        level = 1
    mode = str(state.get("mode_key") or "").upper() or "SR"
    raw = lc.get("owned_item_ids")
    ids = [str(i).strip() for i in raw if i is not None and str(i).strip()] \
        if isinstance(raw, list) else []
    return {"champion": champion, "level": level, "mode": mode, "items": ids,
            "items_source": "owned_item_ids" if ids else "none",
            "game_time_s": lc.get("game_time_s")}


def capture(rendered: Optional[str] = None, since_levelup_s: Optional[float] = None,
            *, state_fn: Optional[Callable[[], dict]] = None,
            rank_fn: Optional[Callable] = None,
            post_fn: Optional[Callable[[dict], dict]] = None,
            now: Optional[str] = None) -> dict:
    """Record one glance: the slot-1 ranked rows behind the panel's plan.

    Inputs come from /api/state exactly as the panel reads them
    (``panel_inputs``). The enemy target stats come from the RUNNING route's
    own response (``target_stats``): in-game the route resolves them from RC's
    warm Live Client cache, which a fresh process cannot see (its cache starts
    empty and would fall back to the mode/level curve). The production planner
    is re-run with those stats and a recording rank_fn; ``rows_match`` is true
    only when the re-run's greedy order equals the route's AND the panel's items
    provably came from a non-empty owned_item_ids. ``grade`` only grades a tick
    whose glance has ``rows_match`` true and ``since_levelup_s`` at or past
    MIN_SETTLE_S. Network unless state_fn, rank_fn and post_fn are given."""
    from core.archetype_picks import canonical_champion_id, get_archetype_for
    from core.build_order import _canonical_id, plan_build_order

    if since_levelup_s is not None and (
            isinstance(since_levelup_s, bool)
            or not isinstance(since_levelup_s, (int, float))
            or not math.isfinite(since_levelup_s) or since_levelup_s < 0):
        raise ValueError("since_levelup_s must be a finite, non-negative number")
    inp = panel_inputs((state_fn or _get_state)())
    lvl = max(1, min(18, inp["level"]))
    items = inp["items"]
    # Same body the panel sends (_maybeRefreshBuildOrder), minus the incumbent.
    body = {"champion": inp["champion"], "mode": inp["mode"], "level": lvl,
            "items": list(items), "archetype": ""}
    route = (post_fn or _post_build_order)(body)
    tgt = (route or {}).get("target_stats") or {}
    if not (route or {}).get("ok") or any(k not in tgt for k in TARGET_KEYS):
        raise RuntimeError("build-order route gave no plan / target_stats")
    route_order = [str(s.get("item_id")) for s in route.get("order") or []
                   if isinstance(s, dict)]

    champ = canonical_champion_id(inp["champion"]) or inp["champion"]
    if rank_fn is None:
        from core.daemon_slayer_client import rank_for_primary_archetype as rank_fn
    calls: list[dict] = []

    def _rec(*a, **kw):
        out = rank_fn(*a, **kw)
        calls.append(out if isinstance(out, dict) else {})
        return out

    arch = (get_archetype_for(champ).get("primary") or "carry").lower()
    res = plan_build_order(
        champ, arch, level=lvl, owned_item_ids=list(items), mode=inp["mode"],
        slots=6, timeout=2.0, rank_fn=_rec,
        **{k: float(tgt[k]) for k in TARGET_KEYS},
    )
    order = [str(s.item_id) for s in res.order] if res is not None else []
    owned = {_canonical_id(i) for i in items}
    # Same pre-pick filter as plan_build_order (drops owned aliases).
    ranked = [r for r in (_rows(calls[0]) if calls else [])
              if _canonical_id(r.get("item_id")) not in owned]
    return {
        "ts": now or datetime.now().astimezone().isoformat(timespec="seconds"),
        "champion": champ, "mode": inp["mode"], "level": lvl, "items": list(items),
        "items_source": inp["items_source"], "game_time_s": inp["game_time_s"],
        "rendered_top": rendered or "",
        "since_levelup_s": since_levelup_s,
        "greedy_order": order,
        "route_order": route_order,
        "rows_match": (bool(order) and order == route_order
                       and inp["items_source"] == "owned_item_ids"),
        "target_source": str(tgt.get("source") or ""),
        "ranked": ranked,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append(None)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("band")
    pb.add_argument("rank_json")
    pb.add_argument("--incumbent")
    pb.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    pb.add_argument("--json", action="store_true")
    pg = sub.add_parser("grade")
    pg.add_argument("glances")
    pg.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    pg.add_argument("--json", action="store_true")
    pc = sub.add_parser("capture")
    pc.add_argument("--rendered", required=True)
    pc.add_argument("--since-levelup-s", type=float, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "capture":
        try:
            line = capture(a.rendered, a.since_levelup_s)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"capture failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(line, sort_keys=True))
        return 0
    try:
        if a.cmd == "band":
            data = _load_json(Path(a.rank_json))
        else:
            data = _load_jsonl(Path(a.glances))
    except (OSError, ValueError) as exc:
        print(f"unreadable input: {exc}", file=sys.stderr)
        return 2
    if a.cmd == "band":
        out = band(data, a.incumbent, a.margin)
        print(json.dumps(out, sort_keys=True) if a.json else
              f"greedy {out['greedy_top']} runner {out['runner_up']} gap_pct "
              f"{out['gap_pct']} held {out['held_pick']} in_band {out['in_band']} "
              f"({out['reason']})")
        return 0
    out = grade(data, a.margin)
    if a.json:
        print(json.dumps(out, sort_keys=True))
    else:
        print(f"{out['verdict']} in_band={out['in_band']} held={out['held']} "
              f"tightest_gap_pct={out['tightest_gap_pct']}")
        for r in out["reasons"]:
            print(f"  - {r}")
    return 0 if out["verdict"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
