"""Guard: DS server.py cites burst.py and itself by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. ``agents/daemon_slayer/server.py``
carried five line cites:

- ``burst.py:485`` twice (``_route_burst`` and ``_route_rank_assassin``),
  written by 3f2557286 (2026-06-27), where it named the ``assume_magic_burst``
  parameter of ``compute_burst_damage``;
- ``burst.py:2160-2163`` (``_route_rank_assassin``), written by 041984580
  (2026-07-25), where it named ``rank_items_by_burst``'s ``kit_conversion``
  lookup gated on ``kit_conversion_strength > 0.0``;
- ``server.py:481`` (``_route_rank_assassin``, 041984580) and
  ``server.py:518`` (``_route_rank_bruiser``, c09d9397b), both meaning the
  CARRY route's ``kit_conversion_strength`` read in ``_route_rank``. The first
  was right on the pre-edit tree and staled inside its own commit (the read sat
  at 520 once 041984580 landed); the second was two lines short when written.

At HEAD every one of those lines holds unrelated code, though every claim
still holds. A line cite into a file other commits keep editing resolves to
SOME line forever, so it never fails loudly.

Scope: server.py's ``burst.py:<n>`` and ``server.py:<n>`` cites only. Its
other line cites (``hybrid.py``, ``rank.py``, ``dps.py``) and the remaining
tracked ``burst.py:<n>`` cites elsewhere are not this guard's.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
SERVER = DS / "server.py"
BURST = DS / "burst.py"

# ``burst.py:485``, ``(server.py:481)``; the boundary keeps a longer module
# name ending in ``burst.py`` / ``server.py`` out.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:burst|server)\.py:\d")

# Phrases only the replacement prose carries; each claim is pinned to the code
# below, so a rename or a moved gate fails here instead of leaving it stale.
_NAMED_IN_PROSE = (
    "compute_burst_damage does (its assume_magic_burst parameter - the on-cast",
    "(only compute_burst_damage takes them as parameters)",
    "route (_route_rank) to the bruiser ranker",
    "route (_route_rank) to the assassin/burst ranker. rank_items_by_burst",
    "(it gates its\n    # kit_conversion lookup on kit_conversion_strength > 0.0)",
)


def _function(path: Path, name: str) -> tuple[ast.FunctionDef, str]:
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node, ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{path.name} has no top-level def {name}")


def _params(fn: ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "(burst.py:485 - the on-cast",
        "does at burst.py:485).",
        "ranker. burst.py:2160-2163",
        "route (server.py:518) to",
        "route (server.py:481) to",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "burst.py",
        "server.py",
        "agents.daemon_slayer.burst",
        "x_burst.py:12",
        "mcp_server.py:40",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_burst_or_server():
    text = SERVER.read_text(encoding="utf-8")
    hits = [
        f"server.py:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_prose_names_the_symbols():
    text = SERVER.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_burst_seams_are_compute_params_not_ranker_params():
    compute = _params(_function(BURST, "compute_burst_damage")[0])
    ranker_fn = _function(BURST, "rank_items_by_burst")[0]
    ranker = _params(ranker_fn)
    assert ranker_fn.args.kwarg is None, (
        "rank_items_by_burst grew **kwargs - re-check the /burst scoping comments"
    )
    for seam in (
        "assume_magic_burst",
        "assume_physical_burst",
        "assume_shielded_target",
    ):
        assert seam in compute, f"compute_burst_damage lost {seam}"
        assert seam not in ranker, (
            f"rank_items_by_burst now takes {seam} - the server comments "
            "scoping it to /burst are stale"
        )


def test_ranker_gates_kit_conversion_on_positive_strength():
    _, body = _function(BURST, "rank_items_by_burst")
    assert "if kit_conversion_strength > 0.0 else None" in body, (
        "the kit_conversion gate moved or changed - re-check the server comment"
    )


def test_carry_route_reads_kit_conversion_strength():
    read = '_opt_float(body, "kit_conversion_strength", 0.0)'
    for route in ("_route_rank", "_route_rank_bruiser", "_route_rank_assassin"):
        _, body = _function(SERVER, route)
        assert read in body, f"{route} no longer reads kit_conversion_strength"
