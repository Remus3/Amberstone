"""Guard: the crit override registries cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The two crit registries carried four
line cites into _effects_data.py and every one had drifted (cited -> line
before this edit): Infinity Edge ``_effects_data.py:33`` -> the 3031 row at
31-36, Runaan's Hurricane 3085 ``:184-202`` -> 185-202, and its Arena mirror
223085 ``:4272-4285`` -> 4446-4459. Two prose defects sat beside them in
_crit_conversion_overrides.py:

- "``rank.py`` has no crit-conversion parameter" was false in the very commit
  that wrote it (bfbe2d01f added ``rank_items(apply_crit_conversion=...)`` and
  the ``POST /rank`` parse alongside the module). The true reason the shipped
  build tables are untouched is that no table generator sends the flag.
- ``tests/test_crit_conversion_ashe_rm46.py`` names a path that does not
  exist; the file lives under agents/daemon_slayer/tests.

The tests below pin the claims the docstrings lean on, so a refactor that
breaks one turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import rank
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGETS = (
    DS / "_crit_chance_overrides.py",
    DS / "_crit_conversion_overrides.py",
)
# ``_effects_data.py:33``. Not the port shape ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d")
_GENERATORS = (
    REPO / "core" / "build_order_precompute.py",
    REPO / "core" / "build_order_variants.py",
    REPO / "tools" / "daemon_slayer_build_orders_generate.py",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "SHIPPED IE in ``_effects_data.py:33`` carries crit_damage_bonus",
        "with no crit term (``_effects_data.py:184-202``), so the shipped",
        "# _effects_data.py:4272-4285).",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "crit-conversion parameter and the table generator drives ``:8860``.",
        "SHIPPED IE (``ITEM_EFFECTS[\"3031\"]`` in ``_effects_data.py``)",
        "``agents/daemon_slayer/tests/test_crit_conversion_ashe_rm46.py``",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_targets():
    hits = [
        f"{path.name}:{n}: {line.strip()}"
        for path in TARGETS
        for n, line in enumerate(_source(path).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_false_rank_claim_is_gone_and_rank_carries_the_flag():
    text = " ".join(_source(TARGETS[1]).split())
    assert "has no crit-conversion parameter" not in text
    params = inspect.signature(rank.rank_items).parameters
    assert params["apply_crit_conversion"].default is False
    server = ast.parse(_source(DS / "server.py"))
    route = next(n for n in server.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_route_rank")
    assert any(isinstance(n, ast.Constant) and n.value == "apply_crit_conversion"
               for n in ast.walk(route))


def test_no_table_generator_sends_the_flag():
    text = " ".join(_source(TARGETS[1]).split())
    assert "no build-table generator sends it" in text
    for path in _GENERATORS:
        assert path.is_file(), path
        assert "apply_crit_conversion" not in _source(path), path


def test_rm46_test_path_is_the_real_one():
    text = _source(TARGETS[1])
    path = "agents/daemon_slayer/tests/test_crit_conversion_ashe_rm46.py"
    assert path in text
    assert "``tests/test_crit_conversion_ashe_rm46.py``" not in text
    assert (REPO / path).is_file()


def test_infinity_edge_row_matches_the_prose():
    assert "ITEM_EFFECTS[\"3031\"]" in _source(TARGETS[0])
    ie = ITEM_EFFECTS["3031"]
    assert ie.name == "Infinity Edge"
    assert ie.crit_damage_bonus == 0.30


def test_runaan_rows_have_no_crit_term():
    text = _source(TARGETS[1])
    for item_id in ("3085", "223085"):
        assert f"ITEM_EFFECTS[\"{item_id}\"]" in text, item_id
        procs = ITEM_EFFECTS[item_id].periodics
        assert [p.name for p in procs] == ["Wind's Fury"], item_id
        src = inspect.getsource(procs[0].bonus_damage)
        assert "crit" not in src, (item_id, src)
        assert "2.0 * 0.55 * (c.base_ad + c.bonus_ad)" in src, item_id


def test_compute_dps_imports_the_registry_only_behind_the_flag():
    tree = ast.parse(_source(DS / "dps.py"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "_crit_conversion_overrides" not in ast.unparse(node)
    gate = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and ast.unparse(n.test) == "apply_crit_conversion"
    )
    assert "_crit_conversion_overrides" in ast.unparse(gate)
