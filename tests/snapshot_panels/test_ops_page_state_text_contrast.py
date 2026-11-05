"""
tests/snapshot_panels/test_ops_page_state_text_contrast.py
RM-1554 (s144 uiux) - every state-coloured TEXT on /ops.html reaches WCAG
AA (4.5:1) on its own resolved fill, in every theme.

WHAT IS MEASURED (headless Chromium, /ops.html at 1920x920 against the
snapshot mock server; colours resolved by the browser, oklch and color-mix
included, lane doc trap 3; a translucent fill composited over the first
opaque ancestor, so the PAIR is measured, never the token, trap 4):
  - .ops-fail (the "unavailable - ..." card body; the Gated Queue route is
    stubbed with its own {"ok": false, "reason": ...} answer, so that card
    paints it);
  - the Drift Strip pills in each state (ok / amber / red / unknown), the
    label (.k) and the value (.v);
  - the Seam Map inert row's seam name (tr.inert td.seam) and its "NO"
    gate cell (.g-no) on the row's --bad-soft tint, plus a wired row's
    "yes" (.g-yes) on --surface;
  - the Match Ingest state words (.ing-s.s-ok / s-amber / s-red).
Every one is 16px (--fs-xs), not WCAG "large" text, so the 4.5:1 bar
applies. Each must also keep its hue and its tint, so a fix can only move
the TEXT, never drop the state encoding.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _themes():
    # "hextech" is the DEFAULT palette at :root (web/css/themes.css header);
    # no [data-theme="hextech"] block exists, so stamping it selects :root.
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    found = set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text))
    return ["hextech"] + sorted(found - {"hextech"})


_THEMES = _themes()

# Synthetic payloads in the shapes core/ops_panels.py returns (read by
# web/js/panels/ops_panels.js renderSeamMap / renderDriftStrip /
# renderIngestFreshness). No real game, match or account id.
_SEAM = {
    "ok": True, "wired_count": 1, "inert_count": 1,
    "seams": [
        {"seam": "dps.apply_example_seam", "inert": True, "flag": "yes",
         "transport": "no", "route": "no", "reason": "synthetic inert row"},
        {"seam": "ehp.example_wired_seam", "inert": False, "flag": "yes",
         "transport": "yes", "route": "yes", "reason": ""},
    ],
}
_DRIFT = {
    "ok": True, "amber_count": 2,
    "pills": [
        {"label": "Engine", "value": "v0.0.1", "state": "ok"},
        {"label": "Patch", "value": "26.1", "state": "amber"},
        {"label": "Mirror", "value": "stale 2h", "state": "red"},
        {"label": "Docs", "value": "-", "state": "unknown"},
    ],
}
_INGEST = {
    "ok": True, "basis": "synthetic basis",
    "rows": [
        {"key": "last_receipt", "value": "12 min ago", "state": "ok"},
        {"key": "tally", "value": "3 of 4", "state": "amber"},
        {"key": "lag", "value": "2 games behind", "state": "red"},
        {"key": "catchup", "value": "-", "state": "unknown"},
        {"key": "retry_backlog", "value": "0", "state": "ok"},
    ],
}
_STUBS = {
    "/api/ops/seam-map": _SEAM,
    "/api/ops/drift-strip": _DRIFT,
    "/api/ops/ingest-freshness": _INGEST,
    # The route's own failure answer, so the Gated Queue card paints
    # .ops-fail (the mock server's generic /api/* answer is {}, a shape the
    # real route never returns).
    "/api/ops/gated-queue": {"ok": False, "reason": "synthetic failure"},
}

_MEASURE_JS = r"""
async () => {
  await document.fonts.ready;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, base) => [0, 1, 2].map(
    (i) => top[i] * top[3] + base[i] * (1 - top[3]));
  const fill = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) layers.push(b);
      if (b[3] >= 1) break;
    }
    if (!layers.length || layers[layers.length - 1][3] < 1) return null;
    let acc = layers.pop().slice(0, 3);
    while (layers.length) acc = over(layers.pop(), acc);
    return acc;
  };
  const tok = (name) => {
    const d = document.createElement('div');
    d.style.backgroundColor = `var(${name})`;
    document.body.appendChild(d);
    const c = rgba(getComputedStyle(d).backgroundColor);
    d.remove();
    return c;
  };
  // An element's own tint: the first non-transparent background at or above
  // it (a td sits on its tr's tint, a .k span on its pill's).
  const tint = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) return b;
    }
    return null;
  };
  const marks = [];
  const add = (kind, state, el) => {
    if (!el || !el.getClientRects().length) return;
    const cs = getComputedStyle(el);
    marks.push({kind, state, text: (el.textContent || '').trim(),
                color: rgba(cs.color), opacity: parseFloat(cs.opacity),
                fill: fill(el), tint: tint(el),
                fontSize: parseFloat(cs.fontSize),
                weight: parseInt(cs.fontWeight, 10)});
  };
  add('ops-fail', 'bad', document.querySelector('#gated-queue-panel .ops-fail'));
  const pillState = (p) => p.classList.contains('red') ? 'bad'
    : p.classList.contains('amber') ? 'warn'
    : p.classList.contains('unknown') ? 'unknown' : 'good';
  for (const p of document.querySelectorAll('#drift-strip-panel .strip .pill')) {
    add('pill-k', pillState(p), p.querySelector('.k'));
    add('pill-v', pillState(p), p.querySelector('.v'));
  }
  for (const td of document.querySelectorAll('table.seams tr.inert td.seam')) {
    add('seam-inert-name', 'bad', td);
  }
  for (const td of document.querySelectorAll('table.seams td.g-no')) {
    add('seam-no', 'bad', td);
  }
  for (const td of document.querySelectorAll('table.seams td.g-yes')) {
    add('seam-yes', 'good', td);
  }
  for (const s of document.querySelectorAll('#ingest-freshness-panel .ing-s')) {
    const st = s.classList.contains('s-red') ? 'bad'
      : s.classList.contains('s-amber') ? 'warn'
      : s.classList.contains('s-ok') ? 'good' : 'unknown';
    add('ingest-state', st, s);
  }
  return {text: tok('--text'), badSoft: tok('--bad-soft'),
          warnSoft: tok('--warn-soft'), goodSoft: tok('--good-soft'),
          marks};
}
"""


def _lum(c) -> float:
    def ch(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _effective(color, opacity, fill):
    # An element's own opacity < 1 blends its glyphs into what is behind them
    # (.strip .pill .k sets opacity .85), so the rendered text colour is the
    # text composited over its fill at that opacity, not the computed colour.
    a = color[3] * opacity
    return [color[i] * a + fill[i] * (1 - a) for i in range(3)]


# Theme flips below must not straddle a colour transition (RM-1132).
_CALM = ("*, *::before, *::after { transition: none !important;"
         " animation: none !important; }")
# Every element _MEASURE_JS reads (test_theme_swap_reads_settled pins them).
_READS = ("#gated-queue-panel .ops-fail,"
          " #drift-strip-panel .strip .pill .k, #drift-strip-panel .strip .pill .v,"
          " table.seams tr.inert td.seam, table.seams td.g-no,"
          " table.seams td.g-yes, #ingest-freshness-panel .ing-s")


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    def _route(route):
        path = "/" + route.request.url.split("/", 3)[3].split("?", 1)[0]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_STUBS[path]))

    for p in _STUBS:
        page.route("**" + p, _route)
    try:
        page.goto(mock_server.url + "/ops.html",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_selector("#drift-strip-panel .strip .pill.red",
                               timeout=10_000)
        page.wait_for_selector("#gated-queue-panel .ops-fail", timeout=10_000)
        page.wait_for_selector("table.seams tr.inert", timeout=10_000)
        page.wait_for_selector("#ingest-freshness-panel .ing-s.s-red",
                               timeout=10_000)
        page.add_style_tag(content=_CALM)
    except Exception:
        page.close()
        ctx.close()
        raise
    return ctx, page, errors


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    out = {}
    try:
        # The page's own pre-paint stamp, before any theme flip below.
        out["_stamped"] = page.evaluate(
            "document.documentElement.getAttribute('data-theme')")
        for t in _THEMES:
            # hextech is the UNSTAMPED base palette (the FOUC guard removes
            # nothing and sets nothing for it), so it is measured unstamped.
            page.evaluate(
                "(t) => t === 'hextech'"
                " ? document.documentElement.removeAttribute('data-theme')"
                " : document.documentElement.setAttribute('data-theme', t)",
                t)
            out[t] = page.evaluate(_MEASURE_JS)
        out["_scroll"] = page.evaluate(
            "({overflow: getComputedStyle(document.body).overflowY,"
            " scrollH: document.scrollingElement.scrollHeight,"
            " clientH: document.scrollingElement.clientHeight,"
            " bodyH: document.body.getBoundingClientRect().height})")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return out


def test_theme_scan_anchor(measured):
    assert len(_THEMES) >= 6, _THEMES
    # The theme flip must really repaint, or every theme measures one palette.
    bads = {tuple(measured[t]["badSoft"]) for t in _THEMES}
    assert len(bads) >= 3, f"theme flip inert: {bads}"


@pytest.mark.parametrize("theme", _THEMES)
def test_every_palette_token_the_page_uses_resolves(theme, measured):
    # Trap 1 (an undefined var() inherits instead): before RM-1554 the
    # page never loaded panels/base.css, so under the hextech base palette
    # --text / --bad / --*-soft were undefined - text computed black and no
    # tint painted. A defined palette paints the -soft tints with alpha.
    out = measured[theme]
    for name in ("badSoft", "warnSoft", "goodSoft"):
        assert out[name][3] > 0, (theme, name, "token undefined", out[name])
    assert sum(out["text"][:3]) > 300, (theme, "--text undefined or dark",
                                        out["text"])


def test_page_follows_the_dashboard_theme_default(measured):
    # No ?theme= and no stored rc-theme: the dashboard default (theme.js
    # DEFAULT_THEME) is stamped, exactly as index.html does.
    mod = (ROOT / "web" / "js" / "lib" / "theme.js").read_text(encoding="utf-8")
    default = re.search(r'export const DEFAULT_THEME = "([a-z]+)";', mod).group(1)
    want = None if default == "hextech" else default
    assert measured["_stamped"] == want, (measured["_stamped"], want)


def test_page_still_scrolls(measured):
    # base.css's body is the dashboard shell (height 100%, overflow hidden);
    # the ops page must undo it or its lower cards are unreachable.
    s = measured["_scroll"]
    assert s["overflow"] != "hidden", s
    assert s["scrollH"] > s["clientH"], ("anchor: content fits, so the"
                                         " scroll check proves nothing", s)
    assert s["bodyH"] + 1 >= s["scrollH"] - 56, s


def test_fouc_guard_matches_theme_module():
    # The ops page copies the index.html pre-paint guard; both copies must
    # match web/js/lib/theme.js (THEMES, DEFAULT_THEME, the storage key).
    html = (ROOT / "web" / "ops.html").read_text(encoding="utf-8")
    mod = (ROOT / "web" / "js" / "lib" / "theme.js").read_text(encoding="utf-8")
    names = re.compile(r'"([a-z]+)"')
    inline = names.findall(re.search(r"var T = \[(.*?)\]", html, re.S).group(1))
    canon = names.findall(
        re.search(r"export const THEMES = \[(.*?)\]", mod, re.S).group(1))
    assert inline == canon, (inline, canon)
    assert 'localStorage.getItem("rc-theme")' in html
    default = re.search(r'export const DEFAULT_THEME = "([a-z]+)";', mod).group(1)
    assert f't = "{default}"' in html, default
    # The guard must run before the stylesheets paint (a module script or a
    # script after the links would flash the base palette first).
    assert html.index("var T = [") < html.index('rel="stylesheet"')
    # base.css carries the hextech :root palette and must precede the theme
    # overrides, which only win by specificity over the SAME tokens.
    assert (html.index("/css/panels/base.css")
            < html.index("/css/themes.css")), "base.css must load first"


_WANT = {
    ("ops-fail", "bad"), ("pill-k", "good"), ("pill-v", "good"),
    ("pill-k", "warn"), ("pill-v", "warn"), ("pill-k", "bad"),
    ("pill-v", "bad"), ("pill-k", "unknown"), ("pill-v", "unknown"),
    ("seam-inert-name", "bad"), ("seam-no", "bad"), ("seam-yes", "good"),
    ("ingest-state", "good"), ("ingest-state", "warn"),
    ("ingest-state", "bad"),
}


@pytest.mark.parametrize("theme", _THEMES)
def test_every_state_text_reaches_aa_on_its_fill(theme, measured):
    out = measured[theme]
    kinds = {(m["kind"], m["state"]) for m in out["marks"]}
    # Anchor: every mark class really rendered, so an empty page cannot pass.
    missing = _WANT - kinds
    assert not missing, (theme, sorted(missing))
    bad = []
    for m in out["marks"]:
        assert m["fill"] is not None, (theme, m)
        assert m["fontSize"] < 24, (theme, m)  # not WCAG large text
        eff = _effective(m["color"], m["opacity"], m["fill"])
        ratio = _ratio(eff, m["fill"])
        if ratio < 4.5:
            bad.append(
                f"{m['kind']}/{m['state']} {m['text']!r}:"
                f" rgb{tuple(round(v) for v in eff)} on"
                f" rgb{tuple(round(v) for v in m['fill'])} = {ratio:.2f}:1")
    assert not bad, f"{theme}: below AA 4.5:1: {sorted(set(bad))}"


@pytest.mark.parametrize("theme", _THEMES)
def test_every_state_text_keeps_its_hue_and_its_tint(theme, measured):
    out = measured[theme]
    bad = []
    soft = {"bad": out["badSoft"], "warn": out["warnSoft"],
            "good": out["goodSoft"]}
    for m in out["marks"]:
        r, g, b = m["color"][:3]
        if m["state"] == "bad" and not r - max(g, b) >= 60:
            bad.append((m["kind"], "bad no longer reads red", (r, g, b)))
        if m["state"] == "good" and not g - max(r, b) >= 30:
            bad.append((m["kind"], "good no longer reads green", (r, g, b)))
        if m["state"] == "warn" and not (r - b >= 60 and g - b >= 30):
            bad.append((m["kind"], "warn no longer reads amber", (r, g, b)))
        if m["state"] != "unknown" and m["color"][:3] == out["text"][:3]:
            bad.append((m["kind"], m["state"], "plain --text, hue lost"))
        # The tinted surfaces keep their own -soft tint.
        if m["kind"] in ("ops-fail", "seam-inert-name", "seam-no") or (
                m["kind"].startswith("pill-") and m["state"] in soft):
            want = soft[m["state"]]
            if m["tint"] != want:
                bad.append((m["kind"], m["state"], "tint moved",
                            m["tint"], want))
    assert not bad, f"{theme}: {bad}"
