"""
core/draft_elo.py - Elo log-odds draft-composition aggregator.

Closes the FUTURE entry from `draft tool L (the community fork) triage 2026-05-19` (BACKLOG):
the team-vs-team draft layer the existing pickban backend
(``dashboard/routes_pickban.py``) is missing. Algorithm reimplemented
clean from the formula (no draft tool L (the community fork) license; the algorithm is the
public-domain Elo math used widely in chess + draft systems):

  rating(win_rate) = -400 * log10(1/wr - 1)
  win_rate(rating) =  1  / (1 + 10^(-rating/400))

A team's draft strength is the sum of ratings from three sources:

  champ_rating[i]  - smoothed solo WR on each ally champion, in rating units
  pair_rating[i,j] - smoothed pair WR for each unordered ally pair (synergy)
  matchup_rating[i,j] - smoothed pair WR for each ally x enemy laneup (counter)

  team_score = sum(ally_champ)   + sum(ally_pair)   + sum(matchup)
             - sum(enemy_champ)  - sum(enemy_pair)

  predicted_winrate = win_rate(team_score)

The smoothing layer is ``core.smoothed_rates`` (Laplace prior + shrink).
This module is PURE MATH - no I/O, no DB. Use ``core.draft_elo_db`` for
the rewind-history-backed prior look-ups. Composing on smoothed_rates
keeps the statistical family coherent across the pick/ban / augment /
PGR consumers (CLAUDE.md #90 lock).

Why log-odds Elo over additive WR averages:
  An additive sum of per-champ win rates blows up past [0, 1] for any
  team with 5 above-average champs. The log-odds transform maps win
  rate onto an unbounded additive scale that the inverse sigmoid then
  squashes back into [0, 1] - the same trick BattleNet / TrueSkill /
  Glicko use to mix multiple independent edges into a single match
  prediction. Additive Elo ratings ARE the right thing to sum.

Numerical guards (none of which a real caller hits, but defensive):
  - win_rate clamped to (0.001, 0.999) before the rating transform so a
    1.0 or 0.0 input does not blow up to +/- infinity.
  - rating_to_winrate is unbounded-input safe (extreme deltas saturate
    cleanly to ~0 or ~1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


_EPS = 1e-3       # clamp WR to (EPS, 1-EPS) before the log
_LOG_SCALE = 400.0  # canonical Elo log-scale (chess + League MMR convention)


def winrate_to_rating(win_rate: float, scale: float = _LOG_SCALE) -> float:
    """Convert a win rate (in [0, 1]) to an Elo rating in points.

    Identity points: ``wr == 0.5`` -> rating 0. Above 0.5 -> positive,
    below -> negative. The scale defaults to 400 (chess + LoL MMR).

    Extreme inputs are clamped to (0.001, 0.999) so the log10 is finite.
    A real caller pulls win rates from ``laplace_rate`` which never
    returns the endpoints, so the clamp is defensive only.
    """
    wr = max(_EPS, min(1.0 - _EPS, float(win_rate)))
    return -scale * math.log10(1.0 / wr - 1.0)


def rating_to_winrate(rating: float, scale: float = _LOG_SCALE) -> float:
    """Inverse of ``winrate_to_rating``.

    Returns the probability the team with this rating delta wins:
      rating  0   -> 0.5
      rating +100 -> ~0.640
      rating +400 -> ~0.909
      rating -400 -> ~0.091
    """
    # Stable sigmoid form: 1 / (1 + 10^(-x/scale)).
    return 1.0 / (1.0 + math.pow(10.0, -float(rating) / scale))


@dataclass(frozen=True)
class DraftSide:
    """Per-side aggregate. Used as both input to ``team_score`` and as
    a structured response by ``dashboard.routes_draft_elo``.

    ``champ_ratings``  - one entry per champion on this side (5 for SR).
    ``pair_ratings``   - one entry per unordered ally-pair (10 for SR).
    ``matchup_ratings`` - one entry per ally x enemy laneup (5 for SR;
                          off-lane matchups are typically 0 because
                          the data is too sparse to be informative).
    """
    champ_ratings: tuple[float, ...]
    pair_ratings: tuple[float, ...]
    matchup_ratings: tuple[float, ...] = ()

    @property
    def total(self) -> float:
        return (
            sum(self.champ_ratings)
            + sum(self.pair_ratings)
            + sum(self.matchup_ratings)
        )


def team_score(ally: DraftSide, enemy: DraftSide) -> float:
    """Subtract enemy's rating total from ally's.

    Matchup ratings are accrued on the ALLY side (they're ally champ X
    vs enemy laner Y); the enemy side carries its own solo + pair
    ratings but does not double-count matchups.
    """
    return ally.total - (sum(enemy.champ_ratings) + sum(enemy.pair_ratings))


def draft_winrate(ally: DraftSide, enemy: DraftSide,
                  scale: float = _LOG_SCALE) -> float:
    """One-shot: ``rating_to_winrate(team_score(...))``."""
    return rating_to_winrate(team_score(ally, enemy), scale=scale)


# Helpful enumerators for the route layer. Kept here so the math module
# stays the single source-of-truth for the 5-champ assumption.

def unordered_pairs(seq: tuple[int, ...]) -> list[tuple[int, int]]:
    """All unordered 2-tuples of seq. (5-len -> 10 pairs.)

    Order within each pair: lower champ id first, so the cache key is
    deterministic and ally-pair (a, b) == ally-pair (b, a).
    """
    n = len(seq)
    out: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = seq[i], seq[j]
            if a > b:
                a, b = b, a
            out.append((a, b))
    return out


def cross_pairs(ally: tuple[int, ...], enemy: tuple[int, ...]) -> list[tuple[int, int]]:
    """All (ally_i, enemy_j) pairs, ordered. (5x5 -> 25 cross-pairs.)

    Order: ally id is FIRST in the returned tuple so the caller can
    distinguish ally x enemy from enemy x ally semantically. For a real
    "matchup" the caller usually filters down to the 5 same-lane
    pairings; the cross-pair helper just enumerates all 25 so the
    lane-pairing decision lives in the consumer.
    """
    return [(a, e) for a in ally for e in enemy]


# Per-row contribution breakdown for the draft Elo hover strip (BACKLOG
# Draft Tool L pair-list + Diff15 pattern, ROADMAP carry-forward 109(b)).
#
# Each entry decomposes one rating-source's signed contribution to the
# final team_score so the frontend can render a top-N "why this WR"
# overlay. Signs are normalized to the ALLY perspective:
#
#   ally-pair  delta = +rating  (positive helps ally)
#   enemy-pair delta = -rating  (positive enemy rating SUBTRACTS from
#                                team_score; see team_score() above)
#   matchup    delta = +rating  (already ally-perspective)
#
# Sample density ``n`` is the raw game count for the underlying pair or
# matchup query, surfaced verbatim so the frontend can render the
# confidence band (matches the shrink-style "n=N" indicator on the
# top-level chip).


@dataclass(frozen=True)
class Contribution:
    """One signed contribution to the team_score, sortable by abs(delta).

    ``kind`` is "ally-pair" / "enemy-pair" / "matchup". ``a`` is the
    first champion id (lower-id ally, lower-id enemy, or the ally champ
    of the matchup). ``b`` is the second. ``delta`` is the signed
    Elo-rating credit to the ALLY team_score. ``n`` is the raw game
    count from the underlying smoothed-rate query.
    """
    kind: str
    a: int
    b: int
    delta: float
    n: int


def top_contributions(
    *,
    ally_pairs: list[tuple[int, int]],
    enemy_pairs: list[tuple[int, int]],
    matchup_cross: list[tuple[int, int]],
    ally_pair_ratings: tuple[float, ...],
    enemy_pair_ratings: tuple[float, ...],
    matchup_ratings: tuple[float, ...],
    ally_pair_counts: list[int],
    enemy_pair_counts: list[int],
    matchup_counts: list[int],
    limit: int = 3,
) -> list[Contribution]:
    """Return the top-N contributions to team_score by abs(delta).

    Pure aggregation over the same inputs ``team_score()`` already
    consumes - no new math, just the decomposed view. Sign convention
    is normalized to the ally-team perspective so a hover row's
    +/-arrow reads correctly regardless of which side carries the
    edge.

    Lengths must agree (the caller built them from the same
    enumerators); a mismatch is silently ignored (only the prefix
    that matches is considered). This is defensive against a future
    schema drift; real callers always pass coherent triples.
    """
    out: list[Contribution] = []
    # Ally pairs: positive rating helps ally.
    for (a, b), r, n in zip(ally_pairs, ally_pair_ratings, ally_pair_counts):
        out.append(Contribution(kind="ally-pair", a=int(a), b=int(b),
                                delta=float(r), n=int(n)))
    # Enemy pairs: positive rating subtracts from team_score; flip sign.
    for (a, b), r, n in zip(enemy_pairs, enemy_pair_ratings, enemy_pair_counts):
        out.append(Contribution(kind="enemy-pair", a=int(a), b=int(b),
                                delta=-float(r), n=int(n)))
    # Matchups: already ally-perspective rating.
    for (a, b), r, n in zip(matchup_cross, matchup_ratings, matchup_counts):
        out.append(Contribution(kind="matchup", a=int(a), b=int(b),
                                delta=float(r), n=int(n)))
    # Sort by abs(delta) descending. Stable sort keeps ally-pair before
    # enemy-pair before matchup on ties, which makes the test pin
    # deterministic without affecting the top-N for any real input.
    out.sort(key=lambda c: -abs(c.delta))
    if limit and limit > 0:
        return out[:limit]
    return out
