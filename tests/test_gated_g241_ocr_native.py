"""Tests for tools/gated_g241_ocr_native.py (G2-41 PREP, s144 lane gated c45).

Every input is hand-built (RM-906: no real game, match or player id) and no test
touches the screen, the relay or :2999: the grab, the fetches, the foreground
probe and the OCR are injected. These pin the stated predicates, the verdict
rules, the refuse-before-capture gate, and the source facts the tool's module
doc cites (no production caller of grab_native; the slow-field cache that makes
read_fast_fields unusable for an in-process A/B).
"""
from __future__ import annotations

import base64
import io
import subprocess
import sys
from pathlib import Path

import pytest

from tools import gated_g241_ocr_native as g241

ROOT = Path(__file__).resolve().parent.parent


def _t(wall, gt, gold, level):
    return {"wall": wall, "game_time": gt, "gold": gold, "level": level}


def _doc(gold=1234.6, level=7, gt=600.4):
    return {"activePlayer": {"currentGold": gold, "level": level},
            "gameData": {"gameTime": gt}}


# -- truth + predicates -------------------------------------------------------

def test_truth_from_floors_gold_and_rejects_bad_shapes():
    assert g241.truth_from(_doc(), 10.0) == _t(10.0, 600.4, 1234, 7)
    for bad in (None, {}, {"activePlayer": {}}, {"activePlayer": {"currentGold": 1},
                "gameData": {}}, _doc(level=True)):
        assert g241.truth_from(bad, 1.0) is None


@pytest.mark.parametrize("text,secs", [("10:00", 600), ("0:05", 5), ("59:59", 3599)])
def test_parse_clock(text, secs):
    assert g241.parse_clock(text) == secs


@pytest.mark.parametrize("text", ["10:0", "10:60", "x:00", "1000", None, 600])
def test_parse_clock_rejects(text):
    assert g241.parse_clock(text) is None


def test_level_predicate():
    t0, t1 = _t(100.0, 600.0, 1000, 7), _t(101.0, 601.0, 1002, 7)
    assert g241.grade_value("level", 7, t0, t1, 100.5)[0] == "MATCH"
    assert g241.grade_value("level", 1, t0, t1, 100.5)[0] == "MISS"
    assert g241.grade_value("level", None, t0, t1, 100.5)[0] == "NONE"
    assert g241.grade_value("level", 7, t0, _t(101.0, 601.0, 1002, 8), 100.5)[0] == "VOID"


def test_gold_predicate_bracket_and_lead():
    t0, t1 = _t(100.0, 600.0, 1000, 7), _t(102.0, 602.0, 1004, 7)
    assert g241.grade_value("gold", 1000, t0, t1, 101.0)[0] == "MATCH"
    assert g241.grade_value("gold", 1006, t0, t1, 101.0)[0] == "MATCH"   # +2 slack
    assert g241.grade_value("gold", 1007, t0, t1, 101.0)[0] == "MISS"
    assert g241.grade_value("gold", 998, t0, t1, 101.0)[0] == "MATCH"    # -2 slack
    assert g241.grade_value("gold", 997, t0, t1, 101.0)[0] == "MISS"
    # A frame captured 1 s BEFORE truth read 0 may show up to 3 g less.
    assert g241.grade_value("gold", 995, t0, t1, 99.0)[0] == "MATCH"
    # A dropped digit is a miss, not a near miss.
    assert g241.grade_value("gold", 100, t0, t1, 101.0)[0] == "MISS"


def test_gold_void_on_kill_or_buy():
    t0, t1 = _t(100.0, 600.0, 1000, 7), _t(101.0, 601.0, 1300, 7)
    assert g241.grade_value("gold", 1000, t0, t1, 100.5)[0] == "VOID"
    assert g241.grade_value("gold", 1000, t0, _t(101.0, 601.0, 200, 7), 100.5)[0] == "VOID"


def test_timer_predicate():
    t0, t1 = _t(100.0, 600.4, 1000, 7), _t(101.0, 601.4, 1000, 7)
    for ok in ("9:59", "10:00", "10:01", "10:02"):
        assert g241.grade_value("timer", ok, t0, t1, 100.5)[0] == "MATCH", ok
    assert g241.grade_value("timer", "10:03", t0, t1, 100.5)[0] == "MISS"
    assert g241.grade_value("timer", "9:58", t0, t1, 100.5)[0] == "MISS"
    # A relay frame 2 s older than truth read 0 may show a 2 s older clock.
    assert g241.grade_value("timer", "9:57", t0, t1, 98.0)[0] == "MATCH"
    assert g241.grade_value("timer", None, t0, t1, 100.5)[0] == "NONE"
    assert g241.grade_value("timer", "garbage", t0, t1, 100.5)[0] == "MISS"


def test_unknown_field_raises():
    with pytest.raises(ValueError):
        g241.grade_value("cs", 1, _t(0, 0, 0, 1), _t(0, 0, 0, 1), 0)


# -- verdict --------------------------------------------------------------------

def _sample(h: dict, n: dict) -> dict:
    return {"halved": {"grades": {f: [h[f], ""] for f in g241.FIELDS}},
            "native": {"grades": {f: [n[f], ""] for f in g241.FIELDS}}}


ALL_M = {"gold": "MATCH", "level": "MATCH", "timer": "MATCH"}
GOLD_MISS = {"gold": "MISS", "level": "MATCH", "timer": "MATCH"}
ALL_NONE = {"gold": "NONE", "level": "NONE", "timer": "NONE"}


def test_verdict_native_better():
    v = g241.verdict([_sample(GOLD_MISS, ALL_M)] * 3)
    assert v["verdict"] == "NATIVE_BETTER" and v["native_better_on"] == ["gold"]


def test_verdict_halved_better_wins_over_any_native_gain():
    s = [_sample({"gold": "MATCH", "level": "MISS", "timer": "MATCH"}, GOLD_MISS)] * 3
    assert g241.verdict(s)["verdict"] == "HALVED_BETTER"


def test_verdict_no_gain():
    assert g241.verdict([_sample(ALL_M, ALL_M)] * 3)["verdict"] == "NO_GAIN"


def test_verdict_one_sample_native_gain_is_not_enough():
    # One halved miss in 6 is what a single buy before truth read 0 can cause.
    s = [_sample(GOLD_MISS, ALL_M)] + [_sample(ALL_M, ALL_M)] * 5
    assert g241.verdict(s)["verdict"] == "NO_GAIN"
    s = [_sample(GOLD_MISS, ALL_M)] * 2 + [_sample(ALL_M, ALL_M)] * 4
    assert g241.verdict(s)["verdict"] == "NATIVE_BETTER"


@pytest.mark.parametrize("valid,h,n,want", [
    (5, 1, 3, "NATIVE_BETTER"), (10, 1, 3, "NATIVE_BETTER"), (10, 4, 6, "NATIVE_BETTER"),
    (10, 5, 7, "NATIVE_BETTER"), (7, 3, 5, "NATIVE_BETTER"), (5, 1, 2, "NO_GAIN"),
    (40, 10, 11, "NO_GAIN"), (5, 3, 3, "NO_GAIN"),
])
def test_verdict_two_sample_margin_is_exact(valid, h, n, want):
    # Exact fractions: a float compare read 1/5 vs 3/5 as under 2 samples.
    s = ([_sample(ALL_M, ALL_M)] * min(h, n)
         + [_sample(GOLD_MISS, ALL_M)] * (n - min(h, n))
         + [_sample(GOLD_MISS, GOLD_MISS)] * (valid - n))
    assert len(s) == valid
    assert g241.verdict(s)["verdict"] == want


def test_verdict_zero_matches_is_no_result_not_no_gain():
    assert g241.verdict([_sample(ALL_NONE, ALL_NONE)] * 3)["verdict"] == "NO_RESULT"


def test_verdict_too_few_valid_is_no_result():
    assert g241.verdict([_sample(GOLD_MISS, ALL_M)] * 2)["verdict"] == "NO_RESULT"
    void = {"gold": "VOID", "level": "VOID", "timer": "VOID"}
    assert g241.verdict([_sample(void, void)] * 5)["verdict"] == "NO_RESULT"


def test_verdict_ignores_a_path_missing_from_a_sample():
    s = [_sample(GOLD_MISS, ALL_M)] * 3 + [{"halved_void": "frame older than 2.0 s",
                                             "native": _sample(ALL_M, ALL_M)["native"]}]
    v = g241.verdict(s)
    assert v["fields"]["gold"]["halved"]["valid"] == 3
    assert v["fields"]["gold"]["native"]["valid"] == 4


# -- collect: gates and wiring ---------------------------------------------------

class _Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        self.now += 0.1
        return self.now


def _fail(*_a, **_k):
    raise AssertionError("must not be called")


def test_collect_refuses_before_any_capture_when_not_in_game():
    code, rep = g241.collect(truth_fetch=lambda: None, relay_fetch=_fail,
                             native_grab=_fail, foreground=_fail, token=_fail,
                             ocr=_fail)
    assert code == 2 and rep["verdict"]["verdict"] == "NOT_IN_GAME"
    assert rep["samples"] == []


def test_collect_no_token_exit_3_and_no_capture():
    code, rep = g241.collect(truth_fetch=_doc, relay_fetch=_fail, native_grab=_fail,
                             foreground=_fail, token=lambda: ("", "none"), ocr=_fail)
    assert code == 3 and rep["samples"] == []


def _ocr_for(values_by_b64):
    def ocr(b64):
        return {"frame": [1280, 720] if b64 == "H" else [2560, 1440],
                "values": values_by_b64[b64]}
    return ocr


def test_collect_grades_both_paths():
    clock = _Clock()
    vals = {"H": {"gold": 1234, "level": 7, "timer": "10:00"},
            "N": {"gold": 1234, "level": 7, "timer": "10:00"}}
    code, rep = g241.collect(samples=3, truth_fetch=_doc,
                             relay_fetch=lambda tok: ("H", {"ts": clock.now, "source": "gdi",
                                                            "width": 1280, "height": 720}),
                             native_grab=lambda: {"ok": True, "b64": "N"},
                             foreground=lambda: True, token=lambda: ("SECRET-zq9", "env"),
                             ocr=_ocr_for(vals), clock=clock, sleep=lambda _s: None)
    assert code == 0 and len(rep["samples"]) == 3
    s = rep["samples"][0]
    assert s["halved"]["grades"]["gold"][0] == "MATCH"
    assert s["native"]["grades"]["timer"][0] == "MATCH"
    assert s["halved_meta"]["source"] == "gdi"
    assert "SECRET-zq9" not in repr(rep)
    assert g241.verdict(rep["samples"])["verdict"] == "NO_GAIN"


def test_collect_skips_native_grab_when_league_not_foreground():
    clock = _Clock()
    code, rep = g241.collect(samples=1, truth_fetch=_doc,
                             relay_fetch=lambda tok: ("H", {"ts": clock.now}),
                             native_grab=_fail, foreground=lambda: False,
                             token=lambda: ("tok", "env"),
                             ocr=_ocr_for({"H": {"gold": 1234, "level": 7, "timer": "10:00"}}),
                             clock=clock, sleep=lambda _s: None)
    s = rep["samples"][0]
    assert s["native_void"] == "League not foreground" and "native" not in s


def test_collect_voids_a_stale_relay_frame():
    clock = _Clock()
    code, rep = g241.collect(samples=1, max_age=2.0, truth_fetch=_doc,
                             relay_fetch=lambda tok: ("H", {"ts": clock.now - 30.0}),
                             native_grab=lambda: {"ok": False, "error": "x", "reason": "locked"},
                             foreground=lambda: True, token=lambda: ("tok", "env"),
                             ocr=_fail, clock=clock, sleep=lambda _s: None)
    s = rep["samples"][0]
    assert "halved" not in s and "older than" in s["halved_void"]
    assert s["native_void"] == "locked"


@pytest.mark.parametrize("meta,why", [
    ({}, "frame carries no ts"),
    ({"ts": 0}, "frame carries no ts"),
    ({"ts": True}, "frame carries no ts"),
    ({"ts": "FUTURE"}, "frame ts in the future"),
])
def test_collect_voids_a_relay_frame_without_a_usable_ts(meta, why):
    clock = _Clock()
    if meta.get("ts") == "FUTURE":
        meta = {"ts": 10_000.0}
    code, rep = g241.collect(samples=1, truth_fetch=_doc,
                             relay_fetch=lambda tok: ("H", dict(meta)),
                             native_grab=lambda: {"ok": True, "b64": "N"},
                             foreground=lambda: True, token=lambda: ("tok", "env"),
                             ocr=_ocr_for({"N": {}}), clock=clock, sleep=lambda _s: None)
    s = rep["samples"][0]
    assert "halved" not in s and s["halved_void"] == why
    if why == "frame carries no ts":
        assert s["halved_meta"]["age_s"] is None
    assert "native" in s


def test_collect_relay_failure_is_void_with_its_reason():
    clock = _Clock()
    code, rep = g241.collect(samples=1, truth_fetch=_doc,
                             relay_fetch=lambda tok: (None, {"error": "URLError"}),
                             native_grab=lambda: {"ok": True, "b64": "N"},
                             foreground=lambda: True, token=lambda: ("tok", "env"),
                             ocr=_ocr_for({"N": {}}), clock=clock, sleep=lambda _s: None)
    assert rep["samples"][0]["halved_void"] == "URLError"


def test_collect_stops_when_the_game_ends():
    clock = _Clock()
    calls = iter([_doc(), _doc(), None])
    code, rep = g241.collect(samples=5, truth_fetch=lambda: next(calls),
                             relay_fetch=lambda tok: ("H", {"ts": clock.now}),
                             native_grab=lambda: {"ok": True, "b64": "N"},
                             foreground=lambda: True, token=lambda: ("tok", "env"),
                             ocr=_ocr_for({"H": {}, "N": {}}), clock=clock,
                             sleep=lambda _s: None)
    assert rep["samples"][-1]["void"] == "game ended"


# -- ocr_fields against the real vision_tesseract helpers ----------------------

def _jpeg_b64(w, h):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 10, 10)).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_ocr_fields_scales_boxes_and_bypasses_cadence(monkeypatch):
    from core import vision_tesseract as vt
    monkeypatch.setattr(vt, "_ensure_tesseract", lambda: None)
    monkeypatch.setattr(vt, "_REGIONS_CACHE",
                        {"gold": [1463, 1407, 1549, 1433], "level": [10, 10, 40, 40],
                         "timer": [2400, 0, 2500, 40]})
    monkeypatch.setattr(vt, "_BASE_CACHE", (2560, 1440))
    seen = []

    def parse(name, crop):
        seen.append((name, crop.size))
        return {"gold": 1234, "level": 7, "timer": "10:00"}[name]

    monkeypatch.setattr(vt, "_parse_field", parse)
    monkeypatch.setattr(vt, "read_fast_fields", _fail)
    half = g241.ocr_fields(_jpeg_b64(1280, 720), vt=vt)
    native = g241.ocr_fields(_jpeg_b64(2560, 1440), vt=vt)
    assert half["boxes"]["gold"] == [731, 703, 774, 716]      # the R98 0.5x map
    assert native["boxes"]["gold"] == [1463, 1407, 1549, 1433]
    # timer is read on BOTH frames (read_fast_fields would serve frame 2 from
    # its slow-field cache on 4 calls in 5).
    assert [n for n, _ in seen].count("timer") == 2
    assert half["values"]["timer"] == native["values"]["timer"] == "10:00"


def test_ocr_fields_one_failing_field_is_none(monkeypatch):
    from core import vision_tesseract as vt
    monkeypatch.setattr(vt, "_ensure_tesseract", lambda: None)
    monkeypatch.setattr(vt, "_REGIONS_CACHE", {"gold": [0, 0, 10, 10], "level": [0, 0, 10, 10]})
    monkeypatch.setattr(vt, "_BASE_CACHE", (1280, 720))

    def parse(name, crop):
        if name == "gold":
            raise RuntimeError("tesseract gone")
        return 3

    monkeypatch.setattr(vt, "_parse_field", parse)
    out = g241.ocr_fields(_jpeg_b64(1280, 720), vt=vt)
    assert out["values"] == {"gold": None, "level": 3, "timer": None}
    assert out["errors"] == {"gold": "RuntimeError"}


# -- the source facts the module doc cites ------------------------------------

def test_slow_field_cadence_fact_still_holds():
    from core import vision_tesseract as vt
    assert "timer" in vt._SLOW_FIELDS and vt._SLOW_MODULO > 1
    assert isinstance(vt._slow_cache, dict) and isinstance(vt._DROP_FIELDS, set)


def test_grab_native_still_has_no_production_caller():
    # -w: core/minimap_blob_detect.py's _grab_native_minimap is a different name.
    out = subprocess.run(["git", "grep", "--untracked", "-l", "-w", "grab_native", "--", "*.py"],
                         cwd=ROOT, capture_output=True, text=True, check=False)
    files = {p for p in out.stdout.split() if not p.startswith("tests/")}
    assert files == {"core/screen_grab.py", "tools/gated_g241_ocr_native.py"}, files


def test_relay_frame_is_still_downscaled_to_1280():
    from vision_server import _frame
    assert _frame._SELF_GRAB_MAX_WIDTH == 1280


def test_tool_never_writes(monkeypatch):
    src = (ROOT / "tools" / "gated_g241_ocr_native.py").read_text(encoding="utf-8")
    for banned in ("write_text", "write_bytes", ".save(", "open(\"w", "unlink", "replace("):
        assert banned not in src, banned


def test_cli_help_runs():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "gated_g241_ocr_native.py"),
                          "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                         check=False)
    assert out.returncode == 0 and "--samples" in out.stdout
