"""
core/smoothed_rates.py - shared smoothed-rate primitive.

CLAUDE.md #90 decision (2), LOCKED 2026-05-17. ONE module owning the
small statistical family RC uses to turn sparse win/loss counts into a
trustworthy rate, replacing three ad-hoc reimplementations:

  - the augment recommender's own/pair win-rate + external-seed blend
    (`core/augment_recommender.py`, the concrete reference factored here),
  - pick/ban synergy ranking (today only a raw recent-form proxy in
    `dashboard/routes_pickban.py`),
  - the s220 PGR Morello-style 0-100 score (ROADMAP S3 - prospective
    consumer; the API is shaped to serve it but it is not built yet).

Algorithm re-implemented clean from the math spec (ref
`Maelian25/lol-draft-prediction` - no LICENSE, algorithm only). Three
pure functions, no state, never raise:

  laplace_rate(wins, games, alpha)
      Laplace / Beta-smoothed success rate, shrunk toward 0.5:
          (wins + alpha) / (games + 2*alpha)
      "Beta-smoothed pairwise" is just this applied to pair counts -
      one primitive, two uses. Unseen (games=0, alpha=1) -> 0.5.

  shrink(n, k)
      Confidence weight n / (n + k) in [0, 1). How much a sample of
      size n is trusted relative to a prior. n=0 -> 0.0.

  blend(own, prior, weight)
      Convex external-seed blend: weight*own + (1-weight)*prior.

These reproduce the inline arithmetic that was in `augment_recommender`
exactly. Every RC caller passes alpha=1.0, so `laplace_rate`'s
denominator is always >= 2 and its non-positive guard is unreachable
for real inputs - the extraction is byte-identical (pinned by
tests/test_smoothed_rates.py + the unchanged tests/test_augment_recommender.py).
"""
from __future__ import annotations

# Defaults shared across consumers so the statistical family stays
# coherent. Callers may override per-use (augment recommender exposes
# alpha/k knobs); these match its DEFAULT_ALPHA / DEFAULT_K.
DEFAULT_ALPHA = 1.0   # Laplace/Beta prior strength (-> 0.5 baseline)
DEFAULT_K = 5.0       # n/(n+K) shrinkage (the plan's n/(n+5) family)


def laplace_rate(wins: float, games: float, alpha: float = DEFAULT_ALPHA) -> float:
    """Laplace/Beta-smoothed success rate: (wins + alpha) / (games + 2*alpha).

    Pulls a raw rate toward 0.5 by `alpha` pseudo-wins + `alpha`
    pseudo-losses, so a 2-0 record does not outrank a 14-8 one. With
    games=0 and the default alpha this returns the neutral 0.5.

    `games + 2*alpha <= 0` is unreachable from any RC caller (all use
    alpha=1.0 -> denom >= 2). The guard returns the neutral 0.5 rather
    than raising; it never changes a result a real caller can observe.
    """
    denom = games + 2.0 * alpha
    if denom <= 0:
        return 0.5
    return (wins + alpha) / denom


def shrink(n: float, k: float = DEFAULT_K) -> float:
    """Confidence weight n / (n + k), in [0, 1).

    The fraction of trust a sample of size `n` earns against a prior:
    n=0 -> 0.0 (no own evidence, lean fully on the prior); n >> k -> ~1
    (own evidence dominates). Mirrors the original
    `n / (n + k) if (n + k) > 0 else 0.0` exactly - strict `> 0`, so a
    zero or negative denominator also yields 0.0.
    """
    denom = n + k
    if denom > 0:
        return n / denom
    return 0.0


def blend(own: float, prior: float, weight: float) -> float:
    """Convex external-seed blend: weight*own + (1-weight)*prior.

    `weight` is expected in [0, 1] (callers pass `shrink(...)` output):
    weight=0 -> pure prior (cold start), weight=1 -> pure own history.
    Pure combination - not clamped, because the only producer of
    `weight` is `shrink`, which is already bounded.
    """
    return weight * own + (1.0 - weight) * prior
