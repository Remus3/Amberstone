"""
tests/snapshot_panels/test_user_builds_rune_tabs_keyboard.py
RM-1085 + RM-1086 (s144 uiux): the User Builds rune page builder's two
role="tablist" bars, #ub-rp-tabs (primary tree) and #ub-rp-sec-trees
(secondary tree), carry role="tab" + aria-selected since RM-1084, but
measured in headless Chromium under /?ui_mock=1#user-builds:
  - no roving tabindex: every tree tab was its own Tab stop;
  - no arrow keys: ArrowLeft / ArrowRight / Home / End did nothing, though
    the role promises them;
  - every pick rebuilds the whole builder with innerHTML (main.js
    _ubRpRenderAll), so a keyboard pick of a tree OR a rune threw focus to
    <body> (the repaint-destroys-focus trap, lane doc section 6 trap 2);
  - no tab-to-panel link: no aria-controls, and the rows containers had no
    role="tabpanel".

Fix: WAI-ARIA APG tabs with MANUAL activation - arrows move focus and leave
the selection alone, Enter / Space pick. Manual, not automatic, because a
tree pick is destructive: it clears the keystone and every minor rune of
that pane, so arrowing across the bar must not pick each tree it passes.
The secondary bar skips its disabled copy of the primary tree. Focus is
carried across the rebuild by a stable key (container id plus data-tree /
data-rune / data-row), and only when focus was inside the builder, so the
restore never steals focus.

Drive path as in test_user_builds_rune_tabs.py: Tristana, + Add build, and
/api/dictionary/runes served the TRACKED DDragon dump data/meta/
ddragon_runes.json (its tree order: Domination, Inspiration, Precision,
Resolve, Sorcery).
"""
import datetime
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORT = {"width": 1920, "height": 920}
_RUNES = Path(__file__).resolve().parents[2] / "data" / "meta" / "ddragon_runes.json"
_ORDER = [t["key"] for t in json.loads(_RUNES.read_text(encoding="utf-8"))]
_PRI = "#ub-rp-tabs"
_SEC = "#ub-rp-sec-trees"

_STATE = """() => {
  const bar = (sel) => Array.from(document.querySelectorAll(sel + ' > button'))
    .map((b) => ({
      tree: b.dataset.tree, id: b.id, tabIndex: b.tabIndex,
      selected: b.getAttribute('aria-selected'),
      controls: b.getAttribute('aria-controls'), disabled: b.disabled,
    }));
  const act = document.activeElement;
  let focused = null;
  if (act && act !== document.body) {
    const host = act.parentElement && act.parentElement.id
      ? act.parentElement.id
      : (act.closest('[id]') || {}).id || null;
    focused = {
      id: act.id || null, host,
      tree: act.dataset ? (act.dataset.tree || null) : null,
      rune: act.dataset ? (act.dataset.rune || null) : null,
      visible: act.matches(':focus-visible'),
    };
  }
  const panel = (id) => {
    const el = document.getElementById(id);
    return {role: el.getAttribute('role'), labelledBy: el.getAttribute('aria-labelledby')};
  };
  const val = (id) => (document.getElementById(id) || {}).value || '';
  return {
    primary: bar('#ub-rp-tabs'), secondary: bar('#ub-rp-sec-trees'), focused,
    panels: {primary: panel('ub-rp-primary-rows'), secondary: panel('ub-rp-secondary-rows')},
    fields: {keystone: val('ub-f-keystone'), primary: val('ub-f-primary'),
             secondary: val('ub-f-secondary')},
  };
}"""


def _tristana_page(mock_server, pw_browser):
    """The User Builds view with Tristana picked, the form not yet open."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    body = _RUNES.read_bytes()
    page.route(
        "**/api/dictionary/runes",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body,
        ),
    )
    page.goto(
        mock_server.url + "/?ui_mock=1#user-builds",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    page.fill("#ub-champion-input", "Tristana")
    page.dispatch_event("#ub-champion-input", "change")
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    page._rc_errors = errors
    return ctx, page


@pytest.fixture
def form(mock_server, pw_browser):
    ctx, page = _tristana_page(mock_server, pw_browser)
    try:
        page.click("#ub-add-btn")
        page.wait_for_function(
            f"document.querySelectorAll('{_PRI} > button').length === {len(_ORDER)}",
            timeout=10_000,
        )
        yield page
    finally:
        page.close()
        ctx.close()


def _state(page):
    return page.evaluate(_STATE)


def _pick(page, bar, tree):
    page.click(f"{bar} > button[data-tree={tree!r}]")
    want = "primary" if bar == _PRI else "secondary"
    page.wait_for_function(
        f"document.getElementById('ub-f-{want}').value === {tree!r}", timeout=5_000,
    )


def _kb_focus(page, selector):
    # Keyboard modality first, so a programmatic focus() matches
    # :focus-visible the way a Tab would.
    page.keyboard.press("Shift")
    page.focus(selector)


def _tab_indexes(tabs):
    return {t["tree"]: t["tabIndex"] for t in tabs}


def _focused_tree(page, bar):
    f = _state(page)["focused"]
    assert f is not None, "focus fell to <body>"
    assert f["host"] == bar.lstrip("#"), f
    return f["tree"]


def test_premise_tree_order_and_disabled_copy(form):
    _pick(form, _PRI, "Precision")
    s = _state(form)
    assert not form._rc_errors, form._rc_errors[:3]
    assert _ORDER == ["Domination", "Inspiration", "Precision", "Resolve", "Sorcery"]
    assert [t["tree"] for t in s["primary"]] == _ORDER
    assert [t["tree"] for t in s["secondary"]] == _ORDER
    assert [t["tree"] for t in s["secondary"] if t["disabled"]] == ["Precision"]


def test_roving_tabindex_with_nothing_selected(form):
    s = _state(form)
    first = {t: (0 if t == _ORDER[0] else -1) for t in _ORDER}
    assert _tab_indexes(s["primary"]) == first, s["primary"]
    assert _tab_indexes(s["secondary"]) == first, s["secondary"]


def test_roving_tabindex_follows_the_selection(form):
    _pick(form, _PRI, "Domination")
    s = _state(form)
    # No secondary picked: the first ENABLED tab is the bar's Tab stop.
    assert _tab_indexes(s["secondary"]) == {
        t: (0 if t == "Inspiration" else -1) for t in _ORDER
    }, s["secondary"]
    _pick(form, _PRI, "Precision")
    _pick(form, _SEC, "Sorcery")
    s = _state(form)
    assert _tab_indexes(s["primary"]) == {
        t: (0 if t == "Precision" else -1) for t in _ORDER
    }, s["primary"]
    assert _tab_indexes(s["secondary"]) == {
        t: (0 if t == "Sorcery" else -1) for t in _ORDER
    }, s["secondary"]


def test_primary_arrows_move_focus_and_leave_the_selection(form):
    _pick(form, _PRI, "Precision")
    form.click("#ub-rp-primary-rows button[data-rune='Conqueror']")
    form.wait_for_function(
        "document.getElementById('ub-f-keystone').value === 'Conqueror'", timeout=5_000,
    )
    _kb_focus(form, f"{_PRI} > button[data-tree='Precision']")
    seen = []
    for key in ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "Home", "End"]:
        form.keyboard.press(key)
        seen.append(_focused_tree(form, _PRI))
    assert seen == ["Resolve", "Sorcery", "Domination", "Sorcery", "Domination", "Sorcery"]
    s = _state(form)
    # Manual activation: nothing was picked, the keystone survives.
    assert s["fields"]["primary"] == "Precision", s["fields"]
    assert s["fields"]["keystone"] == "Conqueror", s["fields"]
    assert [t["tree"] for t in s["primary"] if t["selected"] == "true"] == ["Precision"]
    assert s["focused"]["visible"], s["focused"]


def test_secondary_arrows_skip_the_disabled_primary_copy(form):
    _pick(form, _PRI, "Precision")
    _kb_focus(form, f"{_SEC} > button[data-tree='Inspiration']")
    seen = []
    for key in ["ArrowRight", "ArrowLeft", "Home", "End", "ArrowRight"]:
        form.keyboard.press(key)
        seen.append(_focused_tree(form, _SEC))
    assert seen == ["Resolve", "Inspiration", "Domination", "Sorcery", "Domination"]
    assert _state(form)["fields"]["secondary"] == "", "an arrow picked a tree"


def test_enter_and_space_pick_and_focus_survives_the_rebuild(form):
    _pick(form, _PRI, "Precision")
    _kb_focus(form, f"{_PRI} > button[data-tree='Precision']")
    form.keyboard.press("ArrowRight")
    form.keyboard.press("Enter")
    s = _state(form)
    assert s["fields"]["primary"] == "Resolve", s["fields"]
    assert s["focused"] and s["focused"]["host"] == "ub-rp-tabs", s["focused"]
    assert s["focused"]["tree"] == "Resolve" and s["focused"]["visible"], s["focused"]
    assert _tab_indexes(s["primary"])["Resolve"] == 0, s["primary"]

    _kb_focus(form, f"{_SEC} > button[data-tree='Sorcery']")
    form.keyboard.press("Space")
    s = _state(form)
    assert s["fields"]["secondary"] == "Sorcery", s["fields"]
    assert s["focused"] and s["focused"]["host"] == "ub-rp-sec-trees", s["focused"]
    assert s["focused"]["tree"] == "Sorcery", s["focused"]


def test_rune_picks_from_the_keyboard_keep_focus(form):
    _pick(form, _PRI, "Precision")
    _kb_focus(form, "#ub-rp-primary-rows button[data-rune='Conqueror']")
    form.keyboard.press("Enter")
    s = _state(form)
    assert s["fields"]["keystone"] == "Conqueror", s["fields"]
    assert s["focused"] and s["focused"]["rune"] == "Conqueror", s["focused"]
    # A minor in row 1, same rebuild path.
    _kb_focus(form, "#ub-rp-primary-rows button[data-row='1']")
    want = form.evaluate(
        "document.activeElement.dataset.rune"
    )
    form.keyboard.press("Space")
    s = _state(form)
    assert s["focused"] and s["focused"]["rune"] == want, (want, s["focused"])


def test_modified_and_vertical_keys_are_left_alone(form):
    _pick(form, _PRI, "Precision")
    _kb_focus(form, f"{_PRI} > button[data-tree='Precision']")
    for key in ["Control+ArrowRight", "ArrowDown", "ArrowUp"]:
        form.keyboard.press(key)
        assert _focused_tree(form, _PRI) == "Precision", key


def test_tabs_name_the_rows_panel_they_drive(form):
    s = _state(form)
    assert s["panels"]["primary"] == {"role": "tabpanel", "labelledBy": None}, s["panels"]
    assert s["panels"]["secondary"] == {"role": "tabpanel", "labelledBy": None}, s["panels"]
    _pick(form, _PRI, "Precision")
    _pick(form, _SEC, "Sorcery")
    s = _state(form)
    ids = [t["id"] for t in s["primary"] + s["secondary"]]
    assert len(set(ids)) == len(ids) and all(ids), ids
    for t in s["primary"]:
        assert t["controls"] == "ub-rp-primary-rows", t
    for t in s["secondary"]:
        assert t["controls"] == "ub-rp-secondary-rows", t
    by_tree = {t["tree"]: t["id"] for t in s["primary"]}
    sec_by_tree = {t["tree"]: t["id"] for t in s["secondary"]}
    assert s["panels"]["primary"]["labelledBy"] == by_tree["Precision"], s["panels"]
    assert s["panels"]["secondary"]["labelledBy"] == sec_by_tree["Sorcery"], s["panels"]
    n = form.evaluate(
        "(ids) => ids.filter((i) => document.querySelectorAll('#' + i).length === 1).length",
        ids,
    )
    assert n == len(ids), "a tab id is not unique in the document"


def test_a_rebuild_never_steals_focus_from_outside_the_builder(form):
    _pick(form, _PRI, "Precision")
    form.focus("#ub-f-label")
    # A pick that does not come with a focus move (element.click()).
    form.evaluate(
        "document.querySelector(\"#ub-rp-tabs > button[data-tree='Resolve']\").click()"
    )
    s = _state(form)
    assert s["fields"]["primary"] == "Resolve", s["fields"]
    assert s["focused"] and s["focused"]["id"] == "ub-f-label", s["focused"]


def test_opening_the_form_leaves_no_deferred_focus_steal(mock_server, pw_browser):
    """C6 (s154): _userBuildsOpenForm focused #ub-f-label from a 50 ms
    setTimeout. The rune trees often arrived inside those 50 ms, so this
    module (and a fast keyboard user) had already moved focus into a tab
    bar when the stale timer threw it to the label: the module failed 7 of
    10 solo runs, a different test each time. Page time is paused here, so
    no timer fires on its own; run_for() then fires every timer due in the
    next second, deterministically. The fast-typing contract stays: the
    label holds focus the moment the form opens."""
    ctx, page = _tristana_page(mock_server, pw_browser)
    try:
        page.clock.install()
        page.clock.pause_at(datetime.datetime.now() + datetime.timedelta(minutes=1))
        page.click("#ub-add-btn")
        # Utility-world wait: the paused clock also holds the main world's rAF.
        page.wait_for_selector(f"{_PRI} > button:nth-child({len(_ORDER)})", timeout=10_000)
        s = _state(page)
        assert s["focused"] and s["focused"]["id"] == "ub-f-label", s["focused"]
        _kb_focus(page, f"{_PRI} > button[data-tree='Domination']")
        page.clock.run_for(1_000)
        assert _focused_tree(page, _PRI) == "Domination"
        assert not page._rc_errors, page._rc_errors[:3]
    finally:
        page.close()
        ctx.close()
