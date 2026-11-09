"""
tests/snapshot_panels/test_home_find_match_picker_contrast.py
S144-U-253 (s144 uiux): every text line of the open Home Find Match picker
(#home-find-match-picker) reaches the WCAG 1.4.3 AA text floor in all six
themes, at rest, under a real mouse hover and on the keyboard-focused item.

WHY A PIN AND NOT A FIX. The picker shares the .lq-mode-* rules with the
Lobby "Change Lobby Mode" menu (S144-U-251 lifted that menu's current label
from 4.41:1 in arcane), but it opens over the Home page under its own scrim,
at its own sizes (home.css: section heads --fs-sm, items --fs-md), and no
test read its colours. MEASURED headless under /?ui_mock=1&theme=<t>#home at
1920x920 before this module: every line already passes. Lowest at rest, the
18 px / 800 section heads (not large text, floor 4.5:1): 6.37:1 hextech to
8.18:1 terminal. The 22 px / 700 queue items are large text (floor 3:1) and
read 12.83:1 or more at rest, 9.25:1 or more hovered (--info-soft wash),
12.83:1 or more focused. Nothing to fix; this module pins the verdict so a
later token or rule change that dims the picker fails here, with the theme,
state and line named.

Checked per theme on its own page, booted in the theme (?theme=) with the
transitions-off sheet added before the first interaction (the items
transition background and border on hover, RM-1132): the picker opens from
the hero Find Match CTA; at rest all 4 section heads and all 11 queue items
are read; the hovered item really is hovered, really changes its fill, and
reaches its floor; after a keyboard open (Enter on the CTA, then Tab) the
focused item matches :focus-visible and reaches its floor. The ring itself is
pinned by test_home_find_match_picker_focus.py.

/api/lcu-cmd is fulfilled at the page; nothing here clicks a queue item, so
no LCU command is even attempted.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_AA = 4.5
_AA_LARGE = 3.0
_HOVER_QID = "1090"  # TFT Normal
_FOCUS_QID = "480"   # Swiftplay: the second item, one Tab after a keyboard open
_SECTIONS = ["SR", "ARAM", "Rotating", "TFT"]
_ITEMS = 11

_MEASURE = """(qid) => {
""" + _HELPERS + """
  const one = (el) => {
    const cs = getComputedStyle(el);
    const s = surface(el);
    return {cls: String(el.className),
            qid: el.dataset ? (el.dataset.hfmQid || '') : '',
            text: el.textContent.trim(),
            fg: s ? over(rgba(cs.color), s) : null, bg: s,
            size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
            fill: rgba(cs.backgroundColor),
            hovered: el.matches(':hover'),
            focused: el.matches(':focus-visible')};
  };
  const picker = document.getElementById('home-find-match-picker');
  const rows = [picker, ...picker.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(one);
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    open: !picker.classList.contains('hidden') && picker.checkVisibility(),
    rows,
    pick: qid ? one(picker.querySelector(
      '.lq-mode-item[data-hfm-qid="' + qid + '"]')) : null,
  };
}"""


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/lcu-cmd*", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&theme={theme}#home",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector("#home-hero-cta", state="visible", timeout=10_000)
        page.evaluate("document.fonts.ready.then(() => true)")
        page.add_style_tag(content=_SHEET)
        page.click("#home-hero-cta")
        page.mouse.move(2, 2)
        rest = page.evaluate(_MEASURE, "")
        page.hover("#home-find-match-picker"
                   f' .lq-mode-item[data-hfm-qid="{_HOVER_QID}"]')
        hover = page.evaluate(_MEASURE, _HOVER_QID)
        page.mouse.move(2, 2)
        page.keyboard.press("Escape")
        page.focus("#home-hero-cta")
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        focus = page.evaluate(_MEASURE, _FOCUS_QID)
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, errors[:3]
    return {"rest": rest, "hover": hover, "focus": focus}


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


def _floor(row):
    large = row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)
    return _AA_LARGE if large else _AA


def _shortfalls(rows, tag):
    bad = []
    for r in rows:
        assert r["bg"] is not None, (tag, r)
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < _floor(r):
            bad.append(f"{tag} {r['text']!r} {ratio:.2f}:1 < {_floor(r)}")
    return bad


@pytest.mark.parametrize("theme", _THEMES)
def test_open_picker_text_reaches_its_floor(theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["rest"]
    assert got["theme"] == theme, got["theme"]
    assert got["open"], "the Home Find Match picker did not open"
    rows = got["rows"]
    # 4 section heads + 11 queue items: an empty read cannot pass.
    heads = [r["text"] for r in rows if "lq-mode-section" in r["cls"]]
    items = [r for r in rows if "lq-mode-item" in r["cls"]]
    assert heads == _SECTIONS, heads
    assert len(items) == _ITEMS and len(rows) == len(_SECTIONS) + _ITEMS, (
        [r["text"] for r in rows])
    bad = _shortfalls(rows, "rest")
    assert not bad, f"{theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_hovered_item_reaches_its_floor_and_hover_moves_the_fill(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)
    h = got["hover"]["pick"]
    assert h["hovered"], h
    bad = _shortfalls([h], "hover")
    assert not bad, f"{theme}: " + "; ".join(bad)
    rest = [r for r in got["rest"]["rows"] if r["qid"] == _HOVER_QID]
    assert len(rest) == 1, rest
    assert not rest[0]["hovered"], rest[0]
    # An inert hover would pass the contrast check trivially.
    assert max(abs(a - b) for a, b in zip(rest[0]["fill"][:3], h["fill"][:3])) > 4 \
        or rest[0]["fill"][3] != h["fill"][3], (theme, rest[0]["fill"], h["fill"])


@pytest.mark.parametrize("theme", _THEMES)
def test_keyboard_focused_item_reaches_its_floor(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["focus"]
    assert got["open"], "the keyboard open did not show the picker"
    f = got["pick"]
    assert f["focused"], f"{theme}: Tab did not land :focus-visible on {f['text']!r}"
    assert not f["hovered"], f
    bad = _shortfalls([f], "focus")
    assert not bad, f"{theme}: " + "; ".join(bad)
    # The whole open picker still reads under keyboard focus.
    bad = _shortfalls(got["rows"], "focus-open")
    assert not bad, f"{theme}: " + "; ".join(bad)
