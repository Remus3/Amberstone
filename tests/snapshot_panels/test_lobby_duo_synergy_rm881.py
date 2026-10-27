"""
tests/snapshot_panels/test_lobby_duo_synergy_rm881.py
RM-881 (b) (QA23): the lobby re-fires duo synergy when the party size
reaches 2.

Headless render of the Pre-Game Lobby under ui_mock (the ui_mock lobby
fixture is a party of 3), driven through the same harness as
test_lobby_view.py. Under ui_mock the controller in
web/js/panels/lobby_duo_synergy.js reads the page's own
web/data/ui_mock/duo_synergy.json instead of /api/duo-synergy; the request
contract (party size, my_role, one fetch per party episode, degraded
states) is pinned by web/js/panels/lobby_duo_synergy.test.mjs.

The assertions are the 5-phase UI-fixture audit on the rendered block:
STRUCTURE (two labeled rows of four cells inside the PARTY card, the card
still inside the 1920x1080 viewport, no cell spilling out of the card),
TYPOGRAPHY (no text under --fs-xs, 16 px), HIT-TARGETS (the block is
read-only: no focusable control in it), ASCII (rendered text), HIERARCHY
(title, then BOT, then SUPPORT, top to bottom). It also checks the 2 s
lobby refresh does not re-fire the fetch for the same party.
"""
import json
from pathlib import Path

from tests.snapshot_panels.test_lobby_view import _open_lobby

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = json.loads(
    (ROOT / "web" / "data" / "ui_mock" / "duo_synergy.json")
    .read_text(encoding="utf-8"))
SCREENSHOTS = Path(__file__).parent / "screenshots"

_MEASURE = """() => {
  const box = document.getElementById('lv-duo-synergy');
  const card = box && box.closest('.lobby-view-card-party');
  const r = (e) => { const b = e.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom, left: b.left, right: b.right}; };
  const texts = [];
  if (box) {
    const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walk.nextNode())) {
      if (!n.textContent.trim()) continue;
      const cs = getComputedStyle(n.parentElement);
      texts.push({text: n.textContent,
                  px: parseFloat(cs.fontSize),
                  cls: n.parentElement.className});
    }
  }
  return {
    hidden: !box || box.hidden,
    visible: !!box && box.offsetParent !== null,
    rows: box ? box.querySelectorAll('.lv-duosyn-row').length : 0,
    cells: box ? [...box.querySelectorAll('.lv-duosyn-cell')].map((c) => ({
      name: c.querySelector('.lv-duosyn-name').textContent,
      rect: r(c)})) : [],
    roles: box ? [...box.querySelectorAll('.lv-duosyn-role')]
      .map((e) => ({text: e.textContent, top: r(e).top})) : [],
    title: box && box.querySelector('.lv-duosyn-title')
      ? {text: box.querySelector('.lv-duosyn-title').textContent,
         top: r(box.querySelector('.lv-duosyn-title')).top} : null,
    focusables: box ? box.querySelectorAll(
      'a,button,input,select,textarea,[tabindex]').length : -1,
    card: card ? r(card) : null,
    box: box ? r(box) : null,
    vh: window.innerHeight,
    duo: performance.getEntriesByType('resource').map((e) => e.name)
      .filter((u) => u.includes('duo_synergy.json')
        || u.includes('/api/duo-synergy')),
    texts,
  };
}"""


def test_lobby_duo_synergy_renders_at_party_size_2_plus(
        mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll('#lv-duo-synergy .lv-duosyn-cell')"
            ".length === 8",
            timeout=10_000,
        )
        # Let the 2 s lobby refresh run past at least one more tick.
        page.wait_for_timeout(2_500)
        m = page.evaluate(_MEASURE)
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator(".lobby-view-card-party").screenshot(
            path=str(SCREENSHOTS / "lobby_duo_synergy_rm881.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [lobby duo]: {errors[:3]}"

    # STRUCTURE
    assert not m["hidden"] and m["visible"], m
    assert m["rows"] == 2, m
    want = [c["champ"] for c in FIXTURE["top_row"] + FIXTURE["bottom_row"]]
    assert [c["name"] for c in m["cells"]] == want
    card, box = m["card"], m["box"]
    assert card["top"] <= box["top"] and box["bottom"] <= card["bottom"] + 1
    for c in m["cells"]:
        assert card["left"] - 1 <= c["rect"]["left"], c
        assert c["rect"]["right"] <= card["right"] + 1, c
    assert card["bottom"] <= m["vh"], (card, m["vh"])

    # TYPOGRAPHY: nothing under the --fs-xs floor.
    assert m["texts"], m
    small = [t for t in m["texts"] if t["px"] < 16]
    assert not small, small

    # HIT-TARGETS: read-only block.
    assert m["focusables"] == 0, m

    # ASCII
    for t in m["texts"]:
        assert t["text"].isascii(), t

    # HIERARCHY: title above BOT above SUPPORT.
    assert m["title"]["text"] == "DUO PICKS"
    roles = m["roles"]
    assert [x["text"] for x in roles] == ["BOT", "SUPPORT"]
    assert m["title"]["top"] < roles[0]["top"] < roles[1]["top"]

    # One fetch for this party episode, the fixture not the live route.
    # Resource Timing covers the fetch even though it fired during goto.
    duo = m["duo"]
    assert len(duo) == 1, duo
    assert duo[0].endswith("/data/ui_mock/duo_synergy.json"), duo
