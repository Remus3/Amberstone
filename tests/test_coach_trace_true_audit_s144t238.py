"""Lane 8 true-audit, s144 cycle 238: ``core/coach_trace.py`` hardening.

The coach-call ring buffer (``data/coach_trace.jsonl``, served by
``/api/coach/trace``) claimed "Best-effort; never raises to caller" and
"Capped at MAX_LINES". Measured against the module before this slice:

1. ``append`` built its record OUTSIDE its try, so ``int()`` over a junk
   ``latency_ms`` / token count (None, "abc", NaN, inf) raised into the coach.
2. ``record_enemy_target`` ran ``float()`` / ``round()`` over its inputs
   unguarded and raised the same way.
3. A non-finite float in ``extra`` was written as a bare ``NaN`` /
   ``Infinity`` token; ``dashboard/routes_coach.py`` ``_send_json`` is strict
   (``allow_nan=False``), so ONE such line 500ed the whole trace tab for as
   long as it stayed in the window.
4. A non-JSON-serialisable ``extra`` value dropped the whole call record.
5. ``read_recent(0)`` returned the WHOLE file (``lines[-0:]``) and a negative
   limit returned an arbitrary head slice.
6. ``read_recent`` returned non-dict JSON lines although it promises dicts.
7. ``_truncate(s, n)`` returned n + 2 characters, not at most n.
8. ``_trim`` cut to MAX_LINES only; once MAX_LINES records exceed the 1 MiB
   trigger (measured live: 200 lines, 1491674 bytes, avg 7458 B/line) EVERY
   append re-read and rewrote the whole file under the lock.

The autouse conftest fixture ``redirect_prod_write_paths_to_tmp`` points
``_TRACE_FILE`` at a tmp dir, so nothing here touches data/.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core import coach_trace


def _strict_loads(line: str):
    def _reject(tok):
        raise ValueError(f"non-finite token {tok}")
    return json.loads(line, parse_constant=_reject)


def _rows() -> list:
    path = Path(coach_trace._TRACE_FILE)
    return [_strict_loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


# --- 1. append never raises on junk numbers --------------------------------

@pytest.mark.parametrize("junk", [None, "abc", float("nan"), float("inf"),
                                  float("-inf"), object(), [1]])
@pytest.mark.parametrize("field", ["latency_ms", "tokens_in", "tokens_out",
                                   "cache_read", "cache_write"])
def test_append_never_raises_on_junk_number(field, junk):
    coach_trace.append(mode="SR", model="synthetic-model", response="r",
                       **{field: junk})
    rows = _rows()
    assert len(rows) == 1
    assert rows[0][field] == 0


def test_append_survives_an_unprintable_prompt():
    """The record build runs inside append's try: a value whose str()
    raises is logged and dropped, never raised into the coach."""
    class _Bad:
        def __str__(self):
            raise RuntimeError("no str")

    coach_trace.append(mode="SR", model="m", user_prompt=_Bad())
    path = Path(coach_trace._TRACE_FILE)
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_append_numeric_values_still_recorded():
    coach_trace.append(mode="SR", model="m", latency_ms=1234.9, tokens_in="12",
                       tokens_out=7, cache_read=True, cache_write=0)
    row = _rows()[0]
    assert row["latency_ms"] == 1234
    assert row["tokens_in"] == 12
    assert row["tokens_out"] == 7
    assert row["cache_read"] == 1


# --- 2. record_enemy_target never raises -----------------------------------

def test_record_enemy_target_never_raises_on_junk():
    coach_trace.record_enemy_target(
        mode="SR", champion="Veigar", base_max_hp=None,
        applied_max_hp=float("nan"), hp_scale="abc", tanky_count=None,
        bonus_hp=float("inf"))
    row = _rows()[0]
    ex = row["extra"]
    assert ex["kind"] == "enemy_target"
    assert ex["champion"] == "Veigar"
    assert ex["base_max_hp"] is None
    assert ex["applied_max_hp"] is None
    assert ex["hp_scale"] is None
    assert ex["tanky_count"] is None
    assert ex["bonus_hp"] is None


def test_record_enemy_target_survives_an_unprintable_champion():
    class _Bad:
        def __str__(self):
            raise RuntimeError("no str")

    coach_trace.record_enemy_target(
        mode="SR", champion=_Bad(), base_max_hp=1.0, applied_max_hp=2.0,
        hp_scale=1.0, tanky_count=0)
    assert _rows()[0]["extra"]["champion"] == ""


def test_record_enemy_target_rounds_good_values():
    coach_trace.record_enemy_target(
        mode="SR", champion="Ahri", base_max_hp=1000.04, applied_max_hp=1200.06,
        hp_scale=1.123456, tanky_count=2, bonus_hp=200.0)
    ex = _rows()[0]["extra"]
    assert ex["base_max_hp"] == 1000.0
    assert ex["applied_max_hp"] == 1200.1
    assert ex["hp_scale"] == 1.1235
    assert ex["tanky_count"] == 2
    assert ex["bonus_hp"] == 200.0


# --- 3/4. strict JSON on disk, extra never drops the record ----------------

def test_nonfinite_extra_is_written_as_strict_json():
    coach_trace.append(mode="SR", model="m",
                       extra={"x": float("nan"), "nest": [float("inf"), 1.5]})
    raw = Path(coach_trace._TRACE_FILE).read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    row = _rows()[0]
    assert row["extra"] == {"x": None, "nest": [None, 1.5]}


def test_unserialisable_extra_keeps_the_record():
    coach_trace.append(mode="SR", model="m", response="kept",
                       extra={"obj": object()})
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["response"] == "kept"
    assert isinstance(rows[0]["extra"]["obj"], str)


def test_circular_extra_keeps_the_record():
    loop: dict = {}
    loop["self"] = loop
    coach_trace.append(mode="SR", model="m", response="kept", extra=loop)
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["response"] == "kept"


# --- 3b. legacy NaN lines on disk no longer break the strict route ---------

def test_read_recent_maps_legacy_nonfinite_tokens_to_none():
    path = Path(coach_trace._TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"mode": "SR", "extra": {"x": NaN, "y": -Infinity}}\n'
                     b'{"mode": "SR", "extra": {"x": 1}}\n')
    recs = coach_trace.read_recent(10)
    assert [r["extra"]["x"] for r in recs] == [None, 1]
    assert recs[0]["extra"]["y"] is None
    # The route serialises with allow_nan=False; this must not raise.
    json.dumps({"records": recs}, allow_nan=False)


# --- 5/6. read_recent limit + shape ----------------------------------------

@pytest.mark.parametrize("limit", [0, -1, -3])
def test_read_recent_nonpositive_limit_returns_nothing(limit):
    for i in range(5):
        coach_trace.append(mode="SR", model="m", response=f"r{i}")
    assert coach_trace.read_recent(limit) == []


def test_read_recent_returns_newest_last():
    for i in range(5):
        coach_trace.append(mode="SR", model="m", response=f"r{i}")
    assert [r["response"] for r in coach_trace.read_recent(2)] == ["r3", "r4"]


def test_read_recent_skips_non_dict_lines():
    path = Path(coach_trace._TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'[1, 2]\n"text"\n5\nnull\nnot json\n{"mode": "SR"}\n')
    assert coach_trace.read_recent(50) == [{"mode": "SR"}]


def test_read_recent_skips_a_line_nested_past_the_recursion_limit():
    path = Path(coach_trace._TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    deep = "[" * 200000 + "]" * 200000
    path.write_bytes((deep + "\n" + '{"mode": "SR"}\n').encode("ascii"))
    assert coach_trace.read_recent(50) == [{"mode": "SR"}]


# --- 7. _truncate honours its cap ------------------------------------------

def test_truncate_never_exceeds_cap():
    out = coach_trace._truncate("x" * 5000, 4096)
    assert len(out) == 4096
    assert out.endswith("...")
    assert coach_trace._truncate("abc", 4096) == "abc"
    assert coach_trace._truncate(None, 10) == ""


@pytest.mark.parametrize("cap", [-2, 0, 1, 2, 3, 4, 10])
def test_truncate_small_caps_never_exceed_cap(cap):
    out = coach_trace._truncate("abcdefghijklmnop", cap)
    assert len(out) <= max(0, cap)
    assert "abcdefghijklmnop".startswith(out.removesuffix("..."))


def test_append_prompt_fields_capped_at_4096():
    coach_trace.append(mode="SR", model="m", system_prompt="s" * 9000,
                       user_prompt="u" * 9000, response="r" * 9000)
    row = _rows()[0]
    for k in ("system_prompt", "user_prompt", "response"):
        assert len(row[k]) <= 4096, k


# --- 8. trim hysteresis: no rewrite-per-append thrash ----------------------

def _seed(n: int, width: int) -> None:
    path = Path(coach_trace._TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps({"i": i, "pad": "p" * width}) + "\n"
                   for i in range(n))
    path.write_bytes(body.encode("utf-8"))


def test_trim_does_not_rewrite_on_every_append(monkeypatch):
    """300 x ~12 KB lines (about 3.6 MB) exceed the trigger, and MAX_LINES
    of them (about 2.4 MB) do too, so a line-count-only cut cannot get back
    under it. The first append trims; the trim must leave enough headroom
    that the next appends do not each rewrite the file again (the measured
    live state: 200 lines at 1.49 MB re-trimmed on every coach call)."""
    _seed(300, 12000)
    writes = []
    real = coach_trace.atomic_write_text

    def _count(path, content):
        writes.append(len(content))
        return real(path, content)

    monkeypatch.setattr(coach_trace, "atomic_write_text", _count)
    # 20 x ~4 KB records (~80 KB) is more than one seeded line of slack, so a
    # trigger equal to the target would re-trim within this loop.
    for i in range(20):
        coach_trace.append(mode="SR", model="m", response=f"r{i}" + "x" * 4000)
    assert len(writes) == 1, writes
    rows = _rows()
    assert rows[-1]["response"].startswith("r19")
    assert Path(coach_trace._TRACE_FILE).stat().st_size < 2 * (1 << 20)


def test_trim_keeps_newest_max_lines_for_small_records():
    _seed(30000, 60)  # about 2.4 MB of tiny lines
    coach_trace.append(mode="SR", model="m", response="newest")
    rows = _rows()
    assert len(rows) == coach_trace.MAX_LINES
    assert rows[-1]["response"] == "newest"
    assert rows[0]["i"] == 30000 - coach_trace.MAX_LINES + 1


def test_trim_keeps_the_newest_line_even_if_it_alone_is_huge():
    """A newest record larger than the byte target is still kept - the
    trim never empties the ring."""
    _seed(3, 100)
    coach_trace.append(mode="SR", model="m", response="newest",
                       extra={"pad": "p" * (3 << 20)})
    rows = _rows()
    assert len(rows) == 1
    assert rows[-1]["response"] == "newest"


def test_prom_observe_gets_finite_latency(monkeypatch):
    seen = []
    monkeypatch.setattr(coach_trace._M_COACH_LATENCY, "observe",
                        lambda v, **kw: seen.append(v))
    coach_trace.append(mode="SR", model="m", latency_ms=float("nan"))
    coach_trace.append(mode="SR", model="m", latency_ms=1500)
    assert seen == [0.0, 1.5]
    assert all(math.isfinite(v) for v in seen)
