"""
tests/snapshot_panels/test_panel_visibility_tabs_keyboard.py
RM-1081 (s144 uiux): the PANEL VISIBILITY context tabs on the Settings view
(SR / ARAM / ARENA / TFT / OUT-OF-GAME, web/js/panels/panel_visibility.js
buildPanelVisibilitySettings) were keyboard-unreachable.

_selectTab gave the selected tab tabIndex 0 and every other tab tabIndex -1
(the WAI-ARIA roving-tabindex half of a tablist), but nothing handled the
arrow keys (the other half): no keydown listener on the bar, and no
ArrowRight anywhere in web/js. So Tab reached exactly one tab, the four
others were skipped by the tab sequence, and arrows did nothing. Measured in
headless Chromium under /?ui_mock=1#settings at 1920x920: with the default
OUT-OF-GAME tab selected, ArrowRight / ArrowLeft / Home / End left focus and
selection where they were, so a keyboard user could not open the TFT (or any
other) context's checkboxes at all. It is the only roving-tabindex tablist in
web/ (the other role="tab" bars leave every tab in the tab sequence).

Fix (the WAI-ARIA APG tabs pattern, automatic activation because selecting a
tab only re-renders its checkbox rows): ArrowRight / ArrowLeft move to the
next / previous tab with wrap, Home / End to the first / last; the moved-to
tab is focused, selected and persisted like a click. The rows host is now the
tablist's role="tabpanel", labelled by the selected tab, and every tab names
it in aria-controls.

The grep contract for the tab bar (tests/test_panel_visibility_permode.py)
cannot see any of this; this file drives real key presses.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORT = {"width": 1920, "height": 920}

# TABS order in panel_visibility.js.
_ORDER = ["in-game-sr", "in-game-aram", "in-game-arena", "in-game-tft", "out-game"]

_READ = """() => {
  const card = document.getElementById("panel-visibility-card");
  const tabs = Array.from(card.querySelectorAll(".pv-tab"));
  const sel = tabs.filter((t) => t.getAttribute("aria-selected") === "true");
  const panel = card.querySelector(".pv-table");
  const cbs = Array.from(panel.querySelectorAll("input[type=checkbox]"));
  const act = document.activeElement;
  let stored = null;
  try { stored = sessionStorage.getItem("rc-pv-tab"); } catch (_e) { stored = null; }
  return {
    tabs: tabs.map((t) => ({
      ctx: t.dataset.pvTab, id: t.id, tabIndex: t.tabIndex,
      selected: t.getAttribute("aria-selected"),
      controls: t.getAttribute("aria-controls"),
    })),
    selected: sel.map((t) => t.dataset.pvTab),
    focused: act && act.classList.contains("pv-tab") ? act.dataset.pvTab : null,
    focusVisible: !!(act && act.matches(".pv-tab:focus-visible")),
    ring: act ? getComputedStyle(act).boxShadow : "",
    rowContexts: Array.from(new Set(cbs.map((c) => c.dataset.pvContext))),
    rowCount: cbs.length,
    panelId: panel.id,
    panelRole: panel.getAttribute("role"),
    panelLabelledBy: panel.getAttribute("aria-labelledby"),
    stored,
  };
}"""


@pytest.fixture
def settings_page(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1#settings",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.body.dataset.view === 'settings' && "
            "document.querySelector('#panel-visibility-card .pv-cell') !== null",
            timeout=10_000,
        )
        yield page, errors
    finally:
        page.close()
        ctx.close()


def _focus_selected(page):
    page.focus("#panel-visibility-card .pv-tab[aria-selected='true']")
    return page.evaluate(_READ)


def _assert_one_selected(r, ctx):
    """Exactly one tab is selected, it is `ctx`, it holds focus and the only
    tab-sequence stop, and the rows below are that context's."""
    assert r["selected"] == [ctx], r["selected"]
    assert r["focused"] == ctx, r["focused"]
    stops = [t["ctx"] for t in r["tabs"] if t["tabIndex"] == 0]
    assert stops == [ctx], f"roving tabindex: tab stops {stops}"
    assert r["rowContexts"] == [ctx], r["rowContexts"]
    assert r["rowCount"] >= 10, r["rowCount"]
    assert r["stored"] == ctx, f"selection not persisted: {r['stored']}"


def test_premise_one_tab_stop_on_the_default_context(settings_page):
    page, errors = settings_page
    r = _focus_selected(page)
    # Anchors: the five tabs in TABS order, and no mode in ui_mock means the
    # live context is out-game, the LAST tab - so ArrowRight must wrap.
    assert [t["ctx"] for t in r["tabs"]] == _ORDER
    assert r["selected"] == ["out-game"] and r["focused"] == "out-game"
    assert [t["ctx"] for t in r["tabs"] if t["tabIndex"] == 0] == ["out-game"]
    assert not errors, errors[:3]


def test_arrow_right_walks_every_context_with_wrap(settings_page):
    page, errors = settings_page
    _focus_selected(page)
    # out-game -> (wrap) sr -> aram -> arena -> tft -> out-game: five
    # presses visit every context once and come back to the start.
    for ctx in _ORDER:
        page.keyboard.press("ArrowRight")
        r = page.evaluate(_READ)
        _assert_one_selected(r, ctx)
    assert not errors, errors[:3]


def test_arrow_left_walks_back_with_wrap(settings_page):
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("Home")
    _assert_one_selected(page.evaluate(_READ), "in-game-sr")
    # sr -> (wrap) out-game -> tft.
    for ctx in ("out-game", "in-game-tft"):
        page.keyboard.press("ArrowLeft")
        _assert_one_selected(page.evaluate(_READ), ctx)
    assert not errors, errors[:3]


def test_home_and_end_jump_to_the_ends(settings_page):
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("Home")
    _assert_one_selected(page.evaluate(_READ), "in-game-sr")
    page.keyboard.press("End")
    _assert_one_selected(page.evaluate(_READ), "out-game")
    assert not errors, errors[:3]


def test_tft_checkbox_is_reachable_and_toggles_from_the_keyboard(settings_page):
    """The end-to-end path the defect blocked: keyboard only, open the TFT
    context, Tab into its first checkbox, Space toggles it for in-game-tft."""
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("Home")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    _assert_one_selected(page.evaluate(_READ), "in-game-tft")
    page.keyboard.press("Tab")
    cb = page.evaluate(
        "() => { const a = document.activeElement;"
        " return a && a.matches('#panel-visibility-card input[type=checkbox]')"
        " ? {ctx: a.dataset.pvContext, panel: a.dataset.pvPanel, on: a.checked}"
        " : null; }"
    )
    assert cb is not None, "Tab from the selected tab must land in its tabpanel"
    assert cb["ctx"] == "in-game-tft", cb
    page.keyboard.press("Space")
    blob = page.evaluate("() => JSON.parse(localStorage.getItem('rc-panel-visibility') || 'null')")
    assert blob is not None, "toggle did not persist"
    assert blob.get("in-game-tft", {}).get(cb["panel"]) is (not cb["on"]), blob
    assert not errors, errors[:3]


def test_arrow_moved_tab_paints_the_focus_ring(settings_page):
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("ArrowRight")
    r = page.evaluate(_READ)
    # Focus must have MOVED (out-game wraps to sr); a ring on the tab that
    # already had focus is what the unfixed code painted.
    assert r["focused"] == "in-game-sr", r["focused"]
    assert r["focusVisible"] is True, r
    assert r["ring"] and r["ring"] != "none", r["ring"]
    assert not errors, errors[:3]


def test_tabpanel_semantics_follow_the_selection(settings_page):
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("Home")
    r = page.evaluate(_READ)
    assert r["panelRole"] == "tabpanel", r["panelRole"]
    assert r["panelId"], "the tabpanel needs an id for aria-controls"
    ids = [t["id"] for t in r["tabs"]]
    assert all(ids) and len(set(ids)) == len(ids), ids
    assert all(t["controls"] == r["panelId"] for t in r["tabs"]), r["tabs"]
    sr = next(t for t in r["tabs"] if t["ctx"] == "in-game-sr")
    assert r["panelLabelledBy"] == sr["id"]
    page.keyboard.press("End")
    r = page.evaluate(_READ)
    og = next(t for t in r["tabs"] if t["ctx"] == "out-game")
    assert r["panelLabelledBy"] == og["id"]
    assert not errors, errors[:3]


def test_up_and_down_arrows_are_not_taken_by_the_tablist(settings_page):
    """A horizontal tablist owns Left / Right only (APG); Up / Down keep the
    browser default and must not change the selection."""
    page, errors = settings_page
    _focus_selected(page)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowUp")
    r = page.evaluate(_READ)
    assert r["selected"] == ["out-game"], r["selected"]
    assert not errors, errors[:3]
