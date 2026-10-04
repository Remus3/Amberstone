"""RM-510: an ingest run that ends with rate-limited rows must not exit 0.

RM-484 made `tools/timeline_ingest.py` report a throttled match as the
'rate_limited' tally row instead of writing a permanent partial, but main()
still returned 0, so a scheduler or a chained shell step read a run that left
work undone as a clean success. The same shape lived in
`tools/ladder_role_scout.py` (a persistently throttled match or ids call was
counted, the role file written, and 0 returned).

Exit-code contract (both tools; see the module docstrings):
    0   clean run - nothing was left undone by a throttle or a hard failure
    75  EX_TEMPFAIL (BSD sysexits.h) - the run finished, at least one call
        stayed rate limited after every retry, and no row failed hard.
        Re-running later is expected to finish the work.
    1   at least one row failed hard (not a throttle). Hard wins over tempfail.

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

from core import replay_roster as rr  # noqa: E402
from core import riot_api as RA  # noqa: E402
from core import riot_retry  # noqa: E402
from tools import ladder_role_scout as lrs  # noqa: E402
from tools import timeline_ingest as ti  # noqa: E402


def _throttle(*_a, **_k):
    RA._record_outcome("429")
    return None


def _not_found(*_a, **_k):
    RA._record_outcome("not_found")
    return None


def _ok(value):
    def _fn(*_a, **_k):
        RA._record_outcome("ok")
        return value
    return _fn


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch):
    monkeypatch.setattr(riot_retry, "_sleep", lambda _s: None)
    monkeypatch.setattr(ti, "_pace", lambda: None)
    monkeypatch.setattr(lrs, "_MIN_INTERVAL_S", 0.0)


def test_contract_constant_is_ex_tempfail():
    assert ti.EX_TEMPFAIL == 75
    assert lrs.EX_TEMPFAIL == 75


# --------------------------------------------------------- timeline_ingest

def _wire_ingest(monkeypatch, *, account=None, ids=None, match=None,
                 timeline=None):
    monkeypatch.setattr(rr, "load_roster", lambda: [
        SimpleNamespace(riot_id="A#NA1", name="A", tag="NA1")])
    monkeypatch.setattr(RA, "get_account_by_riot_id",
                        account or _ok({"puuid": "P1"}))
    monkeypatch.setattr(RA, "_call", ids or _ok(["NA1_1", "NA1_2"]))
    monkeypatch.setattr(RA, "get_match", match or _ok({"info": {}}))
    monkeypatch.setattr(RA, "get_match_timeline",
                        timeline or _ok({"frames": [1]}))


def _run_ingest(tmp_path):
    with redirect_stdout(io.StringIO()) as buf:
        code = ti.main(["--root", str(tmp_path), "--per-account", "2",
                        "--quiet"])
    return code, buf.getvalue()


def test_ingest_clean_run_exits_zero(tmp_path, monkeypatch):
    _wire_ingest(monkeypatch)
    code, _ = _run_ingest(tmp_path)
    assert code == 0
    assert len(list((tmp_path / "timelines").glob("*.json"))) == 2


def test_ingest_rate_limited_rows_exit_tempfail(tmp_path, monkeypatch):
    """The RM-510 bug: DONE {'rate_limited': 2} used to return 0."""
    _wire_ingest(monkeypatch, timeline=_throttle)
    code, out = _run_ingest(tmp_path)
    assert "'rate_limited': 2" in out
    assert code == ti.EX_TEMPFAIL


def test_ingest_hard_fail_wins_over_rate_limited(tmp_path, monkeypatch):
    seen = {"n": 0}

    def _match(mid):
        seen["n"] += 1
        return _not_found() if mid == "NA1_1" else _ok({"info": {}})()

    _wire_ingest(monkeypatch, match=_match, timeline=_throttle)
    code, out = _run_ingest(tmp_path)
    assert "'fail': 1" in out and "'rate_limited': 1" in out
    assert code == 1


def test_ingest_throttled_account_lookup_exits_tempfail(tmp_path, monkeypatch):
    _wire_ingest(monkeypatch, account=_throttle)
    code, _ = _run_ingest(tmp_path)
    assert code == ti.EX_TEMPFAIL


def test_ingest_throttled_ids_page_exits_tempfail(tmp_path, monkeypatch):
    """A throttled ids page truncates that account's history for this run."""
    _wire_ingest(monkeypatch, ids=_throttle)
    code, _ = _run_ingest(tmp_path)
    assert code == ti.EX_TEMPFAIL


def test_ingest_real_missing_timeline_partial_still_exits_zero(tmp_path,
                                                               monkeypatch):
    """A 404 timeline is a fact about the match, not undone work."""
    _wire_ingest(monkeypatch, timeline=_not_found)
    code, out = _run_ingest(tmp_path)
    assert "'partial': 2" in out
    assert code == 0


# ------------------------------------------------------- ladder_role_scout

_SCOUT_MATCH = {"info": {"participants": [
    {"puuid": "P1", "teamPosition": "TOP", "riotIdGameName": "A",
     "riotIdTagline": "NA1"}]}}


def _scout_call(ids_throttled=False):
    def _call(endpoint, url, rate_limit_timeout_s=5.0):
        if endpoint == "league_v4":
            RA._record_outcome("ok")
            return {"entries": [{"puuid": "P1", "leaguePoints": 900},
                                {"puuid": "P2", "leaguePoints": 800}]}
        if ids_throttled and "P2" in url:
            return _throttle()
        RA._record_outcome("ok")
        return ["M1"] if "P1" in url else ["M2"]
    return _call


def _run_scout(out):
    with redirect_stdout(io.StringIO()):
        return lrs.main(["--out", str(out), "--min-share", "0.5"])


def test_scout_clean_run_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "_call", _scout_call())
    monkeypatch.setattr(RA, "get_match", _ok(_SCOUT_MATCH))
    assert _run_scout(tmp_path / "o.json") == 0


def test_scout_throttled_match_exits_tempfail(tmp_path, monkeypatch):
    out = tmp_path / "o.json"
    monkeypatch.setattr(RA, "_call", _scout_call())
    monkeypatch.setattr(
        RA, "get_match",
        lambda mid: _throttle() if mid == "M2" else _ok(_SCOUT_MATCH)())
    assert _run_scout(out) == lrs.EX_TEMPFAIL
    # The partial result is still written; the exit code carries the gap.
    assert json.loads(out.read_text())["match_failures"] == 1


def test_scout_throttled_ids_exits_tempfail(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "_call", _scout_call(ids_throttled=True))
    monkeypatch.setattr(RA, "get_match", _ok(_SCOUT_MATCH))
    assert _run_scout(tmp_path / "o.json") == lrs.EX_TEMPFAIL


def test_scout_hard_match_failure_exits_one(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "_call", _scout_call())
    monkeypatch.setattr(
        RA, "get_match",
        lambda mid: _not_found() if mid == "M2" else _ok(_SCOUT_MATCH)())
    assert _run_scout(tmp_path / "o.json") == 1
