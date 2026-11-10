"""S144-D-347, S144-D-349, S144-D-350 - the two "EXHAUSTED scan" recitals in
``_passive_damage_overrides`` match a scan anyone can re-run.

WHY. The module docstring closes two seeding passes with an exhaustion claim
(item 249 per-stack, item 513 caster bonus resist). Neither claim was tied to
the live snapshot, and both had drifted from what a re-run finds:

* S144-D-347: item 249 said "of the 15 no_damage P-forms with per stack +
  damage language, only these 4" are per-stack target damage. The literal
  criterion ("per stack" + "damage" over no_damage P-forms) finds 1 form
  (Orianna) even at the 16.11.1 snapshot the claim cites, because Kai'Sa says
  "per Plasma stack" and Darius / Twitch say "For each stack". Garen's named
  per-stack steroid is Courage on his W, not his P. The reproducible scan below
  finds 17 forms; the two the docstring never named are Brand P (the Ablaze
  DoT, per-stack target damage that the item-255 row documents as NOT
  modeled) and Jinx Q (a per-stack attack-speed steroid).
* S144-D-349: item 513 said "all 172 champs"; the snapshot carries 171
  champion keys at both 16.11.1 and 16.22.1. Its stated criterion (no_damage
  forms with "bonus armor" / "bonus magic resist" + "damage") finds 13 forms.
  Five of them deal caster-resist-scaled damage, and the docstring named four:
  Rell P Break the Mold (on-hit 5% total armor + 5% total MR) was missing.
* S144-D-350: the two named rejects carried reasons that later work retired.
  K'Sante P All Out Bonus was "staged, not seeded blind" and is seeded (R50,
  ``_ALL_OUT_BONUS_OVERRIDES``); Rammus W had "no caster total-MR field" and
  is seeded in ``_passive_reflect_overrides`` on the R49 ``caster_mr`` target.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Only
docstring and comment text changed, so the scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from agents.daemon_slayer import _passive_damage_overrides as pdo
from agents.daemon_slayer._passive_damage_overrides import (
    _ALL_OUT_BONUS_OVERRIDES,
    _PASSIVE_DAMAGE_OVERRIDES,
)
from agents.daemon_slayer._passive_reflect_overrides import _PASSIVE_REFLECT_OVERRIDES
from agents.daemon_slayer._resist_damage_coupling import _CHAMPION_RESIST_DAMAGE_COUPLING

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_PDO_PY = _REPO_ROOT / "agents" / "daemon_slayer" / "_passive_damage_overrides.py"
_KEYS = ("P", "Q", "W", "E", "R")

Form = tuple[str, str, int]

_STACK_WORDING = re.compile(
    r"\bper (?:\w+ )?stacks?\b|\beach stack\b|\bbased on (?:\w+ )?stacks\b"
    r"|\bof (?:\w+ ){0,2}stacks\b",
    re.IGNORECASE,
)
_BONUS_RESIST_WORDING = ("bonus armor", "bonus magic resist")
_RESIST_RATIO = re.compile(
    r"[\d.]+% (?:per 100 )?(?:of (?:her|his) )?(?:bonus |total )?"
    r"(?:armor|magic resistance)"
)

# --- the measured partitions (16.22.1) --------------------------------------
_PER_STACK_SEEDED: frozenset[Form] = frozenset(
    {("Kaisa", "P", 0), ("Darius", "P", 0), ("Twitch", "P", 0), ("Orianna", "P", 0)}
)
_PER_STACK_DOCUMENTED_NOT_MODELED: frozenset[Form] = frozenset({("Brand", "P", 0)})
_PER_STACK_NOT_TARGET_DAMAGE: frozenset[Form] = frozenset(
    {
        ("Belveth", "P", 0),
        ("Garen", "W", 0),
        ("Irelia", "P", 0),
        ("Jinx", "Q", 0),
        ("Kayle", "P", 0),
        ("Samira", "P", 0),
        ("Senna", "P", 0),
        ("Volibear", "P", 0),
        ("MonkeyKing", "P", 0),
        ("Mel", "P", 0),
        ("Smolder", "P", 0),
        ("Sona", "P", 0),
    }
)
_RESIST_SEEDED_HERE: frozenset[Form] = frozenset({("Taric", "P", 0), ("Galio", "P", 0)})
_RESIST_SEEDED_ELSEWHERE: frozenset[Form] = frozenset(
    {("KSante", "P", 0), ("Rammus", "W", 0), ("Rell", "P", 0)}
)
_RESIST_STEROID_ONLY: frozenset[Form] = frozenset(
    {
        ("Anivia", "P", 0),
        ("Garen", "W", 0),
        ("Jayce", "R", 1),
        ("Kled", "P", 1),
        ("Ornn", "P", 0),
        ("Sejuani", "P", 0),
        ("Shyvana", "P", 0),
        ("MonkeyKing", "P", 0),
    }
)


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _abilities() -> dict[str, Any]:
    raw = json.loads((_patch_dir() / "champion_abilities.json").read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _no_damage_forms() -> list[tuple[Form, list[str]]]:
    out: list[tuple[Form, list[str]]] = []
    for champion, kit in _abilities().items():
        for key in _KEYS:
            for form in kit.get(key, []):
                if form.get("parse_status") != "no_damage":
                    continue
                form_id = (champion, key, int(form.get("form_index", 0)))
                out.append((form_id, list(form.get("effects_descriptions", []))))
    return out


def _says_damage(texts: list[str]) -> bool:
    return any("damage" in s.lower() for s in texts)


def _per_stack_scan() -> set[Form]:
    return {
        f
        for f, texts in _no_damage_forms()
        if _says_damage(texts) and any(_STACK_WORDING.search(s) for s in texts)
    }


def _bonus_resist_scan() -> set[Form]:
    return {
        f
        for f, texts in _no_damage_forms()
        if _says_damage(texts)
        and any(w in s.lower() for s in texts for w in _BONUS_RESIST_WORDING)
    }


def _resist_scaled_damage(texts: list[str]) -> bool:
    """A sentence that both deals damage and carries a caster-resist ratio."""
    for s in texts:
        for sentence in re.split(r"(?<=\.)\s+", s):
            if "damage" in sentence.lower() and _RESIST_RATIO.search(sentence):
                return True
    return False


def _texts(form: Form) -> list[str]:
    champion, key, index = form
    hits = [f for f in _abilities()[champion][key] if int(f.get("form_index", 0)) == index]
    assert len(hits) == 1, f"{form}: {len(hits)} forms"
    return list(hits[0].get("effects_descriptions", []))


def _flat(text: str) -> str:
    return " ".join(text.split())


def _doc() -> str:
    return _flat(pdo.__doc__ or "")


def _source() -> str:
    """Whole module text with comment markers dropped, so a wrapped comment reads as one line."""
    lines = _PDO_PY.read_text(encoding="utf-8").splitlines()
    return _flat(" ".join(re.sub(r"^\s*#", "", line) for line in lines))


# --- S144-D-347: the per-stack scan -----------------------------------------


def test_the_per_stack_scan_is_the_measured_partition() -> None:
    expected = _PER_STACK_SEEDED | _PER_STACK_DOCUMENTED_NOT_MODELED | _PER_STACK_NOT_TARGET_DAMAGE
    assert len(expected) == 17
    assert _per_stack_scan() == expected


def test_the_literal_item_249_criterion_cannot_reproduce_its_count() -> None:
    literal = {
        f
        for f, texts in _no_damage_forms()
        if f[1] == "P" and any("per stack" in s.lower() and "damage" in s.lower() for s in texts)
    }
    assert literal == {("Orianna", "P", 0)}


def test_exactly_the_four_per_stack_target_damage_forms_carry_a_per_stack_term() -> None:
    with_term = {k for k, e in _PASSIVE_DAMAGE_OVERRIDES.items() if e.per_stack is not None}
    assert with_term == set(_PER_STACK_SEEDED)


def test_brand_p_is_per_stack_damage_its_row_documents_as_not_modeled() -> None:
    texts = _texts(("Brand", "P", 0))
    assert any("Each stack of Ablaze deals damage to the target individually" in s for s in texts)
    entry = _PASSIVE_DAMAGE_OVERRIDES[("Brand", "P", 0)]
    assert entry.per_stack is None
    assert "base Ablaze DoT not modeled" in entry.note


def test_garens_named_per_stack_steroid_is_on_his_w() -> None:
    assert not any("stack" in s.lower() for s in _texts(("Garen", "P", 0)))
    assert any("For each stack, Garen gains" in s for s in _texts(("Garen", "W", 0)))


def test_the_per_stack_recital_names_the_measured_scan() -> None:
    doc = _doc()
    assert "of the 15 no_damage P-forms" not in doc
    assert f'"of [X] stacks" and "damage" number {len(_per_stack_scan())}' in doc
    for name in ("Garen W", "Jinx Q", "Brand P"):
        assert name in doc, name
    assert "the 13 other forms of the 17-form scan" in _source()


# --- S144-D-349 / S144-D-350: the caster bonus-resist sweep -----------------


def test_the_bonus_resist_scan_is_the_measured_partition() -> None:
    expected = _RESIST_SEEDED_HERE | _RESIST_SEEDED_ELSEWHERE | _RESIST_STEROID_ONLY
    assert len(expected) == 13
    assert _bonus_resist_scan() == expected


def test_the_resist_scaled_damage_forms_are_the_five_named_ones() -> None:
    scaled = {f for f in _bonus_resist_scan() if _resist_scaled_damage(_texts(f))}
    assert scaled == set(_RESIST_SEEDED_HERE | _RESIST_SEEDED_ELSEWHERE)


def test_the_two_linear_cases_carry_their_resist_field_here() -> None:
    assert _PASSIVE_DAMAGE_OVERRIDES[("Taric", "P", 0)].bonus_armor_pct > 0.0
    assert _PASSIVE_DAMAGE_OVERRIDES[("Galio", "P", 0)].bonus_mr_pct > 0.0
    for form in _RESIST_STEROID_ONLY | _RESIST_SEEDED_ELSEWHERE:
        entry = _PASSIVE_DAMAGE_OVERRIDES.get(form)
        if entry is not None:
            assert entry.bonus_armor_pct == 0.0, form
            assert entry.bonus_mr_pct == 0.0, form


def test_the_three_other_resist_scaled_forms_are_seeded_in_their_registries() -> None:
    ksante = _ALL_OUT_BONUS_OVERRIDES[("KSante", "P", 0)]
    assert {t[1] for t in ksante.bilinear_terms} == {"caster_bonus_armor", "caster_bonus_mr"}
    assert ksante.conditional_probability < 1.0
    rammus = _PASSIVE_REFLECT_OVERRIDES[("Rammus", "W", 0)]
    assert rammus.caster_armor_pct > 0.0
    assert rammus.caster_mr_pct > 0.0
    rell = _CHAMPION_RESIST_DAMAGE_COUPLING["Rell"]
    assert rell.pct_base == "total"
    assert rell.armor_pct > 0.0
    assert rell.mr_pct > 0.0


def test_the_bonus_resist_recital_names_the_measured_sweep() -> None:
    doc = _doc()
    src = _source()
    assert "172 champs" not in src
    assert "Staged, not seeded blind" not in src
    assert "no caster total-MR" not in src
    assert f"over all {len(_abilities())} champion keys" in doc
    assert f'"bonus magic resist" and "damage" number {len(_bonus_resist_scan())}' in doc
    for name in ("Rell P", "_ALL_OUT_BONUS_OVERRIDES", "_passive_reflect_overrides", "_resist_damage_coupling"):
        assert name in doc, name
        assert src.count(name) >= 2, name
