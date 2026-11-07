"""
tests/snapshot_panels/test_user_builds_text_contrast.py
S144-U-203 (s144 uiux): every text line on the User Builds view reaches its
WCAG contrast floor on its resolved surface, in every theme, at the
1920x920 baseline and the 923x1280 companion window, with the editor shut
and open. The row Delete button reaches AA at rest AND on hover, and the
editor's status line reaches AA in both its ok and its error state.

Drive path: /?ui_mock=1&theme=<t>#user-builds, the recipe and landing
signal of test_user_builds_review_r30._open_user_builds (a .ub-build-row
appears). The editor opens through the real "+ Add build" button.

Colours are resolved by the browser and composited over the stacked
backgrounds (lane doc traps 3 and 4): the pair is fg on its own surface.
A text line inside a disabled control (WCAG 1.4.3 exempts inactive
components) is skipped by the whole-view sweep.

The status line is measured on the one real #ub-form-status: the test
stamps its class and text exactly as main.js _ubFormStatus does
(className "ub-form-status ok" / "ub-form-status error", hidden false),
then reads the computed colour and puts the element back.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_user_builds_rune_tabs import _RUNES, _TREES
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_AA_LARGE = 3.0

_ROWS = _HELPERS + """
  const host = document.getElementById('view-user-builds');
  const row = (e) => {
    const s = surface(e);
    const cs = getComputedStyle(e);
    return {
      cls: String(e.className), id: e.id,
      text: e.textContent.trim().slice(0, 40),
      fg: s ? over(rgba(cs.color), s) : null, bg: s,
      border: rgba(cs.borderTopColor),
      size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
      inactive: !!e.closest(
        ':disabled, [aria-disabled="true"], .is-disabled'),
    };
  };
  const all = () => [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
  const root = getComputedStyle(document.documentElement);
  const tok = (n) => rgba(root.getPropertyValue(n).trim());
"""

# Editor shut: every text line, plus each row's Delete button.
_SHUT = """async () => {
  await document.fonts.ready;
""" + _ROWS + """
  const deletes = [...host.querySelectorAll('.ub-btn-danger')]
    .filter((e) => e.checkVisibility()).map(row);
  return {all: all(), deletes, text: tok('--text'), bad: tok('--bad')};
}"""

# Editor open: every text line, then the status line stamped ok / error.
_OPEN = """async () => {
  await document.fonts.ready;
""" + _ROWS + """
  const open = all();
  const st = document.getElementById('ub-form-status');
  const keep = [st.className, st.textContent, st.hidden];
  const status = {};
  for (const kind of ['ok', 'error']) {
    st.hidden = false;
    st.className = 'ub-form-status ' + kind;
    st.textContent = kind === 'ok' ? 'Saved.' : 'Pick a champion first.';
    status[kind] = row(st);
  }
  st.className = keep[0]; st.textContent = keep[1]; st.hidden = keep[2];
  const secondary = [...host.querySelectorAll(
      '.ub-field > span, .ub-field-driven, .ub-rp-empty')]
    .filter((e) => e.checkVisibility()).map(row);
  return {all: open, status, secondary,
          text: tok('--text'), dim: tok('--text-dim')};
}"""

_HOVER = """async () => {
""" + _HELPERS + """
  const e = document.querySelector('#view-user-builds .ub-btn-danger');
  const s = surface(e);
  const cs = getComputedStyle(e);
  return {text: e.textContent.trim(), fg: over(rgba(cs.color), s), bg: s};
}"""


def _measure(mock_server, pw_browser, theme, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
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
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#user-builds",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        # The editor opens only once a champion is picked (_UB.champion);
        # same pick as test_user_builds_rune_tabs._open.
        page.fill("#ub-champion-input", "Tristana")
        page.dispatch_event("#ub-champion-input", "change")
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        btn = page.locator("#view-user-builds .ub-btn-danger").first
        btn.scroll_into_view_if_needed()
        btn.hover()
        page.wait_for_timeout(250)  # the 0.1 s colour transition
        hover = page.evaluate(_HOVER)
        page.mouse.move(0, 0)
        page.wait_for_timeout(250)
        shut = page.evaluate(_SHUT)
        page.click("#ub-add-btn")
        page.wait_for_function(
            "() => !document.getElementById('ub-form-pane').hidden"
            " && document.querySelectorAll('#ub-rp-tabs > button').length"
            f" === {len(_TREES)}",
            timeout=10_000,
        )
        opened = page.evaluate(_OPEN)
        got = {"shut": shut["all"], "deletes": shut["deletes"],
               "text": shut["text"], "bad": shut["bad"],
               "open": opened["all"], "status": opened["status"],
               "secondary": opened["secondary"], "dim": opened["dim"],
               "hover": hover}
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _large(row):
    return row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)


def _low(rows):
    out = []
    for row in rows:
        assert row["bg"] is not None, row
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            out.append((row["cls"], row["id"], row["text"], round(ratio, 2),
                        floor))
    return out


@pytest.mark.parametrize("theme", _THEMES)
def test_the_delete_button_reaches_aa_at_rest_and_on_hover(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    assert len(got["deletes"]) >= 2, got["deletes"]
    low = {}
    for i, row in enumerate(got["deletes"]):
        assert row["text"] == "Delete", row
        # 16 px / 700: not WCAG large text, so 4.5 applies.
        assert not _large(row), row
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < _AA:
            low[f"rest[{i}]"] = round(ratio, 2)
    hov = got["hover"]
    assert hov["text"] == "Delete", hov
    # The hover really applied: the fill is the theme's own --bad, so this
    # is not the at-rest colour read a second time.
    assert [round(c) for c in hov["bg"][:3]] == got["bad"][:3], (theme, hov)
    ratio = _ratio(hov["fg"], hov["bg"])
    if ratio < _AA:
        low["hover"] = round(ratio, 2)
    assert not low, f"Delete under AA {_AA} on {theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_delete_button_stays_red(theme, measured, mock_server,
                                     pw_browser):
    """The destructive action must still read as red by hue: the word keeps
    a red lead, and the border keeps the theme's own --bad, so the lift
    only moves the text."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    for row in got["deletes"]:
        r, g, b = row["fg"][:3]
        assert r - max(g, b) >= 60, (theme, (r, g, b))
        assert row["border"][:3] == got["bad"][:3], (theme, row["border"],
                                                     got["bad"])


@pytest.mark.parametrize("theme", _THEMES)
def test_both_status_states_reach_aa(theme, measured, mock_server,
                                     pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    low = {}
    for kind in ("ok", "error"):
        row = got["status"][kind]
        assert row["bg"] is not None, (kind, theme)
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < (_AA_LARGE if _large(row) else _AA):
            low[kind] = round(ratio, 2)
    r, g, b = got["status"]["error"]["fg"][:3]
    assert r - max(g, b) >= 60, ("error stays red", theme, (r, g, b))
    assert not low, f"status line under its floor on {theme}: {low}"


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_user_builds_text_line_reaches_its_floor(
        theme, vp, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    shut = [r for r in got["shut"] if not r["inactive"]]
    assert len(shut) >= 10, f"User Builds rendered too little: {got['shut']}"
    opened = [r for r in got["open"] if not r["inactive"]]
    assert len(opened) > len(shut), "the open editor added no text lines"
    assert any(r["id"] == "ub-form-title" for r in opened), opened
    low = _low(shut) + _low(opened)
    assert not low, f"under the WCAG floor on {theme} at {vp}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_editor_labels_stay_secondary(theme, measured, mock_server,
                                          pw_browser):
    """The lift must not invert the hierarchy: a field label, the "(driven
    by builder)" note and the rune picker's empty hint paint the secondary
    token --text-dim and sit under the primary --text on their own
    surface."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    sec = got["secondary"]
    assert len(sec) >= 8, sec
    classes = [r["cls"] for r in sec]
    assert "ub-field-driven" in classes and "ub-rp-empty" in classes, classes
    for row in sec:
        assert row["fg"][:3] == got["dim"][:3], (theme, row, got["dim"])
        primary = _ratio(_over_opaque(got["text"], row["bg"]), row["bg"])
        assert _ratio(row["fg"], row["bg"]) < primary, (theme, row)


def _over_opaque(top, bot):
    """Composite a token colour over the row's opaque surface."""
    a = top[3]
    return [top[i] * a + bot[i] * (1 - a) for i in range(3)] + [1]
