"""RM-484: the offline-tool siblings of e1a1d13f7 (429 None-conflation).

Every public `core.riot_api` helper returns a bare None for both "no such
resource" and "Riot rate-limited us". These offline ingest tools read that None
as ABSENCE. Each test below stubs the HTTP seam the way `_call_ex` really
behaves on a 429: it records the outcome into any open `track_outcomes()`
scope (`riot_api._record_outcome`, core/riot_api.py) and returns None.

Fully offline: every network seam and every sleep is monkeypatched.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

from core import riot_api as RA  # noqa: E402
from core import riot_retry  # noqa: E402
from tools import build_rank_baselines as brb  # noqa: E402
from tools import ladder_role_scout as lrs  # noqa: E402
from tools import replay_roster_pull as rpp  # noqa: E402
from tools import rofl_archiver as ra  # noqa: E402
from tools import timeline_ingest as ti  # noqa: E402


def _throttled_then(value, throttles: int = 1, outcome: str = "429"):
    """A helper stub: the first *throttles* calls are 429s, then *value*."""
    calls = {"n": 0}

    def _fn(*_a, **_k):
        calls["n"] += 1
        if calls["n"] <= throttles:
            RA._record_outcome(outcome)
            return None
        RA._record_outcome("ok")
        return value

    _fn.calls = calls
    return _fn


def _not_found(*_a, **_k):
    RA._record_outcome("not_found")
    return None


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch):
    naps = []
    monkeypatch.setattr(riot_retry, "_sleep", naps.append)
    monkeypatch.setattr(ti, "_pace", lambda: None)
    monkeypatch.setattr(rpp, "_pace", lambda: None)
    monkeypatch.setattr(brb, "_pace", lambda: None)
    monkeypatch.setattr(lrs, "_MIN_INTERVAL_S", 0.0)
    return naps


# ------------------------------------------------------------- the helper

def test_helper_returns_at_once_on_ok(_no_waits):
    assert riot_retry.fetch_unthrottled(lambda: 7) == (7, False)
    assert _no_waits == []


def test_helper_retries_a_throttle_then_succeeds(_no_waits):
    fn = _throttled_then({"x": 1})
    assert riot_retry.fetch_unthrottled(fn) == ({"x": 1}, False)
    assert fn.calls["n"] == 2
    assert len(_no_waits) == 1


def test_helper_retries_the_local_bucket_refusal_too(_no_waits):
    fn = _throttled_then([1], outcome="rate_limited")
    assert riot_retry.fetch_unthrottled(fn) == ([1], False)


def test_helper_never_retries_a_real_absence(_no_waits):
    calls = []

    def fn():
        calls.append(1)
        return _not_found()

    assert riot_retry.fetch_unthrottled(fn) == (None, False)
    assert len(calls) == 1 and _no_waits == []


def test_helper_reports_a_persistent_throttle(_no_waits):
    fn = _throttled_then("never", throttles=99)
    assert riot_retry.fetch_unthrottled(fn, attempts=3) == (None, True)
    assert fn.calls["n"] == 3
    assert len(_no_waits) == 2


# --------------------------------------------------------- timeline_ingest

def test_ids_page_throttle_does_not_end_the_history(monkeypatch):
    """Old: `if not page: break` read a 429 as end-of-history."""
    monkeypatch.setattr(RA, "_call", _throttled_then(["M1", "M2", "M3"]))
    assert ti.match_ids_for("p", 3) == ["M1", "M2", "M3"]


def test_throttled_timeline_is_not_persisted_as_partial(tmp_path, monkeypatch):
    """Old: wrote {timeline: None}; resume then skipped it forever as 'have'."""
    monkeypatch.setattr(RA, "get_match", lambda mid: {"info": {}})
    monkeypatch.setattr(RA, "get_match_timeline",
                        _throttled_then({"frames": []}, throttles=99))
    assert ti.ingest_match("NA1_1", tmp_path) == "rate_limited"
    assert not (tmp_path / "NA1_1.json").exists()


def test_throttled_match_is_reported_as_rate_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "get_match", _throttled_then({}, throttles=99))
    assert ti.ingest_match("NA1_2", tmp_path) == "rate_limited"


def test_a_real_missing_timeline_is_still_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "get_match", lambda mid: {"info": {}})
    monkeypatch.setattr(RA, "get_match_timeline", _not_found)
    assert ti.ingest_match("NA1_3", tmp_path) == "partial"
    assert json.loads((tmp_path / "NA1_3.json").read_text())["timeline"] is None


def test_retry_partial_backfills_a_polluted_file(tmp_path, monkeypatch):
    """Recovery for files already written by the old code."""
    dest = tmp_path / "NA1_4.json"
    dest.write_text(json.dumps({"match": {"m": 1}, "timeline": None}))
    monkeypatch.setattr(RA, "get_match",
                        lambda mid: pytest.fail("match half must be reused"))
    monkeypatch.setattr(RA, "get_match_timeline", lambda mid: {"frames": [1]})
    assert ti.ingest_match("NA1_4", tmp_path) == "have"     # default: cheap
    assert ti.ingest_match("NA1_4", tmp_path, retry_partial=True) == "ok"
    blob = json.loads(dest.read_text())
    assert blob == {"match": {"m": 1}, "timeline": {"frames": [1]}}


# ------------------------------------------------------- ladder_role_scout

def _ladder_call_stub(ladder_throttles=0, ids_throttles=0):
    state = {"ladder": 0, "ids": 0}

    def _call(endpoint, url, rate_limit_timeout_s=5.0):
        if endpoint == "league_v4":
            state["ladder"] += 1
            if state["ladder"] <= ladder_throttles:
                RA._record_outcome("429")
                return None
            RA._record_outcome("ok")
            return {"entries": [{"puuid": "P1", "leaguePoints": 900}]}
        state["ids"] += 1
        if state["ids"] <= ids_throttles:
            RA._record_outcome("429")
            return None
        RA._record_outcome("ok")
        return ["M1"]
    return _call


_SCOUT_MATCH = {"info": {"participants": [
    {"puuid": "P1", "teamPosition": "TOP", "riotIdGameName": "A",
     "riotIdTagline": "NA1"}]}}


def test_throttled_ladder_does_not_overwrite_the_role_file(tmp_path, monkeypatch):
    """Old: None -> [] -> '0 entries' -> an EMPTY role file replaced the good one."""
    out = tmp_path / "ladder_role_mains.json"
    out.write_text('{"keep": true}')
    monkeypatch.setattr(RA, "_call", _ladder_call_stub(ladder_throttles=99))
    with redirect_stdout(io.StringIO()):
        code = lrs.main(["--out", str(out)])
    assert code != 0
    assert out.read_text() == '{"keep": true}'


def test_scout_retries_throttled_ids_and_matches(tmp_path, monkeypatch):
    out = tmp_path / "ladder_role_mains.json"
    monkeypatch.setattr(RA, "_call",
                        _ladder_call_stub(ladder_throttles=1, ids_throttles=1))
    monkeypatch.setattr(RA, "get_match", _throttled_then(_SCOUT_MATCH))
    with redirect_stdout(io.StringIO()):
        code = lrs.main(["--out", str(out), "--min-share", "0.5"])
    blob = json.loads(out.read_text())
    assert code == 0
    assert blob["accounts_dropped"] == 0
    assert blob["match_failures"] == 0
    assert [r["riot_id"] for r in blob["roles"]["TOP"]] == ["A#NA1"]


# ------------------------------------------------------ replay_roster_pull

def test_queue_lookup_retries_a_throttle(monkeypatch):
    """Old: None -> 'queue unresolved' -> REJECTED, and the replay rotates out."""
    monkeypatch.setattr(RA, "get_match", _throttled_then({"info": {"queueId": 420}}))
    assert rpp._queue_lookup("NA1_9") == 420


def test_throttled_replay_listing_records_no_empty_observation(tmp_path, monkeypatch):
    """Old: `get_replay_urls(...) or []` recorded an EMPTY rotation window."""
    seen = []
    monkeypatch.setattr(RA, "get_account_by_riot_id", lambda n, t: {"puuid": "P"})
    monkeypatch.setattr(RA, "get_replay_urls", _throttled_then([], throttles=99))
    monkeypatch.setattr(rpp, "record_pull_observation",
                        lambda *a, **k: seen.append(a))
    entry = SimpleNamespace(role="TOP", name="A", tag="NA1", riot_id="A#NA1")
    with redirect_stdout(io.StringIO()) as buf:
        rc = rpp._pull_one(entry, tmp_path, (420,), dry_run=False, extract=False)
    assert rc == 1
    assert seen == []
    assert "RATE LIMITED" in buf.getvalue()


# ----------------------------------------------------------- rofl_archiver

def test_archiver_names_a_throttle_instead_of_blaming_the_key(tmp_path, monkeypatch):
    """Not a data defect (it skips, no observation); the diagnosis was wrong."""
    monkeypatch.setattr(RA, "get_account_by_riot_id",
                        _throttled_then({"puuid": "P"}, throttles=99))
    with redirect_stdout(io.StringIO()) as buf:
        ra._api_pull([("A", "NA1")], tmp_path, tmp_path / "index.json")
    text = buf.getvalue()
    assert "rate limited" in text
    assert "PRODUCT key" not in text


def test_archiver_throttled_listing_is_not_called_unentitled(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "get_account_by_riot_id", lambda n, t: {"puuid": "P"})
    monkeypatch.setattr(RA, "get_replay_urls", _throttled_then([], throttles=99))
    with redirect_stdout(io.StringIO()) as buf:
        ra._api_pull([("A", "NA1")], tmp_path, tmp_path / "index.json")
    text = buf.getvalue()
    assert "rate limited" in text
    assert "not entitled" not in text


# ----------------------------------------------------- build_rank_baselines

def test_rank_match_ids_retries_a_throttle(monkeypatch):
    """Old: `... or []` - a throttled account silently contributed nothing."""
    monkeypatch.setattr(RA, "_call", _throttled_then(["M1", "M2"]))
    assert brb.match_ids("p", 2) == ["M1", "M2"]


def test_rank_accounts_retry_a_throttle(monkeypatch):
    monkeypatch.setattr(RA, "_call",
                        _throttled_then({"entries": [{"puuid": "P1"}]}))
    assert brb.accounts_for_cohort("MASTER", None, 5) == ["P1"]


def test_fully_throttled_cohort_does_not_overwrite_a_good_one(tmp_path, monkeypatch):
    """Old: every ids call 429 -> matches=0 cohort replaced the stored one."""
    out = tmp_path / "rank_baselines.json"
    good = {"tier": "MASTER", "division": None, "matches": 40,
            "player_rows": 400, "roles": {}, "marker": 1}
    out.write_text(json.dumps({"tiers": {"MASTER": good}}))
    monkeypatch.setattr(brb, "accounts_for_cohort", lambda t, d, w: ["P1"])

    def _ids(endpoint, url, rate_limit_timeout_s=5.0):
        RA._record_outcome("429")
        return None
    monkeypatch.setattr(RA, "_call", _ids)
    with redirect_stdout(io.StringIO()):
        code = brb.main(["--out", str(out), "--tiers", "MASTER"])
    blob = json.loads(out.read_text())
    assert code != 0
    assert blob["tiers"]["MASTER"] == good
    assert "MASTER" in blob["skipped"]
