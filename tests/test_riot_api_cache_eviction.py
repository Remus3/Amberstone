# arch: RM-153 bounded-growth policy tests | section=tests | frozen=no
"""RM-153: a bounded-growth policy for `data/riot_api_cache.db`.

THE POLICY THESE TESTS PIN
--------------------------
Two halves, deliberately asymmetric:

  OBSERVABILITY - default ON. `stats_fast()` plus the `/metrics` gauges make
  the size visible on every scrape. Zero risk, and it is the half that was
  unambiguously owed: the DB reached 3.3 GB with nothing anywhere reporting
  the number.

  EVICTION - default OFF, opt-in, and it refuses to run without an explicit
  confirmation token. Nothing in RC calls it (pinned by a grep guard below).

WHY EVICTION IS NOT THE DEFAULT - THE ROW'S OWN HYPOTHESIS IS REFUTED
---------------------------------------------------------------------
RM-153 says to check first whether `rewind_history.db` and the `.rofl`
archive already retain this data, "so some of this 3.3 GB may be duplicated
retention rather than the only copy". Measured on the live tree 2026-08-04,
that is FALSE, and it is the finding that decides the policy:

    cached Match-V5 timelines            3123 rows / 2,531,532,421 B (76 pct)
    ... also in rewind_history.db         117  (3.75 pct)
    ... with a .rofl in the archive       316  (10.12 pct)
    ... in NEITHER                       2698  (86.39 pct) / 2,171,646,158 B

The two stores are near-disjoint populations, not copies of each other -
rewind_history carries frames for 2961 matches, 2844 of which the cache does
NOT have. A `.rofl` is not a substitute either, though not for the reason it
would be easy to assume: `core/rofl_archive.py:611 extract_stats` DOES parse
the replay's own trailing Layer-1 blob (magic `RIOT\\x02\\x00` -> `statsJson`,
10 players x ~367 engine-named end-of-game fields). What that blob has is a
FINAL SCOREBOARD; it carries no time series at all. A Match-V5 timeline is
per-minute frames plus events, so those 316 files still cannot reconstitute
one. Full packet parse is separately settled out of scope.

So evicting is NOT reclaiming a redundant second copy. It destroys the only
local copy of 86 pct of the timeline mass, recoverable only by re-fetching
from Riot against the rate limit - and not at all once Riot ages a match out,
or for the event modes whose Match-V5 route already 403s. That is why the
destructive half is opt-in and the observability half is not.

(Aside, so a later reader does not mis-size the corpus: the archive holds
3427 `.rofl` FILES but only 2041 distinct match ids - the same game is
archived under several per-player corpus directories.)

WHY THE SCRAPE PATH MUST NOT CALL `stats()`
-------------------------------------------
Measured on the live 3.3 GB DB, 2026-08-04, three runs each:

    SELECT COUNT(*) FROM cache_immutable          0.0004-0.0009s (covering idx)
    SELECT SUM(LENGTH(response_json)) FROM ...    4.36-4.59s (reads every payload)

Independently re-measured the same day at 3.78-5.67s warm and 8.37s cold, so
treat multiple seconds as the floor, not the outlier. `stats()` does the
second query. Putting it behind `/metrics` would add that to every Prometheus
scrape. `stats_fast()` exists for exactly that reason and omits the byte sum;
`TestMetricsPathIsCheap` pins that the gauge refresh never reaches it.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core import riot_api_cache as rac
from core.riot_api_cache import RiotApiCache
from tests import _repo_walk

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def cache(tmp_path):
    return RiotApiCache(db_path=tmp_path / "c.db")


def _fill(cache, *, timelines=0, details=0, accounts=0, size=2000):
    """Seed rows whose keys match the real key formats in core/riot_api.py."""
    made = []
    for i in range(timelines):
        k = f"match:v5:timeline:NA1_{i:06d}"
        cache.set_immutable(k, {"pad": "t" * size})
        made.append(k)
        time.sleep(0.001)
    for i in range(details):
        k = f"match:v5:NA1_{i:06d}"
        cache.set_immutable(k, {"pad": "d" * size})
        made.append(k)
        time.sleep(0.001)
    for i in range(accounts):
        k = f"account:v1:abc123def456:na1:name#tag{i}"
        cache.set_immutable(k, {"puuid": "p" * size})
        made.append(k)
        time.sleep(0.001)
    return made


# -- observability half (default ON) -------------------------------------


class TestStatsFast:
    def test_stats_fast_omits_the_expensive_byte_sum(self, cache):
        _fill(cache, details=3)
        fast = cache.stats_fast()
        assert "immutable_bytes" not in fast, (
            "stats_fast() must not carry immutable_bytes - computing it is a "
            "SUM(LENGTH(response_json)) full scan, measured at 4.36-4.59s on "
            "the live 3.3 GB DB, and this dict is refreshed on every /metrics "
            "scrape")

    def test_stats_fast_reports_rows_and_disk(self, cache):
        _fill(cache, timelines=2, details=3)
        cache.set_ttl("live", {"a": 1}, ttl_s=300)
        fast = cache.stats_fast()
        assert fast["immutable_rows"] == 5
        assert fast["ttl_live_rows"] == 1
        assert fast["disk_bytes"] > 0

    def test_disk_bytes_counts_the_wal_sidecars(self, cache, tmp_path):
        """The -wal/-shm sidecars ARE the database - RM-153 Windows trap.

        A size alarm that reads only the .db under-reports whatever is
        sitting unflushed in the WAL.
        """
        _fill(cache, details=5)
        db = tmp_path / "c.db"
        wal = tmp_path / "c.db-wal"
        wal.write_bytes(b"x" * 4096)
        assert cache.disk_bytes() >= db.stat().st_size + 4096

    def test_disk_bytes_on_a_missing_db_is_zero_not_an_error(self, tmp_path):
        assert RiotApiCache(db_path=tmp_path / "nope.db").disk_bytes() == 0

    def test_stats_still_reports_bytes_for_deliberate_callers(self, cache):
        """stats() keeps the expensive number - it is correct, just not
        something a scrape may call."""
        _fill(cache, details=2, size=500)
        assert cache.stats()["immutable_bytes"] >= 1000


# -- eviction half (default OFF) -----------------------------------------


class TestEvictionIsOptIn:
    def test_plan_eviction_deletes_nothing(self, cache):
        _fill(cache, timelines=5)
        before = cache.stats_fast()["immutable_rows"]
        plan = cache.plan_eviction(max_bytes=1)
        assert plan["over_cap"] is True
        assert plan["keys"], "a plan over a 1-byte cap must name victims"
        assert cache.stats_fast()["immutable_rows"] == before, \
            "plan_eviction must be read-only"

    def test_evict_refuses_without_a_token(self, cache):
        _fill(cache, timelines=5)
        before = cache.stats_fast()["immutable_rows"]
        res = cache.evict_to_cap(max_bytes=1)
        assert res["applied"] is False
        assert res["deleted"] == 0
        assert cache.stats_fast()["immutable_rows"] == before

    def test_evict_refuses_a_wrong_token(self, cache):
        _fill(cache, timelines=5)
        before = cache.stats_fast()["immutable_rows"]
        res = cache.evict_to_cap(max_bytes=1, confirm="yes")
        assert res["applied"] is False
        assert cache.stats_fast()["immutable_rows"] == before

    def test_under_the_cap_evicts_nothing_even_with_the_token(self, cache):
        _fill(cache, timelines=3)
        res = cache.evict_to_cap(max_bytes=10 * 1024 ** 3,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert res["deleted"] == 0
        assert res["over_cap"] is False
        assert cache.stats_fast()["immutable_rows"] == 3

    def test_no_production_caller_invokes_eviction(self):
        """The destructive half must stay opt-in - nothing may wire it up.

        Same shape as core/data_retention.apply(): the function exists so the
        policy has an enforcement arm, and NOTHING in RC calls it.

        Infrastructure exclusion comes from `tests/_repo_walk` (2026-09-07);
        `skip` keeps only the two trees that are this guard's OWN scope choice -
        tests and docs are allowed to name the function. The skip is applied to
        the path RELATIVE to the root: matching absolute parts returns nothing
        at all when the checkout itself sits under `.claude/worktrees/<id>`,
        which is indistinguishable from a clean tree.
        """
        hits = []
        skip = {"tests", "docs"}
        for p in _repo_walk.repo_files(_REPO_ROOT):
            if any(part in skip for part in p.relative_to(_REPO_ROOT).parts):
                continue
            if p.name == "riot_api_cache.py":
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "evict_to_cap" in text or "EVICT_CONFIRM_TOKEN" in text:
                hits.append(str(p.relative_to(_REPO_ROOT)))
        assert not hits, (
            "eviction is opt-in and must have zero production callers; "
            f"found: {hits}")


class TestEvictedRowIsRefetchable:
    def test_evicted_row_is_a_clean_miss_and_refetches(self, cache, tmp_path):
        """RM-153 acceptance: an evicted row must be RE-FETCHABLE."""
        rac._reset_for_tests(db_path=tmp_path / "c.db")
        try:
            key = "match:v5:timeline:NA1_000042"
            payload = {"info": {"frames": [1, 2, 3]}, "pad": "z" * 4000}
            rac.set_immutable(key, payload)
            assert rac.get_immutable(key) == payload

            res = rac.get_cache().evict_to_cap(
                max_bytes=1, confirm=rac.EVICT_CONFIRM_TOKEN)
            assert res["applied"] is True and res["deleted"] >= 1

            # A clean MISS, not an error and not an empty row.
            assert rac.get_immutable(key) is None

            calls = {"n": 0}

            def fetch():
                calls["n"] += 1
                return payload

            got = rac.cached_get(key, fetch)
            assert got == payload
            assert calls["n"] == 1, "eviction must produce a real re-fetch"

            # And it is cached again afterwards - the second call is a hit.
            assert rac.cached_get(key, fetch) == payload
            assert calls["n"] == 1
        finally:
            rac._reset_for_tests()

    def test_eviction_does_not_poison_the_immutable_contract(self, cache):
        """Survivors stay byte-identical and the schema stays valid."""
        keys = _fill(cache, timelines=6, size=3000)
        survivor = keys[-1]
        survivor_value = cache.get_immutable(survivor)

        res = cache.evict_to_cap(max_bytes=9000,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert res["deleted"] > 0

        assert cache.get_immutable(survivor) == survivor_value, \
            "eviction corrupted a row it was not supposed to touch"

        # Re-writing an evicted key restores it exactly - the contract that
        # an immutable key always maps to the same body is intact.
        evicted = res["keys"][0]
        assert cache.get_immutable(evicted) is None
        cache.set_immutable(evicted, {"pad": "t" * 3000})
        assert cache.get_immutable(evicted) == {"pad": "t" * 3000}

        conn = sqlite3.connect(str(cache._db_path))
        try:
            assert conn.execute(
                "PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()

    def test_ttl_table_is_untouched_by_immutable_eviction(self, cache):
        _fill(cache, timelines=4)
        cache.set_ttl("rank", {"tier": "GOLD"}, ttl_s=300)
        cache.evict_to_cap(max_bytes=1, confirm=rac.EVICT_CONFIRM_TOKEN)
        assert cache.get_ttl("rank") == {"tier": "GOLD"}


class TestEvictionOrder:
    def test_timelines_go_before_match_details(self, cache):
        """Timelines are 810 KB/row against 86 KB for details (measured
        2026-08-04), so they free the most bytes for the fewest rows lost."""
        _fill(cache, timelines=4, details=4, size=3000)
        # Cap chosen so the deficit is smaller than the timeline mass: if
        # ordering were ignored, details would show up in the plan.
        plan = cache.plan_eviction(max_bytes=15000)
        assert plan["keys"], "expected victims over this cap"
        assert all(k.startswith("match:v5:timeline:") for k in plan["keys"]), \
            f"details evicted before timelines were exhausted: {plan['keys']}"

    def test_account_rows_are_never_evicted(self, cache):
        """114 rows / 15 KB total on the live DB - no space back, and
        re-resolving a PUUID costs a rate-limited round trip."""
        _fill(cache, timelines=2, details=2, accounts=3, size=2000)
        res = cache.evict_to_cap(max_bytes=1,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert not any(k.startswith("account:v1:") for k in res["keys"])
        rows = cache.stats_fast()["immutable_rows"]
        assert rows == 3, f"only the 3 account rows should survive, got {rows}"

    def test_account_protection_holds_under_a_sweeping_prefix(
            self, cache, monkeypatch):
        """The _NEVER_EVICT guard must be load-bearing, not decorative.

        With the shipped _EVICT_ORDER no prefix can reach an account key, so
        deleting the guard changes nothing and a test that only exercises the
        default order passes either way (measured - that mutation SURVIVED).
        This drives the guard directly with a prefix that sweeps everything,
        which is what a future _EVICT_ORDER entry would do by accident.
        """
        _fill(cache, timelines=2, accounts=3, size=2000)
        monkeypatch.setattr(rac, "_EVICT_ORDER", ("",))
        res = cache.evict_to_cap(max_bytes=1,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert not any(k.startswith("account:v1:") for k in res["keys"]), \
            "a sweeping prefix reached account rows - _NEVER_EVICT is inert"
        assert cache.stats_fast()["immutable_rows"] == 3

    def test_oldest_rows_go_first_within_a_class(self, cache):
        keys = _fill(cache, timelines=5, size=3000)
        plan = cache.plan_eviction(max_bytes=6000)
        # keys[] is insertion-ordered, so the oldest are at the front.
        assert plan["keys"][0] == keys[0]

    def test_eviction_stops_once_under_the_cap(self, cache):
        _fill(cache, timelines=10, size=3000)
        before = cache.stats()["immutable_bytes"]
        cap = before // 2
        cache.evict_to_cap(max_bytes=cap, confirm=rac.EVICT_CONFIRM_TOKEN)
        after = cache.stats()["immutable_bytes"]
        assert after <= cap, "eviction did not reach the cap"
        assert after > 0, "eviction overshot and emptied the table"


class TestVacuumHonesty:
    def test_result_says_a_vacuum_is_required(self, cache):
        """Deleting rows moves pages to the freelist; the FILE does not
        shrink until a VACUUM. An eviction that silently left the 3.3 GB on
        disk would look like it did nothing."""
        _fill(cache, timelines=5, size=3000)
        res = cache.evict_to_cap(max_bytes=6000,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert res["deleted"] > 0
        assert res["vacuum_required"] is True

    def test_no_vacuum_claim_when_nothing_was_deleted(self, cache):
        _fill(cache, timelines=2)
        res = cache.evict_to_cap(max_bytes=10 * 1024 ** 3,
                                 confirm=rac.EVICT_CONFIRM_TOKEN)
        assert res["vacuum_required"] is False


class TestDefaultCap:
    def test_default_cap_matches_the_data_retention_alarm(self):
        """One number, two modules. core/data_retention.py alarms at this
        size; the cache must not disagree with it."""
        from core.data_retention import DEFAULT_MAX_CACHE_BYTES
        assert rac.DEFAULT_MAX_IMMUTABLE_BYTES == DEFAULT_MAX_CACHE_BYTES


class TestAsciiHygiene:
    def test_module_is_seven_bit_ascii(self):
        for name in ("core/riot_api_cache.py",
                     "tests/test_riot_api_cache_eviction.py"):
            raw = (_REPO_ROOT / name).read_bytes()
            bad = [b for b in raw if b > 127]
            assert not bad, f"{name} carries {len(bad)} non-ASCII byte(s)"


class TestMetricsPathIsCheap:
    """The gauge refresh must never reach the multi-second payload scan."""

    def test_gauge_refresh_does_not_call_stats(self, tmp_path, monkeypatch):
        """The spy RECORDS, it does not raise.

        A raising spy is vacuous here: `_refresh_cache_gauges` wraps its body
        in `except Exception`, and AssertionError is an Exception, so the
        signal would be swallowed and logged at DEBUG. Measured - pointing the
        refresh back at stats() left the raising version GREEN. Record the
        call, delegate to the real method so behaviour is unchanged, and
        assert on the record after the call returns.
        """
        from dashboard import routes_metrics

        rac._reset_for_tests(db_path=tmp_path / "c.db")
        try:
            _fill(rac.get_cache(), timelines=2)

            calls = []
            real_stats = RiotApiCache.stats

            def recording_stats(self):
                calls.append(1)
                return real_stats(self)

            monkeypatch.setattr(RiotApiCache, "stats", recording_stats)
            # Poison a gauge the refresh is required to overwrite. Without
            # this, a refresh that died on its first line would also record
            # zero stats() calls and pass while proving nothing.
            routes_metrics._G_CACHE_IMMUTABLE_ROWS.set(-1)
            routes_metrics._refresh_cache_gauges()

            assert not calls, (
                "the /metrics path called stats(), whose "
                "SUM(LENGTH(response_json)) was measured at 4.36-4.59s warm "
                "and 8.37s cold on the live 3.3 GB DB - use stats_fast()")
            # render() emits HELP/TYPE plus one VALUE line per labelset, so
            # the poisoned -1 is visible here and nowhere else.
            rendered = routes_metrics._G_CACHE_IMMUTABLE_ROWS.render()
            assert not any(ln.endswith(" -1") for ln in rendered), (
                "the refresh never completed, so the stats() assertion above "
                f"proved nothing: {rendered}")
        finally:
            rac._reset_for_tests()

    def test_subprocess_import_of_the_module_is_clean(self):
        """Guards against an import-time DB open sneaking in."""
        out = subprocess.run(
            [sys.executable, "-c", "import core.riot_api_cache"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
