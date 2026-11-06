"""
tests/snapshot_panels/test_lobby_lane_trigger_states.py
RM-1759 (s144 uiux) - two Lobby lane-trigger states that were visual
only now reach the accessibility tree.

THE DEFECTS. MEASURED in headless Chromium under /?ui_mock=1#lobby at
1920x920 before the fix (follow-ups filed by RM-1556,
test_lobby_lane_trigger_names.py):
1. FILL-LOCKED SECONDARY. When the primary is Fill, the secondary shows
   the Fill icon and a press opens nothing (main.js secondary click
   handler returns when _LV.prefPrimary is FILL), but the button kept
   aria-haspopup="menu" and no disabled state, so it was announced as a
   working menu button that silently does nothing; its hover also drew
   the --info "clickable" border.
2. PARTY LANE CONFLICT. When the operator's primary equals another party
   member's primary, _renderPartyMembers adds .is-conflict to
   #lv-lane-primary (red border + a CSS ::after "CONFLICT" overlay). The
   name stayed "Primary lane: Middle", so the conflict existed only in
   pixels.

THE FIX: main.js _renderLanePref stamps aria-disabled="true" on the
Fill-locked secondary (removed in every other state; native disabled is
not used, so the button keeps keyboard focus); _laneTriggerName appends
", conflicts with a party member" to the primary while _LV.laneConflict
is set, and _renderPartyMembers sets that flag and re-stamps the name
when it computes the conflict. header.css keeps the Fill-locked look the
s162 design gave it (opacity 1, not the 0.55 the [aria-disabled] hold
rule would apply).
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_lobby_lane_trigger_names import _named, _names

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "web" / "data" / "ui_mock" / "lobby.json"

_CONFLICT_NAME = "Primary lane: Middle, conflicts with a party member"


def _doc(first, second, mate_first=None):
    """The ui_mock lobby fixture with the self-row prefs overridden and,
    when `mate_first` is given, the first non-self member's primary."""
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    doc["lobby"]["local_member"]["position_preferences"] = {
        "first_preference": first,
        "second_preference": second,
    }
    if mate_first is not None:
        mate = next(m for m in doc["lobby"]["members"] if not m.get("is_self"))
        mate["position_preferences"]["first"] = mate_first
    return doc


def _open(pw_browser, mock_server, vp, doc):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.route("**/api/lcu-cmd", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    body = json.dumps(doc)
    page.route("**/data/ui_mock/lobby.json", lambda route: route.fulfill(
        status=200, content_type="application/json", body=body))
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_selector("#lv-lane-primary", state="visible", timeout=10_000)
    want = doc["lobby"]["local_member"]["position_preferences"]["first_preference"]
    page.wait_for_function(
        "(w) => document.getElementById('lv-lane-primary').dataset.pref === w",
        arg=want, timeout=10_000)
    # The party list (and with it the conflict pass) has rendered.
    page.wait_for_selector("#lv-members-list li", state="attached",
                           timeout=10_000)
    return ctx, page, errors


def _tick_and_log_labels(page):
    """Force one lobby render tick (#home then back to #lobby) and return
    every aria-label value #lv-lane-primary held across it: the value
    before, each intermediate, and the final one."""
    page.evaluate("""() => {
      const b = document.getElementById('lv-lane-primary');
      window.__u149 = [];
      window.__u149obs = new MutationObserver((recs) => {
        for (const r of recs) window.__u149.push(r.oldValue);
      });
      window.__u149obs.observe(b, {attributes: true,
        attributeFilter: ['aria-label'], attributeOldValue: true});
      location.hash = '#home';
    }""")
    page.wait_for_function("() => document.body.dataset.view === 'home'",
                           timeout=10_000)
    page.evaluate("() => { location.hash = '#lobby'; }")
    page.wait_for_function("() => document.body.dataset.view === 'lobby'",
                           timeout=10_000)
    page.wait_for_function("() => window.__u149.length >= 2", timeout=10_000)
    return page.evaluate("""() => {
      window.__u149obs.disconnect();
      return window.__u149.concat([document.getElementById(
        'lv-lane-primary').getAttribute('aria-label')]);
    }""")


def _state(page, tid):
    return page.evaluate("""(tid) => {
      const b = document.getElementById(tid);
      const cs = getComputedStyle(b);
      return {ariaDisabled: b.getAttribute('aria-disabled'),
              disabled: b.disabled,
              locked: b.classList.contains('is-fill-locked'),
              conflict: b.classList.contains('is-conflict'),
              opacity: cs.opacity,
              label: b.getAttribute('aria-label')};
    }""", tid)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
def test_fill_locked_secondary_is_announced_unavailable(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp, _doc("FILL", "FILL"))
    try:
        st = _state(page, "lv-lane-secondary")
        assert st["locked"], st
        assert st["ariaDisabled"] == "true", st
        # Not native disabled: the button stays in the tab order.
        assert st["disabled"] is False, st
        snap = page.locator("#lv-lane-secondary").aria_snapshot()
        assert "[disabled]" in snap, snap
        # The s162 Fill-locked look is kept (no 0.55 hold dim).
        assert st["opacity"] == "1", st
        # A keyboard press still opens nothing.
        page.locator("#lv-lane-secondary").focus()
        page.keyboard.press("Enter")
        hidden = page.evaluate(
            "() => document.getElementById('lv-lane-popup')"
            ".classList.contains('hidden')")
        assert hidden, "Fill-locked secondary opened the lane popup"
        # The primary is never aria-disabled.
        assert _state(page, "lv-lane-primary")["ariaDisabled"] is None
        assert not errors, errors
    finally:
        ctx.close()


def test_fill_locked_secondary_hover_draws_no_clickable_border(
        mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("FILL", "FILL"))
    try:
        def border(tid):
            return page.evaluate(
                "(t) => getComputedStyle(document.getElementById(t))"
                ".borderTopColor", tid)
        # The .lq-btn border-color transition (0.12s) would let a read
        # land mid-fade; with it off, a hover border is there at once.
        page.add_style_tag(content=".lq-btn { transition: none !important; }")
        page.mouse.move(0, 0)
        rest_sec, rest_pri = border("lv-lane-secondary"), border("lv-lane-primary")
        page.hover("#lv-lane-secondary")
        assert border("lv-lane-secondary") == rest_sec, (rest_sec,)
        # Positive control: the working primary still lights on hover.
        page.hover("#lv-lane-primary")
        assert border("lv-lane-primary") != rest_pri, (rest_pri,)
        assert not errors, errors
    finally:
        ctx.close()


def test_empty_party_clears_a_stale_conflict(mock_server, pw_browser):
    """_renderPartyMembers returned before its conflict pass on an empty
    member list, so a conflict from the last party stayed on the button."""
    doc = _doc("MIDDLE", "BOTTOM")
    doc["lobby"]["members"] = []
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0], doc)
    try:
        # Seed the stale class a previous party would have left behind.
        page.evaluate("() => document.getElementById('lv-lane-primary')"
                      ".classList.add('is-conflict')")
        _tick_and_log_labels(page)
        st = _state(page, "lv-lane-primary")
        assert not st["conflict"], st
        assert st["label"] == "Primary lane: Middle", st
        assert not errors, errors
    finally:
        ctx.close()


def test_no_lcu_fill_locked_secondary_still_dims(mock_server, pw_browser):
    """The keep-the-look override must not undo the no-LCU disabled dim:
    with no lobby _renderLanePref sets .is-disabled + native disabled on a
    button that can still be Fill-locked from the last lobby."""
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("FILL", "FILL"))
    try:
        op = page.evaluate("""() => {
          const s = document.getElementById('lv-lane-secondary');
          s.classList.add('is-disabled');
          s.disabled = true;
          return getComputedStyle(s).opacity;
        }""")
        assert op == "0.55", op
        assert not errors, errors
    finally:
        ctx.close()


def test_secondary_is_not_aria_disabled_when_it_works(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("MIDDLE", "BOTTOM"))
    try:
        for tid in ("lv-lane-primary", "lv-lane-secondary"):
            st = _state(page, tid)
            assert st["ariaDisabled"] is None, (tid, st)
            snap = page.locator("#" + tid).aria_snapshot()
            assert "[disabled]" not in snap, snap
        assert not errors, errors
    finally:
        ctx.close()


def test_leaving_fill_clears_aria_disabled(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("FILL", "FILL"))
    try:
        # Primary FILL -> MIDDLE: the secondary needs a pick and works again.
        st = page.evaluate("""() => {
          document.getElementById('lv-lane-primary').click();
          document.querySelector(
            '#lv-lane-popup .lobby-lane-popup-cell[data-pref="MIDDLE"]').click();
          const s = document.getElementById('lv-lane-secondary');
          return {pick: s.classList.contains('needs-pick'),
                  ariaDisabled: s.getAttribute('aria-disabled')};
        }""")
        assert st["pick"], st
        assert st["ariaDisabled"] is None, st
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
def test_party_conflict_is_in_the_primary_name(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp,
                              _doc("MIDDLE", "BOTTOM", mate_first="MIDDLE"))
    try:
        page.wait_for_function(
            "() => document.getElementById('lv-lane-primary')"
            ".classList.contains('is-conflict')", timeout=10_000)
        assert _named(page, _CONFLICT_NAME) == 1, _names(page)
        # The secondary is not part of the conflict.
        assert _named(page, "Secondary lane: Bottom") == 1, _names(page)
        # A forced second lobby tick (under ui_mock no timer tick runs while
        # the SSE stub is fresh, so the view is switched away and back).
        # Each tick writes the name twice, lane render then party render;
        # every value written must carry the suffix, so a _renderLanePref
        # that ignored _LV.laneConflict would show up as an intermediate.
        seen = _tick_and_log_labels(page)
        assert len(seen) >= 3, seen
        assert set(seen) == {_CONFLICT_NAME}, seen
        assert _named(page, _CONFLICT_NAME) == 1, _names(page)
        assert not errors, errors
    finally:
        ctx.close()


def test_no_conflict_keeps_the_plain_name(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("MIDDLE", "BOTTOM", mate_first="JUNGLE"))
    try:
        st = _state(page, "lv-lane-primary")
        assert not st["conflict"], st
        assert st["label"] == "Primary lane: Middle", st
        assert not errors, errors
    finally:
        ctx.close()
