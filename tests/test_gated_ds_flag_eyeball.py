"""Tests for tools/gated_ds_flag_eyeball.py (G2-43 / G2-44 / G2-46 / G2-47 PREP,
s144 lane gated c48).

Every input is hand-built (RM-906: no real game, match or player id; item ids
are synthetic strings). No network: capture runs on injected state and post
functions. These tests pin the verdicts, the pairing rule for G2-47, the strip
anomaly, and the source facts the doc rows cite.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from tools import gated_ds_flag_eyeball as eb

ROOT = Path(__file__).resolve().parent.parent


def _rows(ids):
    return {"ranked": [{"item_id": i, "item_name": "Item " + i, "effective_score": 100 - n}
                       for n, i in enumerate(ids)]}


def _pair(row, champion, off_ids, on_ids, *, gt=600.0, top=eb.POOL_TOP, on_flags=None):
    off_body, on_body = eb.build_bodies(row, {"champion": champion, "level": 11,
                                              "items": ["s1"], "mode": "SR"}, top=top)
    if on_flags is not None:
        on_body = dict(off_body)
        on_body.update({f: True for f in on_flags})
    return {"ts": "2026-10-31T00:00:00+00:00", "row": row, "champion": champion,
            "level": 11, "game_time_s": gt, "items_source": "owned_item_ids",
            "body_off": off_body, "body_on": on_body,
            "off": _rows(off_ids), "on": _rows(on_ids)}


def test_bodies_differ_only_by_the_row_flags():
    for row, spec in eb.ROWS.items():
        off, on = eb.build_bodies(row, {"champion": "Somechamp", "level": 9, "items": []})
        assert not any(f in off for f in spec["flags"])
        assert {k: v for k, v in on.items() if k not in spec["flags"]} == off
        assert all(on[f] is True for f in spec["flags"])


def test_carry_bodies_carry_the_chokepoint_fight_length():
    from core.ds_champion_fight_length import champion_fight_length
    off, on = eb.build_bodies("G2-44", {"champion": "Twitch", "level": 11, "items": []})
    assert off["fight_length"] == champion_fight_length("Twitch") == on["fight_length"]
    off, _ = eb.build_bodies("G2-46", {"champion": "Corki", "level": 11, "items": []})
    assert "fight_length" not in off
    off, _ = eb.build_bodies("G2-43", {"champion": "Zed", "level": 11, "items": []})
    assert "fight_length" not in off


def test_g247_single_flag_pair_is_rejected_as_malformed():
    p = _pair("G2-47", "Akshan", ["a", "b"], ["b", "a"], on_flags=["apply_passive_damage"])
    assert "lacks" in eb.check_pair(p)
    assert eb.grade([p], "G2-47")["verdict"] == "ANOMALY"


def test_on_body_with_an_extra_key_is_rejected():
    p = _pair("G2-46", "Corki", ["a"], ["a"])
    p["body_on"]["apply_ad_axis_dual_scaling_split"] = True
    assert "beyond" in eb.check_pair(p)


def test_strip_left_top_and_pool_stripped_reported():
    p = _pair("G2-44", "Twitch", ["a", "b", "lich", "c", "d"], ["a", "b", "c", "d"])
    d = eb.diff_pair(p, top=3)
    assert d["left_top"] == ["lich"]
    assert d["entered_top"] == ["c"]
    assert d["pool_complete"] is True
    assert d["stripped_pool"] == ["lich"]
    assert d["anomalies"] == []


def test_strip_seam_adding_a_candidate_is_an_anomaly_only_when_pools_complete():
    p = _pair("G2-44", "Jinx", ["a", "b"], ["a", "b", "new"])
    assert eb.grade([p], "G2-44")["verdict"] == "ANOMALY"
    # Truncated pools (as many rows as asked for): the extra row may be #N+1.
    q = _pair("G2-44", "Jinx", ["a", "b", "c"], ["a", "b", "new"], top=3)
    d = eb.diff_pair(q)
    assert d["pool_complete"] is False and d["anomalies"] == [] and d["stripped_pool"] is None


def test_reorder_row_reports_moves_and_never_strip_fields():
    p = _pair("G2-46", "Corki", ["x", "y", "z", "w"], ["x", "y", "w", "z"])
    d = eb.diff_pair(p)
    assert d["moved"] == [{"item_id": "w", "from": 4, "to": 3}, {"item_id": "z", "from": 3, "to": 4}]
    assert d["stripped_pool"] is None


def test_g246_null_control_moving_is_an_anomaly():
    corki = _pair("G2-46", "Corki", ["x", "y"], ["y", "x"])
    ez_ok = _pair("G2-46", "Ezreal", ["m", "n"], ["m", "n"])
    ez_bad = _pair("G2-46", "Ezreal", ["m", "n"], ["n", "m"])
    assert eb.grade([corki, ez_ok], "G2-46")["verdict"] == "NEEDS_EYEBALL"
    assert eb.grade([corki, ez_bad], "G2-46")["verdict"] == "ANOMALY"


def test_coverage_groups():
    akali = _pair("G2-43", "Akali", ["a", "b"], ["a"])
    zed = _pair("G2-43", "Zed", ["a", "b"], ["a", "b"])
    assert eb.grade([akali], "G2-43")["verdict"] == "INCOMPLETE"
    assert eb.grade([akali], "G2-43")["missing_groups"] == [["zed", "talon"]]
    assert eb.grade([akali, zed], "G2-43")["verdict"] == "NEEDS_EYEBALL"
    akshan = _pair("G2-47", "Akshan", ["a", "b"], ["b", "a"])
    kog = _pair("G2-47", "Kog'Maw", ["a", "b"], ["a", "b"])
    assert eb.grade([akshan], "G2-47")["verdict"] == "INCOMPLETE"
    assert eb.grade([akshan, kog], "G2-47")["verdict"] == "NEEDS_EYEBALL"


def test_not_live_pair_is_not_evidence():
    p = _pair("G2-44", "Jhin", ["a", "b"], ["a"], gt=None)
    res = eb.grade([p], "G2-44")
    assert res["verdict"] == "INCOMPLETE"
    assert res["rejected"][0]["why"].startswith("not live")


def test_other_rows_pairs_are_ignored():
    p = _pair("G2-44", "Jhin", ["a"], ["a"])
    assert eb.grade([p], "G2-43")["graded"] == []


def test_capture_reads_panel_inputs_and_posts_two_bodies():
    state = {"mode_key": "sr",
             "coach": {"champion": "Akshan", "level": "12"},
             "liveclient": {"owned_item_ids": ["s1", "s2"], "game_time_s": 812.5}}
    calls = []

    def post(path, body):
        calls.append((path, body))
        return _rows(["a", "b"])

    rec = eb.capture("G2-47", state_fn=lambda: state, post_fn=post, now="T")
    assert rec["ok"] is True and rec["source"] == "api_state"
    assert rec["champion"] == "Akshan" and rec["level"] == 12 and rec["mode"] == "SR"
    assert rec["game_time_s"] == 812.5 and rec["items_source"] == "owned_item_ids"
    assert [c[0] for c in calls] == ["/rank", "/rank"]
    assert eb.check_pair(rec) is None
    assert calls[1][1]["apply_passive_damage"] is True
    assert calls[1][1]["apply_extra_shot_procs"] is True


def test_capture_with_args_has_no_game_time_so_it_never_grades():
    rec = eb.capture("G2-43", champion="Akali", level=11, items=[], mode="SR",
                     post_fn=lambda p, b: _rows(["a"]), now="T")
    assert rec["source"] == "args" and rec["game_time_s"] is None
    assert eb.grade([rec], "G2-43")["verdict"] == "INCOMPLETE"


def test_capture_engine_down_is_not_ok():
    rec = eb.capture("G2-46", champion="Corki", level=11, items=[], mode="SR",
                     post_fn=lambda p, b: None, now="T")
    assert rec["ok"] is False
    assert "missing off / on" in eb.check_pair(rec)


def test_main_grade_exit_codes(tmp_path):
    f = tmp_path / "pairs.jsonl"
    f.write_text(json.dumps(_pair("G2-44", "Caitlyn", ["a", "b"], ["a"])) + "\n", encoding="utf-8")
    assert eb.main(["grade", str(f), "--row", "G2-44"]) == 0
    assert eb.main(["grade", str(f), "--row", "G2-46"]) == 3
    assert eb.main(["grade", str(tmp_path / "absent.jsonl"), "--row", "G2-44"]) == 2


def test_source_facts_routes_parse_the_flags_default_off():
    src = (ROOT / "agents" / "daemon_slayer" / "server.py").read_text(encoding="utf-8")

    def _fn(name):
        body = src[src.index(f"def {name}(body"):]
        return " ".join(body[:body.index("\ndef ", 10)].split())

    rank, assassin = _fn("_route_rank"), _fn("_route_rank_assassin")
    for flag in ("exclude_off_axis_items", "apply_ad_axis_ability_damage",
                 "apply_passive_damage", "apply_extra_shot_procs"):
        assert f'body, "{flag}", False' in rank
    assert 'body, "exclude_off_axis_items", False' in assassin
    # The top-N is not capped by the route, so POOL_TOP asks for the whole pool.
    assert 'body, "top", 20' in rank and 'body, "top", 20' in assassin


def test_source_facts_clients_default_the_flags_off():
    from core import daemon_slayer_client as c
    rank = inspect.signature(c.rank_for).parameters
    for flag in ("exclude_off_axis_items", "apply_ad_axis_ability_damage",
                 "apply_passive_damage", "apply_extra_shot_procs"):
        assert rank[flag].default is False
    assert inspect.signature(c.rank_assassin_for).parameters["exclude_off_axis_items"].default is False


def test_partial_override_is_refused_and_never_poses_as_live():
    import pytest
    state = {"mode_key": "sr", "coach": {"champion": "Akali", "level": 11},
             "liveclient": {"owned_item_ids": ["s1"], "game_time_s": 700.0}}
    with pytest.raises(ValueError):
        eb.capture("G2-43", champion="Zed", state_fn=lambda: state,
                   post_fn=lambda p, b: _rows(["a"]), now="T")


def test_engine_down_capture_prints_nothing_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(eb, "capture", lambda *a, **k: {"ok": False})
    assert eb.main(["capture", "--row", "G2-46"]) == 2
    assert capsys.readouterr().out == ""


def test_empty_id_row_does_not_make_a_full_response_look_complete():
    full = {"ranked": [{"item_id": ""}] + [{"item_id": str(n)} for n in range(4)]}
    p = _pair("G2-44", "Jinx", [], [], top=5)
    p["off"], p["on"] = full, {"ranked": [{"item_id": str(n)} for n in range(4)] + [{"item_id": "z"}]}
    d = eb.diff_pair(p)
    assert d["pool_complete"] is False and d["anomalies"] == []


def test_source_facts_carry_chokepoint_forwards_fight_length():
    from core import daemon_slayer_client as c
    src = " ".join(inspect.getsource(c.rank_for_primary_archetype).split())
    assert "_carry_fight_length = champion_fight_length(champion)" in src
    assert "fight_length=_carry_fight_length" in src


def test_source_facts_rankers_slice_only_by_top_n():
    for rel in (("agents", "daemon_slayer", "rank.py"), ("agents", "daemon_slayer", "burst.py")):
        text = (ROOT.joinpath(*rel)).read_text(encoding="utf-8")
        assert "ranked = ranked[:top_n]" in text


# RM-1290 (s144 lane gated c49): the pass-2 verifier NITs on c48's tool.

_LIVE = {"mode_key": "sr", "coach": {"champion": "Akali", "level": 11},
         "liveclient": {"owned_item_ids": ["s1"], "game_time_s": 700.0}}


def test_mode_alone_is_a_partial_override_and_is_refused():
    import pytest
    with pytest.raises(ValueError):
        eb.capture("G2-43", mode="SR", state_fn=lambda: _LIVE,
                   post_fn=lambda p, b: _rows(["a"]), now="T")
    with pytest.raises(ValueError):
        eb.capture("G2-43", champion="Zed", level=11, items=["s1"],
                   state_fn=lambda: _LIVE, post_fn=lambda p, b: _rows(["a"]), now="T")


def test_full_override_is_stamped_args_items_source():
    rec = eb.capture("G2-43", champion="Zed", level=11, items=["s1"], mode="SR",
                     post_fn=lambda p, b: _rows(["a"]), now="T")
    assert rec["source"] == "args" and rec["items_source"] == "args"


def test_live_non_sr_pair_is_rejected_not_graded_and_not_an_anomaly():
    state = dict(_LIVE, mode_key="aram")
    rec = eb.capture("G2-43", state_fn=lambda: state, post_fn=lambda p, b: _rows(["a"]), now="T")
    assert rec["source"] == "api_state" and rec["body_off"]["mode"] == "ARAM"
    res = eb.grade([rec], "G2-43")
    assert res["graded"] == [] and res["verdict"] == "INCOMPLETE"
    assert res["rejected"][0]["why"].startswith("not SR")


def test_live_pair_without_owned_item_ids_is_rejected():
    state = {"mode_key": "sr", "coach": {"champion": "Akali", "level": 11},
             "liveclient": {"owned_item_ids": [], "game_time_s": 700.0}}
    rec = eb.capture("G2-43", state_fn=lambda: state, post_fn=lambda p, b: _rows(["a"]), now="T")
    assert rec["items_source"] == "none"
    res = eb.grade([rec], "G2-43")
    assert res["graded"] == [] and res["verdict"] == "INCOMPLETE"
    assert res["rejected"][0]["why"].startswith("not panel items")


def test_pair_missing_items_source_is_not_evidence():
    p = _pair("G2-44", "Jhin", ["a", "b"], ["a"])
    del p["items_source"]
    res = eb.grade([p], "G2-44")
    assert res["verdict"] == "INCOMPLETE" and res["graded"] == []
    assert res["rejected"][0]["why"] == "not panel items (items_source None)"


def test_live_sr_pair_with_panel_items_grades():
    zed = dict(_LIVE, coach={"champion": "Zed", "level": 11})
    a = eb.capture("G2-43", state_fn=lambda: _LIVE, post_fn=lambda p, b: _rows(["a"]), now="T")
    z = eb.capture("G2-43", state_fn=lambda: zed, post_fn=lambda p, b: _rows(["a"]), now="T")
    assert eb.grade([a, z], "G2-43")["verdict"] == "NEEDS_EYEBALL"


def test_rows_carry_no_dead_keys():
    for spec in eb.ROWS.values():
        assert set(spec) == {"route", "flags", "kind", "need", "null_control"}


def test_source_facts_no_clamp_on_top_in_routes_or_rankers():
    """The route reads ``top`` with default 20 and passes it straight through;
    the rankers only slice by it. A min() / max() clamp anywhere on that path
    would make POOL_TOP=200 silently truncate and a full pool look complete."""
    import re
    src = (ROOT / "agents" / "daemon_slayer" / "server.py").read_text(encoding="utf-8")
    for name in ("_route_rank", "_route_rank_assassin"):
        body = src[src.index(f"def {name}(body"):]
        body = body[:body.index("\ndef ", 10)]
        lines = [ln.strip() for ln in body.splitlines()
                 if re.search(r"\btop_n\b", ln) and not ln.strip().startswith("#")]
        assert lines == ['top_n = _opt_int(body, "top", 20)', "if top_n is None:",
                         "top_n = 20", "budget=budget, slot_count=slot_count, top_n=top_n,"], name
    # In the rankers top_n is only a parameter and a slice bound: no
    # reassignment (a bare ``top_n =`` statement) and no min() / max() over it.
    assign = re.compile(r"^\s*top_n\s*=(?!=)")
    clamp = re.compile(r"\b(?:min|max)\([^)]*\btop_n\b")
    for rel in (("agents", "daemon_slayer", "rank.py"), ("agents", "daemon_slayer", "burst.py")):
        text = (ROOT.joinpath(*rel)).read_text(encoding="utf-8")
        hits = [ln.strip() for ln in text.splitlines() if assign.search(ln) or clamp.search(ln)]
        assert hits == [], (rel, hits)


# RM-1388 (s144 lane gated c61): the line-regex pin above misses a
# multi-line clamp, a chained slice (``ranked[:top_n][:50]``) and a clamp
# inside ``_to_int`` / ``_opt_int``. The AST pins below close all three.

_DS = ROOT / "agents" / "daemon_slayer"


def _ds_fn(filename, name):
    import ast
    tree = ast.parse((_DS / filename).read_text(encoding="utf-8"))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, (filename, name, len(found))
    return found[0]


def _names(fn, ident, ctx):
    import ast
    return [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == ident
            and isinstance(n.ctx, ctx)]


def test_s144g42_rankers_cut_ranked_once_by_top_n_and_never_after():
    """Each ranker reads ``top_n`` only inside ``if top_n is not None and
    top_n > 0: ranked = ranked[:top_n]``; that is the function's only slice,
    and after it ``ranked`` is not re-bound, item-assigned, deleted from, or
    shrunk by pop / remove / clear. Not covered: a cut in the return
    expression or inside a helper that is passed ``ranked``."""
    import ast
    for filename, name in (("rank.py", "rank_items"), ("burst.py", "rank_items_by_burst")):
        fn = _ds_fn(filename, name)
        assert "top_n" in [a.arg for a in fn.args.args + fn.args.kwonlyargs], name
        assert _names(fn, "top_n", (ast.Store, ast.Del)) == [], name
        slices = [n for n in ast.walk(fn) if isinstance(n, ast.Subscript)
                  and isinstance(n.slice, ast.Slice)]
        assert [ast.unparse(n) for n in slices] == ["ranked[:top_n]"], name
        cut = [n for n in ast.walk(fn) if isinstance(n, ast.If)
               and any(isinstance(s, ast.Assign) and s.value is slices[0] for s in n.body)]
        assert len(cut) == 1, name
        assert ast.unparse(cut[0].test) == "top_n is not None and top_n > 0", name
        assert [ast.unparse(s) for s in cut[0].body] == ["ranked = ranked[:top_n]"], name
        assert cut[0].orelse == [], name
        inside = {id(n) for n in ast.walk(cut[0])}
        loads = _names(fn, "top_n", ast.Load)
        assert len(loads) == 3 and all(id(n) in inside for n in loads), (name, len(loads))
        line = slices[0].lineno
        later = [n.lineno for n in _names(fn, "ranked", (ast.Store, ast.Del)) if n.lineno > line]
        assert later == [], (name, later)
        shrink = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and n.lineno > line and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Name) and n.func.value.id == "ranked"
                  and n.func.attr in {"pop", "remove", "clear", "__delitem__"}]
        assert shrink == [], (name, shrink)
        writes = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Subscript)
                  and isinstance(n.value, ast.Name) and n.value.id == "ranked"
                  and isinstance(n.ctx, (ast.Store, ast.Del))]
        assert writes == [], (name, writes)


def test_s144g42_routes_pass_top_through_unclamped_and_never_slice():
    """Both routes bind ``top_n`` only from ``_opt_int(body, 'top', 20)`` and
    the None fallback 20, read it only in that ``is None`` test and in the one
    ``top_n=top_n`` keyword to the ranker, and contain no slice, so the route
    body does not cut the ranker's answer by slicing (other cuts are not
    covered)."""
    import ast
    for name, ranker in (("_route_rank", "rank_items"),
                         ("_route_rank_assassin", "rank_items_by_burst")):
        fn = _ds_fn("server.py", name)
        stores = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "top_n" for t in n.targets)]
        assert [ast.unparse(s) for s in stores] == [
            "top_n = _opt_int(body, 'top', 20)", "top_n = 20"], name
        assert len(_names(fn, "top_n", (ast.Store, ast.Del))) == 2, name
        checks = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "top_n is None"]
        assert len(checks) == 1 and checks[0].body == [stores[1]], name
        kws = [(c, k) for c in ast.walk(fn) if isinstance(c, ast.Call)
               for k in c.keywords if k.arg == "top_n"]
        assert len(kws) == 1, name
        call, kw = kws[0]
        assert ast.unparse(call.func) == ranker, name
        assert ast.unparse(kw.value) == "top_n", name
        assert len(_names(fn, "top_n", ast.Load)) == 2, name
        slices = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Subscript)
                  and isinstance(n.slice, ast.Slice)]
        assert slices == [], (name, slices)


def test_s144g42_to_int_and_opt_int_return_top_unclamped():
    """``top`` values up to 10**6 come back exactly as given, and neither
    coercion helper calls min() or max()."""
    import ast

    from agents.daemon_slayer import server as ds
    for v in (1, 20, 21, eb.POOL_TOP, 500, 10 ** 6):
        assert ds._to_int(v, "top") == v
        assert ds._opt_int({"top": v}, "top", 20) == v
    assert ds._to_int(float(eb.POOL_TOP), "top") == eb.POOL_TOP
    assert ds._opt_int({}, "top", 20) == 20
    assert ds._opt_int({"top": None}, "top", 20) == 20
    for name in ("_to_int", "_opt_int"):
        fn = _ds_fn("server.py", name)
        calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id in {"min", "max"}]
        assert calls == [], (name, calls)
