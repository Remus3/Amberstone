"""
tests/snapshot_panels/test_lobby_mode_menu_current_contrast.py
S144-U-251 (s144 uiux): the Lobby "Change Lobby Mode" menu (#lv-mode-menu)
marks the queue the lobby card names as current, and every text line of the
open menu - and of the lane-preference popup (#lv-lane-popup) - reaches the
WCAG 1.4.3 AA text floor in all six themes, at rest and under a real hover.

THE DEFECTS. MEASURED headless under /?ui_mock=1&theme=<t>#lobby at
1920x920 before the fix:

1. The menu marked "Practice Tool" current while the card above it read
   RANKED SOLO/DUO. The card renders from _lobbyResolveLcu() (the ui_mock
   fixture, web/data/ui_mock/lobby.json queue_id 420), but the trigger's
   click handler read state.latest.lcu directly; under ui_mock that holds no
   lobby, `(lobby && lobby.queue_id) | 0` gave 0, and 0 is Practice Tool's
   data-qid. The open menu contradicted the card it switches.
2. The current item's label (.lq-mode-item.is-current) is --clock on the
   --gold-soft wash over --surface-head, 18 px / 700. Bold 18 px is not WCAG
   large text (that starts at 18.66 px bold), so the floor is 4.5:1, and it
   read 4.41:1 in arcane (hextech 5.22, ember 5.63, bloodmoon 5.82, terminal
   5.86, moonlit 6.02).

THE FIX. The click handler reads _lobbyResolveLcu(), the resolver the card
already uses; outside ui_mock it returns the same state.latest.lcu object as
before, so the live path is unchanged. The current label mixes --clock 80
percent toward --text in oklab (the RM-1550 / S144-U-239 lift pattern); the
--clock border and the --gold-soft wash stay, so the current queue still
reads by hue and by its frame.

Checked per theme on its own page, booted in the theme (?theme=) with the
transitions-off sheet added before the first interaction (the menu items
transition background and border, RM-1132): exactly one item is current and
it is the fixture's queue; every visible text element of the trigger, the
open menu and the open lane popup reaches its floor over the resolved
surface (4.5:1, or 3:1 for large text); the hovered item reaches it too and
its hover really changes the fill; the current item keeps its --clock border
and still differs in colour from a plain item.

/api/lcu-cmd is fulfilled at the page; nothing here clicks a queue item, so
no LCU command is even attempted.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_AA = 4.5
_AA_LARGE = 3.0
_FIXTURE = (Path(__file__).resolve().parents[2]
            / "web" / "data" / "ui_mock" / "lobby.json")
_HOVER_QID = "1090"  # TFT Normal: never the fixture's queue (asserted)

_MEASURE = """(hoverQid) => {
""" + _HELPERS + """
  const one = (el) => {
    const cs = getComputedStyle(el);
    const s = surface(el);
    return {cls: String(el.className), id: el.id || '',
            qid: el.dataset ? (el.dataset.qid || '') : '',
            text: el.textContent.trim(),
            fg: s ? over(rgba(cs.color), s) : null, bg: s,
            size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
            fill: rgba(cs.backgroundColor), border: rgba(cs.borderTopColor),
            hovered: el.matches(':hover')};
  };
  const texts = (root) => [root, ...root.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(one);
  const menu = document.getElementById('lv-mode-menu');
  const popup = document.getElementById('lv-lane-popup');
  const root = getComputedStyle(document.documentElement);
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    menuOpen: !menu.classList.contains('hidden') && menu.checkVisibility(),
    popupOpen: !popup.classList.contains('hidden') && popup.checkVisibility(),
    current: [...menu.querySelectorAll('.lq-mode-item.is-current')]
      .map((e) => e.dataset.qid),
    menu: menu.checkVisibility()
      ? [...texts(document.getElementById('lv-mode-trigger')),
         ...texts(menu)] : [],
    popup: popup.checkVisibility() ? texts(popup) : [],
    hover: hoverQid ? one(menu.querySelector(
      '.lq-mode-item[data-qid="' + hoverQid + '"]')) : null,
    plain: one(menu.querySelector('.lq-mode-item:not(.is-current)')),
    clock: rgba(root.getPropertyValue('--clock').trim()),
  };
}"""


def _fixture_qid():
    return str(json.loads(_FIXTURE.read_text(encoding="utf-8"))["lobby"]["queue_id"])


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
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "id": "synthetic"})))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&theme={theme}#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.view === 'lobby'", timeout=10_000)
        # The card has rendered the fixture's queue: the resolver is loaded.
        page.wait_for_function(
            "() => { const t = document.getElementById('lv-mode-trigger');"
            " const c = document.getElementById('lv-queue-name');"
            " return t && t.checkVisibility() && c"
            " && /ranked solo/i.test(c.textContent); }",
            timeout=10_000,
        )
        page.evaluate("document.fonts.ready.then(() => true)")
        page.add_style_tag(content=_SHEET)
        page.click("#lv-mode-trigger")
        page.mouse.move(2, 2)
        rest = page.evaluate(_MEASURE, "")
        page.hover(f'#lv-mode-menu .lq-mode-item[data-qid="{_HOVER_QID}"]')
        hover = page.evaluate(_MEASURE, _HOVER_QID)
        page.keyboard.press("Escape")
        page.click("#lv-lane-primary")
        page.mouse.move(2, 2)
        lanes = page.evaluate(_MEASURE, "")
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, errors[:3]
    return {"rest": rest, "hover": hover, "lanes": lanes}


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
def test_menu_marks_the_queue_the_card_names(theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["rest"]
    assert got["theme"] == theme, got["theme"]
    assert got["menuOpen"], "the mode menu did not open"
    want = _fixture_qid()
    assert want != _HOVER_QID
    assert got["current"] == [want], (
        f"{theme}: menu marks {got['current']} current, the card's queue is {want}")


@pytest.mark.parametrize("theme", _THEMES)
def test_open_menu_text_reaches_its_floor(theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["rest"]
    rows = got["menu"]
    # Trigger + 4 section heads + 11 queue items: an empty read cannot pass.
    assert len(rows) == 16, [r["text"] for r in rows]
    assert any("is-current" in r["cls"] for r in rows), rows
    bad = _shortfalls(rows, "rest")
    assert not bad, f"{theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_hovered_item_reaches_aa_and_hover_moves_the_fill(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)
    h = got["hover"]["hover"]
    assert h["hovered"], h
    assert "is-current" not in h["cls"], h
    bad = _shortfalls([h], "hover")
    assert not bad, f"{theme}: " + "; ".join(bad)
    rest = [r for r in got["rest"]["menu"] if r["qid"] == _HOVER_QID]
    assert len(rest) == 1, rest
    # An inert hover would pass the contrast check trivially.
    assert max(abs(a - b) for a, b in zip(rest[0]["fill"][:3], h["fill"][:3])) > 4 \
        or rest[0]["fill"][3] != h["fill"][3], (theme, rest[0]["fill"], h["fill"])


@pytest.mark.parametrize("theme", _THEMES)
def test_current_item_keeps_its_clock_frame_and_hue(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["rest"]
    cur = [r for r in got["menu"] if "is-current" in r["cls"]]
    assert len(cur) == 1, cur
    # The current queue still reads by its --clock frame ...
    assert cur[0]["border"] == got["clock"], (theme, cur[0]["border"], got["clock"])
    # ... and by a label colour no plain item carries.
    assert cur[0]["fg"][:3] != got["plain"]["fg"][:3], (theme, cur[0], got["plain"])


@pytest.mark.parametrize("theme", _THEMES)
def test_open_lane_popup_text_reaches_its_floor(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme)["lanes"]
    assert got["popupOpen"], "the lane popup did not open"
    assert not got["menuOpen"], "the mode menu stayed open under the popup"
    rows = got["popup"]
    # The label names the focused (current) lane: one non-empty text line.
    assert [r["id"] for r in rows] == ["lv-lane-popup-label"], rows
    assert rows[0]["text"], rows
    bad = _shortfalls(rows, "lanes")
    assert not bad, f"{theme}: " + "; ".join(bad)
