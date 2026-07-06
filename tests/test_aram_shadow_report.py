"""ARAM shadow report tests - tools.aram_shadow_report. Pins the per-field
deterministic-vs-live_haiku agreement math, the dead-state exclusion (the
cycle-53 false-0% lesson), the choices/field-presence coverage, and the JSON
shape over synthetic shadow logs.
"""
from __future__ import annotations

import json

from tools import aram_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ---- 1. load_jsonl fail-soft (copied from the HZ test style) ----


def test_load_jsonl_fail_soft_missing(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n{"b":2}\n', encoding="utf-8")
    rows = rep.load_jsonl(p)
    assert rows == [{"a": 1}, {"b": 2}]


# ---- 2. classify_verdict ----


def test_classify_verdict_table():
    assert rep.classify_verdict("FALL BACK") == "back_off"
    assert rep.classify_verdict("ALL IN") == "all_in"
    assert rep.classify_verdict("POKE him") == "trade"
    assert rep.classify_verdict("hold the wave") == "hold"
    assert rep.classify_verdict("disengage") == "back_off"


def test_classify_verdict_dead_state_and_empty_are_none():
    assert rep.classify_verdict("WAIT RESPAWN") is None
    assert rep.classify_verdict("COACHING DISABLED") is None
    assert rep.classify_verdict("") is None


# ---- 3. _is_present ----


def test_is_present():
    assert rep._is_present("") is False
    assert rep._is_present("  ") is False
    assert rep._is_present("x") is True
    assert rep._is_present([]) is False
    assert rep._is_present([1]) is True
    assert rep._is_present({}) is False
    assert rep._is_present({"a": 1}) is True
    assert rep._is_present(None) is False


# ---- 4. _is_dead_state (authority = the Haiku action) ----


def test_is_dead_state_authority_is_haiku_action():
    assert rep._is_dead_state({"live_haiku": {"action": "WAIT RESPAWN"}}) is True
    assert rep._is_dead_state({"live_haiku": {"action": "FALL BACK"}}) is False
    # deterministic dead but Haiku alive -> NOT dead-state (authority is Haiku)
    assert rep._is_dead_state(
        {"deterministic": {"action": "WAIT RESPAWN"},
         "live_haiku": {"action": "TRADE"}}) is False


# ---- 5. summarize_action ----


def test_summarize_action_five_rows():
    rows = []
    for d, live in [
        ("FALL BACK", "fall back"),
        ("ALL-IN", "Back off"),
        ("", "TRADE"),
        ("POKE", "WAIT RESPAWN"),
        ("HOLD", "hold the wave"),
    ]:
        rows.append({"deterministic": {"action": d}, "live_haiku": {"action": live}})
    out = rep.summarize_action(rows)
    assert out["comparable"] == 3
    assert out["agree"] == 2
    assert out["agreement_rate"] == round(2 / 3, 4)
    assert out["dead_state_excluded"] == 1
    assert out["live_only_classified"] == 1
    assert out["det_only_classified"] == 0
    assert out["both_unclassified"] == 0
    assert out["by_native"]["back_off"] == {"n": 2, "agree": 1}
    assert out["by_native"]["hold"] == {"n": 1, "agree": 1}
    assert out["by_deterministic"] == {"all_in": 1, "back_off": 1, "hold": 1}
    # confusion sorted by -n then key; all three pairs tie at n=1 so the key
    # ("all_in","back_off") sorts to index 0 by construction (same sort as hz).
    assert out["confusion"][0] == {
        "deterministic": "all_in", "native": "back_off", "n": 1, "agree": False}
    # the back_off self-pair agrees; the all_in -> back_off mismatch is present.
    by_pair = {(c["deterministic"], c["native"]): c for c in out["confusion"]}
    assert by_pair[("back_off", "back_off")]["agree"] is True
    assert by_pair[("all_in", "back_off")]["agree"] is False
    assert by_pair[("all_in", "back_off")]["n"] == 1


# ---- 6. summarize_action empty ----


def test_summarize_action_empty():
    out = rep.summarize_action([])
    assert out["comparable"] == 0
    assert out["agree"] == 0
    assert out["agreement_rate"] == 0.0
    assert out["dead_state_excluded"] == 0
    assert out["by_native"] == {}
    assert out["confusion"] == []


# ---- 7. summarize_choices ----


def test_summarize_choices_four_rows():
    rows = [
        {"deterministic": {"choices": [{"label": "Recall"}]},
         "live_haiku": {"action": "TRADE", "choices": []}},
        {"deterministic": {"choices": [{"label": "Engage on E"}]},
         "live_haiku": {"action": "TRADE", "choices": [{"label": "All in now"}]}},
        {"deterministic": {"choices": []},
         "live_haiku": {"action": "TRADE", "choices": []}},
        # dead-state row - excluded from choices entirely
        {"deterministic": {"choices": [{"label": "whatever"}]},
         "live_haiku": {"action": "WAIT RESPAWN", "choices": [{"label": "x"}]}},
    ]
    out = rep.summarize_choices(rows)
    assert out["non_dead_total"] == 3
    assert out["det_present"] == 2
    assert out["det_coverage_rate"] == round(2 / 3, 4)
    assert out["both_present"] == 1
    assert out["det_only"] == 1
    assert out["live_only"] == 0
    assert out["neither"] == 1
    assert out["label_comparable"] == 1
    assert out["label_agree"] == 1
    assert out["label_agreement_rate"] == 1.0


def test_summarize_choices_instrumented_excludes_pre_instrumentation_rows():
    # Rows logged BEFORE the choices instrumentation landed have NO "choices"
    # key in the deterministic block; they must not drag down the current-code
    # coverage read. det_coverage_rate (all non-dead) counts them as misses;
    # det_coverage_rate_instrumented counts only rows the current code touched.
    rows = [
        # 2 pre-instrumentation rows (no det choices key at all)
        {"deterministic": {"action": "POKE"},
         "live_haiku": {"action": "TRADE"}},
        {"deterministic": {"action": "HOLD"},
         "live_haiku": {"action": "HOLD"}},
        # 2 instrumented rows, both offering choices
        {"deterministic": {"choices": [{"label": "Poke"}]},
         "live_haiku": {"action": "TRADE", "choices": []}},
        {"deterministic": {"choices": [{"label": "Hold"}]},
         "live_haiku": {"action": "HOLD", "choices": []}},
    ]
    out = rep.summarize_choices(rows)
    assert out["non_dead_total"] == 4
    assert out["det_present"] == 2
    assert out["det_instrumented"] == 2
    # raw rate is dragged down by the 2 pre-instrumentation rows
    assert out["det_coverage_rate"] == round(2 / 4, 4)
    # instrumented rate reflects current-code coverage (2/2)
    assert out["det_coverage_rate_instrumented"] == 1.0


def test_summarize_choices_instrumented_zero_safe():
    # No instrumented rows at all -> rate is 0.0, never a ZeroDivisionError.
    rows = [{"deterministic": {"action": "POKE"},
             "live_haiku": {"action": "TRADE"}}]
    out = rep.summarize_choices(rows)
    assert out["det_instrumented"] == 0
    assert out["det_coverage_rate_instrumented"] == 0.0


# ---- 8. summarize_field_presence ----


def test_summarize_field_presence():
    rows = [
        {"deterministic": {"fight_rule": "x", "reset_item": ""},
         "live_haiku": {"action": "TRADE", "fight_rule": "y", "reset_item": "z"}},
        {"deterministic": {"fight_rule": "a", "reset_item": ""},
         "live_haiku": {"action": "TRADE", "fight_rule": "b", "reset_item": "c"}},
    ]
    out = rep.summarize_field_presence(rows)
    assert out["fight_rule"]["both"] == 2
    assert out["reset_item"]["live_only"] >= 1
    # every field present even at zero
    for field in rep._FIELDS:
        assert set(out[field].keys()) == {"both", "det_only", "live_only", "neither"}


# ---- 9. build_report shape ----


def test_build_report_shape(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"deterministic": {"action": "FALL BACK"},
         "live_haiku": {"action": "back off"}},
    ])
    r = rep.build_report(p)
    assert r["schema"] == "aram_shadow_report/v1"
    for key in ("total", "dead_state", "non_dead", "action", "choices",
                "field_presence", "flip_ready_hint"):
        assert key in r


# ---- 10. build_report empty ----


def test_build_report_empty(tmp_path):
    r = rep.build_report(tmp_path / "none.jsonl")
    assert "no shadow data" in r["flip_ready_hint"]
    assert r["action"]["comparable"] == 0


# ---- 11. flip hint gate ----


def test_flip_hint_gate_met_when_all_agree(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"deterministic": {"action": "FALL BACK"},
         "live_haiku": {"action": "back off"}},
        {"deterministic": {"action": "TRADE"},
         "live_haiku": {"action": "poke him"}},
    ])
    r = rep.build_report(p)
    assert "gate MET" in r["flip_ready_hint"]


def test_flip_hint_below_gate_when_mostly_disagree(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"deterministic": {"action": "ALL IN"},
         "live_haiku": {"action": "back off"}},
        {"deterministic": {"action": "ALL IN"},
         "live_haiku": {"action": "fall back"}},
        {"deterministic": {"action": "ALL IN"},
         "live_haiku": {"action": "retreat"}},
        {"deterministic": {"action": "TRADE"},
         "live_haiku": {"action": "poke"}},
    ])
    r = rep.build_report(p)
    assert "below 70% gate" in r["flip_ready_hint"]


# ---- 12. main entrypoints ----


def test_main_human(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"deterministic": {"action": "FALL BACK"},
         "live_haiku": {"action": "back off"}},
    ])
    rc = rep.main(["--path", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[action]" in out
    assert "hint:" in out


def test_main_json(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [
        {"deterministic": {"action": "FALL BACK"},
         "live_haiku": {"action": "back off"}},
    ])
    rc = rep.main(["--path", str(p), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "aram_shadow_report/v1"
