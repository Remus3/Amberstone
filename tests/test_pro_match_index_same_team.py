"""RM-356 regression: `same_team` must be real in BOTH modes, not just the default.

`find_pro_matches` emits a `same_team` flag on every returned row. It derives
that flag from an `operator_team` lookup that was populated only inside
`if same_team_only:`, so under `same_team_only=False` the dict was empty,
`.get(match_id)` returned `None`, and `None == team_id` pinned the flag to
`False` on every row - including matches where the pro genuinely shared the
operator's team. A consumer could not tell that collapsed `False` from a real
one.

The oracle tests in `tests/test_pro_match_index.py` all skip on a clean
checkout (both the roster .xlsx and `data/rewind_history.db` are gitignored
and operator-local), and the only assertion touching the flag checks the
`True` path alone. These tests build their own SQLite fixture instead, so the
contract is guarded on any machine and in CI.
"""

from __future__ import annotations

import sqlite3

import pytest

from core import pro_match_index as pmi

PRO = {
    "riot_id": "ProCarry#NA1",
    "game_name": "ProCarry",
    "tagline": "NA1",
    "pro_name": "ProCarry",
    "role_team": "MID / Example",
}

# match_id -> (operator team_id or None if the operator is absent, pro team_id)
FIXTURE_MATCHES = {
    "NA1_TOGETHER": (100, 100),
    "NA1_AGAINST": (100, 200),
    "NA1_NO_OPERATOR": (None, 100),
}


@pytest.fixture()
def db_path(tmp_path):
    """A minimal `participants` table shaped like `data/rewind_history.db`."""
    path = tmp_path / "fixture_history.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE participants ("
            "match_id TEXT, team_id INTEGER, "
            "riot_id_game_name TEXT, riot_id_tagline TEXT)"
        )
        for match_id, (operator_team, pro_team) in FIXTURE_MATCHES.items():
            if operator_team is not None:
                conn.execute(
                    "INSERT INTO participants VALUES (?, ?, ?, ?)",
                    (match_id, operator_team, pmi.OPERATOR_GAME_NAME, "Vayne"),
                )
            conn.execute(
                "INSERT INTO participants VALUES (?, ?, ?, ?)",
                (match_id, pro_team, PRO["game_name"], PRO["tagline"]),
            )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture()
def roster():
    return [dict(PRO)]


def test_any_pro_mode_reports_a_shared_team_as_shared(db_path, roster):
    """The filed acceptance, asserted literally.

    Operator and pro both on team 100, queried with `same_team_only=False`.
    """
    found = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    assert found["NA1_TOGETHER"][0]["same_team"] is True


def test_any_pro_mode_reports_an_opposing_team_as_not_shared(db_path, roster):
    """The flag must still discriminate - a fix that hardcodes True is wrong."""
    found = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    assert found["NA1_AGAINST"][0]["same_team"] is False


def test_any_pro_mode_reports_false_when_the_operator_is_absent(db_path, roster):
    """No operator row means no shared team, whatever the pro's team_id is."""
    found = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    assert found["NA1_NO_OPERATOR"][0]["same_team"] is False


def test_any_pro_mode_still_returns_every_match_containing_the_pro(db_path, roster):
    """The flag fix must not start filtering the un-filtered mode."""
    found = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    assert set(found) == set(FIXTURE_MATCHES)


def test_same_team_mode_is_unchanged(db_path, roster):
    """Non-regression on the default path: still filtered, still flagged True."""
    found = pmi.find_pro_matches(db_path, roster, same_team_only=True)
    assert set(found) == {"NA1_TOGETHER"}
    assert found["NA1_TOGETHER"][0]["same_team"] is True


def test_the_two_modes_agree_on_every_match_they_share(db_path, roster):
    """The flag is a property of the match, not of the query mode.

    This is the invariant the defect broke: the same match read both ways
    returned `True` under the default and `False` under `same_team_only=False`.
    """
    any_pro = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    with_pro = pmi.find_pro_matches(db_path, roster, same_team_only=True)
    assert set(with_pro) < set(any_pro)
    for match_id, rows in with_pro.items():
        assert [r["same_team"] for r in rows] == [
            r["same_team"] for r in any_pro[match_id]
        ]


def test_operator_lookup_is_case_insensitive_in_any_pro_mode(db_path, roster):
    """The join lowercases both sides; the hoisted query must keep doing so."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE participants SET riot_id_game_name = ? WHERE lower(riot_id_game_name) = ?",
            (pmi.OPERATOR_GAME_NAME.upper(), pmi.OPERATOR_GAME_NAME.lower()),
        )
        conn.commit()
    finally:
        conn.close()
    found = pmi.find_pro_matches(db_path, roster, same_team_only=False)
    assert found["NA1_TOGETHER"][0]["same_team"] is True
