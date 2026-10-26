"""RM-905 / MAIN FIX 2026-10-25 1930 section 2: RC-ReplayRosterPull exited 1
on every hourly run.

Measured causes:

1. Riot IDs that Account-V1 no longer knows (renamed or retagged players)
   answered 404, and `_pull_one` returned 1 for every one of them, so ten stale
   roster rows failed the whole run. A 404 is Riot answering "nobody owns this
   id": it is a reported skip. Any other lookup failure still fails the run.
2. `/replays` answers 403 for every account on the current key (the route is
   entitled to the production-app key only). The None was read as an EMPTY
   listing: an empty rotation observation was appended for every account and
   riot_api logged one 403 warning per account. Now the first 403 stops the
   route for the rest of the run, records nothing, and is reported ONCE.
   Ruling (adjudicator, recorded in the commit): the run exits 0 on that class
   only while the ACTIVE key's fingerprint is acknowledged in the gitignored
   ack file (the filed operator ask names that key); an unacknowledged key
   that still answers 403 exits 1.

Fully offline: every network seam and every sleep is monkeypatched, and the
status / ack files live under tmp_path.
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
from tools import replay_roster_pull as rpp  # noqa: E402


def _outcome(value, outcome):
    def _fn(*_a, **_k):
        RA._record_outcome(outcome)
        return value
    return _fn


def _entry(name="A", tag="NA1", role="TOP"):
    return SimpleNamespace(role=role, name=name, tag=tag, riot_id=f"{name}#{tag}")


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setattr(riot_retry, "_sleep", lambda _s: None)
    monkeypatch.setattr(rpp, "_pace", lambda: None)
    monkeypatch.setattr(rpp, "_STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(rpp, "_ACK_PATH", tmp_path / "ack.json")
    monkeypatch.setattr(rpp, "_key_fingerprint", lambda: "fp-personal")


def _run_one(entry, tmp_path, tally=None):
    with redirect_stdout(io.StringIO()) as buf:
        rc = rpp._pull_one(entry, tmp_path, (420,), dry_run=False,
                           extract=False, tally=tally)
    return rc, buf.getvalue()


# ------------------------------------------------------------ account 404

def test_not_found_account_is_a_reported_skip_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(RA, "get_account_by_riot_id", _outcome(None, "not_found"))
    tally = rpp._RunTally()
    rc, out = _run_one(_entry(), tmp_path, tally)
    assert rc == 0
    assert tally.stale_ids == 1
    assert "NOT FOUND" in out
    assert "ACCOUNT LOOKUP FAILED" not in out


@pytest.mark.parametrize("outcome", ["error", "no_key", "forbidden"])
def test_other_account_lookup_failures_still_fail(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(RA, "get_account_by_riot_id", _outcome(None, outcome))
    tally = rpp._RunTally()
    rc, out = _run_one(_entry(), tmp_path, tally)
    assert rc == 1
    assert tally.stale_ids == 0
    assert "ACCOUNT LOOKUP FAILED" in out


# --------------------------------------------------------- /replays 403

def test_forbidden_listing_records_nothing_and_stops_the_route(tmp_path, monkeypatch):
    seen = []
    listing = {"n": 0}

    def _replays(_puuid):
        listing["n"] += 1
        RA._record_outcome("forbidden")
        return None

    monkeypatch.setattr(RA, "get_account_by_riot_id",
                        _outcome({"puuid": "P"}, "ok"))
    monkeypatch.setattr(RA, "get_replay_urls", _replays)
    monkeypatch.setattr(rpp, "record_pull_observation",
                        lambda *a, **k: seen.append(a))
    tally = rpp._RunTally()
    rc1, out1 = _run_one(_entry("A"), tmp_path, tally)
    rc2, out2 = _run_one(_entry("B"), tmp_path, tally)
    assert (rc1, rc2) == (0, 0)
    assert seen == []                       # no empty rotation observation
    assert listing["n"] == 1                # the route is not asked twice
    assert tally.replays_forbidden is True
    assert tally.replays_blocked == 2
    assert "403" in out1
    assert out2 == ""                        # reported once, not per account


def test_empty_but_served_listing_is_still_observed(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(RA, "get_account_by_riot_id",
                        _outcome({"puuid": "P"}, "ok"))
    monkeypatch.setattr(RA, "get_replay_urls", _outcome([], "ok"))
    monkeypatch.setattr(rpp, "record_pull_observation",
                        lambda *a, **k: seen.append(a))
    monkeypatch.setattr(rpp, "download_replays", lambda *a, **k: SimpleNamespace(
        downloaded=[], skipped=[], gone=[], expired=[], failed=[]))
    tally = rpp._RunTally()
    rc, _out = _run_one(_entry(), tmp_path, tally)
    assert rc == 0
    assert len(seen) == 1
    assert tally.replays_forbidden is False


# ------------------------------------------------------------- run verdict

def _roster(tmp_path, ids):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps({"players": [
        {"role": "TOP", "riot_id": i} for i in ids]}), encoding="utf-8")
    return p


def _main(tmp_path, roster):
    with redirect_stdout(io.StringIO()) as buf:
        rc = rpp.main(["--roster", str(roster), "--root", str(tmp_path / "corpus"),
                       "--no-extract"])
    return rc, buf.getvalue()


def _stub_world(monkeypatch, stale=("Gone#NA1",)):
    def _acct(name, tag):
        if f"{name}#{tag}" in stale:
            RA._record_outcome("not_found")
            return None
        RA._record_outcome("ok")
        return {"puuid": "P-" + name}

    monkeypatch.setattr(RA, "get_account_by_riot_id", _acct)
    monkeypatch.setattr(RA, "get_replay_urls", _outcome(None, "forbidden"))


def test_acknowledged_key_blocked_run_exits_zero(tmp_path, monkeypatch):
    _stub_world(monkeypatch)
    (tmp_path / "ack.json").write_text(json.dumps(
        {"replays_forbidden_ack": {"fp-personal": "operator ask: production key pending"}}),
        encoding="utf-8")
    rc, out = _main(tmp_path, _roster(tmp_path, ["A#NA1", "Gone#NA1", "B#NA1"]))
    assert rc == 0
    assert out.count("BLOCKED") == 1
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["exit"] == 0
    assert status["stale_ids"] == 1
    assert status["replays_blocked"] is True
    assert status["blocked_acknowledged"] is True
    assert status["accounts"] == 3
    assert "Gone" not in json.dumps(status)  # no Riot ID in the status file


def test_unacknowledged_key_blocked_run_exits_one(tmp_path, monkeypatch):
    _stub_world(monkeypatch)
    rc, out = _main(tmp_path, _roster(tmp_path, ["A#NA1"]))
    assert rc == 1
    assert "BLOCKED" in out
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["blocked_acknowledged"] is False
    assert status["exit"] == 1


def test_a_changed_key_is_not_covered_by_the_old_ack(tmp_path, monkeypatch):
    _stub_world(monkeypatch)
    (tmp_path / "ack.json").write_text(json.dumps(
        {"replays_forbidden_ack": {"fp-old": "old key"}}), encoding="utf-8")
    rc, _out = _main(tmp_path, _roster(tmp_path, ["A#NA1"]))
    assert rc == 1


def test_stale_ids_alone_exit_zero(tmp_path, monkeypatch):
    _stub_world(monkeypatch, stale=("Gone#NA1",))
    monkeypatch.setattr(RA, "get_replay_urls", _outcome([], "ok"))
    monkeypatch.setattr(rpp, "record_pull_observation", lambda *a, **k: None)
    monkeypatch.setattr(rpp, "download_replays", lambda *a, **k: SimpleNamespace(
        downloaded=[], skipped=[], gone=[], expired=[], failed=[]))
    rc, out = _main(tmp_path, _roster(tmp_path, ["A#NA1", "Gone#NA1"]))
    assert rc == 0
    assert "stale_ids=1" in out
