"""S144-D-408 - the DS resist -> damage coupling registry matches the live data it cites.

WHY. ``_resist_damage_coupling`` seeds six champions from a machine census of
``champion_abilities.json`` (16.14.1 at authoring) plus effects text it quotes
VERBATIM for the two ``no_damage`` innates (Rammus P, Rell P), cross-references
two rows of ``_passive_damage_overrides`` (Taric P, Galio P), and names four
rejects by the live text they were rejected for. Its only test
(``test_resist_damage_coupling_rm87.py``) pins the arithmetic and the wiring,
never the cited data, so a patch that moved a percent or reworded a quoted
sentence would leave every guard green.

Checked against the CURRENT patch (``data/daemon_slayer/current.txt``):

* the census: the damage blocks carrying an armor / MR percent are exactly the
  six rows the docstring names (K'Sante Q, Malphite W twice, Malphite E,
  Ornn E, Taric E);
* every seeded row: form name, field, flat value, the pool that field implies,
  damage type and the quoted cooldown range;
* the two verbatim innate sentences, their ``no_damage`` parse status and their
  empty damage blocks; the Taric P and Galio P live text against the two
  ``_passive_damage_overrides`` rows the comments cite;
* the rejects: K'Sante Q's 40 / 40 form and K'Sante unseeded, the Rammus W
  reflect, the Poppy W 12 percent, and Skarner carrying no armor / MR text.

MEASURED 2026-11-10 (current patch 16.22.1): every check holds, so this is a
guard only; no registry value changed and every scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _resist_damage_coupling as resist_mod
from agents.daemon_slayer._passive_damage_overrides import _PASSIVE_DAMAGE_OVERRIDES
from agents.daemon_slayer._resist_damage_coupling import (
    _ABILITY_CAST_PROB,
    _CHAMPION_RESIST_DAMAGE_COUPLING,
    _ON_HIT_INNATE_PROB,
    _PERIODIC_EMPOWER_PROB,
    _PERMANENT_CONVERSION_PROB,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = " ".join((resist_mod.__doc__ or "").split())
_SOURCE = Path(resist_mod.__file__).read_text(encoding="utf-8")
_SOURCE_FLAT = " ".join(re.sub(r"(?m)^\s*#\s?", " ", _SOURCE).split())

_RESIST_RE = re.compile(r"(armor|_mr)_pct$")

# (champion, slot, form_index, block_index) -> {field: per-rank values}
_EXPECTED_CENSUS = {
    ("KSante", "Q", 0, 0): {"bonus_armor_pct": [40.0] * 5, "bonus_mr_pct": [40.0] * 5},
    ("Malphite", "W", 0, 2): {"caster_armor_pct": [15.0] * 5},
    ("Malphite", "W", 0, 3): {"caster_armor_pct": [15.0] * 5},
    ("Malphite", "E", 0, 0): {"caster_armor_pct": [40.0] * 5},
    ("Ornn", "E", 0, 0): {"bonus_armor_pct": [40.0] * 5, "bonus_mr_pct": [40.0] * 5},
    ("Taric", "E", 0, 0): {"bonus_armor_pct": [50.0] * 5},
}

# champion -> (slot, armor field or None, mr field or None, pool, damage type, cadence)
_BLOCK_ROWS = {
    "Ornn": ("E", "bonus_armor_pct", "bonus_mr_pct", "bonus", "PHYSICAL", _ABILITY_CAST_PROB),
    "Malphite": ("E", "caster_armor_pct", None, "total", "MAGIC", _ABILITY_CAST_PROB),
    "Taric": ("E", "bonus_armor_pct", None, "bonus", "MAGIC", _ABILITY_CAST_PROB),
}

_RAMMUS_P = (
    "Innate: Rammus gains bonus attack damage equal to the sum of 15% total armor and 15% total magic resistance."
)
_RELL_P = (
    "Innate: Rell's basic attacks deal bonus magic damage on-hit equal to the sum of "
    "5% of her total armor and 5% of her total magic resistance."
)


def _patch_dir() -> Path:
    return _DATA / (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _snapshot(name: str) -> Any:
    raw = json.loads((_patch_dir() / name).read_text(encoding="utf-8"))
    return raw.get("data", raw) if isinstance(raw, dict) else raw


def _form(champion: str, slot: str, fi: int = 0) -> dict[str, Any]:
    return _snapshot("champion_abilities.json")[champion][slot][fi]


def _text(champion: str, slot: str, fi: int = 0) -> str:
    return " ".join(" ".join(_form(champion, slot, fi).get("effects_descriptions") or []).split())


def test_census_is_exactly_the_six_documented_rows():
    seen = {}
    for champ, kit in _snapshot("champion_abilities.json").items():
        for slot, forms in kit.items():
            for fi, form in enumerate(forms):
                for bi, block in enumerate(form.get("damage_blocks") or []):
                    hits = {k: list(v) for k, v in block.items() if _RESIST_RE.search(k)}
                    if hits:
                        seen[(champ, slot, fi, bi)] = hits
    assert seen == _EXPECTED_CENSUS
    assert "returned exactly six rows (KSante Q, Malphite W, Malphite E, Ornn E, Taric E)" in _DOC


def test_registry_membership():
    assert set(_CHAMPION_RESIST_DAMAGE_COUPLING) == {"Rammus", "Ornn", "Rell", "Malphite", "Taric", "Galio"}
    assert "KSante" not in _CHAMPION_RESIST_DAMAGE_COUPLING


@pytest.mark.parametrize("champion", sorted(_BLOCK_ROWS))
def test_block_sourced_row_matches_live(champion):
    slot, armor_field, mr_field, pool, dtype, prob = _BLOCK_ROWS[champion]
    entry = _CHAMPION_RESIST_DAMAGE_COUPLING[champion]
    form = _form(champion, slot)
    block = form["damage_blocks"][0]
    assert form["name"] == entry.attribute
    assert form["damage_type"] == dtype and f"as {dtype} damage" in entry.note
    assert set(block[armor_field]) == {entry.armor_pct}
    assert (set(block[mr_field]) if mr_field else {0.0}) == {entry.mr_pct}
    assert entry.pct_base == pool
    assert entry.conditional_probability == prob


def test_ornn_cooldown_range_is_live():
    cd = _form("Ornn", "E")["cooldown"]
    assert (min(cd), max(cd)) == (12.0, 14.0)
    assert "A 12-14s cooldown damage ability" in _SOURCE_FLAT


def test_malphite_w_peer_source_is_live_and_not_summed():
    w = [b["caster_armor_pct"] for b in _form("Malphite", "W")["damage_blocks"] if "caster_armor_pct" in b]
    assert w == [[15.0] * 5, [15.0] * 5]
    assert _CHAMPION_RESIST_DAMAGE_COUPLING["Malphite"].armor_pct == 40.0
    assert "(caster_armor_pct 15)" in _SOURCE_FLAT


@pytest.mark.parametrize(
    ("champion", "sentence", "prob"),
    [("Rammus", _RAMMUS_P, _PERMANENT_CONVERSION_PROB), ("Rell", _RELL_P, _ON_HIT_INNATE_PROB)],
)
def test_innate_rows_quote_the_live_sentence(champion, sentence, prob):
    form = _form(champion, "P")
    entry = _CHAMPION_RESIST_DAMAGE_COUPLING[champion]
    assert sentence in _text(champion, "P")
    assert sentence in _SOURCE_FLAT
    assert form["name"] == entry.attribute
    assert form.get("parse_status") == "no_damage" and not form.get("damage_blocks")
    pct = 15.0 if champion == "Rammus" else 5.0
    assert (entry.armor_pct, entry.mr_pct, entry.pct_base) == (pct, pct, "total")
    assert entry.conditional_probability == prob


def test_taric_p_rider_matches_live_text_and_override_row():
    assert "(+ 15% bonus armor) bonus magic damage" in _text("Taric", "P")
    assert "next two basic attacks" in _text("Taric", "P")
    row = _PASSIVE_DAMAGE_OVERRIDES[("Taric", "P", 0)]
    assert row.bonus_armor_pct == 15.0 and row.attribute == _form("Taric", "P")["name"] == "Bravado"


def test_galio_row_matches_live_text_and_override_row():
    text = _text("Galio", "P")
    assert text.startswith("Innate: Periodically, Galio's next basic attack is empowered")
    assert "(+ 60% bonus magic resistance) modified magic damage" in text
    row = _PASSIVE_DAMAGE_OVERRIDES[("Galio", "P", 0)]
    entry = _CHAMPION_RESIST_DAMAGE_COUPLING["Galio"]
    assert row.bonus_mr_pct == entry.mr_pct == 60.0 and row.damage_type == "MAGIC" and row.cadence == "on_hit"
    assert entry.attribute == row.attribute == _form("Galio", "P")["name"]
    assert (entry.armor_pct, entry.pct_base, entry.conditional_probability) == (0.0, "bonus", _PERIODIC_EMPOWER_PROB)


def test_rejects_still_read_as_documented():
    assert "15 (+ 10% total armor) (+ 10% total magic resistance) magic damage" in _text("Rammus", "W")
    assert "Poppy increases her total armor and total magic resistance by 12%" in _text("Poppy", "W")
    assert _form("Poppy", "W")["name"] == "Steadfast Presence"
    skarner = " ".join(
        _text("Skarner", s, fi)
        for s, forms in _snapshot("champion_abilities.json")["Skarner"].items()
        for fi in range(len(forms))
    )
    assert not re.search(r"armor|magic resist", skarner, re.I)
    assert _form("KSante", "Q")["name"] == "Ntofo Strikes" and _form("KSante", "Q")["damage_type"] == "PHYSICAL"
