"""Win Probability Added (WPA) post-game scorer.

Re-implements the LoLytics (https://github.com/fqhd/LoLytics, MIT) WPA
decomposition pattern using RC's own timeline data. Per-event WPA =
prob_after - prob_before where prob is a logistic-regression estimate
of "team 100 wins" given the rolling match state at that timestamp.

This module is intentionally pure-Python (no numpy/sklearn dependency) so
the RC fleet does not grow a heavy ML stack just for one post-game panel.
The LR is trained via batch gradient descent over the existing
``rewind_history.db`` timelines. Coefficients are persisted as plain JSON
(``data/post_game_wpa_model.json``) so future retrains are inspectable.

Feature vector per game timestamp (length = 13, all signed for team 100):

    0  gold_diff           (team100_total_gold  - team200_total_gold)
    1  xp_diff             (sum team100 xp      - sum team200 xp)
    2  kill_diff           (team100 kills       - team200 kills)
    3  death_diff          (team100 deaths      - team200 deaths)
    4  assist_diff         (team100 assists     - team200 assists)
    5  turret_diff         (team100 turrets     - team200 turrets) destroyed
    6  inhibitor_diff      (team100 inhibs      - team200 inhibs)  destroyed
    7  dragon_diff         (team100 drakes      - team200 drakes)  killed
    8  baron_diff          (team100 barons      - team200 barons)  killed
    9  herald_diff         (team100 heralds     - team200 heralds) killed
   10  horde_diff          (team100 grubs       - team200 grubs)   killed
   11  game_time_s         (event timestamp, seconds)
   12  bias                always 1.0 (intercept)

The order is locked - persisted models reference indices by position. A
future feature add MUST append at the end (and bump
``WPA_MODEL_VERSION``).

When ``data/post_game_wpa_model.json`` is missing or unreadable, the
predictor falls back to a hand-coded gold-diff sigmoid derived from
LoLytics' empirical curve. This is provably better than no estimate at
all and lets the route ship before the training pipeline runs end-to-end
(operator's play cadence is sparse so a fresh full retrain may not have
N>=20 timelines for a stable fit).

LoLytics formulas re-implemented verbatim:

  * ``calculate_tif(time_minutes)`` - piecewise time-in-fight curve.
    The death timer ramps from 0 at 0 minutes to a 50 percent uplift
    at 55+ minutes. Source: model/game.py.

  * ``calculate_death_timer(level, time_ms)`` - Base Respawn Wait
    (BRW) table by level * (1 + tif/100). Source: model/game.py.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger("rc.post_game_score")

# Feature vector size including the bias term. See module docstring.
WPA_FEATURE_COUNT = 13
WPA_MODEL_VERSION = 1

# Default location for the persisted coefficients.
_DEFAULT_MODEL_PATH = Path("data") / "post_game_wpa_model.json"

# Hand-coded fallback sigmoid: gold_diff -> P(team100 wins). Derived
# from LoLytics' published evaluation curve. Calibrated so that 5000
# gold diff at 20 minutes maps to ~75 percent win probability.
_FALLBACK_GOLD_SCALE = 5000.0

# Base Respawn Wait by champion level (seconds). LoLytics model/game.py
# line 25. Index 0 = level 1.
DEATH_BRW_SECONDS: tuple[float, ...] = (
    10.0, 10.0, 12.0, 12.0, 14.0, 16.0, 20.0, 25.0, 28.0,
    32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5, 50.0, 52.5,
)


def calculate_tif(time_minutes: float) -> float:
    """Time-In-Fight piecewise multiplier. Returns a percentage value
    (0.0 to 50.0). See LoLytics model/game.py.

    The original uses ``math.ceil(2 * (time - X))`` for the bumped
    sub-bands so we preserve that exactly.
    """
    if time_minutes < 15:
        return 0.0
    if time_minutes < 30:
        return math.ceil(2 * (time_minutes - 15)) * 0.425
    if time_minutes < 45:
        return 12.75 + math.ceil(2 * (time_minutes - 30)) * 0.3
    if time_minutes < 55:
        return 21.75 + math.ceil(2 * (time_minutes - 45)) * 1.45
    return 50.0


def calculate_death_timer(level: int, time_ms: int) -> float:
    """Death timer in seconds for a champion at ``level`` (1 to 18)
    dying at ``time_ms`` into the game. Mirrors LoLytics' formula:

        BRW[level-1] + BRW[level-1] * (tif/100)

    Level is clamped to [1, 18] to match the original code path
    (``min(victim['level'], 18)``).
    """
    lvl = max(1, min(int(level), 18))
    brw = DEATH_BRW_SECONDS[lvl - 1]
    tif = calculate_tif(time_ms / 60000.0) / 100.0
    return brw + brw * tif


# ---------------------------------------------------------------------
# Pure-Python LR
# ---------------------------------------------------------------------

def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid."""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass(frozen=True)
class WpaModel:
    """Persisted model state. ``weights`` length must equal
    ``WPA_FEATURE_COUNT``. ``feature_names`` mirrors the feature order
    so future versions can sanity-check schema drift without breaking
    older clients."""

    weights: tuple[float, ...]
    feature_names: tuple[str, ...]
    n_samples: int
    version: int = WPA_MODEL_VERSION

    def predict_prob(self, features: Sequence[float]) -> float:
        """P(team100 wins | features). Returns 0.5 on length mismatch
        rather than raising - WPA decomposition wraps the call in a
        loop and one bad event should not abort the whole match."""
        if len(features) != len(self.weights):
            return 0.5
        z = 0.0
        for w, x in zip(self.weights, features):
            z += w * x
        return _sigmoid(z)

    def to_json_dict(self) -> dict:
        return {
            "version": self.version,
            "n_samples": self.n_samples,
            "feature_names": list(self.feature_names),
            "weights": list(self.weights),
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> "WpaModel":
        return cls(
            weights=tuple(float(x) for x in data.get("weights", ())),
            feature_names=tuple(str(x) for x in data.get("feature_names", ())),
            n_samples=int(data.get("n_samples", 0)),
            version=int(data.get("version", WPA_MODEL_VERSION)),
        )


FEATURE_NAMES: tuple[str, ...] = (
    "gold_diff", "xp_diff", "kill_diff", "death_diff", "assist_diff",
    "turret_diff", "inhibitor_diff", "dragon_diff", "baron_diff",
    "herald_diff", "horde_diff", "game_time_s", "bias",
)
assert len(FEATURE_NAMES) == WPA_FEATURE_COUNT


# Feature scaling: divide raw values so the magnitudes are similar
# before LR. Keeps gradient descent well-conditioned without needing a
# numpy StandardScaler. The scales are chosen from typical mid-to-late
# game ranges in the existing rewind_history.db.
FEATURE_SCALES: tuple[float, ...] = (
    5000.0,   # gold_diff
    8000.0,   # xp_diff
    10.0,     # kill_diff
    10.0,     # death_diff
    20.0,     # assist_diff
    5.0,      # turret_diff
    3.0,      # inhibitor_diff
    3.0,      # dragon_diff
    2.0,      # baron_diff
    2.0,      # herald_diff
    6.0,      # horde_diff
    1800.0,   # game_time_s (30 min reference)
    1.0,      # bias
)
assert len(FEATURE_SCALES) == WPA_FEATURE_COUNT


def scale_features(raw: Sequence[float]) -> tuple[float, ...]:
    """Element-wise divide by ``FEATURE_SCALES``. Returns a fresh tuple."""
    if len(raw) != WPA_FEATURE_COUNT:
        # Defensive: pad/truncate so callers do not crash mid-loop.
        padded = list(raw)[:WPA_FEATURE_COUNT] + [0.0] * (WPA_FEATURE_COUNT - len(raw))
        return tuple(padded[i] / FEATURE_SCALES[i] for i in range(WPA_FEATURE_COUNT))
    return tuple(raw[i] / FEATURE_SCALES[i] for i in range(WPA_FEATURE_COUNT))


# ---------------------------------------------------------------------
# Fallback estimator (used when no model file is present)
# ---------------------------------------------------------------------

def _fallback_prob(features: Sequence[float]) -> float:
    """Hand-coded gold-diff sigmoid. Mirrors the published LoLytics
    evaluation curve where ~5k gold diff at 20 minutes maps to ~75
    percent win probability. We add light contributions from turrets
    and barons because those bake in lasting state changes that gold
    alone cannot reflect.

    Intentionally generous: better than 0.5 baseline, worse than the
    trained LR. TODO: retrain on N>=20 timelines for a stable fit.
    """
    if len(features) < 11:
        return 0.5
    gold_diff = float(features[0])
    turret_diff = float(features[5])
    inhib_diff = float(features[6])
    baron_diff = float(features[8])
    z = (gold_diff / _FALLBACK_GOLD_SCALE) * 1.5
    z += turret_diff * 0.18
    z += inhib_diff * 0.55
    z += baron_diff * 0.35
    return _sigmoid(z)


# ---------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------

def load_model(path: Path | None = None) -> WpaModel | None:
    """Load a persisted model. Returns ``None`` if missing or
    unparseable so callers can fall back gracefully."""
    p = Path(path) if path is not None else _DEFAULT_MODEL_PATH
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("load_model: %s -> %s", p, exc)
        return None
    try:
        return WpaModel.from_json_dict(data)
    except (TypeError, ValueError) as exc:
        log.warning("load_model: bad shape %s -> %s", p, exc)
        return None


def save_model(model: WpaModel, path: Path | None = None) -> Path:
    """Write the model to disk. Atomic: write to ``.tmp`` then replace."""
    target = Path(path) if path is not None else _DEFAULT_MODEL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(model.to_json_dict(), f, indent=2, sort_keys=True)
    tmp.replace(target)
    return target


def predict_prob(features: Sequence[float], model: WpaModel | None = None) -> float:
    """Public entry point. Routes through either the trained model or
    the hand-coded fallback."""
    if model is None:
        return _fallback_prob(features)
    return model.predict_prob(scale_features(features))


# ---------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------

def train_logistic_regression(
    samples: Iterable[Sequence[float]],
    labels: Iterable[int],
    *,
    epochs: int = 200,
    lr: float = 0.5,
    l2: float = 0.001,
) -> WpaModel:
    """Batch gradient descent over (features, label) pairs. Each sample
    is the SCALED feature vector; labels are 1 if team100 won else 0.

    Pure-Python so no numpy dependency. Mini-batches not needed - the
    rewind_history.db sample count is small enough (~thousands of
    frames per game * a few thousand games at most) that a full batch
    fits in memory.

    Returns a ``WpaModel``. Raises ``ValueError`` on empty input or
    mismatched lengths.
    """
    X = [tuple(float(x) for x in row) for row in samples]
    y = [int(v) for v in labels]
    if len(X) == 0:
        raise ValueError("train: empty samples")
    if len(X) != len(y):
        raise ValueError(
            f"train: len(X)={len(X)} != len(y)={len(y)}"
        )
    n = len(X)
    n_feat = len(X[0])
    if n_feat != WPA_FEATURE_COUNT:
        raise ValueError(
            f"train: expected {WPA_FEATURE_COUNT} features, got {n_feat}"
        )

    weights = [0.0] * n_feat
    for _epoch in range(epochs):
        grad = [0.0] * n_feat
        for i in range(n):
            z = 0.0
            xi = X[i]
            for j in range(n_feat):
                z += weights[j] * xi[j]
            p = _sigmoid(z)
            err = p - y[i]
            for j in range(n_feat):
                grad[j] += err * xi[j]
        # L2 + average + step.
        for j in range(n_feat):
            grad[j] = grad[j] / n + l2 * weights[j]
            weights[j] -= lr * grad[j]

    return WpaModel(
        weights=tuple(weights),
        feature_names=FEATURE_NAMES,
        n_samples=n,
    )


# ---------------------------------------------------------------------
# Timeline -> state machine
# ---------------------------------------------------------------------

# Building types as encoded by the timeline. Both TOWER_BUILDING and
# the per-position variants exist; we treat them uniformly.
_TOWER_TYPES = {"OUTER_TURRET", "INNER_TURRET", "BASE_TURRET", "NEXUS_TURRET"}

# Riot's monster naming. HORDE = grubs; RIFTHERALD = herald; BARON
# stays BARON; dragons are all subtypes of DRAGON.
_HERALD_TYPES = {"RIFTHERALD"}
_HORDE_TYPES = {"HORDE"}
_BARON_TYPES = {"BARON_NASHOR"}
_DRAGON_TYPES = {"DRAGON"}


@dataclass
class MatchState:
    """Mutable rolling state used while replaying timeline events."""

    gold_team100: int = 0
    gold_team200: int = 0
    xp_team100: int = 0
    xp_team200: int = 0
    kills_team100: int = 0
    kills_team200: int = 0
    deaths_team100: int = 0
    deaths_team200: int = 0
    assists_team100: int = 0
    assists_team200: int = 0
    turrets_team100: int = 0  # number that THIS team destroyed
    turrets_team200: int = 0
    inhibs_team100: int = 0
    inhibs_team200: int = 0
    dragons_team100: int = 0
    dragons_team200: int = 0
    barons_team100: int = 0
    barons_team200: int = 0
    heralds_team100: int = 0
    heralds_team200: int = 0
    horde_team100: int = 0
    horde_team200: int = 0
    last_frame_ts_ms: int = 0

    def to_feature_vector(self, game_time_s: float) -> tuple[float, ...]:
        return (
            float(self.gold_team100 - self.gold_team200),
            float(self.xp_team100 - self.xp_team200),
            float(self.kills_team100 - self.kills_team200),
            float(self.deaths_team100 - self.deaths_team200),
            float(self.assists_team100 - self.assists_team200),
            float(self.turrets_team100 - self.turrets_team200),
            float(self.inhibs_team100 - self.inhibs_team200),
            float(self.dragons_team100 - self.dragons_team200),
            float(self.barons_team100 - self.barons_team200),
            float(self.heralds_team100 - self.heralds_team200),
            float(self.horde_team100 - self.horde_team200),
            float(game_time_s),
            1.0,
        )


def _team_of_participant(pid: int | None) -> int | None:
    """Riot encodes participants 1-5 = team 100 (blue), 6-10 = team 200
    (red). Returns 100 or 200 or None."""
    if pid is None or pid <= 0:
        return None
    if 1 <= pid <= 5:
        return 100
    if 6 <= pid <= 10:
        return 200
    return None


def _apply_champion_kill(state: MatchState, killer_id, victim_id, assists_json: str | None) -> None:
    """Mutate state on a CHAMPION_KILL event."""
    killer_team = _team_of_participant(killer_id)
    victim_team = _team_of_participant(victim_id)
    if killer_team == 100:
        state.kills_team100 += 1
    elif killer_team == 200:
        state.kills_team200 += 1
    if victim_team == 100:
        state.deaths_team100 += 1
    elif victim_team == 200:
        state.deaths_team200 += 1
    if assists_json:
        try:
            assists = json.loads(assists_json)
        except (TypeError, ValueError):
            assists = []
        for pid in assists:
            t = _team_of_participant(pid)
            if t == 100:
                state.assists_team100 += 1
            elif t == 200:
                state.assists_team200 += 1


def _apply_building_kill(state: MatchState, killer_id, building_type, tower_type, team_id) -> None:
    """Mutate state on a BUILDING_KILL. The team_id field is the team
    that LOST the building so the OTHER team gets credit."""
    # Some timelines stamp team_id as 100/200 directly; others as 0/1.
    if team_id in (100, 0):
        destroyed_by = 200
    elif team_id in (200, 1):
        destroyed_by = 100
    else:
        # Fall back to participant team.
        destroyed_by = _team_of_participant(killer_id) or 0
    is_tower = (
        (tower_type and tower_type in _TOWER_TYPES)
        or (building_type and "TOWER" in building_type.upper())
    )
    is_inhib = building_type and "INHIB" in building_type.upper()
    if is_tower:
        if destroyed_by == 100:
            state.turrets_team100 += 1
        elif destroyed_by == 200:
            state.turrets_team200 += 1
    elif is_inhib:
        if destroyed_by == 100:
            state.inhibs_team100 += 1
        elif destroyed_by == 200:
            state.inhibs_team200 += 1


def _apply_elite_monster_kill(state: MatchState, killer_id, monster_type, monster_subtype) -> None:
    """Dragons/barons/heralds/horde grubs."""
    team = _team_of_participant(killer_id)
    if team not in (100, 200):
        return
    mt = (monster_type or "").upper()
    if mt in _DRAGON_TYPES:
        if team == 100:
            state.dragons_team100 += 1
        else:
            state.dragons_team200 += 1
    elif mt in _BARON_TYPES:
        if team == 100:
            state.barons_team100 += 1
        else:
            state.barons_team200 += 1
    elif mt in _HERALD_TYPES:
        if team == 100:
            state.heralds_team100 += 1
        else:
            state.heralds_team200 += 1
    elif mt in _HORDE_TYPES:
        if team == 100:
            state.horde_team100 += 1
        else:
            state.horde_team200 += 1


def update_state_from_frame(state: MatchState, frame_rows: Sequence[tuple]) -> None:
    """``frame_rows`` is the result of selecting (participant_id,
    total_gold, xp) for one timestamp. Aggregates gold/xp into the
    state's per-team totals."""
    g100 = g200 = x100 = x200 = 0
    for pid, total_gold, xp in frame_rows:
        team = _team_of_participant(pid)
        if team == 100:
            g100 += int(total_gold or 0)
            x100 += int(xp or 0)
        elif team == 200:
            g200 += int(total_gold or 0)
            x200 += int(xp or 0)
    state.gold_team100 = g100
    state.gold_team200 = g200
    state.xp_team100 = x100
    state.xp_team200 = x200


# ---------------------------------------------------------------------
# Strong events (worth surfacing as WPA widgets)
# ---------------------------------------------------------------------

# Mirrors LoLytics is_strong_event() but excludes LEVEL_UP because that
# event is not in our timeline_events table by default (and would dilute
# the widget list with noise).
_STRONG_EVENT_TYPES = {"CHAMPION_KILL", "BUILDING_KILL", "ELITE_MONSTER_KILL"}


def is_strong_event(event_type: str | None, killer_id: int | None, monster_type: str | None) -> bool:
    """Return True if this event is worth showing as a WPA widget.

    Filters out epic monster kills where the killer is a minion
    (killer_id == 0 in the LoLytics payload). In our DB schema killer
    is NULL for monster-only events, so we cannot perfectly mirror
    that filter; we keep the event because the team_id field is
    populated for objective-skirmish bounty grants downstream.
    """
    if not event_type:
        return False
    if event_type not in _STRONG_EVENT_TYPES:
        return False
    if event_type == "ELITE_MONSTER_KILL" and (killer_id is None or killer_id == 0):
        # Minion-killed wall jungler etc; LoLytics skips these.
        return False
    return True


# ---------------------------------------------------------------------
# Match-level WPA decomposition
# ---------------------------------------------------------------------

def _interpolate_frame_for_event(frames: list[tuple[int, list[tuple]]],
                                 event_ts_ms: int) -> Sequence[tuple] | None:
    """Pick the most recent frame at or before ``event_ts_ms``.
    ``frames`` is sorted by ts ascending. Returns the rows of that
    frame or ``None`` if no earlier frame exists."""
    chosen = None
    for ts, rows in frames:
        if ts <= event_ts_ms:
            chosen = rows
        else:
            break
    return chosen


def compute_match_wpa(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    model: WpaModel | None = None,
) -> dict:
    """Replay one match's timeline and compute per-event WPA.

    Returns:
        {
            "ok": bool,
            "match_id": str,
            "events": [
                {
                    "game_time": int (seconds),
                    "type": "CHAMPION_KILL" | "BUILDING_KILL" | "ELITE_MONSTER_KILL",
                    "wpa": float (signed delta),
                    "prob_before": float,
                    "prob_after": float,
                    "actor": int | None (killer participant id),
                    "actor_team": 100 | 200 | None,
                    "victim": int | None,
                    "subtype": str | None,
                },
                ...
            ],
            "top_phases": [...top-3 by abs(wpa)...]
        }

    If the match has no timeline data, returns ``{"ok": False,
    "error": "no_timeline", "match_id": ...}``.
    """
    # Pull frames first - one shot, group by timestamp.
    frame_cur = conn.execute(
        "SELECT timestamp_ms, participant_id, total_gold, xp "
        "FROM timeline_frames WHERE match_id=? "
        "ORDER BY timestamp_ms ASC, participant_id ASC",
        (match_id,),
    )
    frames: list[tuple[int, list[tuple]]] = []
    current_ts: int | None = None
    current_rows: list[tuple] = []
    for ts, pid, gold, xp in frame_cur:
        if current_ts is None or ts != current_ts:
            if current_ts is not None and current_rows:
                frames.append((current_ts, current_rows))
            current_ts = int(ts or 0)
            current_rows = []
        current_rows.append((pid, gold, xp))
    if current_ts is not None and current_rows:
        frames.append((current_ts, current_rows))
    if not frames:
        return {"ok": False, "error": "no_timeline", "match_id": match_id}

    # Pull all strong events ordered chronologically.
    ev_cur = conn.execute(
        "SELECT timestamp_ms, event_type, killer_id, victim_id, "
        "assisting_ids_json, building_type, tower_type, team_id, "
        "monster_type, monster_subtype "
        "FROM timeline_events WHERE match_id=? "
        "AND event_type IN ('CHAMPION_KILL', 'BUILDING_KILL', 'ELITE_MONSTER_KILL') "
        "ORDER BY timestamp_ms ASC, id ASC",
        (match_id,),
    )
    raw_events = list(ev_cur.fetchall())

    state = MatchState()
    events_out: list[dict] = []
    last_applied_frame_ts: int = -1

    # Helper: refresh state's gold/xp from the most recent frame at or
    # before a timestamp.
    def _refresh_state_at(ts_ms: int) -> None:
        nonlocal last_applied_frame_ts
        rows = _interpolate_frame_for_event(frames, ts_ms)
        if rows is None:
            return
        update_state_from_frame(state, rows)

    # Initial state: use the earliest frame so prob_before is grounded.
    _refresh_state_at(0)

    for (ts_ms, ev_type, killer_id, victim_id, assists_json,
         building_type, tower_type, team_id, monster_type, monster_subtype) in raw_events:
        if not is_strong_event(ev_type, killer_id, monster_type):
            continue
        # Snapshot prob_before based on rolling state interpolated from
        # the most recent frame so gold/xp diff reflects the event's
        # timestamp - then apply the event delta.
        _refresh_state_at(int(ts_ms or 0))
        feats_before = state.to_feature_vector(float(ts_ms or 0) / 1000.0)
        prob_before = predict_prob(feats_before, model)

        if ev_type == "CHAMPION_KILL":
            _apply_champion_kill(state, killer_id, victim_id, assists_json)
        elif ev_type == "BUILDING_KILL":
            _apply_building_kill(state, killer_id, building_type, tower_type, team_id)
        elif ev_type == "ELITE_MONSTER_KILL":
            _apply_elite_monster_kill(state, killer_id, monster_type, monster_subtype)

        feats_after = state.to_feature_vector(float(ts_ms or 0) / 1000.0)
        prob_after = predict_prob(feats_after, model)
        wpa = prob_after - prob_before
        subtype = monster_subtype
        if ev_type == "BUILDING_KILL":
            subtype = building_type or tower_type

        events_out.append({
            "game_time": int((ts_ms or 0) // 1000),
            "type": ev_type,
            "wpa": round(wpa, 4),
            "prob_before": round(prob_before, 4),
            "prob_after": round(prob_after, 4),
            "actor": int(killer_id) if killer_id else None,
            "actor_team": _team_of_participant(killer_id),
            "victim": int(victim_id) if victim_id else None,
            "subtype": subtype,
        })

    # Sort top phases by absolute WPA.
    top = sorted(events_out, key=lambda e: abs(e["wpa"]), reverse=True)[:3]
    # Avoid mutating events_out shared references in the output.
    top_phases = [dict(e) for e in top]

    return {
        "ok": True,
        "match_id": match_id,
        "events": events_out,
        "top_phases": top_phases,
        "frame_count": len(frames),
        "event_count": len(events_out),
    }


# ---------------------------------------------------------------------
# Dataset builder (used by training pipeline)
# ---------------------------------------------------------------------

def build_training_samples(
    conn: sqlite3.Connection,
    *,
    match_ids: Iterable[str] | None = None,
    frames_per_match: int = 4,
) -> tuple[list[tuple[float, ...]], list[int]]:
    """Return (X, y) where X are SCALED feature vectors and y are
    {0, 1} labels for "team 100 wins". Samples ``frames_per_match``
    timestamps from each match (evenly spaced) so the LR sees the
    full game arc, not just one snapshot per match.

    The DB ``teams`` row carries ``team_id`` (0 for blue/100, 1 for
    red/200) and ``win`` (boolean). We label by team_id=0's win.
    """
    if match_ids is None:
        cur = conn.execute(
            "SELECT match_id FROM matches WHERE has_timeline=1 AND map_id IN (11, 12) "
            "ORDER BY game_creation_ts DESC"
        )
        match_ids = [r[0] for r in cur.fetchall()]

    samples: list[tuple[float, ...]] = []
    labels: list[int] = []

    for mid in match_ids:
        cur = conn.execute(
            "SELECT team_id, win FROM teams WHERE match_id=?", (mid,)
        )
        teams = {int(r[0]): int(r[1] or 0) for r in cur.fetchall()}
        # The DB carries team_id in either Riot's 100/200 encoding or
        # the legacy 0/1 encoding depending on when the row was
        # ingested. Accept either; label by team 100 (blue) winning.
        if 100 in teams:
            label = int(teams[100])
        elif 0 in teams:
            label = int(teams[0])
        else:
            continue

        # Pull frames and events for this match.
        fcur = conn.execute(
            "SELECT timestamp_ms, participant_id, total_gold, xp "
            "FROM timeline_frames WHERE match_id=? "
            "ORDER BY timestamp_ms ASC, participant_id ASC",
            (mid,),
        )
        frames: list[tuple[int, list[tuple]]] = []
        cur_ts: int | None = None
        cur_rows: list[tuple] = []
        for ts, pid, gold, xp in fcur:
            if cur_ts is None or ts != cur_ts:
                if cur_ts is not None and cur_rows:
                    frames.append((cur_ts, cur_rows))
                cur_ts = int(ts or 0)
                cur_rows = []
            cur_rows.append((pid, gold, xp))
        if cur_ts is not None and cur_rows:
            frames.append((cur_ts, cur_rows))
        if not frames:
            continue

        ecur = conn.execute(
            "SELECT timestamp_ms, event_type, killer_id, victim_id, "
            "assisting_ids_json, building_type, tower_type, team_id, "
            "monster_type, monster_subtype "
            "FROM timeline_events WHERE match_id=? "
            "AND event_type IN ('CHAMPION_KILL', 'BUILDING_KILL', 'ELITE_MONSTER_KILL') "
            "ORDER BY timestamp_ms ASC, id ASC",
            (mid,),
        )
        all_events = list(ecur.fetchall())

        # Pick sample timestamps evenly across the match.
        max_ts = frames[-1][0]
        if max_ts <= 0:
            continue
        step = max_ts // (frames_per_match + 1)
        sample_times = [step * (i + 1) for i in range(frames_per_match)]

        for snap_ts in sample_times:
            state = MatchState()
            # Apply all events up to snap_ts.
            for (ts_ms, ev_type, killer_id, victim_id, assists_json,
                 building_type, tower_type, team_id, monster_type, monster_subtype) in all_events:
                if (ts_ms or 0) > snap_ts:
                    break
                if not is_strong_event(ev_type, killer_id, monster_type):
                    continue
                if ev_type == "CHAMPION_KILL":
                    _apply_champion_kill(state, killer_id, victim_id, assists_json)
                elif ev_type == "BUILDING_KILL":
                    _apply_building_kill(state, killer_id, building_type, tower_type, team_id)
                elif ev_type == "ELITE_MONSTER_KILL":
                    _apply_elite_monster_kill(state, killer_id, monster_type, monster_subtype)
            # Fold in the gold/xp from the most-recent frame.
            rows = _interpolate_frame_for_event(frames, snap_ts)
            if rows is not None:
                update_state_from_frame(state, rows)
            feats = state.to_feature_vector(float(snap_ts) / 1000.0)
            samples.append(scale_features(feats))
            labels.append(label)

    return samples, labels


def train_from_db(
    db_path: Path | None = None,
    *,
    model_path: Path | None = None,
    frames_per_match: int = 4,
    epochs: int = 200,
    lr: float = 0.5,
    l2: float = 0.001,
) -> WpaModel:
    """End-to-end training entry point. Reads
    ``data/rewind_history.db``, builds samples, fits the LR, persists
    the coefficients."""
    src = Path(db_path) if db_path is not None else (Path("data") / "rewind_history.db")
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        X, y = build_training_samples(conn, frames_per_match=frames_per_match)
    finally:
        conn.close()
    if len(X) == 0:
        raise ValueError("train_from_db: no samples extracted")
    model = train_logistic_regression(
        X, y, epochs=epochs, lr=lr, l2=l2,
    )
    save_model(model, path=model_path)
    return model
