"""Focus board (RM-841, s133) - per-enemy time-to-kill both ways, kill order, danger list.

For MY champion (level + items) against EACH enemy (level + items) this module
answers the team-fight targeting questions the 1v1 ``matchup`` engine cannot:

* ``my_ttk_s`` - seconds for me alone to kill that enemy from full HP;
* ``team_ttk_s`` - the same with every supplied ally's sustained DPS added;
* ``their_ttk_on_me_s`` - seconds for that enemy alone to kill me;
* ``combo_lethal_hp_pct`` - my one-combo burst as a fraction of their HP
  ("your combo kills Lux below 62 percent HP"), capped at 1;
* ``focus_value`` - their DPS on me divided by ``team_ttk_s``: threat removed
  per second of team focus.

The board orders the rows two ways: ``kill_order`` (focus_value descending)
and ``danger_order`` (their_ttk_on_me_s ascending - who kills me fastest).

Pure + deterministic: composes ONLY existing scorers. No LLM, no network, no
new data. Purely additive - a new module with no route; it changes no
existing scorer's output, so ENGINE_VERSION does not move (item-374
precedent). The HTTP route, the version bump, the docs rows and the live
adapter belong to later slices (see DEFERRED below).

Composition (cite before changing - each was re-grepped at RM-841):

* Defences: ``matchup._defensive_stats`` (armor / MR / max HP / bonus HP via
  ``engine.build_champion``), the same resolution the EHP scorer and the 1v1
  matchup use, so every side is scored off one stat line.
* Sustained DPS = ``dps.compute_dps(...).weighted_dps`` PLUS
  ``ability_dps.compute_ability_dps(...).total_ability_dps``. ``compute_dps``
  is auto-attack DPS ONLY (its docstring: "Ability damage is **not**
  included"); its rotation durations already include casting time, so the AA
  term is diluted by the casts rather than double-counting them. Leaving the
  ability term out ranks every mage as harmless (adjudicator correction).
  Both scorers mitigate against the target's armor / MR with the attacker's
  own penetration, so the DPS figures here are POST-resist damage.
* Burst: ``burst.compute_burst_damage(...).total_burst_damage``, also
  post-resist (matchup.py module docstring: "do not re-apply armor").
* Effective HP = max HP / damage-taken multiplier. Resists are already in
  the DPS, so the only thing left to fold into the HP pool is the mode's
  per-champion damage-taken multiplier, resolved exactly as
  ``ehp.compute_ehp`` resolves it: ARAM ``aramDamageTaken`` through
  ``ehp._aram_damage_taken``; for any other mode the wiki sidecar's
  ``dmg_taken`` only when ``apply_mode_modifiers`` is on. In SR it is 1.0, so
  effective HP is the resolved max HP.

MODE. ``mode`` is folded once through ``data_loader.canonical_mode`` and,
with ``apply_mode_modifiers``, reaches BOTH sides and BOTH halves of each
side: my offence into each enemy's defences, each enemy's offence into mine,
every ally's offence, and both damage-taken multipliers. That is the RM-172
rule (matchup.py docstring): arming a subset scores one side off the ARENA
stat line and the other off the SR one, which is worse than blind.
``apply_mode_modifiers`` stays DEFAULT-OFF, like every other DS seam. Only
the public ``compute_focus_board`` carries the kwarg by that name; the private
helpers take it as ``mode_flag``, so the RM-172 GATE A census
(``tests/test_rm172_mode_modifier_seam_characterization.py``
``EXPECTED_GATE_A``, measured by ``inspect.signature`` over every DS function)
widens by exactly one entry.

LIMITS (stated in every board's ``notes``):

* Every HP is assumed FULL. The Live Client API exposes no enemy current HP,
  so TTK is from full; ``combo_lethal_hp_pct`` is the mitigation - the player
  reads it against the live HP bar.
* This is an ORDERING of computed quantities, not an outcome prediction. No
  healing, shields, CC, positioning or focus-switching is modelled, and the
  RM-12 standing finding (the matchup engine is a coin-flip against real
  outcomes) applies: any consumer stays shadow until agreement data says
  otherwise.

Never raises: an unknown champion, a malformed fighter tuple or a build the
engine cannot resolve becomes a fixed-text note and that fighter is skipped;
an unknown item id is dropped from the build with a note. Notes never carry
exception text (RM-835), only the exception class name.

DEFERRED (owned by the merger / later rows): the ``/focus-board`` route in
``server.py`` + ENGINE bump + ``docs/DAEMON_SLAYER.md`` / ``docs/API.md``
rows; the live adapter (per-enemy level is missing from the Live Client
players list in ``dashboard/_liveclient.py``); the shadow ``target_priority``
wiring (``core/arena_coach_shadow.py``, ``core/arena_target_rule.py``); the
Arena 2v2 partner variant (pass the partner as the one ally today).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .ability_dps import compute_ability_dps
from .burst import compute_burst_damage
from .data_loader import DataSnapshot, canonical_mode
from .dps import compute_dps
from .ehp import _aram_damage_taken
from .matchup import _defensive_stats
from .stats import clamp_level

# A fighter as callers pass it: (champion_id, level, item_ids).
Fighter = tuple[str, int, Sequence[str | int]]

_FULL_HP_NOTE = (
    "all HP assumed full: the Live Client exposes no enemy current HP, so every "
    "TTK is from full HP - read combo_lethal_hp_pct against the live HP bar"
)
_DPS_NOTE = (
    "sustained DPS = auto-attack DPS (compute_dps weighted_dps) + ability DPS "
    "(compute_ability_dps total_ability_dps), post armor / MR"
)
_ORDERING_NOTE = (
    "an ordering of computed quantities, not an outcome prediction: no healing, "
    "shields, CC or positioning is modelled"
)


@dataclass(frozen=True)
class _Fighter:
    """A validated fighter: snapshot champion id, clamped level, known items."""

    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]


@dataclass(frozen=True)
class _Defence:
    """One fighter's resolved defensive line plus its damage-taken multiplier."""

    armor: float
    mr: float
    max_hp: float
    bonus_hp: float
    damage_taken_mult: float

    @property
    def effective_hp(self) -> float:
        # Resists are already folded into every DPS / burst figure (both
        # scorers mitigate against target armor / MR), so only the mode's
        # damage-taken multiplier is left to fold into the pool.
        return self.max_hp / self.damage_taken_mult


@dataclass(frozen=True)
class FocusRow:
    """One enemy on the focus board, scored both ways.

    ``slot`` is the enemy's index in the caller's ``enemies`` sequence, so a
    consumer can tell apart two rows of the same champion (One For All).
    Times are seconds; ``math.inf`` means "never" (zero DPS) and serialises to
    ``None`` in ``to_dict``. ``my_burst`` is one full combo, post-resist.
    """

    slot: int
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    target_max_hp: float
    target_effective_hp: float
    my_dps: float
    team_dps: float
    my_ttk_s: float
    team_ttk_s: float
    their_dps_on_me: float
    their_ttk_on_me_s: float
    my_burst: float
    combo_lethal_hp_pct: float
    focus_value: float

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "target_max_hp": _num(self.target_max_hp),
            "target_effective_hp": _num(self.target_effective_hp),
            "my_dps": _num(self.my_dps),
            "team_dps": _num(self.team_dps),
            "my_ttk_s": _num(self.my_ttk_s),
            "team_ttk_s": _num(self.team_ttk_s),
            "their_dps_on_me": _num(self.their_dps_on_me),
            "their_ttk_on_me_s": _num(self.their_ttk_on_me_s),
            "my_burst": _num(self.my_burst),
            "combo_lethal_hp_pct": _num(self.combo_lethal_hp_pct),
            "focus_value": _num(self.focus_value),
        }


@dataclass(frozen=True)
class FocusBoard:
    """The whole board: one row per scorable enemy plus the two orderings.

    ``kill_order`` / ``danger_order`` hold champion ids (ties broken by input
    slot). ``me`` is "" and ``rows`` is empty when my own fighter could not be
    resolved; ``notes`` then says why.
    """

    me: str
    me_level: int
    mode: str
    apply_mode_modifiers: bool
    my_max_hp: float
    my_effective_hp: float
    allies: tuple[str, ...]
    rows: tuple[FocusRow, ...]
    kill_order: tuple[str, ...]
    danger_order: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "me": self.me,
            "me_level": self.me_level,
            "mode": self.mode,
            "apply_mode_modifiers": self.apply_mode_modifiers,
            "my_max_hp": _num(self.my_max_hp),
            "my_effective_hp": _num(self.my_effective_hp),
            "allies": list(self.allies),
            "rows": [r.to_dict() for r in self.rows],
            "kill_order": list(self.kill_order),
            "danger_order": list(self.danger_order),
            "notes": list(self.notes),
        }


def _num(value: float) -> Optional[float]:
    """Finite float, or None for inf / NaN so ``to_dict`` stays strict JSON."""
    return float(value) if math.isfinite(value) else None


def _parse_fighter(
    snapshot: DataSnapshot, fighter: Any, role: str,
) -> tuple[Optional[_Fighter], list[str]]:
    """Validate one ``(champion_id, level, item_ids)`` tuple.

    Returns ``(None, notes)`` for a malformed tuple, an unknown champion id or
    a non-integer level. Unknown item ids are dropped (live inventories carry
    wards and consumables the snapshot may not price) and named in a note.
    """
    try:
        champion_id, level, item_ids = fighter
    except (TypeError, ValueError):
        return None, [
            f"{role}: malformed fighter, expected (champion_id, level, item_ids)"
            " - skipped"
        ]
    if not isinstance(champion_id, str) or champion_id not in snapshot.champions:
        shown = champion_id if isinstance(champion_id, str) else type(champion_id).__name__
        return None, [f"{role}: unknown champion id {shown!r} - skipped"]
    try:
        lvl = clamp_level(int(level))
    except (TypeError, ValueError):
        return None, [f"{role} {champion_id}: level is not an integer - skipped"]

    if item_ids is None:
        raw: Iterable[Any] = ()
    elif isinstance(item_ids, (str, int)):
        raw = (item_ids,)
    else:
        raw = item_ids
    kept: list[str] = []
    dropped: list[str] = []
    try:
        for iid in raw:
            key = str(iid)
            (kept if key in snapshot.items else dropped).append(key)
    except TypeError:
        return None, [f"{role} {champion_id}: item_ids is not a sequence - skipped"]

    notes: list[str] = []
    if dropped:
        notes.append(
            f"{role} {champion_id}: dropped unknown item id(s) {', '.join(dropped)}"
        )
    name = str(snapshot.champion(champion_id).get("name") or champion_id)
    return _Fighter(champion_id, name, lvl, tuple(kept)), notes


def _damage_taken_multiplier(
    snapshot: DataSnapshot, champion_id: str, mode: str, mode_flag: bool,
) -> float:
    """The receiving side's mode damage multiplier, resolved as ``compute_ehp`` does.

    Mirrors ehp.py's inline block after ``_aram_damage_taken`` (the item-232
    opt-in): ARAM keeps its authoritative lolmath ``aramDamageTaken``; any
    other mode reads the wiki sidecar's ``dmg_taken`` ONLY when the flag is
    on, and never routes ARAM through the sidecar (double-count). A
    non-positive value falls back to 1.0 so a corrupt row cannot divide by
    zero.
    """
    mult = _aram_damage_taken(snapshot, champion_id, mode)
    if mode != "ARAM" and mode_flag:
        mm = snapshot.mode_modifier(champion_id, mode)
        if isinstance(mm, dict) and "dmg_taken" in mm:
            mult = float(mm["dmg_taken"])
    return mult if mult > 0 else 1.0


def _defence(
    snapshot: DataSnapshot, f: _Fighter, mode: str, mode_flag: bool,
) -> _Defence:
    armor, mr, max_hp, bonus_hp = _defensive_stats(
        snapshot, f.champion_id, f.level, f.item_ids, mode,
        apply_mode_modifiers=mode_flag,
    )
    return _Defence(
        armor=armor,
        mr=mr,
        max_hp=max_hp,
        bonus_hp=bonus_hp,
        damage_taken_mult=_damage_taken_multiplier(
            snapshot, f.champion_id, mode, mode_flag,
        ),
    )


def _target_kwargs(d: _Defence, mode: str, mode_flag: bool) -> dict:
    return {
        "mode": mode,
        "target_armor": d.armor,
        "target_mr": d.mr,
        "target_max_hp": d.max_hp,
        "target_bonus_hp": d.bonus_hp,
        "apply_mode_modifiers": mode_flag,
    }


def _sustained_dps(
    snapshot: DataSnapshot, attacker: _Fighter, target: _Defence,
    mode: str, mode_flag: bool,
) -> float:
    """Auto-attack DPS + ability DPS of ``attacker`` into ``target``, post-resist."""
    kw = _target_kwargs(target, mode, mode_flag)
    aa = compute_dps(
        snapshot, attacker.champion_id, attacker.level, attacker.item_ids, **kw,
    ).weighted_dps
    ability = compute_ability_dps(
        snapshot, attacker.champion_id, attacker.level, attacker.item_ids, **kw,
    ).total_ability_dps
    return float(aa) + float(ability)


def _ttk(effective_hp: float, dps: float) -> float:
    """Seconds to remove ``effective_hp`` at ``dps``; inf when dps is zero."""
    if effective_hp <= 0:
        return 0.0
    return effective_hp / dps if dps > 0 else math.inf


def _focus_value(their_dps_on_me: float, team_ttk_s: float) -> float:
    """Threat removed per second of focus. A target the team cannot hurt
    (team_ttk inf) is worth 0; a zero-HP target (team_ttk 0) is worth inf."""
    if math.isinf(team_ttk_s):
        return 0.0
    if team_ttk_s <= 0:
        return math.inf
    return their_dps_on_me / team_ttk_s


def _score_row(
    snapshot: DataSnapshot,
    slot: int,
    me: _Fighter,
    my_def: _Defence,
    enemy: _Fighter,
    allies: Sequence[_Fighter],
    mode: str,
    mode_flag: bool,
) -> FocusRow:
    e_def = _defence(snapshot, enemy, mode, mode_flag)
    e_eff_hp = e_def.effective_hp

    my_dps = _sustained_dps(snapshot, me, e_def, mode, mode_flag)
    team_dps = my_dps + sum(
        _sustained_dps(snapshot, a, e_def, mode, mode_flag)
        for a in allies
    )
    my_burst = float(compute_burst_damage(
        snapshot, me.champion_id, me.level, me.item_ids,
        target_current_hp_pct=1.0,
        **_target_kwargs(e_def, mode, mode_flag),
    ).total_burst_damage)
    combo_pct = 1.0 if e_eff_hp <= 0 else min(1.0, max(0.0, my_burst / e_eff_hp))

    their_dps = _sustained_dps(snapshot, enemy, my_def, mode, mode_flag)
    team_ttk = _ttk(e_eff_hp, team_dps)

    return FocusRow(
        slot=slot,
        champion_id=enemy.champion_id,
        champion_name=enemy.champion_name,
        level=enemy.level,
        item_ids=enemy.item_ids,
        target_max_hp=e_def.max_hp,
        target_effective_hp=e_eff_hp,
        my_dps=my_dps,
        team_dps=team_dps,
        my_ttk_s=_ttk(e_eff_hp, my_dps),
        team_ttk_s=team_ttk,
        their_dps_on_me=their_dps,
        their_ttk_on_me_s=_ttk(my_def.effective_hp, their_dps),
        my_burst=my_burst,
        combo_lethal_hp_pct=combo_pct,
        focus_value=_focus_value(their_dps, team_ttk),
    )


def compute_focus_board(
    snapshot: DataSnapshot,
    me: Fighter,
    enemies: Iterable[Fighter],
    allies: Iterable[Fighter] = (),
    mode: str = "SR",
    apply_mode_modifiers: bool = False,
) -> FocusBoard:
    """Score every enemy against me (and my allies) both ways and order them.

    Each fighter is ``(champion_id, level, item_ids)`` with a snapshot
    champion id (``"Jinx"``, ``"MonkeyKing"``). See the module docstring for
    the composition, the effective-HP definition and the mode rule. Never
    raises; every skipped fighter is named in ``notes``.
    """
    notes: list[str] = [_FULL_HP_NOTE, _DPS_NOTE, _ORDERING_NOTE]
    if isinstance(mode, str) and mode.strip():
        mode_s = canonical_mode(mode.strip())
    else:
        mode_s = "SR"
        notes.append("mode missing or not a string - scored as SR")
    flag = bool(apply_mode_modifiers)

    def _empty(reason_notes: list[str]) -> FocusBoard:
        return FocusBoard(
            me="", me_level=0, mode=mode_s, apply_mode_modifiers=flag,
            my_max_hp=0.0, my_effective_hp=0.0, allies=(), rows=(),
            kill_order=(), danger_order=(), notes=tuple(notes + reason_notes),
        )

    me_f, me_notes = _parse_fighter(snapshot, me, "me")
    notes.extend(me_notes)
    if me_f is None:
        return _empty(["no board: my own champion could not be resolved"])
    try:
        my_def = _defence(snapshot, me_f, mode_s, flag)
    except Exception as exc:  # noqa: BLE001 - never-raises contract
        return _empty([
            f"me {me_f.champion_id}: engine could not resolve this build "
            f"({type(exc).__name__}) - no board"
        ])

    ally_fs: list[_Fighter] = []
    for i, ally in enumerate(allies or ()):
        a_f, a_notes = _parse_fighter(snapshot, ally, f"ally {i}")
        notes.extend(a_notes)
        if a_f is not None:
            ally_fs.append(a_f)

    rows: list[FocusRow] = []
    for slot, enemy in enumerate(enemies or ()):
        e_f, e_notes = _parse_fighter(snapshot, enemy, f"enemy {slot}")
        notes.extend(e_notes)
        if e_f is None:
            continue
        try:
            rows.append(_score_row(
                snapshot, slot, me_f, my_def, e_f, ally_fs, mode_s, flag,
            ))
        except Exception as exc:  # noqa: BLE001 - never-raises contract
            notes.append(
                f"enemy {slot} {e_f.champion_id}: engine could not score this row "
                f"({type(exc).__name__}) - skipped"
            )

    kill_order = tuple(
        r.champion_id for r in sorted(rows, key=lambda r: (-r.focus_value, r.slot))
    )
    danger_order = tuple(
        r.champion_id
        for r in sorted(rows, key=lambda r: (r.their_ttk_on_me_s, r.slot))
    )
    return FocusBoard(
        me=me_f.champion_id,
        me_level=me_f.level,
        mode=mode_s,
        apply_mode_modifiers=flag,
        my_max_hp=my_def.max_hp,
        my_effective_hp=my_def.effective_hp,
        allies=tuple(a.champion_id for a in ally_fs),
        rows=tuple(rows),
        kill_order=kill_order,
        danger_order=danger_order,
        notes=tuple(notes),
    )
