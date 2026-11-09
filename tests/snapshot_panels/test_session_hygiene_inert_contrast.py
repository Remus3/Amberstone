"""
tests/snapshot_panels/test_session_hygiene_inert_contrast.py
S144-U-239 (s144 uiux): every text line in the Session view's SHOULD I
QUEUE readiness card (#session-hygiene-card) reaches its WCAG text floor
(1.4.3) on its resolved surface in all six themes, with ancestor opacity
folded in: the factor list at the 1920x1080 baseline and the 923x1280
companion window, the whole card in four routed readiness states - and an
inert factor (contributed=false, "no data") still reads quieter than a
live one.

THE DEFECTS. MEASURED headless under /?ui_mock=1#session before the fix
(web/css/panels/session_hygiene.css):
- the inert factor row (`.sh-factor.is-inert`) dimmed by row opacity 0.6,
  which sank its --text-faint note ("next game is #3 this session") and
  "no data" count (16 px / 400) to 2.57:1 hextech - 2.66 moonlit, and its
  "-" value in --signal-dim (18 px / 400, not large text) to 3.27 arcane -
  3.47 terminal. The shipped ui_mock fixture has ALL FOUR factors inert, so
  the default mock render showed four sub-floor rows. S144-U-201's Session
  sweep (test_session_text_contrast.py) read colours without folding
  opacity, so it passed them;
- three text uses of bare --signal-bad, none in the shipped fixture (it is
  unknown / LOW / no flags / no live factor): a live negative factor delta
  (18 px / 400), the RED light chip (16 px / 700) and an override flag line
  (16 px / 400) - each 4.44 arcane, 4.48 moonlit (4.53 - 5.35 elsewhere).

THE FIX: the inert row drops the opacity; its factor name steps down from
--text to --text-dim (the inert-vs-live cue), the note / count keep
--text-faint and the value keeps --signal-dim, each at full strength. The
three red text uses take the RM-1550 lift (70 percent red toward --text in
oklab); the RED chip border keeps the bare red. The 28 px / 700 score
keeps bare red: WCAG large text, 3:1 floor, 4.44 or more.

The session fixture is routed with two LIVE factors (synthetic deltas) and
two inert ones in every scenario, so both row kinds are on the page.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_ROOT = Path(__file__).resolve().parents[2]
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 1080), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_AA_LARGE = 3.0
_SHEET = "*, *::before, *::after { transition: none !important; }"

_FACTORS = [
    {"factor": "session_position", "n": 14, "delta_pts": 3.2,
     "contributed": True, "note": "next game is #3 this session"},
    {"factor": "rust", "n": 9, "delta_pts": -2.1,
     "contributed": True, "note": "0.4h since last game"},
    {"factor": "hour", "n": 1, "delta_pts": 0.0,
     "contributed": False, "note": "local hour 16"},
    {"factor": "weekday", "n": 3, "delta_pts": 0.0,
     "contributed": False, "note": "Sat"},
]


# Each scenario overrides the shipped fixture's readiness block. "mixed" is
# the factor list above with the shipped unknown head; the three verdict
# scenarios paint the score, light, confidence and flag states the shipped
# fixture never reaches (it is unknown / LOW / no flags), so their colours
# are read too. Synthetic values only (RM-906).
_SCENARIOS = {
    "mixed": {},
    "red": {"score": 31, "state": "red", "confidence": "HIGH",
            "flags": [{"kind": "override", "flag": "tilt",
                       "note": "3 losses in a row - the light is capped"},
                      {"kind": "odds", "flag": "late",
                       "note": "after 01:00 you win 6 pts less"}]},
    "yellow": {"score": 44, "state": "yellow", "confidence": "MED",
               "flags": [{"kind": "odds", "flag": "rust",
                          "note": "first game in 3 days"}]},
    "green": {"score": 68, "state": "green", "confidence": "HIGH"},
}


def _session_fixture(scenario: str) -> str:
    path = _ROOT / "web" / "data" / "ui_mock" / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    readiness = data["session_hygiene"]["readiness"]
    readiness["factors"] = _FACTORS
    readiness.update(_SCENARIOS[scenario])
    return json.dumps(data)


_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const line = (el) => {
    const cs = getComputedStyle(el);
    const fg = rgba(cs.color);
    fg[3] *= alpha(el);
    const s = surface(el);
    const own = [...el.childNodes]
      .filter((n) => n.nodeType === 3).map((n) => n.textContent).join('');
    return {cls: String(el.className), text: own.trim(), alpha: alpha(el),
            fg: s ? over(fg, s) : null, bg: s,
            size: parseFloat(cs.fontSize),
            weight: parseInt(cs.fontWeight, 10)};
  };
  const card = document.getElementById('session-hygiene-card');
  const rows = [...card.querySelectorAll('.sh-factor')]
    .filter((r) => r.checkVisibility());
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    rows: rows.map((r) => ({
      inert: r.classList.contains('is-inert'),
      opacity: parseFloat(getComputedStyle(r).opacity),
      lines: [...r.querySelectorAll('*'), r]
        .filter((e) => [...e.childNodes].some(
          (n) => n.nodeType === 3 && n.textContent.trim()))
        .filter((e) => e.checkVisibility())
        .map(line),
      name: line(r.querySelector('.sh-factor-name')),
    })),
    card: [...card.querySelectorAll('*')]
      .filter((e) => [...e.childNodes].some(
        (n) => n.nodeType === 3 && n.textContent.trim()))
      .filter((e) => e.checkVisibility())
      .map(line),
  };
}"""


def _measure(mock_server, pw_browser, theme, vp, scenario):
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    body = _session_fixture(scenario)
    page.route("**/data/ui_mock/session.json", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#session",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.add_style_tag(content=_SHEET)
        page.wait_for_function(
            "document.querySelectorAll('#session-hygiene-card .sh-factor')"
            f".length === {len(_FACTORS)}",
            timeout=10_000)
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp, scenario="mixed"):
    key = (theme, vp, scenario)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp,
                                 scenario)
    return measured[key]


def _large(row) -> bool:
    return row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_both_row_kinds_render(theme, vp, measured, mock_server, pw_browser):
    rows = _get(measured, mock_server, pw_browser, theme, vp)["rows"]
    assert [r["inert"] for r in rows] == [False, False, True, True], rows
    for r in rows:
        texts = {ln["text"] for ln in r["lines"]}
        if r["inert"]:
            assert {"-", "no data"} <= texts, r
        else:
            assert any(t.startswith("n=") for t in texts), r


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_factor_line_reaches_its_floor(theme, vp, measured,
                                             mock_server, pw_browser):
    rows = _get(measured, mock_server, pw_browser, theme, vp)["rows"]
    lines = [ln for r in rows for ln in r["lines"]]
    assert len(lines) >= 4 * len(rows), lines
    bad = []
    for ln in lines:
        assert ln["bg"] is not None, (theme, ln)
        floor = _AA_LARGE if _large(ln) else _AA
        ratio = _ratio(ln["fg"], ln["bg"])
        if ratio < floor:
            bad.append(f"{ln['cls']} {ln['text']!r} {ratio:.2f}:1 "
                       f"(alpha {ln['alpha']:.2f}) under {floor}")
    assert not bad, f"{theme} {vp}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_inert_name_reads_quieter_than_live(theme, measured, mock_server,
                                            pw_browser):
    rows = _get(measured, mock_server, pw_browser, theme,
                _VIEWPORTS[0])["rows"]
    live = [_ratio(r["name"]["fg"], r["name"]["bg"])
            for r in rows if not r["inert"]]
    inert = [_ratio(r["name"]["fg"], r["name"]["bg"])
             for r in rows if r["inert"]]
    assert live and inert
    assert max(inert) < min(live), (theme, live, inert)
    assert min(inert) >= _AA, (theme, inert)


def _floor_failures(lines):
    bad = []
    for ln in lines:
        assert ln["bg"] is not None, ln
        floor = _AA_LARGE if _large(ln) else _AA
        ratio = _ratio(ln["fg"], ln["bg"])
        if ratio < floor:
            bad.append(f"{ln['cls']} {ln['text']!r} {ratio:.2f}:1 "
                       f"(alpha {ln['alpha']:.2f}) under {floor}")
    return bad


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
@pytest.mark.parametrize("theme", _THEMES)
def test_every_card_line_reaches_its_floor(theme, scenario, measured,
                                           mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0],
               scenario)
    lines = got["card"]
    texts = {ln["text"] for ln in lines}
    assert "SHOULD I QUEUE" in texts, texts
    want = {"mixed": "UNKNOWN", "red": "RED", "yellow": "YELLOW",
            "green": "GREEN"}[scenario]
    assert want in texts, (scenario, texts)
    if scenario == "red":
        assert any("capped" in t for t in texts), texts
    bad = _floor_failures(lines)
    assert not bad, f"{theme} {scenario}: " + "; ".join(bad)
