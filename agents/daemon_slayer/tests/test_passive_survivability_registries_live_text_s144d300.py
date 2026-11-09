"""S144-D-300..303 - the DS survivability registries match the live text they cite.

WHY. Four hand-authored registries copy a magnitude out of quoted ability or
item text: ``_passive_health_overrides`` (stacking max health),
``_passive_revive_overrides`` (death-triggered second life),
``_passive_reflect_overrides`` (on-being-hit reflect, champion and item) and
``_passive_survival_window_overrides`` (untargetable / invulnerable windows).
Their tests pin the literals against the patch each was seeded at (16.11.1 or
16.13.1), or against nothing at all, so a patch that rewrites one of these
abilities would move the real value while every guard stays green.

* S144-D-300: Sion's 4 per kill (and the 15 he omits on purpose), Swain's 15
  per Soul Fragment and Cho'Gath's ``Bonus Health Per Stack`` block equal the
  live text; Cho'Gath's per-level tuple is that block over the R1 6-10 / R2
  11-15 / R3 16-18 cadence and the assumed stacks stay under the live 6-stack
  minion cap. The module docstring called stacking health "the SECOND
  EHP-NUMERATOR term (after the revive multiplier)", a claim the survival
  window module also makes and which is older (2026-06-03 against 2026-06-30);
  the ordinal is dropped and pinned.
* S144-D-301: Anivia "restores all of her health" (1.0) and her egg's
  -40 : 20 bonus armor and magic resistance; Zac "is revived with 10 : 50%";
  each cooldown the note states equals the live one. Anivia's note and its
  comment still said the egg resist was "not modeled here", but item 316 seeds
  ``egg_resist_armor`` / ``egg_resist_mr`` on that very entry and item 321 made
  ``compute_ehp``'s ``apply_egg_resist`` default True; the
  ``revive_egg_resist`` docstring still called False "the default". All three
  corrected and pinned.
* S144-D-302: Rammus's Defensive Ball Curl reflect equals the live "15 (+ 10%
  total armor) (+ 10% total magic resistance) magic damage" sentence; the
  Thornmail and Bramble Vest entries equal the live items_meraki Thorns
  passives (DDragon prose carries no magnitude for either, RM-808 fallback);
  every registered item id is live and named as ``_ITEM_REFLECT_NAMES`` says,
  and the Bramble mirror ids the module says do NOT exist are still absent.
* S144-D-303: every ``_PASSIVE_SURVIVAL_WINDOW_OVERRIDES`` ``window_s`` equals
  the seconds in its live sentence, the attribute names the live ability, and
  an R row is amortized at the ult midpoint, every other row at the basic one.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1): every
literal matched its live text. Guards plus docstring / note fixes; no registry
value changes, so the scorer output is byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _passive_health_overrides as health_mod
from agents.daemon_slayer import _passive_revive_overrides as revive_mod
from agents.daemon_slayer import _passive_survival_window_overrides as window_mod
from agents.daemon_slayer._passive_health_overrides import (
    _CHO_HP_PER_STACK,
    _CHO_STACKS,
    _PASSIVE_HEALTH_OVERRIDES,
)
from agents.daemon_slayer._passive_reflect_overrides import (
    _ITEM_REFLECT_NAMES,
    _ITEM_REFLECT_OVERRIDES,
    _PASSIVE_REFLECT_OVERRIDES,
)
from agents.daemon_slayer._passive_revive_overrides import _PASSIVE_REVIVE_OVERRIDES
from agents.daemon_slayer._passive_survival_window_overrides import (
    _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
    _SURVIVAL_WINDOW_BASIC_PROB,
    _SURVIVAL_WINDOW_ULT_PROB,
)
from agents.daemon_slayer.ehp import compute_ehp

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _snapshot(name: str) -> Any:
    raw = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _form(champion: str, key: str, form_index: int = 0) -> dict[str, Any]:
    forms = _snapshot("champion_abilities.json")[champion][key]
    hits = [f for f in forms if f.get("form_index", 0) == form_index]
    assert len(hits) == 1, f"{champion} {key}[{form_index}]: {len(hits)} forms"
    return hits[0]


def _one_match(form: dict[str, Any], pattern: re.Pattern[str]) -> re.Match[str]:
    hits = [m for s in form["effects_descriptions"] if (m := pattern.search(s))]
    assert len(hits) == 1, f"{form['name']}: {len(hits)} sentences match {pattern.pattern}"
    return hits[0]


def _block(form: dict[str, Any], attribute: str) -> list[float]:
    blocks = [b for b in form["damage_blocks"] if b.get("attribute") == attribute]
    assert len(blocks) == 1, f"{form['name']}: {len(blocks)} '{attribute}' blocks"
    mods = blocks[0]["raw_modifiers"]
    assert len(mods) == 1
    return [float(v) for v in mods[0]["values"]]


def _cooldown(form: dict[str, Any]) -> set[float]:
    return {float(v) for v in form["cooldown"]}


_ALL_CHAMPION_KEYS = sorted(
    set(_PASSIVE_HEALTH_OVERRIDES)
    | set(_PASSIVE_REVIVE_OVERRIDES)
    | set(_PASSIVE_REFLECT_OVERRIDES)
    | set(_PASSIVE_SURVIVAL_WINDOW_OVERRIDES)
)


@pytest.mark.parametrize(("champion", "key", "form_index"), _ALL_CHAMPION_KEYS)
def test_every_registry_key_is_a_live_ability_form(champion: str, key: str, form_index: int) -> None:
    assert champion in _snapshot("champions.json")
    _form(champion, key, form_index)


def test_every_champion_row_has_a_live_text_test_here() -> None:
    """A new row lands red here until it gets its own live-text test above."""
    assert set(_PASSIVE_HEALTH_OVERRIDES) == {("Sion", "W", 0), ("Swain", "P", 0), ("Chogath", "R", 0)}
    assert set(_PASSIVE_REVIVE_OVERRIDES) == {("Anivia", "P", 0), ("Zac", "P", 0)}
    assert set(_PASSIVE_REFLECT_OVERRIDES) == {("Rammus", "W", 0)}
    assert len(_ALL_CHAMPION_KEYS) == 16


# --- S144-D-300: stacking max health -----------------------------------------


def test_sion_soul_furnace_per_kill_health_matches_live_text() -> None:
    form = _form("Sion", "W")
    entry = _PASSIVE_HEALTH_OVERRIDES[("Sion", "W", 0)]
    m = _one_match(
        form,
        re.compile(
            r"Sion gains (?P<flat>[\d.]+) bonus health whenever he kills an enemy, "
            r"increased to (?P<big>[\d.]+) for large enemies"
        ),
    )
    assert entry.hp_per_stack == float(m["flat"])
    assert float(m["big"]) > entry.hp_per_stack, "the omitted upside must be larger"
    assert entry.level_scaled_hp is False
    assert entry.attribute == form["name"]


def test_swain_soul_fragment_health_matches_live_text() -> None:
    form = _form("Swain", "P")
    entry = _PASSIVE_HEALTH_OVERRIDES[("Swain", "P", 0)]
    m = _one_match(
        form,
        re.compile(r"For each stack, Swain gains (?P<hp>[\d.]+) bonus health permanently"),
    )
    assert entry.hp_per_stack == float(m["hp"])
    assert entry.level_scaled_hp is False
    assert entry.attribute == form["name"]


def test_chogath_feast_per_stack_health_is_the_live_block_over_the_r_cadence() -> None:
    form = _form("Chogath", "R")
    entry = _PASSIVE_HEALTH_OVERRIDES[("Chogath", "R", 0)]
    by_rank = _block(form, "Bonus Health Per Stack")
    assert len(by_rank) == 3
    cadence = [0] * 5 + [1] * 5 + [2] * 5 + [3] * 3
    expected = tuple(0.0 if r == 0 else by_rank[r - 1] for r in cadence)
    assert tuple(float(v) for v in _CHO_HP_PER_STACK) == expected
    assert entry.hp_per_stack is _CHO_HP_PER_STACK
    assert entry.level_scaled_hp is True
    assert entry.attribute == form["name"]
    cap = _one_match(form, re.compile(r"Only (?P<cap>\d+) stacks can be gained from non-epic"))
    assert max(_CHO_STACKS) <= int(cap["cap"])
    assert all(s == 0 for s in _CHO_STACKS[:5]), "no Feast stacks before the level-6 ult"


def test_only_one_registry_claims_to_be_the_second_numerator_term() -> None:
    claims = [
        mod.__name__ for mod in (health_mod, revive_mod, window_mod) if "SECOND EHP-NUMERATOR" in (mod.__doc__ or "")
    ]
    assert claims == [window_mod.__name__]


# --- S144-D-301: death-triggered second life ---------------------------------


def test_anivia_rebirth_matches_live_text() -> None:
    form = _form("Anivia", "P")
    entry = _PASSIVE_REVIVE_OVERRIDES[("Anivia", "P", 0)]
    _one_match(form, re.compile(r"enters resurrection for [\d.]+ seconds and restores all of her health"))
    assert entry.revived_hp_fraction == 1.0
    assert entry.level_scaled is False
    egg = _one_match(
        form,
        re.compile(
            r"gains (?P<lo>-?[\d.]+) : (?P<hi>-?[\d.]+) \(based on level\) "
            r"bonus armor and bonus magic resistance"
        ),
    )
    for values in (entry.egg_resist_armor, entry.egg_resist_mr):
        assert isinstance(values, tuple)
        assert len(values) == 18
        assert values[0] == pytest.approx(float(egg["lo"]))
        assert values[-1] == pytest.approx(float(egg["hi"]))
    assert _cooldown(form) == {240.0}
    assert "240s cooldown" in entry.note
    assert entry.attribute == form["name"]


def test_zac_cell_division_matches_live_text() -> None:
    form = _form("Zac", "P")
    entry = _PASSIVE_REVIVE_OVERRIDES[("Zac", "P", 0)]
    m = _one_match(
        form,
        re.compile(r"Zac is revived with (?P<lo>[\d.]+) : (?P<hi>[\d.]+)% maximum health"),
    )
    assert entry.level_scaled is True
    assert isinstance(entry.revived_hp_fraction, tuple)
    assert entry.revived_hp_fraction[0] == pytest.approx(float(m["lo"]) / 100.0)
    assert entry.revived_hp_fraction[-1] == pytest.approx(float(m["hi"]) / 100.0)
    assert entry.egg_resist_armor == 0.0
    assert entry.egg_resist_mr == 0.0
    assert _cooldown(form) == {300.0}
    assert "300s cooldown" in entry.note
    assert entry.attribute == form["name"]


def test_revive_notes_do_not_deny_a_modeled_egg_resist() -> None:
    src = inspect.getsource(revive_mod)
    for key, entry in _PASSIVE_REVIVE_OVERRIDES.items():
        if entry.egg_resist_armor or entry.egg_resist_mr:
            assert "not modeled" not in entry.note.lower(), key
    assert "NOT modeled here either" not in src


def test_revive_egg_resist_docstring_names_the_compute_ehp_default() -> None:
    default = inspect.signature(compute_ehp).parameters["apply_egg_resist"].default
    assert default is True
    doc = inspect.getdoc(revive_mod.revive_egg_resist) or ""
    assert "False (default)" not in doc
    assert "defaults True" in doc


# --- S144-D-302: on-being-hit reflect ----------------------------------------


def test_rammus_defensive_ball_curl_reflect_matches_live_text() -> None:
    form = _form("Rammus", "W")
    entry = _PASSIVE_REFLECT_OVERRIDES[("Rammus", "W", 0)]
    m = _one_match(
        form,
        re.compile(
            r"are dealt (?P<base>[\d.]+) \(\+ (?P<ar>[\d.]+)% total armor\) "
            r"\(\+ (?P<mr>[\d.]+)% total magic resistance\) magic damage"
        ),
    )
    assert entry.base == (float(m["base"]),)
    assert entry.caster_armor_pct == float(m["ar"])
    assert entry.caster_mr_pct == float(m["mr"])
    assert entry.damage_type == "MAGIC"
    assert entry.attribute == form["name"]


@cache
def _meraki_thorns(item_id: int) -> str:
    items = _snapshot("items_meraki.json")["items"]
    rows = items.values() if isinstance(items, dict) else items
    hits = [r for r in rows if r.get("id") == item_id]
    assert len(hits) == 1, f"items_meraki: {len(hits)} rows for {item_id}"
    passives = [p for p in hits[0]["passives"] if p.get("name") == "Thorns"]
    assert len(passives) == 1
    return str(passives[0]["effects"])


def test_thornmail_reflect_matches_live_meraki_thorns() -> None:
    text = _meraki_thorns(3075)
    m = re.search(r"deal \{\{as\|(?P<base>[\d.]+) \{\{as\|\(\+ (?P<pct>[\d.]+)% '''bonus''' armor\)", text)
    assert m, text
    entry = _ITEM_REFLECT_OVERRIDES["3075"]
    assert entry.base == (float(m["base"]),)
    assert entry.caster_bonus_armor_pct == float(m["pct"])
    assert entry.damage_type == "MAGIC"


def test_bramble_vest_reflect_matches_live_meraki_thorns() -> None:
    text = _meraki_thorns(3076)
    m = re.search(r"deal \{\{as\|(?P<base>[\d.]+) magic damage\}\}", text)
    assert m, text
    entry = _ITEM_REFLECT_OVERRIDES["3076"]
    assert entry.base == (float(m["base"]),)
    assert entry.caster_bonus_armor_pct == 0.0
    assert entry.damage_type == "MAGIC"


def test_item_reflect_ids_are_live_and_named() -> None:
    items = _snapshot("items.json")
    assert set(_ITEM_REFLECT_OVERRIDES) == set(_ITEM_REFLECT_NAMES)
    for item_id, name in _ITEM_REFLECT_NAMES.items():
        base_id = "3075" if name == "Thornmail" else "3076"
        assert _ITEM_REFLECT_OVERRIDES[item_id] is _ITEM_REFLECT_OVERRIDES[base_id], item_id
    for item_id, name in _ITEM_REFLECT_NAMES.items():
        assert items[item_id]["name"] == name, item_id
    live_ids = {k for k, v in items.items() if v.get("name") in set(_ITEM_REFLECT_NAMES.values())}
    assert live_ids == set(_ITEM_REFLECT_OVERRIDES)


# --- S144-D-303: guaranteed-survival windows ---------------------------------

_SECONDS = r"(?P<s>[\d.]+) seconds"
_WINDOW_SENTENCE: dict[tuple[str, str, int], re.Pattern[str]] = {
    ("Tryndamere", "R", 0): re.compile(r"minimum health threshold for " + _SECONDS),
    ("Kindred", "R", 0): re.compile(
        r"sacred zone .* that lasts for " + _SECONDS + r"\. All units inside the zone gain a minimum health threshold"
    ),
    ("Taric", "R", 0): re.compile(r"become invulnerable for " + _SECONDS),
    ("Kayle", "R", 0): re.compile(r"grants herself or a target allied champion invulnerability for " + _SECONDS),
    ("Lissandra", "R", 0): re.compile(r"Self Cast: .* entering stasis for " + _SECONDS),
    ("Xayah", "R", 0): re.compile(r"becoming ghosted and untargetable for " + _SECONDS),
    ("Vladimir", "W", 0): re.compile(r"becoming untargetable and ghosted for " + _SECONDS),
    ("Elise", "E", 1): re.compile(r"becoming untargetable .* vanishing for up to " + _SECONDS),
    ("Fizz", "E", 0): re.compile(r"while becoming untargetable, balancing on his trident for " + _SECONDS),
    ("Mel", "W", 0): re.compile(r"protective barrier around herself for " + _SECONDS + r", becoming invulnerable"),
}


def test_every_survival_window_row_has_a_live_sentence_pattern() -> None:
    assert set(_WINDOW_SENTENCE) == set(_PASSIVE_SURVIVAL_WINDOW_OVERRIDES)


@pytest.mark.parametrize("row", sorted(_WINDOW_SENTENCE))
def test_survival_window_matches_live_text(row: tuple[str, str, int]) -> None:
    champion, key, form_index = row
    form = _form(champion, key, form_index)
    entry = _PASSIVE_SURVIVAL_WINDOW_OVERRIDES[row]
    m = _one_match(form, _WINDOW_SENTENCE[row])
    assert entry.window_s == float(m["s"])
    assert entry.rank_scaled is False
    assert entry.level_scaled is False
    assert entry.attribute.startswith(form["name"])
    expected_prob = _SURVIVAL_WINDOW_ULT_PROB if key == "R" else _SURVIVAL_WINDOW_BASIC_PROB
    assert entry.conditional_probability == expected_prob
