"""
tests/snapshot_panels/test_session_user_builds_narrow_fit.py
The Session and User Builds views fit the window at every width down to the
320 px reflow floor (WCAG 1.4.10), so neither scrolls sideways (s144 lane
uiux, S144-U-196).

Measured before the fix (ui_mock, headless Chromium), the view section's
scrollWidth against its clientWidth:
  - Session: 320 in 282 at 320 px. The SHOULD I QUEUE card's head holds the
    score, the readiness chip and the confidence chip on one no-wrap line
    (52 + 117 + 63 px + two 12 px gaps = 256 px), so the single-column
    .session-grid track (`1fr`, whose minimum is the widest card's
    min-content) grew to 302 px and pushed EVERY card 37 px past the view;
    the LOW chip ran past its own card too. With that head wrapping, the
    MATCHES rows were next: a row's min-content (grade, "RenataGlasc", KDA,
    time; 272 px) held every card at 302 px, and from 360 to 400 px the
    time broke into "3:58" over "PM". 360 px and up fit the view.
  - User Builds: 312 in 282 at 320 px. The champion search field
    (`flex: 0 1 360px`) could not shrink below the input's intrinsic width
    (a flex item's min-width: auto), so it stayed 294 px wide in a 246 px
    toolbar. 360 px and up fit. With the editor open the form held 586 px
    from 480 down: its two `1fr` columns could not shrink below two 264 px
    inputs, and the spell grid kept six 56 px columns (376 px). And at
    every width up to 480 a build row gave its name column what Edit and
    Delete left: 17 px at 320 (the name ellipsized to nothing, every 26 px
    item icon ran past it), 57 px at 360.

Contract pinned here, ui_mock, at 1920x920, 721x900, 720x900, 480x800,
360x740 and 320x640 (User Builds at rest and with the editor open):
  - the view section does not scroll sideways;
  - every Session card, and every displayed descendant of the SHOULD I QUEUE
    head, sits inside its card; a MATCHES row's KDA and time never break
    inside themselves; the User Builds toolbar's children sit inside the
    toolbar; every build row's item icons sit inside their column, at 480 px
    and under the name column takes the row's full width (>= 150 px) with
    Edit and Delete on a line below it, and above 480 they share one line,
    Delete on the row's right edge; with the editor open every spell cell
    sits inside the spell grid at the 42 px floor;
  - anti-vacuity: at 1920 the Session grid keeps its two tracks and the SHOULD
    I QUEUE head keeps one line; the champion field stays 360 px wide at 1920
    and keeps at least 200 px and the 42 px hit floor at 320, and its value
    is still typed into it there; at 1920 every MATCHES row is one 42 px line.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_WIDTHS = (
    (1920, 920), (721, 900), (720, 900), (480, 800), (360, 740), (320, 640),
)

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_SECTION = """(id) => {
  const s = document.getElementById(id);
  const r = s.getBoundingClientRect();
  return {
    display: getComputedStyle(s).display,
    sw: s.scrollWidth, cw: s.clientWidth,
    left: r.left + s.clientLeft,
    right: r.left + s.clientLeft + s.clientWidth,
  };
}"""

_SESSION = """() => {
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {left: r.left, right: r.right, top: r.top, w: r.width};
  };
  const shown = (e) => getComputedStyle(e).display !== "none"
    && e.getBoundingClientRect().width > 0;
  const cards = Array.from(
    document.querySelectorAll("#view-session .session-card")
  ).filter(shown).map((c) => ({id: c.id || c.className, ...box(c)}));
  const hyg = document.getElementById("session-hygiene-card");
  const head = hyg.querySelector(".sh-head");
  const kids = Array.from(head.querySelectorAll("*")).filter(shown)
    .map((k) => ({cls: k.className, ...box(k)}));
  const grid = document.querySelector("#view-session .session-grid");
  const rows = Array.from(
    document.querySelectorAll("#session-matches .history-match-row")
  ).map((li) => ({
    h: li.getBoundingClientRect().height,
    dims: Array.from(li.querySelectorAll(":scope > .dim")).map((d) => ({
      t: d.textContent, h: d.getBoundingClientRect().height,
      lh: parseFloat(getComputedStyle(d).lineHeight)
        || parseFloat(getComputedStyle(d).fontSize) * 1.25,
    })),
  }));
  return {
    rows,
    cards,
    hyg: box(hyg),
    hygInner: {
      left: hyg.getBoundingClientRect().left + hyg.clientLeft,
      right: hyg.getBoundingClientRect().left + hyg.clientLeft
        + hyg.clientWidth,
    },
    kids,
    tracks: getComputedStyle(grid).gridTemplateColumns.trim()
      .split(/\\s+/).length,
  };
}"""

_TOOLBAR = """() => {
  const bar = document.querySelector("#view-user-builds .ub-toolbar");
  const br = bar.getBoundingClientRect();
  const shown = (e) => getComputedStyle(e).display !== "none"
    && e.getBoundingClientRect().width > 0;
  const kids = Array.from(bar.children).filter(shown).map((k) => {
    const r = k.getBoundingClientRect();
    return {id: k.id || k.className, left: r.left, right: r.right};
  });
  const inp = document.getElementById("ub-champion-input");
  const ir = inp.getBoundingClientRect();
  const rows = Array.from(document.querySelectorAll(".ub-build-row"))
    .map((row) => {
      const meta = row.querySelector(".ub-build-meta").getBoundingClientRect();
      const items = row.querySelector(".ub-build-items");
      const ib = items.getBoundingClientRect();
      const btns = Array.from(row.querySelectorAll(":scope > button"))
        .map((b) => b.getBoundingClientRect());
      const rr = row.getBoundingClientRect();
      const cs = getComputedStyle(row);
      return {
        metaW: meta.width, metaBottom: meta.bottom,
        rowRight: rr.right - parseFloat(cs.borderRightWidth)
          - parseFloat(cs.paddingRight),
        icons: Array.from(items.querySelectorAll(".ub-build-item-icon"))
          .map((i) => {
            const r = i.getBoundingClientRect();
            return {left: r.left, right: r.right};
          }),
        itemsLeft: ib.left, itemsRight: ib.right,
        btns: btns.map((b) => ({top: b.top, right: b.right, h: b.height})),
      };
    });
  const grid = document.getElementById("ub-sp-grid");
  const gr = grid.getBoundingClientRect();
  const spells = grid.offsetParent === null ? [] : Array.from(
    grid.querySelectorAll(".ub-sp-cell")
  ).map((c) => {
    const r = c.getBoundingClientRect();
    return {left: r.left, right: r.right, w: r.width, h: r.height};
  });
  return {
    spells, spLeft: gr.left, spRight: gr.right,
    left: br.left, right: br.right, kids, rows,
    inputW: ir.width, inputH: ir.height, value: inp.value,
  };
}"""


def _open(pw_browser, mock_server, view, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": vp[0], "height": vp[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1#{view}",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    return ctx, page, errors


def _assert_section_fits(page, sec_id, tag):
    s = page.evaluate(_SECTION, sec_id)
    assert s["display"] != "none", f"{tag}: {sec_id} hidden: {s}"
    assert s["sw"] <= s["cw"], (
        f"{tag}: {sec_id} scrolls sideways, scrollWidth {s['sw']} > "
        f"clientWidth {s['cw']}"
    )
    return s


@pytest.mark.parametrize("vp", _WIDTHS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_session_view_fits_and_cards_hold_their_head(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _open(pw_browser, mock_server, "session", vp)
    try:
        page.wait_for_function(
            "() => { const g = document.querySelector('#session-games');"
            " const t = g && g.textContent.trim();"
            " return t && t !== '-'; }",
            timeout=10_000,
        )
        page.wait_for_selector(
            "#session-hygiene-card .sh-conf", timeout=10_000
        )
        page.evaluate(_SETTLE)
        tag = f"session@{vp[0]}"
        s = _assert_section_fits(page, "view-session", tag)
        m = page.evaluate(_SESSION)
        assert len(m["cards"]) >= 4, f"{tag}: too few cards: {m['cards']}"
        for c in m["cards"]:
            assert c["left"] >= s["left"] - 0.5, (tag, c, s)
            assert c["right"] <= s["right"] + 0.5, (
                f"{tag}: card {c['id']} right {c['right']} past the view's "
                f"padding edge {s['right']}"
            )
        assert len(m["kids"]) >= 3, f"{tag}: head lost a part: {m['kids']}"
        for k in m["kids"]:
            assert k["left"] >= m["hygInner"]["left"] - 0.5, (tag, k, m)
            assert k["right"] <= m["hygInner"]["right"] + 0.5, (
                f"{tag}: SHOULD I QUEUE head part {k['cls']} right "
                f"{k['right']} past its card {m['hygInner']['right']}"
            )
        assert len(m["rows"]) >= 6, f"{tag}: MATCHES rows missing: {m}"
        for row in m["rows"]:
            assert len(row["dims"]) == 2, (tag, row)
            for d in row["dims"]:
                # the KDA and the time never break inside themselves
                assert d["h"] < 1.5 * d["lh"], (
                    f"{tag}: MATCHES value {d['t']!r} broke onto two lines "
                    f"({d['h']} px tall)"
                )
        if vp[0] == 1920:
            for row in m["rows"]:
                assert row["h"] <= 42 + 0.5, (
                    f"{tag}: a MATCHES row wrapped at 1920: {row}"
                )
            assert m["tracks"] == 2, f"{tag}: 2-up grid lost: {m['tracks']}"
            tops = {round(k["top"]) for k in m["kids"]
                    if k["cls"].split()[0] in ("sh-score", "sh-state",
                                               "sh-conf")}
            # one line: the three parts share a row (baseline-aligned, so
            # their tops may differ by the chip padding, never by a line)
            assert max(tops) - min(tops) < 20, (
                f"{tag}: SHOULD I QUEUE head wrapped at 1920: {m['kids']}"
            )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("editing", [False, True], ids=["rest", "editing"])
@pytest.mark.parametrize("vp", _WIDTHS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_user_builds_view_fits_and_search_field_shrinks(
    mock_server, pw_browser, vp, editing
):
    ctx, page, errors = _open(pw_browser, mock_server, "user-builds", vp)
    try:
        page.wait_for_selector(".ub-build-row", timeout=10_000)
        if editing:
            page.fill("#ub-champion-input", "Tristana")
            page.dispatch_event("#ub-champion-input", "change")
            page.wait_for_selector(".ub-build-row", timeout=10_000)
            page.click("#ub-add-btn")
            page.wait_for_function(
                "() => { const p = document.querySelector('#ub-form-pane');"
                " return p && !p.hasAttribute('hidden'); }",
                timeout=5_000,
            )
        else:
            page.fill("#ub-champion-input", "Tristana")
        page.evaluate(_SETTLE)
        tag = f"user-builds@{vp[0]}:{'editing' if editing else 'rest'}"
        _assert_section_fits(page, "view-user-builds", tag)
        t = page.evaluate(_TOOLBAR)
        for k in t["kids"]:
            assert k["left"] >= t["left"] - 0.5, (tag, k, t)
            assert k["right"] <= t["right"] + 0.5, (
                f"{tag}: toolbar child {k['id']} right {k['right']} past "
                f"the toolbar {t['right']}"
            )
        assert t["value"] == "Tristana", (tag, t)
        if editing:
            # the spell grid: every cell inside it, at the hit floor
            assert len(t["spells"]) >= 6, f"{tag}: spell cells missing: {t}"
            for c in t["spells"]:
                assert c["left"] >= t["spLeft"] - 0.5, (tag, c)
                assert c["right"] <= t["spRight"] + 0.5, (
                    f"{tag}: a spell cell runs past the spell grid: {c}"
                )
                assert c["w"] >= 42 - 0.5 and c["h"] >= 42 - 0.5, (tag, c)
        assert len(t["rows"]) >= 3, f"{tag}: build rows missing: {t}"
        # anti-vacuity: the fixture's rows carry icons to check
        assert sum(len(r["icons"]) for r in t["rows"]) >= 6, (tag, t["rows"])
        for row in t["rows"]:
            for i in row["icons"]:
                assert i["left"] >= row["itemsLeft"] - 0.5, (tag, row)
                assert i["right"] <= row["itemsRight"] + 0.5, (
                    f"{tag}: a build row's item icon runs past its column "
                    f"({i['right']} > {row['itemsRight']}, column "
                    f"{row['metaW']} px wide)"
                )
            assert len(row["btns"]) == 2, (tag, row)
            for b in row["btns"]:
                assert b["h"] >= 42 - 0.5, (tag, row)
            assert abs(row["btns"][1]["right"] - row["rowRight"]) <= 0.5, (
                f"{tag}: Delete left the row's right edge: {row}"
            )
            if vp[0] <= 480:
                # name, sub-line and icons get a line of their own
                assert row["metaW"] >= 150, (tag, row)
                for b in row["btns"]:
                    assert b["top"] >= row["metaBottom"] - 0.5, (tag, row)
            else:
                # one line: the buttons sit beside the name
                for b in row["btns"]:
                    assert b["top"] < row["metaBottom"], (tag, row)
        assert t["inputH"] >= 42 - 0.5, f"{tag}: field below hit floor: {t}"
        if vp[0] == 1920:
            assert abs(t["inputW"] - 360) <= 0.5, (
                f"{tag}: the field moved off its 360 px basis: {t}"
            )
        else:
            assert t["inputW"] >= 200, f"{tag}: field too narrow: {t}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
