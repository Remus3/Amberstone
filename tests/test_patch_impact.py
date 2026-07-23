"""core.patch_impact - per-patch "what changed for YOUR champions".

Every test injects (conn, diff_fn, patches, key_map) so nothing here touches
data/ - the rewind db and the DS snapshots are both gitignored, so a
clean-checkout run must still be green.
"""
from __future__ import annotations

import sqlite3

import pytest

from core import patch_impact as pi


# ----- fixtures -----------------------------------------------------------

def _db(rows):
    """In-memory matches table with just the columns the module selects."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE matches (tracked_champion_id INTEGER, "
                 "map_id INTEGER, game_duration_s INTEGER, tracked_win INTEGER)")
    conn.executemany("INSERT INTO matches VALUES (?,?,?,?)", rows)
    conn.commit()
    return conn


KEY_MAP = {
    222: {"id": "Jinx", "name": "Jinx"},
    64: {"id": "LeeSin", "name": "Lee Sin"},
    62: {"id": "MonkeyKing", "name": "Wukong"},
}


def _report():
    """A diff report shaped exactly like tools.ds_patch_diff.diff_snapshots."""
    return {
        "old_patch": "16.13.1",
        "new_patch": "16.14.1",
        "sections": {
            "items": {"added": [], "removed": [], "changed": [
                {"id": "3153", "name": "Blade of the Ruined King",
                 "fields": {"gold.total": [3200, 3100]}},
                {"id": "9999", "name": "Untouched Item",
                 "fields": {"gold.total": [1000, 900]}},
            ]},
            "champions": {"added": [], "removed": [], "changed": [
                {"id": "Jinx", "name": "Jinx",
                 "fields": {"stats.attackdamage": [59, 57]}},
            ]},
            "abilities": {"added": [], "removed": [], "changed": [
                {"champion": "Jinx", "key": "Q", "form_index": 0,
                 "fields": {"cooldown": [[0.9], [0.8]]}},
                {"champion": "MonkeyKing", "key": "E", "form_index": 1,
                 "change": "form_added"},
            ]},
            "builds": {
                "aram": {"added": [], "removed": [], "changed": [
                    {"champion": "Jinx", "archetype": "balanced",
                     "items": [["3153", "3031"], ["3153", "3095"]]},
                ]},
                "sr": {"added": [], "removed": [], "changed": [
                    {"champion": "LeeSin", "archetype": "bruiser",
                     "items": [["3071"], ["3074"]]},
                ]},
                "arena": {"added": [], "removed": [], "changed": []},
            },
        },
    }


def _compute(rows, **kw):
    conn = _db(rows)
    try:
        return pi.compute_patch_impact(
            conn=conn, diff_fn=lambda *a, **k: _report(),
            patches=["16.13.1", "16.14.1"], key_map=KEY_MAP, **kw)
    finally:
        conn.close()


# ----- patch resolution ---------------------------------------------------

def test_patches_sort_numerically_not_lexically(tmp_path):
    # "16.9.1" > "16.10.1" as strings; the newest-two default depends on this.
    assert pi._patch_sort_key("16.9.1") < pi._patch_sort_key("16.10.1")
    for name in ("16.9.1", "16.10.1", "16.14.1", "notapatch"):
        (tmp_path / name).mkdir()
    assert pi.available_patches(root=tmp_path)[-2:] == ["16.10.1", "16.14.1"]


def test_defaults_to_the_two_newest_snapshots():
    out = _compute([(222, 12, 1800, 1)] * 5)
    assert (out["old_patch"], out["new_patch"]) == ("16.13.1", "16.14.1")


def test_fewer_than_two_snapshots_is_an_ok_payload_with_a_reason():
    out = pi.compute_patch_impact(patches=["16.14.1"], conn=_db([]),
                                  diff_fn=lambda *a, **k: _report())
    assert out["ok"] is True
    assert out["champions"] == []
    assert "two patch snapshots" in out["reason"]


def test_explicit_patches_override_the_disk_default():
    out = _compute([(222, 12, 1800, 1)] * 5,
                   old_patch="16.10.1", new_patch="16.11.1")
    assert (out["old_patch"], out["new_patch"]) == ("16.10.1", "16.11.1")


# ----- the join -----------------------------------------------------------

def test_champion_joins_on_the_numeric_key_not_the_display_name():
    # 62 -> "MonkeyKing" in the registry but "Wukong" on screen; a name join
    # would drop this champion's form_added ability change entirely.
    out = _compute([(62, 12, 1800, 1)] * 6)
    row = out["champions"][0]
    assert row["champion"] == "MonkeyKing"
    assert row["name"] == "Wukong"
    assert [c["field"] for c in row["ability_changes"]] == ["form_added"]


def test_change_count_sums_every_section_for_the_champion():
    out = _compute([(222, 12, 1800, 1)] * 8)
    row = out["champions"][0]
    assert len(row["champion_changes"]) == 1   # stats.attackdamage
    assert len(row["ability_changes"]) == 1    # Q cooldown
    assert len(row["build_changes"]) == 1      # balanced build
    assert len(row["item_changes"]) == 1       # 3153 is in the build
    assert row["change_count"] == 4


def test_item_change_is_attributed_only_when_it_is_in_that_build():
    out = _compute([(222, 12, 1800, 1)] * 8)
    ids = [i["item_id"] for i in out["champions"][0]["item_changes"]]
    assert ids == ["3153"]          # 9999 changed but Jinx never buys it
    assert out["changed_items"] == 2  # the global count still reports both


def test_mode_selects_the_build_section_and_the_map_id():
    # LeeSin's build change lives under sr; his ARAM games see none of it.
    sr = _compute([(64, 11, 1800, 1)] * 7, mode="sr")
    assert sr["champions"][0]["build_changes"][0]["archetype"] == "bruiser"
    aram = _compute([(64, 12, 1800, 1)] * 7, mode="aram")
    assert aram["champions"][0]["build_changes"] == []


def test_an_unknown_mode_falls_back_to_the_default():
    out = _compute([(222, 12, 1800, 1)] * 5, mode="urf")
    assert out["mode"] == pi.DEFAULT_MODE


# ----- corpus gating ------------------------------------------------------

def test_min_games_drops_the_thin_champion_at_n_minus_one():
    rows = [(222, 12, 1800, 1)] * 4 + [(64, 12, 1800, 0)] * 9
    out = _compute(rows, min_games=5)
    assert [c["champion"] for c in out["champions"]] == ["LeeSin"]


def test_min_games_admits_the_champion_exactly_at_n():
    rows = [(222, 12, 1800, 1)] * 5
    out = _compute(rows, min_games=5)
    assert [c["champion"] for c in out["champions"]] == ["Jinx"]


def test_remakes_below_min_duration_are_not_counted():
    rows = [(222, 12, 1800, 1)] * 5 + [(222, 12, 120, 0)] * 20
    out = _compute(rows)
    assert out["champions"][0]["games"] == 5


def test_rows_sort_by_games_desc_and_top_n_truncates():
    rows = ([(222, 12, 1800, 1)] * 9 + [(64, 12, 1800, 1)] * 8
            + [(62, 12, 1800, 0)] * 7)
    out = _compute(rows, top_n=2)
    assert [c["champion"] for c in out["champions"]] == ["Jinx", "LeeSin"]


def test_play_share_is_over_the_whole_corpus_not_the_shown_slice():
    rows = [(222, 12, 1800, 1)] * 5 + [(64, 12, 1800, 0)] * 15
    out = _compute(rows, top_n=1)
    assert out["n_matches"] == 20
    assert out["champions"][0]["play_share"] == 75.0  # LeeSin 15/20


def test_winrate_is_laplace_smoothed_not_raw():
    out = _compute([(222, 12, 1800, 1)] * 5)  # 5/5 raw = 100%
    assert out["champions"][0]["winrate"] < 100.0


# ----- never-raises -------------------------------------------------------

def test_a_raising_diff_returns_an_ok_payload_with_a_reason():
    conn = _db([(222, 12, 1800, 1)] * 5)
    try:
        def boom(*_a, **_k):
            raise RuntimeError("snapshot dir not found")
        out = pi.compute_patch_impact(conn=conn, diff_fn=boom,
                                      patches=["16.13.1", "16.14.1"],
                                      key_map=KEY_MAP)
    finally:
        conn.close()
    assert out["ok"] is True and out["champions"] == []
    assert out["reason"] == "patch diff failed - see logs"


def test_a_raw_exception_string_is_never_leaked_in_the_reason():
    conn = _db([])
    try:
        def boom(*_a, **_k):
            raise RuntimeError("C:/secret/path/rewind_history.db is locked")
        out = pi.compute_patch_impact(conn=conn, diff_fn=boom,
                                      patches=["a", "b"], key_map=KEY_MAP)
    finally:
        conn.close()
    assert "secret" not in (out["reason"] or "")


@pytest.mark.parametrize("report", [
    {}, {"sections": None}, {"sections": {}},
    {"sections": {"builds": {"aram": {"changed": [None, 7]}}}},
    {"sections": {"abilities": {"changed": [{"champion": "Jinx"}]}}},
    {"sections": {"items": {"changed": [{"id": "3153", "fields": {"g": [1]}}]}}},
])
def test_malformed_diff_sections_degrade_to_zero_changes(report):
    conn = _db([(222, 12, 1800, 1)] * 5)
    try:
        out = pi.compute_patch_impact(conn=conn, diff_fn=lambda *a, **k: report,
                                      patches=["16.13.1", "16.14.1"],
                                      key_map=KEY_MAP)
    finally:
        conn.close()
    assert out["champions"][0]["change_count"] == 0


def test_no_db_connection_yields_an_empty_champion_list():
    out = pi.compute_patch_impact(conn=None, diff_fn=lambda *a, **k: _report(),
                                  patches=["16.13.1", "16.14.1"],
                                  key_map=KEY_MAP)
    # _open_ro finds no db on a clean checkout; with one present the tracked
    # corpus is still a valid answer - either way the call must not raise.
    assert out["ok"] is True and isinstance(out["champions"], list)


def test_a_champion_with_no_changes_reports_zero_not_a_missing_key():
    # 64 (Lee Sin) has no ARAM-section change in the report.
    out = _compute([(64, 12, 1800, 1)] * 6)
    row = out["champions"][0]
    assert row["change_count"] == 0
    assert row["champion_changes"] == [] and row["item_changes"] == []


def test_bad_top_n_and_min_games_fall_back_instead_of_raising():
    out = _compute([(222, 12, 1800, 1)] * 5, top_n="x", min_games=None)
    assert out["top_n"] == pi.DEFAULT_TOP_N
    assert out["min_games"] == pi.DEFAULT_MIN_GAMES


def test_champion_key_map_on_a_missing_snapshot_is_empty(tmp_path):
    assert pi.champion_key_map("99.99.9", root=tmp_path) == {}


def test_available_patches_on_a_missing_root_is_empty(tmp_path):
    assert pi.available_patches(root=tmp_path / "nope") == []
