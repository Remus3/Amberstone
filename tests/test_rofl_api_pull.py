"""Regression tests for the SANCTIONED Match-V5 replay pull.

MEASURED CONTRACT (2026-07-19), which these tests encode:

  GET https://americas.api.riotgames.com
      /lol/match/v5/matches/by-puuid/{puuid}/replays
  -> 200 {"total": 5, "matchFileURLs": [...]}

Each URL is a PRE-SIGNED S3 link on `lol-prod-us-west-2-match-history-replay`
carrying `response-content-disposition=attachment; filename="NA1_xxxx.rofl"`.

Two bounds are real and are tested here because both bite silently:
  - `X-Amz-Expires=3600` - ONE hour. A stale URL 403s with no useful body, so
    it is detected up front rather than counted as a download failure.
  - exactly FIVE per account - a rolling recency window, NOT an archive. The
    pull is therefore only useful because the archive is IDEMPOTENT and
    ACCUMULATES: run it on a cadence and the window's leavings are kept.

Rate limit is 20000/10s, so throughput never binds; there is deliberately no
backoff here for a limit that cannot be reached.
"""
from __future__ import annotations

import json

import pytest

from core import operator_identity
from core import rofl_archive as ra


_URL = (
    "https://lol-prod-us-west-2-match-history-replay.s3.us-west-2.amazonaws.com"
    "/NA1/5595187452.rofl"
    "?response-content-disposition=attachment%3B%20filename%3D%22NA1_5595187452.rofl%22"
    "&X-Amz-Date=20260719T120000Z&X-Amz-Expires=3600&X-Amz-Signature=deadbeef"
)

# _URL carries a fixed signature time, so any test that exercises the DOWNLOAD
# path must pin the clock inside the window - otherwise it silently drifts into
# the expiry branch and stops testing what it claims to. Expiry has its own
# dedicated cases below.
_SIGNED_AT = 1784462400          # 2026-07-19T12:00:00Z
_FRESH = _SIGNED_AT + 60


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def test_match_id_from_replay_url_reads_the_attachment_filename():
    # The filename in content-disposition is the authoritative id; it is
    # already in RC's underscore form and joins onto matches.match_id.
    assert ra.match_id_from_replay_url(_URL) == "NA1_5595187452"


def test_match_id_from_replay_url_falls_back_to_the_path():
    bare = "https://s3.example/NA1-5595187452.rofl?X-Amz-Expires=3600"
    assert ra.match_id_from_replay_url(bare) == "NA1_5595187452"


def test_match_id_from_replay_url_returns_none_when_unparseable():
    assert ra.match_id_from_replay_url("https://s3.example/notareplay") is None
    assert ra.match_id_from_replay_url("") is None


# ---------------------------------------------------------------------------
# the 1-hour expiry bound
# ---------------------------------------------------------------------------

def test_replay_url_expiry_is_read_from_the_signature():
    signed_at = 1784462400          # 2026-07-19T12:00:00Z, matches _URL
    assert ra.replay_url_expired(_URL, now=signed_at + 60) is False
    # 3600s later the signature is dead; S3 answers 403 with no useful body.
    assert ra.replay_url_expired(_URL, now=signed_at + 3601) is True


def test_replay_url_without_a_signature_is_not_treated_as_expired():
    # Unknown expiry must not silently drop a URL that might be good; let the
    # download attempt decide.
    assert ra.replay_url_expired("https://s3.example/NA1_1.rofl", now=0) is False


# ---------------------------------------------------------------------------
# download pass
# ---------------------------------------------------------------------------

class _FakeFetcher:
    """Stand-in for the HTTP GET. Records what it was asked for."""

    def __init__(self, payloads=None, fail=()):
        self.payloads = payloads or {}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        mid = ra.match_id_from_replay_url(url)
        if mid in self.fail:
            raise OSError("simulated transport failure")
        return self.payloads.get(mid, b"RIOT\x02\x00fake-replay-body")


def test_download_replays_writes_files_and_indexes_them(tmp_path):
    fetch = _FakeFetcher()
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.downloaded == ["NA1_5595187452"]
    dest = tmp_path / "NA1_5595187452.rofl"
    assert dest.is_file()
    assert dest.read_bytes().startswith(b"RIOT")
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "NA1_5595187452" in index["replays"]
    assert index["replays"]["NA1_5595187452"]["source"] == "match_v5_replays"


def test_download_replays_skips_what_is_already_archived(tmp_path):
    fetch = _FakeFetcher()
    ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    # THE property the whole cadence strategy rests on: a repeat pull of the
    # same rolling window costs one skip, not one re-download.
    assert res.skipped == ["NA1_5595187452"]
    assert res.downloaded == []
    assert len(fetch.calls) == 1


def test_download_replays_accumulates_across_rotating_windows(tmp_path):
    """The 5-per-account window rotates; the ARCHIVE is what accumulates."""
    def url(mid):
        return f"https://s3.example/{mid}.rofl?X-Amz-Expires=3600"

    fetch = _FakeFetcher()
    ra.download_replays([url("NA1_1"), url("NA1_2")], tmp_path, fetcher=fetch)
    res = ra.download_replays([url("NA1_2"), url("NA1_3")], tmp_path, fetcher=fetch)

    assert res.downloaded == ["NA1_3"]
    assert res.skipped == ["NA1_2"]
    archived = sorted(p.name for p in tmp_path.glob("*.rofl"))
    assert archived == ["NA1_1.rofl", "NA1_2.rofl", "NA1_3.rofl"]


def test_download_replays_counts_failures_rather_than_dropping_them(tmp_path):
    fetch = _FakeFetcher(fail={"NA1_5595187452"})
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.failed == ["NA1_5595187452"]
    assert res.downloaded == []
    # No half-written artifact may survive a failed transfer.
    assert list(tmp_path.glob("*.rofl")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_download_replays_skips_expired_urls_before_spending_a_request(tmp_path):
    expired = (
        "https://s3.example/NA1_9.rofl"
        "?X-Amz-Date=20260101T000000Z&X-Amz-Expires=3600"
    )
    fetch = _FakeFetcher()
    res = ra.download_replays([expired], tmp_path, fetcher=fetch, now=4102444800)

    assert res.expired == ["NA1_9"]
    assert fetch.calls == []


def test_download_replays_rejects_a_body_that_is_not_a_replay(tmp_path):
    # S3 error bodies are XML and arrive with a 200 in some edge cases; writing
    # one under a .rofl name would poison the archive AND the extract pass.
    fetch = _FakeFetcher(payloads={"NA1_5595187452": b"<?xml version='1.0'?><Error/>"})
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.failed == ["NA1_5595187452"]
    assert list(tmp_path.glob("*.rofl")) == []


def test_download_replays_handles_an_empty_url_list(tmp_path):
    res = ra.download_replays([], tmp_path, fetcher=_FakeFetcher())
    assert (res.downloaded, res.skipped, res.failed, res.expired) == ([], [], [], [])


# ---------------------------------------------------------------------------
# account fan-out
# ---------------------------------------------------------------------------

def test_default_accounts_comes_from_config_and_is_well_formed():
    # Each configured account has its own 5-replay window, and each PUUID must
    # be resolved by Riot ID rather than read from storage (stored PUUIDs are
    # scoped to whichever key resolved them). The LIST is per-install config,
    # so this asserts the SHAPE, not any one person's accounts - an
    # unconfigured clone legitimately has none.
    accounts = ra.DEFAULT_ACCOUNTS
    assert isinstance(accounts, list)
    assert len(accounts) == len(set(accounts)), "duplicate account in config"
    for entry in accounts:
        name, tag = entry
        assert name and tag
        assert "#" not in name and "#" not in tag


def test_default_accounts_reads_the_operator_identity_config(monkeypatch):
    # The wiring is the point: a config change must reach DEFAULT_ACCOUNTS,
    # otherwise the constant silently keeps whatever it was born with.
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "Alpha#AAA,Beta#BBB,Alpha#AAA")
    assert operator_identity.accounts() == [("Alpha", "AAA"), ("Beta", "BBB")]
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "no-tagline-here")
    assert operator_identity.accounts() == []


def test_parse_account_accepts_the_riot_id_form():
    assert ra.parse_account("SamplePlayer#Vayne") == ("SamplePlayer", "Vayne")
    with pytest.raises(ValueError):
        ra.parse_account("SamplePlayer")


# ---------------------------------------------------------------------------
# rotation observation log - the evidence for the cadence hypothesis
# ---------------------------------------------------------------------------

def test_pull_observations_append_one_row_per_pull(tmp_path):
    # The open question is whether the 5-per-account window ROTATES as games
    # are played. That is only answerable by comparing pulls over time, so each
    # pull records what it saw. Append-only: overwriting would destroy the very
    # comparison it exists to enable.
    ra.record_pull_observation(tmp_path, "SamplePlayer#Trist",
                               ["NA1_1", "NA1_2"], now=100.0)
    ra.record_pull_observation(tmp_path, "SamplePlayer#Trist",
                               ["NA1_2", "NA1_3"], now=200.0)

    rows = ra.load_pull_observations(tmp_path)
    assert [r["match_ids"] for r in rows] == [["NA1_1", "NA1_2"], ["NA1_2", "NA1_3"]]
    assert rows[0]["account"] == "SamplePlayer#Trist"
    assert rows[1]["observed_at_unix"] == 200.0


def test_pull_observations_report_whether_the_window_rotated(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1", "NA1_2"], now=100.0)
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_2", "NA1_3"], now=200.0)
    ra.record_pull_observation(tmp_path, "B#2", ["NA1_9"], now=100.0)
    ra.record_pull_observation(tmp_path, "B#2", ["NA1_9"], now=200.0)

    report = ra.pull_rotation_report(tmp_path)
    assert report["A#1"]["rotated"] is True
    assert report["A#1"]["new_ids"] == ["NA1_3"]
    assert report["B#2"]["rotated"] is False
    assert report["B#2"]["new_ids"] == []


def test_pull_rotation_report_needs_two_observations_to_say_anything(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1"], now=100.0)
    report = ra.pull_rotation_report(tmp_path)
    # One sample cannot show rotation; saying "False" would be a fabricated
    # negative answer to the open question.
    assert report["A#1"]["rotated"] is None


# ---------------------------------------------------------------------------
# transport encoding - MEASURED on the first live pull
# ---------------------------------------------------------------------------

def test_download_replays_gunzips_a_gzipped_body(tmp_path):
    """MEASURED 2026-07-19: every body came back gzip-framed (\x1f\x8b), not
    raw container magic. urllib does not decompress, so without this the whole
    pull is rejected by the is-this-a-replay guard - which is exactly what the
    first live run did (5 of 5 discarded)."""
    import gzip
    real = b"RIOT\x02\x00" + b"\x00" * 64
    fetch = _FakeFetcher(payloads={"NA1_5595187452": gzip.compress(real)})

    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.downloaded == ["NA1_5595187452"]
    assert (tmp_path / "NA1_5595187452.rofl").read_bytes() == real


def test_download_replays_still_rejects_gzipped_garbage(tmp_path):
    import gzip
    fetch = _FakeFetcher(payloads={"NA1_5595187452": gzip.compress(b"<Error/>")})
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)
    assert res.failed == ["NA1_5595187452"]
    assert list(tmp_path.glob("*.rofl")) == []


def test_download_skips_a_replay_already_archived_under_the_client_naming(tmp_path):
    """The two sources spell the same match differently: the client writes
    "NA1-5595187452.rofl" (hyphen) and this downloader writes the underscore
    form. Keying the skip on the FILENAME re-downloads 10 MB and leaves two
    copies of one game - measured on the live archive."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "NA1-5595187452.rofl").write_bytes(b"RIOT\x02\x00" + b"\x00" * 16)
    ra.archive_replays(tmp_path, tmp_path)      # index it as the client's copy

    fetch = _FakeFetcher()
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.skipped == ["NA1_5595187452"]
    assert fetch.calls == []
    assert not (tmp_path / "NA1_5595187452.rofl").exists()


def test_a_404_is_gone_not_failed(tmp_path):
    """MEASURED: one account's five URLs all 404 - Riot lists the match but no
    longer retains the file. That is PERMANENT and EXPECTED, so counting it as
    a failure would make the 15-minute scheduled task report LastTaskResult=1
    forever and bury a real failure in the noise."""
    import urllib.error

    class _Gone:
        calls = []

        def __call__(self, url):
            self.calls.append(url)
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    res = ra.download_replays([_URL], tmp_path, fetcher=_Gone(), now=_FRESH)

    assert res.gone == ["NA1_5595187452"]
    assert res.failed == []


def test_a_real_transport_error_is_still_a_failure(tmp_path):
    res = ra.download_replays([_URL], tmp_path,
                              fetcher=_FakeFetcher(fail={"NA1_5595187452"}),
                              now=_FRESH)
    assert res.failed == ["NA1_5595187452"]
    assert res.gone == []
