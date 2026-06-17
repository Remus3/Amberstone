"""Robustness / property / fail-soft tests for tools/replay_build_order_validate.py
- the Lane-B BUILD-ORDER Haiku-flip gate (HZ-C2).

This file is the ROBUSTNESS sibling of tests/test_replay_build_order_validate.py.
The primary file owns the happy paths + the basic status branches; this file
targets the fail-soft DB edges, the statistical / set-semantic PROPERTIES, and
the run_validation cross-arm INVARIANTS that the primary file does not exercise.

Every test injects its own ``comp_lean_fn`` + ``table_lookup_fn`` closures and
builds an in-memory / tmp_path sqlite fixture, so NOTHING here reads the real
HZ-B2 ``build_order_variants`` table or the real data/rewind_history.db. The
schema string is copied locally (matches / participants / timeline_events).

ASCII-only by hard rule. TESTS-ONLY: the gate module is not edited.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import replay_build_order_validate as gate  # noqa: E402


# ----------------------------------------------------------------- schema helpers
# Copied locally (mirrors the primary file) so this file never depends on the
# real DB. The FULL schema; individual tests drop a column to force a fail-soft.
def _full_schema() -> str:
    return (
        "CREATE TABLE matches (match_id TEXT, game_mode TEXT, has_timeline INTEGER, "
        "game_creation_ts INTEGER);"
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, team_id INTEGER, "
        "champion_name TEXT, win INTEGER, item0 INTEGER, item1 INTEGER, item2 INTEGER, "
        "item3 INTEGER, item4 INTEGER, item5 INTEGER, item6 INTEGER);"
        "CREATE TABLE timeline_events (match_id TEXT, timestamp_ms INTEGER, event_type TEXT, "
        "participant_id INTEGER, item_id INTEGER);"
    )


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_full_schema())
    return conn


def _add_match(conn, mid="M1", ts=1000):
    conn.execute(
        "INSERT INTO matches VALUES (?, 'CLASSIC', 1, ?)", (mid, ts))


def _ins(conn, mid, pid, team, champ, win, items):
    """Insert a participant; ``items`` is padded with 0s to fill item0..item6.
    A None champ / None pid is passed through verbatim (to test the skip guard)."""
    cols = list(items) + [0] * (7 - len(items))
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, pid, team, champ, 1 if win else 0, *cols[:7]))


def _ev(conn, mid, ts, etype, pid, iid):
    conn.execute(
        "INSERT INTO timeline_events VALUES (?,?,?,?,?)", (mid, ts, etype, pid, iid))


def _lookup_from(table):
    """A trivial table-lookup over {champ: {variant: {"order": [...]}}}."""
    def _lk(champ, variant):
        return (table.get(champ) or {}).get(variant) or {}
    return _lk


def _lookup_cells(at_cell, as_cell):
    """A table-lookup that returns arbitrary (possibly malformed) cells by variant,
    independent of champion - for distinctive_sets fail-soft probing."""
    def _lk(_champ, variant):
        return at_cell if variant == "anti_tank" else as_cell
    return _lk


# ===================================================================== 1. DB fail-soft
# A missing/renamed column or a missing table -> extract_build_rows /
# first_recommended_purchase_min return [] / None, never raise.
def test_extract_build_rows_missing_column_is_empty():
    conn = sqlite3.connect(":memory:")
    # participants table is MISSING item6 (renamed/dropped) -> the gate's SELECT
    # of item0..item6 raises sqlite3.OperationalError, which must be swallowed.
    conn.executescript(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, team_id INTEGER, "
        "champion_name TEXT, win INTEGER, item0 INTEGER, item1 INTEGER, item2 INTEGER, "
        "item3 INTEGER, item4 INTEGER, item5 INTEGER);"
    )
    assert gate.extract_build_rows(conn, "M1") == []


def test_extract_build_rows_missing_table_is_empty():
    conn = sqlite3.connect(":memory:")  # no participants table at all
    assert gate.extract_build_rows(conn, "M1") == []


def test_first_purchase_min_missing_column_is_none():
    conn = sqlite3.connect(":memory:")
    # timeline_events is MISSING item_id -> SELECT raises -> None.
    conn.executescript(
        "CREATE TABLE timeline_events (match_id TEXT, timestamp_ms INTEGER, "
        "event_type TEXT, participant_id INTEGER);"
    )
    assert gate.first_recommended_purchase_min(
        conn, "M1", 1, frozenset({"2"})) is None


def test_first_purchase_min_missing_table_is_none():
    conn = sqlite3.connect(":memory:")  # no timeline_events table
    assert gate.first_recommended_purchase_min(
        conn, "M1", 1, frozenset({"2"})) is None


# ===================================================== 2. extract_build_rows guards
def test_extract_build_rows_three_teams_is_empty():
    conn = _make_db()
    _add_match(conn, "M3")
    _ins(conn, "M3", 1, 100, "Cho", True, [2])
    _ins(conn, "M3", 6, 200, "Lux", False, [4])
    _ins(conn, "M3", 11, 300, "Zed", False, [9])
    assert gate.extract_build_rows(conn, "M3") == []


def test_extract_build_rows_one_team_is_empty():
    conn = _make_db()
    _add_match(conn, "M1")
    _ins(conn, "M1", 1, 100, "Cho", True, [2])
    _ins(conn, "M1", 2, 100, "Lux", True, [4])
    assert gate.extract_build_rows(conn, "M1") == []


def test_extract_build_rows_skips_null_champ_and_null_pid():
    conn = _make_db()
    _add_match(conn, "M4")
    _ins(conn, "M4", 1, 100, "Cho", True, [2])
    _ins(conn, "M4", 2, 100, None, True, [9])     # NULL champ -> skipped
    _ins(conn, "M4", None, 100, "Ghost", True, [9])  # NULL pid -> skipped
    _ins(conn, "M4", 6, 200, "Lux", False, [4])
    rows = gate.extract_build_rows(conn, "M4")
    champs = sorted(r.champion for r in rows)
    assert champs == ["Cho", "Lux"]
    # The NULL-champ teammate does not pollute Cho's enemy comp either.
    cho = next(r for r in rows if r.champion == "Cho")
    assert cho.enemy_comp == ("Lux",)


def test_extract_build_rows_enemy_team_all_empty_champs_is_empty():
    # A participant whose enemy team has ZERO real champs: every team-200 member
    # has an empty champion_name, so it never registers as a second team and the
    # two-team guard collapses to []. (The per-team 'if not enemy' guard is the
    # defensive backstop for the same condition.)
    conn = _make_db()
    _add_match(conn, "M5")
    _ins(conn, "M5", 1, 100, "Cho", True, [2])
    _ins(conn, "M5", 6, 200, "", False, [4])
    assert gate.extract_build_rows(conn, "M5") == []


# ===================================================== 3. two_prop_diff_ci property
@pytest.mark.parametrize(
    "s1,n1,s2,n2",
    [(60, 100, 50, 100), (10, 50, 40, 80), (1, 2, 1, 1000), (333, 333, 0, 5)],
)
def test_two_prop_diff_ci_diff_is_exact_and_bracketed(s1, n1, s2, n2):
    diff, lo, hi = gate.two_prop_diff_ci(s1, n1, s2, n2)
    assert diff == pytest.approx(s1 / n1 - s2 / n2)
    assert lo <= diff <= hi


def test_two_prop_diff_ci_symmetric_magnitude():
    # Swapping the two arms negates the diff and mirrors the interval.
    d1, lo1, hi1 = gate.two_prop_diff_ci(60, 100, 50, 100)
    d2, lo2, hi2 = gate.two_prop_diff_ci(50, 100, 60, 100)
    assert d2 == pytest.approx(-d1)
    # The interval half-width (margin) is identical; bounds mirror around 0.
    assert (hi1 - lo1) == pytest.approx(hi2 - lo2)
    assert lo2 == pytest.approx(-hi1)
    assert hi2 == pytest.approx(-lo1)


def test_two_prop_diff_ci_larger_z_widens():
    _d, lo_95, hi_95 = gate.two_prop_diff_ci(60, 100, 50, 100, z=1.96)
    _d2, lo_99, hi_99 = gate.two_prop_diff_ci(60, 100, 50, 100, z=2.576)
    # Same point estimate, strictly wider interval at the higher z.
    assert (hi_99 - lo_99) > (hi_95 - lo_95)
    assert lo_99 < lo_95 and hi_99 > hi_95


def test_two_prop_diff_ci_zero_over_zero_all_none():
    assert gate.two_prop_diff_ci(0, 0, 0, 0) == (None, None, None)
    assert gate.two_prop_diff_ci(5, 0, 5, 10) == (None, None, None)
    assert gate.two_prop_diff_ci(5, 10, 5, 0) == (None, None, None)


# =================================================== 4. classify_actual_lean property
def test_classify_actual_lean_order_insensitive():
    at, as_ = frozenset({"2", "3"}), frozenset({"4", "5"})
    base = ["1", "2", "3", "9"]
    verdict = gate.classify_actual_lean(base, at, as_)
    assert verdict == "anti_tank"
    for _ in range(20):
        shuf = base[:]
        random.shuffle(shuf)
        assert gate.classify_actual_lean(shuf, at, as_) == verdict


def test_classify_actual_lean_duplicates_counted_once():
    # Set semantics: repeating a distinctive id does not stack the count.
    at, as_ = frozenset({"2"}), frozenset({"4", "5"})
    # anti_tank id "2" duplicated 3x, but anti_squishy still has 2 distinct hits.
    assert gate.classify_actual_lean(
        ["2", "2", "2", "4", "5"], at, as_) == "anti_squishy"


def test_classify_actual_lean_empty_items_is_none():
    assert gate.classify_actual_lean(
        [], frozenset({"2"}), frozenset({"4"})) is None


def test_classify_actual_lean_disjoint_from_both_is_none():
    assert gate.classify_actual_lean(
        ["7", "8", "9"], frozenset({"2", "3"}), frozenset({"4", "5"})) is None


# ===================================================== 5. distinctive_sets fail-soft
def test_distinctive_sets_non_dict_cell_is_none():
    # A non-dict at-cell (a list) -> isinstance(...,dict) False -> order None -> None.
    assert gate.distinctive_sets(
        "C", _lookup_cells(["not", "a", "dict"], {"order": ["1"]})) is None


def test_distinctive_sets_order_not_a_list_is_none():
    # A non-list (falsy scalar) order -> 'not at_order' guard -> None.
    assert gate.distinctive_sets(
        "C", _lookup_cells({"order": ""}, {"order": ["1"]})) is None
    assert gate.distinctive_sets(
        "C", _lookup_cells({"order": 0}, {"order": ["1"]})) is None


def test_distinctive_sets_none_order_is_none():
    assert gate.distinctive_sets(
        "C", _lookup_cells({"order": None}, {"order": ["1"]})) is None
    # Symmetric: the anti_squishy side missing too.
    assert gate.distinctive_sets(
        "C", _lookup_cells({"order": ["1"]}, {"order": None})) is None


def test_distinctive_sets_int_ids_coerced_to_str():
    # Integer item ids in the order are str-coerced and intersect a STR build.
    at_only, as_only = gate.distinctive_sets(
        "C", _lookup_cells({"order": [1, 2, 3]}, {"order": [1, 4, 5]}))
    assert at_only == frozenset({"2", "3"})
    assert as_only == frozenset({"4", "5"})
    # And the str-keyed build classifies against the coerced sets.
    assert gate.classify_actual_lean(["2", "3"], at_only, as_only) == "anti_tank"


# ===================================================== 6. run_validation invariants
def _seed_multirow_db(db_path):
    """A hand-built multi-row CLASSIC DB spanning followed / not-followed /
    ambiguous / uncovered_champ outcomes across both recommended variants.

    Covered champ = Cho (anti_tank order [2], anti_squishy order [4]).
    Covered champ = Vlad (anti_tank order [6], anti_squishy order [8]).
    Uncovered = Lux / Malphite (only ever appear as enemies)."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_full_schema())
    # game_creation_ts descending order is irrelevant to the invariants.
    rows = [
        # mid, pid, team, champ, win, items
        # M1: Cho followed anti_tank (won); enemy Malphite uncovered.
        ("M1", 1, 100, "Cho", True, [2]),
        ("M1", 6, 200, "Malphite", False, [99]),
        # M2: Cho NOT-followed (built anti_squishy item4) while anti_tank rec'd (lost).
        ("M2", 1, 100, "Cho", False, [4]),
        ("M2", 6, 200, "Malphite", True, [99]),
        # M3: Vlad followed anti_tank (lost).
        ("M3", 1, 100, "Vlad", False, [6]),
        ("M3", 6, 200, "Lux", True, [99]),
        # M4: Vlad ambiguous (built neither distinctive id) -> excluded from arms.
        ("M4", 1, 100, "Vlad", True, [99]),
        ("M4", 6, 200, "Lux", False, [99]),
    ]
    for i, (mid, pid, team, champ, win, items) in enumerate(rows):
        if pid == 1:  # one match row per mid; insert the match once
            conn.execute(
                "INSERT INTO matches VALUES (?, 'CLASSIC', 1, ?)", (mid, 1000 - i))
        _ins(conn, mid, pid, team, champ, win, items)
    conn.commit()
    conn.close()


def _multirow_report(db_path, with_timing=False):
    table = {
        "Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}},
        "Vlad": {"anti_tank": {"order": ["6"]}, "anti_squishy": {"order": ["8"]}},
    }
    # Every resolvable enemy comp -> recommend anti_tank (a tank wall).
    return gate.run_validation(
        db_path, limit=0,
        comp_lean_fn=lambda comp: ("anti_tank", "high"),
        table_lookup_fn=_lookup_from(table),
        with_timing=with_timing,
    )


def test_run_validation_arm_totals_equal_decisive(tmp_path):
    db = tmp_path / "inv.db"
    _seed_multirow_db(db)
    rep = _multirow_report(db)
    decisive = rep["status_counts"]["decisive"]
    assert rep["followed"]["n"] + rep["not_followed"]["n"] == decisive
    # Sanity: this fixture yields exactly 3 decisive (Cho-foll, Cho-not, Vlad-foll).
    assert decisive == 3


def test_run_validation_status_counts_sum_to_rows_total(tmp_path):
    db = tmp_path / "inv.db"
    _seed_multirow_db(db)
    rep = _multirow_report(db)
    assert sum(rep["status_counts"].values()) == rep["rows_total"]


def test_run_validation_matrix_reconciles_to_by_variant(tmp_path):
    db = tmp_path / "inv.db"
    _seed_multirow_db(db)
    rep = _multirow_report(db)
    for rec in ("anti_tank", "anti_squishy"):
        # by_variant followed n == matrix[rec][rec] n (followed means actual==rec).
        foll_n = rep["by_variant"][rec]["followed"]["n"]
        assert foll_n == rep["matrix"][rec][rec]["n"]
        # not_followed n == sum over the OTHER actual columns.
        not_n = rep["by_variant"][rec]["not_followed"]["n"]
        other_sum = sum(
            rep["matrix"][rec][act]["n"]
            for act in ("anti_tank", "anti_squishy") if act != rec)
        assert not_n == other_sum
    # And the matrix grand total reconciles to the two headline arms.
    grand = sum(
        rep["matrix"][r][a]["n"]
        for r in ("anti_tank", "anti_squishy")
        for a in ("anti_tank", "anti_squishy"))
    assert grand == rep["followed"]["n"] + rep["not_followed"]["n"]


def test_run_validation_flip_ready_false_when_arm_below_min(tmp_path):
    db = tmp_path / "inv.db"
    _seed_multirow_db(db)
    rep = _multirow_report(db)
    # Each arm is far below _FLIP_MIN_N (300) -> never flip-ready.
    assert rep["followed"]["n"] < gate._FLIP_MIN_N
    assert rep["not_followed"]["n"] < gate._FLIP_MIN_N
    assert rep["difference"]["flip_ready"] is False


def test_run_validation_no_timing_leaves_timing_zero(tmp_path):
    db = tmp_path / "inv.db"
    _seed_multirow_db(db)
    rep = _multirow_report(db, with_timing=False)
    assert rep["timing"]["n"] == 0
    assert rep["timing"]["median_min"] is None


# ===================================================== 7. first_recommended_purchase_min
def test_first_purchase_min_global_earliest_out_of_order():
    conn = _make_db()
    # Inserted out of chronological order; the EARLIEST matching minute wins.
    _ev(conn, "MX", 600000, "ITEM_PURCHASED", 1, 2)
    _ev(conn, "MX", 300000, "ITEM_PURCHASED", 1, 2)   # earliest match = 5.0 min
    _ev(conn, "MX", 900000, "ITEM_PURCHASED", 1, 2)
    got = gate.first_recommended_purchase_min(conn, "MX", 1, frozenset({"2"}))
    assert got == pytest.approx(5.0)


def test_first_purchase_min_ignores_other_events_and_participants():
    conn = _make_db()
    # An even-earlier matching id, but bought by a DIFFERENT participant -> ignored.
    _ev(conn, "MX", 60000, "ITEM_PURCHASED", 9, 2)
    # A non-purchase event for the right pid+id -> ignored.
    _ev(conn, "MX", 120000, "ITEM_DESTROYED", 1, 2)
    # The genuine earliest purchase by pid 1 of a distinctive id is at 7 min.
    _ev(conn, "MX", 420000, "ITEM_PURCHASED", 1, 2)
    got = gate.first_recommended_purchase_min(conn, "MX", 1, frozenset({"2"}))
    assert got == pytest.approx(7.0)


def test_first_purchase_min_matches_on_int_str_coercion():
    conn = _make_db()
    # item_id stored as INT 2; distinctive set is the STR "2" -> must still match.
    _ev(conn, "MX", 480000, "ITEM_PURCHASED", 1, 2)
    got = gate.first_recommended_purchase_min(conn, "MX", 1, frozenset({"2"}))
    assert got == pytest.approx(8.0)


# ===================================================== 8. _WinBucket + _timing_report
def test_winbucket_all_wins_winrate_one():
    b = gate._WinBucket()
    for _ in range(4):
        b.record(True)
    d = b.to_dict()
    assert d["n"] == 4 and d["wins"] == 4
    assert d["winrate"] == pytest.approx(1.0)


def test_winbucket_empty_winrate_none():
    assert gate._WinBucket().to_dict()["winrate"] is None


def test_timing_report_even_count_median_averages_two_middle():
    # n=4 minutes [5,10,20,30] -> median = (10+20)/2 = 15.0.
    rep = gate._timing_report(
        [(5.0, True), (10.0, False), (20.0, True), (30.0, False)])
    assert rep["n"] == 4
    assert rep["median_min"] == pytest.approx(15.0)
    assert rep["fast"]["n"] == 2 and rep["slow"]["n"] == 2


def test_timing_report_ties_at_median_go_fast():
    # Odd n=3 minutes [10,10,20] -> median = middle = 10. Both 10s are <= median
    # so they fall in the FAST bucket; only the 20 is slow.
    rep = gate._timing_report([(10.0, True), (10.0, True), (20.0, False)])
    assert rep["median_min"] == pytest.approx(10.0)
    assert rep["fast"]["n"] == 2
    assert rep["fast"]["wins"] == 2
    assert rep["slow"]["n"] == 1
    assert rep["slow"]["wins"] == 0
