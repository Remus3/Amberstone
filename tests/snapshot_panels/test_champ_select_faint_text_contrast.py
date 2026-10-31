"""
tests/snapshot_panels/test_champ_select_faint_text_contrast.py
RM-1144 (s144 uiux): the champ-select ORDERED SEQUENCE strip
(#csv-builds-seq, web/js/panels/champ_select.js _csvBuildSeqStripHtml) and
the TEAM ANALYSIS head (#csv-ta-head) reach WCAG AA on their resolved
surface, on all six themes. Both are styled in
web/css/panels/champ_select_view.css.

MEASURED headless under /?ui_mock=1&mode=sr&theme=<t>#champ-select at
1920x1080 before the fix (16px text, so the 4.5:1 floor applies; colours
resolved by the browser and composited over the stacked backgrounds, lane
doc traps 3 and 4):
  .csv-boseq-tag "ORDERED SEQUENCE" and
  .csv-boseq-msg "computing..."  on --surface-3   3.64 to 3.94:1
    (hextech, ember, bloodmoon, moonlit, arcane; terminal 4.59)
  .csv-ta-title "TEAM ANALYSIS" and
  .csv-ta-caret "[+]"            on --surface-2   4.31 to 4.52:1
    (under 4.5 on hextech, ember, moonlit, arcane)
The landed strip's slot numbers (.csv-boseq-num, on the --surface-2 chip)
were on the same --text-faint token. --text-faint is documented AA on
--surface only (web/css/panels/base.css); on these two raised surfaces it
is not. All of them now take --text-dim, the next tier up, and stay dimmer
than the primary text they label (the TEAM ANALYSIS verdict), so the
hierarchy holds.

The loading strip is held by an /api/build-order route answering 503 (a
failed POST caches nothing, so the strip stays on "computing..."); the
landed strip by a synthetic ok payload routed to the same POST. The
fixture's own picks drive champion and mode, as in test_champ_select_view.py.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

# Synthetic engine order (item ids are DDragon catalogue ids, not game data).
_ORDER = {"ok": True, "order": [
    {"slot": 1, "item_id": 3031, "item_name": "Infinity Edge",
     "delta": 210.4, "unit": "dps", "gold": 3450},
    {"slot": 2, "item_id": 6672, "item_name": "Kraken Slayer",
     "delta": 147.3, "unit": "dps", "gold": 3100},
    {"slot": 3, "item_id": 3094, "item_name": "Rapid Firecannon",
     "delta": 96.0, "unit": "dps", "gold": 2650},
]}

_MEASURE = """async (want) => {
  await document.fonts.ready;
""" + _HELPERS + """
  // Read in the SAME task that sees the strip in `want`. The strip re-keys
  // when the archetype pick lands after the first build order (ready ->
  // loading -> ready), so a wait in a separate call can pass and the read
  // still find "loading" (CI run 41231114850).
  const settled = () => {
    const s = document.getElementById('csv-builds-seq');
    const v = document.querySelector('#view-champ-select .csv-ta-verdict');
    return !!s && s.dataset.boState === want && !!v && !!v.textContent.trim();
  };
  const t0 = Date.now();
  while (!settled() && Date.now() - t0 < 10000) {
    await new Promise((r) => setTimeout(r, 25));
  }
  const out = [];
  const seq = document.getElementById('csv-builds-seq');
  if (seq) out.push(...read(seq.dataset.boState, seq));
  const head = document.getElementById('csv-ta-head');
  if (head) out.push(...read('ta', head));
  return out;
}"""


def _measure(mock_server, pw_browser, theme, ready):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if ready:
        page.route("**/api/build-order*", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(_ORDER)))
    else:
        # A failed POST caches nothing, so the strip holds "computing...".
        page.route("**/api/build-order*", lambda r: r.fulfill(
            status=503, content_type="application/json", body="{}"))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&theme={theme}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        state = "ready" if ready else "loading"
        page.wait_for_function(
            "document.querySelector("
            f"'#view-champ-select #csv-builds-seq[data-bo-state=\"{state}\"]')"
            " && document.querySelector('#view-champ-select .csv-ta-verdict')"
            ".textContent.trim()",
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        rows = page.evaluate(_MEASURE, state)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return rows


@pytest.fixture(scope="module")
def measured(request):
    return {}


def _rows(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = (_measure(mock_server, pw_browser, theme, False)
                           + _measure(mock_server, pw_browser, theme, True))
    return measured[theme]


def _by(rows, state, cls):
    return [r for r in rows if r[0] == state and cls in r[1].split()]


@pytest.mark.parametrize("theme", _THEMES)
def test_faint_labels_reach_aa_on_their_surface(theme, measured, mock_server,
                                                pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    want = [("loading", "csv-boseq-tag"), ("loading", "csv-boseq-msg"),
            ("ready", "csv-boseq-tag"), ("ready", "csv-boseq-num"),
            ("ta", "csv-ta-title"), ("ta", "csv-ta-caret"),
            ("ta", "csv-ta-verdict")]
    for state, cls in want:
        assert _by(rows, state, cls), f"{cls} ({state}) not rendered"
    nums = _by(rows, "ready", "csv-boseq-num")
    assert len(nums) == len(_ORDER["order"]), nums
    low = []
    for state, cls, text, fg, bg in rows:
        assert fg and bg, f"no resolved surface under {cls!r}"
        r = _ratio(fg, bg)
        if r < 4.5:
            low.append(f"{cls} {text.strip()!r} ({state}) {r:.2f}:1")
    assert not low, f"{theme}: under 4.5:1 - " + "; ".join(low)


@pytest.mark.parametrize("theme", ["hextech", "bloodmoon"])
def test_team_analysis_title_stays_dimmer_than_its_verdict(
        theme, measured, mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    title = _by(rows, "ta", "csv-ta-title")[0]
    verdict = _by(rows, "ta", "csv-ta-verdict")[0]
    assert _lum(title[3]) < _lum(verdict[3]), (
        f"{theme}: TEAM ANALYSIS label is as bright as its verdict")


# CI run 41231114850 (Linux): the strip landed "ready" on its first key (no
# archetype yet), the wait in _measure saw it, then the archetype pick landed,
# re-keyed the build order and put the strip back on "loading" before the read.
# This holds the archetype pick and the archetype-keyed order to replay that.
_HOLD_ARCHETYPE = """
(() => {
  const real = window.fetch.bind(window);
  const gate = () => {
    let open;
    const p = new Promise((r) => { open = r; });
    return {p, open};
  };
  const arch = gate();
  const order = gate();
  window.__rcHold = {arch: arch.open, order: order.open};
  window.fetch = (url, init) => {
    const u = String((url && url.url) || url);
    if (u.includes('/api/cs-archetype-pick')) {
      return arch.p.then(() => real(url, init));
    }
    if (u.includes('/api/build-order')
        && String((init && init.body) || '').includes('"archetype"')) {
      return order.p.then(() => real(url, init));
    }
    return real(url, init);
  };
})();
"""


def test_the_ready_read_survives_the_archetype_rekey(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_HOLD_ARCHETYPE)
    page.route("**/api/build-order*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(_ORDER)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    seq = "#view-champ-select #csv-builds-seq"
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=sr&theme=hextech#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            f"!!document.querySelector('{seq}[data-bo-state=\"ready\"]')",
            timeout=10_000)
        page.evaluate("window.__rcHold.arch()")
        page.wait_for_function(
            f"!!document.querySelector('{seq}[data-bo-state=\"loading\"]')",
            timeout=10_000)
        page.evaluate("setTimeout(window.__rcHold.order, 300)")
        rows = page.evaluate(_MEASURE, "ready")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert _by(rows, "ready", "csv-boseq-tag"), [r[:3] for r in rows]
    assert not _by(rows, "loading", "csv-boseq-tag"), [r[:3] for r in rows]
