"""
tests/snapshot_panels/test_in_view_header_scope.py
The top bar's `header` rules style the top bar only; a `<header>` inside a
view styles exactly as a `<div>` with the same classes would (s144 lane
uiux, S144-U-176).

Measured before the fix (headless Chromium, /?ui_mock=1): the top bar's
rules were bare type selectors - `header { padding: 5px 18px; display: flex;
flex-direction: column; gap: 5px; background: var(--canvas); flex-shrink: 0;
position: relative }` in web/css/panels/header.css, `header { transition:
height 180ms ease }` in web/css/panels/primitives.css, and the mid / late
game-phase gradients `body[data-phase] header` in web/css/panels/base.css.
They matched the three in-view heads too: the User Builds editor head
(`header.ub-form-head`) and the Replay Timeline and Recording heads
(`header.replay-events-head`). Their own classes say `display: flex` and set
no direction, so they computed `flex-direction: column`: the editor's
"Add build" title sat above its close button instead of beside it, and the
Timeline title sat above its filters and count. Each also took the bar's
18 px side and 5 px top padding, the canvas fill (a gold or red gradient
in a mid / late game) and, in the editor head, the bar's 5 px gap.

Contract pinned here, at the 1920x920 baseline:
  - for every `<header>` that is not the top bar, a computed-style list
    (display, flex direction, padding, gap, background, position, flex
    shrink, transition) equals that of a `<div>` given the same classes in
    the same parent, with no game phase and in a mid and a late game;
  - with the editor open, the "Add build" title and its close button sit on
    one line at the head's two ends; with a match loaded, the Timeline
    title and its filters sit on one line;
  - the Recording head (unhidden; ui_mock carries no recording) keeps its
    title and key legend inside the head at 1920 and 320 px: one line at
    the baseline, the legend wrapping under the title where it cannot fit;
  - the top bar keeps its own look: a column, 5 px 18 px padding, the
    canvas fill and its mid / late gradients, and the 44 px compressed
    height when the page scrolls past 200 px.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_SIZE = {"width": 1920, "height": 920}
_PHASES = ("", "mid", "late")

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

# Every property the top bar's rules set, so any one of them leaking shows.
_PROPS = (
    "display", "flexDirection", "paddingTop", "paddingRight",
    "paddingBottom", "paddingLeft", "rowGap", "columnGap",
    "backgroundColor", "backgroundImage", "position", "flexShrink",
    "transitionProperty", "transitionDuration", "height",
)

_COMPARE = """(props) => {
  const out = [];
  const heads = Array.from(document.querySelectorAll("header"))
    .filter((h) => h.parentElement !== document.body);
  for (const h of heads) {
    const twin = document.createElement("div");
    twin.className = h.className;
    twin.innerHTML = h.innerHTML.replace(/\\sid="[^"]*"/g, "");
    h.after(twin);
    const a = getComputedStyle(h);
    const b = getComputedStyle(twin);
    const diff = {};
    for (const p of props) {
      if (a[p] !== b[p]) diff[p] = [a[p], b[p]];
    }
    twin.remove();
    out.push({cls: h.className, diff});
  }
  return out;
}"""

_TOP = """() => {
  const h = document.querySelector("body > header");
  const s = getComputedStyle(h);
  return {dir: s.flexDirection, pad: s.padding, bg: s.backgroundColor,
          img: s.backgroundImage, h: h.getBoundingClientRect().height,
          canvas: getComputedStyle(document.documentElement)
            .getPropertyValue("--canvas").trim()};
}"""


def _mid_y(b):
    return (b["y"] + b["y"] + b["height"]) / 2


def _open(pw_browser, url, view):
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=_SIZE)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(url + "/?ui_mock=1#" + view, wait_until="domcontentloaded",
              timeout=15_000)
    return ctx, page, errors


def _set_phase(page, phase):
    page.evaluate(
        "(p) => { if (p) document.body.dataset.phase = p;"
        " else delete document.body.dataset.phase; }", phase)


@pytest.fixture(scope="module")
def heads(mock_server, pw_browser):
    """Computed-style diffs per phase, plus the open editor and loaded
    Timeline geometry."""
    mock_server._store["data"] = {}
    got = {}
    ctx, page, errors = _open(pw_browser, mock_server.url, "user-builds")
    try:
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        page.evaluate(_SETTLE)
        for ph in _PHASES:
            _set_phase(page, ph)
            got[("diff", ph)] = page.evaluate(_COMPARE, list(_PROPS))
        _set_phase(page, "")
        page.fill("#ub-champion-input", "Tristana")
        page.dispatch_event("#ub-champion-input", "change")
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        page.click("#ub-add-btn")
        page.wait_for_function(
            "() => { const p = document.querySelector('#ub-form-pane');"
            " return p && !p.hasAttribute('hidden'); }", timeout=5_000)
        page.evaluate(_SETTLE)
        got["ub"] = {k: page.locator(sel).bounding_box() for k, sel in (
            ("head", ".ub-form-head"), ("title", "#ub-form-title"),
            ("close", "#ub-form-close"))}
    finally:
        ctx.close()
    assert not errors, f"user-builds page errors: {errors[:3]}"

    ctx, page, errors = _open(pw_browser, mock_server.url, "replay")
    try:
        page.wait_for_selector("#replay-match-list .replay-match-row",
                               timeout=10_000)
        page.click("#replay-match-list .replay-match-row")
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#replay-events-list .replay-events-row').length > 0",
            timeout=10_000)
        page.evaluate(_SETTLE)
        sec = "#replay-events-section .replay-events-"
        got["tl"] = {k: page.locator(sec + k).first.bounding_box()
                     for k in ("head", "title", "filters", "count")}
    finally:
        ctx.close()
    assert not errors, f"replay page errors: {errors[:3]}"
    return got


@pytest.mark.parametrize("phase", _PHASES, ids=["none", "mid", "late"])
def test_an_in_view_header_styles_as_a_div_would(heads, phase):
    rows = heads[("diff", phase)]
    classes = sorted(r["cls"] for r in rows)
    # The three in-view heads web/index.html carries today; a new one is
    # covered by the same check, so only a drop below three is a failure.
    assert classes.count("replay-events-head") >= 2, classes
    assert "ub-form-head" in classes, classes
    leaks = [r for r in rows if r["diff"]]
    assert not leaks, (phase, leaks)


def test_the_editor_title_and_close_share_one_line(heads):
    b = heads["ub"]
    head, title, close = b["head"], b["title"], b["close"]
    assert abs(_mid_y(title) - _mid_y(close)) <= 2, (title, close)
    assert close["x"] > title["x"] + title["width"], (title, close)
    # At the head's two ends: no 18 px bar padding on either side.
    assert abs(title["x"] - head["x"]) <= 1, (title, head)
    assert abs((close["x"] + close["width"]) - (head["x"] + head["width"])) <= 1, (
        close, head)


def test_the_timeline_title_and_filters_share_one_line(heads):
    b = heads["tl"]
    head, title, filters = b["head"], b["title"], b["filters"]
    assert abs(_mid_y(title) - _mid_y(filters)) <= 2, (title, filters)
    assert filters["x"] > title["x"] + title["width"], (title, filters)
    assert abs(title["x"] - head["x"]) <= 1, (title, head)
    # One row: the head is no taller than its tallest child plus the
    # bottom padding and border.
    tallest = max(title["height"], filters["height"], b["count"]["height"])
    assert head["height"] <= tallest + 8 + 1 + 1, (head, tallest)


def test_the_top_bar_keeps_its_own_look(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx, page, errors = _open(pw_browser, mock_server.url, "user-builds")
    try:
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        page.evaluate(_SETTLE)
        rest = {}
        for ph in _PHASES:
            _set_phase(page, ph)
            rest[ph] = page.evaluate(_TOP)
        _set_phase(page, "")
        page.evaluate(
            "document.querySelector('body > header').dataset.compressed = '1'")
        page.evaluate(_SETTLE)
        page.wait_for_timeout(400)  # the 180 ms height transition
        compressed = page.evaluate(_TOP)
    finally:
        ctx.close()
    assert not errors, errors[:3]
    base = rest[""]
    assert base["dir"] == "column", base
    assert base["pad"] == "5px 18px", base
    assert base["img"] == "none", base
    assert base["bg"] != "rgba(0, 0, 0, 0)", base
    for ph in ("mid", "late"):
        assert rest[ph]["img"].startswith("linear-gradient"), (ph, rest[ph])
    assert rest["mid"]["img"] != rest["late"]["img"], rest
    assert abs(compressed["h"] - 44) < 0.5, compressed


def test_the_top_bar_keeps_its_narrow_padding(mock_server, pw_browser):
    """input_activity.css narrows the bar under 1601 px; scoping the bar's
    own rule must not let it outrank that override."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#user-builds",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        got = page.evaluate(
            "() => { const s = getComputedStyle("
            "document.querySelector('body > header'));"
            " return [s.padding, s.rowGap]; }")
    finally:
        ctx.close()
    assert got == ["6px 16px", "10px"], got


_REC = """() => {
  const sec = document.getElementById("replay-video-section");
  sec.hidden = false;
  const head = sec.querySelector(".replay-events-head");
  const box = (e) => { const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
  return {head: box(head), title: box(head.querySelector(
    ".replay-events-title")), keys: box(head.querySelector(
    ".replay-video-keys")), sw: head.scrollWidth, cw: head.clientWidth};
}"""


@pytest.mark.parametrize("width", (1920, 320))
def test_the_recording_head_holds_its_legend(mock_server, pw_browser, width):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#replay",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector("#replay-match-list .replay-match-row",
                               timeout=10_000)
        page.evaluate(_SETTLE)
        r = page.evaluate(_REC)
    finally:
        ctx.close()
    head, title, keys = r["head"], r["title"], r["keys"]
    assert r["sw"] <= r["cw"], r
    for part in (title, keys):
        assert part["l"] >= head["l"] - 0.5 and part["r"] <= head["r"] + 0.5, r
    if width == 1920:
        # One line: the legend sits right of the title, not under it.
        assert keys["l"] > title["r"], r
        assert keys["t"] < title["b"] and title["t"] < keys["b"], r
    else:
        assert keys["t"] >= title["b"] - 0.5, r
