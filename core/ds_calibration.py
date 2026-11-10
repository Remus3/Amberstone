"""Append-only DS pick calibration log.

Called from coaches after their DS dispatch returns rows, so each such coaching
tick (~30s cadence) produces one entry in data/ds_calibration.jsonl. The
consumer, core/ds_calibration_agreement.py (run by
tools/ds_calibration_report.py), joins the log against rewind_history.db
EXACTLY on the Riot game id (``game_id``, else a ``live_<gameId>``
``match_key``) to compare DS-recommended items vs. actually purchased items vs.
win/loss outcome; it takes the earliest tick that recommended each unowned
item, per (game, item, scorer). Non-fatal: any write failure is silently
swallowed so calibration logging never breaks coach operation.

Size cap (S144-Q-123, RM-718 residue): the file grew without bound (measured
2026-11-10: 7.2 MB, 10,469 rows over three months of play). Before an append
the writer rotates it through core.log_rotation once it is at or over
_MAX_BYTES, keeping _BACKUP_COUNT generations (5 MiB x 3, the RM-718 bound).
The file has readers, so a rotated row is still a row: ``log_generations``
names the chain oldest first, and the agreement reader and the synthetic-row
prune both walk it.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from core import log_rotation

_LOG_PATH = Path(__file__).parent.parent / "data" / "ds_calibration.jsonl"
_MAX_BYTES = log_rotation.DEFAULT_MAX_BYTES
_BACKUP_COUNT = log_rotation.DEFAULT_BACKUP_COUNT
# One coach tick at a time renames or appends, so no tick appends into a file
# another tick is rotating (four coaches call log_ds_run).
_LOG_LOCK = threading.Lock()


def log_generations(path=None) -> list:
    """The calibration log's rotation chain that exists, OLDEST first:
    ``<name>.<_BACKUP_COUNT>`` .. ``<name>.1``, then the base file.

    Only the numbered backups the writer keeps count: a rotation's scratch
    (``.rotating.*`` / ``.dropping.*``) and a recovered orphan
    (``.recovered-*``) are not rows a reader should see twice. ``path``
    defaults to the live log path, read at call time.
    """
    base = Path(_LOG_PATH if path is None else path)
    chain = [base.with_name(f"{base.name}.{i}")
             for i in range(_BACKUP_COUNT, 0, -1)]
    chain.append(base)
    return [p for p in chain if p.is_file()]


def _rotate_if_oversize(path: Path) -> None:
    """Recover a crashed rotation's scratch, then rotate at or over the cap.

    Called under _LOG_LOCK. Never raises: a failing cap must not cost the
    tick its row, so any error leaves the file as it is and the caller
    appends to it.
    """
    try:
        log_rotation.recover_orphans(path, _BACKUP_COUNT)
        log_rotation.rotate_if_oversize(path, _MAX_BYTES, _BACKUP_COUNT)
    except Exception:  # noqa: BLE001 - the row matters more than the cap
        pass

# EnemyStats field -> the fallback dispatch_for_coach uses when it builds the
# DS request (coach_integration/archetype_dispatch.py: target_* default 0.0,
# enemy_*_share default 0.5), so the summary records the values actually sent.
_ENEMY_STATS_FIELDS = (
    ("armor", 0.0), ("mr", 0.0), ("max_hp", 0.0), ("bonus_hp", 0.0),
    ("ad_share", 0.5), ("ap_share", 0.5),
)


def enemy_stats_summary(enemy_stats) -> Optional[dict]:
    """RM-875 item 5: the enemy-stat inputs a calibration row needs to re-run.

    ``enemy_stats`` is a ``coach_integration.enemy_stats.EnemyStats`` (or any
    object with those attributes). ``None`` in, ``None`` out, so a caller with
    no enemy context writes no ``enemy_stats`` key at all.
    """
    if enemy_stats is None:
        return None
    out: dict = {}
    for name, default in _ENEMY_STATS_FIELDS:
        try:
            out[name] = float(getattr(enemy_stats, name, default) or default)
        except (TypeError, ValueError):
            out[name] = default
    return out


def current_engine_version() -> str:
    """The on-disk DS ``ENGINE_VERSION`` (RC's own checkout), "?" if unknown.

    Same lazy-import precedent as the core/*_shadow.py row writers. It names
    the engine RC was deployed with; the :8860 process serves the same version
    unless it has not been restarted since a bump.
    """
    try:
        from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - informational stamp, never fatal
        return "?"
    return str(ENGINE_VERSION)


def log_ds_run(
    champion: str,
    mode: str,
    level: int,
    owned_items: list,
    ds_picks: list,
    game_id: str = "",
    match_key: str = "",
    enemy_stats: Optional[dict] = None,
    augments: Optional[list] = None,
    engine_version: Optional[str] = None,
    apply_mode_modifiers: Optional[bool] = None,
) -> None:
    """Append one DS observation to the calibration log.

    Args:
        champion:    champion name (e.g. "Ahri")
        mode:        coaching mode string (e.g. "ARAM", "SR", "ARENA", "BRAWL")
        level:       current champion level
        owned_items: item IDs currently in inventory (list of str or int)
        ds_picks:    list of dicts with keys item_id, item_name, delta_dps, gold
        game_id:     optional Riot match/game id for exact cross-reference
        match_key:   stable per-match key from ``core.live_metrics.match_key``
                     (D-01b). ARAM / Arena never surface a Live Client game_id,
                     so those rows were 100 percent unjoinable; this key groups
                     every tick of one game even with no game_id. Appended at
                     the END of the signature and written as a NEW record field
                     - ``game_id`` keeps its exact old meaning and value, so
                     every existing consumer and every historical row still
                     parse unchanged. Falls back to ``game_id`` when empty.
        enemy_stats / augments / engine_version / apply_mode_modifiers:
                     RM-875 item 5 - the inputs needed to RE-RUN the row
                     (gated row G5-05 CHECK B). Each is written only when the
                     caller passes it (not None), APPENDED after ``match_key``
                     in this order, so a caller that passes none of them (ARAM /
                     SR / Brawl today) writes the exact pre-RM-875 record.

    Record shape (additive):
        ts / champion / mode / level / owned_items / ds_picks / game_id
        + match_key  <- new; "" only when neither key was resolvable
        + enemy_stats / augments / engine_version / apply_mode_modifiers
                     <- RM-875; each present only when supplied
    """
    entry = {
        "ts": time.time(),
        "champion": champion,
        "mode": mode,
        "level": level,
        "owned_items": [str(i) for i in owned_items],
        "ds_picks": ds_picks,
        "game_id": game_id,
        "match_key": match_key or game_id,
    }
    if enemy_stats is not None:
        entry["enemy_stats"] = enemy_stats
    if augments is not None:
        entry["augments"] = [str(a) for a in augments]
    if engine_version is not None:
        entry["engine_version"] = str(engine_version)
    if apply_mode_modifiers is not None:
        entry["apply_mode_modifiers"] = bool(apply_mode_modifiers)
    path = Path(_LOG_PATH)
    with _LOG_LOCK:
        _rotate_if_oversize(path)
        try:
            # newline="\n": LF on Windows too, matching the prune's LF rewrite
            # of this same file (RM-481 residual, RM-1697).
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
