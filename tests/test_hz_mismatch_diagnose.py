"""HZ-mismatch-diagnose tests. Pins the net_swing parse, the bucketing, the
mechanical per-class CALIBRATION-vs-MODEL-ERROR verdict, the partition guard
(class counts sum to exactly the genuine-mismatch population the shadow report
reports), the engine-drift block, and the pure/deterministic markdown render.

All synthetic, tmp_path, ASCII-only. Mirrors tests/test_hz_shadow_report.py.
"""
from __future__ import annotations

import json

from tools import hz_mismatch_diagnose as diag
from tools import hz_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ---- net_swing / expected_outcome parse ----


def test_parse_expected_outcome_happy():
    out = diag.parse_expected_outcome(
        "net swing -0.12; you remove 30% of Caitlyn, they remove 42% of you"
    )
    assert out == {"net_swing": -0.12, "pct_enemy_removed": 0.30,
                   "pct_my_removed": 0.42}


def test_parse_expected_outcome_spaced_enemy_name():
    out = diag.parse_expected_outcome(
        "net swing +0.07; you remove 50% of Aurelion Sol, they remove 43% of you"
    )
    assert out["net_swing"] == 0.07
    assert out["pct_enemy_removed"] == 0.50
    assert out["pct_my_removed"] == 0.43


def test_parse_expected_outcome_garbage_is_none():
    assert diag.parse_expected_outcome("") is None
    assert diag.parse_expected_outcome(None) is None
    assert diag.parse_expected_outcome("no scalar here") is None
    assert diag.parse_expected_outcome(123) is None


# ---- bucket_index boundaries (the 12 pinned cases) ----


def test_bucket_index_boundaries():
    cases = {
        -0.6: 0, -0.5: 0, -0.49: 1, -0.18: 1, -0.17: 2, -0.05: 2,
        -0.04: 3, 0.0: 3, 0.01: 4, 0.09: 4, 0.10: 5, 0.5: 5,
    }
    for swing, want in cases.items():
        assert diag.bucket_index(swing) == want, swing


def test_bucket_index_clamps_extremes():
    assert diag.bucket_index(-99.0) == 0
    assert diag.bucket_index(99.0) == 5


# ---- record_scalars from a log record ----


def test_record_scalars_from_choices():
    rec = {"choices": [{"key": "A", "label": "Back off Caitlyn",
                        "expected_outcome": "net swing -0.12; you remove 30% "
                        "of Caitlyn, they remove 42% of you"}]}
    out = diag.record_scalars(rec)
    assert out == {"net_swing": -0.12, "pct_enemy_removed": 0.30,
                   "pct_my_removed": 0.42}


def test_record_scalars_empty_choices_none():
    assert diag.record_scalars({"choices": []}) is None
    assert diag.record_scalars({}) is None
    assert diag.record_scalars({"choices": [{"label": "x"}]}) is None  # no EO


# ---- genuine-mismatch fixtures: verify they classify to the intended pair ----


def _bo_to_hold_rec(swing, enemy="Caitlyn"):
    """A covered back_off precompute vs a Haiku 'hold' native -> genuine
    mismatch class (back_off, hold). The A-label classifies to back_off, the
    native_action to hold; record_agreement returns a non-agreeing pair."""
    pct_e, pct_m = 30, 42
    eo = (f"net swing {swing:+.2f}; you remove {pct_e}% of {enemy}, "
          f"they remove {pct_m}% of you")
    return {"mode": "aram", "my_champion": "Annie", "enemy": enemy,
            "covered": True,
            "choices": [{"key": "A", "label": f"Back off {enemy}",
                         "expected_outcome": eo}],
            "native_action": "hold and farm", "native_choices": []}


def _bo_to_allin_rec(swing, enemy="Caitlyn"):
    """A covered back_off precompute vs a Haiku 'all_in' native -> class
    (back_off, all_in)."""
    eo = (f"net swing {swing:+.2f}; you remove 30% of {enemy}, "
          f"they remove 42% of you")
    return {"mode": "aram", "my_champion": "Annie", "enemy": enemy,
            "covered": True,
            "choices": [{"key": "A", "label": f"Back off {enemy}",
                         "expected_outcome": eo}],
            "native_action": "all in now", "native_choices": []}


def test_fixtures_classify_to_intended_pair():
    # Guard: the synthetic records actually land in the pair the tests assume.
    p1 = rep.record_agreement(_bo_to_hold_rec(-0.12))
    assert p1 == {"precompute": "back_off", "native": "hold", "agree": False}
    p2 = rep.record_agreement(_bo_to_allin_rec(-0.6))
    assert p2 == {"precompute": "back_off", "native": "all_in", "agree": False}


# ---- per-class bucketing + verdict ----


def test_class_back_off_hold_calibration_zone():
    # back_off -> hold with swings clustered in the (-0.18,-0.05] hold zone:
    # buckets[2] dominant, median in calibration zone -> CALIBRATION verdict.
    recs = [_bo_to_hold_rec(s) for s in (-0.06, -0.10, -0.12, -0.15, -0.17)]
    report = diag.diagnose(recs, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "back_off", "hold")
    assert cls["count"] == 5
    assert cls["buckets"][2] == 5  # all in the hold zone
    assert cls["verdict"].startswith("CALIBRATION")


def test_class_back_off_all_in_model_error_zone():
    # back_off -> all_in with deep-negative swings: buckets[0] dominant,
    # median <= -0.30 -> MODEL-ERROR (enemy-full-combo over-kill).
    recs = [_bo_to_allin_rec(s) for s in (-0.5, -0.6, -0.7, -0.8)]
    # (back_off, all_in) is not a default class -> need --all-classes
    report = diag.diagnose(recs, all_classes=True, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "back_off", "all_in")
    assert cls["count"] == 4
    assert cls["buckets"][0] == 4
    assert cls["verdict"].startswith("MODEL-ERROR")


def test_class_hold_all_in_under_called_non_negative():
    # A precompute 'hold' (A-label "Hold and farm...") vs a Haiku ALL-IN with a
    # positive swing -> under-called a non-negative trade -> CALIBRATION.
    eo = "net swing +0.13; you remove 55% of Lux, they remove 30% of you"
    recs = [{"mode": "sr", "my_champion": "Garen", "enemy": "Lux",
             "covered": True,
             "choices": [{"key": "A", "label": "Hold and farm this window",
                          "expected_outcome": eo}],
             "native_action": "all in now", "native_choices": []}]
    # confirm the fixture lands in (hold, all_in)
    assert rep.record_agreement(recs[0]) == {
        "precompute": "hold", "native": "all_in", "agree": False}
    report = diag.diagnose(recs, now="2026-06-21T00:00:00Z")
    cls = _find_class(report, "hold", "all_in")
    assert cls["count"] == 1
    assert cls["median_swing"] == 0.13
    assert cls["verdict"].startswith("CALIBRATION (under-called")


def test_classify_class_verdict_table():
    # table-driven over every branch of classify_class_verdict
    passive = ("back_off", "hold")
    # no-data
    assert diag.classify_class_verdict(passive, [0, 0, 0, 0, 0, 0], 0.0) == \
        "no-data"
    # deep>=0.5 -> MODEL-ERROR
    v = diag.classify_class_verdict(passive, [3, 1, 0, 0, 0, 0], -0.4)
    assert v.startswith("MODEL-ERROR")
    # median<=-0.30 (deep<0.5) -> MODEL-ERROR
    v = diag.classify_class_verdict(passive, [1, 3, 0, 0, 0, 0], -0.31)
    assert v.startswith("MODEL-ERROR")
    # clustered near threshold (buckets 2+3+4 >=0.5, median>-0.18) -> CALIBRATION
    v = diag.classify_class_verdict(passive, [0, 0, 3, 1, 0, 0], -0.10)
    assert v.startswith("CALIBRATION (clustered")
    # non-negative median, mass NOT majority in the near-threshold buckets
    # (else the clustered branch wins first) -> CALIBRATION under-called
    v = diag.classify_class_verdict(passive, [0, 0, 0, 0, 0, 2], 0.13)
    assert v.startswith("CALIBRATION (under-called")
    # mixed: deep<0.5, near-threshold buckets not majority, median negative but
    # above the -0.30 model-error gate -> no dominant zone -> MIXED
    v = diag.classify_class_verdict(passive, [0, 1, 0, 0, 0, 1], -0.10)
    assert v.startswith("MIXED")
    # native-more-passive branch: firmly positive -> HAIKU-NOISE/CV-VETO
    v = diag.classify_class_verdict(("trade", "back_off"),
                                    [0, 0, 0, 0, 0, 4], 0.22)
    assert v.startswith("HAIKU-NOISE")
    # native-more-passive, small edge -> AMBIGUOUS
    v = diag.classify_class_verdict(("even", "back_off"),
                                    [0, 0, 1, 1, 0, 0], -0.02)
    assert v.startswith("AMBIGUOUS")


# ---- partition guard: class counts == shadow-report genuine-mismatch count ----


def test_partition_matches_shadow_report_population():
    records = [
        _bo_to_hold_rec(-0.10),
        _bo_to_hold_rec(-0.12),
        _bo_to_allin_rec(-0.6),
        # an AGREEING tick (not a mismatch) - must NOT appear in any class
        {"mode": "aram", "covered": True,
         "choices": [{"key": "A", "label": "Trade now",
                      "expected_outcome": "net swing -0.02; you remove 40% of "
                      "Ashe, they remove 41% of you"}],
         "native_action": "TRADE", "native_choices": []},
        # a hold->all_in mismatch
        {"mode": "sr", "covered": True,
         "choices": [{"key": "A", "label": "Hold and farm this window",
                      "expected_outcome": "net swing +0.04; you remove 50% of "
                      "Lux, they remove 40% of you"}],
         "native_action": "all in", "native_choices": []},
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    summ = rep.summarize_agreement(records)
    expected = summ["comparable_covered"] - summ["agree"]
    total_in_classes = sum(c["count"] for c in report["classes"])
    assert total_in_classes == expected
    assert report["genuine_mismatches"] == expected


def test_non_laning_native_state_excluded():
    records = [
        # dead-state native -> excluded by rep guard, no class
        {"mode": "aram", "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.50; you remove 10% of "
                      "Ashe, they remove 60% of you"}],
         "native_action": "WAIT RESPAWN", "native_choices": []},
        # one real mismatch survives
        _bo_to_hold_rec(-0.10),
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    assert report["genuine_mismatches"] == 1
    assert _find_class(report, "back_off", "hold")["count"] == 1


def test_native_recall_excluded():
    records = [
        # native recall -> cross-axis, dropped by record_agreement
        {"mode": "sr", "covered": True,
         "choices": [{"key": "A", "label": "Back off Ashe",
                      "expected_outcome": "net swing -0.20; you remove 20% of "
                      "Ashe, they remove 40% of you"},
                     {"key": "B", "label": "Back soon"}],
         "native_action": "RECALL NOW", "native_choices": []},
        _bo_to_hold_rec(-0.10),
    ]
    report = diag.diagnose(records, all_classes=True,
                           now="2026-06-21T00:00:00Z")
    assert report["genuine_mismatches"] == 1


# ---- engine-drift block ----


def test_drift_block_counts_and_warns():
    records = [
        dict(_bo_to_hold_rec(-0.10), engine_version="1.149.0"),
        dict(_bo_to_hold_rec(-0.12), engine_version="1.120.0"),
        dict(_bo_to_hold_rec(-0.15), engine_version="1.120.0"),
    ]
    report = diag.diagnose(records, current_engine="1.149.0",
                           now="2026-06-21T00:00:00Z")
    drift = report["drift"]
    assert drift["current_engine"] == "1.149.0"
    assert drift["logged_under_current"] == 1
    assert drift["logged_under_other"] == 2
    assert drift["by_engine_version"]["1.120.0"] == 2
    assert drift["by_engine_version"]["1.149.0"] == 1
    md = diag.render_markdown(report)
    assert "WARNING" in md  # logged_under_other > 0 surfaces the warning


def test_drift_no_warning_when_all_current():
    records = [dict(_bo_to_hold_rec(-0.10), engine_version="1.149.0")]
    report = diag.diagnose(records, current_engine="1.149.0",
                           now="2026-06-21T00:00:00Z")
    assert report["drift"]["logged_under_other"] == 0


# ---- markdown: pure, deterministic, ASCII, anti-circularity footer ----


def test_render_markdown_ascii_deterministic_and_footer():
    records = [_bo_to_hold_rec(s) for s in (-0.10, -0.12)]
    report = diag.diagnose(records, now="2026-06-21T12:00:00Z")
    md1 = diag.render_markdown(report)
    md2 = diag.render_markdown(report)
    assert md1 == md2  # pure: byte-identical across calls
    assert md1.isascii()  # no em-dash, smart quote, or box-drawing char
    # anti-circularity footer mentions both fix sites + the no-tune caveat
    assert "core/precomputed_laning_coach.py" in md1
    assert "core/laning_scenario_precompute.py" in md1
    assert "ground-truth" in md1.lower()
    assert "2026-06-21T12:00:00Z" in md1  # injected clock in the body


def test_write_markdown_creates_parent_and_file(tmp_path):
    report = diag.diagnose([_bo_to_hold_rec(-0.10)],
                           now="2026-06-21T00:00:00Z")
    target = tmp_path / "nested" / "deep" / "HZ_MISMATCH_DIAGNOSE.md"
    diag.write_markdown(report, target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").isascii()


# ---- CLI ----


def test_main_json_fail_soft_missing_log(tmp_path, capsys):
    rc = diag.main(["--choice-path", str(tmp_path / "nope.jsonl"),
                    "--json", "--no-write"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["genuine_mismatches"] == 0
    assert out["total_records"] == 0


def test_main_writes_markdown_to_md_path(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [_bo_to_hold_rec(-0.10), _bo_to_hold_rec(-0.12)])
    md = tmp_path / "out" / "HZ_MISMATCH_DIAGNOSE.md"
    rc = diag.main(["--choice-path", str(c), "--md-path", str(md)])
    assert rc == 0
    assert md.exists()
    body = md.read_text(encoding="utf-8")
    assert body.isascii()
    assert "back_off" in body
    # human summary printed
    out = capsys.readouterr().out
    assert "pre=back_off" in out or "back_off" in out


def test_main_human_summary_runs(tmp_path, capsys):
    c = tmp_path / "c.jsonl"
    _write(c, [_bo_to_hold_rec(-0.10)])
    rc = diag.main(["--choice-path", str(c), "--no-write"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "back_off" in out


# ---- helper ----


def _find_class(report, pre, native):
    for c in report["classes"]:
        if c["precompute"] == pre and c["native"] == native:
            return c
    raise AssertionError(f"class ({pre},{native}) not in report: "
                         f"{[(c['precompute'], c['native']) for c in report['classes']]}")
