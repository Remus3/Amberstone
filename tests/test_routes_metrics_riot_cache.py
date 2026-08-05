# arch: RM-153 /metrics cache-size gauges | section=tests | frozen=no
"""RM-153: `data/riot_api_cache.db` size must be visible on `/metrics`.

The DB reached 3.3 GB with nothing anywhere reporting the number - `stats()`
had no production callers at all. These tests pin the observability half of
the RM-153 policy: the size, the row counts and an over-cap alarm are
exposed as Prometheus gauges so the NEXT 3 GB is noticed before it arrives.

The gauges are deliberately built from `stats_fast()`, never `stats()`.
Measured on the live DB 2026-08-04, `stats()` runs a
`SUM(LENGTH(response_json))` full scan taking 4.36-4.59s warm and 8.37s cold;
`stats_fast()` uses covering-index counts at under a millisecond. The
companion `tests/test_riot_api_cache_eviction.py`
pins that the refresh never reaches the expensive call.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import riot_api_cache as rac
from core.prom_metrics import render_all

_REPO_ROOT = Path(__file__).resolve().parent.parent

_EXPECTED_GAUGES = (
    "rc_riot_api_cache_disk_bytes",
    "rc_riot_api_cache_immutable_rows",
    "rc_riot_api_cache_ttl_live_rows",
    "rc_riot_api_cache_over_cap",
)


@pytest.fixture()
def temp_singleton(tmp_path):
    """Point the module singleton at a scratch DB.

    Non-negotiable: the live DB is 3.3 GB and running WAL. A test must never
    open it - see the RM-153 Windows trap.
    """
    rac._reset_for_tests(db_path=tmp_path / "c.db")
    yield rac.get_cache()
    rac._reset_for_tests()


class TestGaugesAreExposed:
    def test_all_cache_gauges_render(self, temp_singleton):
        from dashboard import routes_metrics

        temp_singleton.set_immutable("match:v5:NA1_1", {"a": "x" * 100})
        temp_singleton.set_ttl("league:v4:na1:p", {"t": "GOLD"}, ttl_s=300)
        routes_metrics._refresh_cache_gauges()

        body = render_all()
        for name in _EXPECTED_GAUGES:
            # _gauge_line requires a VALUE line. A bare `name in body` would
            # be satisfied by the module-scope `# HELP` comment alone.
            _gauge_line(body, name)

    def test_row_counts_are_real_values(self, temp_singleton):
        from dashboard import routes_metrics

        for i in range(4):
            temp_singleton.set_immutable(f"match:v5:NA1_{i}", {"a": 1})
        routes_metrics._refresh_cache_gauges()

        line = _gauge_line(render_all(), "rc_riot_api_cache_immutable_rows")
        assert line.endswith(" 4"), line

    def test_disk_bytes_is_positive(self, temp_singleton):
        from dashboard import routes_metrics

        temp_singleton.set_immutable("match:v5:NA1_1", {"a": "x" * 5000})
        routes_metrics._refresh_cache_gauges()

        line = _gauge_line(render_all(), "rc_riot_api_cache_disk_bytes")
        assert float(line.rsplit(" ", 1)[1]) > 0, line


class TestOverCapAlarm:
    def test_over_cap_is_zero_under_the_cap(self, temp_singleton):
        from dashboard import routes_metrics

        temp_singleton.set_immutable("match:v5:NA1_1", {"a": 1})
        routes_metrics._refresh_cache_gauges()
        line = _gauge_line(render_all(), "rc_riot_api_cache_over_cap")
        assert line.endswith(" 0"), line

    def test_over_cap_flips_to_one_past_the_cap(self, temp_singleton,
                                                monkeypatch):
        from dashboard import routes_metrics

        temp_singleton.set_immutable("match:v5:NA1_1", {"a": "x" * 5000})
        # A 1-byte cap is unambiguously breached by any real DB file.
        monkeypatch.setattr(routes_metrics, "_CACHE_CAP_BYTES", 1)
        routes_metrics._refresh_cache_gauges()
        line = _gauge_line(render_all(), "rc_riot_api_cache_over_cap")
        assert line.endswith(" 1"), line

    def test_cap_defaults_to_the_shared_policy_number(self):
        from dashboard import routes_metrics

        assert routes_metrics._CACHE_CAP_BYTES == \
            rac.DEFAULT_MAX_IMMUTABLE_BYTES


class TestRefreshIsFailSoft:
    def test_a_broken_cache_does_not_break_the_scrape(self, monkeypatch):
        """A /metrics scrape must never 500 because the cache is unhappy.

        Here the raise is the STIMULUS, not the signal - but a refresh that
        stopped calling get_cache() entirely would also "not raise" and would
        prove nothing, so record the call and require it happened.
        """
        from dashboard import routes_metrics

        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("db gone")

        monkeypatch.setattr(rac, "get_cache", boom)
        routes_metrics._refresh_cache_gauges()  # must not raise
        assert calls, "the refresh never reached get_cache(), so the " \
                      "fail-soft path was not exercised at all"

    def test_full_refresh_includes_the_cache_gauges(self, temp_singleton):
        """The scrape entry point must actually call the new refresh.

        Asserting the gauge NAME appears in the exposition is not enough: the
        Gauge is declared at module scope, so its `# HELP` and `# TYPE` lines
        render whether or not anything ever set a value. Measured - unwiring
        the refresh call left that weaker assertion GREEN. Poison the value
        first, then require the refresh to have overwritten it.
        """
        from dashboard import routes_metrics

        temp_singleton.set_immutable("match:v5:NA1_1", {"a": 1})
        routes_metrics._G_CACHE_IMMUTABLE_ROWS.set(-1)
        routes_metrics._refresh_gauges()

        line = _gauge_line(render_all(), "rc_riot_api_cache_immutable_rows")
        assert not line.endswith(" -1"), (
            "_refresh_gauges() never refreshed the cache gauges - the scrape "
            "path is not wired to _refresh_cache_gauges()")
        assert line.endswith(" 1"), line


class TestAsciiHygiene:
    def test_files_are_seven_bit_ascii(self):
        for name in ("dashboard/routes_metrics.py",
                     "tests/test_routes_metrics_riot_cache.py"):
            raw = (_REPO_ROOT / name).read_bytes()
            bad = [b for b in raw if b > 127]
            assert not bad, f"{name} carries {len(bad)} non-ASCII byte(s)"


def _gauge_line(body: str, name: str) -> str:
    for line in body.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "{"):
            return line
    raise AssertionError(f"{name} not found in exposition")
