"""s144 true-audit (RM-1037): core/live_event_hub.py hardening.

Each test pins one audit finding:

  F1  a derive_events failure was logged at DEBUG on every tick, so a deriver
      regression turned /api/events into heartbeats only with no trace in the
      log; it now warns once per failure streak.
  F2  a listener failure and an install failure were DEBUG-only too (and the
      route ignores ensure_installed's False), so an unfed hub was silent.
  F3  since() handed out the ring's own stored dicts; one consumer mutating
      an event changed what every other subscriber read next.
  F4  a raising completed_ids provider raised out of observe(), and a non-dict
      item from the deriver raised after a partial append, skipping the
      waiter wake-up.
  F5  since() with a NaN cursor answered (no gap, no events) forever, a
      silent starve; a non-integer cursor is now refused with TypeError.

Synthetic fixtures only.
"""
from __future__ import annotations

import logging
import math
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import live_event_hub as hub_mod  # noqa: E402

LOGGER = "rc.live_event_hub"


def _snap(t, zed_dead=False):
    return {
        "activePlayer": {"summonerName": "SynthLux#T1"},
        "allPlayers": [
            {"championName": "Lux", "summonerName": "SynthLux#T1", "team": "ORDER",
             "isDead": False, "level": 3, "items": []},
            {"championName": "Zed", "summonerName": "SynthZed#T2", "team": "CHAOS",
             "isDead": zed_dead, "level": 4, "items": []},
        ],
        "gameData": {"gameMode": "CLASSIC", "gameTime": t},
        "events": {"Events": []},
    }


@pytest.fixture(autouse=True)
def _fresh_module_state():
    hub_mod._reset_for_tests()
    yield
    hub_mod._reset_for_tests()


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == LOGGER and r.levelno >= logging.WARNING]


# -- F1: deriver failure warns once per streak ---------------------------------

def test_f1_derive_failure_warns_once_per_streak(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    h = hub_mod.LiveEventHub(id_seed=0)
    h.observe(_snap(100.0))
    with mock.patch.object(hub_mod, "derive_events", side_effect=ValueError("boom-1")):
        for i in range(4):
            assert h.observe(_snap(101.0 + i)) == []
    warns = _warnings(caplog)
    assert len(warns) == 1, [r.getMessage() for r in warns]
    assert "boom-1" in warns[0].getMessage()
    assert "ValueError" in warns[0].getMessage()


def test_f1_success_ends_the_streak_so_the_next_failure_warns_again(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    h = hub_mod.LiveEventHub(id_seed=0)
    h.observe(_snap(100.0))
    with mock.patch.object(hub_mod, "derive_events", side_effect=ValueError("a")):
        h.observe(_snap(101.0))
        h.observe(_snap(102.0))
    h.observe(_snap(103.0))  # real deriver: success
    with mock.patch.object(hub_mod, "derive_events", side_effect=ValueError("b")):
        h.observe(_snap(104.0))
    assert len(_warnings(caplog)) == 2


# -- F2: listener and install failures are visible -----------------------------

def test_f2_listener_failure_warns_once_per_streak(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    class _Broken:
        def observe(self, data):
            raise RuntimeError("hub-broken")

    with mock.patch.object(hub_mod, "_HUB", _Broken()):
        for _ in range(3):
            hub_mod.on_liveclient_snapshot(mock.Mock(data=_snap(1.0)))  # never raises
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "hub-broken" in warns[0].getMessage()


def test_f2_install_failure_warns_once_and_keeps_retrying(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    from core import liveclient_cache
    with mock.patch.object(liveclient_cache, "add_listener",
                           side_effect=RuntimeError("no-cache")) as add:
        assert hub_mod.ensure_installed() is False
        assert hub_mod.ensure_installed() is False
        assert add.call_count == 2
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "no-cache" in warns[0].getMessage()
    with mock.patch.object(liveclient_cache, "add_listener") as add_ok:
        assert hub_mod.ensure_installed() is True
        add_ok.assert_called_once_with(hub_mod.on_liveclient_snapshot)


# -- F3: since() never hands out the ring's own dicts ---------------------------

def test_f3_ring_since_returns_copies():
    r = hub_mod.EventRing(maxlen=8, id_seed=10)
    r.append({"kind": "x", "n": 1})
    _, evs = r.since(10)
    evs[0]["id"] = 999
    evs[0].pop("kind")
    _, again = r.since(10)
    assert again == [{"kind": "x", "n": 1, "id": 11}]


def test_f3_hub_since_returns_copies():
    h = hub_mod.LiveEventHub(id_seed=0, completed_ids=lambda: frozenset())
    h.observe(_snap(100.0))
    h.observe(_snap(101.0, zed_dead=True))
    _, evs = h.since(0)
    assert evs, "fixture must emit an event"
    before = dict(evs[0])
    evs[0]["kind"] = "tampered"
    _, again = h.since(0)
    assert again[0] == before


# -- F4: observe is fail-soft end to end ------------------------------------------

def test_f4_raising_completed_ids_provider_never_raises_out_of_observe(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    def _bad():
        raise OSError("ids-unreadable")

    h = hub_mod.LiveEventHub(id_seed=0, completed_ids=_bad)
    assert h.observe(_snap(100.0)) == []
    assert h.observe(_snap(101.0, zed_dead=True)) == []
    assert h.head == 0
    assert len(_warnings(caplog)) == 1


def test_f4_non_dict_items_from_the_deriver_are_skipped_and_waiters_wake():
    h = hub_mod.LiveEventHub(id_seed=0)
    h.observe(_snap(100.0))
    woke = []
    t = threading.Thread(target=lambda: woke.append(h.wait(0, 5.0)), daemon=True)
    t.start()
    junk = [{"kind": "a"}, "junk", None, 7, {"kind": "b"}]
    with mock.patch.object(hub_mod, "derive_events", return_value=junk):
        out = h.observe(_snap(101.0))
    t.join(5.0)
    assert [e["kind"] for e in out] == ["a", "b"]
    assert [e["id"] for e in out] == [1, 2]
    assert h.head == 2
    assert woke == [True]


def test_f4_non_list_deriver_result_is_a_failure_not_a_crash(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    h = hub_mod.LiveEventHub(id_seed=0)
    h.observe(_snap(100.0))
    with mock.patch.object(hub_mod, "derive_events", return_value=None):
        assert h.observe(_snap(101.0)) == []
    assert h.head == 0
    assert len(_warnings(caplog)) == 1


# -- F5: a non-integer cursor is refused ----------------------------------------

@pytest.mark.parametrize("bad", [math.nan, 1.5, 3.0, "5", None, True])
def test_f5_since_refuses_a_non_integer_cursor(bad):
    r = hub_mod.EventRing(maxlen=4, id_seed=0)
    r.append({"kind": "x"})
    with pytest.raises(TypeError):
        r.since(bad)
    h = hub_mod.LiveEventHub(id_seed=0)
    with pytest.raises(TypeError):
        h.since(bad)


def test_f5_integer_cursor_still_works():
    r = hub_mod.EventRing(maxlen=4, id_seed=0)
    r.append({"kind": "x"})
    gap, evs = r.since(0)
    assert gap is None and [e["id"] for e in evs] == [1]
