"""RM-336 - keep the CLAUDE.md DS deep-reference route attributions honest.

CLAUDE.md is auto-loaded into every session, so a wrong route attribution on its
Daemon Slayer deep-reference line misleads by default. Two attributions were
measured wrong on 2026-09-03 and one was understated:

  - ``ds.hybrid apply_ad_axis_ability_damage`` implied ``/hybrid`` parses the
    flag. It does not; ``/rank`` and ``/rank-bruiser`` do.
  - ``ds.ehp score_by=team_blended`` implied ``/ehp`` parses ``score_by``. It
    does not; ``/rank-tank`` and ``/rank-bruiser`` do, and only ``/rank-tank``
    accepts the ``team_blended`` value.
  - ``ds.dps apply_rune_offense_grants`` named one of the three routes that
    parse it.

This is the RM-118 durable ("the ownership prose lies in BOTH directions")
recurring in the doc layer. The fence is a re-derivation, not a second copy of
the prose: the expected sets below are measured from ``server.py`` by AST, so a
future wiring change fails this test and forces the doc to be updated with it.

WHY AST AND NOT GREP: a substring sweep over a route's source text sees
COMMENTS. Both false attributions above survived a first pass precisely because
``_route_ehp`` mentions ``score_by`` in a cross-reference comment and
``_route_hybrid`` mentions ``apply_ad_axis_ability_damage`` in one. Comments do
not appear in the AST at all, which is the whole point of parsing here.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SERVER = _REPO / "agents" / "daemon_slayer" / "server.py"
_CLAUDE_MD = _REPO / "CLAUDE.md"

# Measured 2026-09-03 by the AST sweep in _parsing_routes below.
EXPECTED_PARSING_ROUTES: dict[str, set[str]] = {
    "apply_ad_axis_ability_damage": {"_route_rank", "_route_rank_bruiser"},
    "score_by": {"_route_rank_bruiser", "_route_rank_tank"},
    "apply_rune_offense_grants": {"_route_dps", "_route_hybrid", "_route_rank_bruiser"},
    # RM-333: no HTTP route arms this seam at all.
    "apply_canonical_cast_rate_keys": set(),
}

# Prose that asserts a route which does not parse the flag. Each of these was
# literally present in CLAUDE.md before RM-336.
FALSE_ATTRIBUTIONS: tuple[str, ...] = (
    "ds.hybrid apply_ad_axis_ability_damage",
    "ds.ehp score_by",
    "ds.dps apply_rune_offense_grants",
)


def _route_functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_route_")
    ]


def _parsing_routes(flag: str) -> set[str]:
    """Route functions that reference ``flag`` in CODE (never in a comment)."""
    hits: set[str] = set()
    for func in _route_functions():
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and node.id == flag:
                hits.add(func.name)
                break
            if isinstance(node, ast.Constant) and node.value == flag:
                hits.add(func.name)
                break
            if isinstance(node, ast.keyword) and node.arg == flag:
                hits.add(func.name)
                break
    return hits


class ClaudeMdDsRouteAttributionTests(unittest.TestCase):
    def test_route_universe_is_not_empty(self) -> None:
        """Guard the guard: a broken parser would make every check vacuous."""
        routes = _route_functions()
        self.assertGreater(
            len(routes),
            20,
            "AST sweep found almost no _route_* functions - the parser is broken, "
            "so every other assertion in this file is vacuous",
        )

    def test_parsing_routes_match_the_measured_sets(self) -> None:
        for flag, expected in EXPECTED_PARSING_ROUTES.items():
            with self.subTest(flag=flag):
                self.assertEqual(
                    _parsing_routes(flag),
                    expected,
                    f"{flag} route wiring changed. Update CLAUDE.md's DS deep-reference "
                    f"line in the SAME commit, then update EXPECTED_PARSING_ROUTES.",
                )

    def test_flags_are_still_named_in_claude_md(self) -> None:
        """A rename must not silently turn the prose checks below into no-ops."""
        text = _CLAUDE_MD.read_text(encoding="utf-8")
        for flag in EXPECTED_PARSING_ROUTES:
            if flag == "score_by":
                continue  # named as ``score_by=team_blended`` in the prose
            with self.subTest(flag=flag):
                self.assertIn(flag, text)

    def test_claude_md_carries_no_false_route_attribution(self) -> None:
        text = _CLAUDE_MD.read_text(encoding="utf-8")
        for phrase in FALSE_ATTRIBUTIONS:
            with self.subTest(phrase=phrase):
                self.assertNotIn(
                    phrase,
                    text,
                    f"CLAUDE.md attributes a flag to a route that does not parse it: "
                    f"{phrase!r}. Name the MODULE plus the parsing ROUTES instead.",
                )

    def test_canonical_cast_rate_keys_is_documented_as_routeless(self) -> None:
        """RM-333: the seam is real but no request body can arm it."""
        text = _CLAUDE_MD.read_text(encoding="utf-8")
        self.assertEqual(_parsing_routes("apply_canonical_cast_rate_keys"), set())
        self.assertIn("NO HTTP route parses it", text)


if __name__ == "__main__":
    unittest.main()
