"""Champ-select shadow report tests - tools.champ_select_shadow_report.

Pins the four measurable native-vs-deterministic agreement columns over the
core.champ_select_shadow record shape (summoners set-equality, watchout
roster-overlap, ARAM-gated swap classification, ordered-keyword advice class),
the field-presence silent-gap diagnostic, the MIN_SAMPLE / FLIP_GATE state
machine, and the never-raise contract on every degenerate input.
"""
from __future__ import annotations

import json

from tools import champ_select_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _row(**kw):
    """One shadow record in core.champ_select_shadow's exact written shape."""
    native = kw.pop("native", {})
    det = kw.pop("deterministic", {})
    rec = {
        "ts": "2026-07-28T00:00:00+00:00",
        "is_aram": kw.pop("is_aram", True),
        "queue_id": kw.pop("queue_id", 450),
        "my_champion": kw.pop("my_champion", "Ahri"),
        "my_team": kw.pop("my_team", ["Ahri"]),
        "their_team": kw.pop("their_team", ["Zed", "Lux"]),
        "bench": kw.pop("bench", ["Tristana"]),
        "engine_version": "1.262.0",
        "native": {k: native.get(k, "") for k in rep._FIELDS},
        "deterministic": {k: det.get(k, "") for k in rep._FIELDS},
    }
    rec.update(kw)
    return rec


# ---- 1. constants + record-shape contract ----


def test_fields_match_the_writer_advice_keys():
    from core.champ_select_shadow import _ADVICE_KEYS
    assert rep._FIELDS == _ADVICE_KEYS


def test_gate_constants():
    assert rep.FLIP_GATE == 0.70
    assert rep.MIN_SAMPLE == 20


# ---- 2. load_jsonl fail-soft ----


def test_load_jsonl_fail_soft_missing(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_and_non_dict_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n[1,2]\n"bare"\n{"b":2}\n', encoding="utf-8")
    assert rep.load_jsonl(p) == [{"a": 1}, {"b": 2}]


def test_load_jsonl_on_a_directory_is_fail_soft(tmp_path):
    assert rep.load_jsonl(tmp_path) == []


# ---- 3. summoners: spell-pair SET equality ----


def test_parse_summoners():
    assert rep.parse_summoners("Flash + Heal") == frozenset({"flash", "heal"})
    assert rep.parse_summoners("flash/ignite") == frozenset({"flash", "ignite"})
    assert rep.parse_summoners("Flash, Barrier") == frozenset({"flash", "barrier"})
    assert rep.parse_summoners("Heal + Flash") == frozenset({"flash", "heal"})
    assert rep.parse_summoners("Flash + Snowball") == frozenset({"flash", "mark"})
    assert rep.parse_summoners("") == frozenset()
    assert rep.parse_summoners(None) == frozenset()
    assert rep.parse_summoners("no idea at all") == frozenset()


def test_summarize_summoners():
    rows = [
        _row(deterministic={"summoners": "Flash + Heal"},
             native={"summoners": "Flash + Heal"}),
        _row(deterministic={"summoners": "Flash + Ignite"},
             native={"summoners": "Flash + Heal"}),
        _row(deterministic={"summoners": "Flash + Heal"},
             native={"summoners": ""}),
        _row(deterministic={"summoners": ""}, native={"summoners": ""}),
    ]
    out = rep.summarize_summoners(rows)
    assert out["comparable"] == 2
    assert out["agree"] == 1
    assert out["agreement_rate"] == 0.5
    assert out["det_only_parsed"] == 1
    assert out["native_only_parsed"] == 0
    assert out["both_unparsed"] == 1


def test_summarize_summoners_order_insensitive():
    rows = [_row(deterministic={"summoners": "Flash + Heal"},
                 native={"summoners": "Heal and Flash"})]
    out = rep.summarize_summoners(rows)
    assert out["comparable"] == 1
    assert out["agree"] == 1


# ---- 4. watchout: champion-name overlap vs their_team ----


def test_extract_watchout_names():
    assert rep.extract_watchout_names(
        "Watch Zed (assassin).", ["Zed", "Lux"]) == frozenset({"Zed"})
    assert rep.extract_watchout_names(
        "Watch out for Lee Sin early.", ["Lee Sin", "Lux"]) == frozenset({"Lee Sin"})
    assert rep.extract_watchout_names(
        "Kai'Sa will out-range you.", ["Kai'Sa"]) == frozenset({"Kai'Sa"})
    assert rep.extract_watchout_names("Watch Zed.", []) == frozenset()
    assert rep.extract_watchout_names("nothing here", ["Zed"]) == frozenset()
    assert rep.extract_watchout_names(None, ["Zed"]) == frozenset()


def test_summarize_watchout():
    rows = [
        _row(deterministic={"watchout": "Watch Zed (assassin)."},
             native={"watchout": "Zed will burst you at 6."}),
        _row(deterministic={"watchout": "Watch Zed (assassin)."},
             native={"watchout": "Lux poke is the real problem."}),
        _row(deterministic={"watchout": "Watch Zed (assassin)."},
             native={"watchout": ""}),
        _row(deterministic={"watchout": ""}, native={"watchout": ""}),
        _row(their_team=[],
             deterministic={"watchout": "Watch Zed."},
             native={"watchout": "Watch Zed."}),
    ]
    out = rep.summarize_watchout(rows)
    assert out["comparable"] == 2
    assert out["agree"] == 1
    assert out["agreement_rate"] == 0.5
    assert out["det_only_named"] == 1
    assert out["native_only_named"] == 0
    assert out["both_unnamed"] == 1
    assert out["no_roster"] == 1


# ---- 5. swap: SWAP/KEEP + target, ARAM-gated ----


def test_classify_swap():
    assert rep.classify_swap("", ["Tristana"]) == ("KEEP", None)
    assert rep.classify_swap("   ", ["Tristana"]) == ("KEEP", None)
    assert rep.classify_swap("none", ["Tristana"]) == ("KEEP", None)
    assert rep.classify_swap("no swap needed", ["Tristana"]) == ("KEEP", None)
    assert rep.classify_swap(None, []) == ("KEEP", None)
    assert rep.classify_swap("Tristana", ["Tristana"]) == ("SWAP", "Tristana")
    assert rep.classify_swap(
        "Swap to Tristana for the range", ["Tristana"]) == ("SWAP", "Tristana")
    assert rep.classify_swap("take the bench pick", ["Tristana"]) == ("SWAP", None)


def test_summarize_swap_gates_out_non_aram_rows():
    rows = [
        _row(is_aram=True),
        _row(is_aram=True),
        _row(is_aram=False, queue_id=420, bench=[]),
    ]
    out = rep.summarize_swap(rows)
    assert out["gated_out_non_aram"] == 1
    assert out["comparable"] == 2


def test_summarize_swap_agreement():
    rows = [
        _row(deterministic={"swap": ""}, native={"swap": ""}),
        _row(deterministic={"swap": "Tristana"},
             native={"swap": "Swap to Tristana"}),
        _row(deterministic={"swap": "Tristana"}, native={"swap": ""}),
    ]
    out = rep.summarize_swap(rows)
    assert out["comparable"] == 3
    assert out["agree"] == 2
    assert out["agreement_rate"] == round(2 / 3, 4)
    assert out["class_agree"] == 2
    assert out["target_agree"] == 1
    by_pair = {(c["deterministic"], c["native"]): c for c in out["confusion"]}
    assert by_pair[("SWAP:Tristana", "KEEP")]["agree"] is False


def test_summarize_swap_counts_rows_without_a_bench():
    rows = [_row(bench=[])]
    out = rep.summarize_swap(rows)
    assert out["comparable"] == 1
    assert out["no_bench"] == 1


# ---- 6. advice: ordered keyword-class agreement ----


def test_classify_advice_table():
    assert rep.classify_advice("Stay Ahri - solid into this comp.") == "keep"
    assert rep.classify_advice(
        "Stay Ahri, shift build - enemy AD-heavy, prioritize armor.") == "variant"
    assert rep.classify_advice("Swap to Tristana - better range") == "swap"
    assert rep.classify_advice("Lock in Ahri now") == "keep"
    assert rep.classify_advice("Dodge this one") == "dodge"
    assert rep.classify_advice("First pick Ahri here") == "pick"
    assert rep.classify_advice("") is None
    assert rep.classify_advice(None) is None
    assert rep.classify_advice("hello there") is None


def test_classify_advice_degraded_states_are_none():
    assert rep.classify_advice("(no champion locked yet)") is None
    assert rep.classify_advice("(champ-select coach disabled)") is None
    assert rep.classify_advice("(coaching paused - retrying)") is None
    assert rep.classify_advice("(API key missing - coach disabled)") is None


def test_is_degraded_authority_is_the_native_advice():
    assert rep.is_degraded(
        _row(native={"advice": "(coaching paused - retrying)"})) is True
    assert rep.is_degraded(_row(native={"advice": "Stay Ahri - solid."})) is False
    # deterministic degraded but native spoke -> NOT degraded (authority = native)
    assert rep.is_degraded(
        _row(deterministic={"advice": "(coaching paused - retrying)"},
             native={"advice": "Stay Ahri - solid."})) is False


def test_summarize_advice():
    rows = [
        _row(deterministic={"advice": "Stay Ahri - solid into this comp."},
             native={"advice": "Stay Ahri, the comp is fine."}),
        _row(deterministic={"advice": "Swap to Tristana - range"},
             native={"advice": "Stay Ahri, you out-scale."}),
        _row(deterministic={"advice": "Stay Ahri - solid."},
             native={"advice": "no strong read"}),
        _row(deterministic={"advice": ""}, native={"advice": ""}),
        _row(deterministic={"advice": "Stay Ahri - solid."},
             native={"advice": "(coaching paused - retrying)"}),
    ]
    out = rep.summarize_advice(rows)
    assert out["comparable"] == 2
    assert out["agree"] == 1
    assert out["agreement_rate"] == 0.5
    assert out["det_only_classified"] == 1
    assert out["native_only_classified"] == 0
    assert out["both_unclassified"] == 1
    assert out["degraded_excluded"] == 1
    assert out["by_deterministic"] == {"keep": 1, "swap": 1}
    assert out["by_native"]["keep"] == {"n": 2, "agree": 1}


# ---- 7. field presence (the silent-gap diagnostic) ----


def test_summarize_field_presence():
    rows = [
        _row(deterministic={"advice": "Stay Ahri.", "summoners": "Flash + Heal"},
             native={"advice": "Stay Ahri.", "summoners": "", "swap": "Tristana"}),
        _row(deterministic={"advice": "Stay Ahri.", "summoners": "Flash + Heal"},
             native={"advice": "Stay Ahri.", "summoners": "", "swap": "Tristana"}),
    ]
    out = rep.summarize_field_presence(rows)
    assert out["advice"]["both"] == 2
    assert out["summoners"]["det_only"] == 2
    assert out["swap"]["native_only"] == 2
    assert out["watchout"]["neither"] == 2
    for field in rep._FIELDS:
        assert set(out[field]) == {"both", "det_only", "native_only", "neither"}


def test_field_presence_excludes_degraded_rows():
    rows = [_row(native={"advice": "(coaching paused - retrying)"})]
    out = rep.summarize_field_presence(rows)
    assert out["advice"]["neither"] == 0
    assert out["advice"]["both"] == 0


# ---- 8. coverage ----


def test_coverage_block():
    rows = [
        _row(my_champion="Ahri"),
        _row(my_champion="Lux"),
        _row(is_aram=False, queue_id=420, my_champion="Ahri"),
        _row(my_champion="Zed", native={"advice": "(coaching paused - retrying)"}),
    ]
    cov = rep.summarize_coverage(rows)
    assert cov["total"] == 4
    assert cov["degraded"] == 1
    assert cov["scorable"] == 3
    assert cov["aram"] == 2
    assert cov["non_aram"] == 1
    assert cov["distinct_champions"] == 2
    assert cov["distinct_queues"] == 2


# ---- 9. never raises on degenerate input ----


def test_every_summarizer_survives_non_dict_records():
    junk = [None, 3, "x", [], {"native": "notadict", "deterministic": 7}]
    assert rep.summarize_coverage(junk)["total"] == 5
    assert rep.summarize_summoners(junk)["comparable"] == 0
    assert rep.summarize_watchout(junk)["comparable"] == 0
    assert rep.summarize_swap(junk)["comparable"] == 0
    assert rep.summarize_advice(junk)["comparable"] == 0
    assert rep.summarize_field_presence(junk)["advice"]["neither"] == 5


def test_records_missing_a_side_are_scored_as_absent():
    rows = [
        {"is_aram": True, "their_team": ["Zed"], "bench": ["Tristana"],
         "deterministic": {"advice": "Stay Ahri.", "summoners": "Flash + Heal"}},
        {"is_aram": True, "their_team": ["Zed"], "bench": ["Tristana"],
         "native": {"advice": "Stay Ahri.", "summoners": "Flash + Heal"}},
    ]
    assert rep.summarize_advice(rows)["comparable"] == 0
    assert rep.summarize_summoners(rows)["comparable"] == 0
    fp = rep.summarize_field_presence(rows)
    assert fp["advice"]["det_only"] == 1
    assert fp["advice"]["native_only"] == 1


def test_build_report_survives_a_malformed_log(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"native": {"advice": "Stay Ahri."}}\nNOT JSON\n{"trunc"\n'
                 '[1,2]\n\n{"deterministic": {}}\n', encoding="utf-8")
    r = rep.build_report(p)
    assert r["coverage"]["total"] == 2
    assert r["state"] == "awaiting_accrual"


# ---- 10. build_report shape + state machine ----


def test_build_report_shape(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri."},
                    native={"advice": "Stay Ahri."})])
    r = rep.build_report(p)
    assert r["schema"] == "champ_select_shadow_report/v1"
    for key in ("path", "min_sample", "coverage", "agreement", "field_presence",
                "flip_hint", "state"):
        assert key in r
    for field in rep._FIELDS:
        assert field in r["agreement"]
    # JSON-serializable end to end (no sets / tuples leak into the report)
    json.dumps(r, sort_keys=True)


def test_build_report_missing_path_is_awaiting_accrual(tmp_path):
    r = rep.build_report(tmp_path / "none.jsonl")
    assert r["coverage"]["total"] == 0
    assert r["state"] == "awaiting_accrual"
    assert "no shadow data" in r["flip_hint"]


def test_build_report_empty_file_is_awaiting_accrual(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    r = rep.build_report(p)
    assert r["coverage"]["total"] == 0
    assert r["state"] == "awaiting_accrual"


def test_state_awaiting_accrual_below_min_sample(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri."},
                    native={"advice": "Stay Ahri."})] * 3)
    r = rep.build_report(p)
    assert r["state"] == "awaiting_accrual"
    assert "3/20" in r["flip_hint"]


def test_state_ready_when_gate_met(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri - solid."},
                    native={"advice": "Stay Ahri, comp is fine."})] * 20)
    r = rep.build_report(p)
    assert r["agreement"]["advice"]["comparable"] == 20
    assert r["state"] == "ready"
    assert "gate MET" in r["flip_hint"]


def test_state_not_ready_below_gate(tmp_path):
    p = tmp_path / "c.jsonl"
    agree = _row(deterministic={"advice": "Stay Ahri - solid."},
                 native={"advice": "Stay Ahri, comp is fine."})
    disagree = _row(deterministic={"advice": "Swap to Tristana - range."},
                    native={"advice": "Stay Ahri, comp is fine."})
    _write(p, [agree] * 5 + [disagree] * 15)
    r = rep.build_report(p)
    assert r["agreement"]["advice"]["comparable"] == 20
    assert r["state"] == "not_ready"
    assert "below" in r["flip_hint"]


def test_min_sample_is_overridable(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri."},
                    native={"advice": "Stay Ahri."})] * 2)
    r = rep.build_report(p, min_sample=2)
    assert r["min_sample"] == 2
    assert r["state"] == "ready"


# ---- 11. main entrypoints ----


def test_main_human(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri.",
                                   "summoners": "Flash + Heal",
                                   "watchout": "Watch Zed (assassin)."},
                    native={"advice": "Stay Ahri.",
                            "summoners": "Flash + Heal",
                            "watchout": "Zed will burst you."})])
    assert rep.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    assert "[champ-select shadow]" in out
    assert "advice" in out
    assert "state:" in out


def test_main_json(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri."},
                    native={"advice": "Stay Ahri."})])
    assert rep.main(["--path", str(p), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "champ_select_shadow_report/v1"
    assert out["agreement"]["advice"]["comparable"] == 1


def test_main_on_a_missing_default_shaped_path_is_exit_zero(tmp_path, capsys):
    assert rep.main(["--path", str(tmp_path / "absent.jsonl"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "awaiting_accrual"


def test_main_min_sample_flag(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row(deterministic={"advice": "Stay Ahri."},
                    native={"advice": "Stay Ahri."})])
    assert rep.main(["--path", str(p), "--min-sample", "1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "ready"
