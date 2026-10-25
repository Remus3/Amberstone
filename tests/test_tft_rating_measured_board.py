"""S134-Q (research filing RM-889, half 1): the saved TFT rating records the
board that was PLAYED, never the selected guide comp's target board.

`performance_tracker.save_tft_rating` reads `data/comp_state.json`; when it
names a selected comp that the resolved set's meta carries, the enrichment
block used to OVERWRITE the measured `board_units` / `traits_active` /
`augments` with the comp's `lv8` / `lv7` / `core_units`, `[selected] +
emblems` and `augments_best[:3]`. Those values reached the rating file and
the match_history.db row, whose `get_best_comps` aggregates
`GROUP_CONCAT(DISTINCT tft_traits)`, so the stored history recorded the guide,
not the game. Set 18's `comps` is `{}` today, so the overwrite is inert on
the live box only until the meta is filled.

These tests diff the CONSUMER artifacts (the rating file and the dict handed
to `save_match`), not only the function's locals. The selected comp NAME is
still carried as `comp` (`tests/test_silent_except_merge_hardening.py`
pins that), and the comp's target board is kept under its own labelled key,
`tft_comp_target`, so the guide stays visible without posing as measurement.
"""
from __future__ import annotations

import json

import pytest

import performance_tracker as pt
from tft import tft_set

_GUIDE = {
    "lv8": ["Guide A", "Guide B", "Guide C"],
    "lv7": ["Guide A", "Guide B"],
    "core_units": ["Guide A"],
    "emblem_value": ["Guide Trait"],
    "augments_best": ["Guide Aug 1", "Guide Aug 2", "Guide Aug 3", "Guide Aug 4"],
}
_COACH = {"stage": 4, "game_time_s": 1800, "alive_others": 2}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.delenv("RC_ACCOUNT_ID", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (data / "comp_state.json").write_text(
        json.dumps({"selected": "Test Comp"}), encoding="utf-8")
    meta = data / "meta.json"
    meta.write_text(json.dumps({"comps": {"Test Comp": _GUIDE}}), encoding="utf-8")
    monkeypatch.setattr(tft_set, "meta_path", lambda *a, **k: meta)
    rows = []

    class _Db:
        def save_match(self, row):
            rows.append(dict(row))

    monkeypatch.setattr(pt, "_get_db", lambda sd: _Db())
    monkeypatch.setattr("tft.placement_aggregator.update_heatmap", lambda: None)

    def rate(live):
        grade, _notes = pt.save_tft_rating(str(tmp_path), live, dict(_COACH))
        assert grade, "fixture produced no rating - nothing under test"
        saved = json.loads((data / "ratings" / "last_tft.json").read_text(
            encoding="utf-8"))
        assert len(rows) == 1, rows
        return saved, rows[0]

    return rate


def _live(**over):
    live = {"level": 8, "stage_round": "4-2", "last_round_result": "3rd",
            "board_units": ["Jinx 2-star", "Vi"], "traits_active": ["Rebel 3"],
            "augments": ["Measured Aug"]}
    live.update(over)
    return live


def test_measured_board_survives_a_selected_comp_in_the_meta(rig):
    saved, row = rig(_live())
    for blob in (saved, row):
        assert blob["tft_units"] == ["Jinx 2-star", "Vi"]
        assert blob["tft_traits"] == ["Rebel 3"]
        assert blob["tft_augments"] == ["Measured Aug"]
        assert blob["tft_comp"] == "Test Comp"
    assert saved["tft_core_units"] == ["Jinx", "Vi"]


def test_an_empty_measured_board_stays_empty_not_guide_filled(rig):
    """The overwrite also back-filled an EMPTY reading (an OCR miss) with the
    guide, which is the same fabrication with a better excuse."""
    saved, row = rig(_live(board_units=[], traits_active=[], augments=[]))
    for blob in (saved, row):
        assert blob["tft_units"] == []
        assert blob["tft_traits"] == []
        assert blob["tft_augments"] == []
    assert saved["tft_core_units"] == []


def test_the_guide_target_is_kept_under_its_own_label(rig):
    saved, row = rig(_live())
    assert saved["tft_comp_target"] == {
        "units": ["Guide A", "Guide B", "Guide C"],
        "traits": ["Test Comp", "Guide Trait Emblem"],
        "augments": ["Guide Aug 1", "Guide Aug 2", "Guide Aug 3"],
    }
    # The DB row has no column for it; the measured columns must not carry it.
    assert "Guide A" not in json.dumps(row)


def test_no_target_key_without_a_meta_entry(rig, monkeypatch, tmp_path):
    (tmp_path / "data" / "comp_state.json").write_text(
        json.dumps({"selected": "Not In Meta"}), encoding="utf-8")
    saved, _row = rig(_live())
    assert "tft_comp_target" not in saved
    assert saved["tft_comp"] == "Not In Meta"
