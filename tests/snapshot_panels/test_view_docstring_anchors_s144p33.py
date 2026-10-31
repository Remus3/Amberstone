"""
tests/snapshot_panels/test_view_docstring_anchors_s144p33.py
RM-1184: the History, Session, Settings and User Builds view snapshot
tests describe their router and mock-loader drive path by SYMBOL, never
by file:line.

Their module docstrings cited main.js line numbers (main.js:958-959 for
the sticky-hash rule, main.js:764 / 765 / 782-784 for the applyView
branches, main.js:1781 / 1856 / 2208-2215 for the ui_mock loaders). Every
one had drifted: the sticky-hash rule is `_hashIsStaleGameState` in
`_viewResolveAndApply`, and the branches and loaders sit hundreds of
lines lower. main.js line numbers move on every edit above them (an
unlanded lane commit shifts them again), so the cites are replaced by
symbols, and this guard fails when:

- a docstring carries a .js / .css / .py file:line citation;
- a named anchor is missing from the docstring or from the source file
  it names (so a source rename turns this red instead of leaving the
  prose pointing at nothing);
- a docstring names a `name()` call that no web/js module defines (the
  Settings docstring named renderLoopStatus(), which main.js no longer
  calls or imports).

RM-1185 extended it to the Home, Lobby and Active Match view tests.
Their docstrings cited main.js:3445 / 3008 (home startup fetch and mock
loader), main.js:731 / 3542 / 4863 (lobby branch, mock loader, queue-name
uppercase) and main.js:630 (active-match branch); all six had drifted onto
unrelated code. The Active Match docstring also listed a `cooldowns` ctx
key that none of the mock-path renderActiveMatch calls in main.js passes.
Its "hash wins" sentence (and the Lobby "hash survives" one) now says why:
`_midFlight` is false on the home auto-derive, so the clear gated on
`_hashIsStaleGameState` never runs.

The docstrings are read with ast, so this guard needs no browser and no
mock server. test_replay_view.py carries its own guard of the same shape
(RM-1183).
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).parent

_STICKY = ("web/js/main.js", "_hashIsStaleGameState")

DOC_ANCHORS = {
    "test_active_match_view.py": (
        _STICKY,
        ("web/js/main.js", 'if (viewId === "active-match" && _amIsMock() && _amMockUrl())'),
        ("web/js/main.js", "function _amMockLoad"),
        ("web/js/panels/active_match.js", "const AM_MOCK_FIXTURES"),
        ("web/js/panels/active_match.js", "function _renderDraftEloFromCtx"),
    ),
    "test_home_view.py": (
        ("web/js/main.js", "function _homeWireStartup"),
        ("web/js/main.js", 'if (viewId === "home")'),
        ("web/js/main.js", "function _homeIsMock"),
        ("web/js/main.js", "function _homeMockLoad"),
    ),
    "test_lobby_view.py": (
        _STICKY,
        ("web/js/main.js", 'if (viewId === "lobby")'),
        ("web/js/main.js", "function _lobbyResolveLcu"),
        ("web/js/main.js", "function _lobbyMockLoad"),
        ("web/js/main.js", 'lobby.queue_name || ("queue "'),
        ("web/js/main.js", "function _renderPartyMembers"),
    ),
    "test_history_view.py": (
        _STICKY,
        ("web/js/main.js", 'if (viewId === "history")'),
        ("web/js/main.js", "function _historyMockLoad"),
        ("web/js/main.js", "_historyMockSliceForScope"),
    ),
    "test_session_view.py": (
        _STICKY,
        ("web/js/main.js", 'if (viewId === "session")'),
        ("web/js/main.js", "function _sessionMockLoad"),
    ),
    "test_settings_view.py": (
        _STICKY,
        ("web/js/main.js", "function _viewFromHash"),
        ("web/js/lib/state.js", "export const VIEW_IDS"),
        ("web/js/main.js", 'if (viewId === "settings")'),
    ),
    "test_user_builds_view.py": (
        _STICKY,
        ("web/js/main.js", 'if (viewId === "user-builds")'),
        ("web/js/main.js", "function _userBuildsFetchAndRender"),
        ("web/js/main.js", "if (!builds.length && uiMockOn)"),
    ),
}

_LINE_CITE = re.compile(r"[\w./-]+\.(?:js|css|py):\d+")
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\(\)")


def _docstring(name):
    tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
    return ast.get_docstring(tree, clean=False) or ""


def _has_anchor(text, needle):
    # An anchor that starts or ends on an identifier character must match
    # a whole identifier there: `function _homeIsMock` must not be satisfied
    # by a renamed `function _homeIsMockX` (RM-1185 mutation finding).
    head = r"(?<![\w$])" if re.match(r"[\w$]", needle[0]) else ""
    tail = r"(?![\w$])" if re.match(r"[\w$]", needle[-1]) else ""
    return re.search(head + re.escape(needle) + tail, text) is not None


def _web_js_source():
    parts = []
    for p in sorted((ROOT / "web" / "js").rglob("*.js")):
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.mark.parametrize("name", sorted(DOC_ANCHORS))
def test_docstring_has_no_line_citations(name):
    doc = _docstring(name)
    assert doc, f"{name} has no module docstring"
    cites = _LINE_CITE.findall(doc)
    assert not cites, f"{name} docstring carries drifting file:line cites: {cites}"


@pytest.mark.parametrize("name", sorted(DOC_ANCHORS))
def test_docstring_anchors_exist_in_doc_and_source(name):
    doc = _docstring(name)
    for rel, needle in DOC_ANCHORS[name]:
        assert rel in doc, f"{name} docstring does not name {rel}"
        assert _has_anchor(doc, needle), f"{name} docstring does not cite {needle!r}"
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert _has_anchor(src, needle), f"{rel} no longer contains {needle!r}"


@pytest.mark.parametrize("name", sorted(DOC_ANCHORS))
def test_docstring_named_calls_are_defined_in_web_js(name):
    doc = _docstring(name)
    src = _web_js_source()
    calls = sorted(set(_CALL.findall(doc)))
    assert calls, f"{name} docstring names no calls; the guard would be vacuous"
    missing = [c for c in calls if not re.search(r"function\s+" + re.escape(c) + r"\s*\(", src)]
    assert not missing, f"{name} docstring names undefined calls: {missing}"
