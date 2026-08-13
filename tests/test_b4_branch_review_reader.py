"""B4-e (RM-189) backend: read one match's branch series back out of the
shadow corpus.

B4 keeps in-game capture silent and moves the coaching to a post-game review
(docs/OVERLAY_COMPLIANCE_PLAN.md section 6c). B4-d gave every record a
`game_run_id`; this is the reader that turns a run id back into "here is the
branch you were at, and here is what each path was worth".

Three constraints shape it, all measured rather than assumed:

  1. The corpus is 68 MB and growing, and this serves an HTTP route. It reads a
     bounded TAIL, never the whole file, and says so when the window may have
     clipped the series rather than quietly returning a short one.
  2. Most of that 68 MB predates B4-d and carries NO game_run_id. Those rows
     cannot be grouped and must be skipped and COUNTED, not guessed at.
  3. RM-158: an Arena record whose precompute column is really SR content is
     tagged `precompute_source`. The reader must drop that column and keep the
     native observation - the fence in ROADMAP RM-158 is explicit that purging
     the whole row is wrong.
"""
from __future__ import annotations

import json

from core import branch_review


def _row(**kw):
    base = {
        "ts": "2026-08-12T20:00:00+00:00",
        "mode": "aram", "my_champion": "Annie", "enemy": "Caitlyn",
        "band": "L6", "mana_state": "full", "cd_state": "all_up",
        "covered": True, "game_time_s": 300.0, "level": 6, "item_count": 2,
        "engine_version": "1.277.0",
        "choices": [{"key": "A", "label": "Force a short trade",
                     "expected_outcome": "net swing +0.25", "confidence": "high"},
                    {"key": "B", "label": "Back off", "confidence": "low"}],
        "native_action": "POKE PHASE",
        "native_choices": [], "cv_override": None, "verdict_blocks": None,
        "game_id": None, "game_run_id": "local-aram-2026-08-12T20:00:00+00:00",
    }
    base.update(kw)
    return base


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


RUN_A = "local-aram-2026-08-12T20:00:00+00:00"
RUN_B = "7412995551"


def test_returns_the_series_for_one_run(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [
        _row(game_time_s=120.0, level=3),
        _row(game_time_s=300.0, level=6),
        _row(game_time_s=600.0, level=11, game_run_id=RUN_B),
    ])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["game_run_id"] == RUN_A
    assert len(out["branches"]) == 2
    assert [b["game_time_s"] for b in out["branches"]] == [120.0, 300.0]


def test_defaults_to_the_most_recent_run(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=120.0), _row(game_time_s=600.0, game_run_id=RUN_B)])
    out = branch_review.load_branch_series(path=p)
    assert out["game_run_id"] == RUN_B


def test_branches_are_ordered_by_game_time(tmp_path):
    """The jsonl is append-ordered, but a reader must not depend on that -
    a mid-game RC restart can interleave."""
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=600.0, level=11),
               _row(game_time_s=120.0, level=3),
               _row(game_time_s=300.0, level=6)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert [b["game_time_s"] for b in out["branches"]] == [120.0, 300.0, 600.0]


def test_match_identity_is_carried(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_id="7412995551", game_run_id="7412995551")])
    out = branch_review.load_branch_series("7412995551", path=p)
    assert out["game_id"] == "7412995551"
    assert out["mode"] == "aram"
    assert out["my_champion"] == "Annie"
    assert out["enemy"] == "Caitlyn"


# --- the three constraints -------------------------------------------------

def test_legacy_rows_without_a_run_id_are_skipped_and_counted(tmp_path):
    """68 MB of pre-B4-d records have no game_run_id. Silently dropping them
    would make the corpus look smaller than it is; guessing a grouping would
    invent matches."""
    p = tmp_path / "hz.jsonl"
    legacy = _row()
    del legacy["game_run_id"]
    _write(p, [legacy, legacy, _row(game_time_s=300.0)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["legacy_rows_skipped"] == 2
    assert len(out["branches"]) == 1


def test_arena_precompute_poison_drops_the_column_not_the_row(tmp_path):
    """RM-158: the precompute column of a flagged Arena record is SR content
    wearing an Arena label. The native half is a real observation and must
    survive - ROADMAP is explicit that purging the row was WRONG."""
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(mode="arena", precompute_source="sr_copy_rm158",
                    native_action="ROUND 3 - focus the enchanter")])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["precompute_excluded"] is True
    b = out["branches"][0]
    assert b["choices"] == [], "SR content must not render as Arena advice"
    assert b["precompute_excluded"] is True
    assert b["native_action"] == "ROUND 3 - focus the enchanter"


def test_unflagged_arena_rows_keep_their_precompute(tmp_path):
    """Negative control for the row above - the exclusion must key off the
    flag, not off mode == arena."""
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(mode="arena")])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["precompute_excluded"] is False
    assert len(out["branches"][0]["choices"]) == 2


def test_tail_window_is_bounded_and_truncation_is_reported(tmp_path):
    """Never parse the whole corpus for one HTTP request; and when the window
    might have clipped the series, SAY so rather than serving a short one as
    if it were complete."""
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=float(i)) for i in range(200)])
    out = branch_review.load_branch_series(RUN_A, path=p, tail_bytes=4000)
    assert out["truncated"] is True
    assert 0 < len(out["branches"]) < 200


def test_no_truncation_flag_when_the_whole_file_fits(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=1.0), _row(game_time_s=2.0)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert out["truncated"] is False


def test_a_partial_first_line_in_the_tail_is_discarded(tmp_path):
    """A byte-offset tail lands mid-record; that fragment is not JSON and must
    not become a parse error or a phantom branch."""
    p = tmp_path / "hz.jsonl"
    rows = [_row(game_time_s=float(i)) for i in range(40)]
    _write(p, rows)
    size = p.stat().st_size
    out = branch_review.load_branch_series(RUN_A, path=p,
                                           tail_bytes=(size // 2) + 7)
    assert out["branches"], "the readable remainder must still parse"
    assert all(isinstance(b["game_time_s"], float) for b in out["branches"])


# --- degenerate inputs -----------------------------------------------------

def test_missing_file_is_empty_not_an_error(tmp_path):
    out = branch_review.load_branch_series(path=tmp_path / "nope.jsonl")
    assert out["branches"] == []
    assert out["reason"] == "no-corpus"


def test_unknown_run_id_is_empty_with_a_reason(tmp_path):
    p = tmp_path / "hz.jsonl"
    _write(p, [_row()])
    out = branch_review.load_branch_series("does-not-exist", path=p)
    assert out["branches"] == []
    assert out["reason"] == "run-not-found"


def test_corrupt_lines_are_skipped_not_fatal(tmp_path):
    p = tmp_path / "hz.jsonl"
    p.write_text(json.dumps(_row()) + "\n{ not json\n"
                 + json.dumps(_row(game_time_s=400.0)) + "\n", encoding="utf-8")
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert len(out["branches"]) == 2


def test_coverage_miss_ticks_are_not_branches_but_are_counted(tmp_path):
    """A covered=False tick has no branch set to show. It is still evidence
    the game was running, so it is counted rather than erased."""
    p = tmp_path / "hz.jsonl"
    _write(p, [_row(game_time_s=100.0, covered=False, choices=[]),
               _row(game_time_s=300.0)])
    out = branch_review.load_branch_series(RUN_A, path=p)
    assert len(out["branches"]) == 1
    assert out["ticks_total"] == 2
