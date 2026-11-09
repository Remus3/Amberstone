"""S144-D-286 / D-288 / D-289 - DS shred docstrings and the Nidalee Takedown note.

* S144-D-286 - ``modifier_blocks``' target_shred bullet said the class is one
  "that RC does not yet model", and ``self_shred``' docstring quoted that
  phrase back. ``self_shred.compute_self_shred_uplift`` models it, and
  ``fight_report`` (served on /v2/fight-report) imports it. Both docstrings
  now say RC models the uplift in the fight report only, never in the
  damage scorers, and ``self_shred`` names its one importer.
* S144-D-288 - the ("Nidalee", "Q", 1) amp row and the module docstring said
  Takedown is "gated behind a Cougar-form Q recast". The live Takedown form
  text mentions no recast: Takedown IS the Cougar-form Q cast, and it
  empowers the next basic attack within 10 seconds.
* S144-D-289 - every "<Champion> <key>" that ``self_shred``' docstring lists
  as a target_shred ability resolves, at the live snapshot, to a non-zero
  uplift sourced from that key; the AD-reduction examples it names in its
  comment classify target_shred and still yield no uplift.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _ability_amp_overrides as amp
from agents.daemon_slayer import modifier_blocks, self_shred
from agents.daemon_slayer.abilities import load_default
from agents.daemon_slayer.modifier_blocks import classify_modifier_kind
from agents.daemon_slayer.self_shred import compute_self_shred_uplift

_DS = Path(__file__).resolve().parents[1]


def _norm(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(scope="module")
def ab() -> Any:
    return load_default()


# --------------------------------------------------------------- S144-D-286


def test_neither_docstring_says_shred_is_not_yet_modeled() -> None:
    for mod in (modifier_blocks, self_shred):
        assert "not yet model" not in _norm(mod.__doc__ or ""), mod.__name__


def test_target_shred_bullet_names_the_fight_report_model() -> None:
    doc = _norm(modifier_blocks.__doc__ or "")
    bullet = doc.split("* ``target_shred``", 1)[1].split("* ``defensive_self``", 1)[0]
    assert "self_shred" in bullet
    assert "fight report" in bullet


def quote_errors(quoting_doc: str, quoted_doc: str) -> list[str]:
    """Each "..." quote after "docstring:" must appear in ``quoted_doc``."""
    errors = []
    quotes = re.findall(r'docstring:\s*"([^"]+)"', _norm(quoting_doc))
    if not quotes:
        errors.append("no docstring quote found")
    for q in quotes:
        if q not in _norm(quoted_doc):
            errors.append(q)
    return errors


def test_self_shred_quote_matches_modifier_blocks() -> None:
    assert quote_errors(self_shred.__doc__ or "", modifier_blocks.__doc__ or "") == []


def test_quote_errors_catches_planted_defects() -> None:
    assert quote_errors('see its docstring: "abc def"', "xx abc  def yy") == []
    assert quote_errors('see its docstring: "abc zzz"', "xx abc def yy") == ["abc zzz"]
    assert quote_errors("no quote here", "abc") == ["no docstring quote found"]


def _self_shred_importers() -> set[str]:
    out = set()
    for path in sorted(_DS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            from_hit = isinstance(node, ast.ImportFrom) and (node.module or "").endswith("self_shred")
            plain_hit = isinstance(node, ast.Import) and any(a.name.endswith("self_shred") for a in node.names)
            if from_hit or plain_hit:
                out.add(path.stem)
    return out


def test_self_shred_importers_are_the_named_one() -> None:
    assert _self_shred_importers() == {"fight_report"}
    doc = _norm(self_shred.__doc__ or "")
    assert "fight_report" in doc
    assert "/v2/fight-report" in doc


# --------------------------------------------------------------- S144-D-288


def _takedown_text(ab: Any) -> str:
    # The parsed AbilityForm drops notes / effects prose; read the raw snapshot.
    path = Path(ab.data_root) / ab.patch / "champion_abilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    form = next(f for f in data["Nidalee"]["Q"] if f.get("form_index") == 1)
    raw = [form.get("name", ""), form.get("notes") or ""]
    raw.extend(form.get("effects_descriptions") or ())
    return _norm(" ".join(str(r) for r in raw))


def test_live_takedown_text_has_no_recast(ab: Any) -> None:
    text = _takedown_text(ab)
    assert "Takedown" in text
    assert "next basic attack" in text  # anchor: the text is really there
    assert "recast" not in text.lower()


def test_takedown_row_and_module_doc_drop_the_recast_claim() -> None:
    note = amp._ABILITY_AMP_OVERRIDES[("Nidalee", "Q", 1)].note
    assert "recast" not in note.lower()
    assert "Cougar-form Q" in note
    src = Path(amp.__file__).read_text(encoding="utf-8")
    assert "Cougar-form Q recast" not in src


# --------------------------------------------------------------- S144-D-289

_ALIASES = {"Wukong": "MonkeyKing"}
_PAIR_RE = re.compile(r"\b([A-Z][A-Za-z]+) ([QWER])\b")


def docstring_shred_pairs(doc: str) -> list[tuple[str, str]]:
    """The "(Champ K, ...)" list in the Context paragraph of ``doc``."""
    para = _norm(doc).split("Context", 1)[1].split("The classifier", 1)[0]
    groups = re.findall(r"\(([^()]*)\)", para)
    listing = max(groups, key=lambda g: len(_PAIR_RE.findall(g)), default="")
    return [(_ALIASES.get(c, c), k) for c, k in _PAIR_RE.findall(listing)]


def test_docstring_shred_pairs_parses_the_listing() -> None:
    pairs = docstring_shred_pairs(self_shred.__doc__ or "")
    assert ("Nasus", "E") in pairs
    assert ("MonkeyKing", "Q") in pairs
    assert len(pairs) >= 10


@pytest.mark.parametrize("pair", docstring_shred_pairs(self_shred.__doc__ or ""), ids=str)
def test_docstring_examples_model_a_live_uplift(pair: tuple[str, str]) -> None:
    champ, key = pair
    r = compute_self_shred_uplift(champ, 18, 100.0, 60.0, 1000.0, 1000.0)
    assert r.shred_source == f"{champ}:{key}"
    assert r.dps_uplift_pct > 0.0


AD_REDUCTION = (("Trundle", "Q"), ("Tryndamere", "W"))


@pytest.mark.parametrize("pair", AD_REDUCTION, ids=str)
def test_ad_reduction_examples_classify_shred_but_yield_no_uplift(ab: Any, pair: tuple[str, str]) -> None:
    champ, key = pair
    kinds = {
        classify_modifier_kind(b.attribute)
        for f in ab.get_abilities(champ)[key]
        for b in f.damage_blocks
        if b.attribute_kind == "modifier" and "Attack Damage" in b.attribute
    }
    assert kinds == {"target_shred"}
    r = compute_self_shred_uplift(champ, 18, 100.0, 60.0, 1000.0, 1000.0)
    assert r.dps_uplift_pct == 0.0
    assert r.shred_source == ""


def test_ad_reduction_comment_names_the_tested_pairs() -> None:
    src = Path(self_shred.__file__).read_text(encoding="utf-8")
    for champ, key in AD_REDUCTION:
        assert f"{champ} {key}" in src
