"""RM-855: the TFT state reader's round schedule follows the resolved set.

Before RM-855 `tft/tft_state_reader.py` `_parse` imported the Set 17 Realm of
the Gods tables from `tft/tft_pbe_data.py` (`CONSTANTS_SET = 17` :24,
`ROUND_EVENTS` :51, `PVE_ROUNDS` :64, `GOD_ROUNDS` :65, `BOON_ROUND` :66,
`TEMPO_MILESTONES` :69) for EVERY game (pre-fix :164-166), re-applied them on an OCR override
(pre-fix :188-189) and wrote `round_event` / `is_pve` / `is_god_round` /
`tempo_note` into the state (pre-fix :218-219). RM-840 made Set 18 the
default set (`tft/tft_set.py` `resolve_set` :140), so a Set 18 game carried
Set 17 god rounds, PvE rounds and tempo notes; the tempo note reaches the
coach prompt as "Milestone: ..." (`tft/tft_coach_engine.py` :330-331,
`tft/tft_pbe_engine.py` :118-119).

Set 18's schedule is NOT in the ingested data: the CommunityDragon extract
(`data/meta/tft_set18_cdragon.json`) names carousel rounds and a Stage 3-7 in
augment text but no round index for a carousel, PvE or augment round, and
the Set 18 meta is a skeleton. So Set 18 (and any set without a grounded
schedule) gets the set-neutral schedule, labelled `neutral_unverified`;
the live read-back is `docs/LIVE_GAME_GATED_SYNC.md` LT-01.

Every name used here, cited at the fix tree:
  tft/tft_state_reader.py  `_TIME_TO_ROUND` :21, `TftStateReader._parse`
      :143, the attributes `__init__` sets and `_parse` / `_ocr_data` read
      (`_my_name` / `_last_level` :52, `_confirmed_stage` /
      `_confirmed_round` :53, `_ocr_cache` :56, `_ocr_lock` :57),
      `_ocr_data` :86, the schedule call in `_parse` :205 and the state
      keys `round_event` / `is_pve` / `is_god_round` / `tempo_note` /
      `round_schedule` in its return (:214-216), and the RM-855 block:
      `SCHEDULE_GODS` :247, `SCHEDULE_NEUTRAL` :248, `RoundSchedule` :251
      (`label` field, `fields` :259), `round_schedule` :271.
  tft/tft_set.py  `ROOT` :38 (every resolver call with root=None reads it at
      call time), `FALLBACK_SET` :42, `ENV_PIN` :43, `clear_live_set` :110,
      `resolve_set` :140.
  tft/tft_prompt.py  `set_has_gods` :486 over `_gods` :268, which reads the
      `_patch_notes_*` "carousel" / "realm_of_gods" keys (`_ROUND_KEYS` :243,
      `_mechanic_record` :246) - the record the committed
      `data/meta/tft_set17_meta.json` `_patch_notes_17.1` carries.
  core/game_snapshot.py  `round_event` default "pvp" :569, `tempo_note`
      default "" :595 (the neutral values).

Each test writes its own data/meta under tmp_path and points `tft_set.ROOT`
at it, except the `_committed_` test, which reads the tracked tree on purpose.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tft import tft_pbe_data as pbe
from tft import tft_set
from tft.tft_state_reader import _TIME_TO_ROUND, TftStateReader

REPO_ROOT = Path(__file__).resolve().parent.parent

GODS = "set17_realm_of_gods"
NEUTRAL = "neutral_unverified"

# The one Realm of the Gods record left in the tracked Set 17 meta
# (data/meta/tft_set17_meta.json `_patch_notes_17.1`, kept by RM-846).
_GODS_NOTES = {
    "carousel": "REMOVED - replaced by Realm of the Gods",
    "realm_of_gods": "Stage X-4 = God offering. Stage 4-7 = God Boon armory.",
}


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    """No noted live set and no env pin leaks between tests."""
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("ascii") + b"\n")


@pytest.fixture
def two_sets(tmp_path, monkeypatch):
    """A data/meta shaped like the tracked one: a Set 17 skeleton meta with
    its Realm of the Gods patch-note record, a Set 18 skeleton meta and a Set
    18 CommunityDragon extract whose augment text names carousel rounds."""
    meta = tmp_path / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {
        "_set": 17, "_note": "SKELETON - UNVERIFIED",
        "all_traits": ["Anima", "Meeple"], "unit_costs": {"Jinx": 1},
        "comps": {}, "_patch_notes_17.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set18_meta.json", {
        "_set": 18, "_note": "SKELETON - UNVERIFIED", "comps": {},
    })
    _write(meta / "tft_set18_cdragon.json", {
        "_set": 18, "champions": ["Kobuko"], "all_traits": ["Fae"],
        "augments": [
            {"name": "Hard Bargain",
             "desc": "Gain @Gold@ gold each carousel round."},
            {"name": "Infinity Protection",
             "desc": "On Stage 3-7, gain an Infinity Force."},
        ],
    })
    monkeypatch.setattr(tft_set, "ROOT", tmp_path)
    return tmp_path


def _reader(ocr=None) -> TftStateReader:
    rdr = object.__new__(TftStateReader)  # skip __init__ (OCR thread)
    rdr._my_name = ""
    rdr._last_level = 1
    rdr._confirmed_stage = 1
    rdr._confirmed_round = 1
    rdr._ocr_cache = dict(ocr or {})
    rdr._ocr_lock = threading.Lock()
    return rdr


def _raw(game_time: float) -> dict:
    return {
        "activePlayer": {"summonerName": "Me", "level": 5},
        "allPlayers": [{"summonerName": "Me", "items": [], "scores": {}}],
        "gameData": {"gameMode": "TFT", "gameTime": game_time, "mapNumber": 22},
    }


def _at(stage: int, rnd: int) -> float:
    """A game time the fallback time table maps to stage-rnd."""
    for ms, st, rn in _TIME_TO_ROUND:
        if (st, rn) == (stage, rnd):
            return ms + 1.0
    raise AssertionError(f"{stage}-{rnd} not in _TIME_TO_ROUND")


def test_set17_keeps_the_realm_of_the_gods_schedule(two_sets, monkeypatch):
    """Set 17 resolves (operator pin) and its meta records Realm of the Gods:
    the tft_pbe_data schedule is still served, from the time table and from
    an accepted OCR override, and the state names which schedule it used."""
    monkeypatch.setenv(tft_set.ENV_PIN, "17")
    assert tft_set.resolve_set() == 17
    rdr = _reader()

    s = rdr._parse(_raw(_at(2, 4)))
    assert s["stage_round"] == "2-4"
    assert s.get("round_schedule") == GODS
    assert s["is_god_round"] is True
    assert s["round_event"] == pbe.ROUND_EVENTS[(2, 4)]
    assert s["tempo_note"] == pbe.TEMPO_MILESTONES["2-4"]

    s = rdr._parse(_raw(_at(2, 5)))
    assert s["is_pve"] is True
    assert s["round_event"] == pbe.ROUND_EVENTS[(2, 5)]

    s = rdr._parse(_raw(_at(4, 7)))
    assert s["round_event"] == pbe.ROUND_EVENTS[pbe.BOON_ROUND]

    # OCR override (pre-fix :186-189): the table says 3-5, OCR says 3-4.
    s = _reader({"stage_round": "3-4"})._parse(_raw(_at(3, 5)))
    assert s["stage_round"] == "3-4"
    assert s["is_god_round"] is True
    assert s.get("round_schedule") == GODS


def test_set18_gets_the_neutral_schedule_and_no_set17_label(two_sets):
    """Set 18 resolves by default (newest ingested). Its data grounds no
    round index, so no round carries a Set 17 event, PvE, god or tempo label,
    on the time-table path or on an OCR override."""
    assert tft_set.resolve_set() == 18
    set17_events = set(pbe.ROUND_EVENTS.values())
    set17_tempo = set(pbe.TEMPO_MILESTONES.values())
    rdr = _reader()
    for ms, st, rn in _TIME_TO_ROUND:
        s = rdr._parse(_raw(ms + 1.0))
        assert s["stage_round"] == f"{st}-{rn}"
        assert s["round_event"] not in set17_events, s["stage_round"]
        assert s["round_event"] == "pvp", s["stage_round"]
        assert s["is_god_round"] is False, s["stage_round"]
        assert s["is_pve"] is False, s["stage_round"]
        assert s["tempo_note"] not in set17_tempo, s["stage_round"]
        assert s["tempo_note"] == "", s["stage_round"]
        assert s.get("round_schedule") == NEUTRAL, s["stage_round"]

    # OCR override (pre-fix :186-189): the table says 4-6, OCR says 4-7.
    s = _reader({"stage_round": "4-7"})._parse(_raw(_at(4, 6)))
    assert s["stage_round"] == "4-7"
    assert s["round_event"] == "pvp"
    assert s["is_god_round"] is False
    assert s["tempo_note"] == ""
    assert s.get("round_schedule") == NEUTRAL


def test_unknown_set_gets_no_god_rounds(tmp_path, monkeypatch):
    """A set with no grounded schedule gets no god rounds: (a) an ingested
    Set 19 whose meta even records Realm of the Gods - the Set 17 tables are
    never borrowed for another set; (b) nothing ingested at all, where the
    resolver falls back to FALLBACK_SET with no data on disk."""
    meta = tmp_path / "s19" / "data" / "meta"
    _write(meta / "tft_set19_meta.json", {
        "_set": 19, "_note": "SKELETON - UNVERIFIED", "comps": {},
        "_patch_notes_19.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set19_cdragon.json", {"_set": 19, "champions": ["X"]})
    monkeypatch.setattr(tft_set, "ROOT", tmp_path / "s19")
    assert tft_set.resolve_set() == 19
    s = _reader()._parse(_raw(_at(2, 4)))
    assert s["is_god_round"] is False
    assert s["round_event"] == "pvp"
    assert s["tempo_note"] == ""
    assert s.get("round_schedule") == NEUTRAL

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(tft_set, "ROOT", empty)
    assert tft_set.resolve_set() == tft_set.FALLBACK_SET
    for stage, rnd in sorted(pbe.GOD_ROUNDS) + [pbe.BOON_ROUND]:
        s = _reader()._parse(_raw(_at(stage, rnd)))
        assert s["is_god_round"] is False, (stage, rnd)
        assert s["round_event"] == "pvp", (stage, rnd)
        assert s.get("round_schedule") == NEUTRAL


def test_committed_tree_selects_gods_for_17_only():
    """The tracked data/meta: Set 17's meta records Realm of the Gods, Set
    18's does not, so only Set 17 gets the god schedule."""
    from tft.tft_state_reader import round_schedule
    assert round_schedule(17, root=REPO_ROOT).label == GODS
    assert round_schedule(18, root=REPO_ROOT).label == NEUTRAL
