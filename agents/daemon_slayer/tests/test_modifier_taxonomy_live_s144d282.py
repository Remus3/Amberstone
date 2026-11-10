"""S144-D-282..285 - the modifier-block taxonomy files every live block where its docstring says.

``modifier_blocks.classify_modifier_kind`` buckets every ``attribute_kind ==
"modifier"`` block. These tests tie it to the live snapshot and to its own
docstring:

* S144-D-282 - grey-health and replicated-projectile blocks are ``other``, as
  the docstring says, not ``damage_amp_self`` (the "damage modifier" /
  "damage stored" amp patterns used to win first).
* S144-D-283 - a "Non-Minion" block is champion-scoped, never ``pve_only``
  (a bare word boundary used to let "minion" match after the hyphen).
* S144-D-284 - the docstring names the engine modules that import the
  classifier, and each of them reads only ``defensive_self`` or
  ``target_shred``. That is why moving a block between ``damage_amp_self``,
  ``pve_only`` and ``other`` is scorer-neutral.
* S144-D-285 - every "Champion Key" example in a bucket's docstring bullet
  has a live block of that kind, and no docstring count is stated as current
  at a dated patch.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import modifier_blocks
from agents.daemon_slayer.abilities import load_default
from agents.daemon_slayer.modifier_blocks import MODIFIER_KINDS, classify_modifier_kind

DS_DIR = Path(modifier_blocks.__file__).resolve().parent


@pytest.fixture(scope="module")
def ab() -> Any:
    return load_default()


def _live_modifier_blocks(ab: Any) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for cid, key, form in ab.iter_forms():
        out.extend((cid, key, b.attribute) for b in form.damage_blocks if b.attribute_kind == "modifier")
    return out


# --------------------------------------------------------------- S144-D-282

GREY_HEALTH_AND_REPLICATED = (
    ("Mel", "W", "Replicated Projectile Damage Modifier"),
    ("TahmKench", "E", "Damage Stored into Grey Health"),
    ("TahmKench", "E", "Increased Damage Stored into Grey Health"),
)

# Real self-amps that share the amp patterns and must stay put.
STILL_AMP = (
    ("Mel", "R", "Stored Damage Increase per Stack"),
    ("Yone", "E", "Damage Stored"),
    ("Jayce", "W", "Damage Modifier"),
    ("Nidalee", "Q", "Increased Damage Modifier"),
    ("AurelionSol", "W", "Breath of Light Flat Damage Modifier"),
)


@pytest.mark.parametrize("blk", GREY_HEALTH_AND_REPLICATED, ids=lambda b: f"{b[0]}{b[1]}-{b[2]}")
def test_grey_health_and_replicated_projectile_are_other(ab: Any, blk: tuple[str, str, str]) -> None:
    assert blk in _live_modifier_blocks(ab), f"{blk} is no longer a live modifier block"
    assert classify_modifier_kind(blk[2]) == "other"


@pytest.mark.parametrize("blk", STILL_AMP, ids=lambda b: f"{b[0]}{b[1]}-{b[2]}")
def test_real_self_amps_stay_damage_amp_self(ab: Any, blk: tuple[str, str, str]) -> None:
    assert blk in _live_modifier_blocks(ab), f"{blk} is no longer a live modifier block"
    assert classify_modifier_kind(blk[2]) == "damage_amp_self"


def test_no_live_grey_health_or_replicated_block_is_an_amp(ab: Any) -> None:
    bad = [
        b
        for b in _live_modifier_blocks(ab)
        if re.search(r"grey health|replicated projectile", b[2], re.IGNORECASE)
        and classify_modifier_kind(b[2]) != "other"
    ]
    assert bad == []


# --------------------------------------------------------------- S144-D-283

NON_MINION = (
    ("Aatrox", "Q", "Maximum Non-Minion Non-Sweetspot Damage"),
    ("Aatrox", "Q", "Maximum Non-Minion Sweetspot Damage"),
    ("Heimerdinger", "W", "Combined Total Non-Minion Damage"),
    ("Heimerdinger", "W", "Total Subsequent Non-Minion Damage"),
)


@pytest.mark.parametrize("blk", NON_MINION, ids=lambda b: f"{b[0]}{b[1]}-{b[2]}")
def test_non_minion_blocks_are_not_pve(ab: Any, blk: tuple[str, str, str]) -> None:
    assert blk in _live_modifier_blocks(ab), f"{blk} is no longer a live modifier block"
    assert classify_modifier_kind(blk[2]) == "other"


def test_no_live_non_minion_or_non_monster_block_is_pve(ab: Any) -> None:
    bad = [
        b
        for b in _live_modifier_blocks(ab)
        if re.search(r"non-(minion|monster)", b[2], re.IGNORECASE) and classify_modifier_kind(b[2]) == "pve_only"
    ]
    assert bad == []


@pytest.mark.parametrize(
    "attr",
    ["Minion Damage", "Minion and Small Monster Damage", "Non-Champion Damage", "Non-Epic Monster Damage",
     "Capped Minion/Monster Health Damage", "Combined Total Minion Damage"],
)
def test_pve_scoped_blocks_stay_pve(attr: str) -> None:
    assert classify_modifier_kind(attr) == "pve_only"


def test_reclassified_blocks_never_reach_an_engine_read_kind() -> None:
    """The moved blocks land in ``other``, never in a kind an engine consumer reads."""
    for _c, _k, attr in GREY_HEALTH_AND_REPLICATED + NON_MINION:
        assert classify_modifier_kind(attr) not in ENGINE_READ_KINDS


# --------------------------------------------------------------- S144-D-284

ENGINE_READ_KINDS = frozenset({"defensive_self", "target_shred"})
# Module stem -> names it imports from modifier_blocks.
EXPECTED_IMPORTERS = {
    "data_loader": {"classify_modifier_kind"},
    "self_shred": {"classify_modifier_kind"},
    "server": {"summarize_modifiers"},
}


def _importers() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in sorted(DS_DIR.glob("*.py")):
        if path.stem == "modifier_blocks":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("modifier_blocks"):
                out.setdefault(path.stem, set()).update(a.name for a in node.names)
            elif isinstance(node, ast.Import) and any(a.name.endswith("modifier_blocks") for a in node.names):
                out.setdefault(path.stem, set()).add("*module*")
    return out


def _is_classifier_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "classify_modifier_kind"


def classifier_reads(src: str) -> tuple[set[str], int]:
    """Return (kinds compared against a classifier call, classifier calls outside a compare)."""
    tree = ast.parse(src)
    kinds: set[str] = set()
    in_compare: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        calls = [s for s in sides if _is_classifier_call(s)]
        if not calls:
            continue
        in_compare.update(id(c) for c in calls)
        kinds.update(s.value for s in sides if isinstance(s, ast.Constant) and isinstance(s.value, str))
    loose = sum(1 for n in ast.walk(tree) if _is_classifier_call(n) and id(n) not in in_compare)
    return kinds, loose


def test_importers_are_the_named_set() -> None:
    assert _importers() == EXPECTED_IMPORTERS


@pytest.mark.parametrize("stem", sorted(s for s, n in EXPECTED_IMPORTERS.items() if "classify_modifier_kind" in n))
def test_engine_importers_read_only_defensive_and_shred(stem: str) -> None:
    kinds, loose = classifier_reads((DS_DIR / f"{stem}.py").read_text(encoding="utf-8"))
    assert kinds, f"{stem} compares no kind against classify_modifier_kind"
    assert kinds <= ENGINE_READ_KINDS, kinds
    assert loose == 0, f"{stem} uses classify_modifier_kind outside a compare"


def test_classifier_reads_catches_planted_defects() -> None:
    kinds, loose = classifier_reads('if classify_modifier_kind(a) == "damage_amp_self":\n    pass\n')
    assert kinds == {"damage_amp_self"}
    assert loose == 0
    _kinds, loose = classifier_reads("k = classify_modifier_kind(a)\n")
    assert loose == 1


def test_docstring_names_the_engine_importers() -> None:
    doc = " ".join((modifier_blocks.__doc__ or "").split())
    assert "nothing in the DPS / EHP / ability-DPS / HPS path imports it" not in doc
    for stem, names in EXPECTED_IMPORTERS.items():
        if "classify_modifier_kind" in names:
            assert f"{stem}.py" in doc, stem
    for kind in ENGINE_READ_KINDS:
        assert kind in doc


# --------------------------------------------------------------- S144-D-285

_PAIR_RE = re.compile(r"\b([A-Z][A-Za-z]+) ([QWER])\b")


def _bullets(doc: str) -> dict[str, str]:
    """Map each ``* ``kind`` - text`` taxonomy bullet to its flattened text."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^\* ``(\w+)``\s*-(.*?)(?=^\* ``|^\S|\Z)", doc, re.MULTILINE | re.DOTALL):
        out[m.group(1)] = " ".join(m.group(2).split())
    return out


def bullet_errors(doc: str, live: list[tuple[str, str, str]]) -> list[str]:
    champs = {c for c, _k, _a in live}
    kinds_at = {(c, k, classify_modifier_kind(a)) for c, k, a in live}
    bullets = _bullets(doc)
    errs: list[str] = []
    if set(bullets) != set(MODIFIER_KINDS):
        errs.append(f"bullets {sorted(bullets)} != kinds {sorted(MODIFIER_KINDS)}")
    for kind, text in bullets.items():
        pairs = [(c, k) for c, k in _PAIR_RE.findall(text) if c in champs]
        if not pairs:
            errs.append(f"{kind}: names no live 'Champion Key' example")
        errs.extend(f"{kind}: {c} {k} has no live {kind} block" for c, k in pairs if (c, k, kind) not in kinds_at)
    return errs


def test_docstring_examples_resolve_to_their_kind(ab: Any) -> None:
    assert bullet_errors(modifier_blocks.__doc__ or "", _live_modifier_blocks(ab)) == []


def test_bullet_errors_catches_planted_defects(ab: Any) -> None:
    live = _live_modifier_blocks(ab)
    doc = modifier_blocks.__doc__ or ""
    assert "(Nasus E, " in doc
    errs = bullet_errors(doc.replace("(Nasus E, ", "(Garen W, ", 1), live)
    assert any("Garen W has no live target_shred" in e for e in errs), errs
    assert "* ``other``" in doc
    errs = bullet_errors(doc.replace("* ``other``", "* ``misc``", 1), live)
    assert any("bullets" in e for e in errs), errs


def test_no_docstring_count_is_stated_current_at_a_dated_patch() -> None:
    flat = " ".join((modifier_blocks.__doc__ or "").split())
    sentences = re.split(r"(?<=[.;:])\s+", flat)
    dated = [
        s
        for s in sentences
        if re.search(r"\b\d+\.\d+\.\d+\b", s) and re.search(r"\b\d{2,3} (of \d+ )?blocks\b", s)
    ]
    assert dated, "the docstring no longer records its first-read count"
    assert all("first read" in s for s in dated), dated
