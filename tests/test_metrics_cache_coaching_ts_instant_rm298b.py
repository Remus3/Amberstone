"""
tests/test_metrics_cache_coaching_ts_instant_rm298b.py

RM-298b - MetricsCache._read_last_coaching_ts picked the newest coaching
timestamp across the five per-mode artifacts by LEXICOGRAPHIC string
compare (`ts_str > latest`).  That was right only because one writer
(core/coaching_timestamps.py, `datetime.now(timezone.utc).isoformat()`)
emits every artifact.  A `Z`-suffixed value sorts after every `+00:00`
value in the same second (ord('Z') 90 > ord('.') 46 and ord('+') 43), a
non-UTC offset sorts by its wall-clock digits, and `str(ts)` coerced a
non-string `ts` (or any garbage string) into the ordering instead of
rejecting it.

The reader now parses each value to an aware datetime and compares
instants; it still returns the winning artifact's ORIGINAL string, so the
published field keeps the writer's format.  A value it cannot place on
the timeline (non-string, unparseable, or naive) is skipped and named on
refresh_error rather than silently competing.

Red on the base: five of the ordering / rejection tests below fail against
the string compare (the later-Z, empty-ts and writer-format tests are
behaviour-preserving guards and pass on both).  No live dependencies: every test uses tmp_path.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.coaching_timestamps import write_coaching_ts
from core.metrics_cache import MetricsCache, MetricsSummary


def _write(rt, mode, ts):
    (rt / f"coaching_ts_{mode}.json").write_text(
        json.dumps({"ts": ts, "mode": mode}), encoding="utf-8"
    )


def _read(rt):
    mc = MetricsCache(rt, refresh_interval_s=9999)
    s = MetricsSummary()
    faults = []
    mc._read_last_coaching_ts(s, faults)
    return s.last_coaching_ts, faults


def test_z_suffix_does_not_beat_a_later_offset_value_in_the_same_second(tmp_path):
    # The row's own red-first case: same second, the sub-second +00:00
    # value is genuinely later, but 'Z' sorts after '.' as a string.
    _write(tmp_path, "sr", "2026-10-25T10:00:00Z")
    _write(tmp_path, "tft", "2026-10-25T10:00:00.500000+00:00")
    latest, faults = _read(tmp_path)
    assert latest == "2026-10-25T10:00:00.500000+00:00"
    assert faults == []


def test_z_suffix_that_is_later_still_wins(tmp_path):
    # The converse: a Z value that IS later must win, so the fix is an
    # instant compare and not a blanket demotion of the Z spelling.
    _write(tmp_path, "sr", "2026-10-25T10:00:01Z")
    _write(tmp_path, "tft", "2026-10-25T10:00:00.500000+00:00")
    latest, _ = _read(tmp_path)
    assert latest == "2026-10-25T10:00:01Z"


def test_non_utc_offset_is_compared_as_an_instant(tmp_path):
    # 12:00+02:00 is 10:00 UTC, earlier than 10:30 UTC, but "12" > "10".
    _write(tmp_path, "aram", "2026-10-25T12:00:00+02:00")
    _write(tmp_path, "arena", "2026-10-25T10:30:00+00:00")
    latest, _ = _read(tmp_path)
    assert latest == "2026-10-25T10:30:00+00:00"


def test_non_string_ts_is_rejected_not_coerced(tmp_path):
    # str(9999999999) == "9999999999" sorted above every ISO string.
    _write(tmp_path, "sr", 9999999999)
    _write(tmp_path, "brawl", "2026-10-25T10:00:00+00:00")
    latest, faults = _read(tmp_path)
    assert latest == "2026-10-25T10:00:00+00:00"
    assert any("coaching_ts_sr.json" in f for f in faults), faults


def test_unparseable_and_naive_ts_are_skipped_and_named(tmp_path):
    # "not-a-time" sorts above "2026-..." ('n' > '2'); a naive value has no
    # instant to compare.  Both are skipped and both are faults.
    _write(tmp_path, "sr", "not-a-time")
    _write(tmp_path, "aram", "2026-10-25T23:00:00")
    _write(tmp_path, "tft", "2026-10-25T10:00:00+00:00")
    latest, faults = _read(tmp_path)
    assert latest == "2026-10-25T10:00:00+00:00"
    assert any("coaching_ts_sr.json" in f for f in faults), faults
    assert any("coaching_ts_aram.json" in f for f in faults), faults


def test_only_unusable_values_leave_the_field_none(tmp_path):
    _write(tmp_path, "sr", "not-a-time")
    _write(tmp_path, "aram", ["2026-10-25T10:00:00+00:00"])
    latest, faults = _read(tmp_path)
    assert latest is None
    assert len(faults) == 2, faults


def test_empty_ts_stays_a_quiet_skip(tmp_path):
    # Unchanged behaviour: an empty / missing ts is not a fault.
    _write(tmp_path, "sr", "")
    (tmp_path / "coaching_ts_aram.json").write_text(
        json.dumps({"mode": "aram"}), encoding="utf-8"
    )
    latest, faults = _read(tmp_path)
    assert latest is None
    assert faults == []


def test_the_sole_writer_emits_a_value_the_reader_accepts(tmp_path):
    # Writer-format guard: what core/coaching_timestamps.py writes must parse
    # to an AWARE datetime, or every real artifact would now be skipped.
    for mode in ("sr", "aram", "arena", "brawl", "tft"):
        write_coaching_ts(mode, runtime_dir=tmp_path)
        raw = json.loads(
            (tmp_path / f"coaching_ts_{mode}.json").read_text(encoding="utf-8")
        )["ts"]
        assert datetime.fromisoformat(raw).tzinfo is not None
    latest, faults = _read(tmp_path)
    assert latest is not None
    assert faults == []
