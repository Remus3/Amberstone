"""Guard: core/daemon_slayer_client.py cites the DS engine by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The client still carried fifteen line
cites into server.py, rank.py, ehp.py, hybrid.py and abilities.py, written by
the W2 conversion plumb (51e6dd0cf), the RM-115 drain (041984580), RM-118 and
RM-334 (f3ab8ed72). Every one had drifted off its line, and a line cite into
an engine file other commits keep editing resolves to SOME line forever, so it
never fails loudly. Each claim was re-read by symbol at HEAD and holds, except
one that was already imprecise when written: "/rank-mage is the sole route
that parses" apply_passive_aura_damage. The same commit (041984580) taught
``_route_ability_dps`` to parse it too, so the prose now says sole RANKER
route, and the test below pins exactly which routes parse it.

Scope: the engine cites in core/daemon_slayer_client.py only. Its cites into
RC modules (dashboard/, core/) and the burst.py cites (guarded by
test_client_burst_symbol_cites_s144d33.py) are out of scope here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT = REPO / "core" / "daemon_slayer_client.py"
DS = REPO / "agents" / "daemon_slayer"

# ``server.py:481``, ``(ehp.py:3161-3162)``; the boundary keeps a longer
# module name ending in one of these (``_hybrid.py``) out.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:server|rank|ehp|hybrid|abilities)\.py:\d"
)

# Phrases only the replacement prose carries, so deleting the prose fails here.
_NAMED_IN_PROSE = (
    "parsed off the SAME POST /rank body server-side (_route_rank).",
    "(``_route_rank`` in ``agents/daemon_slayer/server.py``) and accepted by",
    "engine (``rank_items`` parameters)",
    "(rank_items' RM-86 L1 gate)",
    "``compute_ehp``'s ``if apply_build_tenacity:``",
    "``rank_items_by_ehp`` names BOTH as parameters",
    "``rank_items_by_hybrid`` names every one as a parameter",
    "(AbilitiesSnapshot.load)",
    "the scalar /ability-dps route parses it too",
    "/rank-mage is the sole RANKER route that\n"
    "    # parses apply_passive_aura_damage (_route_rank_mage)",
)


def _tree(name: str) -> tuple[str, ast.Module]:
    src = (DS / name).read_text(encoding="utf-8")
    return src, ast.parse(src)


def _function(name: str, fn: str) -> tuple[str, ast.FunctionDef]:
    src, tree = _tree(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            return src, node
    raise AssertionError(f"{name} has no def {fn}")


def _params(name: str, fn: str) -> set[str]:
    _, node = _function(name, fn)
    return {a.arg for a in node.args.args + node.args.kwonlyargs}


def _segment(name: str, fn: str) -> str:
    src, node = _function(name, fn)
    return ast.get_source_segment(src, node) or ""


def _string_args(node: ast.FunctionDef) -> set[str]:
    return {
        a.value
        for call in ast.walk(node) if isinstance(call, ast.Call)
        for a in call.args
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    }


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "server-side (server.py:481 / :488).",
        "(``rank.py:918`` / ``:921``)",
        "names BOTH (ehp.py:3161-3162), so",
        "every one (hybrid.py:1037-1042), so",
        "the engine (abilities.py:1006), resolved",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "agents/daemon_slayer/server.py",
        "_route_rank_mage",
        "my_hybrid.py:12",
        "burst.py:522",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_engine_line_cite_left_in_client():
    hits = [
        f"daemon_slayer_client.py:{n}: {line.strip()}"
        for n, line in enumerate(
            CLIENT.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = CLIENT.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_route_rank_parses_both_conversion_seams_and_rank_items_takes_them():
    _, node = _function("server.py", "_route_rank")
    assert {"kit_conversion_strength", "apply_crit_conversion"} <= _string_args(node)
    assert {"kit_conversion_strength", "apply_crit_conversion"} <= _params(
        "rank.py", "rank_items")


def test_rank_items_consults_registry_only_when_positive():
    assert "if kit_conversion_strength > 0.0 else None" in _segment(
        "rank.py", "rank_items"), "the RM-86 L1 gate moved - re-check the client"


def test_tank_and_bruiser_routes_read_build_tenacity_tri_state():
    for route in ("_route_rank_tank", "_route_rank_bruiser"):
        assert '"apply_build_tenacity" in body' in _segment("server.py", route), (
            f"{route} no longer reads apply_build_tenacity None-when-absent"
        )


def test_ehp_and_hybrid_rankers_name_the_rune_lanes():
    assert {"apply_rune_self_heal", "apply_rune_shield_grants"} <= _params(
        "ehp.py", "rank_items_by_ehp")
    assert {
        "apply_rune_self_heal", "apply_rune_shield_grants",
        "apply_rune_offense_grants",
    } <= _params("hybrid.py", "rank_items_by_hybrid")


def test_compute_ehp_reads_item_tenacity_under_the_flag():
    body = _segment("ehp.py", "compute_ehp")
    assert "if apply_build_tenacity:" in body
    assert "total_item_tenacity(item_ids or ())" in body


def test_ability_base_overrides_is_a_load_time_param():
    assert "apply_ability_base_overrides" in _params("abilities.py", "load")


def test_passive_aura_damage_parsed_by_rank_mage_and_ability_dps_only():
    _, tree = _tree("server.py")
    parsers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("_route_")
        and "apply_passive_aura_damage" in _string_args(node)
    }
    assert parsers == {"_route_rank_mage", "_route_ability_dps"}, parsers
