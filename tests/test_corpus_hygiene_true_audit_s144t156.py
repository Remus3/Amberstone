"""True-audit s144 cycle 156: core/corpus_hygiene.py never raises on junk input.

Each finding has its own test, named for its provisional id. The module rule
these pin: an UNKNOWN value is never read as a measured exclusion (a missing,
negative, junk or non-finite duration is not a remake), but a blob whose
SHAPE is wrong is not a match at all and is never mined.
"""
from __future__ import annotations

import json
import math

import pytest

from core import corpus_hygiene as ch


def _match(duration=1600, early=False, **info_extra):
    info = {"gameDuration": duration,
            "participants": [{"participantId": 1,
                              "gameEndedInEarlySurrender": early}]}
    info.update(info_extra)
    return {"info": info}


def _sidecar(tmp_path, blob, name="s.json", prefix=b""):
    p = tmp_path / name
    p.write_bytes(prefix + json.dumps(blob).encode("utf-8"))
    return p


# ------------------------------------------------- characterization (pinned)

@pytest.mark.parametrize("duration,include", [
    (1600, True), (300, True), (299, False), (70, False), (1, False),
    (299.5, False), (300.0, True), ("1600", True), ("120", False),
    (None, True), (0, True),
])
def test_characterization_duration_verdicts(duration, include):
    assert ch.judge(_match(duration=duration)).include is include


def test_characterization_remake_reason_names_the_seconds():
    assert ch.judge(_match(duration=70)).reason == "remake (70s)"


def test_characterization_missing_info_is_not_excluded():
    assert ch.judge({}).include is True
    assert ch.judge({"info": None}).include is True
    assert ch.judge({"info": {"participants": []}}).include is True


def test_characterization_early_surrender_true_excludes():
    v = ch.judge(_match(early=True))
    assert v.include is False and v.reason == "early surrender"


# ------------------------------------------------ RM-1925 negative duration

@pytest.mark.parametrize("duration", [-5, -1, -299, "-120", -0.5, 0.5])
def test_t461_negative_or_sub_second_duration_is_unknown_not_a_remake(duration):
    v = ch.judge(_match(duration=duration))
    assert v.include is True, v.reason


# ------------------------------------- RM-1926 non-finite / junk duration

@pytest.mark.parametrize("duration", [
    float("inf"), float("-inf"), float("nan"), "abc", "", "inf", "nan",
    [1600], {"s": 1600}, True, False, object(),
])
def test_t462_junk_duration_never_raises_and_is_unknown(duration):
    v = ch.judge(_match(duration=duration))
    assert v.include is True, v.reason


def test_t462_numeric_string_with_fraction_parses():
    assert ch.judge(_match(duration="120.0")).include is False
    assert ch.judge(_match(duration=" 1600.5 ")).include is True


def test_t462_huge_int_duration_does_not_raise():
    assert ch.judge(_match(duration=10 ** 400)).include is True


# ------------------------------------ RM-1927 millisecond-era gameDuration

def test_t463_millisecond_remake_is_excluded():
    # Pre-11.20 Match-V5 blobs carry gameDuration in MILLISECONDS; 120000 ms
    # is a two-minute remake, not a 33-hour game. Same threshold as
    # tools/mine_event_patterns.py _minutes (> 60000 reads as ms).
    v = ch.judge(_match(duration=120000))
    assert v.include is False
    assert v.reason == "remake (120s)"


def test_t463_millisecond_full_game_is_included():
    assert ch.judge(_match(duration=1800000)).include is True


def test_t463_threshold_matches_the_miner():
    # 60000 itself is still read as seconds, exactly as the miner reads it.
    assert ch.judge(_match(duration=60000)).include is True
    assert ch.judge(_match(duration=60001)).include is False


# ------------------------------------------- RM-1928 malformed blob shapes

@pytest.mark.parametrize("match", [
    None, [], ["info"], "match", 5,
    {"info": []}, {"info": "x"}, {"info": 5},
    {"info": {"gameDuration": 1600, "participants": {"a": 1}}},
    {"info": {"gameDuration": 1600, "participants": "abc"}},
    {"info": {"gameDuration": 1600, "participants": 7}},
    {"info": {"gameDuration": 1600, "participants": [None]}},
    {"info": {"gameDuration": 1600, "participants": [{"x": 1}, "p2"]}},
])
def test_t464_malformed_blob_never_raises_and_is_never_mined(match):
    v = ch.judge(match)
    assert v.include is False
    assert v.reason.startswith("malformed")


def test_t464_partition_carries_malformed_to_drop():
    keep, drop = ch.partition([(None, None), (_match(), None)])
    assert len(keep) == 1
    assert drop == [(None, "malformed match")]


# ----------------------------------------- RM-1929 early-surrender parsing

@pytest.mark.parametrize("flag", ["false", "False", "0", "no", "off", "", 0,
                                  0.0, "0.0", " FALSE ", None, False])
def test_t465_explicit_false_spellings_do_not_exclude(flag):
    assert ch.judge(_match(early=flag)).include is True


@pytest.mark.parametrize("flag", [True, 1, "true", "1", "yes"])
def test_t465_true_spellings_exclude(flag):
    assert ch.judge(_match(early=flag)).include is False


def test_t465_flag_on_a_later_seat_is_seen():
    m = {"info": {"gameDuration": 1600, "participants": [
        {"participantId": 1},
        {"participantId": 2, "gameEndedInEarlySurrender": True}]}}
    assert ch.judge(m).include is False


# ------------------------------------------ RM-1930 malformed sidecar JSON

@pytest.mark.parametrize("blob", [
    [1, 2], "players", 5, None,
    {"players": {"WAS_AFK": "1"}}, {"players": "WAS_AFK"},
    {"players": 3}, {"players": [None, 5, "x"]},
])
def test_t466_malformed_sidecar_never_raises(tmp_path, blob):
    assert ch.sidecar_has_afk(_sidecar(tmp_path, blob)) is False
    assert ch.judge(_match(), _sidecar(tmp_path, blob, "j.json")).include


def test_t466_good_row_after_junk_rows_is_still_seen(tmp_path):
    sc = _sidecar(tmp_path, {"players": [None, "x", {"WAS_AFK": "1"}]})
    assert ch.sidecar_has_afk(sc) is True


# ----------------------------------------------- RM-1931 UTF-8 BOM sidecar

def test_t467_bom_prefixed_sidecar_keeps_its_ground_truth(tmp_path):
    sc = _sidecar(tmp_path, {"players": [{"WAS_AFK": "1"}]},
                  prefix=b"\xef\xbb\xbf")
    assert ch.sidecar_has_afk(sc) is True
    assert ch.judge(_match(), sc).include is False


# -------------------------------------- RM-1932 non-finite sidecar values

@pytest.mark.parametrize("value", ["inf", "1e999", "-inf", "nan",
                                   math.inf, "Infinity"])
def test_t468_non_finite_sidecar_value_is_not_afk(tmp_path, value):
    sc = tmp_path / "s.json"
    # json.dumps(math.inf) writes the non-standard token Infinity, which
    # json.loads accepts, so this is a real on-disk shape.
    sc.write_text(json.dumps({"players": [{"WAS_AFK": value}]}),
                  encoding="utf-8")
    assert ch.sidecar_has_afk(sc) is False


@pytest.mark.parametrize("value,afk", [
    (True, True), (False, False), (1, True), (0, False), ("2", True),
    ("0.0", False), (None, False),
])
def test_t468_characterization_finite_and_bool_values(tmp_path, value, afk):
    sc = _sidecar(tmp_path, {"players": [{"WAS_LEAVER": value}]})
    assert ch.sidecar_has_afk(sc) is afk


# ----------------------------------------- RM-1933 junk sidecar_path args

@pytest.mark.parametrize("path", [5, 1.5, object(), "bad\x00name.json"])
def test_t469_junk_sidecar_path_never_raises(path):
    assert ch.sidecar_has_afk(path) is False
    assert ch.judge(_match(), path).include is True


def test_t469_deeply_nested_sidecar_never_raises(tmp_path):
    sc = tmp_path / "deep.json"
    sc.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    assert ch.sidecar_has_afk(sc) is False
