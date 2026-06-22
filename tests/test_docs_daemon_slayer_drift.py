"""Guard: docs/DAEMON_SLAYER.md header stays in lock-step with engine truth.

The Daemon Slayer summary doc restates the live engine identity in two
machine-checkable places that drifted silently on every ENGINE bump (CI runs
no pytest, so nothing failed on a stale doc - item 579, closing gaps f1 + f3
in docs/DS_COMPLETENESS_GAP.md):

  * the status banner (the ``Status: FUNCTIONALLY COMPLETE`` line) restates
    ``ENGINE_VERSION`` + ``patch``;
  * the ``server.py`` module-map row lists the :8893 HTTP route surface.

This guard pins those two STABLE identifiers to their source of truth
(``agents/daemon_slayer/__init__.py`` ENGINE_VERSION + ``current.txt`` patch)
and asserts the documented endpoint list covers every route the server
registers, so the next bump / route-add that forgets the doc fails locally.

It deliberately does NOT pin the ``def test_`` counts the doc carries - those
move on every test addition and are approximate prose, not an identity. ASCII
only (CLAUDE.md hard rule).
"""
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
# Route dict-key literals registered in server.py ("/rank":, "/anti-tank": ...).
_SERVER_ROUTE = re.compile(r'"(/[a-z][a-z-]*)":')


def _doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


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


def test_doc_endpoint_list_covers_all_server_routes():
    server_routes = set(_SERVER_ROUTE.findall(_SERVER.read_text(encoding="utf-8")))
    assert server_routes, "no route literals parsed from server.py - regex drift?"
    # The documented surface is the server.py module-map row (unique marker).
    doc_line = next(
        (ln for ln in _doc_text().splitlines() if "ThreadingHTTPServer" in ln),
        None,
    )
    assert doc_line, "missing the server.py 'ThreadingHTTPServer' module-map row"
    doc_routes = set(re.findall(r"/[a-z][a-z-]*", doc_line))
    missing = sorted(server_routes - doc_routes)
    assert not missing, (
        "docs/DAEMON_SLAYER.md server.py endpoint list is missing route(s) the "
        f"server registers: {missing}. Add them to the module-map row."
    )
