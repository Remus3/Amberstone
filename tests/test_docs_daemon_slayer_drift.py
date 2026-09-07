"""Guard: docs/DAEMON_SLAYER.md header stays in lock-step with engine truth.

The Daemon Slayer summary doc restates the live engine identity in two
machine-checkable places that drifted silently on every ENGINE bump (CI runs
no pytest, so nothing failed on a stale doc - item 579, closing gaps f1 + f3
in docs/DS_COMPLETENESS_GAP.md):

  * the status banner (the ``Status: FUNCTIONALLY COMPLETE`` line) restates
    ``ENGINE_VERSION`` + ``patch``;
  * the ``server.py`` module-map row lists the :8860 HTTP route surface.

This guard pins those two STABLE identifiers to their source of truth
(``agents/daemon_slayer/__init__.py`` ENGINE_VERSION + ``current.txt`` patch)
and asserts the documented endpoint list covers every route the server
registers, so the next bump / route-add that forgets the doc fails locally.

It deliberately does NOT pin the ``def test_`` counts the doc carries - those
move on every test addition and are approximate prose, not an identity. ASCII
only (CLAUDE.md hard rule).

RM-208 - the route half of this guard used to parse server.py with the regex
``"(/[a-z][a-z-]*)":`` and compare in ONE direction. Two defects, both
measured:

  1. That pattern cannot match a path carrying a digit or a second ``/``, so
     ``/v2/fight-report`` and ``/v2/matchup`` were invisible to it - it saw 32
     of the 34 live routes, and a new ``/v2/*`` route could ship undocumented
     with the guard green. The three GET-only paths were visible only BY
     ACCIDENT: ``if path == "/health":`` ends in a Python statement colon,
     which is what satisfied the ``":`` anchor. Rewriting that ``if`` chain
     into an ``in (...)`` membership test would have silently dropped all
     three. Both halves are now read structurally with ``ast``: the
     ``_POST_ROUTES`` dict literal is walked for its keys and the ``do_GET``
     body for its path-shaped string constants, so a route is found as syntax
     rather than matched as text - and neither the digit/slash blindness nor
     the colon accident can recur.
  2. Only ``server - doc`` was computed, so the doc could name a route the
     server does not register and nothing failed. Both directions are
     asserted now.
"""
import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_INIT = _REPO_ROOT / "agents" / "daemon_slayer" / "__init__.py"
_SERVER = _REPO_ROOT / "agents" / "daemon_slayer" / "server.py"
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"

_SEMVER = r"\d+\.\d+\.\d+"
# The single ENGINE_VERSION assignment literal (source of truth, __init__:18).
_INIT_ENGINE = re.compile(rf'^ENGINE_VERSION = "({_SEMVER})"', re.MULTILINE)
# The doc status banner: "... ENGINE_VERSION 1.149.0 - 7362 tests - patch 16.12.1."
_DOC_STATUS = re.compile(
    rf"Status: FUNCTIONALLY COMPLETE.*?ENGINE_VERSION\s+({_SEMVER})\b"
    rf".*?patch\s+({_SEMVER})\b"
)
# The HTML index. do_GET answers ``if path in ("", "/")`` with a rendered page,
# not a JSON route, and the module-map row does not list it - so it is excluded
# from the documented surface deliberately, by name, not by a pattern accident.
_INDEX_PATHS = frozenset({"", "/"})


def _doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _server_ast() -> ast.Module:
    return ast.parse(_SERVER.read_text(encoding="utf-8"))


def _post_routes(tree: ast.Module) -> list[str]:
    """Ordered ``_POST_ROUTES`` keys, read structurally from the source.

    Parsed rather than imported: importing server.py drags in the whole
    engine. A dict-literal walk does not.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_POST_ROUTES":
                assert isinstance(node.value, ast.Dict), "_POST_ROUTES is not a dict literal"
                return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise AssertionError("_POST_ROUTES dict not found in agents/daemon_slayer/server.py")


def _get_only_routes(tree: ast.Module) -> set[str]:
    """Paths ``do_GET`` answers itself, i.e. the GET-only surface.

    Every path-shaped string constant inside ``do_GET``, minus the POST routes
    it forwards to ``_POST_ROUTES`` and minus the HTML index. Structural, so it
    survives the ``if path == X`` chain being rewritten as ``if path in (...)``
    - the old regex depended on that chain's trailing statement colon and would
    not have.
    """
    do_get = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_GET"),
        None,
    )
    assert do_get is not None, "do_GET not found in agents/daemon_slayer/server.py"
    literals = {
        n.value
        for n in ast.walk(do_get)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.startswith("/")
    }
    return literals - set(_post_routes(tree)) - set(_INDEX_PATHS)


def _server_routes() -> set[str]:
    """The full registered :8860 surface: POST routes plus the GET-only paths."""
    tree = _server_ast()
    return set(_post_routes(tree)) | _get_only_routes(tree)


def _doc_route_row() -> str:
    """The server.py module-map row (unique marker: 'ThreadingHTTPServer')."""
    row = next(
        (ln for ln in _doc_text().splitlines() if "ThreadingHTTPServer" in ln),
        None,
    )
    assert row, "missing the server.py 'ThreadingHTTPServer' module-map row"
    return row


def _doc_routes() -> set[str]:
    """Backticked route names on the module-map row.

    Anchored on the backticks rather than on a path pattern: the old bare
    ``/[a-z][a-z-]*`` scan chopped ``/v2/matchup`` into the fragments ``/v``
    and ``/matchup``, which matched no server route and which nothing asserted
    on. Whole-token extraction is what makes the reverse direction meaningful.
    """
    return set(re.findall(r"`(/[^`]+)`", _doc_route_row()))


def test_doc_engine_version_matches_source_of_truth():
    init_m = _INIT_ENGINE.search(_INIT.read_text(encoding="utf-8"))
    assert init_m, "no ENGINE_VERSION literal in agents/daemon_slayer/__init__.py"
    live = init_m.group(1)
    doc_m = _DOC_STATUS.search(_doc_text())
    assert doc_m, (
        "could not find the 'Status: FUNCTIONALLY COMPLETE ... ENGINE_VERSION "
        "<x> ... patch <y>' banner in docs/DAEMON_SLAYER.md"
    )
    assert doc_m.group(1) == live, (
        f"docs/DAEMON_SLAYER.md status banner ENGINE_VERSION {doc_m.group(1)} "
        f"!= live {live} (agents/daemon_slayer/__init__.py). Bump the doc when "
        "you bump the engine."
    )


def test_doc_patch_matches_current_txt():
    live = _CURRENT.read_text(encoding="utf-8").strip()
    doc_m = _DOC_STATUS.search(_doc_text())
    assert doc_m, "missing status banner in docs/DAEMON_SLAYER.md"
    assert doc_m.group(2) == live, (
        f"docs/DAEMON_SLAYER.md status banner patch {doc_m.group(2)} != live "
        f"{live} (data/daemon_slayer/current.txt)."
    )


def test_server_route_parse_sees_the_v2_and_get_only_routes():
    """Anchor on the four routes the old regex could not honestly see.

    ``/v2/fight-report`` + ``/v2/matchup`` were invisible outright; the three
    GET-only paths were visible only via the ``if path == "/health":``
    statement colon. If this ever fails, the parser regressed - not the doc.
    """
    routes = _server_routes()
    for path in ("/v2/fight-report", "/v2/matchup", "/health", "/snapshot",
                 "/modifier-summary"):
        assert path in routes, (
            f"{path} is registered in server.py but the route parser in this "
            "guard cannot see it - the guard is blind, fix the parser"
        )
    assert "/" not in routes, "the HTML index is not a documented JSON route"


def test_doc_endpoint_list_covers_all_server_routes():
    server_routes = _server_routes()
    assert server_routes, "no routes parsed from server.py - parser drift?"
    missing = sorted(server_routes - _doc_routes())
    assert not missing, (
        "docs/DAEMON_SLAYER.md server.py endpoint list is missing route(s) the "
        f"server registers: {missing}. Add them to the module-map row."
    )


def test_doc_endpoint_list_names_no_unregistered_route():
    """The reverse direction: a documented route the server does not serve.

    Without this, the module-map row could keep advertising a route that was
    renamed or deleted, and the one-directional check stayed green.
    """
    unknown = sorted(_doc_routes() - _server_routes())
    assert not unknown, (
        "docs/DAEMON_SLAYER.md server.py endpoint list names route(s) the "
        f"server does not register: {unknown}. Remove them from the module-map "
        "row, or register them."
    )
