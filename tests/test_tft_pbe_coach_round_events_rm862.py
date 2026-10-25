"""RM-862: the TFT PBE coach injects round events from the resolved set's
round schedule (RM-855), not from the Set 17 tables for any set whose meta
records gods.

Before RM-862:
  coaches/tft_pbe_coach.py `Coach._inject_pbe_events` (pre-fix :157) gated
      on `tft_prompt.set_has_gods()` (pre-fix :166, RM-845: ANY set whose
      meta records Realm of the Gods), then imported `ROUND_EVENTS`,
      `PVE_ROUNDS`, `GOD_ROUNDS`, `BOON_ROUND` and `TEMPO_MILESTONES` from
      `tft/tft_pbe_data.py` (pre-fix :168) and wrote `round_event` /
      `is_pve` / `is_carousel` / `is_god_round` / `is_boon_round` /
      `tempo_note` (pre-fix :172-177). So a Set 18 or a later ingested set
      whose meta records Realm of the Gods got the Set 17 rounds.

After RM-862 it asks `tft/tft_state_reader.py` `round_schedule()` (RM-855,
the RM-858 sibling pattern), which serves the Set 17 Realm of the Gods
tables only for Set 17 with that mechanic and the neutral schedule for every
other set; on the neutral schedule the state reader's own round fields stand.

The Set 17 test fails first on its ROUTING assertion (pre-fix the coach
never called `round_schedule`); its exact-state assertions pin Set 17
behaviour as unchanged. The Set 18 and unknown-set tests fail first on the
Set 17 fields the pre-fix coach wrote for a meta that records gods.

Every name used here, cited at the fix tree:
  coaches/tft_pbe_coach.py  `Coach` :59, `Coach._inject_pbe_events` :158
      (a staticmethod, so it is called on the class with no instance; it
      calls `tft_state_reader.round_schedule` at call time, so the spy
      below sees it) and the six keys it writes on the gods schedule
      (:183-188).
  tft/tft_state_reader.py  `_TIME_TO_ROUND` :21, `SCHEDULE_GODS` :247,
      `SCHEDULE_NEUTRAL` :248, `RoundSchedule` :251 (`label` field),
      `round_schedule` :271.
  tft/tft_set.py  `ROOT` :38, `FALLBACK_SET` :42, `ENV_PIN` :43,
      `clear_live_set` :110, `resolve_set` :140.
  tft/tft_prompt.py  `set_has_gods` :486 (the pre-fix gate, asserted True
      on the gods-record fixtures so they exercise it).
  tft/tft_pbe_data.py  `ROUND_EVENTS` :51, `PVE_ROUNDS` :64, `GOD_ROUNDS`
      :65, `BOON_ROUND` :66, `TEMPO_MILESTONES` :69.

Each test writes its own data/meta under tmp_path and points `tft_set.ROOT`
at it (the RM-855 / RM-858 fixture shape,
tests/test_tft_round_labels_rm858.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from coaches import tft_pbe_coach as pbe_coach
from tft import tft_pbe_data as pbe
from tft import tft_prompt
from tft import tft_set
from tft import tft_state_reader
from tft.tft_state_reader import _TIME_TO_ROUND

GODS = tft_state_reader.SCHEDULE_GODS
NEUTRAL = tft_state_reader.SCHEDULE_NEUTRAL
EVERY_ROUND = sorted({(st, rn) for _, st, rn in _TIME_TO_ROUND}
                     | set(pbe.GOD_ROUNDS) | set(pbe.PVE_ROUNDS)
                     | set(pbe.ROUND_EVENTS) | {pbe.BOON_ROUND})

# The one Realm of the Gods record in the tracked Set 17 meta
# (data/meta/tft_set17_meta.json `_patch_notes_17.1`).
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


@pytest.fixture
def calls(monkeypatch):
    """Wrap the real round_schedule and record every call."""
    seen: list = []
    real = tft_state_reader.round_schedule

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(tft_state_reader, "round_schedule", spy)
    return seen


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj, indent=1).encode("ascii") + b"\n")


def _sets(root: Path, monkeypatch, *, set18_gods: bool) -> None:
    """A Set 17 skeleton meta with its Realm of the Gods record and a Set 18
    meta + CommunityDragon extract; the Set 18 meta records Realm of the Gods
    only when set18_gods (the shape the pre-fix gate let through)."""
    meta = root / "data" / "meta"
    _write(meta / "tft_set17_meta.json", {
        "_set": 17, "_note": "SKELETON - UNVERIFIED",
        "all_traits": ["Anima", "Meeple"], "unit_costs": {"Jinx": 1},
        "comps": {}, "_patch_notes_17.1": dict(_GODS_NOTES),
    })
    s18 = {"_set": 18, "_note": "SKELETON - UNVERIFIED", "comps": {}}
    if set18_gods:
        s18["_patch_notes_18.1"] = dict(_GODS_NOTES)
    _write(meta / "tft_set18_meta.json", s18)
    _write(meta / "tft_set18_cdragon.json", {
        "_set": 18, "champions": ["Kobuko"], "all_traits": ["Fae"],
    })
    monkeypatch.setattr(tft_set, "ROOT", root)


def _reader_state(stage: int, rnd: int, label: str) -> dict:
    """The round fields the state reader writes (tft/tft_state_reader.py
    _parse) for a round on a schedule with no event, PvE, god or tempo label;
    label is the reader's round_schedule value."""
    return {"stage": stage, "round": rnd, "stage_round": f"{stage}-{rnd}",
            "round_event": "pvp", "is_pve": False, "is_carousel": False,
            "is_god_round": False, "tempo_note": "", "round_schedule": label}


def _inject(state: dict) -> dict:
    pbe_coach.Coach._inject_pbe_events(state)
    return state


def _set17_expected(state: dict) -> dict:
    """The pre-fix Set 17 injection, re-derived from tft/tft_pbe_data.py."""
    rk = (state.get("stage", 1), state.get("round", 1))
    sr = state.get("stage_round", f"{rk[0]}-{rk[1]}")
    out = dict(state)
    out.update({
        "round_event": pbe.ROUND_EVENTS.get(rk, "pvp"),
        "is_pve": rk in pbe.PVE_ROUNDS,
        "is_carousel": False,
        "is_god_round": rk in pbe.GOD_ROUNDS,
        "is_boon_round": rk == pbe.BOON_ROUND,
        "tempo_note": pbe.TEMPO_MILESTONES.get(sr, ""),
    })
    return out


def _assert_no_set17_fields(state_in: dict, shape: str) -> None:
    before = dict(state_in)
    after = _inject(state_in)
    rk = (before["stage"], before["round"])
    assert after == before, (shape, rk, after)
    assert "is_boon_round" not in after, (shape, rk)


def test_pbe_coach_set17_events_unchanged_and_from_round_schedule(tmp_path, monkeypatch, calls):
    _sets(tmp_path, monkeypatch, set18_gods=False)
    monkeypatch.setenv(tft_set.ENV_PIN, "17")
    assert tft_set.resolve_set() == 17
    for stage, rnd in EVERY_ROUND:
        state = _reader_state(stage, rnd, GODS)
        expected = _set17_expected(state)
        assert _inject(state) == expected, (stage, rnd)
    # Every Set 17 table entry is reached, so the comparison above is not
    # vacuous on any of them.
    seen = {(s, r) for s, r in EVERY_ROUND}
    assert set(pbe.GOD_ROUNDS) <= seen and set(pbe.PVE_ROUNDS) <= seen
    assert pbe.BOON_ROUND in seen and set(pbe.ROUND_EVENTS) <= seen
    assert _inject(_reader_state(*pbe.BOON_ROUND, GODS))["is_boon_round"] is True
    assert _inject(_reader_state(2, 4, GODS))["round_event"] == "realm_of_gods"
    assert _inject(_reader_state(2, 4, GODS))["tempo_note"] == pbe.TEMPO_MILESTONES["2-4"]
    # The state defaults (no stage / round / stage_round) are unchanged too.
    assert _inject({}) == _set17_expected({})
    assert calls, "the PBE coach never asked round_schedule() for its round events"


def test_pbe_coach_set18_gets_no_set17_events(tmp_path, monkeypatch):
    for set18_gods in (False, True):
        root = tmp_path / f"gods-{set18_gods}"
        _sets(root, monkeypatch, set18_gods=set18_gods)
        assert tft_set.resolve_set() == 18
        # The gods-record shape is the one the pre-fix gate let through.
        assert tft_prompt.set_has_gods() is set18_gods
        assert tft_state_reader.round_schedule().label == NEUTRAL
        for stage, rnd in EVERY_ROUND:
            _assert_no_set17_fields(_reader_state(stage, rnd, NEUTRAL),
                                    f"set18 gods={set18_gods}")


def test_pbe_coach_unknown_set_with_gods_meta_gets_no_set17_events(tmp_path, monkeypatch):
    # An ingested Set 19 whose meta records Realm of the Gods.
    s19 = tmp_path / "s19"
    meta = s19 / "data" / "meta"
    _write(meta / "tft_set19_meta.json", {
        "_set": 19, "_note": "SKELETON - UNVERIFIED", "comps": {},
        "_patch_notes_19.1": dict(_GODS_NOTES),
    })
    _write(meta / "tft_set19_cdragon.json", {"_set": 19, "champions": ["X"]})
    monkeypatch.setattr(tft_set, "ROOT", s19)
    assert tft_set.resolve_set() == 19
    assert tft_prompt.set_has_gods() is True
    assert tft_state_reader.round_schedule().label == NEUTRAL
    for stage, rnd in EVERY_ROUND:
        _assert_no_set17_fields(_reader_state(stage, rnd, NEUTRAL), "set19 gods")
    # Nothing ingested at all: the resolver falls back to FALLBACK_SET with no
    # data, so there is no Realm of the Gods record and no schedule.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(tft_set, "ROOT", empty)
    assert tft_set.resolve_set() == tft_set.FALLBACK_SET
    for stage, rnd in EVERY_ROUND:
        _assert_no_set17_fields(_reader_state(stage, rnd, NEUTRAL), "nothing-ingested")
