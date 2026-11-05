"""
tests/snapshot_panels/test_lobby_lane_trigger_names.py
RM-1556 (s144 uiux) - the Lobby lane-preference triggers
(#lv-lane-primary / #lv-lane-secondary) carry an accessible name that says
which slot they set and what it holds.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#lobby at
1920x920 before the fix. Each trigger is an icon-only <button>; its name
came from its content alone (data-tt is the app tooltip, not a name):
- a set lane named the button by the icon alt, the uppercase LANE_LABELS
  value ("MIDDLE", "BOTTOM"), with no word of which slot it sets;
- an unset slot was named "-" (the .lq-lane-empty dash);
- the needs-pick secondary (primary moved off Fill) was named by the
  header.css ::before glyph, a multiplication sign, and nothing else;
- the Fill-locked secondary (primary is Fill) showed the Fill icon with
  the img alt left at its HTML default "" or at the last lane it held, so
  the button had no name or a stale one.
Two triggers side by side were therefore indistinguishable to a screen
reader, and three of the four states read as noise or silence.

THE FIX: main.js _renderLanePref stamps aria-label from _laneTriggerName -
"<Primary|Secondary> lane: <Top|Jungle|Middle|Bottom|Support|Fill>",
"... lane: not set", "Secondary lane: not set, pick one" (needs-pick) and
"Secondary lane: Fill, follows the primary lane" (Fill-locked) - and the
Fill-locked icon alt is set to FILL. index.html carries the unset label as
the pre-render default.

The names are read through Playwright's get_by_role(name=, exact=True),
which runs the accessible-name computation, not by reading the attribute.
The one exception is the needs-pick state: it only exists between a pick
and the next lobby refresh, so it is built and read in one synchronous
evaluate, which reads the aria-label attribute (the name source for a
<button> that carries one) and checks the content text is empty.
/api/lcu-cmd is intercepted at the page, so nothing but the local mock is
reached.
"""
import json
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

_ROOT = Path(__file__).resolve().parents[2]
_INDEX = _ROOT / "web" / "index.html"
_FIXTURE = _ROOT / "web" / "data" / "ui_mock" / "lobby.json"


def _lobby_doc(first, second):
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    doc["lobby"]["local_member"]["position_preferences"] = {
        "first_preference": first,
        "second_preference": second,
    }
    return doc


def _open_lobby(pw_browser, mock_server, vp, prefs=None):
    """Open #lobby under ui_mock; `prefs` = (first, second) overrides the
    fixture's self-row position preferences."""
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.route("**/api/lcu-cmd", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    if prefs is not None:
        body = json.dumps(_lobby_doc(*prefs))
        page.route("**/data/ui_mock/lobby.json", lambda route: route.fulfill(
            status=200, content_type="application/json", body=body))
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-lane-primary", state="visible", timeout=10_000)
    want = (prefs or ("MIDDLE", "BOTTOM"))[0]
    page.wait_for_function(
        "(w) => document.getElementById('lv-lane-primary').dataset.pref === w",
        arg=want, timeout=10_000)
    return ctx, page, errors


def _named(page, name):
    """How many buttons carry exactly this computed accessible name."""
    return page.get_by_role("button", name=name, exact=True).count()


def _names(page):
    """The computed names of both triggers, read through the a11y tree."""
    out = {}
    for tid in ("lv-lane-primary", "lv-lane-secondary"):
        loc = page.locator("#" + tid)
        snap = loc.aria_snapshot()
        m = re.search(r'button "([^"]*)"', snap)
        out[tid] = m.group(1) if m else ""
    return out


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
def test_set_lanes_name_their_slot_and_lane(mock_server, pw_browser, vp):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, vp)
    try:
        assert _named(page, "Primary lane: Middle") == 1, _names(page)
        assert _named(page, "Secondary lane: Bottom") == 1, _names(page)
        # Positive control: the old content-derived names are gone.
        assert _named(page, "MIDDLE") == 0, _names(page)
        assert _named(page, "BOTTOM") == 0, _names(page)
        assert not errors, errors
    finally:
        ctx.close()


def test_unset_slots_say_not_set(mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, VIEWPORTS[0],
                                    prefs=("UNSELECTED", "UNSELECTED"))
    try:
        assert _named(page, "Primary lane: not set") == 1, _names(page)
        assert _named(page, "Secondary lane: not set") == 1, _names(page)
        assert _named(page, "-") == 0, _names(page)
        # The visible dash is unchanged: only the name moved.
        dash = page.evaluate(
            "() => document.querySelector('#lv-lane-primary .lq-lane-empty')"
            ".textContent")
        assert dash == "-", dash
        assert not errors, errors
    finally:
        ctx.close()


def test_fill_locked_secondary_names_why(mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, VIEWPORTS[0],
                                    prefs=("FILL", "FILL"))
    try:
        st = page.evaluate("""() => {
          const s = document.getElementById('lv-lane-secondary');
          const img = s.querySelector('.lq-lane-icon');
          return {locked: s.classList.contains('is-fill-locked'),
                  alt: img.getAttribute('alt'), hidden: img.hidden};
        }""")
        assert st["locked"] and not st["hidden"], st
        assert _named(page, "Primary lane: Fill") == 1, _names(page)
        assert _named(
            page, "Secondary lane: Fill, follows the primary lane") == 1, _names(page)
        # The shown Fill icon is not left with an empty or stale alt.
        assert st["alt"] == "FILL", st
        assert not errors, errors
    finally:
        ctx.close()


def test_needs_pick_secondary_says_pick_one(mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server, VIEWPORTS[0],
                                    prefs=("FILL", "FILL"))
    try:
        # Primary FILL -> MIDDLE leaves the secondary needing a pick. Built
        # and read in one task, before the next lobby refresh resets it.
        st = page.evaluate("""() => {
          const pri = document.getElementById('lv-lane-primary');
          const sec = document.getElementById('lv-lane-secondary');
          pri.click();
          const cell = document.querySelector(
            '#lv-lane-popup .lobby-lane-popup-cell[data-pref="MIDDLE"]');
          cell.click();
          return {pick: sec.classList.contains('needs-pick'),
                  pri: pri.getAttribute('aria-label'),
                  sec: sec.getAttribute('aria-label'),
                  secText: sec.textContent.trim()};
        }""")
        assert st["pick"], st
        assert st["pri"] == "Primary lane: Middle", st
        assert st["sec"] == "Secondary lane: not set, pick one", st
        # Without the label the content is empty (the glyph is CSS ::before).
        assert st["secText"] == "", st
        assert not errors, errors
    finally:
        ctx.close()


def test_index_html_carries_the_unset_default():
    html = _INDEX.read_text(encoding="utf-8")
    for tid, slot in (("lv-lane-primary", "Primary"),
                      ("lv-lane-secondary", "Secondary")):
        m = re.search(r'<button[^>]*id="' + tid + r'"[^>]*>', html, re.S)
        assert m, tid
        assert f'aria-label="{slot} lane: not set"' in m.group(0), m.group(0)
