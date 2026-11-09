"""S144-D-359..362 - the item-238 ability correction registry matches the live text it cites.

WHY. ``_ability_overrides`` hand-authors two correction tables from a roster
scan of patch 16.11.1: ``DAMAGE_TYPE_OVERRIDES`` (a null ``damage_type`` that
the engine would mis-mitigate as MAGIC) and ``NON_DAMAGE_BLOCKS`` (a block
labelled ``damage`` that is really a self AD grant or a shield value). The
existing tests (``test_null_damage_type_overrides_2026_05_31.py``, the
S144-D-198 form-key guard) pin that each row loads and resolves, but nothing
compares a row with the live snapshot it was copied from. A patch that gives
one of these forms a real ``damage_type``, reorders its blocks or rewrites its
text would leave the row stale while every guard stays green.

* S144-D-359: every ``DAMAGE_TYPE_OVERRIDES`` row is still a null
  ``damage_type`` in the live raw snapshot (so the override is live, not
  redundant), its first damage block carries the name the inline comment
  quotes, the live effect text states the corrected type, and the block the
  ability scorer SERVES (the block-index registry ordinal, else the first
  damage block) is named for that type. One known gap is pinned: Camille Q is
  served the damage-ordinal 1 block "Increased Mixed Damage" (the recast,
  part true damage), which the PHYSICAL override mitigates as all physical.
  Filed Tier-2 as S144-D-363.
* S144-D-360: every ``NON_DAMAGE_BLOCKS`` attribute is the FIRST damage-kind
  block of the live raw form, so the flip really changes what
  ``block_strategy="first"`` evaluates, and the live text states the grant.
  The module said "block[0]"; for Aatrox R, Janna E, Olaf R, Sona W and
  Vayne R the flipped block is raw index 1 or 2 because a non-damage block
  precedes it (``_select_blocks`` filters ``attribute_kind == "damage"``
  before it picks). The docstring now says so.
* S144-D-361: the "27 ability forms" census re-derives at the live patch:
  27 null-type forms with a damage block = the 7 type overrides + the 7
  null-type non-damage rows + the 13 forms the docstring names as
  intentionally absent. DrMundo E and Twitch R, the residual-sweep rows, are
  typed PHYSICAL live, so they sit outside the census. Every absent form but
  Ryze R and Yunara R states magic damage in its live text, Ryze R's block
  carries no numeric field, and the docstring names each absent form's key.
* S144-D-362: the "checked and intentionally NOT flipped" residual claims
  hold live. Mel R is routed by the block-index registry to damage ordinal 1
  (raw block 2, "Magic Damage"), so its "Increased Stored Damage" block 0 is
  never the default block. The comment above ``NON_DAMAGE_BLOCKS`` said
  "block 2 ("Total Damage")", a raw index and a block name that does not
  exist live, and now says what the registry does. Nocturne Q and Trundle Q
  carry their AD grant on a later damage block, never the first.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1, ENGINE
1.291.0): every claim above held after the docstring fixes. Registry values
are unchanged, so the scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _ability_overrides as mod
from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer._ability_overrides import (
    DAMAGE_TYPE_OVERRIDES,
    NON_DAMAGE_BLOCKS,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_MODULE_SRC = Path(mod.__file__).read_text(encoding="utf-8")
_DOC = " ".join((mod.__doc__ or "").split())
# Source with comment markers dropped, so a claim wrapped over comment lines
# reads as one sentence.
_SRC_FLAT = " ".join(_MODULE_SRC.replace("#", " ").split())

# The live text phrase each corrected type must appear as.
_TYPE_PHRASE = {
    "PHYSICAL": "physical damage",
    "MIXED": "equal parts physical and magic damage",
}

# Served block names that are allowed to disagree with the override, each a
# filed gap. Remove an entry the day the gap is fixed.
_KNOWN_SERVED_DRIFT = {
    ("Camille", "Q", 0): "Increased Mixed Damage",  # S144-D-363
}

# The forms the module docstring names as intentionally absent.
_ABSENT_MAGIC = {
    ("Ahri", "Q", 0), ("Fizz", "Q", 0), ("Gwen", "Q", 0),
    ("Lillia", "Q", 0), ("Velkoz", "R", 0), ("Pantheon", "R", 0),
    ("Skarner", "W", 0), ("Zeri", "E", 0), ("Zeri", "R", 0),
    ("Nunu", "Q", 0), ("Yunara", "Q", 0),
}
_ABSENT_OTHER = {("Ryze", "R", 0), ("Yunara", "R", 0)}

_NUMERIC_BLOCK_KEYS = re.compile(r"(_pct|^base$|_ratio|^flat)")


@cache
def _abilities() -> dict[str, Any]:
    patch = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads(
        (_DATA / patch / "champion_abilities.json").read_text(encoding="utf-8")
    )
    return raw.get("data", raw)


def _form(champion: str, key: str, idx: int) -> dict[str, Any]:
    return _abilities()[champion][key][idx]


def _damage_blocks(form: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for b in form["damage_blocks"] if b["attribute_kind"] == "damage"]


def _text(form: dict[str, Any]) -> str:
    return " ".join(form["effects_descriptions"]).lower()


def _served_block(champion: str, key: str, form: dict[str, Any]) -> dict[str, Any]:
    """The block ``compute_ability_dps`` evaluates on the default path."""
    mapping, _source = registries.get_block_index_for(champion)
    blocks = _damage_blocks(form)
    ordinal = mapping.get(key, 0)
    assert isinstance(ordinal, int), (champion, key, ordinal)
    assert 0 <= ordinal < len(blocks), (champion, key, ordinal, len(blocks))
    return blocks[ordinal]


def _comment_quote(champion: str, key: str) -> str:
    line = re.search(
        rf'\("{champion}", "{key}", 0\): "[A-Z]+",\s*#\s*(.*)$',
        _MODULE_SRC,
        re.MULTILINE,
    )
    assert line is not None, f"no inline comment for {champion} {key}"
    return line.group(1)


def _null_type_damage_forms() -> set[tuple[str, str, int]]:
    out: set[tuple[str, str, int]] = set()
    for champion, keys in _abilities().items():
        for key, forms in keys.items():
            if not isinstance(forms, list):
                continue
            for idx, form in enumerate(forms):
                if form.get("damage_type") is None and _damage_blocks(form):
                    out.add((champion, key, idx))
    return out


# --- S144-D-359: damage-type overrides -------------------------------------


@pytest.mark.parametrize("row", sorted(DAMAGE_TYPE_OVERRIDES))
def test_type_override_target_is_still_null_live(row: tuple[str, str, int]) -> None:
    assert _form(*row)["damage_type"] is None, (
        f"{row} now carries a live damage_type; the override is redundant "
        "or contradicts the feed - re-check and drop or justify it"
    )


@pytest.mark.parametrize("row", sorted(DAMAGE_TYPE_OVERRIDES))
def test_type_override_comment_names_the_first_damage_block(
    row: tuple[str, str, int],
) -> None:
    champion, key, _ = row
    first = _damage_blocks(_form(*row))[0]["attribute"]
    quote = _comment_quote(champion, key)
    if first == "Damage":
        # Sett W: the block is plainly "Damage"; the comment names the effect.
        assert "physical" in quote.lower()
    else:
        assert f'"{first}"' in quote, (row, first, quote)


@pytest.mark.parametrize("row", sorted(DAMAGE_TYPE_OVERRIDES))
def test_type_override_matches_live_effect_text(row: tuple[str, str, int]) -> None:
    phrase = _TYPE_PHRASE[DAMAGE_TYPE_OVERRIDES[row]]
    assert phrase in _text(_form(*row)), (row, phrase)


@pytest.mark.parametrize("row", sorted(DAMAGE_TYPE_OVERRIDES))
def test_served_block_is_named_for_the_override_type(
    row: tuple[str, str, int],
) -> None:
    champion, key, _ = row
    served = _served_block(champion, key, _form(*row))["attribute"]
    if row in _KNOWN_SERVED_DRIFT:
        assert served == _KNOWN_SERVED_DRIFT[row], (
            f"{row} served block moved to {served!r}; re-check S144-D-363 "
            "and update or drop the pinned drift"
        )
        return
    want = DAMAGE_TYPE_OVERRIDES[row]
    if served == "Damage":
        return  # Sett W: an unnamed block; the effect text test covers it.
    word = "Mixed" if want == "MIXED" else "Physical"
    assert word in served, (row, served, want)


def test_known_served_drift_is_still_open() -> None:
    for row in _KNOWN_SERVED_DRIFT:
        assert row in DAMAGE_TYPE_OVERRIDES
        assert DAMAGE_TYPE_OVERRIDES[row] == "PHYSICAL"
        assert "true damage" in _text(_form(*row))


def test_camille_comment_states_the_served_block() -> None:
    quote = _comment_quote("Camille", "Q")
    assert "Increased Mixed Damage" in quote and "S144-D-363" in quote, quote


# --- S144-D-360: non-damage block flips ------------------------------------


@pytest.mark.parametrize("row", sorted(NON_DAMAGE_BLOCKS))
def test_flipped_attribute_is_the_first_damage_block_live(
    row: tuple[str, str, int],
) -> None:
    attrs = NON_DAMAGE_BLOCKS[row]
    assert len(attrs) == 1, row
    first = _damage_blocks(_form(*row))[0]["attribute"]
    assert first in attrs, (
        f"{row}: first damage block is {first!r}, not {sorted(attrs)}; the "
        "flip no longer changes what block_strategy='first' evaluates"
    )


@pytest.mark.parametrize("row", sorted(NON_DAMAGE_BLOCKS))
def test_flipped_grant_is_stated_in_live_text(row: tuple[str, str, int]) -> None:
    text = _text(_form(*row))
    (attr,) = NON_DAMAGE_BLOCKS[row]
    if attr == "Bonus Attack Damage":
        assert "bonus attack damage" in text, row
    else:
        assert attr == "Minimum Damage Mitigated"
        assert "shield" in text and "minimum amount of damage" in text, row


def test_flips_preceded_by_a_non_damage_block_are_the_named_five() -> None:
    preceded = set()
    for row in NON_DAMAGE_BLOCKS:
        (attr,) = NON_DAMAGE_BLOCKS[row]
        names = [b["attribute"] for b in _form(*row)["damage_blocks"]]
        if names.index(attr) > 0:
            preceded.add(row[:2])
    assert preceded == {
        ("Aatrox", "R"), ("Janna", "E"), ("Olaf", "R"),
        ("Sona", "W"), ("Vayne", "R"),
    }


def test_loaded_forms_no_longer_serve_the_flipped_block() -> None:
    snap = AbilitiesSnapshot.load()
    for row, attrs in NON_DAMAGE_BLOCKS.items():
        form = snap.get_ability(*row)
        names = [b.attribute for b in form.damage_blocks_only()]
        assert not (set(names) & attrs), (row, names)


def test_docstring_says_first_damage_block_not_block_zero() -> None:
    assert 'block[0] (the one ``block_strategy="first"`` picks)' not in _DOC
    assert "first ``attribute_kind == \"damage\"`` block" in _DOC
    for name in ("Aatrox R", "Janna E", "Olaf R", "Sona W", "Vayne R"):
        assert name in _DOC, name


# --- S144-D-361: the 27-form census -----------------------------------------


def test_null_type_census_partitions_exactly() -> None:
    census = _null_type_damage_forms()
    dt = set(DAMAGE_TYPE_OVERRIDES)
    nb_null = {r for r in NON_DAMAGE_BLOCKS if r in census}
    absent = _ABSENT_MAGIC | _ABSENT_OTHER
    assert len(census) == 27
    assert dt <= census
    assert len(dt) == 7 and len(nb_null) == 7 and len(absent) == 13
    assert census == dt | nb_null | absent
    assert not (dt & nb_null) and not ((dt | nb_null) & absent)


def test_residual_sweep_rows_are_typed_physical_live() -> None:
    for row in (("DrMundo", "E", 0), ("Twitch", "R", 0)):
        assert row in NON_DAMAGE_BLOCKS
        assert _form(*row)["damage_type"] == "PHYSICAL", row


@pytest.mark.parametrize("row", sorted(_ABSENT_MAGIC))
def test_absent_form_is_magic_in_live_text(row: tuple[str, str, int]) -> None:
    assert "magic damage" in _text(_form(*row)), row


def test_ryze_r_block_is_empty() -> None:
    (block,) = _damage_blocks(_form("Ryze", "R", 0))
    numeric = [k for k in block if _NUMERIC_BLOCK_KEYS.search(k)]
    assert numeric == [], numeric


def test_census_detector_is_not_vacuous() -> None:
    census = _null_type_damage_forms()
    assert ("Camille", "Q", 0) in census
    assert ("Camille", "W", 0) not in census  # typed live


def test_docstring_names_each_absent_form_key() -> None:
    for champion, key, _ in sorted(_ABSENT_MAGIC | _ABSENT_OTHER):
        assert f"{champion} {key}" in _DOC, f"{champion} {key}"
    assert "re-derived 27 at 16.22.1" in _DOC


# --- S144-D-362: residual "intentionally NOT flipped" claims ----------------


def test_mel_r_is_routed_to_damage_ordinal_one_magic_damage() -> None:
    form = _form("Mel", "R", 0)
    assert _damage_blocks(form)[0]["attribute"] == "Increased Stored Damage"
    served = _served_block("Mel", "R", form)
    assert served["attribute"] == "Magic Damage"
    assert form["damage_blocks"].index(served) == 2


def test_mel_r_comment_matches_the_registry() -> None:
    assert "block 2 (\"Total Damage\")" not in _SRC_FLAT
    assert 'damage-block ordinal 1 (raw block 2, "Magic Damage"' in _SRC_FLAT


@pytest.mark.parametrize("champion", ["Nocturne", "Trundle"])
def test_grant_block_is_never_the_first_damage_block(champion: str) -> None:
    names = [b["attribute"] for b in _damage_blocks(_form(champion, "Q", 0))]
    assert "Bonus Attack Damage" in names[1:], names
    assert names[0] != "Bonus Attack Damage"
