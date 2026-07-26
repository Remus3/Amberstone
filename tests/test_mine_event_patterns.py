"""Normalisation guards for the win-vs-loss miner.

Every test here exists because the FIRST full-corpus run (1266 matches,
2026-07-26) produced a table whose loudest rows were artefacts of how the
population was counted, not findings. See docs/REPLAY_T2_PARSE_CRITERIA.md
section 4b.
"""
from __future__ import annotations

from tools import mine_event_patterns as mine


def _match(duration=1800, win_team=200):
    return {"info": {"gameDuration": duration, "participants": [
        {"participantId": i, "teamId": 100 if i <= 5 else 200,
         "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5],
         "win": (100 if i <= 5 else 200) == win_team}
        for i in range(1, 11)]}}


def _kill(t, killer, victim, bounty=300, shutdown=0):
    return {"type": "CHAMPION_KILL", "timestamp": t, "killerId": killer,
            "victimId": victim, "assistingParticipantIds": [],
            "bounty": bounty, "shutdownBounty": shutdown,
            "position": {"x": 1, "y": 2}}


def _frame(t, gold_by_pid):
    return {"timestamp": t, "events": [], "participantFrames": {
        str(pid): {"participantId": pid, "totalGold": g}
        for pid, g in gold_by_pid.items()}}


def _tl(events, frames=None):
    fr = list(frames or [])
    fr.append({"timestamp": 0, "participantFrames": {}, "events": events})
    return {"info": {"frameInterval": 60000, "frames": fr}}


# --------------------------------------------------- team-level inflation

def test_a_team_level_criterion_yields_one_row_per_team_not_one_per_player():
    # gold_deficit_profile is computed from TEAM totals, so all five players
    # on a side carry the identical value. Mining it per player counted one
    # team observation five times and pinned every role to the same number:
    # the first corpus run read 0.240 / 0.709 identically across all 5 roles.
    gold = {pid: (100 if pid <= 5 else 900) for pid in range(1, 11)}
    tl = _tl([], frames=[_frame(60000, gold)])
    rows = mine.team_rows(_match(), tl)
    assert len(rows) == 2
    assert {r["role"] for r in rows} == {"TEAM"}
    assert {r["win"] for r in rows} == {True, False}


def test_player_rows_no_longer_carry_the_team_level_criterion():
    gold = {pid: (100 if pid <= 5 else 900) for pid in range(1, 11)}
    tl = _tl([], frames=[_frame(60000, gold)])
    for row in mine.player_rows(_match(), tl):
        assert "gold_deficit_profile" not in row["values"]


# ------------------------------------------------------- rate normalising

def test_death_counts_are_also_reported_per_minute():
    # A raw count confounds "died more" with "played longer".
    tl = _tl([_kill(60000, 7, 2), _kill(120000, 7, 2), _kill(180000, 7, 2)])
    row = [r for r in mine.player_rows(_match(duration=1800), tl)
           if r["participant_id"] == 2][0]
    assert row["values"]["death_cost"] == 3.0
    assert round(row["values"]["deaths_per_min"], 4) == 0.1


def test_a_zero_length_game_does_not_divide_by_zero():
    tl = _tl([_kill(1000, 7, 2)])
    row = [r for r in mine.player_rows(_match(duration=0), tl)
           if r["participant_id"] == 2][0]
    assert "deaths_per_min" not in row["values"]


# ------------------------------------------------- shutdown exposure trap

def test_shutdowns_given_is_normalised_by_the_deaths_that_could_pay_one():
    # Winners gave MORE shutdowns in every role on the first corpus run
    # (1.42 vs 0.52). A shutdown is only payable when the victim was ALREADY
    # ahead, so the raw count measures how often you were ahead. The rate
    # over your own deaths removes that exposure.
    tl = _tl([_kill(60000, 7, 2, shutdown=300), _kill(120000, 7, 2),
              _kill(180000, 7, 2), _kill(240000, 7, 2)])
    row = [r for r in mine.player_rows(_match(), tl)
           if r["participant_id"] == 2][0]
    assert row["values"]["shutdowns_given"] == 1.0
    assert row["values"]["shutdown_rate"] == 0.25


def test_a_player_who_never_died_has_no_shutdown_rate_rather_than_zero():
    row = [r for r in mine.player_rows(_match(), _tl([]))
           if r["participant_id"] == 2][0]
    assert "shutdown_rate" not in row["values"]


# --------------------------------------------------------- the gate itself

def test_the_gate_needs_an_effect_size_not_just_a_relative_difference():
    # SUPPORT plate_share read SEPARATES on 0.035 vs 0.027 in the first run:
    # a 0.008 difference clears a 10 pct relative gate trivially because the
    # base is tiny. A spread-aware effect size is what makes that a NO.
    # Clears the relative gate (0.01 on a 0.09 base = 11 pct) and fails the
    # effect gate, because the spread inside each side dwarfs the gap.
    noisy_w = [0.0, 0.2] * 40
    noisy_l = [0.0, 0.18] * 40
    assert mine.verdict(noisy_w, noisy_l, min_sample=30, min_sep=0.10,
                        min_effect=0.2)["verdict"] == "NO SEPARATION"


def test_a_real_separation_still_clears_the_gate():
    tight_w = [5.0, 5.1] * 40
    tight_l = [8.0, 8.1] * 40
    out = mine.verdict(tight_w, tight_l, min_sample=30, min_sep=0.10,
                       min_effect=0.2)
    assert out["verdict"] == "SEPARATES"
    assert abs(out["effect"]) > 2


def test_an_undersampled_row_is_insufficient_whatever_its_gap():
    out = mine.verdict([1.0] * 5, [9.0] * 5, min_sample=30, min_sep=0.10,
                       min_effect=0.2)
    assert out["verdict"] == "INSUFFICIENT"


def test_two_identical_populations_have_no_effect_and_no_separation():
    same = [1.0, 2.0, 3.0] * 20
    out = mine.verdict(same, list(same), min_sample=30, min_sep=0.10,
                       min_effect=0.2)
    assert out["effect"] == 0.0
    assert out["verdict"] == "NO SEPARATION"


# ------------------------------------------------------- dropped-row bias

def test_rows_a_criterion_declines_to_emit_are_counted_not_silently_lost():
    # objective_participation emits nothing when a team took zero elite
    # monsters, and those teams are disproportionately the LOSING ones. The
    # first run showed it: n was 1238 win vs 1066 loss for that criterion
    # alone, so the loss mean was taken over a survivor-biased sample.
    tl = _tl([])  # no ELITE_MONSTER_KILL anywhere
    rows = mine.player_rows(_match(), tl)
    assert rows
    for row in rows:
        assert "objective_participation" not in row["values"]
        assert "objective_participation" in row["absent"]
