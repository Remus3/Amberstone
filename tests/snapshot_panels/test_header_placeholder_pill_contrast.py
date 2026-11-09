"""
tests/snapshot_panels/test_header_placeholder_pill_contrast.py
S144-U-240 (s144 uiux): every text line in the Active Match header's
no-data placeholder pills reaches its WCAG text floor (1.4.3) on its
resolved surface in all six themes, with ancestor opacity folded in, at
the 1920x920 baseline viewport and the 923x1280 companion window.

THE DEFECTS. MEASURED headless under /?ui_mock=1&mode=sr#active-match
before the fix (web/css/panels/header.css). The static-pill rule keeps a
data-less pill in its slot but fades it with opacity 0.55, and the mock
has no zone, CS or vision value, so all three show as placeholders:
- the zone pill "-" (#zone-label, 16 px / 900, not WCAG large text, so
  the 4.5:1 floor applies) read 2.99 hextech, 3.16 arcane, 3.19 ember,
  3.21 bloodmoon, 3.23 moonlit, 3.36 terminal;
- the CS pill's "CS" label (21 px / 700, large text, 3:1 floor) read
  2.99 in hextech (3.16 - 3.36 elsewhere).
The vision "-" (3.13 - 3.37) and the offline heartbeat (3.02 - 3.34) are
21 px / 900 large text and clear 3:1; they keep the fade.
(These before ratios fold the 0.55 into the text but read the pill's opaque
fill unfaded, so they are close, not exact; the after ratios are exact.)

THE FIX. The zone and CS placeholders drop the opacity: their text (the
CS value included) is --text-faint at full strength and their fill is
--surface at 55 percent, the look the fade gave the fill. A stale zone
class left on a hidden pill (map_state.js adds .hidden and keeps the last
zone class) no longer paints its red / green / gold call or pulses.

Checked per theme and viewport: every visible header text line reaches
its floor; the zone and CS placeholders are --text-faint at opacity 1 on
a translucent fill; and a hidden pill still carrying zone-enemy /
zone-deep / zone-safe reads as the same grey placeholder, unanimated.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_AA_LARGE = 3.0
_SHEET = "*, *::before, *::after { transition: none !important; }"
# The stale classes map_state.js can leave on a hidden zone pill.
_STALE = ["zone-pill zone-enemy hidden", "zone-pill zone-enemy zone-deep hidden",
          "zone-pill zone-safe hidden", "zone-pill zone-dmz hidden"]

_MEASURE = """async (stale) => {
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
    return {id: el.id, cls: String(el.className), text: own.trim(),
            alpha: alpha(el), fg: s ? over(fg, s) : null, bg: s,
            size: parseFloat(cs.fontSize),
            weight: parseInt(cs.fontWeight, 10)};
  };
  const hdr = document.querySelector('header');
  const lines = [...hdr.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(line);
  const root = getComputedStyle(document.documentElement);
  const faint = rgba(root.getPropertyValue('--text-faint').trim());
  const pill = (id) => {
    const p = document.getElementById(id);
    const cs = getComputedStyle(p);
    return {cls: String(p.className), opacity: parseFloat(cs.opacity),
            color: rgba(cs.color), bg: rgba(cs.backgroundColor),
            anim: cs.animationName, shadow: cs.boxShadow,
            shown: p.checkVisibility()};
  };
  const zp = document.getElementById('zone-pill');
  const orig = zp.className;
  const stales = stale.map((cls) => {
    zp.className = cls;
    const out = pill('zone-pill');
    out.label = line(document.getElementById('zone-label'));
    return out;
  });
  zp.className = orig;
  return {theme: document.documentElement.dataset.theme || 'hextech',
          faint, lines, zone: pill('zone-pill'), cs: pill('cs-pill'),
          csVal: rgba(getComputedStyle(
            document.getElementById('cs-val')).color),
          stales};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.wait_for_function(
            "() => document.getElementById('zone-pill')"
            ".classList.contains('hidden')"
            " && document.getElementById('cs-pill')"
            ".classList.contains('hidden')",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE, _STALE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _large(ln) -> bool:
    return ln["size"] >= 24 or (ln["size"] >= 18.66 and ln["weight"] >= 700)


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_header_line_reaches_its_floor(theme, vp, measured,
                                             mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    lines = got["lines"]
    ids = {ln["id"] for ln in lines}
    # The three placeholders are on the page, so an empty read cannot pass.
    assert {"zone-label", "cs-val", "vis-val"} <= ids, ids
    assert any(ln["id"] == "cs-pill" and ln["text"] == "CS"
               for ln in lines), lines
    bad = []
    for ln in lines:
        assert ln["bg"] is not None, (theme, ln)
        floor = _AA_LARGE if _large(ln) else _AA
        ratio = _ratio(ln["fg"], ln["bg"])
        if ratio < floor:
            bad.append(f"#{ln['id'] or ln['cls']} {ln['text']!r} "
                       f"{ratio:.2f}:1 (alpha {ln['alpha']:.2f}) "
                       f"under {floor}")
    assert not bad, f"{theme} {vp}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_zone_and_cs_placeholders_are_faint_text_on_a_faded_fill(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    for key in ("zone", "cs"):
        p = got[key]
        assert p["shown"], (theme, key, p)
        assert "hidden" in p["cls"].split(), (theme, key, p)
        assert p["opacity"] == 1, (theme, key, p)
        assert p["color"] == got["faint"], (theme, key, p, got["faint"])
        # The fill stays a translucent tint, never a solid chip.
        assert 0 < p["bg"][3] < 1, (theme, key, p)
    assert got["csVal"] == got["faint"], (theme, got["csVal"])


@pytest.mark.parametrize("theme", _THEMES)
def test_a_stale_zone_class_on_a_hidden_pill_reads_as_the_placeholder(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    base = got["zone"]
    assert len(got["stales"]) == len(_STALE)
    for cls, st in zip(_STALE, got["stales"]):
        assert st["cls"] == cls, st
        assert st["color"] == got["faint"], (theme, cls, st)
        assert st["bg"] == base["bg"], (theme, cls, st["bg"], base["bg"])
        assert st["anim"] == "none", (theme, cls, st["anim"])
        assert st["shadow"] == "none", (theme, cls, st["shadow"])
        ln = st["label"]
        assert _ratio(ln["fg"], ln["bg"]) >= _AA, (theme, cls, ln)
