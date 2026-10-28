"""Guard: the P2-W2 slice-D test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. tests/test_p2w2_ds_d.py (20df1767f)
listed 15 symbols with line cites into _effects_types.py, effects.py and
_effects_data.py. Every cite had drifted (cited line -> line before this
edit): ``CallContext`` 30 -> 32, its ``base_ad`` / ``target_max_hp`` fields
74 / 80 -> 75 / 81, ``PeriodicProc`` 143 -> 153, its ``bonus_damage`` field
170 -> 211, ``PeriodicProc.resolve_damage`` 204 -> 262, ``ItemShield``
217 -> 287, ``ItemShield.resolve_magnitude`` 279 -> 363, ``ItemHeal``
311 -> 405, ``ItemHeal.resolve_magnitude`` 396 -> 489, the damage-type
constants 16,17,26 -> 17,18,27, ``collect_effects`` 55 -> 245,
``total_crit_chance_bonus`` 110 -> 364, ``ITEM_EFFECTS`` 26 -> 29 and the
3153 entry 532 -> 587. Each claim was re-read by symbol at HEAD and still
holds; the list now names the symbol alone, and the tests below pin the
claims the test file's prose makes, so a moved or deleted construct fails
here instead of leaving a cite that resolves to SOME line forever.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = REPO / "tests" / "test_p2w2_ds_d.py"

# ``(_effects_types.py:143)``, ``(_effects_types.py:16,17,26)``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:_effects_types|_effects_data|effects)\.py:\d"
)

# (module, dotted attribute) for every def / class in the symbol list.
_SYMBOLS = (
    ("_effects_types", "CallContext"),
    ("_effects_types", "PeriodicProc"),
    ("_effects_types", "PeriodicProc.resolve_damage"),
    ("_effects_types", "ItemShield"),
    ("_effects_types", "ItemShield.resolve_magnitude"),
    ("_effects_types", "ItemHeal"),
    ("_effects_types", "ItemHeal.resolve_magnitude"),
    ("effects", "collect_effects"),
    ("effects", "total_crit_chance_bonus"),
    ("effects", "total_bonus_ap_from_hp"),
)

# (module, class, field) for the dataclass fields in the symbol list.
_FIELDS = (
    ("_effects_types", "CallContext", "target_max_hp"),
    ("_effects_types", "CallContext", "base_ad"),
    ("_effects_types", "PeriodicProc", "bonus_damage"),
)


def _source(module: str) -> str:
    return (DS / f"{module}.py").read_text(encoding="utf-8")


def _node(module: str, dotted: str) -> tuple[str, ast.AST]:
    src = _source(module)
    scope: list[ast.AST] = list(ast.parse(src).body)
    node: ast.AST | None = None
    for part in dotted.split("."):
        node = next(
            (n for n in scope
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name == part),
            None,
        )
        assert node is not None, f"{module}.py has no {dotted}"
        scope = list(getattr(node, "body", []))
    return src, node


def _segment(module: str, dotted: str) -> str:
    src, node = _node(module, dotted)
    return ast.get_source_segment(src, node) or ""


def _module_assign(module: str, name: str) -> ast.AST:
    for n in ast.parse(_source(module)).body:
        targets = (
            [n.target] if isinstance(n, ast.AnnAssign)
            else n.targets if isinstance(n, ast.Assign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return n
    raise AssertionError(f"{module}.py has no module-level {name}")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "  _effects_types.PeriodicProc                 (_effects_types.py:143)",
        "  _effects_types.MAGICAL / PHYSICAL / ANY     (_effects_types.py:16,17,26)",
        "  effects.collect_effects                     (effects.py:55)",
        "                                              (_effects_data.py:532)",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "  _effects_types.PeriodicProc.resolve_damage",
        "agents/daemon_slayer/_effects_types.py",
        "side_effects.py:12",
        "dps.py:284",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(
            TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_every_listed_symbol_resolves():
    text = TARGET.read_text(encoding="utf-8")
    for module, dotted in _SYMBOLS:
        assert f"{module}.{dotted}" in text, (module, dotted)
        _node(module, dotted)


def test_every_listed_field_is_a_dataclass_field():
    text = TARGET.read_text(encoding="utf-8")
    for module, cls, field in _FIELDS:
        assert f"{module}.{cls}.{field}" in text, (cls, field)
        _src, node = _node(module, cls)
        names = {
            n.target.id for n in node.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        assert field in names, (cls, field)


def test_damage_type_constants_and_registry_are_module_level():
    for name in ("MAGICAL", "PHYSICAL", "ANY"):
        _module_assign("_effects_types", name)
    _module_assign("_effects_data", "ITEM_EFFECTS")


def test_botrk_entry_still_carries_the_target_max_hp_lambda():
    node = _module_assign("_effects_data", "ITEM_EFFECTS")
    entry = next(
        v for k, v in zip(node.value.keys, node.value.values)
        if isinstance(k, ast.Constant) and k.value == "3153"
    )
    seg = ast.get_source_segment(_source("_effects_data"), entry) or ""
    assert "bonus_damage=lambda c: 0.09 * c.target_max_hp" in seg


def test_resolve_damage_drops_non_finite_to_zero():
    body = _segment("_effects_types", "PeriodicProc.resolve_damage")
    assert "if not math.isfinite(out):\n            return 0.0" in body


def test_shield_and_heal_guard_before_the_zero_floor():
    for cls in ("ItemShield", "ItemHeal"):
        body = _segment("_effects_types", f"{cls}.resolve_magnitude")
        guard = body.find("if not math.isfinite(total):")
        floor = body.find("return max(0.0, float(total))")
        assert guard != -1 and floor != -1 and guard < floor, cls


def test_bonus_ap_from_hp_returns_zero_on_non_positive_hp():
    body = _segment("effects", "total_bonus_ap_from_hp")
    assert "if caster_bonus_hp <= 0:\n        return 0.0" in body
