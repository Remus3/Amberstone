# arch: regression - live-client subresource reads must be falsifiable | section=vision | frozen=no
"""Silent-except triage BATCH 3 / finding A4.

`game_reader/poller.py:250-253` `_get` does NOT swallow - it lets urllib raise.
That makes the four handlers in the rune / ability readers of
`game_reader/snapshot_normalizer.py` the SOLE swallow point for a 404,
endpoint rename or auth change on the Live Client subresources
`/activeplayerrunes`, `/playermainrunes?summonerName=` and
`/activeplayerabilities`.

Those fields feed live coach prompts directly (`coaches/aram_coach.py:350, 352`),
so a permanently-404ing endpoint degrades every coach prompt with zero operator
signal. These tests fail while the failure is logged at DEBUG only: caplog is
pinned to WARNING so a DEBUG line cannot satisfy them.
"""

import logging
import urllib.error

import pytest

from game_reader.snapshot_normalizer import (
    _NormalizerMixin,
    get_liveclient_subresource_failures,
    reset_liveclient_subresource_failures,
)

_LOGGER_NAME = "game_reader.snapshot_normalizer"


def _http_404(url="https://127.0.0.1:2999/liveclientdata/x"):
    return urllib.error.HTTPError(url, 404, "Not Found", {}, None)


class _Faulted(_NormalizerMixin):
    """Minimal host for the mixin whose `_get` raises like the real one does."""

    def __init__(self, exc_factory=_http_404):
        self._exc_factory = exc_factory
        self.calls = 0

    def _get(self, url):
        self.calls += 1
        raise self._exc_factory()


@pytest.fixture(autouse=True)
def _clean_counters():
    reset_liveclient_subresource_failures()
    yield
    reset_liveclient_subresource_failures()


ENEMIES = [{"championName": "Ahri", "riotIdGameName": "SomeEnemy"}]


@pytest.mark.parametrize(
    "method,args,expected_empty,subresource",
    [
        ("_read_my_runes", (), "", "/activeplayerrunes"),
        ("_read_my_runes_structured", (), {}, "/activeplayerrunes"),
        ("_read_enemy_runes", (ENEMIES,), {}, "/playermainrunes"),
        ("_read_my_abilities", (), {}, "/activeplayerabilities"),
    ],
)
def test_subresource_404_emits_warning(
    caplog, method, args, expected_empty, subresource
):
    """A 404 from `_get` must produce a record at level >= WARNING.

    Fails while the handler logs at DEBUG only.
    """
    reader = _Faulted()
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    result = getattr(reader, method)(*args)

    # The degrade-to-empty contract is preserved - the read never raises.
    assert result == expected_empty
    assert reader.calls == 1

    warnings = [
        r for r in caplog.records
        if r.name == _LOGGER_NAME and r.levelno >= logging.WARNING
    ]
    assert warnings, (
        f"{method} swallowed a 404 without any record at >= WARNING; "
        "the live-client subresource failure is unfalsifiable"
    )
    assert subresource in warnings[0].getMessage()


@pytest.mark.parametrize(
    "method,args,subresource",
    [
        ("_read_my_runes", (), "/activeplayerrunes"),
        ("_read_my_runes_structured", (), "/activeplayerrunes"),
        ("_read_enemy_runes", (ENEMIES,), "/playermainrunes"),
        ("_read_my_abilities", (), "/activeplayerabilities"),
    ],
)
def test_subresource_404_increments_degradation_counter(method, args, subresource):
    """Each swallowed failure must increment a per-subresource counter."""
    reader = _Faulted()

    assert get_liveclient_subresource_failures() == {}

    getattr(reader, method)(*args)
    assert get_liveclient_subresource_failures().get(subresource) == 1

    getattr(reader, method)(*args)
    assert get_liveclient_subresource_failures().get(subresource) == 2


def test_warning_is_throttled_but_counter_is_not(caplog):
    """The poller runs continuously - a per-tick WARNING would spam the log.

    The counter must still track every failure so the throttle cannot hide the
    scale of the degradation.
    """
    reader = _Faulted()
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    for _ in range(25):
        reader._read_my_abilities()

    warnings = [
        r for r in caplog.records
        if r.name == _LOGGER_NAME and r.levelno >= logging.WARNING
    ]
    assert len(warnings) == 1, (
        "expected exactly one throttled WARNING for 25 consecutive failures, "
        f"got {len(warnings)}"
    )
    assert get_liveclient_subresource_failures()["/activeplayerabilities"] == 25


def test_enemy_runes_counts_once_per_failing_enemy(caplog):
    """`_read_enemy_runes` queries per enemy, so the counter is per query."""
    reader = _Faulted()
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    enemies = [
        {"championName": "Ahri", "riotIdGameName": "E1"},
        {"championName": "Zed", "riotIdGameName": "E2"},
        {"championName": "Lux", "riotIdGameName": "E3"},
    ]
    assert reader._read_enemy_runes(enemies) == {}
    assert reader.calls == 3
    assert get_liveclient_subresource_failures()["/playermainrunes"] == 3


def test_success_path_logs_nothing_and_leaves_counter_clean(caplog):
    """A healthy read must not warn and must not touch the counter."""

    class _Healthy(_NormalizerMixin):
        def _get(self, url):
            return {
                "keystone": {"id": 8005, "displayName": "Press the Attack"},
                "primaryRuneTree": {"displayName": "Precision"},
                "secondaryRuneTree": {"displayName": "Domination"},
            }

    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)
    reader = _Healthy()

    assert reader._read_my_runes() == "Press the Attack | Precision / Domination"
    assert get_liveclient_subresource_failures() == {}
    assert [r for r in caplog.records if r.name == _LOGGER_NAME] == []
