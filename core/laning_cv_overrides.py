# arch: RC2-P5.1 CV-driven laning verdict overrides (vision_state) | section=core | frozen=no
"""RC2 Phase 5.1 - local-CV laning overrides over the fog model.

PURPOSE
    Workstream 1 step 2 of docs/research/RC2_COACHING_SPEC.md. The precomputed
    laning band (``core.precomputed_laning_coach.laning_band``) answers the
    STATIC "trade / hold / back off" matchup question, but the single most
    common REAL laning decision is dynamic and fully observable from local CV
    without any LLM: the enemy laner is DEAD (free shove), or MISSING (back off
    + ward), or my own HP is too low to take the trade the table recommends. RC
    already derives all three from data it writes every tick:
      * ``data/vision_state.json``  (``core.vision_tracker`` fog model: per-enemy
        is_dead / respawn_in_s / visible / missing_for_s / last_seen_zone)
      * the Live Client hp / hp_max (my hp_fraction)

    This module is the PURE decision layer (spec 1.2 pipeline, layers 1-3) that
    turns those reads into an override verdict + a confidence band, or ``None``
    when CV adds nothing over the static table verdict. It reads NO network and
    NO LLM; the impure ``vision_state.json`` read is a thin fail-soft loader kept
    here (mirrors ``core.decision_detector._read_vision_state``) so the dashboard
    resolver can pass a preloaded dict in tests.

SHADOW-FIRST (charter 4b "do not flip blind")
    Like the WS1 step-1 hold-band (commit 4da01fbe), this ships SHADOW-ONLY: the
    override rides the ``data/hz_choice_shadow.jsonl`` record (a new
    ``cv_override`` column) so ``tools/hz_shadow_report`` can re-measure
    det-vs-Haiku agreement WITH the CV layer applied, on the same live games,
    BEFORE any served chip changes. The served-output flip is operator/Gemini
    gated (``docs/LIVE_GAME_GATED_SYNC.md``), never a blind overnight flip.

FAIL-SOFT
    A missing/malformed vision_state, an enemy the fog model does not list, or
    any bad scalar yields ``None`` (no override) - the caller keeps the static
    band. Never raises (the coach hot path contract).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.archetype_picks import canonical_champion_id

_APP_DIR = Path(__file__).parent.parent
_VISION_STATE_PATH: Path = _APP_DIR / "data" / "vision_state.json"

# An enemy un-seen for at least this many seconds counts as MISSING (spec 1.2
# layer 2). Mirrors the laning sense of "gone long enough to be a gank threat".
MISS_THRESHOLD_S: float = 3.0

# At/under this fraction of my max HP an aggressive static verdict is overridden
# to a disengage (spec 1.2 layer 3). Conservative - only the costly-if-wrong
# all-in / trade verdicts are flipped; hold / even / back_off are already safe.
LOW_HP_FRACTION: float = 0.35

# The static verdicts a low-HP read should veto (the only case worth paying to
# be cautious about). hold / even / back_off are passive already.
_AGGRESSIVE_VERDICTS: frozenset[str] = frozenset({"all_in", "trade"})


def load_vision_state(path: Optional[Path] = None) -> dict:
    """Fail-soft read of the fog model JSON (``{}`` on any error).

    Mirrors ``core.decision_detector._read_vision_state``. ``path`` overrides the
    live ``data/vision_state.json`` (test seam)."""
    target = path if path is not None else _VISION_STATE_PATH
    try:
        data = json.loads(Path(target).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - hot path must never raise
        return {}


def enemy_cv_status(vision_state: object, enemy_name: object) -> dict:
    """Normalized fog status for ``enemy_name``, or ``{}`` when unlisted.

    Matches on the canonical champion id (so a display name "Tahm Kench" finds a
    fog entry keyed "TahmKench"). Returns only the fields the override pipeline
    reads. Fail-soft ``{}`` on any malformed input."""
    if not isinstance(vision_state, dict) or not enemy_name:
        return {}
    enemies = vision_state.get("enemies")
    if not isinstance(enemies, dict):
        return {}
    try:
        want = canonical_champion_id(str(enemy_name))
    except Exception:  # noqa: BLE001
        return {}
    for key, val in enemies.items():
        if not isinstance(val, dict):
            continue
        champ = val.get("champion") or key
        try:
            if canonical_champion_id(str(champ)) != want:
                continue
        except Exception:  # noqa: BLE001
            continue
        return {
            "is_dead": bool(val.get("is_dead")),
            "respawn_in_s": val.get("respawn_in_s"),
            "visible": val.get("visible"),
            "missing_for_s": val.get("missing_for_s"),
            "last_seen_zone": val.get("last_seen_zone"),
        }
    return {}


def _as_float(value: object) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def cv_override(enemy_status: object, hp_fraction: object,
                base_verdict: object) -> Optional[dict]:
    """The pure spec-1.2 layer-1/2/3 decision, or ``None`` (no override).

    Precedence (first match wins): enemy DEAD (and not already respawning) ->
    shove; enemy MISSING >= MISS_THRESHOLD_S -> back off; my HP below
    LOW_HP_FRACTION while the static verdict is aggressive -> disengage. The
    low-HP layer reads MY state, so it fires even with an empty ``enemy_status``.
    Returns ``{verdict, confidence, reason, kind}``."""
    status = enemy_status if isinstance(enemy_status, dict) else {}

    # Layer 1 - enemy dead -> free shove (high confidence).
    if status.get("is_dead"):
        respawn = _as_float(status.get("respawn_in_s"))
        if respawn is None or respawn > 0:
            if respawn is None:
                reason = "Enemy dead - shove + take plates/prio"
            else:
                reason = f"Enemy dead {int(round(respawn))}s - shove + take plates/prio"
            return {
                "verdict": "shove", "confidence": "high",
                "reason": reason, "kind": "enemy_dead",
            }

    # Layer 2 - enemy missing long enough to be a gank threat (mid confidence).
    if status.get("visible") is False:
        missing = _as_float(status.get("missing_for_s"))
        if missing is not None and missing >= MISS_THRESHOLD_S:
            return {
                "verdict": "back_off", "confidence": "mid",
                "reason": (
                    f"Enemy missing {int(round(missing))}s - "
                    "back off, ward, do not overextend"
                ),
                "kind": "enemy_missing",
            }

    # Layer 3 - my HP too low to take an aggressive static verdict.
    hp = _as_float(hp_fraction)
    verdict = str(base_verdict or "")
    if hp is not None and hp < LOW_HP_FRACTION and verdict in _AGGRESSIVE_VERDICTS:
        return {
            "verdict": "disengage", "confidence": "high",
            "reason": "Low HP - disengage, do not take this trade",
            "kind": "low_hp",
        }

    return None


def resolve_cv_override(
    enemy_name: object,
    hp_fraction: object,
    base_verdict: object,
    *,
    vision_state: Optional[dict] = None,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Glue: load (or accept) the fog model, look the enemy up, apply the
    override pipeline. ``vision_state`` overrides the file read (test seam);
    ``path`` overrides the live JSON path. Fail-soft ``None`` on any error."""
    try:
        vs = vision_state if vision_state is not None else load_vision_state(path)
        status = enemy_cv_status(vs, enemy_name)
        return cv_override(status, hp_fraction, base_verdict)
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


__all__ = [
    "MISS_THRESHOLD_S",
    "LOW_HP_FRACTION",
    "load_vision_state",
    "enemy_cv_status",
    "cv_override",
    "resolve_cv_override",
]
