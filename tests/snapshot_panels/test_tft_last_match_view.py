"""
tests/snapshot_panels/test_tft_last_match_view.py
The TFT Post Game Review rendered from a fixture (session 134, lane uiux,
RM-952).

web/js/panels/last_match.js _renderTftLastMatch (RM-616 / s134 QA D4) had
only a grep contract (tests/test_last_match_tft_branch_rm616.py) and no
?ui_mock=1 path: _lmMockUrl mapped sr / aram / arena only, so the TFT card
could be audited only right after a real TFT game. ?ui_mock=1&mode=tft now
loads web/data/ui_mock/last_match_tft.json - the payload RC really served for
the operator's newest TFT game (game_id blanked) - and this file pins what the
card renders from it in real headless Chromium.

Defect found by this render and fixed in the same slice: that real payload
carries set_number null and set_core_name "TFTSet18", and the hero sub-line
printed the raw client token ("TFT - TFTSet18"). It now reads "TFT - Set 18".

Drive path: /?ui_mock=1&mode=tft#last-match with an empty /api/state. The
#last-match hash routes the PGR view, its activate hook calls
fetchAndRenderLastMatch, and the TFT branch never touches #lm-mode-tag, so the
landing signal is the .lm-tft-place node inside #lm-tft.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_HEADINGS = ["Final board", "Traits (unit counts)", "Augments", "HP curve", "Lobby"]
_FACTS = [
    ["Final HP", "0"], ["Level", "-"], ["Gold left", "-"],
    ["Rounds", "-"], ["Duration", "36:09"],
]

_READ = """() => {
  const host = document.getElementById("lm-tft");
  const body = document.getElementById("lm-body");
  const txt = (el) => (el ? el.textContent.trim() : null);
  const all = (sel) => Array.from(host.querySelectorAll(sel));
  const sizes = all("*").filter((el) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) return true;
    }
    return false;
  }).map((el) => [el.className || el.tagName, parseFloat(getComputedStyle(el).fontSize)]);
  return {
    hostHidden: host.hidden,
    hostDisplay: getComputedStyle(host).display,
    bodyDisplay: getComputedStyle(body).display,
    meta: txt(document.getElementById("lm-meta")),
    place: txt(host.querySelector(".lm-tft-place")),
    top: host.querySelector(".lm-tft-hero").dataset.top,
    sub: txt(host.querySelector(".lm-tft-sub")),
    facts: all(".lm-tft-fact").map((f) => [
      txt(f.querySelector(".lm-tft-fact-label")),
      txt(f.querySelector(".lm-tft-fact-value")),
    ]),
    headings: all(".lm-tft-section h3").map(txt),
    units: all(".lm-tft-board > .lm-tft-unit").map((u) => [
      txt(u.querySelector(".lm-tft-unit-name")),
      txt(u.querySelector(".lm-tft-unit-meta")),
      txt(u.querySelector(".lm-tft-unit-items")),
    ]),
    traits: all(".lm-tft-traits > .lm-tft-trait").map(txt),
    notes: all(".lm-tft-note").map(txt),
    lobby: all(".lm-tft-lobby > li").map((li) => [li.dataset.local, txt(li)]),
    text: host.textContent,
    sizes,
    placeSize: parseFloat(getComputedStyle(host.querySelector(".lm-tft-place")).fontSize),
    hostOverflow: host.scrollWidth - host.clientWidth,
    pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""


@pytest.fixture
def tft_pgr(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=tft#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const h = document.getElementById('lm-tft');"
            " return !!(h && !h.hidden && h.querySelector('.lm-tft-place')); })()",
            timeout=10_000,
        )
        yield page.evaluate(_READ), errors
    finally:
        page.close()
        ctx.close()


def test_tft_mock_card_replaces_the_league_body(tft_pgr):
    r, errors = tft_pgr
    assert r["hostHidden"] is False and r["hostDisplay"] != "none"
    assert r["bodyDisplay"] == "none", "the League PGR body must collapse under the TFT card"
    assert r["meta"].startswith("TFT - "), r["meta"]
    assert not errors, errors[:3]


def test_tft_hero_reads_placement_and_set_never_the_raw_token(tft_pgr):
    r, _ = tft_pgr
    assert r["place"] == "3rd of 8"
    assert r["top"] == "1", "3rd of 8 is a top-4 finish"
    # RM-952: set_number is null in the real payload; the label comes from
    # set_core_name "TFTSet18" and must not print the client token.
    assert r["sub"] == "TFT - Set 18", r["sub"]
    assert "TFTSet" not in r["text"]


def test_tft_facts_board_traits_and_lobby_from_the_real_payload(tft_pgr):
    r, _ = tft_pgr
    assert r["facts"] == _FACTS
    assert r["headings"] == _HEADINGS
    assert len(r["units"]) == 9
    assert r["units"][0] == ["Ashe", "2-star - 5 cost",
                             "Infinity Edge, Last Whisper, Guinsoo's Rageblade"]
    assert r["units"][1] == ["Taric", "2-star - 5 cost", "no items"]
    assert len(r["traits"]) == 13 and r["traits"][0] == "Blossom 3"
    assert r["notes"] == [
        "Not recorded by the client for this game.",
        "Not recorded yet - per-round history is not captured.",
    ]
    assert len(r["lobby"]) == 8
    local = [row for row in r["lobby"] if row[0] == "1"]
    assert len(local) == 1 and local[0][1].startswith("3rd (you) - Ashe, Taric")
    assert r["lobby"][0][1].startswith("1st - Alistar, LeBlanc")


def test_tft_card_typography_hierarchy_and_no_overflow(tft_pgr):
    r, _ = tft_pgr
    # TYPOGRAPHY: no rendered text below the --fs-xs floor (16px).
    small = [s for s in r["sizes"] if s[1] < 16]
    assert not small, small[:5]
    # HIERARCHY: the placement is the largest text in the card.
    assert all(r["placeSize"] >= s[1] for s in r["sizes"]), r["placeSize"]
    # STRUCTURE: no horizontal overflow at the 1920 baseline.
    assert r["hostOverflow"] <= 0 and r["pageOverflow"] <= 0
