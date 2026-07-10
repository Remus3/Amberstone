"""OCR shadow report tests - tools.ocr_shadow_report. Pins the per-field
OCR-vs-Sonnet match math, the present/matched semantics that mirror
core.vision_routing._log_ocr_shadow (match = ocr_val is not None and
ocr_val == sonnet_val), the two-part flip gate (samples >= MIN AND match_rate
>= GATE), the KNOWN_FIELDS seed, and the JSON/human shapes over synthetic
shadow logs. This is the Lane E OCR-migration flip-readiness gate; it FLAGS
readiness only and never authorizes an OCR-only flip.
"""
from __future__ import annotations

import json

from tools import ocr_shadow_report as rep


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _row(field, ocr_val, sonnet_val, ts=1.0):
    """One shadow row exactly as core.vision_routing._log_ocr_shadow writes it."""
    return {
        "ts": ts,
        "field": field,
        "ocr_val": ocr_val,
        "sonnet_val": sonnet_val,
        "match": ocr_val is not None and ocr_val == sonnet_val,
    }


# ---- 1. load_jsonl fail-soft ----


def test_load_jsonl_fail_soft_missing(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nNOT JSON\n\n{"b":2}\n', encoding="utf-8")
    assert rep.load_jsonl(p) == [{"a": 1}, {"b": 2}]


# ---- 2. KNOWN_FIELDS guard (mirrors the coach shadow field lists) ----


def test_known_fields_are_the_eight_coach_shadow_numerics():
    # coaches/aram_coach.py:513 (_ARAM_SHADOW_FIELDS) and
    # coaches/arena_coach.py:1122 (SHADOW_FIELDS) both register these eight.
    assert set(rep.KNOWN_FIELDS) == {
        "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
        "gold", "level", "cs", "kda",
    }


# ---- 3. present / matched semantics ----


def test_row_present_and_matched():
    # OCR produced a value that equals Sonnet -> present + matched
    assert rep._row_present(_row("gold", 100, 100)) is True
    assert rep._row_matched(_row("gold", 100, 100)) is True
    # OCR produced a value that differs -> present, not matched
    assert rep._row_present(_row("gold", 90, 100)) is True
    assert rep._row_matched(_row("gold", 90, 100)) is False
    # OCR missed the field entirely -> not present, not matched
    assert rep._row_present(_row("gold", None, 100)) is False
    assert rep._row_matched(_row("gold", None, 100)) is False


def test_row_matched_trusts_logged_match_bool():
    # The logged match flag is authoritative when it is a real bool - even if
    # it contradicts the values (the capture-time verdict wins).
    assert rep._row_matched({"ocr_val": 5, "sonnet_val": 5, "match": True}) is True
    assert rep._row_matched({"ocr_val": 5, "sonnet_val": 5, "match": False}) is False


def test_row_matched_recomputes_when_match_absent():
    assert rep._row_matched({"ocr_val": 7, "sonnet_val": 7}) is True
    assert rep._row_matched({"ocr_val": 7, "sonnet_val": 8}) is False
    assert rep._row_matched({"ocr_val": None, "sonnet_val": 8}) is False


# ---- 4. summarize_fields math ----


def test_summarize_fields_per_field_math():
    rows = [
        _row("gold", 100, 100),   # matched
        _row("gold", 90, 100),    # present, mismatch
        _row("gold", None, 100),  # ocr miss
    ]
    out = rep.summarize_fields(rows, gate=0.90, min_samples=2)
    g = out["gold"]
    assert g["samples"] == 3
    assert g["ocr_present"] == 2
    assert g["matches"] == 1
    assert g["match_rate"] == round(1 / 3, 4)
    assert g["present_rate"] == round(2 / 3, 4)
    assert g["accuracy_when_present"] == round(1 / 2, 4)


def test_summarize_fields_seeds_all_known_fields_zeroed():
    out = rep.summarize_fields([], gate=0.90, min_samples=2)
    for f in rep.KNOWN_FIELDS:
        assert out[f]["samples"] == 0
        assert out[f]["match_rate"] == 0.0
        assert out[f]["flip_eligible"] is False


def test_summarize_fields_includes_unknown_observed_field():
    out = rep.summarize_fields([_row("mystery", 1, 1)], gate=0.9, min_samples=1)
    assert "mystery" in out
    assert out["mystery"]["samples"] == 1


# ---- 5. two-part flip gate (samples >= MIN AND match_rate >= GATE) ----


def test_flip_gate_met_needs_both_samples_and_rate():
    rows = [_row("level", 5, 5), _row("level", 6, 6), _row("level", 7, 7)]
    out = rep.summarize_fields(rows, gate=0.90, min_samples=2)
    assert out["level"]["flip_eligible"] is True


def test_flip_gate_blocked_below_rate_even_with_samples():
    rows = [_row("cs", 10, 10), _row("cs", 11, 99), _row("cs", 12, 98)]
    out = rep.summarize_fields(rows, gate=0.90, min_samples=2)
    assert out["cs"]["flip_eligible"] is False
    assert "gate" in out["cs"]["reason"].lower()


def test_flip_gate_blocked_below_samples_even_at_perfect_rate():
    rows = [_row("kda", "1/0/2", "1/0/2")]  # 100% match but only 1 sample
    out = rep.summarize_fields(rows, gate=0.90, min_samples=50)
    assert out["kda"]["match_rate"] == 1.0
    assert out["kda"]["flip_eligible"] is False
    assert "sample" in out["kda"]["reason"].lower()


# ---- 6. build_report shape + fail-soft ----


def test_build_report_shape(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 100, 100)])
    r = rep.build_report(p, gate=0.90, min_samples=1)
    assert r["schema"] == "ocr_shadow_report/v1"
    for key in ("total", "gate", "min_samples", "fields", "eligible_fields",
                "flip_ready_hint"):
        assert key in r
    assert r["total"] == 1
    assert "gold" in r["eligible_fields"]


def test_build_report_empty_is_fail_soft(tmp_path):
    r = rep.build_report(tmp_path / "none.jsonl")
    assert r["total"] == 0
    assert r["eligible_fields"] == []
    assert "no ocr shadow data" in r["flip_ready_hint"].lower()


# ---- 7. flip hint is NOT an authorization ----


def test_flip_hint_flags_eligible_without_authorizing(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 5, 5), _row("gold", 6, 6)])
    r = rep.build_report(p, gate=0.90, min_samples=2)
    hint = r["flip_ready_hint"].lower()
    assert "gold" in hint
    assert "not a flip authorization" in hint


def test_flip_hint_none_eligible(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 5, 99)])
    r = rep.build_report(p, gate=0.90, min_samples=2)
    assert "no field" in r["flip_ready_hint"].lower()


# ---- 8. main entrypoints ----


def test_main_human(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 100, 100)])
    rc = rep.main(["--path", str(p), "--min-samples", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[fields]" in out
    assert "hint:" in out


def test_main_json(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 100, 100)])
    rc = rep.main(["--path", str(p), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "ocr_shadow_report/v1"


def test_main_gate_and_min_samples_flags(tmp_path, capsys):
    p = tmp_path / "c.jsonl"
    _write(p, [_row("gold", 5, 5), _row("gold", 6, 6)])
    rc = rep.main(["--path", str(p), "--json", "--gate", "0.5", "--min-samples", "2"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate"] == 0.5
    assert out["min_samples"] == 2
    assert "gold" in out["eligible_fields"]
