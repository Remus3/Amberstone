"""The absent-row exclusion DEFLATES win-vs-loss separation - it cannot inflate it.

docs/REPLAY_T2_PARSE_CRITERIA.md section 4b-4 carried this bias with the sign
BACKWARDS until 2026-07-28. It claimed that taking the loss mean over survivors
would INFLATE the `objective_participation` rows, and used that to justify the
"not promotable" call. The arithmetic runs the other way.

`core/event_patterns.py:160` drops a player whose team took zero elite monsters
(`if not took: return []`). The natural value for those players is 0 - you
cannot participate in a share of nothing - and 0 is the minimum of the range.
Deleting minimum-valued rows RAISES the mean of the side they came from. They
come overwhelmingly from the loss side, so the loss mean is held UP, and
`win_mean - loss_mean` is held DOWN. The exclusion hides separation.

These tests encode that as arithmetic, not as prose. They run the REAL gate,
`tools.mine_event_patterns.verdict` - the same function that produced the
published table - over generated distributions, over the shipped corpus
summary, and against the numbers printed in the doc.
"""
from __future__ import annotations

import json
import pathlib
import random
import re

from core import event_patterns as ep
from tools import mine_event_patterns as mine

REPO = pathlib.Path(__file__).resolve().parent.parent
RATES = REPO / "data" / "event_pattern_rates.json"
DOC = REPO / "docs" / "REPLAY_T2_PARSE_CRITERIA.md"

# The miner's own gate thresholds, so `verdict` behaves here as it does live.
MIN_SAMPLE, MIN_SEP, MIN_EFFECT = 30, 0.3, 0.2


def _sep(win_values, loss_values) -> float:
    """Signed separation from the real gate: win_mean - loss_mean."""
    return mine.verdict(win_values, loss_values,
                        MIN_SAMPLE, MIN_SEP, MIN_EFFECT)["delta"]


# --------------------------------------------------------------------------
# 1. The arithmetic invariant, as a property over many distributions.
# --------------------------------------------------------------------------

def _distributions(rng):
    """Shapes a participation-share population plausibly takes, in [0, 1]."""
    return {
        "uniform": lambda: rng.uniform(0.0, 1.0),
        "beta_high": lambda: rng.betavariate(5.0, 2.0),
        "beta_low": lambda: rng.betavariate(2.0, 5.0),
        "tight_mid": lambda: min(1.0, max(0.0, rng.gauss(0.5, 0.08))),
        "bimodal": lambda: rng.betavariate(1.2, 8.0) if rng.random() < 0.4
        else rng.betavariate(8.0, 1.2),
        "quantised": lambda: rng.randint(0, 4) / 4.0,
    }


def test_dropping_absent_rows_never_raises_the_separation():
    """Signed: excluding the zero rows can only move the delta DOWN.

    This is the general claim and it holds for every shape - the exclusion
    cannot manufacture separation. Magnitude is checked separately below,
    because a large enough drop can push the delta through zero and out the
    far side, which is a bigger failure than the one being guarded here.
    """
    rng = random.Random(20260728)
    checked = 0
    for name, draw in _distributions(rng).items():
        for trial in range(25):
            n = rng.randint(200, 600)
            # Losing teams take zero objectives far more often than winning
            # ones: the shipped corpus drops 3 win rows against 281 loss rows.
            win_absent = rng.randint(0, 5)
            loss_absent = rng.randint(30, int(n * 0.45))
            win_present = [draw() for _ in range(n)]
            loss_present = [draw() for _ in range(n - loss_absent)]

            with_zeros = _sep(win_present + [0.0] * win_absent,
                              loss_present + [0.0] * loss_absent)
            dropped = _sep(win_present, loss_present)

            assert dropped <= with_zeros + 1e-12, (
                f"{name} trial {trial}: dropping the absent rows RAISED the "
                f"separation {with_zeros:.6f} -> {dropped:.6f}")
            checked += 1
    assert checked == 150, f"expected 150 generated cases, ran {checked}"


def test_dropping_absent_rows_shrinks_the_magnitude_when_the_sign_holds():
    """Magnitude: while the separation still points win-ward, it SHRINKS.

    Restricted to the regime the doc is actually talking about - a positive
    measured delta, as BOT/MID/TOP/SUPPORT all have. The non-vacuity assert at
    the end is load-bearing: without it a precondition that never fires would
    make this pass by never testing anything.
    """
    rng = random.Random(96040)
    exercised = 0
    for name, draw in _distributions(rng).items():
        for trial in range(25):
            n = rng.randint(200, 600)
            loss_absent = rng.randint(30, int(n * 0.45))
            # Win side drawn from the same shape, shifted up, so the delta
            # starts positive the way every published role row does.
            win_present = [min(1.0, draw() + 0.15) for _ in range(n)]
            loss_present = [draw() for _ in range(n - loss_absent)]

            with_zeros = _sep(win_present, loss_present + [0.0] * loss_absent)
            dropped = _sep(win_present, loss_present)
            if not (with_zeros > 0 and dropped > 0):
                continue

            assert abs(dropped) < abs(with_zeros), (
                f"{name} trial {trial}: magnitude did not shrink "
                f"{with_zeros:.6f} -> {dropped:.6f}")
            exercised += 1
    assert exercised >= 100, (
        f"only {exercised} cases reached the magnitude assert - the "
        "precondition is filtering the test into vacuity")


def test_the_deflation_comes_from_the_asymmetry_not_the_exclusion():
    """Isolates the cause: it is WHICH side loses rows, not that rows are lost.

    Two populations differing only in how many zeros sit on the loss side.
    Excluding zeros multiplies each side's mean by `N / (N - zeros)`, so when
    the two sides lose the same share the delta is scaled up, not down - a
    symmetric exclusion does NOT deflate. The published rows lose 281 loss rows
    against 3 win rows, and that lopsidedness is the entire effect.
    """
    rng = random.Random(1064)
    n = 500
    for _ in range(20):
        win_present = [rng.betavariate(5.0, 2.0) for _ in range(n - 5)]
        loss_present = [rng.betavariate(2.0, 5.0) for _ in range(n - 200)]
        excluded = _sep(win_present, loss_present)

        lopsided = _sep(win_present + [0.0] * 5, loss_present + [0.0] * 200)
        assert excluded < lopsided, (
            "with the drop concentrated on the loss side the exclusion must "
            f"deflate: {lopsided:.4f} -> {excluded:.4f}")

        # Same loss sample, same exclusion, but now only 5 zeros were lost
        # from it - matching the win side's 5.
        symmetric = _sep(win_present + [0.0] * 5, loss_present + [0.0] * 5)
        assert excluded > symmetric, (
            "when both sides lose the same share, excluding the zeros scales "
            f"the delta UP, not down: {symmetric:.4f} -> {excluded:.4f}")


# --------------------------------------------------------------------------
# 2. The mechanism that creates the absent rows, exercised for real.
# --------------------------------------------------------------------------

def _match():
    return {"info": {"gameDuration": 1800, "participants": [
        {"participantId": i, "teamId": 100 if i <= 5 else 200,
         "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][
             (i - 1) % 5],
         "win": i > 5}
        for i in range(1, 11)]}}


def _timeline(events):
    return {"info": {"frames": [{"events": events}]}}


def _elite(killer, team, assists=()):
    return {"type": "ELITE_MONSTER_KILL", "timestamp": 600000,
            "killerId": killer, "killerTeamId": team, "monsterType": "DRAGON",
            "monsterSubType": "FIRE_DRAGON", "position": {"x": 1, "y": 2},
            "bounty": 100, "assistingParticipantIds": list(assists)}


def test_zero_objective_team_emits_no_row_at_all():
    """The source of the missing rows: absence, not a recorded 0."""
    match = _match()
    # Team 200 takes two dragons; team 100 takes none.
    tl = _timeline([_elite(6, 200), _elite(7, 200, assists=[6])])

    assert ep.objective_participation(match, tl, 1) == [], (
        "a player on a team that took zero elite monsters must emit no row - "
        "that absence is the whole bias")
    taker = ep.objective_participation(match, tl, 6)
    assert len(taker) == 1 and taker[0].value == 1.0


def test_imputing_zero_for_the_absent_rows_widens_the_gap():
    """End to end on the real criterion: restore the rows, gap grows.

    Builds two populations from the real `objective_participation`, one side
    containing teams that took nothing, then compares the gate's delta with
    those players excluded (what the miner does today) against the delta with
    their true 0 restored.
    """
    match = _match()
    winners, losers = [], []
    absent_losers = 0
    for i in range(60):
        # Winning team 200 always takes objectives; participant 6 shares most.
        tl = _timeline([_elite(6, 200), _elite(7, 200, assists=[6])])
        winners.extend(f.value for f in ep.objective_participation(match, tl, 6))
        # Losing team 100 takes something only a third of the time.
        if i % 3 == 0:
            tl_l = _timeline([_elite(1, 100), _elite(2, 100)])
        else:
            tl_l = _timeline([_elite(6, 200)])
        rows = ep.objective_participation(match, tl_l, 1)
        if rows:
            losers.extend(f.value for f in rows)
        else:
            absent_losers += 1

    assert absent_losers > 0, "fixture must actually produce absent rows"
    measured = _sep(winners, losers)
    imputed = _sep(winners, losers + [0.0] * absent_losers)
    assert imputed > measured, (
        f"restoring the absent rows at 0 must WIDEN the gap: measured "
        f"{measured:.4f}, imputed {imputed:.4f}")


# --------------------------------------------------------------------------
# 3. The published numbers, re-derived from the shipped corpus summary.
# --------------------------------------------------------------------------

def _objective_rows():
    blob = json.loads(RATES.read_text(encoding="utf-8"))
    rows = {r["role"]: r for r in blob["rows"]
            if r["criterion"] == "objective_participation"}
    # Per-role train population: what a criterion with no absences reports.
    pop = {}
    for r in blob["rows"]:
        if r["absent_win"] == 0 and r["absent_loss"] == 0:
            pop[r["role"]] = max(pop.get(r["role"], 0), r["n_win"], r["n_loss"])
    return rows, pop


def _imputed_delta(row, population):
    """Delta with every dropped row restored at its natural 0.

    A mean over `n` present rows, re-taken over `population` rows of which the
    missing ones are 0, is just `mean * n / population`. Both sides use the
    TRAIN population, because `n_win`/`n_loss` are train-split counts while
    `absent_win`/`absent_loss` are whole-corpus counts - mixing them is the
    unit trap called out in the doc.
    """
    win = row["win_mean"] * row["n_win"] / population
    loss = row["loss_mean"] * row["n_loss"] / population
    return win - loss


def test_every_role_deflates_on_the_shipped_corpus():
    rows, pop = _objective_rows()
    assert set(rows) == {"BOT", "JUNGLE", "MID", "SUPPORT", "TOP"}
    for role, row in sorted(rows.items()):
        imputed = _imputed_delta(row, pop[role])
        assert imputed > row["delta"], (
            f"{role}: imputing the absent rows must raise the delta, got "
            f"{row['delta']:.4f} -> {imputed:.4f}")


def test_jungle_no_separation_is_an_artefact_of_the_exclusion():
    """The strongest form of the claim: one role's verdict flips outright."""
    rows, pop = _objective_rows()
    jungle = rows["JUNGLE"]
    assert jungle["verdict"] == "NO SEPARATION"
    assert jungle["delta"] < 0, "JUNGLE reads negative as measured"
    assert _imputed_delta(jungle, pop["JUNGLE"]) > 0, (
        "restoring the absent rows must flip JUNGLE positive - the exclusion "
        "is what produced the NO SEPARATION verdict")


def test_doc_table_matches_a_fresh_derivation():
    """Read the published table off disk and re-derive every cell.

    Not a substring pin. The doc prints a number per role; this recomputes that
    number from `data/event_pattern_rates.json` and requires agreement, so the
    table cannot drift away from the corpus it claims to summarise.
    """
    rows, pop = _objective_rows()
    text = DOC.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\|\s*(BOT|MID|TOP|SUPPORT|JUNGLE)\s*\|\s*([+-]?\d*\.\d+)\s*\|"
        r"\s*([+-]?\d*\.\d+)\s*\|", re.MULTILINE)
    published = {m.group(1): (float(m.group(2)), float(m.group(3)))
                 for m in pattern.finditer(text)}
    assert set(published) == set(rows), (
        f"could not read all five role rows out of {DOC.name}: "
        f"found {sorted(published)}")

    for role, (doc_measured, doc_imputed) in sorted(published.items()):
        row = rows[role]
        assert abs(doc_measured - row["delta"]) < 5e-4, (
            f"{role}: doc prints measured {doc_measured}, corpus says "
            f"{row['delta']}")
        derived = _imputed_delta(row, pop[role])
        assert abs(doc_imputed - derived) < 5e-4, (
            f"{role}: doc prints imputed {doc_imputed}, derivation gives "
            f"{derived:.4f}")
        assert doc_imputed > doc_measured, (
            f"{role}: the published table must show deflation")
