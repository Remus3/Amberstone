"""
tests/snapshot_panels/test_theme_soft_token_hue.py
RM-1318 (s144 uiux) - every status `-soft` tint resolves to its own
theme's status hue.

THE DEFECT. web/css/panels/base.css :root declares each status colour with
an 18%-alpha `-soft` sibling (--gold / --good / --warn / --bad / --info /
--advisory, each with --<name>-soft). web/css/themes.css re-declares the
solid colour per :root[data-theme] block, but the moonlit block overrode
--info (an aqua-blue, oklch(0.75 0.110 215)) WITHOUT re-declaring
--info-soft, so moonlit's --info-soft kept base.css's hextech blue
rgba(124,168,255,.18). Every consumer that pairs the two - the Session /
History hover and Recent-5 deep-link tint beside its --info rail
(web/css/panels/home.css), the intent chips, the coach info rows - painted
the tint and the rail in two different blues. MEASURED in headless Chromium
before the fix: moonlit --info resolves to sRGB about (73,191,217) while
--info-soft resolved to (124,168,255) at 0.18 alpha.

THE FIX. The moonlit block declares --info-soft beside --info, in the
file's own hex-then-oklch pattern.

WHAT IS MEASURED (headless Chromium, computed values, never a grep): for
the base hextech palette (no data-theme) and EVERY :root[data-theme] block
in themes.css, each status token and its -soft sibling are resolved
through `color-mix(in srgb, ...)` (so an oklch() declaration is compared
as the sRGB the browser paints, not as the hex fallback a grep would
find). The -soft RGB must equal the solid RGB within 3/255 per channel
(the hex fallbacks are sRGB-clamped equivalents of their oklch lines) and
its alpha must be 0.18 +- 0.01.
"""
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent

TOKENS = ("gold", "good", "warn", "bad", "info", "advisory")
TOL = 3          # per channel, 0-255
ALPHA = 0.18

_RESOLVE_JS = r"""
(names) => {
  const d = document.createElement('div');
  document.body.appendChild(d);
  const read = (v) => {
    d.style.color = 'color-mix(in srgb, var(' + v + ') 100%, transparent 0%)';
    return getComputedStyle(d).color;
  };
  const out = {};
  for (const n of names) {
    out[n] = { solid: read('--' + n), soft: read('--' + n + '-soft') };
  }
  d.remove();
  return out;
}
"""

_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


def _parse(col):
    """Parse a computed colour into (r, g, b, a) on 0-255 / 0-1 scales."""
    nums = [float(x) for x in _NUM.findall(col)]
    if col.startswith("color(srgb"):
        r, g, b = (round(v * 255, 2) for v in nums[:3])
        a = nums[3] if len(nums) > 3 else 1.0
    elif col.startswith("rgb"):
        r, g, b = nums[:3]
        a = nums[3] if len(nums) > 3 else 1.0
    else:
        raise AssertionError(f"unexpected computed colour form: {col!r}")
    return r, g, b, a


def _themes():
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "document.body.dataset.view === 'home'", timeout=10_000
    )
    return ctx, page, errors


def _set_theme(page, theme):
    if theme == "hextech":
        page.evaluate(
            "() => document.documentElement.removeAttribute('data-theme')"
        )
    else:
        page.evaluate(
            "(t) => document.documentElement.setAttribute('data-theme', t)",
            theme,
        )


def _measure_all(pw_browser, mock_server):
    themes = ["hextech"] + _themes()
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        got = {}
        for t in themes:
            _set_theme(page, t)
            got[t] = page.evaluate(_RESOLVE_JS, list(TOKENS))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return got


def _failures(got):
    bad = []
    for theme, toks in got.items():
        for name, pair in toks.items():
            sr, sg, sb, sa = _parse(pair["solid"])
            tr, tg, tb, ta = _parse(pair["soft"])
            if sa < 0.99:
                bad.append((theme, name, "solid not opaque", pair))
            if max(abs(sr - tr), abs(sg - tg), abs(sb - tb)) > TOL:
                bad.append((theme, name, "soft hue != solid hue", pair))
            if abs(ta - ALPHA) > 0.01:
                bad.append((theme, name, f"soft alpha {ta}", pair))
    return bad


def test_every_soft_tint_matches_its_themes_status_hue(mock_server, pw_browser):
    got = _measure_all(pw_browser, mock_server)
    assert len(got) >= 6, f"theme scan anchor: {sorted(got)}"
    assert not _failures(got), f"soft-token mismatches: {_failures(got)[:6]}"


def test_moonlit_info_soft_is_moonlits_aqua_blue(mock_server, pw_browser):
    # The specific RM-1318 pair, so a regression names itself.
    got = _measure_all(pw_browser, mock_server)
    pair = got["moonlit"]["info"]
    sr, sg, sb, _ = _parse(pair["solid"])
    tr, tg, tb, ta = _parse(pair["soft"])
    assert sg > sr and sb > sr, f"moonlit --info is not aqua-blue: {pair}"
    assert max(abs(sr - tr), abs(sg - tg), abs(sb - tb)) <= TOL, pair
    assert abs(ta - ALPHA) <= 0.01, pair


def test_theme_flip_is_not_inert(mock_server, pw_browser):
    # Anchor: an inert theme flip would make the hue check trivially pass.
    got = _measure_all(pw_browser, mock_server)
    infos = {got[t]["info"]["solid"] for t in got}
    golds = {got[t]["gold"]["solid"] for t in got}
    assert len(infos) >= 3, f"--info identical across themes: {infos}"
    assert len(golds) >= 4, f"--gold identical across themes: {golds}"
