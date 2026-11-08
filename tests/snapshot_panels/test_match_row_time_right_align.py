"""
tests/snapshot_panels/test_match_row_time_right_align.py
A Session MATCHES row and a History match row keep their time on the row's
right edge at every width down to the 320 px reflow floor, and nothing in
either row runs past the row (s144 lane uiux, S144-U-198).

Both rows are built by web/js/main.js (the Session renderer and
_historyMatchRowEl) with the same markup, and both carried their layout in
inline style attributes (`flex:1; margin-left:8px` on the name,
`margin-left:8px` on the time), which no stylesheet rule can override, so
the row could not be taught to wrap cleanly. Measured before the fix
(ui_mock, headless Chromium):
  - Session, 360 and 320 px: the time dropped to its own line at the row's
    LEFT edge (x 73 in a row whose content box ends at 297 / 257), under the
    grade, instead of staying in the right-hand column the other rows use.
  - History, 480 to 400 px: the name was squeezed to 36 px, so "Jinx - SR"
    broke over two lines beside a one-line 173 px timestamp; 360 and 320 px:
    the timestamp itself broke over three lines and ran 7 to 56 px past the
    row's content box (right 304 / 313 against 297 / 257).
  - History, 1201 px (two-column card): "Tristana - SR" broke over two lines
    while the timestamp kept one.

Contract pinned here, ui_mock, at 1920, 1201, 721, 480, 400, 360 and 320 px,
both views:
  - no element inside a match row carries an inline style; the name, KDA
    and time carry the hmr-name / hmr-kda / hmr-time classes;
  - the time's right edge is the row's content-box right edge, on one line
    or wrapped;
  - every child of the row sits inside the row's content box;
  - the grade pip stays at the row's left, on the first line of the name
    (an uncapped one-line name pushed "RenataGlasc - Ranked Solo" to a line
    of its own at 320 px and left the pip alone, justified to the RIGHT);
  - the KDA and the time never break inside themselves, and the name does
    not break when the row's content box could hold it on one line;
  - the view does not scroll sideways;
  - anti-vacuity: at 1920 every row is one line at the 42 px floor with the
    name before the KDA before the time, and at 320 at least one row in
    each view has its time on a line below its name.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_WIDTHS = (
    (1920, 920), (1201, 900), (721, 900), (480, 800), (400, 760),
    (360, 740), (320, 640),
)

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_ROWS = """(listSel) => {
  const list = document.querySelector(listSel);
  const sec = list.closest("section");
  const lh = (e) => parseFloat(getComputedStyle(e).lineHeight)
    || parseFloat(getComputedStyle(e).fontSize) * 1.25;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,
            w: r.width, h: r.height, lh: lh(e), t: e.textContent};
  };
  // the name's one-line width, measured on a detached-from-flow clone
  const oneLine = (e) => {
    const c = e.cloneNode(true);
    c.removeAttribute("style");
    c.style.position = "absolute";
    c.style.visibility = "hidden";
    c.style.whiteSpace = "nowrap";
    c.style.width = "auto";
    document.body.appendChild(c);
    const w = c.getBoundingClientRect().width;
    c.remove();
    return w;
  };
  const rows = Array.from(
    list.querySelectorAll(":scope > .history-match-row")
  ).map((li) => {
    const cs = getComputedStyle(li);
    const r = li.getBoundingClientRect();
    const one = (sel) => {
      const e = li.querySelector(":scope > " + sel);
      return e ? box(e) : null;
    };
    const name = li.querySelector(":scope > .hmr-name");
    return {
      h: r.height,
      cl: r.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
      cr: r.right - parseFloat(cs.borderRightWidth)
        - parseFloat(cs.paddingRight),
      styled: Array.from(li.querySelectorAll("[style]"))
        .map((e) => e.outerHTML.slice(0, 80)),
      kids: Array.from(li.children).map(box),
      name: one(".hmr-name"),
      nameMax: name ? oneLine(name) : null,
      kda: one(".hmr-kda"),
      time: one(".hmr-time"),
      grade: one(".home-recent-grade"),
    };
  });
  return {sw: sec.scrollWidth, cw: sec.clientWidth, id: sec.id, rows};
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


@pytest.mark.parametrize("view", ["session", "history"])
@pytest.mark.parametrize("vp", _WIDTHS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_match_row_time_holds_the_right_edge(
    mock_server, pw_browser, vp, view
):
    ctx, page, errors = _open(pw_browser, mock_server, view, vp)
    try:
        if view == "history":
            list_sel = "#history-match-list"
            page.wait_for_selector(".history-session-row", timeout=10_000)
            page.click(".history-session-row")
        else:
            list_sel = "#session-matches"
        page.wait_for_selector(
            f"{list_sel} > .history-match-row", timeout=10_000
        )
        page.evaluate(_SETTLE)
        m = page.evaluate(_ROWS, list_sel)
        tag = f"{view}@{vp[0]}"
        assert m["sw"] <= m["cw"], (
            f"{tag}: {m['id']} scrolls sideways ({m['sw']} > {m['cw']})"
        )
        rows = m["rows"]
        assert len(rows) >= 4, f"{tag}: match rows missing: {m}"
        for row in rows:
            # the row element itself carries cursor:pointer from the HIST1
            # wiring; querySelectorAll looks only inside it
            assert not row["styled"], (
                f"{tag}: inline style left in a match row: {row['styled']}"
            )
            for part in ("name", "kda", "time", "grade"):
                assert row[part] is not None, f"{tag}: no {part}: {row}"
            g, n = row["grade"], row["name"]
            # the name still reads "<champion> <middle dot> <mode>": the
            # source writes the dot as the JS escape \u00b7 (ASCII source)
            assert n["t"].count(" \u00b7 ") == 1, (
                f"{tag}: name lost its separator: {n['t']!r}"
            )
            # the grade pip leads the name on the row's first line, at the
            # left; it is never left alone on a line or pushed to the right
            assert g["right"] <= n["left"] + 0.5, (
                f"{tag}: grade {g['t']!r} is not left of the name: {row}"
            )
            assert g["top"] < n["top"] + n["lh"], (
                f"{tag}: grade {g['t']!r} is on a line of its own: {row}"
            )
            assert g["left"] <= row["cl"] + 40, (
                f"{tag}: grade {g['t']!r} left the row's left edge: {row}"
            )
            t = row["time"]
            assert abs(t["right"] - row["cr"]) <= 0.5, (
                f"{tag}: time {t['t']!r} right {t['right']} is not on the "
                f"row's right edge {row['cr']}"
            )
            for k in row["kids"]:
                assert k["left"] >= row["cl"] - 0.5, (tag, k, row["cl"])
                assert k["right"] <= row["cr"] + 0.5, (
                    f"{tag}: {k['t']!r} right {k['right']} past the row's "
                    f"content box {row['cr']}"
                )
            for part in ("kda", "time"):
                d = row[part]
                assert d["h"] < 1.5 * d["lh"], (
                    f"{tag}: {part} {d['t']!r} broke onto two lines "
                    f"({d['h']} px tall)"
                )
            # the name breaks only when the row's whole content box (less
            # the grade pip, its gaps and a result glyph) cannot hold it
            if row["nameMax"] <= row["cr"] - row["cl"] - 60:
                n = row["name"]
                assert n["h"] < 1.5 * n["lh"], (
                    f"{tag}: name {n['t']!r} broke onto two lines "
                    f"({n['h']} px tall, needs {row['nameMax']} px)"
                )
        if vp[0] == 1920:
            for row in rows:
                assert row["h"] <= 42 + 0.5, f"{tag}: row wrapped: {row}"
                assert (row["name"]["right"] <= row["kda"]["left"]
                        and row["kda"]["right"] <= row["time"]["left"]), (
                    f"{tag}: name, KDA, time out of order: {row}"
                )
        if vp[0] == 320:
            wrapped = [r for r in rows
                       if r["time"]["top"] >= r["name"]["bottom"] - 0.5]
            assert wrapped, f"{tag}: no row wrapped its time at 320: {rows}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_WRAP_STATE = """(sel) => Array.from(document.querySelectorAll(sel)).map((li) => {
  const dim = li.querySelector(":scope > .dim");
  return {
    wrap: getComputedStyle(li).flexWrap,
    justify: getComputedStyle(li).justifyContent,
    dimSpace: dim ? getComputedStyle(dim).whiteSpace : null,
  };
})"""


@pytest.mark.parametrize("vp", ((1920, 920), (320, 640)),
                         ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_wrap_reaches_match_rows_only(mock_server, pw_browser, vp):
    # S144-U-213: the wrap rules moved into RM-726 slice HS-4 and are scoped
    # by :has(> .hmr-name) instead of the two list selectors. The Session
    # REPLAYED CHAMPIONS rows (#session-champs) share the history-match-row
    # class but have no .hmr-name, so they keep the base row: no wrap, the
    # flex-start packing, a .dim "Ng" cell that may wrap. The ui_mock Session
    # carries one champion played twice (Jinx), so that card renders a row.
    ctx, page, errors = _open(pw_browser, mock_server, "session", vp)
    try:
        page.wait_for_selector(
            "#session-matches > .history-match-row", timeout=10_000
        )
        page.wait_for_selector(
            "#session-champs > .history-match-row", timeout=10_000
        )
        page.evaluate(_SETTLE)
        champs = page.evaluate(_WRAP_STATE, "#session-champs > .history-match-row")
        matches = page.evaluate(
            _WRAP_STATE, "#session-matches > .history-match-row"
        )
        page.goto(
            mock_server.url + "/?ui_mock=1#history",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_selector(".history-session-row", timeout=10_000)
        page.click(".history-session-row")
        page.wait_for_selector(
            "#history-match-list > .history-match-row", timeout=10_000
        )
        page.evaluate(_SETTLE)
        history = page.evaluate(
            _WRAP_STATE, "#history-match-list > .history-match-row"
        )
    finally:
        ctx.close()
    assert not errors, errors
    assert champs and matches and history, (champs, matches, history)
    for row in champs:
        assert row == {"wrap": "nowrap", "justify": "normal",
                       "dimSpace": "normal"}, f"champ row: {row}"
    for row in matches + history:
        assert row == {"wrap": "wrap", "justify": "flex-end",
                       "dimSpace": "nowrap"}, f"match row: {row}"
