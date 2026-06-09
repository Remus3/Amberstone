"""HZ-C - tools.hz_shadow_report tests. Pins the coverage/distribution math,
the fail-soft empty-state, and the JSON shape over synthetic shadow logs.
"""
from __future__ import annotations

import json

from tools import hz_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_load_jsonl_fail_soft_missing(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n{"b":2}\n', encoding="utf-8")
    rows = rep.load_jsonl(p)
    assert rows == [{"a": 1}, {"b": 2}]


def test_laning_coverage_and_distribution(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"my_champion": "Annie", "band": "L6", "covered": True,
         "choices": [{"key": "A", "label": "All-in Caitlyn"}]},
        {"my_champion": "Annie", "band": "L6", "covered": True,
         "choices": [{"key": "A", "label": "All-in Caitlyn"}]},
        {"my_champion": "Yasuo", "band": "L2", "covered": False, "choices": []},
    ])
    out = rep.summarize_laning(rep.load_jsonl(p))
    assert out["total"] == 3
    assert out["covered"] == 2
    assert out["coverage_rate"] == round(2 / 3, 4)
    assert out["by_band"] == {"L6": 2}  # only covered rows
    assert out["by_recommendation"] == {"All-in Caitlyn": 2}
    assert out["by_champion"]["Annie"] == {"total": 2, "covered": 2}
    assert out["by_champion"]["Yasuo"] == {"total": 1, "covered": 0}


def test_build_lean_distribution(tmp_path):
    p = tmp_path / "b.jsonl"
    _write(p, [
        {"my_champion": "Ahri", "lean": "anti_tank", "covered": True, "choices": [1, 2]},
        {"my_champion": "Lux", "lean": "anti_squishy", "covered": True, "choices": [1, 2]},
        {"my_champion": "Zed", "lean": "anti_tank", "covered": False, "choices": []},
    ])
    out = rep.summarize_build(rep.load_jsonl(p))
    assert out["total"] == 3
    assert out["covered"] == 2
    assert out["by_lean"] == {"anti_squishy": 1, "anti_tank": 1}  # covered only


def test_comparable_counts_native_signal(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"my_champion": "A", "covered": True, "choices": [{"label": "x"}],
         "native_choices": [{"label": "y"}], "native_action": "do y"},
        {"my_champion": "B", "covered": True, "choices": [{"label": "x"}],
         "native_choices": [], "native_action": None},  # no native -> not comparable
    ])
    out = rep.summarize_laning(rep.load_jsonl(p))
    assert out["comparable"] == 1


def test_build_report_shape_and_hint_empty(tmp_path):
    r = rep.build_report(tmp_path / "none1.jsonl", tmp_path / "none2.jsonl")
    assert r["schema"] == "hz_shadow_report/v1"
    assert r["laning"]["total"] == 0 and r["build"]["total"] == 0
    assert "no shadow data" in r["flip_ready_hint"]


def test_flip_hint_low_coverage(tmp_path):
    c = tmp_path / "c.jsonl"
    b = tmp_path / "b.jsonl"
    _write(c, [
        {"my_champion": "A", "covered": False, "choices": []},
        {"my_champion": "B", "covered": False, "choices": []},
        {"my_champion": "C", "covered": True, "choices": [{"label": "x"}]},
    ])
    _write(b, [{"my_champion": "A", "lean": None, "covered": False, "choices": []}])
    r = rep.build_report(c, b)
    assert "low seed coverage" in r["flip_ready_hint"]


def test_main_json_runs(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [{"my_champion": "A", "band": "L6", "covered": True,
                "choices": [{"label": "Trade B"}]}])
    rc = rep.main(["--choice-path", str(c), "--build-path", str(tmp_path / "no.jsonl"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["laning"]["covered"] == 1
