"""
tests/snapshot_panels/test_user_builds_fit.py
The User Builds list pane contains its own content, and the view fits the
1920x920 baseline without a scroll once it has settled (session 144, lane
uiux, RM-1008).

RM-1008 was filed as "at 1920x920 the User Builds view scrolls 1px at rest
(scrollHeight 828 vs clientHeight 827)". Re-measured in headless Chromium on
/?ui_mock=1#user-builds, that 1px is a FIRST-PAINT reading, not a resting
one. Right at the landing signal (#ub-count leaves "-") the webfonts have
not loaded: the view head is 44px and the list pane ends at y=882, so the
view reads 828/827 (pre-footer CSS) or 828/821 (the 42px footer of
RM-1009). After document.fonts.ready plus two frames the head is 40px,
the pane ends at y=851 and the view reads 827/827 (pre-footer) and 821/821
now, with about 26px of slack below the pane. Nothing sized to the view
causes it, and the pane's gold corner bracket (`.ub-list-pane::after`,
`bottom: -1px` in web/css/panels/header.css) does not either: with the
brackets hidden the view reads the same.

What the bracket DOES do is the RM-1006 class on the pane itself: the
pane reads scrollHeight 678 against clientHeight 677, because the ::after
sits on the pane's 1px border and scrollHeight counts from the padding
edge. With the brackets hidden the pane reads equal.

Rule pinned here, by layout value on the SETTLED page (a grep cannot see
any of it), at 1920x920 and at the 923x1280 companion width:
- every in-flow child of .ub-list-pane ends inside the pane's content box
  (bottom border and bottom padding subtracted);
- whatever reaches past the pane's padding box stays inside its border box
  (scrollHeight - clientHeight <= the bottom border width), and with the
  corner brackets hidden nothing reaches past the padding box at all, so
  the 1px is the bracket and only the bracket;
- neither #view-user-builds nor the document scrolls vertically with the
  editor pane closed (the resting state; the open editor is a long form and
  is allowed to scroll).

Drive path: /?ui_mock=1#user-builds, the same recipe and landing signal as
test_user_builds_view.py, then the settle wait of
test_lobby_card_containment.py.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_VIEWPORTS = {
    "baseline": {"width": 1920, "height": 920},
    "companion": {"width": 923, "height": 1280},
}

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const pane = document.querySelector("#view-user-builds .ub-list-pane");
  const form = document.querySelector("#view-user-builds .ub-form-pane");
  const view = document.getElementById("view-user-builds");
  const cs = getComputedStyle(pane);
  const r = pane.getBoundingClientRect();
  const contentBottom = r.bottom - parseFloat(cs.borderBottomWidth)
    - parseFloat(cs.paddingBottom);
  const kids = [...pane.children]
    .filter((c) => {
      const k = getComputedStyle(c);
      return k.display !== "none" && k.position !== "absolute"
        && k.position !== "fixed";
    })
    .map((c) => ({
      cls: c.className,
      bottom: c.getBoundingClientRect().bottom
        + parseFloat(getComputedStyle(c).marginBottom),
    }));
  return {
    rows: document.querySelectorAll("#ub-build-list .ub-build-row").length,
    formHidden: !form || form.hidden,
    view: getComputedStyle(view).display,
    contentBottom,
    kids,
    paneOverflowY: pane.scrollHeight - pane.clientHeight,
    borderBottom: parseFloat(cs.borderBottomWidth),
    viewScroll: view.scrollHeight - view.clientHeight,
    docScroll: document.documentElement.scrollHeight - window.innerHeight,
  };
}"""

_HIDE_BRACKETS = (
    ".ub-list-pane::before, .ub-list-pane::after,"
    " .ub-form-pane::before, .ub-form-pane::after"
    " { display: none !important; }"
)


@pytest.fixture(scope="module", params=sorted(_VIEWPORTS))
def user_builds(request, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport=_VIEWPORTS[request.param]
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#user-builds",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const q = document.querySelector('#ub-count');"
            " const t = q ? q.textContent.trim() : '';"
            " return t !== '' && t !== '-'; })()",
            timeout=10_000,
        )
        # Measured: at the landing signal the fonts are not in yet (view
        # head 44px, a transient 828/821 view); measure the settled page.
        page.evaluate(_SETTLE)
        settled = page.evaluate(_READ)
        page.add_style_tag(content=_HIDE_BRACKETS)
        page.evaluate(_SETTLE)
        bare = page.evaluate(_READ)
        yield request.param, settled, bare, errors
    finally:
        page.close()
        ctx.close()


def test_the_resting_list_pane_is_measured(user_builds):
    # Anchor: an empty pane or a hidden view would pass every check below.
    _, r, _, errors = user_builds
    assert r["view"] != "none", r
    assert r["formHidden"] is True, r
    assert r["rows"] == 5, r
    assert len(r["kids"]) >= 2, r
    assert errors == []


def test_every_list_pane_child_ends_inside_the_pane_content_box(user_builds):
    _, r, _, _ = user_builds
    for kid in r["kids"]:
        assert kid["bottom"] <= r["contentBottom"] + 0.5, (r, kid)


def test_nothing_escapes_the_list_pane_border_box(user_builds):
    _, r, _, _ = user_builds
    assert r["paneOverflowY"] <= r["borderBottom"], r


def test_the_list_pane_1px_is_the_corner_bracket_only(user_builds):
    _, _, bare, _ = user_builds
    assert bare["paneOverflowY"] <= 0, bare


def test_user_builds_fits_without_vertical_scroll_at_rest(user_builds):
    _, r, bare, _ = user_builds
    assert r["viewScroll"] <= 0, r
    assert r["docScroll"] <= 0, r
    # The brackets are not what the view fit depends on either way.
    assert bare["viewScroll"] == r["viewScroll"], (r, bare)
