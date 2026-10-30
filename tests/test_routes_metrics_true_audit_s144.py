"""Lane 8 (true-audit) s144 cycle 67: dashboard/routes_metrics.py hardening.

One test group per finding F1-F6 from the cycle report. Every source the
scrape reads (health.json, DecisionStore, the cost tracker, the Riot API
cache) is injected, so nothing here opens a live store or the live DB.

F1  one junk health.json field raised out of _refresh_gauges, so the whole
    /metrics body became a 500 and every other gauge was lost with it.
F2  a non-finite number (health age 1e400, a NaN / Infinity literal in the
    spend ledger) was stored in a gauge, and core.prom_metrics._format_value
    then raised on EVERY later render - /metrics stayed 500 until restart.
F3  a value that became UNKNOWN (key absent or None, store unreadable) left
    the previous scrape's number in the gauge, served as if it were current.
F4  rc_alive used truthiness, so "false" / "0" / 1 read as alive.
F5  a bool was accepted as an age or a count (True -> 1.0).
F6  one junk field from stats_fast() aborted the remaining cache gauges and
    left rc_riot_api_cache_over_cap stale.
"""
from __future__ import annotations

import pytest

from core import prom_metrics
from core import riot_api_cache as rac
from core.prom_metrics import render_all
from dashboard import routes_metrics as rm

_ALL = (
    "rc_alive",
    "rc_dashboard_ui_pulse_age_seconds",
    "rc_game_poll_worker_age_seconds",
    "rc_decisions_pending",
    "rc_daily_spend_usd",
    "rc_daily_calls",
    "rc_riot_api_cache_disk_bytes",
    "rc_riot_api_cache_immutable_rows",
    "rc_riot_api_cache_ttl_live_rows",
    "rc_riot_api_cache_over_cap",
)


def _value(name: str):
    """The unlabelled sample for `name`, or None when no sample is emitted.

    The # HELP / # TYPE lines render whether or not a value was ever set, so
    only a line starting with `name ` counts as a sample.
    """
    for line in render_all().splitlines():
        if line.startswith(name + " "):
            return float(line.rsplit(" ", 1)[1])
    return None


class _Store:
    def __init__(self, items=None, exc=None):
        self.items = items if items is not None else []
        self.exc = exc

    def list_pending(self):
        if self.exc is not None:
            raise self.exc
        return self.items


class _Tracker:
    def __init__(self, spend=None, exc=None):
        self.spend = spend if spend is not None else {"total_usd": 0.0, "calls": 0}
        self.exc = exc

    def daily_spend(self):
        if self.exc is not None:
            raise self.exc
        return self.spend


class _Cache:
    def __init__(self, stats=None, exc=None):
        self.stats = stats if stats is not None else {
            "disk_bytes": 10, "immutable_rows": 2, "ttl_live_rows": 1}
        self.exc = exc

    def stats_fast(self):
        if self.exc is not None:
            raise self.exc
        return self.stats


class _Handler:
    def __init__(self):
        self.sent = []

    def _send(self, code, body, ctype):
        self.sent.append((code, body, ctype))


@pytest.fixture()
def src(monkeypatch):
    """Injectable sources; each test mutates the attributes it needs."""
    import core.cost_tracker as ct
    import core.decision_detector as dd

    state = type("S", (), {})()
    state.health = {"alive": True, "ui_pulse_age_s": 1.5,
                    "game_poll_worker_age_s": 2.5}
    state.store = _Store([{"id": "a"}, {"id": "b"}])
    state.tracker = _Tracker({"total_usd": 0.25, "calls": 7})
    state.cache = _Cache()
    monkeypatch.setattr(rm, "read_json", lambda rel: state.health)
    monkeypatch.setattr(dd, "DecisionStore", lambda: state.store)
    monkeypatch.setattr(ct, "get_tracker", lambda: state.tracker)
    monkeypatch.setattr(rac, "get_cache", lambda: state.cache)
    monkeypatch.setattr(rm, "_CACHE_CAP_BYTES", 100)
    return state


def _scrape():
    h = _Handler()
    rm._serve_metrics(h)
    assert len(h.sent) == 1
    return h.sent[0]


class TestBaseline:
    def test_good_sources_fill_every_gauge(self, src):
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_alive") == 1
        assert _value("rc_dashboard_ui_pulse_age_seconds") == 1.5
        assert _value("rc_game_poll_worker_age_seconds") == 2.5
        assert _value("rc_decisions_pending") == 2
        assert _value("rc_daily_spend_usd") == 0.25
        assert _value("rc_daily_calls") == 7
        assert _value("rc_riot_api_cache_disk_bytes") == 10
        assert _value("rc_riot_api_cache_immutable_rows") == 2
        assert _value("rc_riot_api_cache_ttl_live_rows") == 1
        assert _value("rc_riot_api_cache_over_cap") == 0


class TestF1JunkHealthFieldDegradesOnlyItself:
    @pytest.mark.parametrize("junk", ["abc", [1], {"x": 1}, "1e3x"])
    def test_junk_ui_age_keeps_the_scrape_alive(self, src, junk):
        src.health = {"alive": True, "ui_pulse_age_s": junk,
                      "game_poll_worker_age_s": 3.0}
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_dashboard_ui_pulse_age_seconds") is None
        assert _value("rc_game_poll_worker_age_seconds") == 3.0
        assert _value("rc_decisions_pending") == 2
        assert _value("rc_riot_api_cache_disk_bytes") == 10

    def test_junk_worker_age_keeps_the_ui_age(self, src):
        src.health = {"alive": True, "ui_pulse_age_s": 4.0,
                      "game_poll_worker_age_s": "soon"}
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_dashboard_ui_pulse_age_seconds") == 4.0
        assert _value("rc_game_poll_worker_age_seconds") is None

    def test_non_dict_health_reads_as_empty(self, src):
        _scrape()
        src.health = ["not", "a", "dict"]
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_alive") == 0
        assert _value("rc_dashboard_ui_pulse_age_seconds") is None

    def test_numeric_string_is_still_read(self, src):
        """Characterization: float("2.5") was accepted before; keep it."""
        src.health = {"alive": True, "ui_pulse_age_s": "2.5"}
        _scrape()
        assert _value("rc_dashboard_ui_pulse_age_seconds") == 2.5


class TestF2NonFiniteNeverWedgesTheScrape:
    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"),
                                     "Infinity", "nan"])
    def test_non_finite_health_age_is_dropped(self, src, bad):
        src.health = {"alive": True, "ui_pulse_age_s": bad,
                      "game_poll_worker_age_s": 3.0}
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_dashboard_ui_pulse_age_seconds") is None
        # The NEXT scrape must not be poisoned by what the first one saw.
        src.health = {"alive": True, "ui_pulse_age_s": 5.0}
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_dashboard_ui_pulse_age_seconds") == 5.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_spend_is_dropped(self, src, bad):
        src.tracker = _Tracker({"total_usd": bad, "calls": bad})
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_daily_spend_usd") is None
        assert _value("rc_daily_calls") is None
        assert _value("rc_decisions_pending") == 2

    @pytest.mark.parametrize("v, text", [(float("nan"), "NaN"),
                                         (float("inf"), "+Inf"),
                                         (float("-inf"), "-Inf")])
    def test_format_value_renders_non_finite_per_text_format(self, v, text):
        assert prom_metrics._format_value(v) == text

    def test_format_value_finite_is_unchanged(self):
        assert prom_metrics._format_value(3.0) == "3"
        assert prom_metrics._format_value(0.25) == "0.25"
        assert prom_metrics._format_value(1e16) == "1e+16"

    def test_render_all_survives_a_nan_gauge(self):
        """Any OTHER caller that sets a non-finite gauge must not 500 /metrics."""
        g = rm._G_RC_ALIVE
        try:
            g.set(float("nan"))
            body = render_all()
            assert "\nrc_alive NaN\n" in body
        finally:
            g.set(0.0)


class TestF3UnknownClearsTheGauge:
    def test_worker_age_none_drops_the_previous_value(self, src):
        _scrape()
        assert _value("rc_game_poll_worker_age_seconds") == 2.5
        src.health = {"alive": True, "ui_pulse_age_s": 1.0,
                      "game_poll_worker_age_s": None}
        _scrape()
        assert _value("rc_game_poll_worker_age_seconds") is None

    def test_missing_health_file_drops_both_ages(self, src):
        _scrape()
        src.health = {}
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_alive") == 0
        assert _value("rc_dashboard_ui_pulse_age_seconds") is None
        assert _value("rc_game_poll_worker_age_seconds") is None

    def test_unreadable_decision_store_drops_pending(self, src):
        _scrape()
        assert _value("rc_decisions_pending") == 2
        src.store = _Store(exc=OSError("locked"))
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_decisions_pending") is None

    def test_failing_tracker_drops_spend_and_calls(self, src):
        _scrape()
        src.tracker = _Tracker(exc=RuntimeError("ledger gone"))
        code, _body, _ = _scrape()
        assert code == 200
        assert _value("rc_daily_spend_usd") is None
        assert _value("rc_daily_calls") is None

    def test_non_dict_spend_drops_spend_and_calls(self, src):
        _scrape()
        src.tracker = _Tracker(spend=["not", "a", "dict"])
        _scrape()
        assert _value("rc_daily_spend_usd") is None
        assert _value("rc_daily_calls") is None

    def test_failing_cache_drops_every_cache_gauge(self, src):
        _scrape()
        src.cache = _Cache(exc=RuntimeError("db gone"))
        code, _body, _ = _scrape()
        assert code == 200
        for name in _ALL[6:]:
            assert _value(name) is None, name

    def test_a_good_scrape_after_unknown_restores_values(self, src):
        src.health = {}
        _scrape()
        src.health = {"alive": True, "ui_pulse_age_s": 9.0,
                      "game_poll_worker_age_s": 8.0}
        _scrape()
        assert _value("rc_dashboard_ui_pulse_age_seconds") == 9.0
        assert _value("rc_game_poll_worker_age_seconds") == 8.0


class TestF4AliveIsStrict:
    @pytest.mark.parametrize("v", ["false", "0", "true", 1, [1], {"a": 1}])
    def test_only_a_real_true_is_alive(self, src, v):
        src.health = {"alive": v}
        _scrape()
        assert _value("rc_alive") == 0

    def test_true_is_alive(self, src):
        src.health = {"alive": True}
        _scrape()
        assert _value("rc_alive") == 1


class TestF5BoolIsNotANumber:
    def test_bool_age_is_dropped(self, src):
        src.health = {"alive": True, "ui_pulse_age_s": True,
                      "game_poll_worker_age_s": False}
        _scrape()
        assert _value("rc_dashboard_ui_pulse_age_seconds") is None
        assert _value("rc_game_poll_worker_age_seconds") is None

    def test_bool_spend_is_dropped(self, src):
        src.tracker = _Tracker({"total_usd": True, "calls": True})
        _scrape()
        assert _value("rc_daily_spend_usd") is None
        assert _value("rc_daily_calls") is None


class TestF6CacheFieldsDegradeIndependently:
    def test_one_junk_row_count_keeps_the_rest(self, src):
        src.cache = _Cache({"disk_bytes": 500, "immutable_rows": "x",
                            "ttl_live_rows": 3})
        _scrape()
        assert _value("rc_riot_api_cache_disk_bytes") == 500
        assert _value("rc_riot_api_cache_immutable_rows") is None
        assert _value("rc_riot_api_cache_ttl_live_rows") == 3
        assert _value("rc_riot_api_cache_over_cap") == 1

    def test_junk_disk_bytes_drops_disk_and_over_cap(self, src):
        _scrape()
        assert _value("rc_riot_api_cache_over_cap") == 0
        src.cache = _Cache({"disk_bytes": "big", "immutable_rows": 4,
                            "ttl_live_rows": 0})
        _scrape()
        assert _value("rc_riot_api_cache_disk_bytes") is None
        assert _value("rc_riot_api_cache_over_cap") is None
        assert _value("rc_riot_api_cache_immutable_rows") == 4
        assert _value("rc_riot_api_cache_ttl_live_rows") == 0

    def test_non_dict_stats_drops_every_cache_gauge(self, src):
        _scrape()
        src.cache = _Cache(stats=[1, 2, 3])
        _scrape()
        for name in _ALL[6:]:
            assert _value(name) is None, name


class TestRenderFailureIsGeneric:
    def test_render_failure_is_500_with_fixed_body(self, src, monkeypatch):
        def boom():
            raise RuntimeError("secret detail")
        monkeypatch.setattr(rm, "render_all", boom)
        code, body, ctype = _scrape()
        assert code == 500
        assert body == b"metrics_render_failed"
        assert b"secret" not in body
        assert ctype == "text/plain"
