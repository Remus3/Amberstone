"""s144 true-audit - core/live_benchmark_band_shadow.py hardening.

F1 (headline): the coarse-state dedup was check-then-write with no lock, so
two concurrent /api/state builds both passed the check and both appended the
same record. Measured on the live shadow file at audit time: 1020 of 3495
rows were a byte-identical sig repeat of the row before them, written about
70 microseconds later (a serialized caller self-suppresses, so a duplicate
means a race).

F2: cs / level / game_time_s were logged raw - a NaN / inf reached the jsonl
as a bare NaN / Infinity token (invalid strict JSON), an inf clock raised
OverflowError and lost the record, a str clock "600" bucketed as 0 and was
logged as a str, a bool cs logged true.

F3: bands were trusted - a str became a list of characters, non-dict
entries (and a list with NO real band) were logged as a firing, a band dict
holding a NaN wrote a bare NaN token and one holding a non-JSON value lost
the whole record.

F4: a blank / whitespace / over-long champion and a non-str / blank mode
were logged.

F5: native_action was logged raw: a dict or list, an unbounded string.

F6: a str path silently never wrote (AttributeError swallowed); a non-str
now_iso was logged raw.

Every test writes to tmp_path, never the live data/ file.
"""
from __future__ import annotations

import json
import math
import threading

import pytest

from core import live_benchmark_band_shadow as lbs

_BAND = {
    "checkpoint": "10", "metric": "cs_at_10", "display": "CS",
    "value": 90.0, "band": "above-p75", "p50": 70.0,
    "line": "CS at 10: top quartile on Tristana.", "source_tag": "live-bench",
}


def _strict_rows(path):
    """Parse every line with NaN / Infinity REJECTED, as a strict reader does."""
    def _reject(tok):
        raise ValueError(f"non-standard JSON constant {tok}")
    text = path.read_text(encoding="utf-8")
    return [json.loads(ln, parse_constant=_reject)
            for ln in text.splitlines() if ln.strip()]


def _log(path, **kw):
    kw.setdefault("bands", [_BAND])
    kw.setdefault("game_time_s", 600.0)
    kw.setdefault("cs", 90)
    kw.setdefault("level", 9)
    mode = kw.pop("mode", "sr")
    champ = kw.pop("champion", "Tristana")
    return lbs.log_live_bands(mode, champ, path=path, **kw)


@pytest.fixture(autouse=True)
def _clear_sig():
    lbs._LAST_SIG.clear()
    yield
    lbs._LAST_SIG.clear()


# --- F1: dedup race ---------------------------------------------------------

def test_f1_concurrent_same_state_writes_one_row(tmp_path, monkeypatch):
    """Two threads with the same coarse state: exactly one row.

    The patched clock holds the first entrant inside the write path until the
    second thread arrives (or 1 s passes). Unlocked, both pass the dedup check
    and both write; locked, the second sees the first's sig and skips."""
    p = tmp_path / "shadow.jsonl"
    real_dt = lbs.datetime
    arrived = []
    both = threading.Event()
    guard = threading.Lock()

    class _SlowDT:
        @staticmethod
        def now(tz=None):
            with guard:
                arrived.append(1)
                if len(arrived) >= 2:
                    both.set()
            both.wait(1.0)
            return real_dt.now(tz)

    monkeypatch.setattr(lbs, "datetime", _SlowDT)
    results = []

    def _run():
        results.append(_log(p))

    threads = [threading.Thread(target=_run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
    assert len(_strict_rows(p)) == 1
    assert sum(1 for r in results if r is not None) == 1


def test_f1_sequential_dedup_still_holds(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p) is not None
    assert _log(p, game_time_s=603.0) is None
    assert len(_strict_rows(p)) == 1


def test_f1_failed_write_does_not_poison_dedup(tmp_path):
    """A record that fails to write must not record its sig: the SAME state
    to the SAME target is written once the target becomes writable."""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "shadow.jsonl"  # parent is a file -> mkdir fails
    assert _log(target) is None
    blocker.unlink()
    assert _log(target) is not None
    assert len(_strict_rows(target)) == 1


# --- F2: numeric fields -----------------------------------------------------

@pytest.mark.parametrize("field", ["cs", "level", "game_time_s"])
@pytest.mark.parametrize("junk", [float("nan"), float("inf"), float("-inf")])
def test_f2_non_finite_field_is_null_and_strict_json(tmp_path, field, junk):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, **{field: junk})
    assert rec is not None
    rows = _strict_rows(p)
    assert len(rows) == 1
    assert rows[0][field] is None
    assert rec[field] is None


@pytest.mark.parametrize("field,junk", [
    ("cs", True), ("cs", -5), ("cs", 10 ** 6), ("cs", "90"),
    ("cs", 90.5), ("cs", [90]),
    ("level", False), ("level", 0), ("level", 31), ("level", "9"), ("level", 9.5),
    ("game_time_s", True), ("game_time_s", -1.0), ("game_time_s", 10 ** 7),
    ("game_time_s", "600"), ("game_time_s", {"t": 600}),
])
def test_f2_out_of_vocabulary_field_is_null(tmp_path, field, junk):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, **{field: junk})
    assert rec is not None
    assert _strict_rows(p)[0][field] is None


@pytest.mark.parametrize("field,good,want", [
    ("cs", 90, 90), ("cs", 90.0, 90), ("cs", 0, 0), ("cs", 10 ** 5, 10 ** 5),
    ("level", 1, 1), ("level", 30, 30), ("level", 9.0, 9),
    ("game_time_s", 600, 600), ("game_time_s", 600.25, 600.25),
    ("game_time_s", 0, 0), ("game_time_s", None, None),
])
def test_f2_valid_field_passes_through(tmp_path, field, good, want):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, **{field: good})
    assert rec is not None
    got = _strict_rows(p)[0][field]
    assert got == want
    assert type(got) is type(want)


@pytest.mark.parametrize("field", ["cs", "level", "game_time_s"])
def test_f2_5000_digit_int_is_null_not_a_lost_record(tmp_path, field):
    """str() of a >4300-digit int raises ValueError inside the dedup sig."""
    p = tmp_path / "shadow.jsonl"
    assert _log(p, **{field: 10 ** 5000}) is not None
    assert _strict_rows(p)[0][field] is None


def test_f2_negative_zero_clock_logs_positive_zero(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, game_time_s=-0.0) is not None
    got = _strict_rows(p)[0]["game_time_s"]
    assert got == 0.0 and math.copysign(1.0, got) == 1.0


def test_f2_str_clock_does_not_dedup_as_bucket_zero(tmp_path):
    """A str "600" bucketed as 0 and collided with a real 0..4 s tick."""
    p = tmp_path / "shadow.jsonl"
    assert _log(p, game_time_s=2.0) is not None
    assert _log(p, game_time_s="600") is not None


def test_f2_inf_clock_record_is_not_lost(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, game_time_s=float("inf")) is not None
    assert len(_strict_rows(p)) == 1


# --- F3: bands --------------------------------------------------------------

@pytest.mark.parametrize("junk", [
    "above-p75", {"band": "above-p75"}, 5, ["junk", 5], [None], [{}],
    [{"band": ""}], [{"band": "  "}], [{"band": 5}], [{"metric": "cs_at_10"}],
])
def test_f3_no_real_band_is_a_gate_miss(tmp_path, junk):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, bands=junk) is None
    assert not p.exists()


def test_f3_junk_entries_dropped_real_band_kept(tmp_path):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, bands=["junk", 5, _BAND, None])
    assert rec is not None
    assert _strict_rows(p)[0]["bands"] == [_BAND]


def test_f3_non_sequence_bands_is_gate_miss(tmp_path):
    """Only a list / tuple is a band list; an iterator is not trusted."""
    p = tmp_path / "shadow.jsonl"
    assert _log(p, bands=iter([_BAND])) is None
    assert not p.exists()


def test_f3_tuple_of_bands_accepted(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, bands=(_BAND,)) is not None
    assert _strict_rows(p)[0]["bands"] == [_BAND]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object(), {1, 2}])
def test_f3_unserialisable_band_dropped_not_whole_record(tmp_path, bad):
    p = tmp_path / "shadow.jsonl"
    poisoned = dict(_BAND, metric="level_at_10", value=bad)
    rec = _log(p, bands=[poisoned, _BAND])
    assert rec is not None
    rows = _strict_rows(p)
    assert rows[0]["bands"] == [_BAND]


def test_f3_only_band_unserialisable_is_gate_miss(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, bands=[dict(_BAND, value=float("nan"))]) is None
    assert not p.exists()


def test_f3_band_is_copied_not_aliased(tmp_path):
    p = tmp_path / "shadow.jsonl"
    band = dict(_BAND)
    rec = _log(p, bands=[band])
    band["band"] = "below-p25"
    assert rec["bands"][0]["band"] == "above-p75"


# --- F4: champion / mode ----------------------------------------------------

@pytest.mark.parametrize("champ", ["   ", "\t", "x" * 65, None, 123, ["Tristana"]])
def test_f4_junk_champion_is_gate_miss(tmp_path, champ):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, champion=champ) is None
    assert not p.exists()


def test_f4_champion_is_stripped(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, champion="  Tristana ") is not None
    assert _strict_rows(p)[0]["champion"] == "Tristana"


def test_f4_champion_64_chars_accepted(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, champion="x" * 64) is not None


@pytest.mark.parametrize("mode", [None, "", "  ", 5, {"m": "sr"}, "s" * 33])
def test_f4_junk_mode_is_gate_miss(tmp_path, mode):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, mode=mode) is None
    assert not p.exists()


def test_f4_mode_is_stripped(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(p, mode=" sr ") is not None
    assert _strict_rows(p)[0]["mode"] == "sr"


# --- F5: native_action ------------------------------------------------------

@pytest.mark.parametrize("junk", [{"a": float("nan")}, ["Push"], 5, True])
def test_f5_non_str_native_action_is_null(tmp_path, junk):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, native_action=junk)
    assert rec is not None
    assert _strict_rows(p)[0]["native_action"] is None


def test_f5_long_native_action_is_capped(tmp_path):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, native_action="a" * 5000)
    assert rec is not None
    got = _strict_rows(p)[0]["native_action"]
    assert got == "a" * lbs._MAX_ACTION_CHARS


def test_f5_normal_native_action_kept(tmp_path):
    p = tmp_path / "shadow.jsonl"
    _log(p, native_action="Push to tower")
    assert _strict_rows(p)[0]["native_action"] == "Push to tower"


# --- F6: path / now_iso -----------------------------------------------------

def test_f6_str_path_writes(tmp_path):
    p = tmp_path / "shadow.jsonl"
    assert _log(str(p)) is not None
    assert len(_strict_rows(p)) == 1


@pytest.mark.parametrize("junk", [5, None, {"t": 1}])
def test_f6_non_str_now_iso_uses_real_clock(tmp_path, junk):
    p = tmp_path / "shadow.jsonl"
    rec = _log(p, now_iso=junk) if junk is not None else _log(p)
    assert rec is not None
    ts = _strict_rows(p)[0]["ts"]
    assert isinstance(ts, str) and ts[:2] == "20"


def test_f6_str_now_iso_kept(tmp_path):
    p = tmp_path / "shadow.jsonl"
    _log(p, now_iso="2026-10-28T00:00:00+00:00")
    assert _strict_rows(p)[0]["ts"] == "2026-10-28T00:00:00+00:00"


# --- contract: never raises -------------------------------------------------

def test_never_raises_over_a_junk_grid(tmp_path):
    p = tmp_path / "shadow.jsonl"
    junk = [None, True, -1, float("nan"), float("inf"), 10 ** 5000, "x", [], {}, object()]
    for j in junk:
        for field in ("cs", "level", "game_time_s", "native_action", "bands",
                      "mode", "champion", "now_iso"):
            _log(p, **{field: j})
    for row in _strict_rows(p):
        for k in ("cs", "level", "game_time_s"):
            v = row[k]
            assert v is None or (isinstance(v, (int, float)) and math.isfinite(v))
