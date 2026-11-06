"""
tests/snapshot_panels/test_settings_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) every Settings card fits the view and no
value in it is cut (s144 lane uiux, RM-1779; RM-1774 did the view
heads, RM-1775 / U-166 the Lobby).

Measured before the fix (ui_mock settings, headless Chromium): the
.settings-body grid is one 1fr track below 1200 px, and a 1fr track cannot
shrink below its widest card's min-content. The PANEL VISIBILITY rows are a
two-track grid (name 1fr | a fixed 7.5em checkbox column, 203 px), so every
card was held at 367 px: 45 px past the view at 360 and 85 at 320, and the
whole view scrolled sideways (section scrollWidth 385 in 322 / 282). Behind
that floor, at 320 the Post Game Review Rank-Tier select and the Baseline
Games slider row held one line and ran 17 / 39 px past their card; a real
Windows voice name in the Voice picker, and a Dev-mode API SPEND GATES row
(checkbox, text, a 130 px cost column) did the same.

Contract pinned here, ui_mock settings with Dev mode on (gate rows routed in
from the core/cost_tracker.py GATE_META labels) and one Windows voice name
in the Voice picker, at 640x900, 480x800, 360x740 and 320x640:
  - the view does not scroll sideways and every shown descendant lies inside
    the view's content box;
  - every card lies inside the view, and no shown descendant of a card
    reaches past that card's frame;
  - a PANEL VISIBILITY row keeps a checkbox cell of at least --hit-min
    (42 px) each way, the checkbox inside it, and a panel name that is not
    cut (it may wrap between words);
  - the Rank-Tier select is never narrower than its own min-content (no
    option text is cut where the line can hold it); the Baseline Games
    value sits on the slider's line;
  - a spend-gate cost is never cut and stays right-aligned in its row.
Above the line (722x900 and the 1920x920 baseline) the desktop layout is
unchanged: the 7.5em checkbox column and one-line, non-wrapping rows.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((640, 900), (480, 800), (360, 740), (320, 640))
_WIDE = ((722, 900), (1920, 920))
_IDS = [str(s[0]) for s in _NARROW]
_WIDE_IDS = [str(s[0]) for s in _WIDE]

# A built-in Windows SAPI voice name (what speechSynthesis.getVoices()
# returns on the operator's box; headless Chromium returns none).
_VOICE = "Microsoft Zira - English (United States)"

# Shape: dashboard/routes_coach.py _serve_spend_gates ({"gates":
# CostTracker.gates_state(), "per_match": CostTracker.recent_match_avg()}).
# Labels and explain lines are core/cost_tracker.py GATE_META verbatim;
# the costs are synthetic.
_LABELS = {
    "sr": ("SR coach", "Live Summoner's Rift text coaching (Haiku)."),
    "aram": ("ARAM coach", "Live ARAM text coaching (Haiku)."),
    "arena": ("Arena coach", "Live Arena text coaching (Haiku)."),
    "brawl": ("Brawl coach", "Live Brawl text coaching (Haiku)."),
    "vision": ("Vision scans", "Sonnet screen-vision escalation (all modes;"
               " the priciest call)."),
    "champ_select": ("Champ select", "Champ-select brief, team analyzer,"
                     " experimental builder."),
    "tft": ("TFT coach", "TFT live + PBE coaching and TFT board vision."),
}
_GATES = {
    "gates": {g: {"label": lab, "explain": exp, "disabled": g == "brawl"}
              for g, (lab, exp) in _LABELS.items()},
    "per_match": {
        g: ({"usd": 0.0412, "tokens": 15234, "n": 2} if g in ("aram", "vision")
            else {"usd": 0.0, "tokens": 0, "n": 0})
        for g in _LABELS
    },
}

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const sec = document.getElementById("view-settings");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const scs = getComputedStyle(sec);
  const sr = sec.getBoundingClientRect();
  const content = {
    l: sr.left + parseFloat(scs.borderLeftWidth) + parseFloat(scs.paddingLeft),
    r: sr.right - parseFloat(scs.borderRightWidth)
      - parseFloat(scs.paddingRight),
  };
  const shown = (e) => getComputedStyle(e).display !== "none"
    && getComputedStyle(e).visibility !== "hidden"
    && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const tag = (d) => d.tagName + "#" + d.id + "."
    + String(d.className).slice(0, 40);
  const viewPast = [];
  for (const d of sec.querySelectorAll("*")) {
    if (!shown(d)) continue;
    const r = d.getBoundingClientRect();
    if (r.right > content.r + 1 || r.left < content.l - 1) {
      viewPast.push([tag(d), Math.round(r.left), Math.round(r.right)]);
    }
  }
  const cards = Array.from(sec.querySelectorAll(".settings-card"))
    .filter(shown).map((c) => {
      const cr = c.getBoundingClientRect();
      const past = [];
      for (const d of c.querySelectorAll("*")) {
        if (!shown(d)) continue;
        const r = d.getBoundingClientRect();
        if (r.right > cr.right + 1 || r.left < cr.left - 1) {
          past.push([tag(d), Math.round(r.left), Math.round(r.right),
                     Math.round(cr.left), Math.round(cr.right)]);
        }
      }
      const head = c.querySelector(".settings-card-head");
      return {head: head ? head.textContent.trim() : c.id, box: box(c),
              past: past.slice(0, 6), n: past.length};
    });
  const pv = Array.from(sec.querySelectorAll(
    "#panel-visibility-card .pv-row:not(.pv-row-head)")).filter(shown)
    .map((row) => {
      const name = row.querySelector(".pv-panel-name");
      const cell = row.querySelector(".pv-cell");
      const cb = cell.querySelector("input");
      return {name: name.textContent, nsw: name.scrollWidth,
              ncw: name.clientWidth, cell: box(cell), cb: box(cb),
              tracks: getComputedStyle(row).gridTemplateColumns,
              em: parseFloat(getComputedStyle(row).fontSize)};
    });
  const pvHead = sec.querySelector("#panel-visibility-card .pv-col-head");
  // The select's own min-content width, read with it taken out of flex
  // sizing (inside the row its width is the flexed one), then restored.
  const minContent = (el) => {
    const keep = el.getAttribute("style");
    el.style.flex = "none";
    el.style.minWidth = "0";
    el.style.width = "min-content";
    const w = el.getBoundingClientRect().width;
    if (keep === null) el.removeAttribute("style");
    else el.setAttribute("style", keep);
    return w;
  };
  const sel = (id) => {
    const el = document.getElementById(id);
    const row = el.closest(".settings-row");
    return {...box(el), min: minContent(el), row: box(row),
            lab: box(row.querySelector(":scope > span"))};
  };
  const rng = document.getElementById("set-pgr-baseline");
  const val = document.getElementById("set-pgr-baseline-val");
  const gates = Array.from(sec.querySelectorAll(".spend-gate-row"))
    .filter(shown).map((row) => {
      const cost = row.querySelector(".spend-gate-cost");
      const rcs = getComputedStyle(row);
      return {row: box(row), cost: box(cost), csw: cost.scrollWidth,
              txt: box(row.querySelector(".spend-gate-txt")),
              ccw: cost.clientWidth,
              rowContentR: row.getBoundingClientRect().right
                - parseFloat(rcs.paddingRight) - parseFloat(rcs.borderRightWidth),
              text: cost.textContent};
    });
  const rows = Array.from(sec.querySelectorAll(".settings-row")).filter(shown);
  return {
    sw: sec.scrollWidth, cw: sec.clientWidth, content,
    docSw: document.documentElement.scrollWidth, vw: innerWidth,
    viewPast: viewPast.slice(0, 8), nViewPast: viewPast.length,
    cards, pv, pvHead: pvHead ? box(pvHead) : null,
    rank: sel("set-pgr-rank-tier"), voice: sel("set-voice-name"),
    rng: box(rng), val: box(val), gates,
    rngLab: box(rng.closest(".settings-row").querySelector(":scope > span")),
    wraps: rows.map((r) => getComputedStyle(r).flexWrap),
    boxRows: rows.filter((r) => r.querySelector(
      ":scope > input[type='checkbox']")).map((r) => {
        const cb = r.querySelector(":scope > input[type='checkbox']");
        const txt = cb.nextElementSibling;
        return {wrap: getComputedStyle(r).flexWrap, cb: box(cb),
                gate: r.classList.contains("spend-gate-row"),
                txt: box(txt), text: txt.textContent.slice(0, 40)};
      }),
  };
}"""


def _read(pw_browser, url, size):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(
        "try { localStorage.setItem('rc-dev-mode', '1'); } catch (_) {}")
    page.route("**/api/spend/gates*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_GATES)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/?ui_mock=1#settings", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'settings'"
            " && document.querySelectorAll('#view-settings .spend-gate-row')"
            f".length === {len(_LABELS)}"
            " && document.querySelectorAll('#panel-visibility-card"
            " .pv-row:not(.pv-row-head)').length > 0",
            timeout=10_000,
        )
        page.evaluate(
            """(name) => {
              const s = document.getElementById("set-voice-name");
              const o = document.createElement("option");
              o.value = name; o.textContent = name;
              s.appendChild(o); s.value = name;
            }""",
            _VOICE,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {s: _read(pw_browser, mock_server.url, s) for s in _NARROW}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {s: _read(pw_browser, mock_server.url, s) for s in _WIDE}


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_the_view_does_not_scroll_sideways(narrow, size):
    r = narrow[size]
    assert r is not None, size
    assert r["sw"] <= r["cw"], (size, r["sw"], r["cw"])
    assert r["docSw"] <= r["vw"], (size, r["docSw"], r["vw"])
    assert r["nViewPast"] == 0, (size, r["viewPast"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_every_card_fits_the_view_and_holds_its_content(narrow, size):
    r = narrow[size]
    heads = [c["head"] for c in r["cards"]]
    assert {"CLIENT SETTINGS", "DISPLAY", "API SPEND GATES",
            "PANEL VISIBILITY"} <= set(heads), heads
    for c in r["cards"]:
        b = c["box"]
        assert b["l"] >= r["content"]["l"] - 1, (size, c["head"], b)
        assert b["r"] <= r["content"]["r"] + 1, (size, c["head"], b)
        assert c["n"] == 0, (size, c["head"], c["past"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_panel_visibility_rows_keep_the_hit_floor_and_whole_names(narrow,
                                                                  size):
    rows = narrow[size]["pv"]
    assert len(rows) >= 4, rows
    for row in rows:
        cell, cb = row["cell"], row["cb"]
        assert cell["w"] >= 42 - 0.5 and cell["h"] >= 42 - 0.5, (size, row)
        assert cb["l"] >= cell["l"] - 0.5 and cb["r"] <= cell["r"] + 0.5, (
            size, row)
        assert row["nsw"] <= row["ncw"] + 1, (size, row)
    head = narrow[size]["pvHead"]
    assert head is not None
    # The SHOW column head sits over the checkbox column.
    first = rows[0]["cell"]
    assert head["l"] >= first["l"] - 1 and head["r"] <= first["r"] + 1, (
        size, head, first)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_rank_select_is_never_cut_and_the_slider_keeps_its_value(narrow,
                                                                 size):
    r = narrow[size]
    rank = r["rank"]
    assert rank["w"] + 0.5 >= rank["min"], (size, rank)
    assert rank["r"] <= rank["row"]["r"] + 1, (size, rank)
    voice = r["voice"]
    assert voice["r"] <= voice["row"]["r"] + 1, (size, voice)
    rng, val = r["rng"], r["val"]
    mid = (val["t"] + val["b"]) / 2
    assert rng["t"] - 1 <= mid <= rng["b"] + 1, (size, rng, val)
    assert val["l"] >= rng["r"] - 1, (size, rng, val)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_a_checkbox_row_keeps_its_text_beside_the_box(narrow, size):
    rows = narrow[size]["boxRows"]
    assert len(rows) >= 8, rows
    for row in rows:
        # A spend-gate row wraps only its cost (test below); the text stays
        # beside the box on the first line in every checkbox row.
        if not row["gate"]:
            assert row["wrap"] == "nowrap", (size, row)
        assert row["txt"]["l"] >= row["cb"]["r"], (size, row)
        assert row["txt"]["t"] <= row["cb"]["b"], (size, row)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_spend_gate_costs_are_never_cut(narrow, size):
    gates = narrow[size]["gates"]
    assert len(gates) == len(_LABELS), gates
    for g in gates:
        assert g["csw"] <= g["ccw"] + 1, (size, g)
        assert abs(g["cost"]["r"] - g["rowContentR"]) < 1.5, (size, g)
    priced = [g for g in gates if "$" in g["text"]]
    assert len(priced) == 2, gates


def test_at_320_the_controls_and_costs_take_their_own_line(narrow):
    r = narrow[(320, 640)]
    for key in ("rank", "voice"):
        c = r[key]
        assert c["t"] >= c["lab"]["b"] - 1, (key, c)
    assert r["rng"]["t"] >= r["rngLab"]["b"] - 1, (r["rng"], r["rngLab"])
    for g in r["gates"]:
        assert g["cost"]["t"] >= g["txt"]["b"] - 1, g


@pytest.mark.parametrize("size", _WIDE, ids=_WIDE_IDS)
def test_desktop_layout_is_unchanged_above_the_line(wide, size):
    r = wide[size]
    assert r["sw"] <= r["cw"], (size, r["sw"], r["cw"])
    assert set(r["wraps"]) == {"nowrap"}, (size, r["wraps"])
    assert len(r["pv"]) >= 4, r["pv"]
    assert len(r["gates"]) == len(_LABELS), r["gates"]
    for row in r["pv"]:
        cols = [float(t[:-2]) for t in row["tracks"].split()]
        assert len(cols) == 2, row
        assert abs(cols[1] - 7.5 * row["em"]) < 0.5, (size, row)
    # One line per select / slider row: the control shares the label's line.
    for key in ("rank", "voice"):
        c = r[key]
        lab_mid = (c["lab"]["t"] + c["lab"]["b"]) / 2
        assert c["t"] - 1 <= lab_mid <= c["b"] + 1, (size, key, c)
        assert c["l"] >= c["lab"]["r"], (size, key, c)
    rng, val = r["rng"], r["val"]
    assert abs((rng["t"] + rng["b"]) / 2 - (val["t"] + val["b"]) / 2) < 12, (
        size, rng, val)
    for g in r["gates"]:
        assert abs(g["cost"]["r"] - g["rowContentR"]) < 1.5, (size, g)
