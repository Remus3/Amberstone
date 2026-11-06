"""
tests/snapshot_panels/test_view_head_narrow_wrap.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) every dashboard view head
(.view-section-head) wraps inside its view instead of running past it
(s144 lane uiux, RM-1774; RM-1772 did it for Active Match alone).

Measured before the fix (ui_mock, headless Chromium), the head's own
descendants against the view's padding edge:
  - History: the four scope tabs held one row beside the title, so from 480
    down they ran 95 px past the view (215 px at 360 / 320), and at 720 /
    640 the tab labels broke onto two lines inside 56 px buttons;
  - User Builds: the sub-line holds one unbreakable data-file path, so it
    could not shrink below it and ran 155 px past at 480, 275 px at 320;
  - archive Post Game Review: the Back button ran 25 px past from 640 down,
    the title (with its ARCHIVE tag) 112 px past at 360;
  - Champ Select, Build Insights, Replay, Post Game Review: the sub-line or
    the title ran past at 360 / 320; Pre-Game Lobby's title at 320.
8 of the 11 heads reached past the view at 360 and 320.

Contract pinned here, ui_mock, all 11 views, at 640x900, 480x800, 360x740
and 320x640:
  - no displayed head descendant reaches past the head's own box, and the
    head does not scroll sideways;
  - the title breaks only between words (no line narrower than its widest
    word), and a scope tab keeps its label on one line at the hit floor;
  - the sub-line stays beside the title while 12em fits (User Builds at
    640), and drops under it after.
Above the line (722x900) the head keeps the RM-975 rule: no wrap, and the
title does not shrink. The overlay shell keeps its own heads.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_VIEWS = (
    "lobby", "champ-select", "session", "history", "user-builds",
    "build-insights", "settings", "replay", "last-match", "historical-pgr",
    "active-match",
)

_NARROW = ((640, 900), (480, 800), (360, 740), (320, 640))
_WIDE = (722, 900)

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const sec = Array.from(document.querySelectorAll("section.view-section"))
    .find((s) => getComputedStyle(s).display !== "none");
  if (!sec) return null;
  const head = sec.querySelector(".view-section-head");
  const hr = head.getBoundingClientRect();
  const shown = (e) => getComputedStyle(e).display !== "none"
    && e.getBoundingClientRect().width > 0;
  const past = [];
  for (const d of head.querySelectorAll("*")) {
    if (!shown(d)) continue;
    const r = d.getBoundingClientRect();
    if (r.right > hr.right + 1 || r.left < hr.left - 1) {
      past.push([d.tagName + "." + String(d.className),
                 Math.round(r.left), Math.round(r.right),
                 Math.round(hr.left), Math.round(hr.right)]);
    }
  }
  const box = (e) => {
    if (!e || !shown(e)) return null;
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const h2 = head.querySelector("h2");
  // Widest word of the title, measured in the title's own font.
  const probe = document.createElement("span");
  probe.style.cssText = "position:absolute;visibility:hidden;"
    + "white-space:nowrap";
  h2.appendChild(probe);
  let widest = 0;
  for (const w of h2.childNodes[0].textContent.trim().split(/\\s+/)) {
    probe.textContent = w;
    widest = Math.max(widest, probe.getBoundingClientRect().width);
  }
  probe.remove();
  const lh = parseFloat(getComputedStyle(h2).lineHeight);
  const tabs = Array.from(head.querySelectorAll(".view-tab")).filter(shown)
    .map((b) => ({h: b.getBoundingClientRect().height,
                  sw: b.scrollWidth, cw: b.clientWidth,
                  lines: Math.round((b.getBoundingClientRect().height
                    - parseFloat(getComputedStyle(b).paddingTop)
                    - parseFloat(getComputedStyle(b).paddingBottom)
                    - parseFloat(getComputedStyle(b).borderTopWidth)
                    - parseFloat(getComputedStyle(b).borderBottomWidth))
                    / parseFloat(getComputedStyle(b).lineHeight))}));
  const cs = getComputedStyle(head);
  return {
    sec: sec.id, past,
    head: {sw: head.scrollWidth, cw: head.clientWidth, wrap: cs.flexWrap},
    h2: box(h2), h2Lines: Math.round(h2.getBoundingClientRect().height / lh),
    h2Shrink: getComputedStyle(h2).flexShrink, widest,
    sub: box(head.querySelector(".view-section-sub")), tabs,
  };
}"""


def _read_all(pw_browser, url, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    got: dict[str, dict] = {}
    try:
        for view in _VIEWS:
            page.goto(url + "/?ui_mock=1#" + view,
                      wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_function(
                f"document.body.dataset.view === '{view}'", timeout=10_000
            )
            page.evaluate(_SETTLE)
            got[view] = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {size: _read_all(pw_browser, mock_server.url, size)
            for size in _NARROW}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return _read_all(pw_browser, mock_server.url, _WIDE)


_CASES = [(s, v) for s in _NARROW for v in _VIEWS]
_IDS = [f"{s[0]}-{v}" for s, v in _CASES]


@pytest.mark.parametrize(("size", "view"), _CASES, ids=_IDS)
def test_no_head_descendant_reaches_past_the_head(narrow, size, view):
    r = narrow[size][view]
    assert r is not None and r["sec"] == "view-" + view, r
    assert r["past"] == [], (size, view, r["past"])
    assert r["head"]["sw"] <= r["head"]["cw"] + 1, (size, view, r["head"])
    assert r["head"]["wrap"] == "wrap", r["head"]


@pytest.mark.parametrize(("size", "view"), _CASES, ids=_IDS)
def test_title_breaks_only_between_words(narrow, size, view):
    r = narrow[size][view]
    h2 = r["h2"]
    assert h2 is not None, (size, view)
    # One line, or every line at least as wide as the widest word: a title
    # squeezed narrower than a word would cut it or spill it.
    assert r["h2Lines"] == 1 or h2["w"] + 1 >= r["widest"], (size, view, r)


@pytest.mark.parametrize("size", _NARROW, ids=[str(s[0]) for s in _NARROW])
def test_history_scope_tabs_keep_one_line_labels_at_the_hit_floor(
    narrow, size
):
    tabs = narrow[size]["history"]["tabs"]
    assert len(tabs) == 4, tabs
    for t in tabs:
        assert t["lines"] == 1, (size, t)
        assert t["sw"] <= t["cw"] + 1, (size, t)
        assert t["h"] >= 42 - 0.5, (size, t)


def test_sub_line_stays_beside_the_title_while_12em_fits(narrow):
    # User Builds at 640: 602 px content, a 214 px title, so the sub-line
    # keeps the rest of the row beside it.
    r = narrow[(640, 900)]["user-builds"]
    assert r["sub"]["l"] >= r["h2"]["r"], r
    assert r["sub"]["t"] < r["h2"]["b"], r


@pytest.mark.parametrize("size", [(360, 740), (320, 640)], ids=["360", "320"])
def test_sub_line_drops_under_the_title_when_12em_does_not_fit(narrow, size):
    r = narrow[size]["user-builds"]
    assert r["sub"]["t"] >= r["h2"]["b"] - 1, (size, r)
    assert abs(r["sub"]["l"] - r["h2"]["l"]) <= 1, (size, r)


@pytest.mark.parametrize("view", _VIEWS)
def test_above_the_line_the_head_keeps_the_rm975_rule(wide, view):
    r = wide[view]
    assert r is not None and r["sec"] == "view-" + view, r
    assert r["head"]["wrap"] == "nowrap", (view, r["head"])
    assert r["h2Shrink"] == "0", (view, r["h2Shrink"])


def test_overlay_shell_heads_do_not_take_the_narrow_rule(
    mock_server, pw_browser
):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 480, "height": 800}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    try:
        page.goto(mock_server.url + "/?ui_mock=1#user-builds",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'user-builds'", timeout=10_000
        )
        got = page.evaluate("""() => {
          const head = document.querySelector(
            '#view-user-builds .view-section-head');
          const before = getComputedStyle(head).flexWrap;
          document.body.dataset.shell = 'overlay';
          const after = getComputedStyle(head).flexWrap;
          const shrink = getComputedStyle(head.querySelector('h2')).flexShrink;
          return {before, after, shrink};
        }""")
    finally:
        ctx.close()
    assert got == {"before": "wrap", "after": "nowrap", "shrink": "0"}, got
