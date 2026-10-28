"""Guard: the P2-W2 slice-E test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. tests/test_p2w2_ds_e.py (20df1767f)
listed 8 symbols with line cites into the _passive_*_overrides modules, and 7
had drifted (cited line -> line before this edit): ``resist_grants``
607 -> 624, ``_PASSIVE_RESIST_OVERRIDES`` 216 -> 227, ``_ASSUMED_SOUL_COUNT``
156 -> 157, ``ally_resist_grant`` 225 -> 328, ``_PASSIVE_DAMAGE_OVERRIDES``
346 -> 399, ``to_damage_block`` 791 -> 1074, ``revive_multiplier``
250 -> 253 (``survival_window_multiplier`` 300 still matched). The list now
names the symbol alone.

One prose claim was false: the Renata test said the display-name miss was
"confirmed by the ally_revive path below", and no such path existed - the
test only called ``ally_resist_grant``, which returns 0.0 for BOTH spellings
(Renata W is a revive, not a resist), so it could not tell a canonical key
from a dead one. The test now asserts through ``ally_revive_multiplier``,
the accessor the ("Renata", "W", 0) entry actually feeds. The tests below
pin the claims the test file's prose makes.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = REPO / "tests" / "test_p2w2_ds_e.py"

# ``(_passive_resist_overrides.py:607)``.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])_passive_[a-z_]+_overrides\.py:\d")

# (module, top-level def or module-level assignment) in the symbol list.
_SYMBOLS = (
    ("_passive_resist_overrides", "resist_grants"),
    ("_passive_resist_overrides", "_PASSIVE_RESIST_OVERRIDES"),
    ("_passive_resist_overrides", "_ASSUMED_SOUL_COUNT"),
    ("_passive_ally_grant_overrides", "ally_resist_grant"),
    ("_passive_ally_grant_overrides", "ally_revive_multiplier"),
    ("_passive_damage_overrides", "_PASSIVE_DAMAGE_OVERRIDES"),
    ("_passive_damage_overrides", "to_damage_block"),
    ("_passive_revive_overrides", "revive_multiplier"),
    ("_passive_survival_window_overrides", "survival_window_multiplier"),
)


def _source(module: str) -> str:
    return (DS / f"{module}.py").read_text(encoding="utf-8")


def _top_level(module: str, name: str) -> ast.AST:
    for n in ast.parse(_source(module)).body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
        targets = (
            [n.target] if isinstance(n, ast.AnnAssign)
            else n.targets if isinstance(n, ast.Assign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return n
    raise AssertionError(f"{module}.py has no top-level {name}")


def _segment(module: str, name: str) -> str:
    return ast.get_source_segment(
        _source(module), _top_level(module, name)) or ""


def _registry_keys(module: str, name: str) -> set[tuple]:
    node = _top_level(module, name)
    return {
        ast.literal_eval(k) for k in node.value.keys
        if isinstance(k, ast.Tuple)
    }


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "  _passive_resist_overrides.resist_grants  (_passive_resist_overrides.py:607)",
        "  x  (_passive_survival_window_overrides.py:300)",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "  _passive_resist_overrides.resist_grants",
        "agents/daemon_slayer/_passive_resist_overrides.py",
        "ehp.py:124",
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
    for module, name in _SYMBOLS:
        assert f"{module}.{name}" in text, (module, name)
        _top_level(module, name)


def test_percent_paths_still_carry_the_finite_guard():
    # The FIX-NOW prose: a non-finite resist input is the no-op 0.0 in the
    # PERCENT path of both accessors.
    for module, name in (
        ("_passive_resist_overrides", "resist_grants"),
        ("_passive_ally_grant_overrides", "ally_resist_grant"),
    ):
        seg = _segment(module, name)
        assert "if not math.isfinite(res_a):" in seg, name
        assert "if not math.isfinite(res_m):" in seg, name


def test_ehp_still_consumes_resist_grants():
    # The prose names compute_ehp as the EHP-denominator seam it guards.
    src = _source("ehp")
    assert "from ._passive_resist_overrides import resist_grants" in src
    assert "resist_grants(" in _segment("ehp", "compute_ehp")


def test_registry_keys_the_prose_names():
    resist = _registry_keys(
        "_passive_resist_overrides", "_PASSIVE_RESIST_OVERRIDES")
    for key in (("MonkeyKing", "P", 0), ("Malphite", "W", 0),
                ("Poppy", "W", 0), ("Thresh", "P", 0)):
        assert key in resist, key
    assert not any(k[0] in ("Wukong", "KSante", "K'Sante") for k in resist)
    ally = _registry_keys(
        "_passive_ally_grant_overrides", "_PASSIVE_ALLY_GRANT_OVERRIDES")
    assert ("Taric", "W", 0) in ally
    assert ("Renata", "W", 0) in ally


def test_renata_claim_is_backed_by_the_revive_accessor():
    text = TARGET.read_text(encoding="utf-8")
    assert "ally_revive path below" not in text
    assert 'ally_revive_multiplier("Renata", 11, True)' in text
    assert 'ally_revive_multiplier("Renata Glasc", 11, True)' in text
