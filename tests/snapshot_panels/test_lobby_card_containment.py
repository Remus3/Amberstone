"""
tests/snapshot_panels/test_lobby_card_containment.py
The four Pre-Game Lobby cards contain their own content, and the lobby fits
the 1920x920 baseline without a scroll (session 144, lane uiux, RM-1006).

RM-1006 was filed as "the Friends card overflows its own box by 1px": its
scrollHeight read 381 against a clientHeight of 380. Re-measured in headless
Chromium on /?ui_mock=1#lobby, that 1px is NOT content. Every lobby card shows
it (queue 390/389, party 390/389, mains 381/380, friends 381/380), and with
`.lobby-view-card::after` hidden all four read equal. The ::after is the gold
corner bracket in web/css/panels/header.css, absolutely placed at
`bottom: -1px` so it paints over the card's own 1px border. scrollHeight
counts from the padding edge, so a bracket sitting on the border reads as a
1px overflow while it never leaves the card's border box. The in-flow content
of the Friends card ends exactly at its content-box bottom (search row bottom
373 = 382 - 1 border - 8 padding).

Rule pinned here, by layout value (a grep cannot see either):
- every in-flow child of every lobby card ends inside the card's content box
  (bottom border and bottom padding subtracted), at 1920x920 and at the
  923x1280 companion width;
- whatever reaches past a card's padding box stays inside its border box
  (scrollHeight - clientHeight <= the bottom border width), so the bracket
  stays decorative and nothing escapes the card;
- at the 1920x920 baseline neither #view-lobby nor the document scrolls
  vertically (the RM-979 residue: that guard measured 1920x920 for the
  search row only and never asserted the page still fits).

The companion width is NOT pinned for scroll: measured this cycle,
#view-lobby scrolls there (1217 against 1186) because the 1-col stack of four
cards is taller than the view - a layout question filed for later, not a
containment defect.

Drive path: /?ui_mock=1#lobby, the same recipe and landing signal as
test_lobby_view.py (#lv-queue-name leaves its "-" placeholder).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_VIEWPORTS = {
    "baseline": {"width": 1920, "height": 920},
    "companion": {"width": 923, "height": 1280},
}

_READ = """() => {
  const cards = [...document.querySelectorAll("#view-lobby .lobby-view-card")];
  const view = document.getElementById("view-lobby");
  return {
    cards: cards.map((card) => {
      const cs = getComputedStyle(card);
      const r = card.getBoundingClientRect();
      const contentBottom = r.bottom - parseFloat(cs.borderBottomWidth)
        - parseFloat(cs.paddingBottom);
      const kids = [...card.children]
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
        cls: card.className,
        contentBottom,
        kids,
        overflowY: card.scrollHeight - card.clientHeight,
        borderBottom: parseFloat(cs.borderBottomWidth),
      };
    }),
    viewScroll: view.scrollHeight - view.clientHeight,
    docScroll: document.documentElement.scrollHeight - window.innerHeight,
  };
}"""


@pytest.fixture(scope="module", params=sorted(_VIEWPORTS))
def lobby_cards(request, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport=_VIEWPORTS[request.param]
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const q = document.querySelector('#lv-queue-name');"
            " const t = q ? q.textContent.trim() : '';"
            " return t !== '' && t !== '-'; })()",
            timeout=10_000,
        )
        # Measured: right at the landing signal the view head is 44px and
        # #view-lobby reads 854/828 (a 26px scroll); ~100ms later the head
        # is 40px and the view 827/827. Wait for the fonts and two frames
        # so the settled page is measured, not the first paint.
        page.evaluate(
            "document.fonts.ready.then(() => new Promise((ok) =>"
            " requestAnimationFrame(() => requestAnimationFrame(ok))))"
        )
        yield request.param, page.evaluate(_READ), errors
    finally:
        page.close()
        ctx.close()


def test_all_four_lobby_cards_are_measured(lobby_cards):
    # Anchor: an empty enumeration would pass every containment check below.
    _, r, errors = lobby_cards
    names = sorted(c["cls"].split()[-1] for c in r["cards"])
    assert names == [
        "lobby-view-card-friends",
        "lobby-view-card-mainchamps",
        "lobby-view-card-party",
        "lobby-view-card-queue",
    ], r
    assert all(c["kids"] for c in r["cards"]), r
    assert errors == []


def test_every_card_child_ends_inside_the_card_content_box(lobby_cards):
    _, r, _ = lobby_cards
    for card in r["cards"]:
        for kid in card["kids"]:
            assert kid["bottom"] <= card["contentBottom"] + 0.5, (card, kid)


def test_nothing_escapes_a_card_border_box(lobby_cards):
    _, r, _ = lobby_cards
    for card in r["cards"]:
        assert card["overflowY"] <= card["borderBottom"], card


def test_lobby_fits_the_baseline_without_vertical_scroll(lobby_cards):
    vp, r, _ = lobby_cards
    if vp != "baseline":
        pytest.skip("companion width scroll is a filed layout question")
    assert r["viewScroll"] <= 0, r
    assert r["docScroll"] <= 0, r
