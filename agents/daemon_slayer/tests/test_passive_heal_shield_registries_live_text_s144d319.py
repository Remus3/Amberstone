"""S144-D-319..322 - the DS heal and shield throughput registries match the live text they cite.

WHY. ``_passive_heal_overrides`` (24 rows) and ``_passive_shield_overrides``
(10 rows) copy every heal / shield magnitude out of a quoted
``effects_descriptions`` sentence, and each module docstring claims an
EXHAUSTED roster scan: every heal-verb (shield-verb) form with no structured
heal (shield) block is either seeded or named under a documented exclusion
class. Their tests (items 250-254, 260, S144-D-252, S144-D-260) pin the
arithmetic, the labels and the tuple lengths, never the text, so a patch that
rewrote one of these abilities would move the real value while every guard
stays green, and a new or reworded ability would sit outside both lists
unseen.

* S144-D-319: every shield row's terms equal its live sentence (percent of max
  HP / max mana, the "X : Y (based on level)" lerp endpoints, the AP and
  bonus-health ratios); exact key-set anchor; the attribute names the live
  ability.
* S144-D-320: the shield scan, re-measured at 16.22.1, finds 39 forms, not
  the 38 the docstring quoted. Lucian P (an empowerment triggered by being
  shielded) was unnamed, and three exclusions were wrong: Ambessa W
  ("shields herself ... for 50 : 320 (based on level) (+ 150% bonus AD)"),
  Poppy P ("gaining a shield for 11% : 20% (based on level) of her maximum
  health") and Yone W ("grants himself a shield for 40 : 90 (based on level)
  (+ 65% bonus AD)") are real self-shields on units the eval already
  resolves, filed as "no self/ally shield-magnitude grant". The docstring now
  names them UNSEEDED; the seed is a Tier-2 follow-up (S144-D-323). Renekton W
  (it destroys the target's shields) moves to the shield-strip class, and
  Tahm Kench is spelled by champion id like the heal docstring.
* S144-D-321: every heal row's terms equal its live sentence (linear,
  bilinear "per 100" factors, the Xin Zhao slash-step tiers, the Taric
  per-charge triple); exact key-set anchor; the attribute names the live
  ability.
* S144-D-322: the heal scan, re-measured at 16.22.1, finds 93 forms, not 84,
  and 15 were named nowhere. Two are clean self-heals on existing units:
  Nocturne P ("healing himself for 13 : 30 (based on level) (+ 30% AP) per
  enemy hit") and Elise P ("heal her for 6 / 8 / 10 / 12 (based on Spider
  Form's Rank) (+ 8% AP) on-hit"), so "the LINEAR effects-text heal class is
  now exhausted" no longer held. The docstring names all 15 by class; the
  seed is a Tier-2 follow-up (S144-D-324).

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Guards plus
docstring fixes; no registry value changes, so the scorer output is
byte-identical.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _passive_heal_overrides as heal_mod
from agents.daemon_slayer import _passive_shield_overrides as shield_mod
from agents.daemon_slayer._passive_damage_overrides import (
    _lerp_per_level,
    _per_100,
    _step_per_level,
)
from agents.daemon_slayer._passive_heal_overrides import _PASSIVE_HEAL_OVERRIDES
from agents.daemon_slayer._passive_shield_overrides import _PASSIVE_SHIELD_OVERRIDES

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_HEAL_DOC = heal_mod.__doc__ or ""
_SHIELD_DOC = shield_mod.__doc__ or ""
_KEYS = ("P", "Q", "W", "E", "R")
_HEAL_VERB = re.compile(r"\b(heal(s|ing|ed)?\b|restor)", re.IGNORECASE)
_SHIELD_VERB = re.compile(r"\b(shield|absorb)", re.IGNORECASE)
_NUM = r"([\d.]+)"


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


def _lerp(m: re.Match[str], i: int = 1) -> tuple[float, ...]:
    return _lerp_per_level(_f(m, i), _f(m, i + 1))


def _scan(verb: re.Pattern[str], kind: str) -> set[tuple[str, str, int]]:
    """Forms with no ``kind`` block whose effects text carries ``verb``."""
    out: set[tuple[str, str, int]] = set()
    for champion, kit in _abilities().items():
        for key in _KEYS:
            for form in kit.get(key, []):
                if any(b.get("attribute_kind") == kind for b in form.get("damage_blocks", [])):
                    continue
                if any(verb.search(s) for s in form.get("effects_descriptions", [])):
                    out.add((champion, key, int(form.get("form_index", 0))))
    return out


# Expected terms per row: (pattern, builder(match) -> {field: expected}).
_Spec = tuple[str, Callable[[re.Match[str]], dict[str, Any]]]

_SHIELD_SPECS: dict[tuple[str, str, int], _Spec] = {
    ("Malphite", "P", 0): (
        rf"shield equal to {_NUM}% of his maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Camille", "P", 0): (
        rf"shield equal to {_NUM}% of her maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Vi", "P", 0): (
        rf"shield equal to {_NUM}% of her maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Rakan", "P", 0): (
        rf"shield for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\)",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap"))},
    ),
    ("Shen", "P", 0): (
        rf"shield for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% bonus health\)",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% bonus health"))},
    ),
    ("Yasuo", "P", 0): (
        rf"shield for {_NUM} : {_NUM} \(based on level\) that lasts",
        lambda m: {"linear_terms": ((_lerp(m), ""),)},
    ),
    ("Blitzcrank", "P", 0): (
        rf"shield equal to {_NUM}% of maximum mana",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum mana"),)},
    ),
    ("Skarner", "W", 0): (
        rf"shielding himself equal to {_NUM}% of his maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Volibear", "E", 0): (
        rf"shield equal to {_NUM}% of his maximum health \(\+ {_NUM}% AP\)",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"), (_f(m, 2), "% ap"))},
    ),
    ("Viktor", "Q", 0): (
        rf"shield for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\) for",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap")), "level_scaled": True},
    ),
}

_HEAL_SPECS: dict[tuple[str, str, int], _Spec] = {
    ("Viego", "P", 0): (
        rf"heals himself for {_NUM}% \(\+ {_NUM}% per 100 bonus AD\) \(\+ {_NUM}% per 100 AP\) "
        rf"\(\+ {_NUM}% per 100% bonus attack speed\) of the target's maximum health",
        lambda m: {
            "linear_terms": ((_f(m, 1), "% of target's maximum health"),),
            "bilinear_terms": (
                _per_100(_f(m, 2), "bonus_ad", "target_max_hp"),
                _per_100(_f(m, 3), "ap", "target_max_hp"),
                _per_100(_f(m, 4), "bonus_as", "target_max_hp"),
            ),
        },
    ),
    ("Karma", "W", 1): (
        rf"heals for {_NUM}% \(\+ {_NUM}% per 100 AP\) of her missing health",
        lambda m: {
            "linear_terms": ((_f(m, 1), "% missing health"),),
            "bilinear_terms": (_per_100(_f(m, 2), "ap", "caster_missing_hp"),),
        },
    ),
    ("Kayn", "R", 0): (
        rf"heals Rhaast for {_NUM}% \(\+ {_NUM}% per 100 bonus AD\) of the target's maximum health",
        lambda m: {
            "linear_terms": ((_f(m, 1), "% of target's maximum health"),),
            "bilinear_terms": (_per_100(_f(m, 2), "bonus_ad", "target_max_hp"),),
        },
    ),
    ("Ahri", "P", 0): (
        rf"At 9 stacks, she consumes them to heal herself for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\)",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap"))},
    ),
    ("Alistar", "P", 0): (
        rf"heal himself for {_NUM}% of his maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Aurora", "P", 0): (
        rf"Aurora is healed for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\) every second",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap"))},
    ),
    ("Chogath", "P", 0): (
        rf"it heals for {_NUM} : {_NUM} \(based on level\)",
        lambda m: {"linear_terms": ((_lerp(m), ""),)},
    ),
    ("Evelynn", "P", 0): (
        rf"heals herself for {_NUM} : {_NUM} \(based on level\) every second",
        lambda m: {"linear_terms": ((_lerp(m), ""),)},
    ),
    ("Fiora", "P", 0): (
        rf"heal Fiora for {_NUM} : {_NUM} \(based on level\)",
        lambda m: {"linear_terms": ((_lerp(m), ""),)},
    ),
    ("Gragas", "P", 0): (
        rf"heals himself for {_NUM}% of his maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
    ("Lillia", "P", 0): (
        rf"and {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\) against champions \]",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap"))},
    ),
    ("Maokai", "P", 0): (
        rf"heal him for {_NUM}% : {_NUM}% \(based on level\) maximum health",
        lambda m: {"linear_terms": ((_lerp(m), "% maximum health"),)},
    ),
    ("RekSai", "P", 0): (
        rf"heal for up to {_NUM}% : {_NUM}% \(based on level\) maximum health",
        lambda m: {"linear_terms": ((_lerp(m), "% maximum health"),)},
    ),
    ("Swain", "P", 0): (
        rf"heal for {_NUM}% : {_NUM}% \(based on level\) of his maximum health",
        lambda m: {"linear_terms": ((_lerp(m), "% maximum health"),)},
    ),
    ("Trundle", "P", 0): (
        rf"heals himself for {_NUM}% : {_NUM}% \(based on level\) of the target's maximum health",
        lambda m: {"linear_terms": ((_lerp(m), "% of target's maximum health"),)},
    ),
    ("XinZhao", "P", 0): (
        rf"heal Xin Zhao for {_NUM}% / {_NUM}% / {_NUM}% \(based on level\) of his maximum health \(\+ {_NUM}% AP\)",
        lambda m: {
            "linear_terms": (
                (_step_per_level((_f(m, 1), _f(m, 2), _f(m, 3))), "% maximum health"),
                (_f(m, 4), "% ap"),
            ),
        },
    ),
    ("Yuumi", "P", 0): (
        rf"will heal her for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\)",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap"))},
    ),
    ("Rakan", "Q", 0): (
        rf"heals himself and nearby allied champions for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\)",
        lambda m: {"linear_terms": ((_lerp(m), ""), (_f(m, 3), "% ap")), "level_scaled": True},
    ),
    ("Talon", "Q", 0): (
        rf"Talon heals for {_NUM} : {_NUM} \(based on level\)",
        lambda m: {"linear_terms": ((_lerp(m), ""),), "level_scaled": True},
    ),
    ("Taric", "Q", 0): (
        rf"for {_NUM} \(\+ {_NUM}% AP\) \(\+ {_NUM}% of his maximum health\) per charge",
        lambda m: {
            "linear_terms": (),
            "per_charge": ((_f(m, 1), ""), (_f(m, 2), "% ap"), (_f(m, 3), "% maximum health")),
        },
    ),
    ("Mordekaiser", "R", 0): (
        rf"healing himself for {_NUM}% of their maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% of target's maximum health"),)},
    ),
    ("Illaoi", "P", 0): (
        rf"heals Illaoi for {_NUM}% of her missing health",
        lambda m: {"linear_terms": ((_f(m, 1), "% missing health"),)},
    ),
    ("Zac", "P", 0): (
        rf"consume it to heal for {_NUM}% : {_NUM}% \(based on level\) of his maximum health",
        lambda m: {"linear_terms": ((_lerp(m), "% maximum health"),)},
    ),
    ("DrMundo", "P", 0): (
        rf"healing himself for {_NUM}% of his maximum health",
        lambda m: {"linear_terms": ((_f(m, 1), "% maximum health"),)},
    ),
}


# --- S144-D-319 / S144-D-321: every seeded row matches its live sentence -------


def test_the_shield_registry_is_exactly_the_rows_tested_here() -> None:
    """A new row lands red here until it gets a live-text spec above."""
    assert set(_PASSIVE_SHIELD_OVERRIDES) == set(_SHIELD_SPECS)


def test_the_heal_registry_is_exactly_the_rows_tested_here() -> None:
    assert set(_PASSIVE_HEAL_OVERRIDES) == set(_HEAL_SPECS)


@pytest.mark.parametrize("row", sorted(_SHIELD_SPECS))
def test_every_shield_row_matches_its_live_sentence(row: tuple[str, str, int]) -> None:
    pattern, build = _SHIELD_SPECS[row]
    form = _form(*row)
    entry = _PASSIVE_SHIELD_OVERRIDES[row]
    assert entry.attribute == form["name"]
    expected = build(_one_match(form, pattern))
    assert entry.linear_terms == expected["linear_terms"]
    assert entry.level_scaled is expected.get("level_scaled", False)
    assert entry.bilinear_terms == ()


@pytest.mark.parametrize("row", sorted(_HEAL_SPECS))
def test_every_heal_row_matches_its_live_sentence(row: tuple[str, str, int]) -> None:
    pattern, build = _HEAL_SPECS[row]
    form = _form(*row)
    entry = _PASSIVE_HEAL_OVERRIDES[row]
    assert entry.attribute == form["name"]
    expected = build(_one_match(form, pattern))
    assert entry.linear_terms == expected["linear_terms"]
    assert entry.bilinear_terms == expected.get("bilinear_terms", ())
    assert entry.per_charge == expected.get("per_charge", ())
    assert entry.level_scaled is expected.get("level_scaled", False)


# --- S144-D-320: the shield roster scan --------------------------------------

# Every live shield-verb form with no shield block that is NOT seeded, by the
# docstring's exclusion class (S144-D-320 re-measure at 16.22.1).
_SHIELD_EXCLUDED: dict[tuple[str, str, int], str] = {
    ("Nocturne", "W", 0): "spell shield",
    ("Sivir", "E", 0): "spell shield",
    ("Sett", "W", 0): "damage-stored",
    ("Mordekaiser", "W", 0): "damage-stored",
    ("TahmKench", "E", 0): "damage-stored",
    ("Galio", "R", 0): "re-grant",
    ("Yuumi", "R", 0): "re-grant",
    ("Blitzcrank", "R", 0): "shield-strip",
    ("Rell", "Q", 0): "shield-strip",
    ("Renekton", "W", 0): "shield-strip",
    ("Akshan", "P", 0): "no grant",
    ("Aphelios", "P", 2): "no grant",
    ("Braum", "Q", 0): "no grant",
    ("Braum", "E", 0): "no grant",
    ("Braum", "R", 0): "no grant",
    ("Leona", "Q", 0): "no grant",
    ("Leona", "W", 0): "no grant",
    ("Lucian", "P", 0): "no grant",
    ("Malphite", "W", 0): "no grant",
    ("Mel", "P", 0): "no grant",
    ("Nilah", "P", 0): "no grant",
    ("Nilah", "Q", 0): "no grant",
    ("Nilah", "R", 0): "no grant",
    ("Pantheon", "W", 0): "no grant",
    ("Pantheon", "E", 0): "no grant",
    ("Yuumi", "W", 0): "no grant",
    ("Ambessa", "W", 0): "unseeded",
    ("Poppy", "P", 0): "unseeded",
    ("Yone", "W", 0): "unseeded",
}


def _doc_count(doc: str, pattern: str) -> int:
    hits = re.findall(pattern, doc)
    assert len(hits) == 1, f"{len(hits)} matches for {pattern}"
    return int(hits[0])


def test_every_live_shield_candidate_is_seeded_or_classified() -> None:
    live = _scan(_SHIELD_VERB, "shield")
    assert not set(_SHIELD_EXCLUDED) & set(_PASSIVE_SHIELD_OVERRIDES)
    assert live == set(_PASSIVE_SHIELD_OVERRIDES) | set(_SHIELD_EXCLUDED)


def test_the_shield_docstring_count_is_the_live_scan() -> None:
    live = len(_scan(_SHIELD_VERB, "shield"))
    assert _doc_count(_SHIELD_DOC, r"re-measured (\d+) at 16\.22\.1") == live


@pytest.mark.parametrize("row", sorted(_SHIELD_EXCLUDED))
def test_every_shield_exclusion_is_named_in_the_docstring(row: tuple[str, str, int]) -> None:
    champion = row[0]
    assert re.search(rf"\b{champion}\b", _SHIELD_DOC), champion


def _unseeded_section(doc: str) -> str:
    m = re.search(r"\n  - UNSEEDED [^\n]*(?:\n    [^\n]*)*", doc)
    assert m, "no UNSEEDED exclusion class in the docstring"
    return m.group(0)


@pytest.mark.parametrize(
    ("row", "pattern", "label", "quote"),
    [
        (
            ("Ambessa", "W", 0),
            rf"shields herself at the time of cast for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% bonus AD\)",
            "Ambessa W",
            "{1} : {2} (based on level) (+ {3}% bonus AD)",
        ),
        (
            ("Poppy", "P", 0),
            rf"gaining a shield for {_NUM}% : {_NUM}% \(based on level\) of her maximum health",
            "Poppy P",
            "{1}% : {2}% (based on level) of max HP",
        ),
        (
            ("Yone", "W", 0),
            rf"grants himself a shield for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% bonus AD\)",
            "Yone W",
            "{1} : {2} (based on level) (+ {3}% bonus AD)",
        ),
    ],
)
def test_real_self_shields_are_documented_unseeded(
    row: tuple[str, str, int], pattern: str, label: str, quote: str
) -> None:
    m = _one_match(_form(*row), pattern)
    section = " ".join(_unseeded_section(_SHIELD_DOC).split())
    assert label in section
    assert quote.format(*([None] + list(m.groups()))) in section


def test_the_shield_docstring_drops_the_wrong_exclusion_reasons() -> None:
    assert "exactly these 10" not in _SHIELD_DOC
    assert "buckler = damage passive" not in _SHIELD_DOC
    assert "Yone W (cleave)" not in _SHIELD_DOC
    assert "Akshan P,\n    Ambessa W," not in _SHIELD_DOC


# --- S144-D-322: the heal roster scan ----------------------------------------

_HEAL_EXCLUDED: dict[tuple[str, str, int], str] = {
    # vamp / % of damage dealt
    ("Aatrox", "P", 0): "vamp",
    ("Aatrox", "E", 0): "vamp",
    ("Briar", "P", 0): "vamp",
    ("DrMundo", "Q", 0): "vamp",
    ("Gwen", "P", 0): "vamp",
    ("Kayn", "P", 0): "vamp",
    ("Morgana", "P", 0): "vamp",
    ("Vladimir", "W", 0): "vamp",
    ("Warwick", "P", 0): "vamp",
    ("Warwick", "R", 0): "vamp",
    ("XinZhao", "W", 0): "vamp",
    ("Aphelios", "P", 2): "vamp",
    ("Nilah", "Q", 0): "vamp",
    ("Nilah", "R", 0): "vamp",
    ("Olaf", "E", 0): "vamp",
    ("Camille", "W", 0): "vamp",
    ("Viego", "Q", 0): "vamp",
    ("Trundle", "R", 0): "vamp",
    # resource restores
    ("Akali", "W", 0): "resource",
    ("Ambessa", "P", 0): "resource",
    ("Bard", "P", 0): "resource",
    ("Brand", "P", 0): "resource",
    ("Ezreal", "W", 0): "resource",
    ("Fizz", "W", 0): "resource",
    ("Hwei", "W", 3): "resource",
    ("Jayce", "W", 0): "resource",
    ("Kalista", "E", 0): "resource",
    ("Karthus", "E", 0): "resource",
    ("Kassadin", "W", 0): "resource",
    ("Kennen", "P", 0): "resource",
    ("Kennen", "E", 0): "resource",
    ("Kled", "Q", 1): "resource",
    ("LeeSin", "P", 0): "resource",
    ("Malzahar", "E", 0): "resource",
    ("Shen", "E", 0): "resource",
    ("Smolder", "Q", 0): "resource",
    ("Syndra", "P", 0): "resource",
    ("Velkoz", "Q", 0): "resource",
    ("Xerath", "P", 0): "resource",
    ("Yuumi", "E", 0): "resource",
    ("Zed", "W", 0): "resource",
    # revive / grey health / remount
    ("Anivia", "P", 0): "revive",
    ("Pyke", "P", 0): "revive",
    ("Rengar", "W", 0): "revive",
    ("TahmKench", "E", 0): "revive",
    ("Sion", "P", 0): "revive",
    ("Kled", "P", 0): "revive",
    ("Kled", "P", 1): "revive",
    ("DrMundo", "W", 0): "revive",
    ("Renata", "W", 0): "revive",
    ("KSante", "R", 0): "revive",
    # pet heals
    ("Zyra", "R", 0): "pet",
    ("Naafiri", "E", 0): "pet",
    # %-of-HP damage lines
    ("Sejuani", "P", 0): "damage",
    # bespoke shapes
    ("Kindred", "W", 0): "bespoke",
    ("Darius", "Q", 0): "bespoke",
    ("TwistedFate", "W", 0): "bespoke",
    ("Aphelios", "R", 0): "bespoke",
    ("Nilah", "P", 0): "bespoke",
    ("Elise", "R", 0): "bespoke",
    # no heal magnitude (trigger / amp / hunt / reference)
    ("Warwick", "W", 0): "no heal",
    ("Galio", "W", 0): "no heal",
    ("Khazix", "W", 1): "no heal",
    ("Lucian", "P", 0): "no heal",
    ("Sona", "P", 0): "no heal",
    ("Trundle", "W", 0): "no heal",
    ("Rakan", "P", 0): "no heal",
    # clean self-heals on existing units, not seeded (Tier-2 follow-up)
    ("Nocturne", "P", 0): "unseeded",
    ("Elise", "P", 0): "unseeded",
}


def test_every_live_heal_candidate_is_seeded_or_classified() -> None:
    live = _scan(_HEAL_VERB, "heal")
    assert not set(_HEAL_EXCLUDED) & set(_PASSIVE_HEAL_OVERRIDES)
    assert live == set(_PASSIVE_HEAL_OVERRIDES) | set(_HEAL_EXCLUDED)


def test_the_heal_docstring_count_is_the_live_scan() -> None:
    live = len(_scan(_HEAL_VERB, "heal"))
    assert _doc_count(_HEAL_DOC, r"re-measured (\d+) at 16\.22\.1") == live


@pytest.mark.parametrize("row", sorted(_HEAL_EXCLUDED))
def test_every_heal_exclusion_is_named_in_the_docstring(row: tuple[str, str, int]) -> None:
    champion = row[0]
    assert re.search(rf"\b{champion}\b", _HEAL_DOC), champion


@pytest.mark.parametrize(
    ("row", "pattern", "label", "quote"),
    [
        (
            ("Nocturne", "P", 0),
            rf"healing himself for {_NUM} : {_NUM} \(based on level\) \(\+ {_NUM}% AP\) per enemy hit",
            "Nocturne P",
            "{1} : {2}",
        ),
        (
            ("Elise", "P", 0),
            rf"heal her for {_NUM} / {_NUM} / {_NUM} / {_NUM} \(based on Spider Form's Rank\) \(\+ {_NUM}% AP\)",
            "Elise P",
            "{1} / {2} / {3} / {4}",
        ),
    ],
)
def test_clean_self_heals_are_documented_unseeded(
    row: tuple[str, str, int], pattern: str, label: str, quote: str
) -> None:
    m = _one_match(_form(*row), pattern)
    section = " ".join(_unseeded_section(_HEAL_DOC).split())
    assert label in section
    assert quote.format(*([None] + list(m.groups()))) in section


def test_the_heal_docstring_no_longer_claims_the_linear_class_exhausted() -> None:
    assert "effects-text heal class is now exhausted" not in _HEAL_DOC
