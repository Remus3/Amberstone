"""Merge-time hardening for the silent-except batch program.

Two defects found by CROSS-READING the batch results rather than inside any
single batch's scope. Both follow the program's own thesis: a swallowed error
converted into a worse failure somewhere the swallow did not look.

1. `agents/supervisor.py` - BATCH 2's A3 fix (correctly) makes a rating-locator
   bug propagate out of `_file_post_game_summary` instead of silently stripping
   fields. But the sole caller at `:658` runs it BEFORE the auto-analyze
   scheduling block at `:659-668`, with no try between them. So a locator bug
   would also stop auto-analyze from ever being scheduled at game end - one bug
   disabling an unrelated feature. Visibility is already preserved by the outer
   guard in `agents/agent2_backend/file_ingest.py:200-202`, which logs the raise
   at WARNING, so decoupling the two loses no observability.

2. `performance_tracker.py` - `_sel` is bound at `:273` INSIDE the try that
   reads `data/comp_state.json`. The handler logs at debug and falls through to
   `comp=_sel if _sel else ...`, which raises `UnboundLocalError` when the file
   is absent or corrupt. `data/comp_state.json` is a gitignored `data/` artifact,
   so a clean checkout hits this. The caller is `app/_game_lifecycle.py:168` at
   TFT game end (a frozen file), so the crash lands in the lifecycle handler and
   the TFT rating is lost.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

# `last_round_result` drives _parse_tft_placement; without a parseable placement
# save_tft_rating returns early at :259 and never reaches the defect under test.
_TFT_LIVE = {
    "level": 8,
    "traits_active": [],
    "board_units": [],
    "augments": [],
    "last_round_result": "4th",
}
# `stage` must be numeric: calculate_tft_rating does `0 < stage <= 4`
# (performance_tracker.py:244), so a "4-2" string TypeErrors before the
# defect under test is reached.
_TFT_COACHING = {"stage": 4, "game_time_s": 1800, "alive_others": 7}


# ---------------------------------------------------------------------------
# 1. supervisor: a locator bug must not also disable auto-analyze scheduling
# ---------------------------------------------------------------------------

def test_post_game_summary_failure_does_not_block_auto_analyze():
    """A raise out of _file_post_game_summary must not skip the auto-analyze
    scheduling that follows it. RED before the hardening: the exception escapes
    _on_mode_transition at :658 and :659-668 never runs."""
    from agents.supervisor import Supervisor

    sup = Supervisor.__new__(Supervisor)
    scheduled = {"n": 0}

    def _boom(prev, new):
        raise RuntimeError("rating locator bug")

    sup._warm_agent7 = None  # skip the game-start prime branch at :617
    sup._file_post_game_summary = _boom
    sup._schedule_auto_analyze = lambda: scheduled.__setitem__("n", scheduled["n"] + 1)
    sup._cancel_pending_auto_analyze = lambda reason: None

    class _Loop:
        def call_soon_threadsafe(self, fn):
            fn()

    with mock.patch("agents.supervisor.asyncio") as _aio:
        _aio.get_event_loop.return_value.is_running.return_value = True
        _aio.get_running_loop.return_value = _Loop()
        # The locator bug must still surface (it is a real bug, not to be hidden)
        # but it must not take auto-analyze down with it.
        sup._on_mode_transition("game", "client")

    assert scheduled["n"] == 1, (
        "auto-analyze was never scheduled - a post-game summary failure "
        "silently disabled an unrelated feature"
    )


# ---------------------------------------------------------------------------
# 2. performance_tracker: missing comp_state.json must not raise UnboundLocalError
# ---------------------------------------------------------------------------

def test_save_tft_rating_survives_missing_comp_state(tmp_path):
    """With data/comp_state.json absent, the enrichment swallow must leave
    `_sel` defined. RED before the hardening: UnboundLocalError at the
    `comp=_sel if _sel else ...` line."""
    import performance_tracker as pt

    (tmp_path / "data").mkdir()
    assert not (tmp_path / "data" / "comp_state.json").exists()

    try:
        pt.save_tft_rating(str(tmp_path), _TFT_LIVE, _TFT_COACHING)
    except UnboundLocalError as exc:
        pytest.fail(
            "missing comp_state.json raised UnboundLocalError instead of "
            f"degrading: {exc}"
        )


def test_save_tft_rating_survives_corrupt_comp_state(tmp_path):
    """Same defect via a corrupt (not absent) file - json.loads raises inside
    the same try, so `_sel` is equally unbound."""
    import performance_tracker as pt

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "comp_state.json").write_text("{not json", encoding="utf-8")

    try:
        pt.save_tft_rating(str(tmp_path), _TFT_LIVE, _TFT_COACHING)
    except UnboundLocalError as exc:
        pytest.fail(
            f"corrupt comp_state.json raised UnboundLocalError instead of degrading: {exc}"
        )


def test_comp_state_enrichment_still_applies_when_present(tmp_path):
    """Guard the hardening did not break the happy path: a valid comp_state
    with a selected comp must still be picked up as `comp`."""
    import performance_tracker as pt

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "comp_state.json").write_text(
        json.dumps({"selected": "Test Comp"}), encoding="utf-8"
    )

    grade, _notes = pt.save_tft_rating(str(tmp_path), _TFT_LIVE, _TFT_COACHING)
    assert grade, "happy path produced no grade - the enrichment path regressed"
    rated = sorted((tmp_path / "data").rglob("*.json"))
    blob = "\n".join(Path(p).read_text(encoding="utf-8") for p in rated)
    assert "Test Comp" in blob, "selected comp was not carried into the rating"
