"""Tests for tools/gated_g303_variant_reach.py (G3-03 PREP, read-only).

The engine half is the REAL core.aram_comp_verdict (its _variants /
_find_variant / keyword sets), so a keyword-set change there shows up here.
The row sources are injected, so nothing reads the operator's user-build
store or the network.
"""

from __future__ import annotations

import json

from tools import gated_g303_variant_reach as g


def _curated(champ):
    return [{"key": "aram-collapsed", "label": f"Builds for {champ}",
             "is_default": True}]


def test_panel_rows_mirror_route_merge_and_panel_filter():
    rows = g.panel_rows(
        [{"key": "empty", "label": "x"}, {"key": "aram-collapsed", "label": ""}],
        [{"key": "abc", "label": "Snowball Crit"}, {"key": "def"}])
    assert rows == [
        {"key": "aram-collapsed", "label": "aram-collapsed", "summary": ""},
        {"key": "userbuild_abc", "label": "Snowball Crit", "summary": ""},
        {"key": "userbuild_def", "label": "user build", "summary": ""},
    ]


def test_collapsed_key_is_a_substring_ap_hit_not_genuine():
    rows = g.panel_rows(_curated("Caitlyn"), [{"key": "abc", "label": "crit max"}])
    out = g.reach(rows, "userbuild_abc")
    assert out["ap"] == {"variant_to": "aram-collapsed", "keyword": "ap",
                         "kind": "substring"}


def test_current_row_is_skipped():
    rows = g.panel_rows(_curated("Caitlyn"), [{"key": "abc", "label": "crit max"}])
    out = g.reach(rows, "aram-collapsed")
    assert out["ap"]["variant_to"] is None
    assert out["ad"] == {"variant_to": "userbuild_abc", "keyword": "crit",
                         "kind": "genuine"}
    assert out["sustain"]["variant_to"] is None


def test_whole_word_label_is_genuine():
    rows = g.panel_rows(_curated("Ahri"), [{"key": "x1", "label": "AP burst"},
                                            {"key": "x2", "label": "Lifesteal"}])
    out = g.reach(rows, "aram-collapsed")
    assert out["ap"]["kind"] == "genuine"
    assert out["ap"]["variant_to"] == "userbuild_x1"
    assert out["sustain"] == {"variant_to": "userbuild_x2",
                              "keyword": "lifesteal", "kind": "genuine"}


def test_single_row_reaches_nothing():
    rows = g.panel_rows(_curated("Annie"), [])
    out = g.reach(rows, "aram-collapsed")
    assert all(v["variant_to"] is None for v in out.values())


def test_report_defaults_current_to_first_row_and_self_lean_closes_gap():
    # Vayne is an AD-lean champion in my_team, so "the comp lacks AD" can
    # never open: the genuine "crit" hit is unreachable live.
    recs = g.report(["Vayne"], None, _curated,
                    lambda c: [{"key": "k", "label": "AS CRIT"}])
    assert recs[0]["current"] == "aram-collapsed"
    assert recs[0]["rows"] == 2
    assert recs[0]["lean"] == "ad"
    assert recs[0]["gaps"]["ad"]["kind"] == "genuine"
    assert recs[0]["gaps"]["ad"]["self_closes"] is True
    assert recs[0]["genuine_gaps"] == []


def test_report_keeps_a_gap_the_champion_does_not_supply():
    # Vayne (AD lean) with a whole-word AP row: an all-AD comp opens the AP
    # gap, so that hit is reachable.
    recs = g.report(["Vayne"], None, _curated,
                    lambda c: [{"key": "k", "label": "AP on-hit"}])
    assert recs[0]["gaps"]["ap"]["self_closes"] is False
    assert recs[0]["genuine_gaps"] == ["ap"]


def test_main_prints_json_lines_and_summary(monkeypatch, capsys):
    monkeypatch.setattr(g, "_default_sources", lambda store=None: (
        _curated, lambda c: [], lambda: ["Annie", "Zed"]))
    assert g.main(["--all"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [r["champion"] for r in lines[:-1]] == ["Annie", "Zed"]
    assert lines[-1]["summary"] == {"champions": 2, "with_2plus_rows": 0,
                                    "genuine": 0, "substring_only": 0}


def test_store_flag_reads_that_file_read_only(tmp_path):
    import coaches.sr_user_builds as ub
    before = ub._STORE_PATH
    store = tmp_path / "user_builds.json"
    store.write_text(json.dumps({"_schema_version": 1, "champions": {
        "Vayne": [{"id": "k1", "label": "AP on-hit",
                   "items": ["Nashor's Tooth"]}]}}), encoding="utf-8")
    _, user, _ = g._default_sources(str(store))
    assert [(r["key"], r["label"]) for r in user("Vayne")] == [("k1", "AP on-hit")]
    assert user("Caitlyn") == []
    assert before == ub._STORE_PATH  # the module store is never repointed


def test_default_path_reads_the_module_store_without_its_reader(monkeypatch,
                                                                 tmp_path):
    import coaches.sr_user_builds as ub
    store = tmp_path / "user_builds.json"
    store.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ub, "_STORE_PATH", store)

    def _boom(*a, **k):
        raise AssertionError("the module reader must not run")

    monkeypatch.setattr(ub, "list_for", _boom)
    monkeypatch.setattr(ub, "_read_cached_locked", _boom)
    _, user, _ = g._default_sources()
    assert user("Vayne") == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["user_builds.json"]


def test_corrupt_store_is_left_in_place(tmp_path):
    store = tmp_path / "user_builds.json"
    store.write_text("{not json", encoding="utf-8")
    _, user, _ = g._default_sources(str(store))
    assert user("Vayne") == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["user_builds.json"]


def test_sustain_champion_closes_the_sustain_gap():
    recs = g.report(["Soraka"], None, _curated,
                    lambda c: [{"key": "k", "label": "heal power"}])
    assert recs[0]["gaps"]["sustain"]["kind"] == "genuine"
    assert recs[0]["gaps"]["sustain"]["self_closes"] is True
    assert "sustain" not in recs[0]["genuine_gaps"]
