"""Regression tests for the .rofl pull path (core.rofl_archive pull helpers).

MEASURED CONTRACT (live client, 2026-07-19) - the tests below encode this:

  POST /lol-replays/v1/rofls/{gameId}/download/graceful  -> 204
  GET  /lol-replays/v1/metadata/{gameId}                 -> {"state": ...}

  state machine observed: "checking" -> "incompatible"   (patch 16.13, 14.24)
                          "watch"                        (already on disk, 16.14)

The `/graceful` variant runs a real compatibility check first; the plain
`/download` variant reported "incompatible" immediately. Replays remain hard
locked to the CURRENT game patch - graceful does NOT bypass that - so pulling is
only ever worth attempting for matches whose patch equals the live client's.

`archive_replays` copies what the client already wrote; `pull_replays` makes the
client FETCH a current-patch replay that was never manually saved. Together they
are the forward-capture pipeline.
"""
from __future__ import annotations

import logging

import pytest

from core import rofl_archive as ra


# ---------------------------------------------------------------------------
# patch / id helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "game_version,expected",
    [
        ("16.14.794.5912", "16.14"),   # the live client's real string
        ("16.13.700.1234", "16.13"),
        ("9.4.1", "9.4"),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_patch_from_game_version(game_version, expected):
    assert ra.patch_from_game_version(game_version) == expected


@pytest.mark.parametrize(
    "match_id,expected",
    [
        ("NA1_5592802194", "5592802194"),
        ("EUW1_1234567890", "1234567890"),
        ("5592802194", "5592802194"),
        ("garbage", None),
        ("", None),
    ],
)
def test_game_id_from_match_id(match_id, expected):
    assert ra.game_id_from_match_id(match_id) == expected


# ---------------------------------------------------------------------------
# candidate selection - the patch lock is the whole point
# ---------------------------------------------------------------------------

def test_select_pullable_keeps_only_current_patch():
    rows = [
        ("NA1_1", "16.14"),
        ("NA1_2", "16.13"),   # one patch back - measured incompatible
        ("NA1_3", "14.24"),
        ("NA1_4", "16.14"),
    ]
    assert ra.select_pullable(rows, "16.14") == ["NA1_1", "NA1_4"]


def test_select_pullable_is_empty_when_nothing_matches():
    """Today's real situation: the DB tops out at 16.13, client is on 16.14."""
    rows = [("NA1_1", "16.13"), ("NA1_2", "14.24")]
    assert ra.select_pullable(rows, "16.14") == []


def test_select_pullable_skips_already_archived():
    rows = [("NA1_1", "16.14"), ("NA1_2", "16.14")]
    assert ra.select_pullable(rows, "16.14", already={"NA1_1"}) == ["NA1_2"]


def test_select_pullable_tolerates_missing_patch():
    rows = [("NA1_1", None), ("NA1_2", ""), ("NA1_3", "16.14")]
    assert ra.select_pullable(rows, "16.14") == ["NA1_3"]


# ---------------------------------------------------------------------------
# pull loop - driven through an injected client, no live LCU needed
# ---------------------------------------------------------------------------

class _FakeClient:
    """Scripted stand-in for the LCU replay surface.

    `states` maps gameId -> list of states returned by successive metadata
    polls, so a checking->terminal transition can be replayed exactly.
    """

    def __init__(self, states, download_status=204):
        self.states = {k: list(v) for k, v in states.items()}
        self.download_status = download_status
        self.requested = []
        self.polls = 0

    def request_download(self, game_id):
        self.requested.append(game_id)
        return self.download_status

    def metadata(self, game_id):
        self.polls += 1
        seq = self.states.get(game_id) or ["incompatible"]
        return {"gameId": game_id, "state": seq.pop(0) if len(seq) > 1 else seq[0]}


def test_pull_returns_downloaded_for_a_watch_state():
    c = _FakeClient({"1": ["checking", "checking", "watch"]})
    res = ra.pull_replays(["NA1_1"], c, poll_interval=0, max_polls=5)
    assert res.downloaded == ["NA1_1"]
    assert res.incompatible == [] and res.timed_out == []
    assert c.requested == ["1"]


def test_pull_reports_incompatible_rather_than_silently_skipping(caplog):
    """An incompatible replay is the expected outcome for most ids and must be
    counted, not swallowed - otherwise a fully-failed pull looks like success."""
    c = _FakeClient({"1": ["checking", "incompatible"]})
    with caplog.at_level(logging.INFO, logger=ra.logger.name):
        res = ra.pull_replays(["NA1_1"], c, poll_interval=0, max_polls=5)
    assert res.incompatible == ["NA1_1"]
    assert res.downloaded == []


def test_pull_gives_up_after_max_polls():
    """A permanently 'checking' replay must not hang the caller forever."""
    c = _FakeClient({"1": ["checking"]})
    res = ra.pull_replays(["NA1_1"], c, poll_interval=0, max_polls=3)
    assert res.timed_out == ["NA1_1"]
    assert res.downloaded == [] and res.incompatible == []


def test_pull_records_a_failed_download_request():
    c = _FakeClient({"1": ["watch"]}, download_status=404)
    res = ra.pull_replays(["NA1_1"], c, poll_interval=0, max_polls=3)
    assert res.failed == ["NA1_1"]
    assert res.downloaded == []


def test_pull_handles_a_mixed_batch():
    c = _FakeClient({
        "1": ["checking", "watch"],
        "2": ["checking", "incompatible"],
        "3": ["checking"],
    })
    res = ra.pull_replays(["NA1_1", "NA1_2", "NA1_3"], c, poll_interval=0, max_polls=3)
    assert res.downloaded == ["NA1_1"]
    assert res.incompatible == ["NA1_2"]
    assert res.timed_out == ["NA1_3"]


def test_pull_of_an_empty_list_is_a_no_op():
    c = _FakeClient({})
    res = ra.pull_replays([], c, poll_interval=0, max_polls=3)
    assert res.downloaded == res.incompatible == res.timed_out == res.failed == []
    assert c.requested == []


def test_pull_skips_unparseable_match_ids():
    c = _FakeClient({"1": ["watch"]})
    res = ra.pull_replays(["garbage", "NA1_1"], c, poll_interval=0, max_polls=3)
    assert res.downloaded == ["NA1_1"]
    assert "garbage" in res.failed
