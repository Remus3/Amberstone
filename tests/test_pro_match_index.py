"""Oracle tests for the local pro-match recovery join.

Both inputs are operator-local and gitignored (the .xlsx lives on the Desktop,
the DB is not tracked), so every test skips rather than fails on a clean
checkout. See `docs/_scratch/PRO_MATCH_RECOVERY_SPEC.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import pro_match_index as pmi

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Confirmed live 2026-07-20 against Match-V5: queue 420, full timelines.
SEED_EXPECTATIONS = {
    "NA1_5216883079": {"Blaber", "Zven"},
    "NA1_5217712024": {"Impact"},
    "NA1_5221491343": {"Quad"},
}


@pytest.fixture(scope="module")
def roster():
    if not pmi.DEFAULT_ROSTER_PATH.exists():
        pytest.skip("pro roster xlsx not present on this machine")
    return pmi.load_pro_roster()


@pytest.fixture(scope="module")
def with_pro(roster):
    if not DB_PATH.exists():
        pytest.skip("rewind_history.db not present (gitignored)")
    return pmi.find_pro_matches(DB_PATH, roster, same_team_only=True)


def test_roster_parses_without_openpyxl(roster):
    assert len(roster) == 30
    for row in roster:
        assert "#" in row["riot_id"]
        assert row["game_name"] and row["tagline"]
    assert any(r["pro_name"] == "Blaber" for r in roster)


def test_seed_matches_resolve_to_expected_pros(with_pro):
    for match_id, expected in SEED_EXPECTATIONS.items():
        assert match_id in with_pro, f"{match_id} missing from the WITH-pro set"
        names = {p["pro_name"] for p in with_pro[match_id]}
        assert names == expected, f"{match_id}: {names} != {expected}"


def test_every_recovered_match_is_already_ingested(with_pro):
    """The whole point: no Match-V5 ingestion pass is needed."""
    meta = pmi.describe_matches(DB_PATH, list(with_pro))
    assert set(meta) == set(with_pro), "a recovered id is absent from matches"
    missing = [m for m, v in meta.items() if not (v["has_stats"] and v["has_timeline"])]
    assert not missing, f"matches lacking stats or timeline: {missing}"


def test_same_team_filter_is_narrower_than_any_pro(roster):
    if not DB_PATH.exists():
        pytest.skip("rewind_history.db not present (gitignored)")
    any_pro = pmi.find_pro_matches(DB_PATH, roster, same_team_only=False)
    with_pro = pmi.find_pro_matches(DB_PATH, roster, same_team_only=True)
    assert set(with_pro) < set(any_pro)
    assert all(p["same_team"] for ps in with_pro.values() for p in ps)
