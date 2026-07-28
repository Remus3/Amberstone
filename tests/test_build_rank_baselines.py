"""Regression tests for the four rank-baseline builder defects.

MASTER went missing from data/rank_baselines.json for weeks because a skipped
cohort is invisible: nothing in the payload records it and the exit code stays
0. And nobody could backfill just MASTER, because a targeted rerun rewrote the
whole file from a one-cohort plan and destroyed the other 30 cohorts.

Every seam that touches the network is monkeypatched; these tests are offline.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

from tools import build_rank_baselines as brb  # noqa: E402

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


def _participant(pid: int, position: str) -> dict:
    """A Match-V5 participant that survives cohort_baseline.participant_metrics.

    timePlayed must clear MIN_TIME_PLAYED_S (600) or the metric dict is empty
    and the row is dropped before it reaches cb.build.
    """
    return {
        "participantId": pid,
        "teamPosition": position,
        "timePlayed": 1800,
        "totalMinionsKilled": 150,
        "neutralMinionsKilled": 10,
        "goldEarned": 12000,
        "totalDamageDealtToChampions": 18000,
        "totalDamageTaken": 22000,
        "visionScore": 30,
        "wardsPlaced": 12,
        "wardsKilled": 4,
        "timeCCingOthers": 25,
        "totalHealsOnTeammates": 0,
        "damageDealtToTurrets": 3000,
        "kills": 5,
        "deaths": 4,
        "assists": 9,
        "gameEndedInEarlySurrender": False,
        "win": pid <= 5,
    }


def _match() -> dict:
    """A ten-seat match that the REAL corpus_hygiene.judge() includes.

    gameDuration clears REMAKE_MAX_SECONDS (300) and seat 1 does not carry
    gameEndedInEarlySurrender, which are the only two things judge() checks
    without a sidecar.
    """
    return {
        "metadata": {"matchId": "NA1_FAKE"},
        "info": {
            "gameDuration": 1800,
            "queueId": 420,
            "participants": [_participant(i + 1, ROLES[i % 5])
                             for i in range(10)],
        },
    }


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Neutralize pacing and every network seam in the module."""
    monkeypatch.setattr(brb, "_pace", lambda: None)
    monkeypatch.setattr(
        brb, "accounts_for_cohort",
        lambda tier, division, want: [f"puuid-{tier}-{division}-0"])
    monkeypatch.setattr(brb, "match_ids", lambda puuid, count: [f"{puuid}-m0"])
    monkeypatch.setattr(brb.riot_api, "get_match", lambda mid: _match())


def _run(tmp_path, *extra) -> tuple:
    """main() over a tmp --out; returns (exit_code, stdout, parsed_payload)."""
    out = tmp_path / "rank_baselines.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = brb.main(["--out", str(out), *extra])
    payload = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return code, buf.getvalue(), payload


# ------------------------------------------------------------------ D1 merge

def test_targeted_rerun_preserves_untouched_cohorts(tmp_path):
    """A --tiers MASTER backfill must not destroy the other 30 cohorts."""
    out = tmp_path / "rank_baselines.json"
    seeded = {
        "source": "match_v5", "queue": brb.QUEUE, "tiers": {
            "IRON_I": {"tier": "IRON", "division": "I", "matches": 41,
                       "player_rows": 410, "roles": {"TOP": {"marker": 1}}},
            "GOLD_IV": {"tier": "GOLD", "division": "IV", "matches": 37,
                        "player_rows": 370, "roles": {"BOT": {"marker": 2}}},
        }}
    out.write_text(json.dumps(seeded, indent=2), encoding="utf-8")

    code, _, payload = _run(tmp_path, "--tiers", "MASTER")

    assert code == 0
    assert payload["tiers"]["IRON_I"] == seeded["tiers"]["IRON_I"]
    assert payload["tiers"]["GOLD_IV"] == seeded["tiers"]["GOLD_IV"]
    assert "MASTER" in payload["tiers"]
    assert payload["tiers"]["MASTER"]["tier"] == "MASTER"


def test_sampling_params_recorded_per_cohort(tmp_path):
    """Under merge the top-level params describe THIS run only, so each
    cohort has to carry the params it was actually sampled with."""
    _, _, first = _run(tmp_path, "--tiers", "MASTER",
                       "--accounts-per-cohort", "3", "--matches-per-account", "2")
    assert first["tiers"]["MASTER"]["accounts_per_cohort"] == 3
    assert first["tiers"]["MASTER"]["matches_per_account"] == 2

    _, _, second = _run(tmp_path, "--tiers", "CHALLENGER",
                        "--accounts-per-cohort", "9", "--matches-per-account", "7")
    assert second["tiers"]["MASTER"]["accounts_per_cohort"] == 3
    assert second["tiers"]["MASTER"]["matches_per_account"] == 2
    assert second["tiers"]["CHALLENGER"]["accounts_per_cohort"] == 9
    assert second["tiers"]["CHALLENGER"]["matches_per_account"] == 7


def test_unparseable_existing_file_does_not_abort_the_run(tmp_path):
    """A corrupt prior file is not a reason to lose this run's work."""
    out = tmp_path / "rank_baselines.json"
    out.write_text("{ not json", encoding="utf-8")

    code, _, payload = _run(tmp_path, "--tiers", "MASTER")

    assert code == 0
    assert "MASTER" in payload["tiers"]


# ------------------------------------------------------- D2 + D3 summary rows

def test_summary_lists_every_sampled_cohort_exactly_once(tmp_path):
    """Divisional cohorts are keyed PLATINUM_I, so a summary that looks up
    the bare tier name prints only apex rows - and every row it does print
    is labelled with a leaked loop variable."""
    _, stdout, payload = _run(tmp_path, "--tiers", "PLATINUM,MASTER")

    expected = ["PLATINUM_I", "PLATINUM_II", "PLATINUM_III", "PLATINUM_IV",
                "MASTER"]
    assert sorted(payload["tiers"]) == sorted(expected)

    lines = stdout.splitlines()
    header = next(i for i, ln in enumerate(lines)
                  if ln.startswith("tier") and "rows" in ln)
    labels = [ln.split()[0] for ln in lines[header + 1:]
              if ln.strip() and not ln.startswith("(")]
    for key in expected:
        assert labels.count(key) == 1, f"{key} label count {labels.count(key)}"
    assert len(labels) == len(set(labels)), f"duplicate summary labels: {labels}"


# -------------------------------------------------------------- D4 loud skip

def test_skipped_cohort_is_recorded_and_exits_non_zero(tmp_path, monkeypatch):
    """The MASTER regression itself: a cohort that resolves no accounts must
    leave a machine-detectable trace and fail the run."""
    def _no_master(tier, division, want):
        return [] if tier == "MASTER" else [f"puuid-{tier}-{division}-0"]

    monkeypatch.setattr(brb, "accounts_for_cohort", _no_master)
    code, _, payload = _run(tmp_path, "--tiers", "MASTER,CHALLENGER")
    out = tmp_path / "rank_baselines.json"

    assert code != 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "MASTER" in payload["skipped"]
    assert "CHALLENGER" in payload["tiers"]
    assert "MASTER" not in payload["tiers"]


def test_clean_run_reports_no_skips(tmp_path):
    code, _, payload = _run(tmp_path, "--tiers", "MASTER,GRANDMASTER")

    assert code == 0
    assert payload["skipped"] == []
    assert sorted(payload["tiers"]) == ["GRANDMASTER", "MASTER"]


# --------------------------------------------------------- real judge() path

def test_real_judge_drops_a_remake_and_keeps_a_full_game(tmp_path, monkeypatch):
    """Exercises the unpatched corpus_hygiene.judge over the fixture."""
    remake = _match()
    remake["info"]["gameDuration"] = 120
    served = [remake]
    monkeypatch.setattr(brb.riot_api, "get_match", lambda mid: served[0])

    _, _, dropped = _run(tmp_path, "--tiers", "MASTER")
    assert dropped["tiers"]["MASTER"]["matches"] == 0
    assert dropped["tiers"]["MASTER"]["dropped"] == 1

    served[0] = _match()
    _, _, kept = _run(tmp_path, "--tiers", "CHALLENGER")
    assert kept["tiers"]["CHALLENGER"]["matches"] == 1
    assert kept["tiers"]["CHALLENGER"]["dropped"] == 0
    assert kept["tiers"]["CHALLENGER"]["player_rows"] == 10
