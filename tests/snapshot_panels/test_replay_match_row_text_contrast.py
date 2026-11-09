"""
tests/snapshot_panels/test_replay_match_row_text_contrast.py
S144-U-242 (s144 uiux): every text line of the Replay view's RECENT
MATCHES rows (#replay-match-list .replay-match-row: the W / L / "-"
verdict, the champion, the queue label and the date - duration - patch
line) reaches its WCAG 1.4.3 floor in all six themes, on the row at rest,
under a real mouse hover and on the picked (.active) row.

S144-U-241's sweep (cycle 236) filed the lost-row "L" (.replay-match-
verdict.lost, --bad, 900 weight at --fs-sm) as an AA defect in two themes.
This test measures the whole row, each line composited over the surface it
actually sits on, so a fix to one line cannot hide another.

The rows come from web/data/ui_mock/replay.json under /?ui_mock=1#replay:
four SYNTHETIC matches (RM-906: MOCK_* ids), one won, one lost, one with no
tracked result and one more won, so every verdict class renders.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_ROWS = "#replay-match-list .replay-match-row"

_MEASURE = """async (state) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const line = (el) => {
    const cs = getComputedStyle(el);
    const s = surface(el);
    const btn = el.closest('.replay-match-row');
    return {row: btn ? btn.dataset.matchId : '',
            rowCls: btn ? String(btn.className) : '',
            cls: String(el.className), text: el.textContent.trim(),
            fg: s ? over(rgba(cs.color), s) : null, bg: s,
            px: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10)};
  };
  const rows = [...document.querySelectorAll('__ROWS__')];
  const pick = state === 'rest' ? rows
    : rows.filter((r) => state === 'hover' ? r.matches(':hover')
                                           : r.classList.contains('active'));
  const texts = pick.flatMap((r) => [...r.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(line));
  return {theme: document.documentElement.dataset.theme || 'hextech',
          rows: rows.length, picked: pick.length, texts};
}""".replace("__ROWS__", _ROWS)


def _large(row) -> bool:
    return row["px"] >= 24 or (row["px"] >= 18.66 and row["weight"] >= 700)


def _measure(mock_server, pw_browser, theme):
    """Rest reads of the four rows, then each row under a real mouse hover
    and each row picked (.active, mouse moved away), one page per theme."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    got = {}
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#replay",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            f"() => document.querySelectorAll('{_ROWS}').length === 4",
            timeout=10_000,
        )
        page.add_style_tag(content=_SHEET)
        page.mouse.move(0, 0)
        got["rest"] = page.evaluate(_MEASURE, "rest")
        rows = page.locator(_ROWS)
        got["hover"], got["active"] = [], []
        for i in range(4):
            rows.nth(i).hover()
            got["hover"].append(page.evaluate(_MEASURE, "hover"))
        for i in range(4):
            rows.nth(i).click()
            page.wait_for_function(
                "(i) => document.querySelectorAll("
                f"'{_ROWS}')[i].classList.contains('active')",
                arg=i, timeout=10_000,
            )
            page.mouse.move(0, 0)
            got["active"].append(page.evaluate(_MEASURE, "active"))
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _got(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


def _low(texts):
    low = []
    for r in texts:
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        assert r["px"] >= 14, f"{r['cls']} {r['text']!r} at {r['px']}px"
        floor = 3.0 if _large(r) else 4.5
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < floor:
            low.append((r["row"], r["cls"], r["text"], round(ratio, 2), floor))
    return low


@pytest.mark.parametrize("theme", _THEMES)
def test_rows_at_rest_reach_their_floor(theme, measured, mock_server,
                                        pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)["rest"]
    assert got["theme"] == theme, "theme did not apply"
    assert got["rows"] == 4, got["rows"]
    # Anchor: 4 rows x 4 lines (verdict, champion, queue, date line); an
    # empty sweep would pass.
    assert len(got["texts"]) == 4 * 4, [r["text"] for r in got["texts"]]
    verdicts = sorted(r["text"] for r in got["texts"]
                      if "replay-match-verdict" in r["cls"])
    assert verdicts == ["-", "L", "W", "W"], verdicts
    low = _low(got["texts"])
    assert not low, f"{theme} rest: {low}"


def _each_row(reads, state):
    texts = []
    for got in reads:
        assert got["picked"] == 1, f"{state}: not exactly one row in state"
        assert len(got["texts"]) == 4, [r["text"] for r in got["texts"]]
        assert len({r["row"] for r in got["texts"]}) == 1, got["texts"]
        texts += got["texts"]
    # Anchor: each of the four rows took the state once, in list order.
    ids = [g["texts"][0]["row"] for g in reads]
    assert len(set(ids)) == 4, ids
    return texts


@pytest.mark.parametrize("theme", _THEMES)
def test_hovered_rows_reach_their_floor(theme, measured, mock_server,
                                        pw_browser):
    reads = _got(measured, mock_server, pw_browser, theme)["hover"]
    low = _low(_each_row(reads, "hover"))
    assert not low, f"{theme} hover: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_picked_rows_reach_their_floor(theme, measured, mock_server,
                                       pw_browser):
    reads = _got(measured, mock_server, pw_browser, theme)["active"]
    low = _low(_each_row(reads, "active"))
    assert not low, f"{theme} active: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_verdicts_keep_their_result_hue(theme, measured, mock_server,
                                        pw_browser):
    """The lift must not flatten the result: L stays red-dominant and W
    green-dominant, and the champion stays the brightest line of its row."""
    got = _got(measured, mock_server, pw_browser, theme)["rest"]
    for r in got["texts"]:
        if "replay-match-verdict" not in r["cls"]:
            continue
        red, green = r["fg"][0], r["fg"][1]
        if r["text"] == "L":
            assert red > green + 40, (theme, r)
        elif r["text"] == "W":
            assert green > red + 20, (theme, r)
    # The champion stays the brightest line of its row in every state: the
    # lifted "L" and the stepped-up hover / picked queue label sit under it.
    reads = [got] + list(measured[theme]["hover"]) + list(
        measured[theme]["active"])
    checked = 0
    for read in reads:
        by_row = {}
        for r in read["texts"]:
            by_row.setdefault(r["row"], []).append(r)
        for lines in by_row.values():
            champ = [r for r in lines if "replay-match-champ" in r["cls"]]
            assert len(champ) == 1, lines
            for r in lines:
                if r["text"] == "L" or "replay-match-queue" in r["cls"]:
                    assert _lum(r["fg"]) < _lum(champ[0]["fg"]), (theme, r)
                    checked += 1
    # Anchor: rest (1 L + 4 queues) + 4 hovers + 4 picks (1 L + 1 queue
    # where the lost row took the state, 1 queue on each other row).
    assert checked == 5 + 5 + 5, checked
