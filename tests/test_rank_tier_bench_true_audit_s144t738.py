"""Lane 8 true-audit (S144-T-738) of core/rank_tier_bench.py.

The module is the reader behind GET /api/rank-tier-bench (the overlay stats
panel's benchmark column). Its docstring promises a loader that is
"thread-safe, idempotent, TTL-cached, and never raises". Five defects, each
pinned by a test below that was RED against the pre-fix module:

  1  SEED NOT VALIDATED. _load_static_grid returned the seed's `tiers` dict
     verbatim. Only live rows were checked (_fold_rows), so a NaN / bool /
     string / negative seed avg reached the grid, a non-dict tier or mode
     block made _overlay raise AttributeError (rank_tier_grid raised, against
     its own "never raises"), and a seed of pure junk was reported as source
     "static" although nothing in it was a usable benchmark.
  2  A FAILED COLD LOAD WAS CACHED FOR THE FULL 6 h TTL. A missing or briefly
     unreadable seed at first read published an empty grid stamped fresh, so
     the panel said "no benchmark" for six hours after the file came back.
     The RM-295c guard only protects a grid that already holds data.
  3  A NEGATIVE LIVE AVG WIPED A GOOD STATIC VALUE. _fold_rows accepted a
     negative average (untrusted endpoint bytes; rank_tier_source only checks
     the envelope), _overlay wrote it over the seed's value, and the route's
     own value gate then nulled the cell - so the estimate that should back a
     bad live row was lost.
  4  A NON-LIST fetch_rows RESULT RAISED OUT OF THE SWEEP. `for r in rows or
     []` over an int raised TypeError outside the per-cell try, so one bad
     cell killed the whole refresh (and the cold-start reader with it).
  5  SEED READ EDGES. A UTF-8 BOM made json.loads refuse the seed ("none"),
     and a deeply nested seed raised RecursionError straight through the
     loader. A non-string live role became a str() repr key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import rank_tier_bench as RTB  # noqa: E402
from core import rank_tier_source as RTS  # noqa: E402

_REAL_SEED = RTB._SEED_PATH


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("RC_RANK_TIER_LIVE", raising=False)
    RTB._reset_cache()
    yield
    assert RTB._await_refresh_for_tests(10.0)
    RTB._reset_cache()


def _cell(cs=200, kda=2.5, kp=55):
    one = {"cs": {"avg": cs}, "kda": {"avg": kda}, "kp": {"avg": kp}}
    return {"all": {"early": dict(one), "mid": dict(one)}}


def _seed(tmp_path, monkeypatch, tiers, *, raw: str | None = None,
          bom: bool = False) -> Path:
    p = tmp_path / "seed.json"
    text = raw if raw is not None else json.dumps({"schema": 1, "tiers": tiers})
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    p.write_bytes(data)
    monkeypatch.setattr(RTB, "_SEED_PATH", p)
    return p


# --- 1: the static seed is validated like a live row ----------------------

@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "true",
                                 '"205"', "-3", "null", "[1]", "{}"])
def test_bad_seed_avg_is_dropped_and_good_metrics_survive(tmp_path, monkeypatch,
                                                          bad):
    raw = (
        '{"tiers": {"gold": {"SR": {"all": {"early": {'
        '"cs": {"avg": ' + bad + '}, "kda": {"avg": 2.5}, "kp": {"avg": 58}'
        '}}}}}}'
    )
    _seed(tmp_path, monkeypatch, None, raw=raw)
    early = RTB.rank_tier_grid("gold", "SR")["all"]["early"]
    assert "cs" not in early, early
    assert early["kda"] == {"avg": 2.5}
    assert early["kp"] == {"avg": 58}
    assert RTB.source() == "static"


@pytest.mark.parametrize("junk", [5, "gold", [1, 2], None, True])
def test_non_dict_seed_tier_block_does_not_crash_the_live_overlay(
        tmp_path, monkeypatch, junk):
    _seed(tmp_path, monkeypatch, {"gold": junk, "iron": {"SR": _cell(cs=140)}})
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")

    def _rows(tier, mode, **_kw):
        if tier == "gold" and mode == "SR":
            return [{"role": "all", "bracket": "early", "metric": "cs",
                     "avg": 210.0}]
        return None

    monkeypatch.setattr(RTS, "fetch_rows", _rows)
    grid = RTB.rank_tier_grid("gold", "SR")
    assert grid == {"all": {"early": {"cs": {"avg": 210.0}}}}
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140
    assert RTB.source() == "live"


@pytest.mark.parametrize("junk_level", ["mode", "role", "bracket", "metric"])
def test_non_dict_seed_inner_level_does_not_crash_the_live_overlay(
        tmp_path, monkeypatch, junk_level):
    tiers = {"gold": {"SR": _cell()}}
    if junk_level == "mode":
        tiers["gold"]["SR"] = 7
    elif junk_level == "role":
        tiers["gold"]["SR"]["all"] = "x"
    elif junk_level == "bracket":
        tiers["gold"]["SR"]["all"]["early"] = [1]
    else:
        tiers["gold"]["SR"]["all"]["early"]["cs"] = 205
    _seed(tmp_path, monkeypatch, tiers)
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    monkeypatch.setattr(
        RTS, "fetch_rows",
        lambda tier, mode, **_k: (
            [{"bracket": "early", "metric": "cs", "avg": 1.0}]
            if (tier, mode) == ("gold", "SR") else None))
    grid = RTB.rank_tier_grid("gold", "SR")
    assert grid["all"]["early"]["cs"] == {"avg": 1.0}


def test_seed_of_pure_junk_reports_none_not_static(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, {
        "gold": 5,
        "notatier": {"SR": _cell()},
        "iron": {"ARENA": _cell(), "SR": {"all": {"late": _cell()["all"]["early"]}}},
    })
    assert RTB.rank_tier_grid("gold", "SR") == {}
    assert RTB.rank_tier_grid("iron", "SR") == {}
    assert RTB.source() == "none"


def test_the_committed_seed_passes_validation_unchanged():
    """The validator must not drop anything real: the shipped seed's tiers
    block reads back byte-for-byte equal after validation."""
    raw = json.loads(_REAL_SEED.read_text(encoding="utf-8"))["tiers"]
    assert RTB._load_static_grid() == raw


# --- 2: a failed cold load is retried soon, not pinned for the TTL --------

def test_failed_cold_load_is_retried_well_inside_the_ttl(tmp_path, monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    monkeypatch.setattr(RTB, "_SEED_PATH", tmp_path / "absent.json")
    assert RTB.rank_tier_grid("iron", "SR") == {}
    assert RTB.source() == "none"

    monkeypatch.setattr(RTB, "_SEED_PATH", _REAL_SEED)   # the file is back
    retry = RTB._EMPTY_RETRY_S
    assert 0 < retry <= 300.0, "an empty grid must be retried within minutes"
    assert retry < RTB._TTL_S
    clock[0] += retry + 1.0
    RTB.rank_tier_grid("iron", "SR")                     # kicks the retry
    assert RTB._await_refresh_for_tests(10.0)
    assert RTB.source() == "static"
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140


def test_failed_cold_load_is_not_reread_on_every_call(tmp_path, monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    reads = []
    monkeypatch.setattr(RTB, "_load_static_grid",
                        lambda: reads.append(1) or {})
    for _ in range(5):
        assert RTB.rank_tier_grid("iron", "SR") == {}
    assert RTB._await_refresh_for_tests(10.0)
    assert len(reads) == 1, "an empty grid re-read the seed on every request"


def test_a_good_grid_still_honours_the_full_ttl(monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(RTB, "_clock", lambda: clock[0])
    assert RTB.source() == "static"
    reads = []
    real = RTB._load_static_grid
    monkeypatch.setattr(RTB, "_load_static_grid",
                        lambda: reads.append(1) or real())
    clock[0] += RTB._EMPTY_RETRY_S + 1.0
    RTB.rank_tier_grid("iron", "SR")
    assert RTB._await_refresh_for_tests(10.0)
    assert reads == [], "a populated grid was refreshed on the empty-retry clock"


# --- 3: a negative live avg never overwrites the static estimate ----------

@pytest.mark.parametrize("bad", [-1, -0.5, -150.0])
def test_negative_live_avg_keeps_the_static_value(monkeypatch, bad):
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    monkeypatch.setattr(
        RTS, "fetch_rows",
        lambda tier, mode, **_k: (
            [{"role": "all", "bracket": "early", "metric": "cs", "avg": bad},
             {"role": "all", "bracket": "early", "metric": "kda", "avg": 9.5}]
            if (tier, mode) == ("iron", "SR") else None))
    early = RTB.rank_tier_grid("iron", "SR")["all"]["early"]
    assert early["cs"] == {"avg": 140}, "a negative live avg wiped the seed"
    assert early["kda"] == {"avg": 9.5}


def test_fold_rows_drops_negative_and_keeps_zero():
    out = RTB._fold_rows([
        {"bracket": "early", "metric": "cs", "avg": -2},
        {"bracket": "early", "metric": "kp", "avg": 0},
    ])
    assert out == {"all": {"early": {"kp": {"avg": 0.0}}}}


def test_overflowing_int_live_avg_is_dropped_not_raised(monkeypatch):
    """json reads a 400-digit literal as an int; float() of it raises
    OverflowError, which escaped _fold_rows (and the sweep) before."""
    huge = 10 ** 400
    out = RTB._fold_rows([
        {"bracket": "early", "metric": "cs", "avg": huge},
        {"bracket": "early", "metric": "kda", "avg": 2.0},
    ])
    assert out == {"all": {"early": {"kda": {"avg": 2.0}}}}
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    monkeypatch.setattr(
        RTS, "fetch_rows",
        lambda tier, mode, **_k: [{"bracket": "early", "metric": "cs",
                                   "avg": huge}])
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140


def test_overflowing_int_seed_avg_is_dropped(tmp_path, monkeypatch):
    raw = ('{"tiers": {"gold": {"SR": {"all": {"early": {'
           '"cs": {"avg": 1' + "0" * 400 + '}, "kda": {"avg": 2.5}}}}}}}')
    _seed(tmp_path, monkeypatch, None, raw=raw)
    assert RTB.rank_tier_grid("gold", "SR") == {
        "all": {"early": {"kda": {"avg": 2.5}}}}


# --- 4: a non-list fetch_rows result is skipped, not raised ---------------

@pytest.mark.parametrize("junk", [5, 2.5, True, object()])
def test_non_list_live_rows_skip_the_cell(monkeypatch, junk):
    monkeypatch.setenv("RC_RANK_TIER_LIVE", "1")
    good = [{"bracket": "early", "metric": "cs", "avg": 300.0}]
    monkeypatch.setattr(
        RTS, "fetch_rows",
        lambda tier, mode, **_k: junk if tier == "iron" else good)
    assert RTB.rank_tier_grid("iron", "SR")["all"]["early"]["cs"]["avg"] == 140
    assert RTB.rank_tier_grid("gold", "SR")["all"]["early"]["cs"]["avg"] == 300.0
    assert RTB.source() == "live"


@pytest.mark.parametrize("junk", [5, 2.5, True, object(), "rows", {"a": 1}])
def test_fold_rows_of_a_non_list_is_empty(junk):
    assert RTB._fold_rows(junk) == {}


@pytest.mark.parametrize("role", [["top"], {"r": 1}, 3, 1.5])
def test_fold_rows_drops_a_non_string_role(role):
    out = RTB._fold_rows([
        {"role": role, "bracket": "early", "metric": "cs", "avg": 5.0},
        {"role": "top", "bracket": "mid", "metric": "kda", "avg": 3.0},
    ])
    assert out == {"top": {"mid": {"kda": {"avg": 3.0}}}}, out


def test_fold_rows_missing_or_empty_role_defaults_to_all():
    out = RTB._fold_rows([
        {"bracket": "early", "metric": "cs", "avg": 5.0},
        {"role": "", "bracket": "early", "metric": "kda", "avg": 2.0},
        {"role": None, "bracket": "early", "metric": "kp", "avg": 50.0},
    ])
    assert out == {"all": {"early": {"cs": {"avg": 5.0}, "kda": {"avg": 2.0},
                                     "kp": {"avg": 50.0}}}}


# --- 5: seed read edges ---------------------------------------------------

def test_a_bom_prefixed_seed_is_read(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, {"gold": {"SR": _cell(cs=205)}}, bom=True)
    assert RTB.rank_tier_grid("gold", "SR")["all"]["early"]["cs"]["avg"] == 205
    assert RTB.source() == "static"


def test_a_deeply_nested_seed_fails_soft(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, None, raw="[" * 200000 + "]" * 200000)
    assert RTB.rank_tier_grid("gold", "SR") == {}
    assert RTB.source() == "none"


def test_this_file_is_ascii_lf():
    b = Path(__file__).read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []
    assert b"\r" not in b
