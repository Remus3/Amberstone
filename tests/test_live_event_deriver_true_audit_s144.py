"""s144 true-audit (lane 8) of core/live_event_deriver.py.

The module doc promises that a missing / junk value "emits nothing for that
field". Two junk shapes broke that promise for the WHOLE tick instead, and a
third failure was silent:

  F1  an unhashable championName (list / dict) in ONE allPlayers row raised
      TypeError from the duplicate-name Counter. The hub catches it and drops
      the tick, so every other player's death / level / item event was lost.
  F2  an unhashable EventName in ONE events.Events entry raised TypeError from
      the ``in OBJECTIVE_EVENT_NAMES`` membership test, with the same effect.
  F3  the default completed-item catalog failing to load (or loading empty)
      turned item_completed off with nothing logged, so the event kind went
      dark with no trace. It now warns once per failure streak.

All fixtures are synthetic (no real Riot IDs).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import live_event_deriver as led  # noqa: E402

LEG = frozenset({"3031"})
_LOGGER = "core.live_event_deriver"


def _p(champ, team="ORDER", dead=False, level=3, items=(), name=None):
    return {
        "championName": champ,
        "summonerName": name or f"Synth{champ}#T1",
        "team": team,
        "isDead": dead,
        "respawnTimer": 0.0,
        "level": level,
        "items": [{"itemID": i, "slot": n} for n, i in enumerate(items)],
    }


def _snap(t, players, events=()):
    return {
        "activePlayer": {"summonerName": "SynthLux#T1"},
        "allPlayers": players,
        "gameData": {"gameMode": "CLASSIC", "gameTime": t},
        "events": {"Events": list(events)},
    }


def _kinds(evs):
    return [e["kind"] for e in evs]


@pytest.fixture(autouse=True)
def _fresh_warn_state():
    led._reset_catalog_warned_for_tests()
    yield
    led._reset_catalog_warned_for_tests()


# -- F1: a junk championName drops only its own row ------------------------

@pytest.mark.parametrize("junk", [["Lux"], {"n": "Lux"}])
def test_f1_unhashable_champion_name_drops_only_that_row(junk):
    a = _snap(100.0, [_p("Lux", level=3), _p(junk, team="CHAOS"),
                      _p("Zed", team="CHAOS")])
    b = _snap(101.0, [_p("Lux", level=4), _p(junk, team="CHAOS"),
                      _p("Zed", team="CHAOS", dead=True)])
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert sorted(_kinds(evs)) == ["death", "level_up"]
    assert {e["champion"] for e in evs} == {"Lux", "Zed"}


# -- F2: a junk EventName drops only its own entry --------------------------

@pytest.mark.parametrize("junk", [["DragonKill"], {"x": 1}])
def test_f2_unhashable_event_name_drops_only_that_entry(junk):
    good = {"EventID": 7, "EventName": "BaronKill", "EventTime": 100.5,
            "KillerName": "SynthLux#T1"}
    bad = {"EventID": 8, "EventName": junk, "EventTime": 100.6,
           "KillerName": "SynthLux#T1"}
    a = _snap(100.0, [_p("Lux"), _p("Zed", team="CHAOS")])
    b = _snap(101.0, [_p("Lux"), _p("Zed", team="CHAOS", dead=True)],
              events=[good, bad])
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert _kinds(evs) == ["objective_taken", "death"]
    assert evs[0]["event_id"] == 7 and evs[0]["objective"] == "baron"


# -- F3: a dark item_completed channel is logged, once per streak ----------

def _item_pair():
    a = _snap(100.0, [_p("Lux"), _p("Zed", team="CHAOS")])
    b = _snap(101.0, [_p("Lux", items=(3031,)), _p("Zed", team="CHAOS")])
    return a, b


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and r.levelno == logging.WARNING]


def test_f3_catalog_load_failure_warns_once_per_streak(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    def boom():
        raise RuntimeError("synthetic-catalog-failure")
    monkeypatch.setattr(led, "_load_completed_ids", boom)
    a, b = _item_pair()
    assert led.derive_events(a, b) == []
    assert led.derive_events(a, b) == []
    w = _warnings(caplog)
    assert len(w) == 1
    assert "synthetic-catalog-failure" in w[0].getMessage()

    # the streak ends on a good load (silently); a new failure warns again
    monkeypatch.setattr(led, "_load_completed_ids", lambda: LEG)
    assert _kinds(led.derive_events(a, b)) == ["item_completed"]
    assert len(_warnings(caplog)) == 1
    monkeypatch.setattr(led, "_load_completed_ids", boom)
    assert led.derive_events(a, b) == []
    assert len(_warnings(caplog)) == 2


def test_f3_empty_default_catalog_warns_once(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    monkeypatch.setattr(led, "_load_completed_ids", lambda: frozenset())
    a, b = _item_pair()
    assert led.derive_events(a, b) == []
    assert led.derive_events(a, b) == []
    w = _warnings(caplog)
    assert len(w) == 1
    assert "empty" in w[0].getMessage()


def test_f3_caller_supplied_empty_set_is_not_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    a, b = _item_pair()
    assert led.derive_events(a, b, completed_ids=()) == []
    assert _warnings(caplog) == []


def test_f3_no_inventory_gain_never_touches_the_catalog(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    def boom():
        raise AssertionError("catalog must stay lazy")
    monkeypatch.setattr(led, "_load_completed_ids", boom)
    a = _snap(100.0, [_p("Lux"), _p("Zed", team="CHAOS")])
    b = _snap(101.0, [_p("Lux", level=4), _p("Zed", team="CHAOS")])
    assert _kinds(led.derive_events(a, b)) == ["level_up"]
    assert _warnings(caplog) == []
