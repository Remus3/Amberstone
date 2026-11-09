"""
tests/snapshot_panels/test_overlay_empty_caption_contrast.py
S144-U-272 (s144 uiux): the in-game overlay's fight-model pane caption
("OVERLAY", .ovset-cap) and its empty line ("resolving fight model..." /
"no items rank under this fight model", .ovds-empty), and the Active Match
empty notices (.am-empty: "Awaiting coach...", "DS engine ranks...",
"Static mode map...", and the TFT / fallback lines active_match.js writes),
reach the WCAG 1.4.3 AA text floor (4.5:1) on their pane in all six themes,
in the ?overlay=1 shell and on the dashboard.

THE DEFECT. MEASURED headless (private static server over web/, 1920x1080,
?overlay=1&ui_mock=1&mode=<sr|aram|arena|complete>#active-match, six
themes) before the fix: all three rules painted --faint / --text-faint, which
reads 4.46 hextech, 4.39 ember, 4.48 moonlit and 4.31 arcane on the overlay
pane surface - the same 4.31 - 4.48 S144-U-215 and S144-U-243 measured for
--text-faint on the Active Match panes. terminal and bloodmoon passed.

THE FIX (web/css/panels/overlay_ds_controls.css,
web/css/panels/active_match.css). The three rules take --text-dim, the
S144-U-215 / S144-U-243 empty-state tier (the TFT board and lobby empty lines
already use it). The caption takes the same tone as the row labels under it
(.ovset-row > span, --dim); its uppercase and letter-spacing still mark it as
the strip's caption. Sizes are unchanged.

Checked per theme and shell: every rendered line reaches 4.5:1 at opacity 1
down its ancestor chain, is --text-dim, and reads dimmer than full --text on
the same surface; the caption is no brighter than the row labels it heads.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"

# The surfaces measured, each (query, ready predicate, selectors read).
# "ovds": the overlay-only fight-model pane under ?ui_mock=1. Its empty line
# is the in-flight or the unrankable copy, so it is matched by class and its
# string checked against the two overlay_ds_controls.js writes.
# "dashboard" / "overlay": no mock and an empty state envelope, the screen
# before the first tick. The call pane says "no in-game session", and the
# static .am-empty placeholders (web/index.html) stay in the BUILD and MAP
# panes; the overlay shell hides the MAP pane, so it shows the BUILD one only.
_OVDS_TEXTS = {"resolving fight model...",
               "no items rank under this fight model"}
_EMPTY_EXPECT = {
    "dashboard": ["DS engine ranks", "Static mode map"],
    "overlay": ["DS engine ranks"],
}


def _empty_ready(shell):
    return ("() => [...document.querySelectorAll('#view-active-match"
            " .am-empty')].filter((e) => e.checkVisibility()).length"
            f" >= {len(_EMPTY_EXPECT[shell])}")


_SURFACES = {
    "ovds": (
        "?ui_mock=1&mode=sr&overlay=1",
        "() => { const e = document.querySelector('#ovds-rows .ovds-empty');"
        " return !!(e && e.checkVisibility()); }",
        ["#ovds-body .ovset-cap", "#ovds-rows .ovds-empty",
         "#ovds-body .ovset-row > span"],
    ),
    "dashboard": ("?mode=sr", _empty_ready("dashboard"),
                  ["#view-active-match .am-empty"]),
    "overlay": ("?mode=sr&overlay=1", _empty_ready("overlay"),
                ["#view-active-match .am-empty"]),
}

_MEASURE = """async (sels) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const root = getComputedStyle(document.documentElement);
  const tok = (name) => rgba(root.getPropertyValue(name).trim());
  const text = tok('--text');
  const out = [];
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      if (!el.checkVisibility()) continue;
      const cs = getComputedStyle(el);
      const fg = rgba(cs.color);
      const a = alpha(el);
      const s = surface(el);
      const faded = fg.slice(); faded[3] *= a;
      out.push({sel, text: el.textContent.trim(), alpha: a, color: fg,
                fg: s ? over(faded, s) : null, bg: s,
                full: s ? over(text, s) : null,
                size: parseFloat(cs.fontSize)});
    }
  }
  return {theme: document.documentElement.dataset.theme || 'hextech',
          shell: document.body.dataset.shell || '',
          dim: tok('--text-dim'), lines: out};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, surface):
    query, ready, sels = _SURFACES[surface]
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/{query}&theme={theme}#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.wait_for_function(ready, timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE, sels)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, surface):
    key = (theme, surface)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, surface)
    return measured[key]


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _check(got, lines, label):
    bad = []
    for ln in lines:
        assert ln["bg"] is not None, (label, ln)
        assert ln["alpha"] == 1, (label, ln["sel"], ln["alpha"])
        ratio = _ratio(ln["fg"], ln["bg"])
        if ratio < _AA:
            bad.append(f"{ln['sel']} {ln['text'][:30]!r} {ratio:.2f}:1")
    assert not bad, f"{label}: " + "; ".join(bad)
    for ln in lines:
        # The notice tier: --text-dim, quieter than full --text.
        assert ln["color"] == got["dim"], (label, ln["sel"], ln["color"],
                                           got["dim"])
        assert _lum(ln["fg"]) < _lum(ln["full"]), (label, ln)


@pytest.mark.parametrize("theme", _THEMES)
def test_overlay_fight_model_caption_and_empty_line_reach_aa(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, "ovds")
    assert got["shell"] == "overlay", got["shell"]
    cap = [ln for ln in got["lines"] if ln["sel"].endswith(".ovset-cap")]
    empty = [ln for ln in got["lines"] if ln["sel"].endswith(".ovds-empty")]
    # Both are on the page, so an empty read cannot pass.
    assert [ln["text"] for ln in cap] == ["OVERLAY"], cap
    assert len(empty) == 1 and empty[0]["text"] in _OVDS_TEXTS, empty
    _check(got, cap + empty, f"{theme} overlay ovds")


@pytest.mark.parametrize("theme", _THEMES)
def test_overlay_caption_is_no_brighter_than_its_row_labels(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, "ovds")
    cap = [ln for ln in got["lines"] if ln["sel"].endswith(".ovset-cap")]
    rows = [ln for ln in got["lines"] if ln["sel"].endswith("> span")]
    assert len(cap) == 1 and rows, (cap, rows)
    for ln in rows:
        assert _lum(cap[0]["fg"]) <= _lum(ln["fg"]) + 1e-9, (theme, cap, ln)


@pytest.mark.parametrize("shell", sorted(_EMPTY_EXPECT))
@pytest.mark.parametrize("theme", _THEMES)
def test_active_match_empty_notices_reach_aa(
        theme, shell, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, shell)
    assert got["shell"] == ("overlay" if shell == "overlay" else ""), got
    lines = got["lines"]
    # Exactly the expected notices, so an empty read cannot pass.
    assert [next((w for w in _EMPTY_EXPECT[shell] if ln["text"].startswith(w)),
                 ln["text"]) for ln in lines] == _EMPTY_EXPECT[shell], lines
    _check(got, lines, f"{theme} {shell} am-empty")
