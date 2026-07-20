"""Silent-except triage BATCH 6 - observability regression for the TFT
heatmap-update failure in performance_tracker.save_tft_rating.

Spec: docs/specs/2026-07-19-silent-except-triage.md sections 2c + 4 (shape 1,
observability test). The handler that wraps
tft.placement_aggregator.update_heatmap stays deliberately broad (its callee
re-walks and re-parses the whole ratings dir, so the raise set is not closed by
inspection), but it used to log at DEBUG while both sibling save failures in
the same function log at WARNING. A permanently dead heatmap was therefore the
only invisible failure in save_tft_rating.

caplog is pinned at WARNING so a DEBUG record cannot satisfy the assertion -
this test fails while the failure is swallowed at DEBUG.
"""
import logging

import pytest

import performance_tracker


class _Boom(Exception):
    pass


def _seed_comp_state(root):
    """save_tft_rating reads data/comp_state.json and then uses `_sel`
    unconditionally at performance_tracker.py:294. When the file is absent the
    read fails, `_sel` is never bound, and the function raises
    UnboundLocalError - a pre-existing defect outside this batch's scope. Seed
    the file so these tests exercise the heatmap handler, not that bug.
    """
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "comp_state.json").write_text('{"selected": ""}', encoding="utf-8")


@pytest.fixture
def _tft_inputs():
    """Minimal tft_live / tft_coaching pair that reaches the heatmap call."""
    tft_live = {
        "last_round_result": "3rd",
        "stage_round": "5-2",
        "level": 8,
        "traits_active": ["Rebel 4"],
        "board_units": ["Jinx"],
        "augments": [],
        "unit_placement": "",
    }
    tft_coaching = {"variant": "standard", "alive_others": 2, "game_time_s": 1800}
    return tft_live, tft_coaching


def test_heatmap_update_failure_is_logged_at_warning(
    tmp_path, monkeypatch, caplog, _tft_inputs
):
    tft_live, tft_coaching = _tft_inputs
    _seed_comp_state(tmp_path)

    import tft.placement_aggregator as _pa

    def _explode():
        raise _Boom("heatmap dead")

    monkeypatch.setattr(_pa, "update_heatmap", _explode)
    # DS/match-DB persistence is irrelevant here and would touch real paths.
    monkeypatch.setattr(performance_tracker, "_get_db", lambda _sd: None)

    caplog.set_level(logging.WARNING, logger="rc.tracker")

    grade, _notes = performance_tracker.save_tft_rating(
        str(tmp_path), tft_live, tft_coaching
    )

    assert grade, "save_tft_rating should still succeed - the heatmap is best-effort"
    hits = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "Heatmap" in r.getMessage()
    ]
    assert hits, (
        "heatmap update failure must surface at WARNING or above; "
        f"records seen: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_heatmap_failure_does_not_break_the_rating_write(
    tmp_path, monkeypatch, _tft_inputs
):
    """The lift must not change control flow - the rating file is still written."""
    tft_live, tft_coaching = _tft_inputs
    _seed_comp_state(tmp_path)

    import tft.placement_aggregator as _pa

    monkeypatch.setattr(
        _pa, "update_heatmap", lambda: (_ for _ in ()).throw(_Boom("nope"))
    )
    monkeypatch.setattr(performance_tracker, "_get_db", lambda _sd: None)

    grade, notes = performance_tracker.save_tft_rating(
        str(tmp_path), tft_live, tft_coaching
    )

    assert grade
    assert notes
    assert performance_tracker._mode_file(str(tmp_path), "TFT").exists()
