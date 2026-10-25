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

FOCUS BOARD COLUMN (RM-844, SHADOW-ONLY): each fresh row also carries
``focus_board`` - the DS focus board's top ``kill_order`` pick for the live
roster (core.focus_board_live, in-process, cached + throttled, engine loaded
off this thread) beside the rule's pick read back from
``deterministic.target_priority``, plus where the board ranks the rule's pick.
The ``deterministic`` column is untouched, so the rule stays authoritative and
the served coach never changes. Computed only after the dedup check (one
lookup per written row, never per tick). Any adapter failure becomes a
``status`` + note in the column, never a dropped row. ``RC_FOCUS_BOARD_SHADOW=0``
omits the column (the row keeps its pre-RM-844 shape).
"""

from __future__ import annotations

import json
import logging
import re
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

# The live Arena artifact fields captured per side, in artifact order
# (coaches/arena_coach.py:781-788). Used to normalize BOTH blocks so a partial
# dict still records every column (missing -> "" / [] for choices). ``choices``
# (the deterministic + native A/B array) was added so the shadow row carries the
# WHOLE coach block for the operator to eyeball before a live flip - mirroring
# the ARAM shadow schema.
_BLOCK_KEYS = (
    "action",
    "round_strategy",
    "fight_rule",
    "augment_advice",
    "anvil_advice",
    "target_priority",
    "risk",
    "choices",
)


def _norm_block(block: object) -> dict:
    """Return the block as a normalized dict, fail-soft.

    Every string column coerces to a stripped str ("" for missing / non-str);
    ``choices`` is the one list-typed column and keeps its list (a non-list /
    missing choices -> []). A malformed side still records a complete (empty)
    column rather than blocking the row. Only the known keys are kept (the live
    artifact carries many more fields).
    """
    src = block if isinstance(block, dict) else {}
    out: dict = {}
    for key in _BLOCK_KEYS:
        val = src.get(key)
        if key == "choices":
            out[key] = val if isinstance(val, list) else []
        else:
            out[key] = val.strip() if isinstance(val, str) else ""
    return out


# RM-844: the rule's kill-order line is "Kill {name} first - ..." (both shapes
# of core.arena_target_rule.target_priority); the rule's pick is read back from
# it, so the rule module itself stays untouched.
_RULE_PICK_RE = re.compile(r"^Kill (.+?) first(?:\s|$)")


def _rule_pick(target_line: object) -> str:
    """The champion the target_priority rule names, or "" when unparseable."""
    if not isinstance(target_line, str):
        return ""
    m = _RULE_PICK_RE.match(target_line.strip())
    return m.group(1).strip() if m else ""


def _name_key(text: object) -> str:
    """Case- and punctuation-insensitive name key ("Kai'Sa" == "Kaisa")."""
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _focus_board_column(det: dict, lc: dict, mode_key: str) -> dict | None:
    """RM-844 SHADOW column: the focus board's top pick beside the rule's pick.

    None when the kill switch is off. Never raises: an adapter that cannot be
    imported or that raises becomes a ``status`` + note, never a dropped row.
    ``agree`` is None unless both picks exist; ``rule_pick_board_rank`` is the
    rule pick's index in the board's ``kill_order`` (None when not on it).
    """
    rule_pick = _rule_pick(det.get("target_priority"))
    try:
        from core import focus_board_live  # lazy: keeps DS off this import path
    except Exception as exc:  # noqa: BLE001
        log.debug("arena_coach_shadow: focus board adapter import failed",
                  exc_info=True)
        fb: dict = {"status": "unavailable", "notes": [
            f"focus board adapter could not load ({type(exc).__name__})"]}
    else:
        try:
            if not focus_board_live.enabled():
                return None
            fb = focus_board_live.board_for_lc(lc, mode_key)
        except Exception as exc:  # noqa: BLE001
            log.debug("arena_coach_shadow: focus board failed", exc_info=True)
            fb = {"status": focus_board_live.STATUS_ERROR, "notes": [
                f"focus board failed ({type(exc).__name__}) - no board"]}
    if not isinstance(fb, dict):
        fb = {"status": "error", "notes": ["focus board returned no result"]}

    top = fb.get("top_kill") if isinstance(fb.get("top_kill"), dict) else {}
    board_pick = str(top.get("champion_name") or "")
    rank = None
    if rule_pick:
        want = _name_key(rule_pick)
        ids = fb.get("kill_order") if isinstance(fb.get("kill_order"), list) else []
        names = (fb.get("kill_order_names")
                 if isinstance(fb.get("kill_order_names"), list) else [])
        for i, cid in enumerate(ids):
            name = names[i] if i < len(names) else cid
            if want in (_name_key(cid), _name_key(name)):
                rank = i
                break
    column: dict = {
        "rule_pick": rule_pick,
        "board_pick": board_pick,
        "agree": (rank == 0) if (rule_pick and board_pick) else None,
        "rule_pick_board_rank": rank,
    }
    for key, val in fb.items():
        column.setdefault(key, val)
    return column


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
        # RM-844 shadow column, AFTER the dedup check so the board is looked
        # up once per written row. Its own guard: a failure here is a status
        # in the column, never a dropped row.
        try:
            fb_col = _focus_board_column(det, lc, mode_key)
        except Exception as exc:  # noqa: BLE001
            log.debug("arena_coach_shadow: focus board column failed",
                      exc_info=True)
            fb_col = {"rule_pick": "", "board_pick": "", "agree": None,
                      "rule_pick_board_rank": None, "status": "error",
                      "notes": [f"focus board column failed ({type(exc).__name__})"]}
        if fb_col is not None:
            record["focus_board"] = fb_col

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("arena_coach_shadow.log_arena_coach failed", exc_info=True)
        return None


__all__ = ["log_arena_coach", "SHADOW_PATH"]
