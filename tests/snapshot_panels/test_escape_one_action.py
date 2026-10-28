"""
tests/snapshot_panels/test_escape_one_action.py
RM-1067 (s144 uiux): one Escape press does ONE thing.

Measured in headless Chromium before the fix (web/js/main.js), an Escape
pressed to close a transient layer was not consumed, so the next
document-level Escape handler acted on the same press:
- the view menu (#view-menu, _viewWireOnce) closed AND the Replay recording
  player released focus (web/js/panels/review_player.js _onKeydown moved
  focus from #view-trigger to #replay-video-section), as the RM-1062
  verifier reported;
- the view menu, the task modal (#task-modal) or the Home Find Match picker
  (#home-find-match-picker) closed AND the general Escape chain (the
  keyboard-shortcut handler: modal -> reply toast -> zen) exited zen mode,
  so an operator in zen who opened the menu and backed out of it lost zen.

The fix: each of the three layers consumes the Escape that closes it
(preventDefault, in the capture phase, so it runs before every bubble-phase
document handler whatever order they were added in), and the general Escape
chain, like the player (review_player_model.js hotkeyAction), stands down on
a press already consumed. A second Escape still reaches the next handler
(positive controls below), and an Escape with no layer open is untouched.

RM-1068 (s144 uiux) closes the same double action on two more layers
outside main.js: the Right Now cross-session digest popover
(#digest-popout, web/js/panels/right_now.js bindDigestIcon) and the
draft-elo contributions overlay (.draft-elo-contributions,
web/js/panels/draft_elo.js, the hover-only overlay Escape dismisses). Each
closed AND exited zen on one press; each now consumes the press it acts on,
and only that press.

The Replay lane stays hidden under ?ui_mock=1, so the player tests reveal
#replay-video-section the way a servable sidecar would (the helper from
test_replay_space_single_action.py).
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page
from tests.snapshot_panels.test_replay_space_single_action import _open_loaded

_STATE = """
() => {
  const vm = document.getElementById('view-menu');
  const tm = document.getElementById('task-modal');
  const fp = document.getElementById('home-find-match-picker');
  const ae = document.activeElement;
  return {
    menuOpen: !!vm && !vm.classList.contains('hidden'),
    expanded: document.getElementById('view-trigger').getAttribute('aria-expanded'),
    modalOpen: !!tm && !tm.classList.contains('hidden'),
    pickerOpen: !!fp && !fp.classList.contains('hidden'),
    zen: document.body.dataset.zen || '',
    focus: ae ? (ae.id || ae.tagName) : null,
  };
}
"""


def _open_view(pw_browser, mock_server, vp, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + "/?ui_mock=1#" + view,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"() => document.body.dataset.view === '{view}'", timeout=10_000
    )
    return ctx, page, errors


def _zen_on(page):
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("z")
    assert page.evaluate(_STATE)["zen"] == "1", "Z did not turn zen on"


def _open_view_menu(page):
    page.click("#view-trigger")
    st = page.evaluate(_STATE)
    assert st["menuOpen"] and st["expanded"] == "true", st
    return st


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_view_menu_without_moving_replay_focus(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_loaded(pw_browser, mock_server, vp)
    try:
        st = _open_view_menu(page)
        assert st["focus"] == "view-trigger", st
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["menuOpen"] and st["expanded"] == "false", st
        assert st["focus"] == "view-trigger", (
            f"the Escape that closed the view menu also ran the player's "
            f"release-focus: {st}"
        )
        # Positive control: the player key is live, so the NEXT Escape
        # releases focus to the lane.
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["focus"] == "replay-video-section", st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_view_menu_and_keeps_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        _open_view_menu(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["menuOpen"], st
        assert st["zen"] == "1", f"closing the view menu also exited zen: {st}"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["zen"] == "", f"a second Escape no longer exits zen: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_task_modal_and_keeps_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        # openTaskModal (main.js) shows the modal by dropping .hidden; its
        # opener is a task-id chip in a coach card the fixtures do not carry.
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
        assert page.evaluate(_STATE)["modalOpen"]
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["modalOpen"], st
        assert st["zen"] == "1", f"closing the task modal also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == ""
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_find_match_picker_and_keeps_zen(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        _zen_on(page)
        page.click("#home-hero-cta")
        assert page.evaluate(_STATE)["pickerOpen"]
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["pickerOpen"], st
        assert st["zen"] == "1", f"closing the Find Match picker also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == ""
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_with_no_layer_open_still_exits_zen(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert st["zen"] == "", st
        assert not (st["menuOpen"] or st["modalOpen"] or st["pickerOpen"]), st
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# RM-1068 ----------------------------------------------------------------

_DIGEST_OPEN = (
    "() => !document.getElementById('digest-popout').classList.contains('hidden')"
)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_closes_the_digest_popover_and_keeps_zen(
        mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        # #digest-icon stays [hidden] until a digest payload arrives (the
        # fixtures carry none); its click handler is the real opener.
        page.evaluate("() => document.getElementById('digest-icon').click()")
        assert page.evaluate(_DIGEST_OPEN), "the digest popover did not open"
        page.keyboard.press("Escape")
        assert not page.evaluate(_DIGEST_OPEN), "Escape did not close the popover"
        st = page.evaluate(_STATE)
        assert st["zen"] == "1", f"closing the digest popover also exited zen: {st}"
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == "", "a second Escape no longer exits zen"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_CONTRIB_SHOWN = """
() => {
  const o = document.querySelector('#am-draft-elo .draft-elo-contributions');
  return !!o && getComputedStyle(o).display !== 'none';
}
"""


def test_escape_dismisses_the_draft_elo_overlay_and_keeps_zen(
        mock_server, pw_browser):
    from tests.snapshot_panels.conftest import DRAFT_ELO_GOOD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_GOOD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )
            _zen_on(page)
            page.hover("#am-draft-elo")
            assert page.evaluate(_CONTRIB_SHOWN), "hover did not show the overlay"
            page.keyboard.press("Escape")
            assert not page.evaluate(_CONTRIB_SHOWN), "Escape did not dismiss it"
            st = page.evaluate(_STATE)
            assert st["zen"] == "1", (
                f"dismissing the draft-elo overlay also exited zen: {st}"
            )
            # Nothing left to dismiss (still hovered, inline display:none),
            # so the next Escape reaches the zen exit.
            page.keyboard.press("Escape")
            assert page.evaluate(_STATE)["zen"] == "", (
                "a second Escape no longer exits zen"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


# RM-1069 ----------------------------------------------------------------
# Two layers open at once: the cross-session digest popover (#digest-popout,
# z-index 9500, web/css/panels/header.css) over the task modal (#task-modal,
# z-index 200, web/css/panels/input_activity.css), with zen on underneath.
# Every layer listens on document in the capture phase; before the fix none
# of them checked e.defaultPrevented, so one Escape closed BOTH layers (and
# only zen survived, because the bubble-phase chain does check it). Each
# layer now stands down on a press another layer consumed, so the press goes
# to the first registered listener: right_now.js is imported by main.js and
# binds at module evaluation, before main.js wires the task modal. One press
# peels one layer. RM-1070 then moved every layer onto one dispatcher that
# picks the topmost open layer (web/js/lib/escape_layers.js), so the order is
# paint order, not registration order; for THIS pair the two agree, and the
# RM-1070 tests at the end of the file pin a pair where they disagree.

_STACK = """
() => ({
  digest: !document.getElementById('digest-popout').classList.contains('hidden'),
  modal: !document.getElementById('task-modal').classList.contains('hidden'),
  zen: document.body.dataset.zen || '',
})
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_escape_peels_stacked_layers_one_per_press(mock_server, pw_browser, vp):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
        page.evaluate("() => document.getElementById('digest-icon').click()")
        st = page.evaluate(_STACK)
        assert st == {"digest": True, "modal": True, "zen": "1"}, st
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st == {"digest": False, "modal": True, "zen": "1"}, (
            f"the first Escape did not close only the topmost layer: {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st == {"digest": False, "modal": False, "zen": "1"}, (
            f"the second Escape did not close only the task modal: {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK)
        assert st["zen"] == "", f"the third Escape no longer exits zen: {st}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# A press consumed UPSTREAM is not taken again, by any layer. The stack test
# above can only reach the listeners registered after another layer's, so
# this one consumes the Escape in a window capture listener (window runs
# before every document listener) and asserts each layer stays open. The
# first-registered layer (the digest popover) is pinned only here.

_CONSUME_UPSTREAM = """
() => window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') e.preventDefault();
}, true)
"""

_LAYER_OPEN = {
    "task-modal": "() => !document.getElementById('task-modal').classList.contains('hidden')",
    "view-menu": "() => !document.getElementById('view-menu').classList.contains('hidden')",
    "find-match-picker": (
        "() => !document.getElementById('home-find-match-picker')"
        ".classList.contains('hidden')"
    ),
    "digest-popover": _DIGEST_OPEN,
}


def _open_layer(page, layer):
    if layer == "task-modal":
        page.evaluate(
            "() => document.getElementById('task-modal').classList.remove('hidden')"
        )
    elif layer == "view-menu":
        page.click("#view-trigger")
    elif layer == "find-match-picker":
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        page.click("#home-hero-cta")
    else:
        page.evaluate("() => document.getElementById('digest-icon').click()")


@pytest.mark.parametrize("layer", sorted(_LAYER_OPEN))
def test_a_press_consumed_upstream_leaves_the_layer_open(
        mock_server, pw_browser, layer):
    ctx, page, errors = _open_view(pw_browser, mock_server, VIEWPORTS[0], "home")
    try:
        _open_layer(page, layer)
        assert page.evaluate(_LAYER_OPEN[layer]), f"{layer} did not open"
        page.evaluate(_CONSUME_UPSTREAM)
        page.keyboard.press("Escape")
        assert page.evaluate(_LAYER_OPEN[layer]), (
            f"{layer} closed on an Escape another listener had consumed"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_press_consumed_upstream_leaves_the_draft_elo_overlay_shown(
        mock_server, pw_browser):
    from tests.snapshot_panels.conftest import DRAFT_ELO_GOOD_BAND
    from tests.snapshot_panels.test_active_match_view import _open_active_match

    mock_server.set_draft_elo(DRAFT_ELO_GOOD_BAND)
    try:
        ctx, page, errors = _open_active_match(pw_browser, mock_server, "sr")
        try:
            page.wait_for_function(
                "document.querySelector('#am-draft-elo') && "
                "document.querySelector('#am-draft-elo').dataset.deState "
                "=== 'ready'",
                timeout=15_000,
            )
            page.hover("#am-draft-elo")
            assert page.evaluate(_CONTRIB_SHOWN), "hover did not show the overlay"
            page.evaluate(_CONSUME_UPSTREAM)
            page.keyboard.press("Escape")
            assert page.evaluate(_CONTRIB_SHOWN), (
                "the draft-elo overlay was dismissed by an Escape another "
                "listener had consumed"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"
    finally:
        mock_server.set_draft_elo(None)


# RM-1070 ----------------------------------------------------------------
# Close order is PAINT order. Measured in headless Chromium (?ui_mock=1#home,
# 1920x920): #task-modal is z-index 200, #view-menu 9100, the Find Match
# picker 9200 (its backdrop 9100) and #digest-popout 9500, all position:
# fixed in the root stacking context. Before the fix each layer had its own
# document capture listener and the first REGISTERED open layer took the
# press: the task modal is wired before the view menu and the lazily bound
# picker, so with either open OVER the modal one Escape closed the modal
# underneath and left the upper layer showing. Both upper layers are opened
# here the way the keyboard opens them (an activation, no pointer): the modal
# backdrop intercepts the mouse, which is why only keyboard users reach this.

_OVER_MODAL = {
    "view-menu": "() => document.getElementById('view-trigger').click()",
    "find-match-picker": "() => document.getElementById('home-hero-cta').click()",
}


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("upper", sorted(_OVER_MODAL))
def test_escape_closes_the_layer_painted_on_top_first(
        mock_server, pw_browser, vp, upper):
    ctx, page, errors = _open_view(pw_browser, mock_server, vp, "home")
    try:
        _zen_on(page)
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        _open_layer(page, "task-modal")
        page.evaluate(_OVER_MODAL[upper])
        assert page.evaluate(_LAYER_OPEN[upper]), f"{upper} did not open"
        assert page.evaluate(_LAYER_OPEN["task-modal"]), "the modal closed"
        z = page.evaluate(
            """(sel) => [sel, '#task-modal'].map(s =>
                 +getComputedStyle(document.querySelector(s)).zIndex)""",
            "#view-menu" if upper == "view-menu" else "#home-find-match-picker",
        )
        assert z[0] > z[1], f"{upper} is not painted over the modal: z={z}"
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert page.evaluate(_LAYER_OPEN["task-modal"]) and st["zen"] == "1", (
            f"the first Escape closed the task modal UNDER the open {upper}: {st}"
        )
        assert not page.evaluate(_LAYER_OPEN[upper]), (
            f"the first Escape did not close the topmost layer ({upper}): {st}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STATE)
        assert not st["modalOpen"] and st["zen"] == "1", (
            f"the second Escape did not close only the task modal: {st}"
        )
        page.keyboard.press("Escape")
        assert page.evaluate(_STATE)["zen"] == "", "the third Escape kept zen"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# Every layer goes through the one dispatcher: several document capture
# listeners racing on registration order is the defect class, so the page
# may not grow a second one. An init script records every capture-phase
# keydown listener added to document or window whose source names Escape;
# after load, with the lazily bound Find Match picker opened too, exactly one
# may exist (the dispatcher). The source check pins which layers register.

_RECORD_CAPTURES = """
(() => {
  window.__escCaptures = [];
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    const capture = opts === true || !!(opts && opts.capture);
    if (type === 'keydown' && capture
        && (this === document || this === window)
        && String(fn).includes('Escape')) {
      window.__escCaptures.push(String(fn).slice(0, 80));
    }
    return orig.call(this, type, fn, opts);
  };
})();
"""


def test_every_escape_layer_registers_with_the_one_dispatcher(
        mock_server, pw_browser):
    import re
    from pathlib import Path

    ctx, page, errors = _new_page(pw_browser, mock_server, VIEWPORTS[0])
    try:
        page.add_init_script(_RECORD_CAPTURES)
        page.goto(mock_server.url + "/?ui_mock=1#home",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function("() => document.body.dataset.view === 'home'",
                               timeout=10_000)
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        page.evaluate("() => document.getElementById('home-hero-cta').click()")
        page.keyboard.press("Escape")
        caps = page.evaluate("() => window.__escCaptures")
        assert len(caps) == 1, (
            f"expected the one Escape dispatcher, found {len(caps)} capture-"
            f"phase Escape listeners: {caps}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"

    root = Path(__file__).resolve().parents[2] / "web" / "js"
    names = {}
    for rel in ("main.js", "panels/right_now.js", "panels/draft_elo.js"):
        src = (root / rel).read_text(encoding="utf-8")
        assert re.search(r"import \{[^}]*registerEscapeLayer[^}]*\} from "
                         r"['\"]\.{1,2}/lib/escape_layers\.js['\"]", src), rel
        names[rel] = re.findall(r"registerEscapeLayer\(\{\s*name:\s*\"([^\"]+)\"",
                                src)
    assert names == {
        "main.js": ["task-modal", "view-menu", "find-match-picker"],
        "panels/right_now.js": ["digest-popover"],
        "panels/draft_elo.js": ["draft-elo-contributions"],
    }, names


# RM-1074 ----------------------------------------------------------------
# The dispatcher ranks layers by their STACKING CONTEXTS, not by the z-index
# of the outermost positioned ancestor. Each case builds two registered
# layers over the same 400x400 box: a child (position:absolute; inset:0;
# z-index childZ) inside a wrapper styled to create, or not create, a
# stacking context, and a position:fixed sibling at z-index sibZ appended
# after it. The paint truth is Chromium's own hit test,
# document.elementsFromPoint, and each case also states the expected winner
# so the oracle itself is pinned. One Escape must close exactly the layer
# painted on top. Under the first cut (RM-1070) every case marked RED
# closed the wrong layer: a z-index trapped in a transform / opacity /
# filter / isolation / will-change / contain / blend context out-ranked the
# z 50 sibling, a static flex item's z-index 60 was ignored, and a top-layer
# popover ranked by its child's z-index 1.

_BOX = "position:absolute;top:0;left:0;width:400px;height:400px;"
_ITEM = "width:400px;height:400px;z-index:60;"
_POPOVER = _BOX + "margin:0;padding:0;border:0;right:auto;bottom:auto;"

# id -> (outer style, wrapper style, wrapper is a popover, childZ, sibZ, winner)
_STACK_CASES = {
    "transform-RED": ("", _BOX + "transform:translateZ(0)", False, 9999, 50, "sibling"),
    "opacity-RED": ("", _BOX + "opacity:0.99", False, 9999, 50, "sibling"),
    "filter-RED": ("", _BOX + "filter:brightness(1)", False, 9999, 50, "sibling"),
    "isolation-RED": ("", _BOX + "isolation:isolate", False, 9999, 50, "sibling"),
    "will-change-RED": ("", _BOX + "will-change:transform", False, 9999, 50, "sibling"),
    "contain-paint-RED": ("", _BOX + "contain:paint", False, 9999, 50, "sibling"),
    "blend-RED": ("", _BOX + "mix-blend-mode:multiply", False, 9999, 50, "sibling"),
    "flex-item-z-RED": (_BOX + "display:flex", _ITEM, False, 1, 50, "child"),
    "grid-item-z-RED": (_BOX + "display:grid", _ITEM, False, 1, 50, "child"),
    "popover-top-layer-RED": ("", _POPOVER, True, 1, 2147483647, "child"),
    "block-item-z-control": (_BOX, _ITEM, False, 1, 50, "sibling"),
    "no-context-control": ("", _BOX, False, 9999, 50, "child"),
    "positioned-z-control": ("", _BOX + "z-index:10", False, 9999, 50, "sibling"),
    # Measured in headless Chromium 147: container-type creates no context.
    "container-type-control": ("", _BOX + "container-type:size", False, 9999, 50, "child"),
    # RM-1075: four more creators Chromium 147 honours that the RM-1074
    # rules missed (view-transition-name makes a context with no transition
    # running; content-visibility:auto implies paint containment while the
    # computed `contain` stays none), a display:contents element that has no
    # box and so makes NO context whatever it carries, and a flex item whose
    # parent is display:contents (the item belongs to the nearest box). An
    # `outer` list nests its styles outermost first.
    "view-transition-name-RED": ("", _BOX + "view-transition-name:u48", False, 9999, 50, "sibling"),
    "content-visibility-auto-RED": ("", _BOX + "content-visibility:auto", False, 9999, 50, "sibling"),
    "box-reflect-RED": ("", _BOX + "-webkit-box-reflect:below", False, 9999, 50, "sibling"),
    "offset-path-RED": ("", _BOX + "offset-path:path('M0,0')", False, 9999, 50, "sibling"),
    "contents-opacity-RED": ("", "display:contents;opacity:0.5", False, 9999, 50, "child"),
    "contents-parent-flex-item-RED": (
        [_BOX + "display:flex", "display:contents"], _ITEM, False, 1, 50, "child"),
    "contents-parent-block-item-control": (
        [_BOX, "display:contents"], _ITEM, False, 1, 50, "sibling"),
    "mask-border-control": ("", _BOX + "mask-border-source:linear-gradient(red,red)",
                            False, 9999, 50, "child"),
}

_BUILD_STACK = """
async ([outer, wrap, popover, childZ, sibZ]) => {
  const m = await import('/js/lib/escape_layers.js');
  const outers = Array.isArray(outer) ? outer : [outer];
  const o = document.createElement('div');
  o.style.cssText = outers[0];
  let host = o;
  for (const css of outers.slice(1)) {
    const d = document.createElement('div');
    d.style.cssText = css;
    host.appendChild(d);
    host = d;
  }
  const w = document.createElement('div');
  w.style.cssText = wrap;
  if (popover) w.setAttribute('popover', 'manual');
  const c = document.createElement('div');
  c.id = 'u47-child';
  c.style.cssText = 'position:absolute;inset:0;background:#123;z-index:' + childZ;
  const sib = document.createElement('div');
  sib.id = 'u47-sibling';
  sib.style.cssText = 'position:fixed;top:0;left:0;width:400px;height:400px;'
    + 'background:#321;z-index:' + sibZ;
  w.appendChild(c);
  host.appendChild(w);
  document.body.appendChild(o);
  document.body.appendChild(sib);
  if (popover) w.showPopover();
  for (const el of [c, sib]) {
    el.dataset.open = '1';
    m.registerEscapeLayer({
      name: el.id, el: () => el,
      isOpen: () => el.dataset.open === '1',
      close: () => { el.dataset.open = '0'; },
    });
  }
  const hit = document.elementsFromPoint(200, 200).find((e) => e === c || e === sib);
  return hit ? hit.id.slice(4) : null;
}
"""

_STACK_OPEN = """
() => ({
  child: document.getElementById('u47-child').dataset.open === '1',
  sibling: document.getElementById('u47-sibling').dataset.open === '1',
})
"""


@pytest.mark.parametrize("case", sorted(_STACK_CASES))
def test_escape_ranks_layers_by_their_stacking_contexts(
        mock_server, pw_browser, case):
    outer, wrap, popover, child_z, sib_z, winner = _STACK_CASES[case]
    loser = "sibling" if winner == "child" else "child"
    ctx, page, errors = _open_view(pw_browser, mock_server, VIEWPORTS[0], "home")
    try:
        on_top = page.evaluate(_BUILD_STACK, [outer, wrap, popover, child_z, sib_z])
        assert on_top == winner, (
            f"{case}: Chromium paints {on_top} on top, the case expects {winner}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_STACK_OPEN)
        assert st == {winner: False, loser: True}, (
            f"{case}: one Escape should close only the {winner} painted on "
            f"top, got open={st}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# RM-1075 ----------------------------------------------------------------
# Two layers in the TOP LAYER (an open popover, a modal dialog) both paint
# over every z-index, and between them the one opened LAST paints on top,
# whatever their tree order. The RM-1074 cut ranked such a tie by tree
# order, so opening the later-in-tree layer first and the earlier one second
# made Escape close the one underneath. Each case builds `first` then
# `second` in tree order, registers both, opens them in `opens` order and
# checks the winner against Chromium's hit test before pressing Escape.
_TOP = ("position:fixed;inset:auto;top:0;left:0;width:400px;height:400px;"
        "margin:0;padding:0;border:0;max-width:none;max-height:none;")

# id -> (first kind, second kind, open order, winner)
_TOP_CASES = {
    "popover-opened-second-RED": ("popover", "popover", ["second", "first"], "first"),
    "popover-tree-order-control": ("popover", "popover", ["first", "second"], "second"),
    "dialog-opened-over-popover-RED": ("dialog", "popover", ["second", "first"], "first"),
    "dialog-opened-second-RED": ("dialog", "dialog", ["second", "first"], "first"),
    "dialog-tree-order-control": ("dialog", "dialog", ["first", "second"], "second"),
    # No popover-over-modal case: a popover outside an open modal dialog is
    # inert, so the hit test (the oracle here) never reports it on top.
}

_BUILD_TOP = """
async ([kinds, opens, css]) => {
  const m = await import('/js/lib/escape_layers.js');
  const els = {};
  ['first', 'second'].forEach((key, i) => {
    const el = document.createElement(kinds[i] === 'dialog' ? 'dialog' : 'div');
    el.id = 'u48-' + key;
    el.style.cssText = css + 'background:#' + (i ? '321' : '123');
    if (kinds[i] === 'popover') el.setAttribute('popover', 'manual');
    document.body.appendChild(el);
    els[key] = el;
    const dlg = kinds[i] === 'dialog';
    m.registerEscapeLayer({
      name: el.id, el: () => el,
      isOpen: () => (dlg ? el.open : el.matches(':popover-open')),
      close: () => (dlg ? el.close() : el.hidePopover()),
    });
  });
  for (const key of opens) {
    const el = els[key];
    if (el.tagName === 'DIALOG') el.showModal(); else el.showPopover();
  }
  const hit = document.elementsFromPoint(200, 200)
    .find((e) => e === els.first || e === els.second);
  return hit ? hit.id.slice(4) : null;
}
"""

_TOP_OPEN = """
() => {
  const st = (el) => (el.tagName === 'DIALOG' ? el.open : el.matches(':popover-open'));
  return {
    first: st(document.getElementById('u48-first')),
    second: st(document.getElementById('u48-second')),
  };
}
"""


@pytest.mark.parametrize("case", sorted(_TOP_CASES))
def test_escape_ranks_top_layer_ties_by_open_order(mock_server, pw_browser, case):
    first, second, opens, winner = _TOP_CASES[case]
    loser = "second" if winner == "first" else "first"
    ctx, page, errors = _open_view(pw_browser, mock_server, VIEWPORTS[0], "home")
    try:
        on_top = page.evaluate(_BUILD_TOP, [[first, second], opens, _TOP])
        assert on_top == winner, (
            f"{case}: Chromium paints {on_top} on top, the case expects {winner}"
        )
        page.keyboard.press("Escape")
        st = page.evaluate(_TOP_OPEN)
        assert st == {winner: False, loser: True}, (
            f"{case}: one Escape should close only the {winner} opened last, "
            f"got open={st}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
