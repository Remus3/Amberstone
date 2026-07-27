"""Deterministic lead-projection generator for live coaching.

Precomputes a macro "you are ahead / even / behind + what to do" directive from
a game-state diff WITHOUT a Claude Haiku call. Pure, diff-driven, fail-soft.

WHY this exists: the live coach path otherwise pays a Haiku call to restate the
obvious macro read ("you are behind, farm safe"). That read is a deterministic
function of a few always-present signals (game time, my CS, my gold, my level,
my KDA), so it can be precomputed locally at zero latency / zero spend. This
module is the projection logic only; a later wave wires it into the state
builder. Nothing here touches the network, an LLM, or the DS engine.

SIGNAL AVAILABILITY (what is ACTUALLY in the game-state dict at request time,
verified against coach_integration/_coach.py + coaches/aram_coach.py):
  - game_time_s / game_seconds : float seconds since game start (always present)
  - cs                         : int creep score (always present)
  - gold                       : int current gold on-hand (always present)
  - level                      : int champion level (always present)
  - kda                        : str "K/D/A" e.g. "5/2/3" (always present)
RC does NOT reliably carry the ENEMY laner's exact gold/cs, nor discrete
ally_kills / enemy_kills / cs_per_min fields, at live request time. So the
verdict is built from MY-side-vs-expected-benchmark deltas plus a personal
kill-participation proxy parsed from the kda string. This is the honest signal
set; the per-minute benchmarks below are the "expected" baseline a solo player
of average standing would hit, and the deltas against them stand in for the
laner gap RC cannot directly observe.

All benchmark numbers are HEURISTIC, operator-tunable constants. Bases:
  - Solo-lane CS benchmark ~8 cs/min is the canonical "good laner" reference
    (roughly 1 wave/min of perfect last-hits = ~6-7 melee/caster, plus jungle
    camps / extra waves push a strong solo laner toward ~8). Coaching tools and
    the wider community treat ~8 cs/min as the solo-lane competence bar.
  - Gold ~ a flat passive trickle (~20.4 gold/sec base income after the first
    ~110s, i.e. ~1.2k/min) plus CS gold (~21 gold/minion average). The combined
    "expected gold at minute M" benchmark below folds both into one per-minute
    rate; it is deliberately coarse because RC reads CURRENT (on-hand, post-buy)
    gold, not total earned, so the gold signal is the weakest of the three and
    is down-weighted.
  - Level: a solo laner is ~ level 1 + (minutes * a per-minute level rate); the
    ~0.5 levels/min benchmark lands a fed solo laner near 6 at ~10 min, 11 at
    ~20 min, matching the standard XP curve closely enough for a coarse verdict.
ARAM has no last-hit denial and shared XP, so CS-vs-expected is meaningless
there; the ARAM weighting drops CS to zero and leans on level + KDA + time.
Arena (2v2v2v2, round-based, fixed partner) has no lane and no minions at all,
so it rides the same no-CS treatment - see the ARENA row in _WEIGHTS and the
Arena directive table.
"""

from __future__ import annotations

from typing import Dict

# --- operator-tunable benchmark constants (heuristic; bases cited in module
#     docstring). All are "expected value at minute M" per-minute rates. ---

# Solo-lane CS competence bar (canonical ~8 cs/min good-laner reference).
_CS_PER_MIN_BENCHMARK_SR: float = 8.0
# No-lane benchmark (ARAM + Arena). Informational only: the CS weight is zeroed
# for those modes, so the exact value never feeds the verdict. It stays wired to
# the benchmark selection anyway so a future nonzero CS weight cannot silently
# inherit the SR bar. See _NO_LANE_CS_MODES.
_CS_PER_MIN_BENCHMARK_ARAM: float = 0.0

# Expected CURRENT gold benchmark per minute. Coarse - RC reads on-hand gold
# (post-buy), so a player who just spent reads "behind" on this axis; hence the
# gold weight is the smallest of the three (see _WEIGHTS).
_GOLD_PER_MIN_BENCHMARK: float = 350.0

# Expected level: 1 + minutes * this rate. ~0.5/min lands ~6 at 10min, ~11 at
# 20min, tracking the standard solo XP curve closely enough for a coarse read.
_LEVEL_PER_MIN_BENCHMARK: float = 0.5
_LEVEL_BASE: float = 1.0

# Phase boundaries in seconds (early < 10min, mid 10-25min, late 25min+).
_EARLY_MAX_S: float = 600.0
_MID_MAX_S: float = 1500.0

# Composite-score thresholds. The composite is a signed, roughly-normalized
# blend of the per-axis ratios (each ratio is (actual - expected) / expected,
# so 0.0 == exactly on benchmark, +0.25 == 25% ahead, -0.25 == 25% behind).
# State bands:
_STATE_EVEN_BAND: float = 0.10   # |score| < this -> "even"
# Magnitude bands (on |score|):
_MAG_SLIGHT_MAX: float = 0.20    # |score| < this (and >= even band) -> slight
_MAG_CLEAR_MAX: float = 0.40     # |score| < this -> clear; >= this -> large

# Per-axis blend weights per mode. Sum is normalized at use-time so the
# composite stays in roughly the same scale regardless of which axes are live.
_WEIGHTS: Dict[str, Dict[str, float]] = {
    # SR: CS is the strongest laner-gap proxy RC can see; level next; gold is
    # noisy (on-hand) so it is down-weighted; personal KDA is a real but
    # spiky signal so it is moderate.
    "SR": {"cs": 0.40, "level": 0.25, "gold": 0.10, "kda": 0.25},
    # ARAM: no CS denial + shared XP, so CS is zeroed and the read leans on
    # level (item/XP tempo), KDA (the dominant ARAM signal - it is a teamfight
    # brawl), and gold.
    "ARAM": {"cs": 0.0, "level": 0.30, "gold": 0.20, "kda": 0.50},
    # ARENA: DERIVED from the ARAM profile, not invented. ARAM is the closest
    # analogue RC already models - no lane, no last-hit denial, no wave, and a
    # verdict that leans on level tempo + a personal kill proxy. Arena adds a
    # partner but keeps every one of those properties, so the ARAM per-axis
    # split carries over unchanged; ARAM's cs weight is ALREADY 0.0, so zeroing
    # CS for Arena needs no redistribution and the weight mass stays 1.00,
    # identical to SR and ARAM. WHY this row has to exist at all: without it
    # ARENA fell through to the SR profile, whose heaviest axis is cs=0.40 -
    # and Arena has no lane CS whatsoever, so every Arena player carried a
    # permanent -0.40 drag and a fed player was coached as if losing.
    "ARENA": {"cs": 0.0, "level": 0.30, "gold": 0.20, "kda": 0.50},
}
# Modes without a bespoke weight table fall back to the SR profile.
_DEFAULT_MODE = "SR"

# Modes with no lane CS at all. WHY a set and not an equality test: the CS
# benchmark and the CS weight have to agree per mode, and a bare
# `mode != "ARAM"` silently handed every future no-lane mode the SR
# 8-cs-per-min bar (that is exactly how ARENA broke).
_NO_LANE_CS_MODES = frozenset({"ARAM", "ARENA"})

# Directive lines, keyed (state, phase). Magnitude selects within the tuple:
# index 0 = slight, 1 = clear, 2 = large. All lines are <= 10 words, ASCII.
# WHY phase-keyed: the right macro action shifts with game stage - an early
# lead means press/deny, a late lead means close on objectives; an early
# deficit means farm safe, a late deficit means group and avoid picks.
_LINES: Dict[str, Dict[str, tuple]] = {
    "ahead": {
        "early": (
            "Slight lead: keep last-hitting, deny enemy CS.",
            "Clear lead: press, zone enemy off farm.",
            "Big lead: dive or roam, snowball it now.",
        ),
        "mid": (
            "Slight lead: take prio, ward deep, track jungler.",
            "Clear lead: force objectives with your tempo.",
            "Big lead: group, force fights, close the map.",
        ),
        "late": (
            "Slight lead: play around the next objective.",
            "Clear lead: group as five, take baron.",
            "Big lead: force the end, end the game.",
        ),
    },
    "even": {
        "early": (
            "Even: farm cleanly, trade only on cooldowns.",
            "Even: trade for prio, track the jungler.",
            "Even: contest scuttle, set up first objective.",
        ),
        "mid": (
            "Even: match waves, ward, take safe objectives.",
            "Even: trade for prio before objective spawns.",
            "Even: group for objectives, avoid coinflips.",
        ),
        "late": (
            "Even: hold position, wait for a pick.",
            "Even: group, control vision near objective.",
            "Even: do not throw, play for one pick.",
        ),
    },
    "behind": {
        "early": (
            "Behind: farm safe under tower, scale up.",
            "Behind: freeze or farm safe, avoid trades.",
            "Behind: give up CS if needed, just survive.",
        ),
        "mid": (
            "Behind: catch side waves, avoid risky fights.",
            "Behind: scale, only fight with your team.",
            "Behind: farm safe, do not get caught.",
        ),
        "late": (
            "Behind: stay with team, wait for picks.",
            "Behind: defend, do not face-check, scale.",
            "Behind: only fight on enemy mistakes.",
        ),
    },
}

# Arena directives. Same (state, phase) keying and same 3-tuple
# slight/clear/large shape as _LINES - only the vocabulary changes. WHY a
# parallel table instead of new keys inside _LINES: every consumer of _LINES
# reads it as state -> phase -> tuple, so the shape is load-bearing. Arena is
# 2v2v2v2 round-based combat with a fixed partner: there is no minion to
# last-hit, no wave to freeze, no tower to farm under, no jungler and no baron,
# so every SR line that named one of those had no referent here.
_ARENA_LINES: Dict[str, Dict[str, tuple]] = {
    "ahead": {
        "early": (
            "Slight lead: play with your partner, take even fights.",
            "Clear lead: pressure them, take fights while ahead.",
            "Big lead: open every round, snowball your gold.",
        ),
        "mid": (
            "Slight lead: pick the weaker duo, fight together.",
            "Clear lead: open on their carry with your partner.",
            "Big lead: burst their carry, close rounds fast.",
        ),
        "late": (
            "Slight lead: hold cooldowns for the final duo.",
            "Clear lead: engage first, your partner follows up.",
            "Big lead: end rounds before the ring closes in.",
        ),
    },
    "even": {
        "early": (
            "Even: take safe augments, respect their cooldowns.",
            "Even: trade cooldowns, reset before the ring closes.",
            "Even: fight beside your partner, never alone.",
        ),
        "mid": (
            "Even: focus one target with your partner.",
            "Even: save escapes, avoid the closing ring.",
            "Even: hold ultimates until their engage is spent.",
        ),
        "late": (
            "Even: play the round out, punish their mistake.",
            "Even: burst the squishier enemy together, then reset.",
            "Even: do not overextend into the ring.",
        ),
    },
    "behind": {
        "early": (
            "Behind: buy defensively, survive the early rounds.",
            "Behind: peel for your partner, avoid long fights.",
            "Behind: take the safer augment, stall for scaling.",
        ),
        "mid": (
            "Behind: stay with your partner, never fight alone.",
            "Behind: scale, only fight beside your partner.",
            "Behind: kite the ring, stall the round out.",
        ),
        "late": (
            "Behind: disengage, look for one clean pick.",
            "Behind: defend your partner, do not chase.",
            "Behind: only fight when they misstep first.",
        ),
    },
}

# Per-mode directive table. A mode absent here reads the shared _LINES.
_LINES_BY_MODE: Dict[str, Dict[str, Dict[str, tuple]]] = {"ARENA": _ARENA_LINES}

_GENERIC_LINE = "Play to your strengths, farm and scale."
_SOURCE_TAG = "lead-proj"


def _phase(game_time_s: float) -> str:
    """Map elapsed seconds to a coarse game phase string. WHY: directives
    differ by stage; see _LINES."""
    if game_time_s < _EARLY_MAX_S:
        return "early"
    if game_time_s < _MID_MAX_S:
        return "mid"
    return "late"


def phase_for(game_time_s: object) -> str:
    """Public early/mid/late phase classifier for ``game_time_s``.

    Thin public wrapper over the internal ``_phase`` so other modules (the RC2
    P5.5 objective playbook) share the SAME phase boundaries instead of
    re-deriving them. Fail-soft: a non-numeric / negative input -> 'early'."""
    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        return "early"
    if gt < 0:
        gt = 0.0
    return _phase(gt)


def _kda_ratio(kda: object) -> float:
    """Parse a "K/D/A" string into a signed personal kill-participation proxy
    in roughly [-1, +1]. WHY: RC has no reliable team-kill diff at request
    time, so a solo player's own (kills + assists) vs deaths is the only kill
    signal available. We return a ratio-style number, not a raw KDA, so it
    composes with the per-minute deltas. Fail-soft: anything unparseable -> 0.0
    (neutral, never raises)."""
    if not isinstance(kda, str):
        return 0.0
    parts = kda.split("/")
    if len(parts) != 3:
        return 0.0
    try:
        k = int(parts[0].strip())
        d = int(parts[1].strip())
        a = int(parts[2].strip())
    except (ValueError, AttributeError):
        return 0.0
    takedowns = k + a
    # Even baseline: takedowns ~= deaths. Map the gap to a bounded ratio. With
    # no deaths, a few takedowns reads clearly ahead; with deaths and no
    # takedowns, clearly behind. The +1 floors avoid div-by-zero and damp the
    # very-early-game (0/0/0) case toward neutral.
    score = (takedowns - d) / (takedowns + d + 1.0)
    # Clamp to [-1, 1] defensively.
    if score > 1.0:
        return 1.0
    if score < -1.0:
        return -1.0
    return score


def _ratio(actual: float, expected: float) -> float:
    """(actual - expected) / expected, clamped to [-1, 1]. WHY: a normalized
    signed delta so each axis contributes on the same scale to the composite.
    expected <= 0 -> axis contributes 0.0 (e.g. ARAM CS benchmark is 0)."""
    if expected <= 0:
        return 0.0
    r = (actual - expected) / expected
    if r > 1.0:
        return 1.0
    if r < -1.0:
        return -1.0
    return r


def project_lead(game_state: dict, *, mode: str = "SR") -> dict:
    """Deterministic macro lead projection.

    Returns a dict with EXACTLY these 4 keys:
      state       : one of "ahead" / "even" / "behind" (exhaustive)
      magnitude   : one of "slight" / "clear" / "large"
      line        : short (<= 10 words) ASCII macro directive
      source_tag  : always "lead-proj"

    Pure + fail-soft: missing/garbage fields default to a neutral "even" verdict
    with a generic line; never raises.
    """
    # Fail-soft front door: a non-dict input yields the neutral verdict.
    if not isinstance(game_state, dict):
        return {
            "state": "even",
            "magnitude": "slight",
            "line": _GENERIC_LINE,
            "source_tag": _SOURCE_TAG,
        }

    mode_key = (mode or _DEFAULT_MODE).upper()
    weights = _WEIGHTS.get(mode_key, _WEIGHTS[_DEFAULT_MODE])

    # --- pull signals defensively. game_time_s falls back to game_seconds. ---
    def _num(*keys: str, default: float = 0.0) -> float:
        for key in keys:
            val = game_state.get(key)
            if isinstance(val, bool):  # bool is an int subclass; reject it
                continue
            if isinstance(val, (int, float)):
                return float(val)
        return default

    game_time_s = _num("game_time_s", "game_seconds", default=0.0)
    if game_time_s < 0:
        game_time_s = 0.0
    minutes = game_time_s / 60.0

    cs = _num("cs", default=0.0)
    gold = _num("gold", default=0.0)
    level = _num("level", default=_LEVEL_BASE)
    kda_proxy = _kda_ratio(game_state.get("kda"))

    # --- per-axis expected benchmarks at this minute ---
    cs_bench = (
        _CS_PER_MIN_BENCHMARK_ARAM if mode_key in _NO_LANE_CS_MODES
        else _CS_PER_MIN_BENCHMARK_SR
    ) * minutes
    gold_bench = _GOLD_PER_MIN_BENCHMARK * minutes
    level_bench = _LEVEL_BASE + (_LEVEL_PER_MIN_BENCHMARK * minutes)

    # --- per-axis normalized signed deltas ---
    cs_sig = _ratio(cs, cs_bench)
    gold_sig = _ratio(gold, gold_bench)
    level_sig = _ratio(level, level_bench)
    kda_sig = kda_proxy  # already a bounded signed ratio

    # --- weighted composite, normalized by the live weight mass so the score
    #     stays in roughly [-1, 1] regardless of which axes are active. ---
    contribs = {
        "cs": (cs_sig, weights.get("cs", 0.0)),
        "gold": (gold_sig, weights.get("gold", 0.0)),
        "level": (level_sig, weights.get("level", 0.0)),
        "kda": (kda_sig, weights.get("kda", 0.0)),
    }
    weight_mass = sum(w for _, w in contribs.values())
    if weight_mass <= 0:
        composite = 0.0
    else:
        composite = sum(sig * w for sig, w in contribs.values()) / weight_mass

    # --- classify state (exhaustive) ---
    if composite > _STATE_EVEN_BAND:
        state = "ahead"
    elif composite < -_STATE_EVEN_BAND:
        state = "behind"
    else:
        state = "even"

    # --- magnitude from |composite| ---
    mag_abs = abs(composite)
    if mag_abs < _MAG_SLIGHT_MAX:
        magnitude = "slight"
    elif mag_abs < _MAG_CLEAR_MAX:
        magnitude = "clear"
    else:
        magnitude = "large"

    # --- directive line (state x phase x magnitude) ---
    phase = _phase(game_time_s)
    mag_idx = {"slight": 0, "clear": 1, "large": 2}[magnitude]
    lines = _LINES_BY_MODE.get(mode_key, _LINES)
    line = lines.get(state, {}).get(phase, (_GENERIC_LINE,) * 3)[mag_idx]

    return {
        "state": state,
        "magnitude": magnitude,
        "line": line,
        "source_tag": _SOURCE_TAG,
    }


# --------------------------------------------------------------------------- #
# HZ-A2: gold-income + power-spike model
# (reused by core.laning_scenario_precompute for recall/back-timing + spike-ETA)
# --------------------------------------------------------------------------- #
# Distinct from _GOLD_PER_MIN_BENCHMARK (on-hand, post-buy - the project_lead
# signal): this is expected GROSS gold EARNED per minute, used to project WHEN a
# player can afford their next item / power spike. Coarse + operator-tunable.
# ARAM out-earns SR (no recall downtime, constant minion flow + the ARAM gold
# passive); unknown modes fall back to the SR rate.
_GOLD_EARNED_PER_MIN: Dict[str, float] = {"SR": 450.0, "ARAM": 600.0}
_DEFAULT_GOLD_EARNED_PER_MIN: float = 450.0

# Cumulative-gold power-spike ladder: (label, gold earned). A spike is "reached"
# once cumulative gross earned gold >= its threshold. Heuristic component /
# completed-item gold landmarks (a Mythic-tier first item ~3k, two-item ~6.2k,
# three-item ~9.4k); tunable. SPIKE_COMPLETE caps the ladder.
_SPIKE_LADDER: tuple = (
    ("component", 1100.0),
    ("first_item", 3000.0),
    ("two_item", 6200.0),
    ("three_item", 9400.0),
)
SPIKE_COMPLETE: str = "complete"


def minutes_for_level(level: float) -> float:
    """Expected game-minute a solo laner reaches ``level`` - the inverse of the
    project_lead level benchmark (level = _LEVEL_BASE + rate * minutes). Bridges a
    discrete level band (L2/L6/L11/L16) to a game-time so the gold/spike model and
    project_lead ride one curve. Fail-soft: a level <= base (or a non-positive
    rate) -> 0.0 (never negative)."""
    if _LEVEL_PER_MIN_BENCHMARK <= 0:
        return 0.0
    m = (float(level) - _LEVEL_BASE) / _LEVEL_PER_MIN_BENCHMARK
    return m if m > 0.0 else 0.0


def gold_income_per_min(mode: str = "SR") -> float:
    """Benchmark GROSS gold earned per minute for ``mode`` (SR default; an
    unknown mode falls back to the SR rate)."""
    return _GOLD_EARNED_PER_MIN.get(
        (mode or _DEFAULT_MODE).upper(), _DEFAULT_GOLD_EARNED_PER_MIN
    )


def expected_gold_earned(minutes: float, mode: str = "SR") -> float:
    """Cumulative gross gold earned by ``minutes`` at the benchmark income rate.
    Negative minutes clamp to 0.0."""
    m = float(minutes)
    if m < 0.0:
        m = 0.0
    return gold_income_per_min(mode) * m


def spike_ladder() -> list:
    """Public copy of the cumulative-gold spike ladder as ``[[label, target], ...]``
    (a list-of-lists so it serializes to JSON cleanly)."""
    return [[label, float(target)] for label, target in _SPIKE_LADDER]


def spike_threshold(label: str) -> float:
    """Cumulative gold for a named spike ``label`` (0.0 if unknown)."""
    for lbl, target in _SPIKE_LADDER:
        if lbl == label:
            return float(target)
    return 0.0


def next_spike(gold_earned: float) -> tuple:
    """The first ladder spike not yet reached: ``(label, target_gold)``. Once
    every ladder entry is reached, returns ``(SPIKE_COMPLETE, last_threshold)``."""
    g = float(gold_earned)
    for label, target in _SPIKE_LADDER:
        if g < target:
            return label, float(target)
    return SPIKE_COMPLETE, float(_SPIKE_LADDER[-1][1])


def spike_eta_seconds(
    gold_earned: float, target_gold: float, mode: str = "SR"
) -> float:
    """Seconds to earn from ``gold_earned`` up to ``target_gold`` at the benchmark
    income rate. 0.0 when already at/past the target or the rate is non-positive."""
    remaining = float(target_gold) - float(gold_earned)
    if remaining <= 0.0:
        return 0.0
    rate_per_min = gold_income_per_min(mode)
    if rate_per_min <= 0.0:
        return 0.0
    return (remaining / rate_per_min) * 60.0
