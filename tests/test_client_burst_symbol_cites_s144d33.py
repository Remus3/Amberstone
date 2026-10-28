"""Guard: core/daemon_slayer_client.py cites burst.py by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. ``rank_assassin_for`` cited
``burst.py:522`` / ``:1075`` / ``:2018`` / ``:2160-2162``, written by the
RM-115 drain (041984580 and 5a9d54c9c, 2026-07-25). At 5a9d54c9c they named the
``assume_magic_burst`` parameter of ``compute_burst_damage``, its Collector
gate ``if assume_takedown and target_max_hp > 0:``, the preset-armor
substitution in ``rank_items_by_burst`` (one line BELOW its
``ranking_target_armor <= 0.0`` guard) and that ranker's ``kit_conversion``
lookup gated on ``kit_conversion_strength > 0.0``. All four have since moved,
and a line cite into an engine file other commits keep editing resolves to
SOME line forever, so it never fails loudly.

Scope: core/daemon_slayer_client.py only. The other tracked .py ``burst.py:<n>``
cites (server.py, dps.py, _rune_offense_grants.py and DS tests) are the rest
of RM-1053.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT = REPO / "core" / "daemon_slayer_client.py"
BURST = REPO / "agents" / "daemon_slayer" / "burst.py"

# ``burst.py:522``, ``(burst.py:2160-2162)``; the boundary keeps a longer
# module name ending in ``burst.py`` out.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])burst\.py:\d")

# Phrases only the replacement prose carries (bare symbol names already occur
# elsewhere in the client, so they would pass with the prose deleted). Each
# claim is pinned to burst.py below, so a rename or a moved gate fails here
# instead of leaving the prose stale.
_NAMED_IN_PROSE = (
    "compute_burst_damage\n    # does). It stays here",
    "(rank_items_by_burst gates its kit_conversion\n"
    "    # lookup on kit_conversion_strength > 0.0)",
    "substitution in rank_items_by_burst is guarded on\n"
    "    #     ranking_target_armor <= 0.0 (the caller's armor)",
    "(compute_burst_damage credits it only when target_max_hp > 0)",
)


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(BURST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"burst.py has no top-level def {name}")


def _params(fn: ast.FunctionDef) -> set[str]:
    return {a.arg for a in fn.args.args + fn.args.kwonlyargs}


def _segment(fn: ast.FunctionDef) -> str:
    return ast.get_source_segment(BURST.read_text(encoding="utf-8"), fn) or ""


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "does, burst.py:522). It stays",
        "(burst.py:2160-2162), so 0.0",
        "<= 0.0 (burst.py:2018). At",
        "== 0.0 (burst.py:1075), which",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "burst.py",
        "agents.daemon_slayer.burst",
        "burst.rank_items_by_burst",
        "x_burst.py:12",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_burst():
    text = CLIENT.read_text(encoding="utf-8")
    hits = [
        f"daemon_slayer_client.py:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_prose_names_the_burst_symbols():
    text = CLIENT.read_text(encoding="utf-8")
    missing = [name for name in _NAMED_IN_PROSE if name not in text]
    assert not missing, missing


def test_magic_burst_is_a_compute_param_not_a_ranker_param():
    compute = _params(_function("compute_burst_damage"))
    ranker = _params(_function("rank_items_by_burst"))
    assert "assume_magic_burst" in compute, "compute_burst_damage lost the seam"
    assert "assume_magic_burst" not in ranker, (
        "rank_items_by_burst now takes assume_magic_burst - the client comment "
        "saying /rank-assassin correctly refuses it is stale"
    )


def test_collector_execute_is_gated_on_positive_target_max_hp():
    body = _segment(_function("compute_burst_damage"))
    assert "if assume_takedown and target_max_hp > 0:" in body, (
        "the Collector gate moved or changed - re-check the client comment"
    )


def test_ranker_gates_armor_substitution_and_kit_conversion():
    body = _segment(_function("rank_items_by_burst"))
    assert "if ranking_target_armor <= 0.0:" in body, (
        "the preset-armor guard moved or changed - re-check the client comment"
    )
    assert "if kit_conversion_strength > 0.0 else None" in body, (
        "the kit_conversion gate moved or changed - re-check the client comment"
    )
