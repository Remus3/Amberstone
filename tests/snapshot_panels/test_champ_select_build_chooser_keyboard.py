"""
tests/snapshot_panels/test_champ_select_build_chooser_keyboard.py
The Champ Select build chooser is keyboard-usable (session 144, lane uiux,
RM-971).

Measured headless before the fix, on the ?ui_mock=1 sr / aram / arena pages:
every clickable in .csv-builds (the legacy .csv-build-row and the collapsed
variant's .csv-build-path-row) had tabIndex -1, no key handler and no
:focus-visible rule, so a build could be picked only with the mouse. A
path-row click also re-renders the central pane through innerHTML
(_csvScheduleRender -> _csvRenderCentralPane), which destroys the focused
node and throws focus to <body> (lane doc section 6, trap 2).

Contract pinned here:
- every chooser click target is in the tab order (tabindex 0, role button,
  aria-pressed mirroring its selected state); the collapsed OUTER row, whose
  click is a no-op, stays out of the tab order;
- Tab moves from one path row to the next;
- Enter and Space activate a row like a click;
- focus survives the central-pane rebuild (re-found by data-variant +
  data-path-key), and a rebuild never STEALS focus that was elsewhere;
- a keyboard-focused row shows a focus ring (computed box-shadow).

Drive path: /?ui_mock=1&mode=<m>#champ-select with an empty /api/state
(the same path as test_champ_select_view.py). sr + arena render a collapsed
variant with path rows; aram renders one legacy row.
"""
import pytest

from tests.snapshot_panels.test_champ_select_view import _open_champ_select

_CLICKABLE = (
    "#view-champ-select .csv-builds .csv-build-row:not(.csv-build-row-collapsed),"
    " #view-champ-select .csv-builds .csv-build-path-row"
)

_ACTIVE_DESC_JS = """() => {
  const a = document.activeElement;
  if (!a || a === document.body) return null;
  return {
    cls: a.className || "",
    variant: a.dataset ? (a.dataset.variant || "") : "",
    path: a.dataset ? (a.dataset.pathKey || "") : "",
    inBuilds: !!a.closest(".csv-builds"),
  };
}"""


def _wait_rows(page) -> None:
    page.wait_for_function(
        "(s) => document.querySelectorAll(s).length > 0",
        arg=_CLICKABLE,
        timeout=10_000,
    )


def _path_keys(page) -> list:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'#view-champ-select .csv-builds .csv-build-path-row'))"
        ".map(r => r.dataset.pathKey)"
    )


def _focus_path(page, key: str) -> None:
    # Focus by keyboard semantics: a programmatic focus followed by a real
    # key press, so :focus-visible matches as it would after Tab.
    page.evaluate(
        "(k) => document.querySelector('#view-champ-select .csv-builds"
        " .csv-build-path-row[data-path-key=\"' + k + '\"]').focus()",
        key,
    )


def _active_path(page) -> str:
    return page.evaluate(
        "() => { const r = document.querySelector('#view-champ-select"
        " .csv-builds .csv-build-path-row.is-active'); return r ?"
        " r.dataset.pathKey : ''; }"
    )


def _wait_rebuilt(page) -> None:
    # The pre-rebuild nodes carry a JS marker; the rebuild replaces them.
    page.wait_for_function(
        "() => { const r = document.querySelector('#view-champ-select"
        " .csv-builds .csv-build-path-row, #view-champ-select .csv-builds"
        " .csv-build-row'); return !!r && !r.__s144u03; }",
        timeout=10_000,
    )


def _mark_nodes(page) -> None:
    page.evaluate(
        "() => document.querySelectorAll('#view-champ-select .csv-builds"
        " .csv-build-path-row, #view-champ-select .csv-builds .csv-build-row')"
        ".forEach(r => { r.__s144u03 = 1; })"
    )


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_every_chooser_target_is_in_the_tab_order(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        _wait_rows(page)
        rows = page.evaluate(
            "(s) => Array.from(document.querySelectorAll(s)).map(r => ({"
            " tab: r.tabIndex, role: r.getAttribute('role'),"
            " pressed: r.getAttribute('aria-pressed'),"
            " on: r.classList.contains('selected')"
            " || r.classList.contains('is-active') }))",
            _CLICKABLE,
        )
        assert rows, mode
        for r in rows:
            assert r["tab"] == 0, (mode, r)
            assert r["role"] == "button", (mode, r)
            assert r["pressed"] == ("true" if r["on"] else "false"), (mode, r)
        outer = page.evaluate(
            "() => Array.from(document.querySelectorAll('#view-champ-select"
            " .csv-builds .csv-build-row-collapsed')).map(r => r.tabIndex)"
        )
        assert all(t == -1 for t in outer), (mode, outer)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode,key", [("sr", "Enter"), ("arena", " ")])
def test_keyboard_picks_a_path_and_focus_survives_the_rebuild(
    mode, key, mock_server, pw_browser
):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        _wait_rows(page)
        keys = _path_keys(page)
        assert len(keys) >= 2, (mode, keys)
        before = _active_path(page)
        target = next(k for k in keys if k != before)
        first = keys[0]
        # Tab reachability: Tab from the first path row lands on the second.
        _focus_path(page, first)
        page.keyboard.press("Tab")
        got = page.evaluate(_ACTIVE_DESC_JS)
        assert got and got["path"] == keys[1], (mode, got)
        _focus_path(page, target)
        page.keyboard.press("Shift")
        ring = page.evaluate(
            "() => getComputedStyle(document.activeElement).boxShadow"
        )
        assert ring and ring != "none", (mode, ring)
        _mark_nodes(page)
        page.keyboard.press(key)
        _wait_rebuilt(page)
        assert _active_path(page) == target, mode
        got = page.evaluate(_ACTIVE_DESC_JS)
        assert got and got["inBuilds"] and got["path"] == target, (mode, got)
        pressed = page.evaluate(
            "(k) => document.querySelector('#view-champ-select .csv-builds"
            " .csv-build-path-row[data-path-key=\"' + k + '\"]')"
            ".getAttribute('aria-pressed')",
            target,
        )
        assert pressed == "true", (mode, pressed)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_keyboard_activates_the_legacy_row(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        _wait_rows(page)
        sel = "#view-champ-select .csv-builds .csv-build-row:not(.csv-build-row-collapsed)"
        # One row on the aram page: clear its selection, then Enter must
        # re-select it exactly as a click does.
        page.evaluate(
            "(s) => { const r = document.querySelector(s);"
            " r.classList.remove('selected'); r.focus(); }",
            sel,
        )
        page.keyboard.press("Enter")
        state = page.evaluate(
            "(s) => { const r = document.querySelector(s); return"
            " [r.classList.contains('selected'), r.getAttribute('aria-pressed'),"
            " document.activeElement === r]; }",
            sel,
        )
        assert state == [True, "true", True], state
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [aram]: {errors[:3]}"


def test_a_rebuild_never_steals_focus(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "sr")
    try:
        _wait_rows(page)
        page.evaluate(
            "() => { if (document.activeElement) document.activeElement.blur(); }"
        )
        _mark_nodes(page)
        page.evaluate(
            "() => document.dispatchEvent(new Event('rc:lol-descriptions-ready'))"
        )
        _wait_rebuilt(page)
        assert page.evaluate(_ACTIVE_DESC_JS) is None
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


# -- RM-972 --------------------------------------------------------------
# Measured headless after RM-971: on the aram page the legacy row sits
# flush against an overflow-x: hidden card body, so the outer 2px
# --focus-ring was cut off on its left edge. And aria-pressed on a path row
# mirrored is-active even when its collapsed variant was not the selected
# one, so a chooser with two collapsed variants (or a collapsed variant
# plus a legacy row) announced two pressed builds.

_RING_BOX_JS = r"""(el) => {
  const bs = getComputedStyle(el).boxShadow || "none";
  if (bs === "none") return {ring: false};
  const inset = /\binset\b/.test(bs);
  const px = (bs.match(/-?[\d.]+px/g) || []).map(parseFloat);
  const spread = inset ? 0 : (px[3] || 0);
  const r = el.getBoundingClientRect();
  const box = {l: r.left - spread, t: r.top - spread,
               r: r.right + spread, b: r.bottom + spread};
  const cuts = [];
  for (let a = el.parentElement; a; a = a.parentElement) {
    const s = getComputedStyle(a);
    const ar = a.getBoundingClientRect();
    const cl = ar.left + a.clientLeft, ct = ar.top + a.clientTop;
    const cr = cl + a.clientWidth, cb = ct + a.clientHeight;
    if (s.overflowX !== "visible" && (box.l < cl - 0.5 || box.r > cr + 0.5)) {
      cuts.push(["x", a.className, box.l - cl, cr - box.r]);
    }
    if (s.overflowY !== "visible" && (box.t < ct - 0.5 || box.b > cb + 0.5)) {
      cuts.push(["y", a.className, box.t - ct, cb - box.b]);
    }
  }
  return {ring: true, inset, cuts, bs};
}"""


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_the_focus_ring_is_never_clipped(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        _wait_rows(page)
        n = page.evaluate(
            "(s) => document.querySelectorAll(s).length", _CLICKABLE
        )
        assert n, mode
        for i in range(n):
            page.evaluate(
                "([s, i]) => document.querySelectorAll(s)[i].focus()",
                [_CLICKABLE, i],
            )
            page.keyboard.press("Shift")
            got = page.evaluate_handle("() => document.activeElement")
            res = page.evaluate(_RING_BOX_JS, got)
            assert res["ring"], (mode, i)
            assert res["cuts"] == [], (mode, i, res)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def _sr_fixture_with(extra_variants: list) -> dict:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"
    sr = json.loads((root / "champ_select_sr.json").read_text(encoding="utf-8"))
    sr["build_variants"]["Jinx|sr"] = (
        list(sr["build_variants"]["Jinx|sr"]) + extra_variants
    )
    return sr


def _second_collapsed_variant() -> dict:
    import copy

    v = copy.deepcopy(_sr_fixture_with([])["build_variants"]["Jinx|sr"][0])
    v["key"] = "sr-collapsed-b"
    v["label"] = "Second set"
    for p in v.get("build_paths") or []:
        p["key"] = "b-" + str(p.get("key") or "")
    return v


def _legacy_variant() -> dict:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"
    aram = json.loads(
        (root / "champ_select_aram.json").read_text(encoding="utf-8")
    )
    v = dict(aram["build_variants"]["Jinx|aram"][0])
    v["key"] = "sr-legacy"
    return v


def _open_sr_with(pw_browser, mock_server, fixture: dict, init: str = ""):
    import json

    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": 1920, "height": 1080},
        service_workers="block",
    )
    body = json.dumps(fixture)
    ctx.route(
        "**/data/ui_mock/champ_select_sr.json",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body
        ),
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    if init:
        page.add_init_script(init)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    return ctx, page, errors


_PRESSED_JS = """(s) => Array.from(document.querySelectorAll(s))
  .filter(r => r.getAttribute('aria-pressed') === 'true')
  .map(r => (r.dataset.variant || '') + ':' + (r.dataset.pathKey || ''))"""


def _wait_targets(page, count: int) -> None:
    page.wait_for_function(
        "([s, n]) => document.querySelectorAll(s).length >= n",
        arg=[_CLICKABLE, count],
        timeout=10_000,
    )


def test_two_collapsed_variants_announce_one_pressed_build(
    mock_server, pw_browser
):
    fixture = _sr_fixture_with([_second_collapsed_variant()])
    n_paths = sum(
        len(v.get("build_paths") or [])
        for v in fixture["build_variants"]["Jinx|sr"]
    )
    ctx, page, errors = _open_sr_with(pw_browser, mock_server, fixture)
    try:
        _wait_targets(page, n_paths)
        pressed = page.evaluate(_PRESSED_JS, _CLICKABLE)
        assert len(pressed) == 1, pressed
        assert pressed[0].startswith("sr-collapsed:"), pressed
        # Pick a path in the SECOND variant: after the rebuild it is the one
        # pressed build.
        target = page.evaluate(
            "() => document.querySelector('#view-champ-select .csv-builds"
            " .csv-build-path-row[data-variant=\"sr-collapsed-b\"]')"
            ".dataset.pathKey"
        )
        _mark_nodes(page)
        page.click(
            "#view-champ-select .csv-builds .csv-build-path-row"
            f"[data-variant=\"sr-collapsed-b\"][data-path-key=\"{target}\"]"
        )
        _wait_rebuilt(page)
        _wait_targets(page, n_paths)
        pressed = page.evaluate(_PRESSED_JS, _CLICKABLE)
        assert pressed == [f"sr-collapsed-b:{target}"], pressed
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


def test_a_legacy_pick_unpresses_the_collapsed_path(mock_server, pw_browser):
    fixture = _sr_fixture_with([_legacy_variant()])
    n_paths = len(fixture["build_variants"]["Jinx|sr"][0]["build_paths"])
    ctx, page, errors = _open_sr_with(pw_browser, mock_server, fixture)
    try:
        _wait_targets(page, n_paths + 1)
        pressed = page.evaluate(_PRESSED_JS, _CLICKABLE)
        assert len(pressed) == 1 and pressed[0].startswith("sr-collapsed:"), (
            pressed
        )
        legacy = (
            "#view-champ-select .csv-builds"
            " .csv-build-row[data-variant=\"sr-legacy\"]"
        )
        page.focus(legacy)
        page.keyboard.press("Enter")
        pressed = page.evaluate(_PRESSED_JS, _CLICKABLE)
        assert pressed == ["sr-legacy:"], pressed
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


# -- RM-973 --------------------------------------------------------------
# Measured headless after RM-972: a path-row click moved is-active and
# aria-pressed but never the outer row's `selected` class, so after a legacy
# pick then a path pick the LEGACY row still read selected until the rAF
# re-render repaired it. And a saved "<variant>:<path>" whose path key no
# longer exists in build_paths (a path renamed between patches) was kept as
# the active path, so no path row was is-active, none was pressed, and the
# rune side panel followed a build id that matches nothing.

_SELECTED_JS = """() => Array.from(document.querySelectorAll(
  '#view-champ-select .csv-builds .csv-build-row.selected'))
  .map(r => r.dataset.variant || '')"""


def test_a_path_click_moves_selected_onto_its_variant(mock_server, pw_browser):
    fixture = _sr_fixture_with([_legacy_variant()])
    n_paths = len(fixture["build_variants"]["Jinx|sr"][0]["build_paths"])
    ctx, page, errors = _open_sr_with(pw_browser, mock_server, fixture)
    try:
        _wait_targets(page, n_paths + 1)
        legacy = (
            "#view-champ-select .csv-builds"
            " .csv-build-row[data-variant=\"sr-legacy\"]"
        )
        page.click(legacy)
        _wait_targets(page, n_paths + 1)
        page.wait_for_function(
            "(s) => { const r = document.querySelector(s);"
            " return !!r && r.classList.contains('selected'); }",
            arg=legacy,
            timeout=10_000,
        )
        # Click a path row and read the classes in the SAME task, before the
        # rAF-scheduled re-render can repair them.
        got = page.evaluate(
            "() => { const p = document.querySelector('#view-champ-select"
            " .csv-builds .csv-build-path-row[data-variant=\"sr-collapsed\"]');"
            " p.click(); return Array.from(document.querySelectorAll("
            "'#view-champ-select .csv-builds .csv-build-row.selected'))"
            ".map(r => r.dataset.variant || ''); }"
        )
        assert got == ["sr-collapsed"], got
        # And the re-render agrees.
        page.wait_for_function(
            "() => { const r = document.querySelector('#view-champ-select"
            " .csv-builds .csv-build-row-collapsed');"
            " return !!r && r.classList.contains('selected'); }",
            timeout=10_000,
        )
        assert page.evaluate(_SELECTED_JS) == ["sr-collapsed"]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


def test_a_stale_saved_path_key_falls_back_to_the_primary_path(
    mock_server, pw_browser
):
    fixture = _sr_fixture_with([])
    paths = fixture["build_variants"]["Jinx|sr"][0]["build_paths"]
    primary = next(p["key"] for p in paths if p.get("_is_primary"))
    assert "renamed-path" not in [p["key"] for p in paths]
    seed = (
        "try { localStorage.setItem('rc-ingame-build-Jinx',"
        " 'sr-collapsed:renamed-path'); } catch (_) {}"
    )
    ctx, page, errors = _open_sr_with(pw_browser, mock_server, fixture, seed)
    try:
        _wait_targets(page, len(paths))
        assert page.evaluate(
            "() => localStorage.getItem('rc-ingame-build-Jinx')"
        ) == "sr-collapsed:renamed-path"
        assert _active_path(page) == primary
        pressed = page.evaluate(_PRESSED_JS, _CLICKABLE)
        assert pressed == [f"sr-collapsed:{primary}"], pressed
        outer = page.evaluate(
            "() => document.querySelector('#view-champ-select .csv-builds"
            " .csv-build-row-collapsed').dataset.activePath"
        )
        assert outer == primary, outer
        # The rune side panel follows the same resolved build.
        build_id = page.evaluate(
            "() => { const s = document.querySelector('#view-champ-select"
            " .csv-rune-side'); return s ? s.dataset.buildId : null; }"
        )
        assert build_id == f"sr-collapsed:{primary}", build_id
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"
