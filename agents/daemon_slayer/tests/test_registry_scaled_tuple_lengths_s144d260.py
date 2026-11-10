"""S144-D-260..264 - every per-rank and per-level tuple in the DS passive,
ability-amp, item and rune registries is exactly as long as the axis its
reader indexes.

WHY. Every resolver of these tuples CLAMPS its index into the tuple bounds:
``_passive_resist_overrides._value_at_level`` reads a ``rank_scaled`` tuple at
``min(rank_at_level(key, level), len - 1)`` and a ``level_scaled`` one at
``min(level - 1, len - 1)``; the item / rune copies, the health and revive
readers and ``DamageBlock.value_at`` do the same. A clamp never raises, so a
mis-authored tuple is silent: a 3-long tuple on a basic ability reads its
rank-3 value at ranks 4 and 5, a 17-long level tuple reads level 17 at 18, and
a tuple on an entry with NO scaling flag is read at its FIRST element by the
"defensive" branch. No test pinned any of these lengths.

* S144-D-260: every ``rank_scaled`` tuple in the champion-keyed registries is
  exactly the live ability's rank count (the snapshot's cooldown / cost / block
  length for that champion, key and form), every rank ``rank_at_level``
  reaches over levels 1-18 indexes a real element and the last element is
  reached; the key is Q / W / E / R (``rank_at_level('P', ...)`` returns
  ``level - 1``, a LEVEL index); and no entry sets both ``rank_scaled`` and
  ``level_scaled``.
* S144-D-261: every per-level tuple is exactly 18 long - a ``level_scaled``
  value, a field-specific flag (``level_scaled_hp``), a field read at
  ``level - 1`` whatever the flags (``assumed_stacks_by_level``, Anivia's egg
  resists), a P-key value an injector hands to ``DamageBlock.value_at`` (read at
  ``rank_at_level('P', level) = level - 1``), and the item / rune per-level
  tables (``_ITEM_RESIST_GRANTS``, ``_RUNE_FLAT_MITIGATION``,
  ``_RUNE_HEALTH_GRANTS`` and their module-level ``*_BY_LEVEL`` constants),
  plus Jhin's ``_AS_LOCK_OVERRIDES`` ``level_ad_pct`` (its reader does not
  clamp, so a short tuple raises instead of misreading - pinned all the same).
* S144-D-262: no other multi-element tuple exists (it would be read at its
  first element or at an ability rank its author never meant), and every
  scaling flag an entry sets has a tuple in a field THAT flag governs (a flag
  on flat values is a no-op that reads as a scaled grant; a field-specific flag
  such as ``level_scaled_hp`` is checked on its own field, never satisfied by
  an always-per-level sibling).
* S144-D-263: every ``amp_per_rank`` in ``_ABILITY_AMP_OVERRIDES`` and
  ``_CROSS_SPELL_AMP_OVERRIDES`` is 1 long (flat) or exactly the live rank
  count of the ability whose rank ``amp_multiplier`` reads (the entry's own
  key, or ``source_key`` form 0 for a cross-spell amp).
* S144-D-264: each checker flags a planted defect, so an empty or blind
  checker cannot pass.

MEASURED 2026-11-09 (live snapshot, patch 16.22.1, ENGINE 1.291.0): 37
rank-scaled tuples (5 long on basics, 3 long on ults, all equal to the live
rank count), 17 per-level tuples over the champion registries, 64 injector
values (45 P values 18 long; 16 P values and 3 Q/W/E values 1 long), 5 item /
rune registry tuples, 3 module-level tables and the one AS-lock tuple, all 18
long; 8 amp_per_rank tuples (4 flat, 4 equal to the live rank count); ZERO
unflagged multi-element tuples and ZERO flags without a governed tuple. A guard, not a fix: no registry value changes.
The count floors in the tests sit below these figures so an emptied walk
fails while a legitimate new row does not.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest

from agents.daemon_slayer import _rune_flat_mitigation as rune_flat_mod
from agents.daemon_slayer import _rune_health_grants as rune_health_mod
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _CROSS_SPELL_AMP_OVERRIDES,
)
from agents.daemon_slayer._champion_cc_mitigation_overrides import (
    _CHAMPION_CC_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._champion_spell_shield_overrides import (
    _CHAMPION_SPELL_SHIELD_OVERRIDES,
)
from agents.daemon_slayer._item_resist_grants import _ITEM_RESIST_GRANTS
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_FLAT_HP_GRANT_OVERRIDES,
    _PASSIVE_ALLY_GRANT_OVERRIDES,
)
from agents.daemon_slayer._passive_as_lock_overrides import _AS_LOCK_OVERRIDES
from agents.daemon_slayer._passive_damage_overrides import (
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
)
from agents.daemon_slayer._passive_flat_mitigation_overrides import (
    _PASSIVE_FLAT_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._passive_heal_overrides import _PASSIVE_HEAL_OVERRIDES
from agents.daemon_slayer._passive_health_overrides import (
    _PASSIVE_HEALTH_OVERRIDES,
)
from agents.daemon_slayer._passive_mitigation_overrides import (
    _PASSIVE_MITIGATION_OVERRIDES,
)
from agents.daemon_slayer._passive_resist_overrides import (
    _PASSIVE_RESIST_OVERRIDES,
)
from agents.daemon_slayer._passive_revive_overrides import (
    _PASSIVE_REVIVE_OVERRIDES,
)
from agents.daemon_slayer._passive_shield_overrides import (
    _PASSIVE_SHIELD_OVERRIDES,
)
from agents.daemon_slayer._passive_survival_window_overrides import (
    _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
)
from agents.daemon_slayer._rune_flat_mitigation import _RUNE_FLAT_MITIGATION
from agents.daemon_slayer._rune_health_grants import _RUNE_HEALTH_GRANTS
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import rank_at_level

LEVELS = 18
Key = tuple[str, str, int]

CHAMPION_REGISTRIES: dict[str, dict[Key, Any]] = {
    "_CHAMPION_CC_MITIGATION_OVERRIDES": _CHAMPION_CC_MITIGATION_OVERRIDES,
    "_CHAMPION_SPELL_SHIELD_OVERRIDES": _CHAMPION_SPELL_SHIELD_OVERRIDES,
    "_PASSIVE_ALLY_GRANT_OVERRIDES": _PASSIVE_ALLY_GRANT_OVERRIDES,
    "_ALLY_FLAT_HP_GRANT_OVERRIDES": _ALLY_FLAT_HP_GRANT_OVERRIDES,
    "_PASSIVE_DAMAGE_OVERRIDES": _PASSIVE_DAMAGE_OVERRIDES,
    "_ALL_OUT_BONUS_OVERRIDES": _ALL_OUT_BONUS_OVERRIDES,
    "_PASSIVE_FLAT_MITIGATION_OVERRIDES": _PASSIVE_FLAT_MITIGATION_OVERRIDES,
    "_PASSIVE_HEAL_OVERRIDES": _PASSIVE_HEAL_OVERRIDES,
    "_PASSIVE_HEALTH_OVERRIDES": _PASSIVE_HEALTH_OVERRIDES,
    "_PASSIVE_MITIGATION_OVERRIDES": _PASSIVE_MITIGATION_OVERRIDES,
    "_PASSIVE_RESIST_OVERRIDES": _PASSIVE_RESIST_OVERRIDES,
    "_PASSIVE_REVIVE_OVERRIDES": _PASSIVE_REVIVE_OVERRIDES,
    "_PASSIVE_SHIELD_OVERRIDES": _PASSIVE_SHIELD_OVERRIDES,
    "_PASSIVE_SURVIVAL_WINDOW_OVERRIDES": _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
}

# Registries whose values become synthetic DamageBlocks on the ability form, so
# an unflagged value is read by ``DamageBlock.value_at`` at the ability rank
# (P: ``level - 1``; Q/W/E/R: the skill rank).
INJECTORS = frozenset(
    {
        "_PASSIVE_DAMAGE_OVERRIDES",
        "_ALL_OUT_BONUS_OVERRIDES",
        "_PASSIVE_HEAL_OVERRIDES",
        "_PASSIVE_SHIELD_OVERRIDES",
    }
)

# (registry, field) read at ``level - 1`` by its own reader, whatever the flags:
# ``_passive_health_overrides._stacks_at_level`` and
# ``_passive_revive_overrides._egg_value_at_level``.
ALWAYS_PER_LEVEL = frozenset(
    {
        ("_PASSIVE_HEALTH_OVERRIDES", "assumed_stacks_by_level"),
        ("_PASSIVE_REVIVE_OVERRIDES", "egg_resist_armor"),
        ("_PASSIVE_REVIVE_OVERRIDES", "egg_resist_mr"),
    }
)

# (registry, field) -> the flag that scales THAT field alone. The revive
# ``level_scaled`` flag governs ``revived_hp_fraction`` only (its egg resists
# are ALWAYS_PER_LEVEL); the health registry names its own flag.
FIELD_FLAGS: dict[tuple[str, str], str] = {
    ("_PASSIVE_HEALTH_OVERRIDES", "hp_per_stack"): "level_scaled_hp",
    ("_PASSIVE_REVIVE_OVERRIDES", "revived_hp_fraction"): "level_scaled",
}

FIELD_FLAG_REGISTRIES = frozenset(reg for reg, _field in FIELD_FLAGS)

FLAG_FIELDS = ("rank_scaled", "level_scaled", "level_scaled_hp")


def _numeric_tuples(value: Any, path: str) -> Iterator[tuple[str, tuple]]:
    """Yield every all-numeric tuple / list nested anywhere in ``value``."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from _numeric_tuples(getattr(value, f.name), f"{path}.{f.name}")
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _numeric_tuples(v, f"{path}[{k!r}]")
    elif isinstance(value, (tuple, list)) and value:
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
            yield path, tuple(value)
        else:
            for i, v in enumerate(value):
                yield from _numeric_tuples(v, f"{path}[{i}]")


def _entry_tuples(entry: Any) -> Iterator[tuple[str, str, tuple]]:
    """Yield (top-level field, path, tuple) for every numeric tuple in an entry."""
    for f in dataclasses.fields(entry):
        if f.name in FLAG_FIELDS:
            continue
        for path, tup in _numeric_tuples(getattr(entry, f.name), f.name):
            yield f.name, path, tup


def _live_rank_count(ab: AbilitiesSnapshot, key: Key) -> int | None:
    champ, slot, form_index = key
    if not ab.has_champion(champ):
        return None
    forms = ab.get_abilities(champ).get(slot) or ()
    if not 0 <= form_index < len(forms):
        return None
    form = forms[form_index]
    for seq in (form.cooldown, form.cost):
        if seq and len(seq) > 1:
            return len(seq)
    lengths = [len(b.base) for b in form.damage_blocks if b.base and len(b.base) > 1]
    return max(lengths) if lengths else None


def _rank_reach(slot: str) -> int:
    """Highest 0-indexed rank ``rank_at_level`` returns over levels 1-18."""
    return max(rank_at_level(slot, lvl) for lvl in range(1, LEVELS + 1))


def _classify(reg_name: str, key: Key, entry: Any, field: str) -> str:
    """Return the axis a tuple in ``field`` is read on: rank / level / injected / flat."""
    flag = FIELD_FLAGS.get((reg_name, field))
    if flag is not None:
        return "level" if getattr(entry, flag, False) else "flat"
    if (reg_name, field) in ALWAYS_PER_LEVEL:
        return "level"
    if reg_name in FIELD_FLAG_REGISTRIES:
        return "injected" if reg_name in INJECTORS else "flat"
    if getattr(entry, "rank_scaled", False):
        return "rank"
    if getattr(entry, "level_scaled", False):
        return "level"
    if reg_name in INJECTORS:
        return "injected"
    return "flat"


def check_rank_scaled(registries: dict[str, dict[Key, Any]], ab: AbilitiesSnapshot) -> list[str]:
    out: list[str] = []
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            rank = bool(getattr(entry, "rank_scaled", False))
            if rank and getattr(entry, "level_scaled", False):
                out.append(f"{reg_name}{key}: rank_scaled AND level_scaled")
            if not rank:
                continue
            slot = key[1]
            if slot not in {"Q", "W", "E", "R"}:
                out.append(f"{reg_name}{key}: rank_scaled on non-rank key {slot!r}")
                continue
            live = _live_rank_count(ab, key)
            reach = _rank_reach(slot) + 1
            for field, path, tup in _entry_tuples(entry):
                if _classify(reg_name, key, entry, field) != "rank":
                    continue
                if live is None:
                    out.append(f"{reg_name}{key}.{path}: no live rank count")
                elif len(tup) != live:
                    out.append(f"{reg_name}{key}.{path}: {len(tup)} ranks, live {live}")
                if len(tup) != reach:
                    out.append(f"{reg_name}{key}.{path}: {len(tup)} ranks, rank_at_level reaches {reach}")
    return out


def check_per_level(registries: dict[str, dict[Key, Any]]) -> list[str]:
    out: list[str] = []
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            for field, path, tup in _entry_tuples(entry):
                axis = _classify(reg_name, key, entry, field)
                if axis == "level" and len(tup) != LEVELS:
                    out.append(f"{reg_name}{key}.{path}: {len(tup)} levels")
                elif axis == "injected" and key[1] == "P" and len(tup) not in (1, LEVELS):
                    out.append(f"{reg_name}{key}.{path}: P value {len(tup)} long")
    return out


def _governs(reg_name: str, flag: str, field: str) -> bool:
    """True when ``flag`` decides how a tuple in ``field`` is read."""
    if (reg_name, field) in ALWAYS_PER_LEVEL:
        return False
    if reg_name in FIELD_FLAG_REGISTRIES:
        return FIELD_FLAGS.get((reg_name, field)) == flag
    return flag in {"rank_scaled", "level_scaled"}


def check_unflagged(registries: dict[str, dict[Key, Any]], ab: AbilitiesSnapshot) -> list[str]:
    out: list[str] = []
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            tuples = list(_entry_tuples(entry))
            for flag in FLAG_FIELDS:
                if getattr(entry, flag, False) and not any(
                    _governs(reg_name, flag, field) for field, _path, _tup in tuples
                ):
                    out.append(f"{reg_name}{key}: {flag} set, no tuple it governs")
            for field, path, tup in tuples:
                axis = _classify(reg_name, key, entry, field)
                if axis in {"rank", "level"}:
                    continue
                if len(tup) == 1:
                    continue
                if axis == "injected" and key[1] == "P":
                    continue
                if axis == "injected" and len(tup) == _live_rank_count(ab, key):
                    continue
                out.append(f"{reg_name}{key}.{path}: unflagged {len(tup)}-tuple ({axis})")
    return out


def check_flat_registry(name: str, reg: dict[Any, Any], level_flag: str = "level_scaled") -> list[str]:
    """Item / rune registries: a tuple is per-level (18 long) or a flagless 1-tuple."""
    out: list[str] = []
    for key, entry in reg.items():
        flagged = bool(getattr(entry, level_flag, False))
        seen = False
        for field, path, tup in _entry_tuples(entry):
            per_level = flagged or field == "assumed_stacks_by_level"
            if per_level:
                seen = seen or flagged
                if len(tup) != LEVELS:
                    out.append(f"{name}[{key!r}].{path}: {len(tup)} levels")
            elif len(tup) != 1:
                out.append(f"{name}[{key!r}].{path}: unflagged {len(tup)}-tuple")
        if flagged and not seen:
            out.append(f"{name}[{key!r}]: {level_flag} set, no tuple")
    return out


def check_amp_per_rank(registries: dict[str, dict[Key, Any]], ab: AbilitiesSnapshot) -> list[str]:
    """``amp_per_rank`` is flat (1 long) or one value per live rank of the read ability."""
    out: list[str] = []
    for reg_name, reg in registries.items():
        for key, entry in reg.items():
            champ, slot, form_index = key
            source = getattr(entry, "source_key", None)
            read_key = (champ, source, 0) if source else (champ, slot, form_index)
            ranks = entry.amp_per_rank
            if len(ranks) == 1:
                continue
            if read_key[1] not in {"Q", "W", "E", "R"}:
                out.append(f"{reg_name}{key}: per-rank amp read on key {read_key[1]!r}")
                continue
            live = _live_rank_count(ab, read_key)
            if live is None or len(ranks) != live:
                out.append(f"{reg_name}{key}: {len(ranks)} ranks, live {live} ({read_key})")
            elif len(ranks) != _rank_reach(read_key[1]) + 1:
                out.append(f"{reg_name}{key}: {len(ranks)} ranks, rank_at_level reach differs")
    return out


AMP_REGISTRIES: dict[str, dict[Key, Any]] = {
    "_ABILITY_AMP_OVERRIDES": _ABILITY_AMP_OVERRIDES,
    "_CROSS_SPELL_AMP_OVERRIDES": _CROSS_SPELL_AMP_OVERRIDES,
}


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


def _count(registries: dict[str, dict[Key, Any]], axis: str) -> int:
    return sum(
        1
        for reg_name, reg in registries.items()
        for key, entry in reg.items()
        for field, _path, _tup in _entry_tuples(entry)
        if _classify(reg_name, key, entry, field) == axis
    )


# --- S144-D-260 -------------------------------------------------------------


def test_s144d260_rank_scaled_tuples_match_live_rank_count(
    ab: AbilitiesSnapshot,
) -> None:
    assert _count(CHAMPION_REGISTRIES, "rank") >= 30, "rank walk went empty"
    assert check_rank_scaled(CHAMPION_REGISTRIES, ab) == []


def test_s144d260_rank_reach_is_five_on_basics_three_on_ults() -> None:
    assert [_rank_reach(s) + 1 for s in ("Q", "W", "E", "R")] == [5, 5, 5, 3]


# --- S144-D-261 -------------------------------------------------------------


def test_s144d261_champion_per_level_tuples_are_18_long() -> None:
    assert _count(CHAMPION_REGISTRIES, "level") >= 15, "level walk went empty"
    assert _count(CHAMPION_REGISTRIES, "injected") >= 50, "injector walk went empty"
    assert check_per_level(CHAMPION_REGISTRIES) == []


@pytest.mark.parametrize(
    ("name", "reg"),
    [
        ("_ITEM_RESIST_GRANTS", _ITEM_RESIST_GRANTS),
        ("_RUNE_FLAT_MITIGATION", _RUNE_FLAT_MITIGATION),
        ("_RUNE_HEALTH_GRANTS", _RUNE_HEALTH_GRANTS),
    ],
)
def test_s144d261_item_and_rune_per_level_tuples_are_18_long(name: str, reg: dict[Any, Any]) -> None:
    assert reg, f"{name} is empty"
    assert any(True for e in reg.values() for _t in _entry_tuples(e)), f"{name} carries no tuple to check"
    assert check_flat_registry(name, reg) == []


@pytest.mark.parametrize(
    "name",
    [
        "_rune_flat_mitigation._BONE_PLATING_FLAT_BY_LEVEL",
        "_rune_health_grants._GRASP_PROCS_BY_LEVEL",
        "_rune_health_grants._OVERGROWTH_ABSORBED_BY_LEVEL",
    ],
)
def test_s144d261_module_level_by_level_tables_are_18_long(name: str) -> None:
    mod_name, attr = name.split(".")
    mod = {
        "_rune_flat_mitigation": rune_flat_mod,
        "_rune_health_grants": rune_health_mod,
    }[mod_name]
    assert len(getattr(mod, attr)) == LEVELS


def test_s144d261_as_lock_level_tables_are_18_long() -> None:
    assert _AS_LOCK_OVERRIDES, "AS-lock registry is empty"
    lengths = {cid: len(e.level_ad_pct) for cid, e in _AS_LOCK_OVERRIDES.items()}
    assert lengths == dict.fromkeys(_AS_LOCK_OVERRIDES, LEVELS)


# --- S144-D-262 -------------------------------------------------------------


def test_s144d262_no_unflagged_multi_element_tuple_and_no_inert_flag(
    ab: AbilitiesSnapshot,
) -> None:
    assert _count(CHAMPION_REGISTRIES, "injected") >= 50, "walk went empty"
    assert check_unflagged(CHAMPION_REGISTRIES, ab) == []


# --- S144-D-263 -------------------------------------------------------------


def test_s144d263_amp_per_rank_is_flat_or_one_value_per_live_rank(
    ab: AbilitiesSnapshot,
) -> None:
    per_rank = [k for reg in AMP_REGISTRIES.values() for k, e in reg.items() if len(e.amp_per_rank) > 1]
    assert len(per_rank) >= 3, "amp walk went empty"
    assert check_amp_per_rank(AMP_REGISTRIES, ab) == []


# --- S144-D-264: planted defects ---------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Stub:
    value: float | tuple[float, ...] = 0.0
    terms: tuple = ()
    rank_scaled: bool = False
    level_scaled: bool = False


def _plant(key: Key, entry: Any, reg_name: str = "_PASSIVE_RESIST_OVERRIDES") -> dict:
    return {reg_name: {key: entry}}


def test_s144d264_rank_checker_flags_planted_defects(ab: AbilitiesSnapshot) -> None:
    short = _plant(("Hecarim", "W", 0), _Stub(value=(1.0, 2.0, 3.0), rank_scaled=True))
    long_ult = _plant(("Olaf", "R", 0), _Stub(value=(1.0,) * 5, rank_scaled=True))
    nested = _plant(
        ("Amumu", "E", 0),
        _Stub(terms=(((1.0, 2.0, 3.0, 4.0), "ANY"),), rank_scaled=True),
    )
    p_key = _plant(("Ahri", "P", 0), _Stub(value=(1.0,) * 5, rank_scaled=True))
    both = _plant(
        ("Braum", "W", 0),
        _Stub(value=(1.0,) * 5, rank_scaled=True, level_scaled=True),
    )
    good = _plant(("Hecarim", "W", 0), _Stub(value=(1.0,) * 5, rank_scaled=True))
    for planted in (short, long_ult, nested, p_key, both):
        assert check_rank_scaled(planted, ab), planted
    assert check_rank_scaled(good, ab) == []


def test_s144d264_level_checker_flags_planted_defects() -> None:
    short = _plant(("Pantheon", "E", 0), _Stub(value=(1.0,) * 17, level_scaled=True))
    always = {
        "_PASSIVE_REVIVE_OVERRIDES": {
            ("Anivia", "P", 0): dataclasses.replace(
                _PASSIVE_REVIVE_OVERRIDES["Anivia", "P", 0],
                egg_resist_armor=(1.0,) * 17,
            )
        }
    }
    p_inject = _plant(("Ahri", "P", 0), _Stub(value=(1.0,) * 5), "_PASSIVE_HEAL_OVERRIDES")
    for planted in (short, always, p_inject):
        assert check_per_level(planted), planted
    good = _plant(("Pantheon", "E", 0), _Stub(value=(1.0,) * 18, level_scaled=True))
    assert check_per_level(good) == []


def test_s144d264_unflagged_checker_flags_planted_defects(
    ab: AbilitiesSnapshot,
) -> None:
    unflagged = _plant(("Braum", "W", 0), _Stub(value=(1.0,) * 5))
    inert = _plant(("Braum", "W", 0), _Stub(value=5.0, rank_scaled=True))
    q_inject = _plant(("Rakan", "Q", 0), _Stub(value=(1.0,) * 18), "_PASSIVE_HEAL_OVERRIDES")
    chogath_flat = {
        "_PASSIVE_HEALTH_OVERRIDES": {
            ("Chogath", "R", 0): dataclasses.replace(_PASSIVE_HEALTH_OVERRIDES["Chogath", "R", 0], hp_per_stack=5.0)
        }
    }
    anivia_flat = {
        "_PASSIVE_REVIVE_OVERRIDES": {
            ("Anivia", "P", 0): dataclasses.replace(_PASSIVE_REVIVE_OVERRIDES["Anivia", "P", 0], level_scaled=True)
        }
    }
    for planted in (unflagged, inert, q_inject, chogath_flat, anivia_flat):
        assert check_unflagged(planted, ab), planted
    p_inject = _plant(("Ahri", "P", 0), _Stub(value=(1.0,) * 18), "_PASSIVE_HEAL_OVERRIDES")
    assert check_unflagged(p_inject, ab) == []


def test_s144d264_flat_registry_checker_flags_planted_defects() -> None:
    assert check_flat_registry("x", {"1": _Stub(value=(1.0,) * 17, level_scaled=True)})
    assert check_flat_registry("x", {"1": _Stub(value=(1.0, 2.0))})
    assert check_flat_registry("x", {"1": _Stub(value=1.0, level_scaled=True)})
    assert check_flat_registry("x", {"1": _Stub(value=(1.0,) * 18, level_scaled=True)}) == []


def test_s144d264_amp_checker_flags_planted_defects(ab: AbilitiesSnapshot) -> None:
    illaoi = _ABILITY_AMP_OVERRIDES["Illaoi", "Q", 0]
    asol = _CROSS_SPELL_AMP_OVERRIDES["AurelionSol", "Q", 0]
    short = {"a": {("Illaoi", "Q", 0): dataclasses.replace(illaoi, amp_per_rank=(0.1, 0.2, 0.3))}}
    cross = {"a": {("AurelionSol", "Q", 0): dataclasses.replace(asol, source_key="R")}}
    p_key = {"a": {("Illaoi", "P", 0): illaoi}}
    for planted in (short, cross, p_key):
        assert check_amp_per_rank(planted, ab), planted
    flat = {"a": {("Illaoi", "Q", 0): dataclasses.replace(illaoi, amp_per_rank=(0.1,))}}
    assert check_amp_per_rank(flat, ab) == []
