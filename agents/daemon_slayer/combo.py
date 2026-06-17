# arch: action-queue combo simulator (clock + cooldown over burst walker) | section=daemon_slayer | frozen=no
"""Action-queue combo simulator - ordered cast/attack list over a clock.

Competitor lift #2 (breadth scan item 213; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 2"). calc.gg ships an
"Action Queue" where the user types a SEQUENTIAL cast/attack list
(``["Q", "AA", "W", "R", "AA"]``) and each action is evaluated in time
order, producing a per-hit damage breakdown + running total over the
sequence (vs RC's single aggregate DPS / burst). The homepage text:
``"Action Queue (Actions are all sequential, not simultaneous, max 60
actions, max 60 seconds)"``.

This module is NET-NEW COMPOSE, not net-new math: it adds the missing
TIME dimension on top of two engine functions that already resolve
per-cast damage through the full mitigation pipeline.

  * Per-cast damage (raw + mitigated, armor/MR/pen/amps already applied):
    ``burst.compute_burst_damage`` returns one ``ComboCast`` per token in
    the sequence with ``raw_damage`` (pre-mode/amps/mit) and
    ``final_damage`` (post-mode/amps/mit). The burst walker also resolves
    AA per-hit + Spellblade procs through ``compute_dps`` - so reusing it
    means the simulator's per-hit damage agrees byte-for-byte with the
    burst scorer. NO scoring math is duplicated or moved here.
  * Cast-time / cooldown clock: per-spell ``cast_time`` + per-rank
    ``cooldown`` lists from the patch-pinned
    ``data/daemon_slayer/<patch>/champion_abilities.json`` (same loader
    pattern as ``cooldown_watch.py``). The clock starts at 0; each action
    is stamped with its start time ``t``; the clock advances by the
    action's cast time after it resolves.

v1 scope (per the DEPTH spec, which itself flags "not all features
implemented" on calc.gg):
  * FIXED cast times. NO animation-cancel modeling. The clock advances by
    the spell's ``cast_time`` (when the abilities JSON has one) or a sane
    fallback; AA windup is a fixed default (no AS-derived windup curve).
  * COOLDOWN RESOLUTION: an ability re-cast while the spell is still on
    cooldown is SKIPPED (zero damage, ``status="on_cooldown"``, with the
    remaining seconds noted) rather than delayed. v1 chooses skip over
    delay because a delay model needs a recast-window policy (does the
    user wait, or do later actions slide forward?) that calc.gg does not
    pin either. The skipped action still advances the clock by 0 (it never
    happened), so subsequent actions keep their authored cadence. AA has
    no cooldown - it always fires.
  * NO regen / mana-gating between actions. The spec lists health/mana
    regen as a calc.gg feature; RC's per-cast damage is mana-independent
    (the burst walker credits each authored cast), so v1 models the
    sequence as "the user has the resources to cast what they typed" and
    leaves resource-gating to a future slice. Cost is surfaced per-row on
    the burst result but does not gate.
  * CAP: the sequence is capped at 60 actions AND the clock at 60s,
    mirroring calc.gg's stated limit. Actions past either cap are dropped.

Fail-soft contract (mirrors ``cooldown_watch`` + the burst walker):
unknown champion / champion absent from the abilities snapshot yields an
empty ``hits`` list with a note rather than raising. An empty / all-blank
sequence yields empty ``hits``.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .burst import compute_burst_damage
from .data_loader import DataSnapshot

_DATA_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "data"
    / "daemon_slayer"
)

# calc.gg's stated Action Queue limits.
MAX_ACTIONS = 60
MAX_DURATION_S = 60.0

# Sane fallback cast time when the abilities JSON has no cast_time for a
# spell form (None for ~51% of forms - dashes / channels / instants). The
# live patch 16.11.1 median spell cast_time is 0.25s; that is the honest
# placeholder for an un-pinned spell. Documented in the module docstring.
_DEFAULT_SPELL_CAST_S = 0.25

# Fixed auto-attack windup default (v1: no AS-derived windup curve). A
# typical mid-game AA windup sits ~0.2-0.3s; 0.25s is the round midpoint.
_DEFAULT_AA_WINDUP_S = 0.25

# The four active spell slots that carry a cooldown. AA + unknown tokens
# are cooldown-free.
_COOLDOWN_KEYS = ("Q", "W", "E", "R")


@dataclass(frozen=True)
class ComboHit:
    """One resolved action in the combo timeline.

    ``t`` is the clock time (seconds from 0) at which the action STARTS.
    ``raw`` is the un-mitigated, pre-amp per-cast damage; ``mitigated`` is
    the post-mode / post-amp / post-mitigation damage that contributes to
    the running total (0.0 for a skipped on-cooldown action). ``cumulative``
    is the running sum of ``mitigated`` through this action inclusive.

    ``status`` is ``"ok"`` for a resolved action or ``"on_cooldown"`` for an
    ability skipped because the slot was still on cooldown. ``cast_time`` is
    how long the action advanced the clock (0.0 for a skipped action).
    ``cooldown_s`` is the slot's effective cooldown at its rank (0.0 for AA
    / unknown). ``note`` carries the human-readable reason for a skip / any
    per-row annotation.
    """

    index: int
    action: str
    ability_key: str
    is_ability: bool
    form_name: str
    rank: int
    t: float
    cast_time: float
    cooldown_s: float
    damage_type: Optional[str]
    raw: float
    mitigated: float
    cumulative: float
    status: str
    note: str = ""


@dataclass(frozen=True)
class ComboResult:
    """Resolved combo timeline + totals.

    ``hits`` is the per-action timeline in cast order (skipped actions are
    retained with ``status="on_cooldown"`` + zero damage so the timeline
    stays 1:1 with the authored sequence up to the cap). ``total_raw`` /
    ``total_mitigated`` sum the per-hit values; ``duration_s`` is the clock
    time after the last resolved action. ``notes`` carries simulator-level
    annotations (unknown champion, cap truncation, missing data).
    """

    champion: str
    champion_name: str
    level: int
    mode: str
    sequence: Tuple[str, ...]
    hits: Tuple[ComboHit, ...] = field(default_factory=tuple)
    total_raw: float = 0.0
    total_mitigated: float = 0.0
    duration_s: float = 0.0
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _load_abilities() -> Dict[str, dict]:
    """Read patch + champion_abilities.json once; return the ``data`` map.

    Mirrors ``cooldown_watch._load_abilities`` exactly: read ``current.txt``
    for the patch, then ``<patch>/champion_abilities.json``, return its
    ``data`` dict (champion id -> {slot: [form, ...]}). Fail-soft to ``{}``
    so a missing file degenerates to "use fallback cast times" rather than
    raising.
    """
    try:
        patch = (_DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not patch:
        return {}
    abil_file = _DATA_DIR / patch / "champion_abilities.json"
    try:
        raw = json.loads(abil_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get("data") or {}
    return data if isinstance(data, dict) else {}


# Loaded once at import (read-only). Tests may monkeypatch this global to
# exercise the fallback-cast-time path or a synthetic champion.
_ABILITIES: Dict[str, dict] = _load_abilities()


def _cast_time_for(champion: str, ability_key: str) -> float:
    """Effective cast time for a spell slot via the patch-pinned JSON.

    Reads the form-0 ``cast_time`` from the module-level ``_ABILITIES``
    global (so a test monkeypatch is honoured). Returns
    ``_DEFAULT_SPELL_CAST_S`` when the slot / cast_time is absent or
    malformed - the simulator never stalls on missing cast-time data.
    """
    forms = (_ABILITIES.get(champion) or {}).get(ability_key)
    if not isinstance(forms, list) or not forms:
        return _DEFAULT_SPELL_CAST_S
    form = forms[0]
    if not isinstance(form, dict):
        return _DEFAULT_SPELL_CAST_S
    ct = form.get("cast_time")
    if not isinstance(ct, (int, float)) or isinstance(ct, bool):
        return _DEFAULT_SPELL_CAST_S
    val = float(ct)
    return val if val > 0.0 else _DEFAULT_SPELL_CAST_S


def _burst_notes(burst) -> Tuple[str, ...]:
    """Best-effort pull of the burst result's notes (fail-soft)."""
    try:
        return tuple(str(n) for n in (getattr(burst, "notes", ()) or ()))
    except Exception:
        return ()


def _normalize_sequence(sequence: Optional[Sequence[str]]) -> List[str]:
    """Clean + cap the authored action list.

    Strips blanks / None, uppercases tokens, and truncates to
    ``MAX_ACTIONS``. The clock-based ``MAX_DURATION_S`` cap is applied
    during the walk (an action whose START time would exceed the cap is
    dropped). Returns a plain list (may be empty).
    """
    out: List[str] = []
    for raw in sequence or []:
        if raw is None:
            continue
        tok = str(raw).strip().upper()
        if not tok:
            continue
        out.append(tok)
        if len(out) >= MAX_ACTIONS:
            break
    return out


def compute_combo(
    champion: str,
    level: int,
    item_ids: Optional[Sequence[str | int]] = None,
    sequence: Optional[Sequence[str]] = None,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    mode: str = "SR",
    snapshot: Optional[DataSnapshot] = None,
    runes: Optional[Sequence[int]] = None,
    score_completion_runes: bool = False,
) -> ComboResult:
    """Walk a clock over an ordered cast/attack list; per-hit mitigated dmg.

    ``sequence`` is an ordered list of action tokens (``"Q"``, ``"AA"``,
    ``"W"``, ``"R"``, ...). The clock starts at 0; for each action:

    1. Stamp the action with its start time ``t`` = current clock.
    2. For a cooldown-bearing ability still on cooldown (last cast +
       cooldown > clock): SKIP it (``status="on_cooldown"``, zero damage,
       remaining-seconds note). The clock does not advance for a skip.
    3. Otherwise resolve the action's per-cast damage from the burst
       walker (full mitigation pipeline), accumulate, record the slot's
       last-cast time, and advance the clock by the action's cast time.

    Caps the timeline at ``MAX_ACTIONS`` actions and ``MAX_DURATION_S``
    seconds (calc.gg's stated limits). Fail-soft: unknown champion /
    empty sequence yields an empty ``hits`` list with a note.
    """
    champ = str(champion or "").strip()
    seq = _normalize_sequence(sequence)
    snap = snapshot if snapshot is not None else DataSnapshot.load()

    notes: List[str] = []
    if not champ:
        notes.append("no champion supplied")
        return ComboResult(
            champion="", champion_name="", level=int(level), mode=mode,
            sequence=tuple(seq), notes=tuple(notes),
        )
    if not seq:
        notes.append("empty sequence")
        return ComboResult(
            champion=champ, champion_name=champ, level=int(level), mode=mode,
            sequence=(), notes=tuple(notes),
        )

    # Single burst-walker call resolves per-cast damage for the WHOLE
    # sequence through the full mitigation pipeline (AA + abilities +
    # spellblade). One ``ComboCast`` per token, in order. The burst walker
    # credits every authored cast (no time/cooldown gating) - this module
    # layers the clock + cooldown skip on top of that per-cast damage.
    try:
        burst = compute_burst_damage(
            snap, champ, int(level), item_ids=list(item_ids or []),
            mode=mode, target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            combo_sequence=seq, runes=runes,
            score_completion_runes=score_completion_runes,
        )
    except Exception as exc:  # fail-soft: surface a note, never raise
        notes.append(f"burst walker failed: {str(exc)[:120]}")
        return ComboResult(
            champion=champ, champion_name=champ, level=int(level), mode=mode,
            sequence=tuple(seq), notes=tuple(notes),
        )

    champ_name = burst.champion_name or champ
    # Detect the absent-from-snapshot case: the burst walker returns a
    # note and zero per_cast for an unknown champion. Surface it.
    if not burst.per_cast:
        for n in _burst_notes(burst):
            notes.append(n)
        notes.append(
            "no resolvable actions (champion absent or sequence empty)"
        )
        return ComboResult(
            champion=burst.champion_id or champ, champion_name=champ_name,
            level=int(level), mode=mode, sequence=tuple(seq),
            notes=tuple(notes),
        )

    # Per-champ AA windup from the optional wiki_stats sidecar (item 221).
    # Used ONLY when it is a real positive float; otherwise the fixed
    # _DEFAULT_AA_WINDUP_S default holds (byte-identical to no-sidecar).
    _wiki_aa = snap.wiki_attack_cast_time(burst.champion_id or champ)
    aa_windup = (
        float(_wiki_aa)
        if isinstance(_wiki_aa, (int, float))
        and not isinstance(_wiki_aa, bool)
        and float(_wiki_aa) > 0.0
        else _DEFAULT_AA_WINDUP_S
    )

    clock = 0.0
    cumulative = 0.0
    total_raw = 0.0
    total_mitigated = 0.0
    last_cast_t: Dict[str, float] = {}
    hits: List[ComboHit] = []
    truncated_by_clock = False

    for i, cast in enumerate(burst.per_cast):
        # Clock cap: an action that would START past the duration cap is
        # dropped (calc.gg caps at 60s).
        if clock > MAX_DURATION_S:
            truncated_by_clock = True
            break

        token = cast.token
        key = cast.ability_key
        is_ability = bool(cast.is_ability)
        cooldown_s = float(cast.cooldown or 0.0)
        cast_time = (
            _cast_time_for(burst.champion_id or champ, key)
            if (is_ability and key in _COOLDOWN_KEYS)
            else aa_windup
        )

        # Cooldown skip: a cooldown-bearing ability re-cast before its
        # slot is off cooldown contributes nothing (v1: skip not delay).
        on_cd = False
        remaining = 0.0
        if is_ability and key in _COOLDOWN_KEYS and cooldown_s > 0.0:
            prev = last_cast_t.get(key)
            if prev is not None:
                ready_at = prev + cooldown_s
                if ready_at > clock + 1e-9:
                    on_cd = True
                    remaining = ready_at - clock

        if on_cd:
            hits.append(ComboHit(
                index=i, action=token, ability_key=key,
                is_ability=is_ability, form_name=cast.form_name,
                rank=int(cast.rank), t=round(clock, 3), cast_time=0.0,
                cooldown_s=round(cooldown_s, 2),
                damage_type=cast.damage_type, raw=0.0, mitigated=0.0,
                cumulative=round(cumulative, 2), status="on_cooldown",
                note=f"{key} on cooldown ({remaining:.1f}s left) - skipped",
            ))
            continue

        raw = float(cast.raw_damage or 0.0)
        mitigated = float(cast.final_damage or 0.0)
        cumulative += mitigated
        total_raw += raw
        total_mitigated += mitigated
        if is_ability and key in _COOLDOWN_KEYS:
            last_cast_t[key] = clock

        hits.append(ComboHit(
            index=i, action=token, ability_key=key, is_ability=is_ability,
            form_name=cast.form_name, rank=int(cast.rank),
            t=round(clock, 3), cast_time=round(cast_time, 3),
            cooldown_s=round(cooldown_s, 2), damage_type=cast.damage_type,
            raw=round(raw, 2), mitigated=round(mitigated, 2),
            cumulative=round(cumulative, 2), status="ok",
        ))
        clock += cast_time

    if truncated_by_clock:
        notes.append(f"sequence truncated at {MAX_DURATION_S:.0f}s clock cap")
    if len(seq) >= MAX_ACTIONS:
        notes.append(f"sequence capped at {MAX_ACTIONS} actions")

    # DS V2 S3 - fold the burst walker's optional rune-proc aggregate into the
    # combo totals so the timeline total reflects keystone/proc runes. The
    # rune burst is a single aggregate on the BurstResult (NOT per-cast), so
    # it is added once to total_raw + total_mitigated rather than to a hit
    # row. ``rune_proc_damage`` is 0.0 when ``runes`` is None -> byte-identical.
    rune_proc = float(getattr(burst, "rune_proc_damage", 0.0) or 0.0)
    if rune_proc > 0.0:
        total_raw += rune_proc
        total_mitigated += rune_proc
        notes.append(f"rune procs +{rune_proc:.1f} folded into combo total")

    return ComboResult(
        champion=burst.champion_id or champ,
        champion_name=champ_name,
        level=int(level),
        mode=mode,
        sequence=tuple(seq),
        hits=tuple(hits),
        total_raw=round(total_raw, 2),
        total_mitigated=round(total_mitigated, 2),
        duration_s=round(clock, 3),
        notes=tuple(notes),
    )


__all__ = [
    "ComboHit",
    "ComboResult",
    "compute_combo",
    "MAX_ACTIONS",
    "MAX_DURATION_S",
]
