"""Append-only DS pick calibration log.

Called from coaches after their DS dispatch returns rows, so each such coaching
tick (~30s cadence) produces one entry in data/ds_calibration.jsonl. The
consumer, core/ds_calibration_agreement.py (run by
tools/ds_calibration_report.py), joins the log against rewind_history.db
EXACTLY on the Riot game id (``game_id``, else a ``live_<gameId>``
``match_key``) to compare DS-recommended items vs. actually purchased items vs.
win/loss outcome; it takes the earliest tick that recommended each unowned
item, per (game, item, scorer).

Non-fatal: ``log_ds_run`` does not raise on wrong-shaped input or on a
failed write. Junk input is coerced (a None or bare value where a list was
expected, a value JSON cannot encode, a NaN / inf float, which is written as
``null`` so every line stays strict JSON); an encode or write failure is
caught and logged at WARNING once per process PER failure kind (S144-T-666;
it used to be swallowed without a trace), so a writer that stops can still
say why. When an argument's OWN ``__str__``, ``__bool__`` or iteration
raises, a ``TypeError`` / ``ValueError`` / ``RecursionError`` drops the row
with the encode WARNING; any other exception is a caller bug and propagates
(every live caller wraps the call in ``except Exception`` anyway).

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
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Optional

from core import log_rotation

log = logging.getLogger(__name__)

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

# Failure kinds already logged, so a broken log path costs one WARNING per
# process, not one per ~30 s tick, and an earlier encode failure never hides a
# later write failure.
_WARNED: set = set()

# The EnemyStats fields a calibration row records, in record order.
_ENEMY_STATS_FIELDS = ("armor", "mr", "max_hp", "bonus_hp")


def _warn_once(kind: str, what: str, exc: BaseException) -> None:
    if kind in _WARNED:
        return
    _WARNED.add(kind)
    log.warning("ds_calibration: %s (%s: %s); further failures are not logged",
                what, type(exc).__name__, exc)


def enemy_stats_summary(enemy_stats) -> Optional[dict]:
    """RM-875 item 5: the enemy-stat inputs a calibration row needs to re-run.

    ``enemy_stats`` is a ``coach_integration.enemy_stats.EnemyStats`` (or any
    object with those attributes). ``None`` in, ``None`` out, so a caller with
    no enemy context writes no ``enemy_stats`` key at all.

    The values are the ones the DS request actually carried: they are read
    through the dispatcher's own ``coach_integration.archetype_dispatch``
    ``_stat`` / ``_shares`` (one source, not a copy), so a real 0.0 damage
    share stays 0.0 and a NaN / inf / bool stat reads as the 0.0 the request
    sent (S144-T-666: a local ``float(x or default)`` read logged an all-AD
    comp as ap_share 0.5 and a NaN armor as NaN). If the dispatcher cannot be
    imported the row records no ``enemy_stats`` rather than guessed values.
    """
    if enemy_stats is None:
        return None
    try:
        from coach_integration.archetype_dispatch import (  # noqa: PLC0415
            _shares,
            _stat,
        )
    except ImportError as exc:
        _warn_once("import", "enemy_stats_summary cannot import the dispatcher",
                   exc)
        return None
    out = {name: _stat(enemy_stats, name) for name in _ENEMY_STATS_FIELDS}
    out["ad_share"], out["ap_share"] = _shares(enemy_stats)
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


def _as_list(values) -> list:
    """None -> [], a bare str / bytes or non-iterable -> [value], else list."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        return [values]
    try:
        return list(values)
    except TypeError:
        return [values]


def _json_key(key):
    """A dict key ``json.dumps`` encodes itself (str, int, bool, None, a
    finite float) kept as-is, so it serializes exactly as before; any other
    key as its ``str``."""
    if key is None or isinstance(key, (str, int)):
        return key
    if isinstance(key, float) and math.isfinite(key):
        return key
    return str(key)


def _jsonable(value):
    """``value`` with every non-finite float as None and every value JSON
    cannot encode as its ``str``, so the line is strict JSON (no bare NaN /
    Infinity token, which ``jq`` and ``JSON.parse`` reject)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, dict):
        return {_json_key(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _append_line(path: Path, data: bytes) -> None:
    """Append ``data`` (one LF-terminated line) as BYTES, in one write.

    Binary mode keeps the row LF on Windows (the prune rewrites this file as
    LF, RM-481 residual, RM-1697). If the file's last byte is not a newline
    (a crash or a full disk tore the previous row), a newline goes first, so
    the new row is not fused onto the torn one and dropped with it by the
    consumer.
    """
    with open(path, "a+b", buffering=0) as fh:
        end = fh.seek(0, os.SEEK_END)
        if end:
            fh.seek(end - 1)
            if fh.read(1) != b"\n":
                data = b"\n" + data
        view = memoryview(data)
        while view:
            written = fh.write(view)
            if not written:
                raise OSError("short write appending ds_calibration row")
            view = view[written:]


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
    """Append one DS observation to the calibration log (non-fatal, see module).

    Args:
        champion:    champion name (e.g. "Ahri")
        mode:        coaching mode string (e.g. "ARAM", "SR", "ARENA", "BRAWL")
        level:       current champion level
        owned_items: item IDs currently in inventory (list of str or int);
                     None -> [], a bare value -> [value]
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
    try:
        entry = {
            "ts": time.time(),
            "champion": champion,
            "mode": mode,
            "level": level,
            "owned_items": [str(i) for i in _as_list(owned_items)],
            "ds_picks": ds_picks,
            "game_id": game_id,
            "match_key": match_key or game_id,
        }
        if enemy_stats is not None:
            entry["enemy_stats"] = enemy_stats
        if augments is not None:
            entry["augments"] = [str(a) for a in _as_list(augments)]
        if engine_version is not None:
            entry["engine_version"] = str(engine_version)
        if apply_mode_modifiers is not None:
            entry["apply_mode_modifiers"] = bool(apply_mode_modifiers)
        line = json.dumps(_jsonable(entry), allow_nan=False) + "\n"
    except (TypeError, ValueError, RecursionError) as exc:
        _warn_once("encode", "a calibration row could not be encoded", exc)
        return
    path = Path(_LOG_PATH)
    with _LOG_LOCK:
        _rotate_if_oversize(path)
        try:
            _append_line(path, line.encode("utf-8"))
        except OSError as exc:
            _warn_once("write", f"appending to {_LOG_PATH} failed", exc)
