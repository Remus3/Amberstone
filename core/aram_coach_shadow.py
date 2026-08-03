"""core/aram_coach_shadow.py - fail-soft Stage 2 ARAM deterministic-vs-Haiku writer.

This is the "eyeball them side-by-side" validation substrate for the ARAM
deterministic coach. The dashboard (dashboard/_state_builder.py) builds the
deterministic ARAM block (core.aram_deterministic_coach.build_block) and reads
the live Haiku block (data/aram_coaching_data.json), then calls this writer to
append ONE JSON line per distinct coarse game state capturing BOTH the
deterministic block AND the live Haiku block - WITHOUT changing any live output.
The operator (or a later agreement report) can then diff the two columns to
decide whether the deterministic block is safe to flip live.

Mirrors core.det_coach_shadow: same fail-soft contract (never raises), same
per-path coarse-state dedup (the dashboard polls /api/state ~2x/sec, so without
dedup the same state would spam the jsonl), same default-path-under-data layout.

GATE (item-386 lesson): logs ONLY a real in-game tick - lc["champion"] present.
The stale coach artifact keeps `champion` after a game ends, so we key the gate
on the LIVECLIENT champion (populated only during a live game), never logging a
lobby / idle / Champ0 row.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.aram_coach_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "aram_coach_shadow.jsonl"

# Per-target dedup, keyed by str(target_path) so an explicit test path and the
# live default each dedup independently. The dashboard polls /api/state every
# ~500ms; without this the same coarse state would be logged ~2x/sec.
_LAST_SIG: dict[str, str] = {}

# The deterministic / live-Haiku fields captured per side, in artifact order.
# Used to normalize BOTH blocks so a partial dict still records every column
# (missing -> "" / {} for reasons / [] for choices). item_extra + objective
# were added R78 (the Haiku-to-ZERO ARAM tail) so the shadow row carries the
# WHOLE coach block for the operator to eyeball before a live flip.
_BLOCK_KEYS = (
    "action",
    "fight_rule",
    "risk",
    "reset_item",
    "item_build",
    "item_build_reasons",
    "choices",
    "item_extra",
    "objective",
)


def _norm_block(block: object) -> dict:
    """Return the normalized block as a plain dict, fail-soft.

    A non-dict input coerces to all-empty fields so a malformed side still
    records a complete (empty) column rather than blocking the row. Only the
    known _BLOCK_KEYS are kept (the live artifact carries many more fields).
    """
    src = block if isinstance(block, dict) else {}
    out: dict = {}
    for key in _BLOCK_KEYS:
        val = src.get(key)
        if key == "item_build_reasons":
            out[key] = val if isinstance(val, dict) else {}
        elif key == "choices":
            out[key] = val if isinstance(val, list) else []
        else:
            out[key] = val if isinstance(val, str) else ("" if val is None else val)
    return out


def _norm_number(value: object) -> float | None:
    """Return a real finite float, else None. Never raises.

    Strict on purpose: this mirrors the assembler's own numeric gate, so a
    column here reads exactly as the rule read it. A bool is rejected because
    it is an int in Python and would turn a flag into a measurement, and a
    non-finite float is rejected because json.dumps writes NaN / Infinity as
    bare tokens that are not valid JSON - one garbage tick would otherwise
    poison the whole corpus for every reader but json.loads.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _norm_count(value: object) -> int | None:
    """Return a whole-number count as an int, else None. Never raises."""
    num = _norm_number(value)
    if num is None or num != int(num):
        return None
    return int(num)


def _lc_hp_pct(lc: dict) -> float | None:
    """Self HP percent 0..100 off the liveclient tick, or None. Never raises.

    Kept DISTINCT from the recorded ``hp_pct`` column: the assembler prefers the
    coach artifact's own hp_pct and only falls back to this ratio, so the two
    have different provenance and can disagree. Recording an lc-derived percent
    under the name of the value the rule actually consumed would silently
    manufacture the attribution this instrumentation exists to make honest.
    """
    cur = _norm_number(lc.get("hp"))
    mx = _norm_number(lc.get("hp_max"))
    if mx is None or mx <= 0 or cur is None:
        return None
    pct = 100.0 * cur / mx
    return pct if 0.0 <= pct <= 150.0 else None


def log_aram_coach(
    det_block: object,
    live_block: object,
    lc: object,
    mode_key: str,
    *,
    path: Path | None = None,
    now_iso: str | None = None,
    hp_pct: object = None,
    wave_pct: object = None,
    low_enemy_count: object = None,
) -> dict | None:
    """Append one deterministic-vs-Haiku ARAM record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup
    skip, or any failure (fail-soft). Never raises - safe on the hot path.

    Args:
        det_block: the deterministic block from
            core.aram_deterministic_coach.build_block (the _BLOCK_KEYS fields).
        live_block: the live Haiku block read from
            data/aram_coaching_data.json (same fields, plus extras we drop).
        lc: the liveclient_summary() dict. The gate + champ + enemy_comp are
            read from here. A non-dict / no-champion lc is gated out.
        mode_key: dashboard mode_key (expected "aram"; recorded verbatim).
        path: jsonl target override (test seam).
        now_iso: ISO timestamp override (test seam).
        hp_pct: the self-HP percent decide_action was given, 0..100.
        wave_pct: the minion-wave position decide_action was given, 0..100.
        low_enemy_count: the low-HP enemy count decide_action was given.

    The three rule inputs are recorded, never consumed: they do not enter the
    dedup signature and they change no verdict. They exist because the agreement
    residual between the two columns is quantised to exactly one ladder tier -
    the shape of the single wave_pct shift operator - and no mismatch in this
    log could be attributed to the state that produced it while the raw
    decide_action inputs were absent from every row. Each degrades to null
    independently, so a partial read still yields an attributable row.
    """
    try:
        # Live-game gate (item-386): only a real in-game liveclient tick carries
        # lc["champion"]. The stale coach file keeps `champion` after a game
        # ends, so champion presence on the coach side is NOT sufficient.
        if not isinstance(lc, dict):
            return None
        champ = lc.get("champion")
        if not champ or not isinstance(champ, str) or not champ.strip():
            return None
        champ = champ.strip()

        enemy_raw = lc.get("enemy_team")
        enemy_comp = (
            [str(e) for e in enemy_raw if e] if isinstance(enemy_raw, list) else []
        )

        det = _norm_block(det_block)
        live = _norm_block(live_block)

        target = path if path is not None else SHADOW_PATH

        # Coarse-state dedup: champ + enemy comp + the deterministic action
        # (the field the operator watches transition). Idle ticks dedup; a real
        # coaching transition (action change, comp change) re-logs. Mirrors the
        # det_coach_shadow coarse-sig approach (no game_time bucket here - the
        # ARAM block has no reliable server-side game-time, and action change is
        # the meaningful signal).
        sig = str((mode_key, champ, tuple(enemy_comp), det.get("action", "")))
        if _LAST_SIG.get(str(target)) == sig:
            return None

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "mode": str(mode_key or ""),
            "champ": champ,
            "enemy_comp": enemy_comp,
            "deterministic": det,
            "live_haiku": live,
            "hp_pct": _norm_number(hp_pct),
            "wave_pct": _norm_number(wave_pct),
            "low_enemy_count": _norm_count(low_enemy_count),
            "lc_hp_pct": _lc_hp_pct(lc),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("aram_coach_shadow.log_aram_coach failed", exc_info=True)
        return None


__all__ = ["log_aram_coach", "SHADOW_PATH"]
