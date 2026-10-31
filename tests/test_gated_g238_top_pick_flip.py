"""Tests for tools/gated_g238_top_pick_flip.py (G2-38 PREP, s144 lane gated c43).

Offline only: no DS call, no RC call, no file write outside tmp_path. The
``capture`` path runs the production planner with an injected rank_fn and an
explicit target dict so it never reaches the network.
"""
from __future__ import annotations

import inspect
import json
import random
import re
from pathlib import Path

import pytest

from core import build_order
from core.build_order import _pick_top_safe, plan_build_order
from tools import gated_g238_top_pick_flip as g

REPO = Path(__file__).resolve().parent.parent
PD, KRAKEN, IE = "3046", "6672", "3031"


def _row(item_id, delta, dead=False):
    return {"item_id": item_id, "item_name": item_id, "delta": delta, "gold": 3000,
            "shares_dead_unique": dead, "dead_unique_key": "k" if dead else "",
            "unique_passive_key": ""}


def _glance(ts, level, rendered, ranked, **extra):
    d = {"ts": ts, "level": level, "rendered_top": rendered, "ranked": ranked,
         "rows_match": True, "since_levelup_s": 35.0}
    d.update(extra)
    return d


# -- pins to production -------------------------------------------------------

def test_default_margin_matches_production_defaults():
    assert inspect.signature(plan_build_order).parameters["incumbent_margin"].default \
        == g.DEFAULT_MARGIN
    assert inspect.signature(_pick_top_safe).parameters["incumbent_margin"].default \
        == g.DEFAULT_MARGIN


def test_route_returns_only_the_chosen_delta_per_slot():
    # The band cannot be read off /api/build-order: a step carries no runner-up.
    step = build_order.BuildStep(slot=1, item_id=PD, item_name="PD", delta=1.0, gold=1,
                                 scorer="dps", unit="dps", excluded_family="",
                                 excluded_example="", locked_family="")
    keys = set(step.to_dict())
    assert not any(re.search(r"runner|second|alt|ranked", k) for k in keys), keys


def test_incumbent_is_client_echo_not_server_state():
    js = (REPO / "web/js/panels/active_match.js").read_text(encoding="utf-8")
    assert "function _incumbentIds(store, champion)" in js
    assert "_boBody.incumbent = _inc" in js
    assert '"Meta Build":     "bm-meta"' in js
    route = (REPO / "dashboard/routes_state.py").read_text(encoding="utf-8")
    assert 'payload.get("incumbent")' in route


# -- band ---------------------------------------------------------------------

def test_band_in_band_keeps_incumbent():
    rows = [_row(KRAKEN, 60.0), _row(PD, 58.709), _row(IE, 40.0)]
    out = g.band(rows, PD)
    assert out["in_band"] is True
    assert out["greedy_top"] == KRAKEN and out["held_pick"] == PD
    assert out["runner_up"] == PD
    assert out["gap_pct"] == round((60.0 - 58.709) / 58.709 * 100, 3)


def test_band_doc_arithmetic_flip_is_allowed():
    # LIVE_GAME_GATED_SYNC G2-38: 58.709 * 1.03 = 60.470 < 61.695 -> flip allowed.
    rows = [_row(KRAKEN, 61.695), _row(PD, 58.709)]
    out = g.band({"ranked": rows}, PD)
    assert out["in_band"] is False and out["reason"] == "challenger beats margin"
    assert out["held_pick"] == KRAKEN


@pytest.mark.parametrize("rows,inc,reason", [
    ([_row(KRAKEN, 60.0), _row(PD, 59.0, dead=True)], PD, "incumbent not an eligible row"),
    ([_row(KRAKEN, 60.0), _row(PD, 0.0)], PD, "incumbent delta not positive"),
    ([_row(KRAKEN, 60.0), _row(PD, 59.0)], KRAKEN, "incumbent is the greedy top"),
    ([_row(KRAKEN, 60.0)], "9999", "incumbent not an eligible row"),
    ([_row(KRAKEN, 60.0), _row(PD, 59.0)], None, "no incumbent"),
])
def test_band_not_in_band_cases(rows, inc, reason):
    out = g.band(rows, inc)
    assert out["in_band"] is False and out["reason"] == reason


def test_band_empty_rows():
    out = g.band([], PD)
    assert out["greedy_top"] is None and out["in_band"] is False


def test_band_held_pick_agrees_with_production_picker():
    rng = random.Random(238)
    ids = [PD, KRAKEN, IE, "3094", "3085"]
    for _ in range(400):
        rows = [_row(i, round(rng.uniform(-5, 80), 3), dead=rng.random() < 0.15)
                for i in rng.sample(ids, rng.randint(1, len(ids)))]
        inc = rng.choice(ids + [None])
        prod, _, _ = _pick_top_safe(rows, incumbent_id=inc)
        out = g.band(rows, inc)
        assert out["held_pick"] == (str(prod["item_id"]) if prod else None)
        if out["in_band"]:
            assert out["held_pick"] == inc != out["greedy_top"]


# -- grade --------------------------------------------------------------------

TIGHT = [_row(KRAKEN, 60.0), _row(PD, 59.0)]
WIDE = [_row(KRAKEN, 70.0), _row(PD, 50.0)]


def test_grade_pass_on_held_in_band_tick():
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, PD, TIGHT)])
    assert out["verdict"] == "PASS" and out["in_band"] == 1 and out["held"] == 1


def test_grade_fail_on_flipped_in_band_tick():
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, KRAKEN, TIGHT)])
    assert out["verdict"] == "FAIL" and "challenger" in out["reasons"][0]


def test_grade_fail_on_unexplained_render():
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, IE, TIGHT + [_row(IE, 1.0)])])
    assert out["verdict"] == "FAIL" and "neither" in out["reasons"][0]


def test_grade_no_result_when_never_in_band_reports_tightest_gap():
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, KRAKEN, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, KRAKEN, WIDE),
                   # incumbent PD, challenger beats margin -> flip allowed, not graded
                   _glance("2026-10-31T10:02:00-05:00", 14, PD, WIDE),
                   _glance("2026-10-31T10:03:00-05:00", 15, KRAKEN, WIDE)])
    assert out["verdict"] == "NO_RESULT"
    assert out["in_band"] == 0 and out["tightest_gap_pct"] == 40.0


def test_grade_skips_reload_and_item_change_ticks():
    out = g.grade([
        _glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
        _glance("2026-10-31T10:01:00-05:00", 13, KRAKEN, TIGHT, reload=True),
        _glance("2026-10-31T10:02:00-05:00", 14, PD, TIGHT, items=["1055"]),
    ])
    assert out["verdict"] == "NO_RESULT"
    assert [t.get("skip", "")[:6] for t in out["ticks"]] == ["reload", "owned "]


def test_grade_ignores_non_level_rise_and_sorts_by_time():
    out = g.grade([_glance("2026-10-31T10:01:00-05:00", 13, PD, TIGHT),
                   _glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:30-05:00", 13, KRAKEN, TIGHT)])
    assert out["verdict"] == "PASS" and len(out["ticks"]) == 1


@pytest.mark.parametrize("bad", [
    None,
    {"ts": "2026-10-31T10:00:00", "level": 12, "rendered_top": PD},  # no offset
    {"ts": "2026-10-31T10:00:00-05:00", "level": "12", "rendered_top": PD},
    {"ts": "2026-10-31T10:00:00-05:00", "level": 12, "rendered_top": ""},
    {"ts": "2026-10-31T10:00:00-05:00", "level": True, "rendered_top": PD},
])
def test_grade_malformed_glance_fails(bad):
    out = g.grade([_glance("2026-10-31T09:00:00-05:00", 11, PD, WIDE), bad])
    assert out["verdict"] == "FAIL" and "malformed" in out["reasons"][0]


# -- panel inputs + capture (injected state, engine and route; no network) ---

ROUTE_TGT = {"target_armor": 77.0, "target_mr": 41.0, "target_max_hp": 2100.0,
             "target_bonus_hp": 600.0, "source": "live-enemy-items"}


def _state(level=13, items=("1055",), mode_key="sr", champion="Jhin", display=""):
    # items_display lives on the COACH payload (core/coaching_payload.py), not
    # on the summarized liveclient block.
    return {"mode_key": mode_key,
            "coach": {"champion": champion, "level": level, "items_display": display},
            "liveclient": {"owned_item_ids": list(items), "level": 14,
                           "game_time_s": 812.0}}


def _engine(first_rows, seen):
    calls = {"n": 0}

    def eng(champion, archetype, **kw):
        calls["n"] += 1
        seen.append(kw)
        ranked = first_rows if calls["n"] == 1 else [_row(str(9000 + calls["n"]), 5.0)]
        return {"ok": True, "scorer": "dps", "archetype": archetype, "ranked": ranked}

    return eng


def _route(order_ids, seen_bodies):
    def post(body):
        seen_bodies.append(body)
        return {"ok": True, "order": [{"item_id": i} for i in order_ids],
                "target_stats": dict(ROUTE_TGT)}
    return post


def _plan_ids(first_rows, owned=()):
    res = plan_build_order("Jhin", "carry", level=13, owned_item_ids=list(owned),
                           mode="SR", rank_fn=_engine(first_rows, []),
                           **{k: ROUTE_TGT[k] for k in g.TARGET_KEYS})
    return [str(s.item_id) for s in res.order]


def test_panel_inputs_read_like_the_panel():
    inp = g.panel_inputs(_state(level="13", items=[3046, " 1055 ", None, ""]))
    # Level is the COACH payload's (13), not the Live Client's (14).
    assert inp["level"] == 13 and inp["mode"] == "SR" and inp["champion"] == "Jhin"
    assert inp["items"] == ["3046", "1055"] and inp["items_source"] == "owned_item_ids"
    assert g.panel_inputs(_state(level=None))["level"] == 1
    assert g.panel_inputs(_state(mode_key=None))["mode"] == "SR"
    assert g.panel_inputs(_state(items=[]))["items_source"] == "none"
    assert g.panel_inputs(_state(items=[], display="Doran's Blade"))["items_source"] \
        == "none"
    with pytest.raises(RuntimeError):
        g.panel_inputs(_state(champion=""))


def test_panel_source_pins():
    js = (REPO / "web/js/panels/active_match.js").read_text(encoding="utf-8")
    assert 'const level    = parseInt(p.level || 0, 10) || 1;' in js
    assert "lc.owned_item_ids" in js
    main = (REPO / "web/js/main.js").read_text(encoding="utf-8")
    assert "const coachPayload = st.coach || st;" in main
    assert "setInterval(pollIfStale, 2000);" in main


def test_capture_uses_route_target_stats_and_matches_route_plan():
    seen, bodies = [], []
    out = g.capture(PD, 18.0, state_fn=lambda: _state(), rank_fn=_engine(TIGHT, seen),
                    post_fn=_route(_plan_ids(TIGHT, owned=["1055"]), bodies),
                    now="2026-10-31T10:00:00-05:00")
    # Every engine call ran on the stats the RUNNING route resolved.
    assert seen and all(kw["target_armor"] == 77.0 and kw["target_mr"] == 41.0
                        for kw in seen)
    # The route got the panel's body (coach level, upper mode), no incumbent.
    assert bodies == [{"champion": "Jhin", "mode": "SR", "level": 13, "items": ["1055"],
                       "archetype": ""}]
    assert out["ranked"] == TIGHT and out["greedy_order"][0] == KRAKEN
    assert out["rows_match"] is True and out["target_source"] == "live-enemy-items"
    assert out["rendered_top"] == PD and out["since_levelup_s"] == 18.0
    assert out["game_time_s"] == 812.0
    json.dumps(out)


def test_capture_flags_rows_the_route_did_not_plan():
    out = g.capture(PD, 18.0, state_fn=lambda: _state(), rank_fn=_engine(TIGHT, []),
                    post_fn=_route([PD, "3009"], []))
    assert out["items_source"] == "owned_item_ids"
    assert out["rows_match"] is False


@pytest.mark.parametrize("display", ["", "Long Sword"])
def test_capture_never_matches_without_owned_item_ids(display):
    # Empty owned_item_ids -> the panel uses allPlayers[].items or the coach
    # items_display, neither replicated here, so the glance is never graded.
    out = g.capture(PD, 18.0, state_fn=lambda: _state(items=[], display=display),
                    rank_fn=_engine(TIGHT, []), post_fn=_route(_plan_ids(TIGHT), []))
    assert out["items_source"] == "none" and out["rows_match"] is False


def test_capture_drops_owned_aliases_like_the_planner():
    rows = [_row(KRAKEN, 60.0), _row("1055", 99.0), _row(PD, 59.0)]
    out = g.capture(PD, 18.0, state_fn=lambda: _state(items=["1055"]),
                    rank_fn=_engine(rows, []),
                    post_fn=_route(_plan_ids(rows, owned=["1055"]), []))
    assert [r["item_id"] for r in out["ranked"]] == [KRAKEN, PD]
    assert out["rows_match"] is True


@pytest.mark.parametrize("resp", [
    {"ok": False, "error": "DS engine unavailable"},
    {"ok": True, "order": [], "target_stats": {"target_armor": 1.0}},
    None,
])
def test_capture_refuses_without_route_plan(resp):
    with pytest.raises(RuntimeError):
        g.capture(PD, 18.0, state_fn=lambda: _state(), rank_fn=_engine(TIGHT, []),
                  post_fn=lambda body: resp)


def test_grade_skips_unmatched_glance():
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, PD, TIGHT, rows_match=False)])
    assert out["verdict"] == "NO_RESULT"
    assert out["ticks"][0]["skip"].startswith("rows not matched")


@pytest.mark.parametrize("settle", [None, 29.9, "40", float("nan"), float("inf"),
                                    float("-inf"), True])
def test_grade_skips_glance_before_the_settle_floor(settle):
    # A HELD read before the repaint is the stale old order, not an observation.
    out = g.grade([_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
                   _glance("2026-10-31T10:01:00-05:00", 13, PD, TIGHT,
                           since_levelup_s=settle)])
    assert out["verdict"] == "NO_RESULT"
    assert out["ticks"][0]["skip"].startswith("glance before the settle floor")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, "40"])
def test_capture_refuses_a_bad_settle_time(bad):
    with pytest.raises(ValueError):
        g.capture(PD, bad, state_fn=lambda: _state(), rank_fn=_engine(TIGHT, []),
                  post_fn=_route(_plan_ids(TIGHT, owned=["1055"]), []))


def test_cli_capture_rejects_nan_settle(capsys):
    assert g.main(["capture", "--rendered", PD, "--since-levelup-s", "nan"]) == 2
    assert "finite" in capsys.readouterr().err


def test_settle_floor_covers_route_worst_case():
    # An in-flight old-level POST blocks the re-fire (inFlight guard), so the
    # worst case is two full plans of 5 engine calls (6 slots, boots without a
    # call) at the route's 2.0 s timeout, plus a 10 s repaint allowance.
    route = (REPO / "dashboard/routes_state.py").read_text(encoding="utf-8")
    assert "mode=mode, slots=slots, timeout=2.0," in route
    js = (REPO / "web/js/panels/active_match.js").read_text(encoding="utf-8")
    assert "if (!stale || _BUILD_ORDER.inFlight) return _BUILD_ORDER.order;" in js
    assert g.MIN_SETTLE_S >= 2 * (5 * 2.0) + 10.0


# -- CLI ----------------------------------------------------------------------

def test_cli_exit_codes(tmp_path, capsys):
    rank = tmp_path / "rank.json"
    rank.write_text(json.dumps({"ranked": TIGHT}), encoding="utf-8")
    assert g.main(["band", str(rank), "--incumbent", PD, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["in_band"] is True
    log = tmp_path / "glances.jsonl"
    log.write_text("\n".join(json.dumps(x) for x in [
        _glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE),
        _glance("2026-10-31T10:01:00-05:00", 13, PD, TIGHT)]) + "\n", encoding="utf-8")
    assert g.main(["grade", str(log)]) == 0
    log.write_text(json.dumps(_glance("2026-10-31T10:00:00-05:00", 12, PD, WIDE)) + "\n",
                   encoding="utf-8")
    assert g.main(["grade", str(log)]) == 3
    assert g.main(["grade", str(tmp_path / "missing.jsonl")]) == 2
    # capture needs both glance facts; argparse refuses without them.
    with pytest.raises(SystemExit):
        g.main(["capture", "--rendered", PD])
