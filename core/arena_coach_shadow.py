"""core/arena_coach_shadow.py - fail-soft Arena deterministic-vs-Haiku writer.

The Arena sibling of core.aram_coach_shadow: the dashboard builds the
deterministic Arena block and reads the live Haiku block
(data/arena_coaching_data.json), then calls this writer to append ONE JSON
line per distinct coarse game state capturing BOTH columns - WITHOUT changing
any live output. The operator (or a later agreement report) diffs the two
columns to decide whether the deterministic block is safe to flip live.

Mirrors core.aram_coach_shadow: same fail-soft contract (never raises), same
per-path dedup, same default-path-under-data layout. The one deliberate
difference is the dedup sig: Arena rounds legitimately repeat the same action
label ("FIGHT") back to back, so the sig is ROUND-AWARE - each round re-logs
even when the label repeats (the ARAM sig has no round).

GATE (item-386 lesson): logs ONLY a real in-game tick - lc["champion"]
present. The stale coach artifact keeps `champion` after a game ends, so the
gate keys on the LIVECLIENT champion (populated only during a live game),
never logging a lobby / idle / Champ0 row.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.arena_coach_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "arena_coach_shadow.jsonl"

# Per-target dedup, keyed by str(target_path) so an explicit test path and the
# live default each dedup independently. The dashboard polls /api/state every
# ~500ms; without this the same coarse state would be logged ~2x/sec.
_LAST_SIG: dict[str, str] = {}

# The seven live Arena artifact fields captured per side, in artifact order
# (coaches/arena_coach.py:781-787). Used to normalize BOTH blocks so a partial
# dict still records every column (missing -> "").
_BLOCK_KEYS = (
    "action",
    "round_strategy",
    "fight_rule",
    "augment_advice",
    "anvil_advice",
    "target_priority",
    "risk",
)


def _norm_block(block: object) -> dict:
    """Return the seven-field block as an all-str dict, fail-soft.

    Simpler than the ARAM normalizer - the Arena artifact carries no
    dict-valued field, so every column coerces to a stripped str ("" for
    missing / non-str) and a malformed side still records a complete (empty)
    column rather than blocking the row. Only the seven known keys are kept
    (the live artifact carries many more fields).
    """
    src = block if isinstance(block, dict) else {}
    out: dict = {}
    for key in _BLOCK_KEYS:
        val = src.get(key)
        out[key] = val.strip() if isinstance(val, str) else ""
    return out


def log_arena_coach(
    det_block: object,
    live_block: object,
    lc: object,
    mode_key: str,
    *,
    round_label=None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one deterministic-vs-Haiku Arena record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup
    skip, or any failure (fail-soft). Never raises - safe on the hot path.

    Args:
        det_block: the deterministic Arena block (the seven fields).
        live_block: the live Haiku block read from
            data/arena_coaching_data.json (same seven fields, plus extras we
            drop).
        lc: the liveclient_summary() dict. The gate + champ + enemy_comp are
            read from here. A non-dict / no-champion lc is gated out.
        mode_key: dashboard mode_key (expected "arena"; recorded verbatim).
        round_label: the Arena round the tick belongs to; part of the dedup
            sig so each round re-logs even when the action label repeats.
        path: jsonl target override (test seam).
        now_iso: ISO timestamp override (test seam).
    """
    try:
        # Live-game gate (item-386): only a real in-game liveclient tick
        # carries lc["champion"]. The stale coach file keeps `champion` after
        # a game ends, so champion presence on the coach side is NOT enough.
        if not isinstance(lc, dict):
            return None
        champ = lc.get("champion")
        if not champ or not isinstance(champ, str) or not champ.strip():
            return None
        champ = champ.strip()

        # Verbatim best-effort comp: callers pass either plain names or dict
        # entries; str() covers both without blocking the row (the agreement
        # report normalizes downstream). Mirrors aram_coach_shadow exactly.
        enemy_raw = lc.get("enemy_team")
        enemy_comp = (
            [str(e) for e in enemy_raw if e] if isinstance(enemy_raw, list) else []
        )

        det = _norm_block(det_block)
        live = _norm_block(live_block)

        target = path if path is not None else SHADOW_PATH

        # Round-aware coarse-state dedup: idle ticks within a round dedup; a
        # new round OR a deterministic action transition re-logs. The round is
        # in the sig because Arena repeats action labels across rounds and
        # each round's side-by-side is a distinct validation sample.
        sig = str((mode_key, champ, str(round_label or ""), det["action"]))
        if _LAST_SIG.get(str(target)) == sig:
            return None

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "mode": str(mode_key or ""),
            "champ": champ,
            "round": round_label,
            "enemy_comp": enemy_comp,
            "deterministic": det,
            "live_haiku": live,
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("arena_coach_shadow.log_arena_coach failed", exc_info=True)
        return None


__all__ = ["log_arena_coach", "SHADOW_PATH"]
