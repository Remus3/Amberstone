"""
tests/snapshot_panels/test_view_section_sub_floor.py
The page-head sub-line (.view-section-sub) renders on the v2.1 --fs-sm
tier, never below the --fs-xs floor (session 144, lane uiux, RM-975).

web/css/panels/header.css carried `.view-section-sub { font-size: 12px }`
and `.view-section-sub.is-error { font-size: 15px }`: the s218 values (one
px over the v1 11 / 14) that the v2 / v2.1 scale lift never reached.
docs/UI_SCALE_SPEC_V2.md names .view-section-sub as an --fs-sm consumer
(18px), and no operator exception covers it. Measured in headless Chromium
at the 1920x920 baseline: the PGR #lm-meta "BRAWL - 23h ago - ..." line
and the Session #session-window line were a computed 12px.

Rule pinned here, by COMPUTED value (a grep cannot see an invalid var()):
- every .view-section-sub in the page (9 view heads) computes to the
  resolved --fs-sm, and that is at or above the resolved --fs-xs;
- the .is-error variant (the lobby's "awaiting LCU lobby data feed") is
  never smaller than the plain sub-line it replaces;
- on two rendered views (Session, Post Game Review) the visible sub-line
  is that size, and the page head still fits on one line at 1920 wide;
- at the ~923px rc-shell companion width the h2 page title stays on ONE
  line on the three views with the longest sub-lines (User Builds, Build
  Insights, the archive Post Game Review): before the h2 flex-shrink: 0
  rule the 18px sub-line squeezed each title onto two lines (head 40 ->
  75px, measured headless).

Drive path: /?ui_mock=1#session and /?ui_mock=1&mode=sr#last-match, the
same recipes as test_session_view.py and test_last_match_view.py.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_TOKENS = """() => {
  const probe = (v) => {
    const d = document.createElement("span");
    d.style.fontSize = "var(" + v + ")";
    document.body.appendChild(d);
    const px = parseFloat(getComputedStyle(d).fontSize);
    d.remove();
    return px;
  };
  return {xs: probe("--fs-xs"), sm: probe("--fs-sm")};
}"""

_ALL_SUBS = """() => Array.from(
  document.querySelectorAll(".view-section-sub")
).map((el) => [
  el.id || el.closest("section, .view-section").id || "?",
  parseFloat(getComputedStyle(el).fontSize),
])"""

_ERROR_SIZE = """() => {
  const el = document.querySelector(".view-section-sub");
  const plain = parseFloat(getComputedStyle(el).fontSize);
  el.classList.add("is-error");
  const err = parseFloat(getComputedStyle(el).fontSize);
  el.classList.remove("is-error");
  return [plain, err];
}"""

_HEAD = """(id) => {
  const sub = document.getElementById(id);
  const head = sub.closest(".view-section-head");
  const h2 = head.querySelector("h2");
  const sr = sub.getBoundingClientRect();
  const hr = h2.getBoundingClientRect();
  return {
    size: parseFloat(getComputedStyle(sub).fontSize),
    visible: sr.width > 0 && sr.height > 0,
    text: sub.textContent.trim(),
    // one line: the sub-line box is not taller than the h2 line box
    one_line: sr.height <= hr.height + 1,
    overflow: head.scrollWidth > head.clientWidth + 1,
  };
}"""


_H2_LINES = """() => {
  const sec = Array.from(document.querySelectorAll(".view-section")).find(
    (s) => s.getBoundingClientRect().height > 0);
  const h2 = sec.querySelector(".view-section-head h2");
  const sub = sec.querySelector(".view-section-head .view-section-sub");
  // One line = the h2 box is under 1.6x its font size (measured: 35px
  // for one 29px line, 70px for two). A range-rect top count is no use
  // here: the archive h2 nests the inline .hpgr-tag pill, whose padded
  // box sits at its own top on a single line.
  const fs = parseFloat(getComputedStyle(h2).fontSize);
  return {
    sec: sec.id,
    h2_h: h2.getBoundingClientRect().height,
    h2_one_line: h2.getBoundingClientRect().height < fs * 1.6,
    sub_size: parseFloat(getComputedStyle(sub).fontSize),
    page_overflow:
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}"""


def _open(pw_browser, mock_server, path, ready, width=1920, height=920):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": width, "height": height}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + path, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(ready, timeout=10_000)
    return ctx, page, errors


_SESSION_READY = (
    "document.querySelector('#session-games') && "
    "!['-', ''].includes("
    "document.querySelector('#session-games').textContent.trim())"
)
_PGR_READY = (
    "document.querySelector('#lm-mode-tag') && "
    "!['-', ''].includes("
    "document.querySelector('#lm-mode-tag').textContent.trim())"
)


def test_every_view_section_sub_is_on_fs_sm(mock_server, pw_browser):
    ctx, page, errors = _open(
        pw_browser, mock_server, "/?ui_mock=1#session", _SESSION_READY
    )
    try:
        tok = page.evaluate(_TOKENS)
        assert tok["xs"] == 16 and tok["sm"] >= tok["xs"], tok
        subs = page.evaluate(_ALL_SUBS)
        # index.html carries 9 page-head sub-lines; an empty list would
        # pass the size check vacuously.
        assert len(subs) >= 9, subs
        bad = [(where, px) for where, px in subs if px != tok["sm"]]
        assert not bad, f"sub-lines off --fs-sm ({tok['sm']}px): {bad}"
        plain, err = page.evaluate(_ERROR_SIZE)
        assert plain == tok["sm"], (plain, tok)
        assert err >= plain, f"is-error {err}px is smaller than plain {plain}px"
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize(
    "path,ready,sub_id",
    [
        ("/?ui_mock=1#session", _SESSION_READY, "session-window"),
        ("/?ui_mock=1&mode=sr#last-match", _PGR_READY, "lm-meta"),
    ],
    ids=["session", "post-game-review"],
)
def test_rendered_page_head_sub_line(mock_server, pw_browser, path, ready, sub_id):
    ctx, page, errors = _open(pw_browser, mock_server, path, ready)
    try:
        tok = page.evaluate(_TOKENS)
        head = page.evaluate(_HEAD, sub_id)
        assert head["visible"], head
        assert head["size"] == tok["sm"], (head, tok)
        assert head["size"] >= tok["xs"], (head, tok)
        assert head["one_line"], head
        assert not head["overflow"], head
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("view", ["user-builds", "build-insights", "historical-pgr"])
def test_companion_width_keeps_the_page_title_on_one_line(
    mock_server, pw_browser, view
):
    ready = f"document.body.dataset.view === '{view}'"
    ctx, page, errors = _open(
        pw_browser, mock_server, f"/?ui_mock=1#{view}", ready, width=923, height=1280
    )
    try:
        tok = page.evaluate(_TOKENS)
        got = page.evaluate(_H2_LINES)
        assert got["sec"] == f"view-{view}", got
        assert got["sub_size"] == tok["sm"], (got, tok)
        assert got["h2_one_line"], got
        assert got["page_overflow"] <= 0, got
        assert not errors, errors
    finally:
        ctx.close()
