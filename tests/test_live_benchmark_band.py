"""Hermetic tests for core.live_benchmark_band.

Drives the REAL core.benchmarks banding logic against an injected in-memory
fixture distribution (monkeypatching benchmarks._cache), so no dependency on the
gitignored champion_benchmarks.json - clean-checkout / CI safe.
"""

from core import benchmarks
from core import live_benchmark_band as lbb


class _StubCache:
    def __init__(self, data):
        self._d = data

    def all(self):
        return self._d


def _install(monkeypatch, champions):
    monkeypatch.setattr(benchmarks, "_cache", _StubCache({"champions": champions}))


def _tristana(mode="sr_ranked", games=10):
    return {
        f"Tristana|{mode}": {
            "games": games,
            "metrics": {
                "cs_at_10": {"p25": 80.0, "p50": 90.0, "p75": 100.0},
                "level_at_10": {"p25": 6.0, "p50": 7.0, "p75": 8.0},
                "cs_at_15": {"p25": 130.0, "p50": 145.0, "p75": 160.0},
            },
        }
    }


def test_at_10_top_quartile_cs_and_level(monkeypatch):
    _install(monkeypatch, _tristana())
    out = lbb.band_metrics("Tristana", 600.0, cs=120.0, level=8.0)
    by_metric = {b["metric"]: b for b in out}
    assert set(by_metric) == {"cs_at_10", "level_at_10"}
    assert by_metric["cs_at_10"]["band"] == "above-p75"
    assert by_metric["cs_at_10"]["checkpoint"] == "10"
    assert "top quartile" in by_metric["cs_at_10"]["line"]
    assert by_metric["cs_at_10"]["p50"] == 90.0
    assert by_metric["level_at_10"]["band"] == "above-p75"
    assert by_metric["level_at_10"]["display"] == "Level"


def test_at_10_below_p25(monkeypatch):
    _install(monkeypatch, _tristana())
    out = lbb.band_metrics("Tristana", 600.0, cs=70.0, level=5.0)
    by_metric = {b["metric"]: b for b in out}
    assert by_metric["cs_at_10"]["band"] == "below-p25"
    assert "bottom quartile" in by_metric["cs_at_10"]["line"]


def test_off_checkpoint_no_bands(monkeypatch):
    _install(monkeypatch, _tristana())
    # 300s and 700s are both outside the +/-45s windows around 600 and 900.
    assert lbb.band_metrics("Tristana", 300.0, cs=90.0, level=7.0) == []
    assert lbb.band_metrics("Tristana", 700.0, cs=90.0, level=7.0) == []


def test_at_15_only_cs(monkeypatch):
    _install(monkeypatch, _tristana())
    out = lbb.band_metrics("Tristana", 900.0, cs=150.0, level=11.0)
    assert [b["metric"] for b in out] == ["cs_at_15"]
    assert out[0]["band"] == "p50-p75"
    assert out[0]["checkpoint"] == "15"


def test_non_sr_mode_no_bands(monkeypatch):
    _install(monkeypatch, _tristana())
    assert lbb.band_metrics("Tristana", 600.0, cs=120.0, level=8.0, mode="ARAM") == []


def test_thin_distribution_gated(monkeypatch):
    _install(monkeypatch, _tristana(games=4))  # < _MIN_GAMES (5)
    assert lbb.band_metrics("Tristana", 600.0, cs=120.0, level=8.0) == []


def test_mode_resolution_falls_back_to_sr(monkeypatch):
    # Only a normals ("sr") distribution exists - a coarse "SR" must resolve to it.
    _install(monkeypatch, _tristana(mode="sr"))
    out = lbb.band_metrics("Tristana", 600.0, cs=120.0)
    assert [b["metric"] for b in out] == ["cs_at_10"]


def test_no_data_metric_skipped(monkeypatch):
    champ = {
        "Tristana|sr_ranked": {
            "games": 10,
            "metrics": {"level_at_10": {"p25": 6.0, "p50": 7.0, "p75": 8.0}},
        }
    }
    _install(monkeypatch, champ)
    out = lbb.band_metrics("Tristana", 600.0, cs=120.0, level=8.0)
    assert [b["metric"] for b in out] == ["level_at_10"]


def test_fail_soft_inputs(monkeypatch):
    _install(monkeypatch, _tristana())
    assert lbb.band_metrics("", 600.0, cs=120.0) == []
    assert lbb.band_metrics("Tristana", 600.0, cs=None, level=None) == []
    assert lbb.band_metrics("Tristana", -10.0, cs=120.0) == []
    assert lbb.band_metrics("Tristana", "bad", cs=120.0) == []
    # bool must not be banded as an int.
    assert lbb.band_metrics("Tristana", 600.0, cs=True) == []


def test_band_from_state_adapter(monkeypatch):
    _install(monkeypatch, _tristana())
    state = {"champion": "Tristana", "cs": 120.0, "level": 8.0, "game_time_s": 600.0}
    out = lbb.band_from_state(state)
    assert {b["metric"] for b in out} == {"cs_at_10", "level_at_10"}
    # non-dict + missing champion are fail-soft.
    assert lbb.band_from_state(None) == []
    assert lbb.band_from_state({"cs": 120.0, "game_time_s": 600.0}) == []
