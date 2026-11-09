"""S144-D-344..346 - the DS passive damage registry matches the live text it cites.

WHY. ``_passive_damage_overrides`` (34 rows in ``_PASSIVE_DAMAGE_OVERRIDES``
plus the K'Sante row in ``_ALL_OUT_BONUS_OVERRIDES``) copies every damage
magnitude out of a quoted ``effects_descriptions`` sentence (or, for the two
Slice B on-hit riders, out of the form's structured max-rank block). Its tests
(items 247-255, 513, RM-42, A-07, S144-D-252, S144-D-260) pin the arithmetic,
the routing and the tuple lengths, never the text, so a patch that rewrote one
of these abilities would move the real value while every guard stays green.

* S144-D-344: every text-sourced row's terms equal its live sentence - the
  "X : Y (based on level)" lerp endpoints, the "X / Y / Z (based on level)"
  step tiers, every AP / AD / bonus-AD / bonus-resist ratio, the percent-of-HP
  terms, the "per 100" bilinear factors, the per-stack terms and the damage
  type - and every term the sentence does not state stays at its default.
  Exact key-set anchor; the attribute names the live ability or a sub-effect
  its text names. Modelling choices (``cadence``, ``assumed_stacks``,
  ``conditional_probability``) are documented in each row's note and are not
  text, so they are not pinned here.
* S144-D-345: the two structured-sourced Slice B riders (Kayle E, Kog'Maw W)
  equal their live max-rank ``damage_blocks``, and Kog'Maw's folded uptime
  equals the live "for the next N seconds" over the live max-rank cooldown;
  the K'Sante All Out Bonus row equals its live sentence.
* S144-D-346: ``per_second_aura_entry``'s docstring recited "other 32 entries
  are on_hit (25), dot (4) and per_fight (3)"; measured at HEAD the other rows
  are 33 (on_hit 26). The docstring now carries the measured counts and a
  guard derives them; ``rank.py`` no longer recites a stale present-tense
  registry size.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Every row
matched its live text; the only fixes are the two count recitals, so the
scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _passive_damage_overrides as pdo
from agents.daemon_slayer._passive_damage_overrides import (
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
    PassiveDamageEntry,
    PerStackTerm,
    _lerp_per_level,
    _per_100,
    _step_per_level,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_RANK_PY = _REPO_ROOT / "agents" / "daemon_slayer" / "rank.py"
_LEVELS = 18
_N = r"([\d.]+)"
_STEPS = r"((?:[\d.]+ / )+[\d.]+)"
_PCT_STEPS = r"((?:[\d.]+% / )+[\d.]+)%"
_LVL = r"\(based on level\)"
_DT = r"(?P<dt>magic|physical|true)"

_SCALAR_FIELDS = (
    "bonus_ad_pct",
    "ap_pct",
    "total_ad_pct",
    "target_max_hp_pct",
    "target_current_hp_pct",
    "target_missing_hp_pct",
    "bonus_armor_pct",
    "bonus_mr_pct",
)
_STACK_FIELDS = ("base", *_SCALAR_FIELDS)


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _abilities() -> dict[str, Any]:
    raw = json.loads((_patch_dir() / "champion_abilities.json").read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _form(champion: str, key: str, form_index: int = 0) -> dict[str, Any]:
    hits = [f for f in _abilities()[champion][key] if f.get("form_index", 0) == form_index]
    assert len(hits) == 1, f"{champion} {key}[{form_index}]: {len(hits)} forms"
    return hits[0]


def _one_match(form: dict[str, Any], pattern: str) -> re.Match[str]:
    rx = re.compile(pattern)
    hits = [m for s in form["effects_descriptions"] if (m := rx.search(s))]
    assert len(hits) == 1, f"{form['name']}: {len(hits)} sentences match {pattern}"
    return hits[0]


def _f(m: re.Match[str], i: int) -> float:
    return float(m.group(i))


def _lerp(m: re.Match[str], i: int) -> tuple[float, ...]:
    return _lerp_per_level(_f(m, i), _f(m, i + 1))


def _step(m: re.Match[str], i: int) -> tuple[float, ...]:
    return _step_per_level(tuple(float(v.rstrip("%")) for v in m.group(i).split(" / ")))


def _dt(m: re.Match[str]) -> str:
    return m.group("dt").upper()


def _levels(value: Any) -> tuple[float, ...]:
    """Per-level view with ``DamageBlock.value_at`` clamping (short tuples hold their last value)."""
    if isinstance(value, tuple):
        if not value:
            return (0.0,) * _LEVELS
        return tuple(float(value[min(i, len(value) - 1)]) for i in range(_LEVELS))
    return (float(value),) * _LEVELS


def _problems(entry: PassiveDamageEntry, expected: dict[str, Any]) -> list[str]:
    """Every field the expectation names must match; every other scaling field stays default."""
    out: list[str] = []
    if entry.damage_type != expected["damage_type"]:
        out.append(f"damage_type {entry.damage_type} != {expected['damage_type']}")
    for name in ("base", *_SCALAR_FIELDS):
        got = _levels(getattr(entry, name))
        want = _levels(expected.get(name, 0.0))
        if got != pytest.approx(want, abs=1e-5):
            out.append(f"{name} {got} != {want}")
    want_bi = expected.get("bilinear_terms", ())
    got_bi = entry.bilinear_terms
    if [t[1:] for t in got_bi] != [t[1:] for t in want_bi] or [t[0] for t in got_bi] != pytest.approx(
        [t[0] for t in want_bi], abs=1e-9
    ):
        out.append(f"bilinear_terms {got_bi} != {want_bi}")
    want_stack = expected.get("per_stack")
    if (entry.per_stack is None) != (want_stack is None):
        out.append(f"per_stack {entry.per_stack} != {want_stack}")
    elif want_stack is not None:
        for name in _STACK_FIELDS:
            got = _levels(getattr(entry.per_stack, name))
            want = _levels(want_stack.get(name, 0.0))
            if got != pytest.approx(want, abs=1e-5):
                out.append(f"per_stack.{name} {got} != {want}")
    return out


# Expected terms per row: (pattern, builder(match) -> {field: expected}).
_Spec = tuple[str, Callable[[re.Match[str]], dict[str, Any]]]


def _flat_lerp(prefix: str, ratios: tuple[tuple[str, str], ...], suffix: str = "") -> _Spec:
    """``<prefix>X : Y (based on level) (+ R% <label>)... bonus <type> damage``."""
    pattern = rf"{prefix}{_N} : {_N} {_LVL}"
    for _field, label in ratios:
        pattern += rf" \(\+ {_N}% {label}\)"
    pattern += rf" (?:bonus )?(?:modified )?{_DT} damage{suffix}"

    def build(m: re.Match[str]) -> dict[str, Any]:
        out: dict[str, Any] = {"base": _lerp(m, 1), "damage_type": _dt(m)}
        for i, (field, _label) in enumerate(ratios):
            out[field] = _f(m, 3 + i)
        return out

    return pattern, build


_TEXT_SPECS: dict[tuple[str, str, int], _Spec] = {
    ("Ziggs", "P", 0): _flat_lerp("empowers his next basic attack to deal ", (("ap_pct", "AP"),)),
    ("Lux", "P", 0): _flat_lerp("consume the mark to deal ", (("ap_pct", "AP"),)),
    ("Warwick", "P", 0): _flat_lerp(
        "Warwick deals ", (("bonus_ad_pct", "bonus AD"), ("ap_pct", "AP")), " on-hit"
    ),
    ("Akali", "P", 0): _flat_lerp(
        "range doubled and deal ", (("bonus_ad_pct", "bonus AD"), ("ap_pct", "AP"))
    ),
    ("Khazix", "P", 0): _flat_lerp("against an enemy champion to deal ", (("bonus_ad_pct", "bonus AD"),)),
    ("Qiyana", "P", 0): _flat_lerp(
        "basic abilities deal ", (("bonus_ad_pct", "bonus AD"), ("ap_pct", "AP"))
    ),
    ("Vex", "P", 0): _flat_lerp("Gloom's detonation deals ", (("ap_pct", "AP"),)),
    ("Sona", "P", 0): _flat_lerp("uncancellable windup, deal ", (("ap_pct", "AP"),)),
    ("Velkoz", "P", 0): _flat_lerp("The third stack consumes them all to deal ", (("ap_pct", "AP"),)),
    ("Ekko", "P", 0): _flat_lerp("The third stack consumes them all to deal ", (("ap_pct", "AP"),)),
    ("Taric", "P", 0): _flat_lerp("attack speed, deal ", (("bonus_armor_pct", "bonus armor"),)),
    ("Galio", "P", 0): _flat_lerp(
        "40% bonus attack speed and deal ",
        (("total_ad_pct", "AD"), ("ap_pct", "AP"), ("bonus_mr_pct", "bonus magic resistance")),
    ),
    ("Orianna", "P", 0): (
        rf"empowered to deal {_N} : {_N} {_LVL} \(\+ {_N}% AP\) bonus {_DT} damage on-hit, "
        rf"increased by\[ [\d.]+% \]\[ {_N} : {_N} {_LVL} \(\+ {_N}% AP\) \]per stack",
        lambda m: {
            "base": _lerp(m, 1),
            "ap_pct": _f(m, 3),
            "damage_type": _dt(m),
            "per_stack": {"base": _lerp(m, 5), "ap_pct": _f(m, 7)},
        },
    ),
    ("Kaisa", "P", 0): (
        rf"deal {_N} : {_N} {_LVL} \(\+ {_N} : {_N} {_LVL} per Plasma stack before application\) "
        rf"\(\+ {_N}% : {_N}% \(based on Plasma stacks before application\) AP\) bonus {_DT} damage",
        lambda m: {
            "base": _lerp(m, 1),
            "ap_pct": _f(m, 5),
            "damage_type": _dt(m),
            "per_stack": {
                "base": _lerp(m, 3),
                "ap_pct": (_f(m, 6) - _f(m, 5)) / (_kaisa_max_stacks() - 1),
            },
        },
    ),
    ("Darius", "P", 0): (
        rf"For each stack, the target is dealt\[ {_N} : {_N} {_LVL} \(\+ {_N}% bonus AD\) "
        rf"total {_DT} damage over the duration",
        lambda m: {
            "damage_type": _dt(m),
            "per_stack": {"base": _lerp(m, 1), "bonus_ad_pct": _f(m, 3)},
        },
    ),
    ("Twitch", "P", 0): (
        rf"\]\[ {_STEPS} {_LVL} \(\+ {_N}% AP\) total {_DT} damage over the duration, \]",
        lambda m: {
            "damage_type": _dt(m),
            "per_stack": {"base": _step(m, 1), "ap_pct": _f(m, 2)},
        },
    ),
    ("Gangplank", "P", 0): (
        rf"dealing them\[ {_N} : {_N} {_LVL} \(\+ {_N}% bonus AD\) \(\+ 2 per 1% critical strike "
        rf"chance\) bonus {_DT} damage over 2\.5 seconds",
        lambda m: {"base": _lerp(m, 1), "bonus_ad_pct": _f(m, 3), "damage_type": _dt(m)},
    ),
    ("Mordekaiser", "P", 0): (
        rf"deals\[ {_N} \(\+ {_N}% AP\) \(\+ {_N}% : {_N}% {_LVL} of target's maximum health\) "
        rf"{_DT} damage every second",
        lambda m: {
            "base": _f(m, 1),
            "ap_pct": _f(m, 2),
            "target_max_hp_pct": _lerp(m, 3),
            "damage_type": _dt(m),
        },
    ),
    ("Aatrox", "P", 0): (
        rf"deal bonus {_DT} damage equal to {_N}% : {_N}% {_LVL} of the target's maximum health",
        lambda m: {"target_max_hp_pct": _lerp(m, 2), "damage_type": _dt(m)},
    ),
    ("JarvanIV", "P", 0): (
        rf"deal bonus {_DT} damage equal to {_N}% of the target's current health",
        lambda m: {"target_current_hp_pct": _f(m, 2), "damage_type": _dt(m)},
    ),
    ("Zed", "P", 0): (
        rf"empowered to deal {_PCT_STEPS} {_LVL} of the target's maximum health as bonus {_DT} damage",
        lambda m: {"target_max_hp_pct": _step(m, 1), "damage_type": _dt(m)},
    ),
    ("Akshan", "P", 0): (
        rf"fires an additional shot after a delay that deals {_N}% AD {_DT} damage",
        lambda m: {"total_ad_pct": _f(m, 1), "damage_type": _dt(m)},
    ),
    ("Caitlyn", "P", 0): (
        rf"uncancellable windup and deal {_PCT_STEPS} {_LVL} \(\+ \([^)]*\) critical strike chance\) "
        rf"AD bonus {_DT} damage",
        lambda m: {"total_ad_pct": _step(m, 1), "damage_type": _dt(m)},
    ),
    ("Gwen", "P", 0): (
        rf"deal bonus {_DT} damage equal to {_N}% \(\+ {_N}% per 100 AP\) of the target's maximum health",
        lambda m: {
            "target_max_hp_pct": _f(m, 2),
            "bilinear_terms": (_per_100(_f(m, 3), "ap", "target_max_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Aurora", "P", 0): (
        rf"consumes them all to deal bonus {_DT} damage equal to {_N}% \(\+ {_N}% per 100 AP\) "
        rf"of the target's maximum health",
        lambda m: {
            "target_max_hp_pct": _f(m, 2),
            "bilinear_terms": (_per_100(_f(m, 3), "ap", "target_max_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Lillia", "P", 0): (
        rf"which deals\[ {_N}% \(\+ {_N}% per 100 AP\) of the target's maximum health total {_DT} "
        rf"damage over 3 seconds",
        lambda m: {
            "target_max_hp_pct": _f(m, 1),
            "bilinear_terms": (_per_100(_f(m, 2), "ap", "target_max_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Renata", "P", 0): (
        rf"the attack also deals bonus {_DT} damage equal to {_N}% : {_N}% {_LVL} "
        rf"\(\+ {_N}% per 100 AP\) of the target's maximum health",
        lambda m: {
            "target_max_hp_pct": _lerp(m, 2),
            "bilinear_terms": (_per_100(_f(m, 4), "ap", "target_max_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Brand", "P", 0): (
        rf"dealt {_DT} damage equal to {_N}% : {_N}% {_LVL} \(\+ {_N}% per 100 AP\) "
        rf"of their maximum health",
        lambda m: {
            "target_max_hp_pct": _lerp(m, 2),
            "bilinear_terms": (_per_100(_f(m, 4), "ap", "target_max_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Ekko", "W", 0): (
        rf"basic attacks deal bonus {_DT} damage equal to {_N}% \(\+ {_N}% per 100 AP\) "
        rf"of the target's missing health",
        lambda m: {
            "target_missing_hp_pct": _f(m, 2),
            "bilinear_terms": (_per_100(_f(m, 3), "ap", "target_missing_hp"),),
            "damage_type": _dt(m),
        },
    ),
    ("Jhin", "P", 0): (
        rf"deals bonus {_DT} damage equal to {_PCT_STEPS} {_LVL} of the target's missing health",
        lambda m: {"target_missing_hp_pct": _step(m, 2), "damage_type": _dt(m)},
    ),
    ("KSante", "P", 0): (
        rf"dealing {_N} \(\+ {_N}% : {_N}% {_LVL} of target's maximum health\) bonus {_DT} damage",
        lambda m: {"base": _f(m, 1), "target_max_hp_pct": _lerp(m, 2), "damage_type": _dt(m)},
    ),
    ("Sejuani", "P", 0): (
        rf"consume the mark to deal bonus {_DT} damage equal to {_N}% of their maximum health",
        lambda m: {"target_max_hp_pct": _f(m, 2), "damage_type": _dt(m)},
    ),
}

_ALL_OUT_SPECS: dict[tuple[str, str, int], _Spec] = {
    ("KSante", "P", 0): (
        rf"All Out Bonus: .* deal bonus {_DT} damage equal to {_N}% \(\+ {_N}% per 100 bonus armor\) "
        rf"\(\+ {_N}% per 100 bonus magic resistance\) of the target's maximum health",
        lambda m: {
            "target_max_hp_pct": _f(m, 2),
            "bilinear_terms": (
                _per_100(_f(m, 3), "caster_bonus_armor", "target_max_hp"),
                _per_100(_f(m, 4), "caster_bonus_mr", "target_max_hp"),
            ),
            "damage_type": _dt(m),
        },
    ),
}

# Slice B riders sourced from the form's structured max-rank block, not prose.
_STRUCTURED_KEYS = frozenset({("Kayle", "E", 0), ("KogMaw", "W", 0)})


def _kaisa_max_stacks() -> int:
    m = _one_match(_form("Kaisa", "P"), r"Plasma to enemies for [\d.]+ seconds, .* stacking up to (\d+) times")
    return int(m.group(1))


def _block(form: dict[str, Any], attribute: str) -> dict[str, Any]:
    hits = [b for b in form["damage_blocks"] if b.get("attribute") == attribute]
    assert len(hits) == 1, f"{form['name']}: {len(hits)} blocks named {attribute}"
    return hits[0]


def _expected_text(key: tuple[str, str, int], specs: dict[tuple[str, str, int], _Spec]) -> dict[str, Any]:
    pattern, build = specs[key]
    return build(_one_match(_form(*key), pattern))


def _expected_kayle() -> dict[str, Any]:
    form = _form("Kayle", "E")
    block = _block(form, "Passive Damage")
    assert block["attribute_kind"] == "damage"
    _one_match(form, rf"Passive: Kayle deals bonus {_DT} damage on-hit\.")
    return {
        "base": (block["base"][-1],),
        "bonus_ad_pct": block["bonus_ad_pct"][-1],
        "ap_pct": block["ap_pct"][-1],
        "damage_type": form["damage_type"],
    }


def _expected_kogmaw() -> dict[str, Any]:
    form = _form("KogMaw", "W")
    block = _block(form, "Bonus Magic Damage")
    assert block["attribute_kind"] == "damage"
    (mod,) = block["unparsed_modifiers"]
    assert set(mod["units"]) == {"% per 100 AP"}
    duration = _f(_one_match(form, rf"basic attacks for the next {_N} seconds"), 1)
    uptime = duration / form["cooldown"][-1]
    return {
        "target_max_hp_pct": round(block["target_max_hp_pct"][-1] * uptime, 6),
        "bilinear_terms": (_per_100(round(mod["values"][-1] * uptime, 6), "ap", "target_max_hp"),),
        "damage_type": form["damage_type"],
    }


_STRUCTURED_BUILDERS: dict[tuple[str, str, int], Callable[[], dict[str, Any]]] = {
    ("Kayle", "E", 0): _expected_kayle,
    ("KogMaw", "W", 0): _expected_kogmaw,
}


# --- S144-D-344: text-sourced rows ------------------------------------------


def test_every_registry_row_has_exactly_one_source() -> None:
    assert set(_TEXT_SPECS) | _STRUCTURED_KEYS == set(_PASSIVE_DAMAGE_OVERRIDES)
    assert not set(_TEXT_SPECS) & _STRUCTURED_KEYS
    assert set(_ALL_OUT_SPECS) == set(_ALL_OUT_BONUS_OVERRIDES)
    assert set(_STRUCTURED_BUILDERS) == _STRUCTURED_KEYS


@pytest.mark.parametrize("key", sorted(_TEXT_SPECS), ids=lambda k: f"{k[0]}-{k[1]}{k[2]}")
def test_text_row_terms_equal_live_sentence(key: tuple[str, str, int]) -> None:
    assert _problems(_PASSIVE_DAMAGE_OVERRIDES[key], _expected_text(key, _TEXT_SPECS)) == []


@pytest.mark.parametrize(
    ("registry", "key"),
    [(_PASSIVE_DAMAGE_OVERRIDES, k) for k in sorted(_PASSIVE_DAMAGE_OVERRIDES)]
    + [(_ALL_OUT_BONUS_OVERRIDES, k) for k in sorted(_ALL_OUT_BONUS_OVERRIDES)],
    ids=lambda v: f"{v[0]}-{v[1]}{v[2]}" if isinstance(v, tuple) else "",
)
def test_attribute_names_the_live_ability(
    registry: dict[tuple[str, str, int], PassiveDamageEntry], key: tuple[str, str, int]
) -> None:
    form = _form(*key)
    attribute = registry[key].attribute
    assert attribute == form["name"] or any(attribute in s for s in form["effects_descriptions"])


def test_comparator_flags_a_drifted_row() -> None:
    """Negative control: a moved endpoint, a dropped ratio and a stray term each fail."""
    key = ("Ziggs", "P", 0)
    entry = _PASSIVE_DAMAGE_OVERRIDES[key]
    expected = _expected_text(key, _TEXT_SPECS)
    assert _problems(entry, expected) == []
    assert _problems(replace(entry, base=_lerp_per_level(20.0, 161.0)), expected)
    assert _problems(replace(entry, ap_pct=0.0), expected)
    assert _problems(replace(entry, bonus_ad_pct=10.0), expected)
    assert _problems(replace(entry, damage_type="PHYSICAL"), expected)
    stacked = replace(entry, per_stack=PerStackTerm(base=(1.0,)))
    assert _problems(stacked, expected)
    gwen = ("Gwen", "P", 0)
    g_entry = _PASSIVE_DAMAGE_OVERRIDES[gwen]
    g_expected = _expected_text(gwen, _TEXT_SPECS)
    assert _problems(replace(g_entry, bilinear_terms=(_per_100(0.56, "ap", "target_max_hp"),)), g_expected)
    assert _problems(replace(g_entry, bilinear_terms=(_per_100(0.55, "ap", "target_missing_hp"),)), g_expected)


def test_step_rows_parse_every_live_tier() -> None:
    """The slash-step rows carry exactly the tier count the live text names (Zed / Caitlyn / Jhin 3, Twitch 5)."""
    tiers = {
        ("Zed", "P", 0): (_PASSIVE_DAMAGE_OVERRIDES[("Zed", "P", 0)].target_max_hp_pct, 3),
        ("Caitlyn", "P", 0): (_PASSIVE_DAMAGE_OVERRIDES[("Caitlyn", "P", 0)].total_ad_pct, 3),
        ("Jhin", "P", 0): (_PASSIVE_DAMAGE_OVERRIDES[("Jhin", "P", 0)].target_missing_hp_pct, 3),
        ("Twitch", "P", 0): (_PASSIVE_DAMAGE_OVERRIDES[("Twitch", "P", 0)].per_stack.base, 5),
    }
    for key, (values, count) in tiers.items():
        assert len(set(_levels(values))) == count, key


# --- S144-D-345: structured riders and the All Out row ----------------------


@pytest.mark.parametrize("key", sorted(_STRUCTURED_KEYS), ids=lambda k: f"{k[0]}-{k[1]}{k[2]}")
def test_structured_rider_equals_live_max_rank_block(key: tuple[str, str, int]) -> None:
    assert _problems(_PASSIVE_DAMAGE_OVERRIDES[key], _STRUCTURED_BUILDERS[key]()) == []


def test_kogmaw_uptime_is_the_live_duration_over_the_live_cooldown() -> None:
    form = _form("KogMaw", "W")
    duration = _f(_one_match(form, rf"basic attacks for the next {_N} seconds"), 1)
    assert (duration, form["cooldown"][-1]) == (8.0, 17.0)


def test_all_out_bonus_row_equals_live_sentence() -> None:
    key = ("KSante", "P", 0)
    assert _problems(_ALL_OUT_BONUS_OVERRIDES[key], _expected_text(key, _ALL_OUT_SPECS)) == []


# --- S144-D-346: count recitals ---------------------------------------------


def test_per_second_docstring_cadence_counts_are_measured() -> None:
    doc = pdo.per_second_aura_entry.__doc__ or ""
    m = re.search(
        r"other (\d+) entries\s+are ``on_hit`` \((\d+)\), ``dot`` \((\d+)\) and\s+``per_fight`` \((\d+)\)",
        doc,
    )
    assert m, "per_second_aura_entry docstring lost its cadence recital"
    counts = Counter(e.cadence for e in _PASSIVE_DAMAGE_OVERRIDES.values())
    assert set(counts) == {"on_hit", "dot", "per_fight", "per_second"}
    others = len(_PASSIVE_DAMAGE_OVERRIDES) - counts["per_second"]
    assert tuple(int(g) for g in m.groups()) == (others, counts["on_hit"], counts["dot"], counts["per_fight"])


def test_rank_py_recites_no_present_tense_registry_size() -> None:
    text = _RANK_PY.read_text(encoding="utf-8")
    assert not re.search(r"``_passive_damage_overrides``\s+holds\s+\d+\s+entries", text)
