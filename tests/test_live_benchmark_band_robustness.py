"""Robustness + invariant tests for core.live_benchmark_band (cycle 45/47,
items 443/447).

Proves band_metrics / band_from_state are pure + fail-soft (the live coach
hot path must never raise) and that the item-447 canonical-id fix holds: a
multiword Live Client DISPLAY name ("Miss Fortune", "Lee Sin", "Tahm Kench")
bands identically to its canonical id ("MissFortune", ...). We do NOT change
the production fix - we pin it.

The benchmarks layer is monkeypatched for hermetic control (no
champion_benchmarks.json dependency); one regression test uses the REAL
core.archetype_picks.canonical_champion_id to prove display==canonical at the
band_metrics entry point.

Contract under test (band_metrics docstring): returns a list (empty when
nothing bandable); never raises; band in the documented allowed set; a non-SR
mode / thin distribution / off-checkpoint time / missing champ / non-numeric
value / "no-data" benchmark all yield no band.
"""
from __future__ import annotations

import pytest

from core import live_benchmark_band as lbb

ALLOWED_BANDS = {"below-p25", "p25-p50", "p50-p75", "above-p75", "in-range"}
# _line emits "in your range" for any band string outside the 4 buckets; the
# band field itself only ever carries the 4 real buckets here.
BUCKETS = {"below-p25", "p25-p50", "p50-p75", "above-p75"}


# ---------------------------------------------------------------------------
# A controllable fake benchmarks backend. Maps a canonical champ id to a
# percentile table so we can drive every branch deterministically.
# ---------------------------------------------------------------------------
class _FakeBench:
    """Stand-in for core.benchmarks with a single rich champion."""

    def __init__(self, champ_canonical="Tristana", games=20,
                 table=None):
        self.champ = champ_canonical
        self.games = games
        # metric_key -> (p25, p50, p75)
        self.table = table or {
            "cs_at_10": (60.0, 75.0, 90.0),
            "cs_at_15": (100.0, 120.0, 140.0),
            "level_at_10": (6.0, 7.0, 8.0),
        }

    def games_for(self, champion, mode):
        if champion == self.champ and mode == "sr":
            return self.games
        return 0

    def get(self, champion, mode, metric_key):
        if champion != self.champ or mode != "sr":
            return {}
        tup = self.table.get(metric_key)
        if not tup:
            return {}
        p25, p50, p75 = tup
        return {"p25": p25, "p50": p50, "p75": p75, "n": self.games}

    def rank_value(self, champion, mode, metric_key, value):
        b = self.get(champion, mode, metric_key)
        if not b:
            return "no-data"
        p25, p50, p75 = b["p25"], b["p50"], b["p75"]
        if value < p25:
            return "below-p25"
        if value < p50:
            return "p25-p50"
        if value < p75:
            return "p50-p75"
        return "above-p75"


def _install(monkeypatch, fake):
    monkeypatch.setattr(lbb.benchmarks, "games_for", fake.games_for)
    monkeypatch.setattr(lbb.benchmarks, "get", fake.get)
    monkeypatch.setattr(lbb.benchmarks, "rank_value", fake.rank_value)


def _invariants(bands):
    """Every returned band dict satisfies the documented shape + bounds."""
    assert isinstance(bands, list)
    for b in bands:
        assert b["band"] in BUCKETS
        assert b["checkpoint"] in {"10", "15"}
        assert b["source_tag"] == lbb._SOURCE_TAG
        assert isinstance(b["value"], float)
        assert b["line"] and isinstance(b["line"], str)
        assert b["line"].isascii()


# ---------------------------------------------------------------------------
# Happy path: at-checkpoint SR with a real distribution -> banded.
# ---------------------------------------------------------------------------
def test_at_10_bands_cs_and_level(monkeypatch):
    _install(monkeypatch, _FakeBench())
    bands = lbb.band_metrics("Tristana", 600.0, cs=85.0, level=7.5)
    _invariants(bands)
    keys = {(b["metric"], b["band"]) for b in bands}
    assert ("cs_at_10", "p50-p75") in keys      # 85 in [75,90)
    assert ("level_at_10", "p50-p75") in keys    # 7.5 in [7,8)


def test_at_15_bands_cs_only(monkeypatch):
    _install(monkeypatch, _FakeBench())
    bands = lbb.band_metrics("Tristana", 900.0, cs=145.0, level=12.0)
    _invariants(bands)
    metrics = {b["metric"] for b in bands}
    assert metrics == {"cs_at_15"}              # no level_at_15 checkpoint
    assert bands[0]["band"] == "above-p75"       # 145 >= 140


# ---------------------------------------------------------------------------
# Item-447 REGRESSION: multiword display name == canonical id.
# Uses the REAL canonical_champion_id (no monkeypatch of archetype_picks) so we
# prove the production canonicalization at band_metrics entry, only stubbing the
# benchmarks backend keyed on the canonical id.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("display,canonical", [
    ("Miss Fortune", "MissFortune"),
    ("Lee Sin", "LeeSin"),
    ("Tahm Kench", "TahmKench"),
    ("Kai'Sa", "Kaisa"),
])
def test_multiword_display_name_bands_same_as_canonical(monkeypatch, display,
                                                        canonical):
    # Sanity: the real resolver maps display -> canonical. If DDragon data is
    # unavailable in this env it returns the input unchanged; guard so the test
    # is meaningful, else skip rather than false-pass.
    resolved = lbb.canonical_champion_id(display)
    if resolved != canonical:
        pytest.skip(f"DDragon resolver unavailable: {display!r}->{resolved!r}")

    fake = _FakeBench(champ_canonical=canonical)
    _install(monkeypatch, fake)

    by_display = lbb.band_metrics(display, 600.0, cs=85.0, level=7.5)
    by_canon = lbb.band_metrics(canonical, 600.0, cs=85.0, level=7.5)

    # Same bands + same metrics regardless of which name-form was passed.
    assert [b["band"] for b in by_display] == [b["band"] for b in by_canon]
    assert [b["metric"] for b in by_display] == [b["metric"] for b in by_canon]
    assert by_display, "display-name path produced no bands (447 regression)"
    # The human-readable line keeps the DISPLAY name passed in (item-447 intent).
    for b in by_display:
        assert display in b["line"]


# ---------------------------------------------------------------------------
# Fail-soft cases: each yields NO band, never raises.
# ---------------------------------------------------------------------------
def test_non_sr_mode_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench())
    assert lbb.band_metrics("Tristana", 600.0, cs=85.0, mode="ARAM") == []
    assert lbb.band_metrics("Tristana", 600.0, cs=85.0, mode="ARENA") == []


def test_thin_distribution_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench(games=4))   # below _MIN_GAMES (5)
    assert lbb.band_metrics("Tristana", 600.0, cs=85.0, level=7.0) == []


def test_off_checkpoint_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench())
    # 700s is > _TOLERANCE_S (45) from both 600 and 900 centers.
    assert lbb.band_metrics("Tristana", 700.0, cs=85.0, level=7.0) == []


def test_unknown_champion_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench())
    assert lbb.band_metrics("Nobody", 600.0, cs=85.0) == []


@pytest.mark.parametrize("champ", ["", None])
def test_empty_champion_no_bands(monkeypatch, champ):
    _install(monkeypatch, _FakeBench())
    assert lbb.band_metrics(champ, 600.0, cs=85.0) == []  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_time", [None, "x", float("nan")])
def test_non_numeric_or_nan_game_time(monkeypatch, bad_time):
    _install(monkeypatch, _FakeBench())
    out = lbb.band_metrics("Tristana", bad_time, cs=85.0)  # type: ignore[arg-type]
    # nan compares false to every checkpoint window -> no bands; str/None caught.
    assert out == []


def test_negative_game_time_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench())
    assert lbb.band_metrics("Tristana", -10.0, cs=85.0) == []


@pytest.mark.parametrize("bad_val", [None, "85", True, False, [1]])
def test_non_numeric_live_value_skipped(monkeypatch, bad_val):
    _install(monkeypatch, _FakeBench())
    # bool is explicitly rejected even though bool is an int subclass.
    out = lbb.band_metrics("Tristana", 600.0, cs=bad_val, level=bad_val)  # type: ignore[arg-type]
    assert out == []


def test_no_data_benchmark_metric_skipped(monkeypatch):
    # A champ with games but NO cs_at_10 table entry -> rank_value "no-data".
    fake = _FakeBench(table={"level_at_10": (6.0, 7.0, 8.0)})
    _install(monkeypatch, fake)
    bands = lbb.band_metrics("Tristana", 600.0, cs=85.0, level=7.5)
    metrics = {b["metric"] for b in bands}
    assert "cs_at_10" not in metrics       # no-data dropped
    assert "level_at_10" in metrics        # the present one still bands


def test_benchmarks_raises_is_swallowed(monkeypatch):
    # If the backend explodes mid-call, band_metrics must still return cleanly.
    def _boom(*a, **k):
        raise RuntimeError("benchmarks blew up")

    fake = _FakeBench()
    monkeypatch.setattr(lbb.benchmarks, "games_for", fake.games_for)
    monkeypatch.setattr(lbb.benchmarks, "rank_value", _boom)
    monkeypatch.setattr(lbb.benchmarks, "get", fake.get)
    out = lbb.band_metrics("Tristana", 600.0, cs=85.0, level=7.0)
    assert out == []   # the per-metric try/except drops every metric


def test_p50_lookup_failure_still_bands(monkeypatch):
    # rank_value works but get() (for p50) raises -> p50 None, band still emitted.
    fake = _FakeBench()

    def _bad_get(*a, **k):
        raise RuntimeError("get blew up")

    monkeypatch.setattr(lbb.benchmarks, "games_for", fake.games_for)
    monkeypatch.setattr(lbb.benchmarks, "rank_value", fake.rank_value)
    monkeypatch.setattr(lbb.benchmarks, "get", _bad_get)
    bands = lbb.band_metrics("Tristana", 600.0, cs=85.0)
    _invariants(bands)
    assert bands and all(b["p50"] is None for b in bands)


# ---------------------------------------------------------------------------
# Tolerance-window boundary (property style around the 600s center).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("t,expect_band", [
    (600.0 - lbb._TOLERANCE_S, True),    # exactly at the lower edge -> in
    (600.0 + lbb._TOLERANCE_S, True),    # exactly at the upper edge -> in
    (600.0 - lbb._TOLERANCE_S - 1, False),
    (600.0 + lbb._TOLERANCE_S + 1, False),
])
def test_checkpoint_tolerance_boundary(monkeypatch, t, expect_band):
    _install(monkeypatch, _FakeBench())
    bands = lbb.band_metrics("Tristana", t, cs=85.0, level=7.0)
    assert bool(bands) is expect_band
    _invariants(bands)


# ---------------------------------------------------------------------------
# band_from_state adapter robustness.
# ---------------------------------------------------------------------------
def test_band_from_state_non_dict_returns_empty():
    assert lbb.band_from_state(None) == []       # type: ignore[arg-type]
    assert lbb.band_from_state("nope") == []      # type: ignore[arg-type]
    assert lbb.band_from_state(42) == []          # type: ignore[arg-type]
    assert lbb.band_from_state([]) == []          # type: ignore[arg-type]


def test_band_from_state_missing_champion_returns_empty(monkeypatch):
    _install(monkeypatch, _FakeBench())
    out = lbb.band_from_state({"cs": 85.0, "game_time_s": 600.0})
    assert out == []


@pytest.mark.parametrize("champ_key", [
    "champion", "champion_name", "champ", "tracked_champion_name",
])
def test_band_from_state_champion_key_variants(monkeypatch, champ_key):
    _install(monkeypatch, _FakeBench())
    state = {champ_key: "Tristana", "cs": 85.0, "level": 7.5,
             "game_time_s": 600.0}
    out = lbb.band_from_state(state)
    _invariants(out)
    assert out, f"champion under {champ_key!r} should band"


def test_band_from_state_game_seconds_alias(monkeypatch):
    _install(monkeypatch, _FakeBench())
    # uses the 'game_seconds' alias rather than 'game_time_s'.
    state = {"champion": "Tristana", "cs": 85.0, "game_seconds": 600.0}
    out = lbb.band_from_state(state)
    _invariants(out)
    assert any(b["metric"] == "cs_at_10" for b in out)


def test_band_from_state_bool_values_ignored(monkeypatch):
    _install(monkeypatch, _FakeBench())
    state = {"champion": "Tristana", "cs": True, "level": False,
             "game_time_s": 600.0}
    # bool cs/level are rejected by _num (and by band_metrics); no bands.
    assert lbb.band_from_state(state) == []


def test_band_from_state_missing_time_defaults_zero_no_bands(monkeypatch):
    _install(monkeypatch, _FakeBench())
    # no time key -> defaults to 0.0 -> off every checkpoint -> no bands.
    out = lbb.band_from_state({"champion": "Tristana", "cs": 85.0})
    assert out == []


# ---------------------------------------------------------------------------
# _resolve_sr_mode + _line + _active_checkpoints unit invariants.
# ---------------------------------------------------------------------------
def test_resolve_sr_mode_priority(monkeypatch):
    # ranked has enough games -> picked over plain sr / flex.
    def games_for(champion, mode):
        return {"sr_ranked": 10, "sr": 30, "sr_flex": 2}.get(mode, 0)

    monkeypatch.setattr(lbb.benchmarks, "games_for", games_for)
    assert lbb._resolve_sr_mode("Tristana", "SR", 5) == "sr_ranked"


def test_resolve_sr_mode_falls_through_to_available(monkeypatch):
    def games_for(champion, mode):
        return {"sr_ranked": 1, "sr": 1, "sr_flex": 9}.get(mode, 0)

    monkeypatch.setattr(lbb.benchmarks, "games_for", games_for)
    assert lbb._resolve_sr_mode("Tristana", "SR", 5) == "sr_flex"


def test_resolve_sr_mode_non_sr_is_none(monkeypatch):
    _install(monkeypatch, _FakeBench())
    assert lbb._resolve_sr_mode("Tristana", "ARAM", 5) is None
    assert lbb._resolve_sr_mode("", "SR", 5) is None


def test_resolve_sr_mode_games_for_raises_is_soft(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(lbb.benchmarks, "games_for", _boom)
    # every probe raises -> swallowed per-iteration -> None, no raise.
    assert lbb._resolve_sr_mode("Tristana", "SR", 5) is None


@pytest.mark.parametrize("band,frag", [
    ("above-p75", "top quartile"),
    ("p50-p75", "above your"),
    ("p25-p50", "below your"),
    ("below-p25", "bottom quartile"),
    ("weird-bucket", "in your"),
])
def test_line_text_per_band(band, frag):
    line = lbb._line("CS", "10", band, "Tristana")
    assert frag in line
    assert line.isascii()


def test_active_checkpoints_selects_nearby():
    got = dict(lbb._active_checkpoints(600.0, lbb._TOLERANCE_S))
    assert "10" in got and "15" not in got
    got2 = dict(lbb._active_checkpoints(900.0, lbb._TOLERANCE_S))
    assert "15" in got2 and "10" not in got2
    assert dict(lbb._active_checkpoints(750.0, lbb._TOLERANCE_S)) == {}
