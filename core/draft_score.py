"""core/draft_score.py - deterministic five-layer draft-quality score.

Serves the Haiku-to-ZERO north star (BACKLOG "Draft + coach lane"): ZERO
API, ZERO LLM. Pure local math over owned primitives - the tracked corpus'
own participant win-rates (core.draft_elo_db over data/rewind_history.db,
Laplace-smoothed via core.smoothed_rates), an injectable DS kit-damage-class
resolver, an injectable champion-scaling resolver, and the item-277
101.qq duo-synergy seam.

The score fuses FIVE layers, each a WR-space sub-score centered at 0.5:

  lane-matchup      30%  mean ally-perspective matchup WR vs the enemy comp
  pairwise synergy  20%  mean same-team pair WR of the ally comp (+101qq nudge)
  damage balance    15%  physical/magical spread of the ally comp (kit-mix)
  early-late scaling 10%  coherence of the comp's power-timing (resolver-fed)
  base WR           25%  mean smoothed solo WR of the ally champions

HONESTY (CLAUDE.md): draft explains little, so the output is deliberately
BOUNDED to a narrow 42-58 band around a neutral 50 - we do NOT manufacture a
0-100 spread. Every layer is trust-weighted by its own sample density
(shrink), so a thin layer barely moves the needle, and a layer with no data
(no enemy comp -> no matchup; no scaling primitive yet -> scaling inert) is
transparently marked contributed=False and simply drops out of the blend
rather than dragging the score toward 50. Confidence (HIGH/MED/LOW) reflects
the aggregate evidence behind the layers that DID contribute.

The scaling layer is declared with its reserved 10% weight but ships inert
by default: RC has no cheap per-champion power-timing primitive yet, and
faking one would violate the no-fake-spread rule. It activates the moment a
scaling_resolver is supplied (the route may wire a DS spike-derived one
later); until then it contributes nothing and says so.

Read-only. Never raises - a bad/empty db, a garbage conn, or a throwing
resolver all degrade to a well-formed neutral payload.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Iterable, Optional

from core.smoothed_rates import shrink

log = logging.getLogger("rc.draft_score")

# ---- fusion constants -------------------------------------------------
# Static layer importance weights (sum to 1.0). The fusion normalizes by the
# weights of the CONTRIBUTING layers, so an inert layer does not bias 50.
WEIGHTS: dict[str, float] = {
    "matchup": 0.30,
    "synergy": 0.20,
    "damage_balance": 0.15,
    "scaling": 0.10,
    "base_wr": 0.25,
}

# Honest bounded band. A trust-weighted mean WR-deviation of `delta` maps to
# 50 + delta*BAND_SCALE points, then hard-clamped to [BAND_LO, BAND_HI].
BAND_LO = 42.0
BAND_HI = 58.0
BAND_SCALE = 100.0

# A corpus layer below this many observed games does not contribute (its
# smoothed rate is too close to the 0.5 prior to trust). Mirrors the sibling
# aggregators' MIN_GAMES floor.
MIN_GAMES = 5

# shrink() confidence thresholds -> tier (DEFAULT_K=5: shrink(20)=0.8,
# shrink(5)=0.5). Mirrors core.session_hygiene.
_CONF_HIGH = 0.8
_CONF_MED = 0.5

# Damage-balance swing: a perfectly split comp lands at 0.5 + this, a mono-
# damage comp at 0.5 - this. Kept small - draft explains little.
_DMG_SWING = 0.15

# 101qq external duo-synergy nudge weight when a covered pair is found.
_DUO_BLEND = 0.30


# ======================================================================
# Pure fusion math (DB-free) - the bulk of the correctness proof.
# ======================================================================
def fuse_layers(layer_inputs: Iterable[dict]) -> dict:
    """Fuse per-layer WR-space sub-scores into one bounded draft score.

    Each layer input: {name, weight, sub_score: float|None, n: int}. A layer
    CONTRIBUTES iff sub_score is not None and n >= MIN_GAMES (resolver layers
    pass a synthetic n to signal coverage). The blend is a trust-weighted
    (static weight * shrink(n)) mean of the (sub_score - 0.5) deviations, so
    thin or inert layers naturally fall away.

    Never raises. Zero contributing layers -> neutral 50.0 / LOW.
    """
    layers_out = []
    num = 0.0          # sum of weight*trust*delta
    den = 0.0          # sum of weight*trust  (blend denominator)
    conf_num = 0.0     # sum of weight*trust  (for aggregate confidence)
    conf_den = 0.0     # sum of weight        (over contributing)
    contributing = 0

    for ly in layer_inputs:
        name = ly.get("name")
        weight = float(ly.get("weight") or 0.0)
        sub = ly.get("sub_score")
        n = int(ly.get("n") or 0)
        contributed = sub is not None and n >= MIN_GAMES
        trust = shrink(n) if contributed else 0.0
        if contributed:
            delta = float(sub) - 0.5
            num += weight * trust * delta
            den += weight * trust
            conf_num += weight * trust
            conf_den += weight
            contributing += 1
        layers_out.append({
            "name": name,
            "weight": round(weight, 4),
            "sub_score": (None if sub is None else round(float(sub), 4)),
            "n": n,
            "trust": round(trust, 4),
            "contributed": contributed,
        })

    if den > 0:
        blended_delta = num / den
        score = 50.0 + blended_delta * BAND_SCALE
        score = max(BAND_LO, min(BAND_HI, score))
    else:
        blended_delta = 0.0
        score = 50.0

    if conf_den > 0:
        agg_trust = conf_num / conf_den
        if agg_trust >= _CONF_HIGH:
            confidence = "HIGH"
        elif agg_trust >= _CONF_MED:
            confidence = "MED"
        else:
            confidence = "LOW"
    else:
        confidence = "LOW"

    return {
        "score": round(score, 1),
        "confidence": confidence,
        "band": [BAND_LO, BAND_HI],
        "blended_delta": round(blended_delta, 4),
        "contributing": contributing,
        "layers": layers_out,
    }


# ======================================================================
# Layer assembly from owned primitives.
# ======================================================================
def _mean(vals: list) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _matchup_layer(conn, ally: list, enemy: Optional[list], qids) -> dict:
    """Layer 1: mean ally-perspective matchup WR over the 25 cross-pairs."""
    if conn is None or not enemy:
        return _layer("matchup", None, 0)
    from core import draft_elo_db
    rates, total = [], 0
    for a in ally:
        for e in enemy:
            try:
                _w, g, rate = draft_elo_db.matchup_winrate(conn, a, e, qids)
            except sqlite3.Error:
                continue
            rates.append(rate)
            total += g
    return _layer("matchup", _mean(rates), total)


def _synergy_layer(conn, ally: list, qids, name_resolver, duo_lookup) -> dict:
    """Layer 2: mean same-team pair WR over the 10 ally pairs, optionally
    nudged toward the 101qq duo-synergy rate for any covered pair."""
    if conn is None or len(ally) < 2:
        return _layer("synergy", None, 0)
    from core import draft_elo_db
    rates, total = [], 0
    for i in range(len(ally)):
        for j in range(i + 1, len(ally)):
            a, b = ally[i], ally[j]
            try:
                _w, g, rate = draft_elo_db.pair_winrate(conn, a, b, qids, side="ally")
            except sqlite3.Error:
                continue
            ext = _duo_rate(a, b, name_resolver, duo_lookup)
            if ext is not None:
                rate = (1.0 - _DUO_BLEND) * rate + _DUO_BLEND * ext
            rates.append(rate)
            total += g
    return _layer("synergy", _mean(rates), total)


def _duo_rate(a, b, name_resolver, duo_lookup) -> Optional[float]:
    """Best-effort 101qq duo-synergy rate for an ally pair, or None."""
    if duo_lookup is None or name_resolver is None:
        return None
    try:
        na, nb = name_resolver(a), name_resolver(b)
        if not na or not nb:
            return None
        for x, y in ((na, nb), (nb, na)):
            r = duo_lookup(x, y)
            if r is not None:
                return float(r)
    except Exception:  # noqa: BLE001 - resolver is external, never trust it
        return None
    return None


def _damage_balance_layer(ally: list, resolver) -> dict:
    """Layer 3: physical/magical spread of the ally comp from a kit-damage-
    class resolver. A balanced comp (harder to itemize against) scores above
    0.5; a mono-damage comp below. Contributes only when >= 2 champs resolve.
    """
    if resolver is None:
        return _layer("damage_balance", None, 0)
    phys = mag = 0.0
    resolved = 0
    for cid in ally:
        try:
            cls = resolver(cid)
        except Exception:  # noqa: BLE001
            cls = None
        if cls == "physical":
            phys += 1.0
        elif cls == "magical":
            mag += 1.0
        elif cls == "mixed":
            phys += 0.5
            mag += 0.5
        else:
            continue
        resolved += 1
    if resolved < 2:
        return _layer("damage_balance", None, 0)
    frac_phys = phys / resolved
    frac_mag = mag / resolved
    balance = 1.0 - abs(frac_phys - frac_mag)   # 1.0 = perfect split, 0 = mono
    sub = 0.5 + (balance - 0.5) * (2.0 * _DMG_SWING)
    # Coverage is the evidence: n = resolved champs (>= MIN_GAMES? no - use a
    # coverage-scaled synthetic count so a fully-resolved comp reads trusted).
    n = resolved * MIN_GAMES
    return _layer("damage_balance", sub, n)


def _scaling_layer(ally: list, resolver) -> dict:
    """Layer 4: early-late scaling coherence from a per-champ power-timing
    resolver (0=early .. 1=late). Coherence = 1 - spread; a comp that shares a
    win condition scores above a scattered one. Inert (no resolver) by design.
    """
    if resolver is None:
        return _layer("scaling", None, 0)
    timings = []
    for cid in ally:
        try:
            t = resolver(cid)
        except Exception:  # noqa: BLE001
            t = None
        if t is not None:
            timings.append(max(0.0, min(1.0, float(t))))
    if len(timings) < 2:
        return _layer("scaling", None, 0)
    m = sum(timings) / len(timings)
    var = sum((t - m) ** 2 for t in timings) / len(timings)
    spread = min(1.0, (var ** 0.5) / 0.5)   # 0.5 stdev == maximal incoherence
    coherence = 1.0 - spread
    sub = 0.5 + (coherence - 0.5) * (2.0 * _DMG_SWING)
    n = len(timings) * MIN_GAMES
    return _layer("scaling", sub, n)


def _base_wr_layer(conn, ally: list, qids) -> dict:
    """Layer 5: mean smoothed solo WR of the ally champions. Trust governed by
    the WEAKEST-evidenced champion (min games), so one thin pick caps it."""
    if conn is None or not ally:
        return _layer("base_wr", None, 0)
    from core import draft_elo_db
    rates, min_g = [], None
    for c in ally:
        try:
            _w, g, rate = draft_elo_db.solo_winrate(conn, c, qids)
        except sqlite3.Error:
            continue
        rates.append(rate)
        min_g = g if min_g is None else min(min_g, g)
    if not rates:
        return _layer("base_wr", None, 0)
    return _layer("base_wr", _mean(rates), min_g or 0)


def _layer(name: str, sub_score: Optional[float], n: int) -> dict:
    return {"name": name, "weight": WEIGHTS[name], "sub_score": sub_score, "n": n}


def compute_draft_score(
    ally_ids: list,
    enemy_ids: Optional[list] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
    queue_ids: Optional[Iterable[int]] = None,
    damage_class_resolver: Optional[Callable] = None,
    scaling_resolver: Optional[Callable] = None,
    duo_synergy_lookup: Optional[Callable] = None,
    champ_name_resolver: Optional[Callable] = None,
) -> dict:
    """Deterministic five-layer draft score for an ally comp (vs an optional
    enemy comp).

    ally_ids: exactly 5 Riot integer champion keys. enemy_ids: optional 5 for
    the matchup layer (omitted -> matchup inert). conn: an injected draft_elo_db
    -shaped sqlite handle (participants+matches); None opens a read-only handle
    to the live rewind db. queue_ids: optional queue filter (default the SR set).
    The four resolver callables are injectable seams (see module docstring);
    each is best-effort and fail-soft.

    Never raises. A bad conn / empty corpus / throwing resolver yields a
    well-formed ok payload with a neutral score.
    """
    if not isinstance(ally_ids, (list, tuple)) or len(ally_ids) != 5:
        return {"ok": False, "error": "ally_ids must be exactly 5 champion ids",
                "score": 50.0, "confidence": "LOW", "band": [BAND_LO, BAND_HI],
                "layers": []}

    ally = list(ally_ids)
    enemy = list(enemy_ids) if enemy_ids else None
    qids = tuple(queue_ids) if queue_ids is not None else None

    own = False
    if conn is None:
        try:
            from core import draft_elo_db
            conn = draft_elo_db.open_ro()
            own = True
        except Exception as exc:  # noqa: BLE001 - absent/locked db is expected
            log.warning("draft_score open_ro: %s", exc)
            conn = None

    # A non-sqlite conn (defensive: a caller passed garbage) must not raise.
    if conn is not None and not isinstance(conn, sqlite3.Connection):
        conn = None

    try:
        layers = [
            _matchup_layer(conn, ally, enemy, qids),
            _synergy_layer(conn, ally, qids, champ_name_resolver, duo_synergy_lookup),
            _damage_balance_layer(ally, damage_class_resolver),
            _scaling_layer(ally, scaling_resolver),
            _base_wr_layer(conn, ally, qids),
        ]
    except Exception as exc:  # noqa: BLE001 - defense in depth, never raise
        log.warning("draft_score assemble: %s", exc)
        layers = [_layer(n, None, 0) for n in WEIGHTS]
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    fused = fuse_layers(layers)
    fused["ok"] = True
    fused["ally"] = ally
    fused["enemy"] = enemy
    fused["queue_ids"] = list(qids) if qids else None
    fused["min_games"] = MIN_GAMES
    return fused
