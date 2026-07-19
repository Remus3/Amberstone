"""Guard: the DS Share package's authored docs keep their ROUTE-TABLE counts in
lock-step with the shipped server's real dispatch tables.

Sibling of ``test_ds_share_doc_anchors.py``. That test pins the MECHANICAL
version/patch anchors that ``tools/ds_share_sync.py`` rewrites automatically.
This one pins a class the sync tool does NOT maintain: the hand-authored route
counts and route table. They rotted once already - both docs claimed "4 GET-only
+ 15 POST = 19" against a server carrying 31 POST routes, a drift of 16 routes
that no existing check caught.

Source of truth is deliberately ``Share/src/agents/daemon_slayer/server.py``,
NOT the main-repo copy: ``Share/docs`` describes the SHIPPED PACKAGE. A
divergence test below asserts the two servers still agree, so a future split
fails loudly here instead of silently making the docs wrong for one of them.

Parsed with ``ast`` rather than imported: the Share tree ships a second
``agents.daemon_slayer`` package, and importing it under the same module name as
the live one is a collision this test has no need to risk.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SHARE_SERVER = _REPO / "Share" / "src" / "agents" / "daemon_slayer" / "server.py"
_MAIN_SERVER = _REPO / "agents" / "daemon_slayer" / "server.py"
_OVERVIEW = _REPO / "Share" / "docs" / "01_OVERVIEW.md"
_FUNCREF = _REPO / "Share" / "docs" / "02_FUNCTION_REFERENCE.md"

# The GET-only surface, as a contract. do_GET answers these four before it ever
# consults _GET_DISPATCH_ROUTES; "" and "/" are one route (the HTML index).
_GET_ONLY = ("/", "/health", "/snapshot", "/modifier-summary")


def _post_routes(server_py: Path) -> list[str]:
    """Ordered ``_POST_ROUTES`` keys, read statically from the source."""
    tree = ast.parse(server_py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_POST_ROUTES":
                assert isinstance(node.value, ast.Dict), "_POST_ROUTES is not a dict literal"
                return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise AssertionError(f"_POST_ROUTES not found in {server_py}")


def _get_only_literals(server_py: Path) -> set[str]:
    """Route literals compared against ``path`` inside ``do_GET``.

    Everything do_GET answers that is NOT a _POST_ROUTES key is a GET-only
    route. "" is folded into "/" (``if path in ("", "/")``).
    """
    tree = ast.parse(server_py.read_text(encoding="utf-8"))
    do_get = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_GET"),
        None,
    )
    assert do_get is not None, "do_GET not found"
    literals = {
        n.value
        for n in ast.walk(do_get)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/")
    }
    return literals - set(_post_routes(server_py))


def _norm(text: str) -> str:
    """Collapse whitespace so a claim that wraps across lines still matches."""
    return re.sub(r"\s+", " ", text)


class ServerDivergenceTests(unittest.TestCase):
    """Share/docs describes the shipped package; assert it still describes both."""

    def test_share_and_main_servers_agree_on_routes(self):
        self.assertEqual(
            _post_routes(_SHARE_SERVER), _post_routes(_MAIN_SERVER),
            "Share/src server.py and the main-repo server.py have diverged on "
            "_POST_ROUTES - Share/docs documents the SHARE one; update the docs "
            "and this test's expectations deliberately",
        )

    def test_share_server_is_byte_identical_to_main(self):
        self.assertEqual(
            _SHARE_SERVER.read_bytes(), _MAIN_SERVER.read_bytes(),
            "Share/src/agents/daemon_slayer/server.py drifted from the main-repo "
            "copy - run tools/ds_share_sync.py",
        )


class LiveRouteSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.post = _post_routes(_SHARE_SERVER)

    def test_post_routes_have_no_duplicates(self):
        self.assertEqual(len(self.post), len(set(self.post)))

    def test_get_only_surface_matches_the_contract(self):
        self.assertEqual(
            _get_only_literals(_SHARE_SERVER), set(_GET_ONLY),
            "do_GET's GET-only branch set changed - update both Share docs",
        )

    def test_get_dispatch_mirrors_post_routes(self):
        """``_GET_DISPATCH_ROUTES = set(_POST_ROUTES.keys())`` - assert the
        source still spells it that way, which is what makes 'each POST route is
        also GET-able' true in the docs."""
        src = _SHARE_SERVER.read_text(encoding="utf-8")
        self.assertIn("_GET_DISPATCH_ROUTES = set(_POST_ROUTES.keys())", src)


class DocumentedCountTests(unittest.TestCase):
    def setUp(self):
        self.post = _post_routes(_SHARE_SERVER)
        self.n_post = len(self.post)
        self.n_get = len(_GET_ONLY)
        self.total = self.n_post + self.n_get
        self.overview = _norm(_OVERVIEW.read_text(encoding="utf-8"))
        self.funcref = _norm(_FUNCREF.read_text(encoding="utf-8"))

    def test_overview_prose_counts(self):
        self.assertIn(
            f"4 GET-only routes plus {self.n_post} POST routes", self.overview,
            f"01_OVERVIEW.md route-count prose is stale - live is {self.n_post} POST",
        )
        self.assertIn(f"= {self.total} distinct paths", self.overview)

    def test_overview_section_headers(self):
        self.assertIn(f"**GET-only ({self.n_get}):**", self.overview)
        self.assertIn(f"**POST ({self.n_post}):**", self.overview)

    def test_overview_family_counts_sum_to_live_total(self):
        """The four family bullets must partition the live POST surface."""
        families = re.findall(r"\*(?:Build scoring \+ ranking|V2 composites|"
                              r"Per-champion kit axes|DSP live-context consumers) "
                              r"\((\d+)\):\*", self.overview)
        self.assertEqual(len(families), 4, "01_OVERVIEW.md lost a POST family bullet")
        self.assertEqual(
            sum(int(n) for n in families), self.n_post,
            f"01_OVERVIEW.md family counts {families} do not sum to {self.n_post}",
        )

    def test_funcref_prose_counts(self):
        self.assertIn(
            f"4 GET-only + {self.n_post} POST (each also GET-able) = {self.total} distinct paths",
            self.funcref,
            f"02_FUNCTION_REFERENCE.md route-count prose is stale - live is {self.n_post} POST",
        )
        self.assertIn(f"{self.n_post} entries", self.funcref)

    def test_funcref_table_headers(self):
        self.assertIn(f"GET-only routes ({self.n_get}):", self.funcref)
        self.assertIn(f"POST routes ({self.n_post})", self.funcref)


class DocumentedRouteTableTests(unittest.TestCase):
    """Every live route is actually IN the table, in dispatch order."""

    def setUp(self):
        self.post = _post_routes(_SHARE_SERVER)
        self.rows = self._numbered_rows()

    def _numbered_rows(self) -> list[tuple[int, str]]:
        rows = []
        for line in _FUNCREF.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\|\s*(\d+)\s*\|\s*`(/[^`]*)`\s*\|", line)
            if m:
                rows.append((int(m.group(1)), m.group(2)))
        return rows

    def test_row_count_matches_live(self):
        self.assertEqual(
            len(self.rows), len(self.post),
            f"02_FUNCTION_REFERENCE.md POST table has {len(self.rows)} rows, "
            f"live _POST_ROUTES has {len(self.post)}",
        )

    def test_rows_are_numbered_consecutively_from_one(self):
        self.assertEqual([n for n, _ in self.rows], list(range(1, len(self.post) + 1)))

    def test_table_paths_match_dispatch_order(self):
        self.assertEqual(
            [p for _, p in self.rows], self.post,
            "the documented POST table drifted from _POST_ROUTES insertion order",
        )

    def test_every_live_route_is_documented(self):
        documented = {p for _, p in self.rows}
        missing = sorted(set(self.post) - documented)
        self.assertEqual(missing, [], f"undocumented live routes: {missing}")

    def test_overview_lists_every_live_route(self):
        overview = _OVERVIEW.read_text(encoding="utf-8")
        missing = sorted(r for r in self.post if f"`{r}`" not in overview)
        self.assertEqual(missing, [], f"01_OVERVIEW.md omits live routes: {missing}")


class SeamDocumentationTests(unittest.TestCase):
    """The two live DEFAULT-OFF seams must stay documented in the authored half.

    Both existed in Share/src with tests and appeared NOWHERE in Share/docs.
    """

    def setUp(self):
        self.funcref = _FUNCREF.read_text(encoding="utf-8")

    def test_term_a_team_blended_seam_is_documented(self):
        self.assertIn("team_blended", self.funcref)
        self.assertIn("Term A - ally-granted EHP", self.funcref)

    def test_kit_conversion_seam_is_documented(self):
        self.assertIn("kit_conversion_strength", self.funcref)
        self.assertIn("RM-86 kit-blindness gate", self.funcref)

    def test_seams_exist_in_the_shipped_source(self):
        """The docs must not describe a seam the package does not ship."""
        ds = _REPO / "Share" / "src" / "agents" / "daemon_slayer"
        self.assertIn("team_blended", (ds / "ehp.py").read_text(encoding="utf-8"))
        self.assertIn("kit_conversion_strength", (ds / "rank.py").read_text(encoding="utf-8"))
        self.assertTrue((ds / "kit_conversion.py").exists())
        self.assertTrue((ds / "_champion_ally_reach.py").exists())

    def test_self_contained_seam_claim_holds(self):
        """Both seams are documented as working inside the shipped package,
        UNLIKE the cast-rate seam whose resolver lives in the host app. That
        claim is only true while their resolvers stay free of a ``core`` import.
        """
        ds = _REPO / "Share" / "src" / "agents" / "daemon_slayer"
        for name in ("kit_conversion.py", "_champion_ally_reach.py", "_item_ally_grant.py"):
            src = (ds / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("core"):
                    self.fail(
                        f"{name} imports from core - it would silently no-op inside "
                        "the Share package, and the docs claim it does not"
                    )
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.startswith("core"),
                            f"{name} imports core - contradicts the documented seam claim",
                        )

    def test_ally_reach_data_file_ships_in_the_package(self):
        """champion_ally_reach resolves its data relative to the package root.
        If the file is absent the gate fail-softs to False and the Term A seam
        silently no-ops - the exact trap the docs say it avoids.
        """
        root = _REPO / "Share" / "src" / "data" / "daemon_slayer"
        patch = (root / "current.txt").read_text(encoding="utf-8").strip()
        self.assertTrue(
            (root / patch / "champion_abilities.json").exists(),
            "champion_abilities.json is missing from the Share package - the "
            "Term A ally-reach gate would fail-soft to inert",
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_docs_and_this_test_are_ascii(self):
        for p in (_OVERVIEW, _FUNCREF, Path(__file__)):
            raw = p.read_bytes()
            bad = [i for i, b in enumerate(raw) if b >= 128]
            self.assertEqual(bad[:5], [], f"{p.name} carries non-ASCII bytes at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
