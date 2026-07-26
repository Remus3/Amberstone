"""Per-role cohort baselines from T0 sidecar rows."""
from __future__ import annotations

from core import cohort_baseline as cb


def _player(**over):
    base = {"TIME_PLAYED": "1200", "MINIONS_KILLED": "100",
            "NEUTRAL_MINIONS_KILLED": "20", "GOLD_EARNED": "10000",
            "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS": "20000",
            "TOTAL_DAMAGE_TAKEN": "18000", "VISION_SCORE": "20",
            "WARD_PLACED": "10", "WARD_KILLED": "4",
            "TIME_CCING_OTHERS": "12", "TOTAL_HEAL_ON_TEAMMATES": "0",
            "TOTAL_DAMAGE_DEALT_TO_TURRETS": "3000",
            "CHAMPIONS_KILLED": "5", "NUM_DEATHS": "3", "ASSISTS": "7"}
    base.update({k: str(v) for k, v in over.items()})
    return base


# ------------------------------------------------------------ row extraction

def test_rates_are_per_minute_of_time_played():
    # 120 cs over 1200 s = 20 min -> 6.0 per minute.
    m = cb.row_metrics(_player())
    assert round(m["cs_per_min"], 3) == 6.0
    assert round(m["gold_per_min"], 3) == 500.0


def test_counts_that_are_not_rates_stay_raw():
    m = cb.row_metrics(_player())
    assert m["kills"] == 5.0
    assert m["deaths"] == 3.0
    assert m["assists"] == 7.0


def test_a_short_row_is_dropped_rather_than_producing_a_wild_rate():
    # Dividing a full game's totals by a 60 s TIME_PLAYED invents a superhuman
    # cs/min and would poison every percentile in the cohort.
    assert cb.row_metrics(_player(TIME_PLAYED=60)) == {}
    assert cb.row_metrics(_player(TIME_PLAYED=cb.MIN_TIME_PLAYED_S)) != {}


def test_string_values_are_parsed_and_junk_is_zero_not_a_crash():
    # Every sidecar value is a string; a bad one must not abort a corpus build.
    m = cb.row_metrics(_player(GOLD_EARNED="not-a-number"))
    assert m["gold_per_min"] == 0.0


def test_a_missing_field_reads_as_zero():
    p = _player()
    del p["WARD_KILLED"]
    assert cb.row_metrics(p)["wards_killed_per_min"] == 0.0


def test_cs_sums_lane_and_jungle_minions():
    m = cb.row_metrics(_player(MINIONS_KILLED=200, NEUTRAL_MINIONS_KILLED=100))
    assert round(m["cs_per_min"], 3) == 15.0
    assert round(m["jungle_cs_per_min"], 3) == 5.0


# ------------------------------------------------------------------- build

def _rows(role, metric, values):
    return [(role, {metric: v}) for v in values]


def test_a_metric_under_twenty_samples_is_not_reported():
    # Percentiles over a handful of rows are noise with decimal places.
    out = cb.build(_rows("TOP", "cs_per_min", list(range(19))))
    assert out.get("TOP", {}).get("cs_per_min") is None
    out = cb.build(_rows("TOP", "cs_per_min", list(range(20))))
    assert out["TOP"]["cs_per_min"]["n"] == 20


def test_percentiles_are_ordered_and_bracket_the_median():
    out = cb.build(_rows("MID", "gold_per_min", list(range(100))))
    t = out["MID"]["gold_per_min"]
    assert t["p10"] < t["p25"] < t["p50"] < t["p75"] < t["p90"]
    assert round(t["p50"], 1) == 49.5


def test_percentile_interpolates_rather_than_snapping():
    assert cb._percentile([0.0, 10.0], 50) == 5.0
    assert cb._percentile([5.0], 90) == 5.0
    assert cb._percentile([], 50) == 0.0


# -------------------------------------------------------------------- rank

def test_rank_reports_the_band_a_value_reaches():
    base = cb.build(_rows("JUNGLE", "cs_per_min", list(range(100))))
    r = cb.rank_of(base, "JUNGLE", "cs_per_min", 95.0)
    assert r["at_or_above_p"] == 90
    low = cb.rank_of(base, "JUNGLE", "cs_per_min", 1.0)
    assert low["at_or_above_p"] == 0


def test_rank_of_an_unknown_cohort_is_none_not_average():
    # Returning a middling band for a cohort we have no data on would be a
    # fabricated comparison.
    base = cb.build(_rows("JUNGLE", "cs_per_min", list(range(100))))
    assert cb.rank_of(base, "SUPPORT", "cs_per_min", 5.0) is None
    assert cb.rank_of(base, "JUNGLE", "nonexistent_metric", 5.0) is None


def test_rank_carries_the_sample_size_and_median():
    base = cb.build(_rows("TOP", "cs_per_min", list(range(50))))
    r = cb.rank_of(base, "TOP", "cs_per_min", 30.0)
    assert r["n"] == 50
    assert "median" in r
