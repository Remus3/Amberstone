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

RM-1186 extended it to the Build Insights view test. Its docstring cited
main.js:573-574 / lib/state.js:40 (sticky hash), main.js:802 (the
build-insights branch) and build_insights.js:280-290 (mock loader). The
main.js and build_insights.js cites had drifted onto unrelated code; the
state.js cite still fell inside VIEW_IDS, but only on its closing line, so
it too is now a symbol. It also called the view "8-tab";
web/index.html carries nine data-bi-tab buttons (four WPA tables plus five
chart panels).

RM-1188 extended it to the two lobby stability tests. Their module
docstrings cited panels/champ_select.js:704 (the csvSig render gate),
header.css:1170 (the reorder overlay) and header.css:1489 (the
.lv-member-action precedent), and their comments and test docstrings
cited main.js:761 / 4278 / 4618 / 5280 / 5498. Every header.css and
main.js cite had drifted onto unrelated code, and the champ_select.js one
sits in a file an unlanded lane commit rewrites. Comments drift the same
way docstrings do, so for these two files the whole source is held to
the no-line-cite rule (WHOLE_FILE_NO_CITES), not just the docstring.

RM-1190 extended the whole-file rule to the panel-file cites. Five
snapshot tests and tests/test_panel_visibility_permode.py cited
overlay.css:570, right_now.js:503-506, overlay_ds_controls.js:367-378,
active_match.js:1062-1063, lib/state.js:5 and tokens.css:119. The
overlay.css, active_match.js and tokens.css cites had drifted onto
unrelated code, and right_now.js:503-506 onto the comment above the stamp
rather than the stamp. The overlay_ds_controls.js and state.js cites
still pointed at the right lines, but only until the next edit above
them. A web/css/overlay.css comment pointed at its own line ":570",
which is now mid-file build-widget CSS. (web/vision_calibrator.html
repeats the tokens.css:119 cite, but in a <style> comment that
tests/test_web_ascii_sweep.py counts in its pinned live-half digest, so it
is left for a joint re-pin.) Each cite now names a symbol, and
SYMBOL_ANCHORS fails when the symbol leaves either the prose or the
source it names. The test_panel_snapshots.py comment also gave the wrong
reason for its None-tolerant lobby assertion: it said setMode
early-returns on an unchanged tag. setMode now always stamps on its first
call (`_modeStamped`). The lobby page reads None because only onHealth
calls setMode("client"), and health reaches that stubbed page only
through the slow HTTP fallback poll. The comment now says so.

RM-1192 extended the rule to the slider hit-target cites.
tests/test_overlay_slider_hit_target.py cited tokens.css:119,
header.css:2902, overlay_ds_controls.css:231, overlay.css:866 and
overlay_layout.js:734 / :745, and repeated the header.css and
overlay_ds_controls.css pair in its failure message. A web/css/overlay.css
comment repeated that pair, and two web/js/lib/overlay_layout.js comments
cited overlay_ds_controls.js:367-378. Only the overlay_ds_controls.css and
overlay_ds_controls.js cites still pointed at the right lines. The others
had drifted: tokens.css:119 onto --fs-xs, header.css:2902 onto
.ub-rp-section, overlay.css:866 onto the right-now stale badge, and
overlay_layout.js:734 / :745 onto the comment above _installLauncher and
into its body. Each now names its rule
selector or function, and REPO_FILES_NO_CITES holds all four files.

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
    "test_build_insights_view.py": (
        _STICKY,
        ("web/js/main.js", "function _viewFromHash"),
        ("web/js/lib/state.js", "export const VIEW_IDS"),
        ("web/js/main.js", 'if (viewId === "build-insights")'),
        ("web/js/panels/build_insights.js", "export function renderBuildInsights"),
        ("web/js/panels/build_insights.js", "function _ensureFetched"),
        ("web/js/panels/build_insights.js", "function _isMock"),
        ("web/js/panels/build_insights.js", "function _mockLoad"),
        ("web/js/panels/build_insights.js", "mockUrl: '/data/ui_mock/build_insights.json'"),
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
    "test_lobby_render_stability.py": (
        ("web/js/main.js", "setInterval(pollLcu, 2000)"),
        ("web/js/main.js", "_maybeRefreshLobbyView"),
        ("web/js/main.js", "_lobbyViewRefresh"),
        ("web/js/main.js", "function _renderPartyMembers"),
        ("web/js/main.js", "function _renderTop8"),
        ("web/js/main.js", "ul.dataset.lvPartySig"),
        ("web/js/main.js", "ul.dataset.lvTop8Sig === _t8Sig"),
        ("web/js/panels/champ_select.js", "section.dataset.csvSig === sig"),
        ("web/css/panels/header.css", ".lv-top8-reorder-btn::before"),
    ),
    "test_lobby_hit_targets.py": (
        ("web/css/panels/header.css", ".lv-top8-reorder-btn::before"),
        ("web/css/panels/header.css", ".lv-top8-reorder-btn:first-child::before"),
        ("web/css/panels/header.css", ".lv-top8-reorder-btn:last-child::before"),
        ("web/css/panels/header.css", ".lv-member-action::before"),
        ("web/js/main.js", "function _top8Hydrate"),
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
# Held to the no-line-cite rule over their whole source - comments and
# test-function docstrings included, not only the module docstring
# (RM-1188).
WHOLE_FILE_NO_CITES = (
    "test_lobby_hit_targets.py",
    "test_lobby_render_stability.py",
    "test_overlay_launcher_menu.py",
    "test_overlay_view.py",
    "test_panel_snapshots.py",
    "test_render_dedup_reshow.py",
    "test_vision_calibrator_seed_warning.py",
)
# Repo-relative files outside this directory held to the same rule
# (RM-1190: test_panel_visibility_permode.py carried the drifted
# tokens.css:119 cite; RM-1192: the slider hit-target test, the overlay.css
# slider comment and the overlay_layout.js menu comments). The value is text
# each file must still contain, so a gutted file cannot pass vacuously.
REPO_FILES_NO_CITES = {
    "tests/test_panel_visibility_permode.py": "tokens.css",
    "tests/test_overlay_slider_hit_target.py": "RANGE_MARKUP_CENSUS",
    "web/css/overlay.css": ".ovx-menu-slider",
    "web/js/lib/overlay_layout.js": "function _renderMenu",
}
# A comment in a source file citing its own line as "(see :NNN)" drifts the
# same way (RM-1190: overlay.css's band-channel comment said "see :570").
_BARE_SELF_CITE = re.compile(r"\(see :\d+")
BARE_SELF_CITE_FILES = ("web/css/overlay.css",)
# Each symbol that replaced a RM-1190 line cite must stay in the citing
# file AND in the source it names, so a rename turns this red instead of
# leaving the prose pointing at nothing. An optional third item is the
# text to find in the SOURCE when the cited name also appears in a mere
# comment there (the overlay.css self-cite repeats "7. Combat declutter";
# tokens.css names --hit-min in comments above its definition).
_DECLUTTER = ("web/css/overlay.css", "7. Combat declutter", "/* 7. Combat declutter")
_HIT_MIN = ("web/css/tokens.css", "--hit-min", "--hit-min:")
# RM-1192 precedent rules. The header.css source target includes the height
# line: a combined `.settings-row select, .settings-row input[type="range"]`
# rule sits above the real one and carries no height.
_HDR_RANGE = (
    "web/css/panels/header.css",
    '.settings-row input[type="range"]',
    '\n.settings-row input[type="range"] {\n  height: var(--hit-min)',
)
_OVSET_RANGE = (
    "web/css/panels/overlay_ds_controls.css",
    '.ovset-range > input[type="range"]',
    '.ovset-range > input[type="range"] {',
)
_P39 = "tests/snapshot_panels/"
SYMBOL_ANCHORS = {
    _P39 + "test_overlay_view.py": (
        _DECLUTTER,
        ("web/js/panels/right_now.js", "RN.root.dataset.s0Pulse"),
        ("web/js/panels/right_now.js", "function renderRightNow"),
    ),
    _P39 + "test_overlay_launcher_menu.py": (
        ("web/js/panels/overlay_ds_controls.js", "function _applySettingsToDom"),
    ),
    _P39 + "test_render_dedup_reshow.py": (
        ("web/js/panels/active_match.js", "function _renderSpikeMarkersFromCtx"),
    ),
    _P39 + "test_panel_snapshots.py": (
        ("web/js/lib/state.js", "export const state"),
        ("web/js/main.js", "_modeStamped"),
        ("web/js/main.js", "onHealth", "function onHealth"),
        ("web/js/main.js", "onState", "function onState"),
    ),
    _P39 + "test_vision_calibrator_seed_warning.py": (
        _HIT_MIN,
    ),
    "tests/test_panel_visibility_permode.py": (
        _HIT_MIN,
    ),
    "tests/test_overlay_slider_hit_target.py": (
        _HIT_MIN,
        _HDR_RANGE,
        _OVSET_RANGE,
        (
            "web/css/overlay.css",
            ".ovx-launcher-menu .ovx-menu-slider",
            'body[data-shell="overlay"] .ovx-launcher-menu .ovx-menu-slider '
            'input[type="range"] {',
        ),
        ("web/js/lib/overlay_layout.js", "_menuPanelRow", "function _menuPanelRow"),
    ),
    "web/css/overlay.css": (_DECLUTTER, _HDR_RANGE, _OVSET_RANGE),
    "web/js/lib/overlay_layout.js": (
        (
            "web/js/panels/overlay_ds_controls.js",
            "_applySettingsToDom",
            "function _applySettingsToDom",
        ),
    ),
}
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


@pytest.mark.parametrize("name", WHOLE_FILE_NO_CITES)
def test_whole_file_has_no_line_citations(name):
    src = (HERE / name).read_text(encoding="utf-8")
    assert "def test_" in src, f"{name} is empty or not a test module"
    cites = _LINE_CITE.findall(src)
    assert not cites, f"{name} carries drifting file:line cites: {cites}"


@pytest.mark.parametrize("rel", sorted(REPO_FILES_NO_CITES))
def test_repo_file_has_no_line_citations(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    must = REPO_FILES_NO_CITES[rel]
    assert must in src, f"{rel} no longer contains {must!r}; re-check this entry"
    cites = _LINE_CITE.findall(src)
    assert not cites, f"{rel} carries drifting file:line cites: {cites}"


@pytest.mark.parametrize("rel", BARE_SELF_CITE_FILES)
def test_source_has_no_bare_self_line_citations(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert len(src) > 1000, f"{rel} is empty; the guard would be vacuous"
    cites = _BARE_SELF_CITE.findall(src)
    assert not cites, f"{rel} carries drifting self line cites: {cites}"


@pytest.mark.parametrize("rel", sorted(SYMBOL_ANCHORS))
def test_symbol_anchors_exist_in_citer_and_source(rel):
    citer = (ROOT / rel).read_text(encoding="utf-8")
    for src_rel, needle, *src_needle in SYMBOL_ANCHORS[rel]:
        target = src_needle[0] if src_needle else needle
        assert _has_anchor(citer, needle), f"{rel} does not cite {needle!r}"
        src = (ROOT / src_rel).read_text(encoding="utf-8")
        assert _has_anchor(src, target), f"{src_rel} no longer contains {target!r}"
