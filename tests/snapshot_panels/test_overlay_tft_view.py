"""
tests/snapshot_panels/test_overlay_tft_view.py
TFT overlay panels on the rendered overlay route (S134 N9) - the 5-phase UI
fixture audit as executable checks, on REAL sanitised TFT payloads.

QA match 3 (ops/runtime/tft_qa/20261025-085349/QA_REPORT.md N9): the overlay was
ON from 1-2 but painted no TFT data, and its panel menu listed only SR / ARAM
panels. web/js/lib/overlay_tft.js now renders three TFT widgets from the full
/api/state (vitals, board, lobby HP) and web/js/lib/overlay_layout.js shows only
the TFT set - and lists only TFT panels - in a TFT match.

Drive path: a LIVE (non-ui_mock) SSE envelope on /?overlay=1, exactly what the
rc-shell overlay window loads, with the fixtures
tests/snapshot_panels/fixtures/tft_overlay_{sentinel,live,feed}.json (real
states from that match, identity keys dropped; "feed" adds the OCR fields RC
does not serve yet, read off the same moment's frame, and the S134 P0-F
board-panel lobby / board rows in their served shape).

Audit phases:
  STRUCTURE    only TFT widgets + the launcher paint in TFT; positions match the
               registry defaults; every painted box clears the TFT HUD keep-out
               regions at 1920x1080 AND at 2560x1440 (ovscale 1.33), using the
               same table as tests/test_overlay_tft_layout.py.
  TYPOGRAPHY   value / label / chip sizes on the overlay type scale; no value or
               unit name clipped (longest real name: Fiddlesticks).
  HIT-TARGETS  widget bodies are click-through (no zone inside except the drag
               handle); the TFT menu rows keep the 42px target.
  ASCII        every painted string is 7-bit ASCII.
  HIERARCHY    HP > stage > unit chip > label; the vitals widget is the primary.
Plus NO-REFLOW (same boxes for the start-of-game placeholder, the live payload
and the full feed) and the League control (SR keeps its own panels + menu).
"""
import json
from pathlib import Path

from tests.test_overlay_tft_layout import KEEP_OUT, NATURAL_H, tft_default_boxes

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
SCRATCH = ROOT / "_scratch"

TFT_IDS = {"w-tft-hud", "w-tft-board", "w-tft-lobby"}

_VISIBLE_WIDGETS_JS = """() => {
  const z = parseFloat(getComputedStyle(document.body).zoom) || 1;
  const out = {};
  for (const el of document.querySelectorAll('.ovx-widget')) {
    const cs = getComputedStyle(el);
    if (el.hidden || cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    out[el.dataset.ovxId || el.id] = [r.left / z, r.top / z, r.right / z, r.bottom / z];
  }
  return out;
}"""


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _open(pw_browser, mock_server, data, viewport=(1920, 1080), query="?overlay=1"):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = data
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": viewport[0], "height": viewport[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query, wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _wait_tft(page):
    page.wait_for_function(
        "() => { const h = document.getElementById('ovt-hud');"
        " return h && !h.hidden && h.classList.contains('ovx-widget')"
        " && document.body.classList.contains('ovx-ready')"
        " && document.body.dataset.ovxGame === 'tft'; }",
        timeout=15_000,
    )
    # S136 T11: web/css/dashboard.css pulls Lato with display=swap, so a box
    # measured before the swap was 1px shorter (the no-reflow size checks
    # flaked 122 vs 123 px). Measure after the pending font loads settle.
    page.evaluate("() => document.fonts.ready.then(() => true)")


def _text(page, sel):
    return page.eval_on_selector(sel, "e => e.textContent")


def _val(page, key):
    return _text(page, f'#ovt-hud .ovt-cell[data-k="{key}"] .ovt-val')


def _fs(page, sel):
    return page.eval_on_selector(sel, "e => parseFloat(getComputedStyle(e).fontSize)")


def _overlap(a, b):
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return (round(dx), round(dy)) if dx > 0.5 and dy > 0.5 else None


def test_tft_overlay_paints_the_real_live_payload(mock_server, pw_browser):
    """STRUCTURE + ASCII: the real live payload paints the vitals + board; only
    TFT widgets and the launcher are on the field; League panels are off."""
    ctx, page, errors = _open(pw_browser, mock_server, _fixture("tft_overlay_live"))
    try:
        _wait_tft(page)
        visible = page.evaluate(_VISIBLE_WIDGETS_JS)
        assert set(visible) == {"w-launcher", "w-tft-hud", "w-tft-board"}, sorted(visible)
        assert _val(page, "hp") == "96"
        assert _val(page, "place") == "#2"
        assert _val(page, "alive") == "8"
        for k in ("stage", "level", "gold"):
            assert _val(page, k) == "-", k
        assert _text(page, "#ovt-hud .ovt-time") == "14:10"
        assert _text(page, "#ovt-hud .ovt-src") == "ROUND FEED"
        names = page.eval_on_selector_all("#ovt-board .ovt-unit-name", "els => els.map(e => e.textContent)")
        assert names[:7] == ["Yorick", "Xayah", "Karma", "Yunara", "Diana", "Ahri", "Elise"]
        assert names[7:] == [""] * 5, "fixed empty slots hold the geometry"
        assert _text(page, "#ovt-board .ovt-time") == "7"
        assert page.eval_on_selector("#ovt-lobby", "e => e.hidden"), "lobby is data-gated"
        assert page.eval_on_selector("#ovt-hud", "e => getComputedStyle(e).position") == "fixed"
        assert page.eval_on_selector("#ovt-hud", "e => e.dataset.ovxTier") == "primary"
        # ASCII: everything the TFT widgets paint.
        painted = page.evaluate(
            "() => ['ovt-hud','ovt-board','ovt-lobby'].map(i => document.getElementById(i).textContent).join('')")
        assert all(ord(c) < 128 for c in painted), painted
        SCRATCH.mkdir(exist_ok=True)
        page.screenshot(path=str(SCRATCH / "overlay_tft_live_1080.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tft live]: {errors[:3]}"


def test_tft_overlay_layout_clears_the_tft_hud_at_1080_and_1440(mock_server, pw_browser):
    """STRUCTURE: the painted boxes (full feed, so the data-gated lobby shows
    too) sit at their registry defaults and clear every TFT HUD keep-out region,
    at the design 1920x1080 and on the operator's 2560x1440 screen."""
    want = tft_default_boxes()
    for vp, query in (((1920, 1080), "?overlay=1"), ((2560, 1440), "?overlay=1&ovscale=1.33")):
        ctx, page, errors = _open(pw_browser, mock_server, _fixture("tft_overlay_feed"), vp, query)
        try:
            _wait_tft(page)
            page.wait_for_function("() => !document.getElementById('ovt-lobby').hidden", timeout=10_000)
            visible = page.evaluate(_VISIBLE_WIDGETS_JS)
            assert TFT_IDS <= set(visible), sorted(visible)
            for wid in TFT_IDS:
                box = visible[wid]
                w = want[wid]
                # x / y / width match the registry within rounding.
                for i in (0, 1):
                    assert abs(box[i] - w[i]) <= 2, f"{vp} {wid} {box} vs default {w}"
                assert abs((box[2] - box[0]) - (w[2] - w[0])) <= 2, f"{vp} {wid} width"
                # the measured height budget in the static guard still holds.
                assert box[3] - box[1] <= NATURAL_H[wid] + 2, (
                    f"{vp} {wid} is {box[3] - box[1]:.0f}px tall, budget {NATURAL_H[wid]} -"
                    " update NATURAL_H in tests/test_overlay_tft_layout.py with the new measurement")
                assert box[2] <= 1920 + 1 and box[3] <= 1080 + 1, f"{vp} {wid} off screen {box}"
                for name, region in KEEP_OUT.items():
                    assert _overlap(box, region) is None, f"{vp} {wid} {box} covers {name} {region}"
            SCRATCH.mkdir(exist_ok=True)
            page.screenshot(path=str(SCRATCH / f"overlay_tft_feed_{vp[0]}.png"))
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [tft feed {vp}]: {errors[:3]}"


def test_tft_overlay_does_not_reflow_when_data_lands(mock_server, pw_browser):
    """NO REFLOW: the start-of-game placeholder (all '-'), the live payload and
    the full feed paint the vitals + board at the same size."""
    sizes = {}
    for name in ("tft_overlay_sentinel", "tft_overlay_live", "tft_overlay_feed"):
        ctx, page, errors = _open(pw_browser, mock_server, _fixture(name))
        try:
            _wait_tft(page)
            sizes[name] = page.evaluate(
                "() => ['ovt-hud','ovt-board'].map(i => {"
                " const r = document.getElementById(i).getBoundingClientRect();"
                " return [Math.round(r.width), Math.round(r.height)]; })")
            if name == "tft_overlay_sentinel":
                for k in ("hp", "place", "alive", "stage", "level", "gold"):
                    assert _val(page, k) == "-", f"sentinel {k}"
                assert _text(page, "#ovt-board .ovt-time") == "-"
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{name}]: {errors[:3]}"
    assert len({json.dumps(v) for v in sizes.values()}) == 1, sizes


def _with_engine_unknown_coach(st, tmp_path):
    """``st`` with the coach envelope /api/state serves when the TFT engine
    wrote HP / level / gold UNKNOWN (s136 T11): the engine's own write
    (tests/test_tft_payload_unknown_vitals_s136.py _UNKNOWN), then the state
    builder's standalone fill (dashboard/_state_builder.py
    tft_coach_for_standalone) from the fixture's liveclient."""
    from unittest.mock import patch

    from dashboard import _state_builder as sb
    from tests.test_tft_payload_unknown_vitals_s136 import _ADVICE, _UNKNOWN, _engine
    from tft import tft_coach_engine as tce

    with patch("core.coaching_timestamps.write_coaching_ts"), \
         patch.object(tce, "_live_data", return_value={}):
        eng = _engine(tmp_path)
        eng._write_fields(_ADVICE, dict(_UNKNOWN))
    coach = json.loads(eng._data_file.read_text(encoding="utf-8"))
    with patch.object(sb, "_coach_file_mtime", return_value=None):
        coach = sb.tft_coach_for_standalone(coach, "tft_coaching_data.json", st["liveclient"])
    return {**st, "coach": coach}


def test_tft_overlay_unknown_vitals_paint_the_no_data_sentinel(mock_server, pw_browser, tmp_path):
    """S136 T11 (STRUCTURE / TYPOGRAPHY / ASCII / NO-REFLOW): the payload the
    TFT engine writes with HP / level / gold unknown paints "-" there, dimmed
    like every placeholder (is-empty), in the same boxes as the real feed. It
    painted "HP 100 / LEVEL 1 / GOLD 0" and a board count of "7/1"; with no
    per-round file, the reader's "unavailable" board_str as a unit chip."""
    want = {"tft_overlay_sentinel": ("-", "-"), "tft_overlay_live": ("96", "7")}
    sizes = {}
    for name in ("tft_overlay_feed", *want):
        st = _fixture(name) if name not in want else _with_engine_unknown_coach(_fixture(name), tmp_path)
        ctx, page, errors = _open(pw_browser, mock_server, st)
        try:
            _wait_tft(page)
            sizes[name] = page.evaluate(
                "() => ['ovt-hud','ovt-board'].map(i => {"
                " const r = document.getElementById(i).getBoundingClientRect();"
                " return [Math.round(r.width), Math.round(r.height)]; })")
            if name not in want:
                continue
            hp, count = want[name]
            assert _val(page, "hp") == hp, f"{name} hp"
            for k in ("level", "gold"):
                assert _val(page, k) == "-", f"{name} {k}"
            assert _text(page, "#ovt-board .ovt-time") == count, f"{name} board count"
            dimmed = page.eval_on_selector_all(
                "#ovt-hud .ovt-cell.is-empty",
                "els => els.map(e => [e.dataset.k, e.querySelector('.ovt-val').textContent,"
                " /rgba?\\(([^)]+)\\)/.exec(getComputedStyle(e.querySelector('.ovt-val')).color)[1]"
                ".split(',').map(Number)[3]])")
            by_key = {k: (text, alpha) for k, text, alpha in dimmed}
            for k in ("level", "gold") + (("hp",) if hp == "-" else ()):
                assert k in by_key, f"{name} {k} not dimmed as empty"
                assert by_key[k][0] == "-" and abs(by_key[k][1] - 0.45) < 0.01, (name, k, by_key[k])
            names = page.eval_on_selector_all("#ovt-board .ovt-unit-name", "els => els.map(e => e.textContent)")
            assert "unavailable" not in names, f"{name}: a no-read placeholder painted as a unit"
            painted = page.evaluate(
                "() => ['ovt-hud','ovt-board'].map(i => document.getElementById(i).textContent).join('')")
            assert all(ord(c) < 128 for c in painted), painted
            # HIERARCHY: the "-" in the major HP cell still outranks the minor ones.
            assert _fs(page, '#ovt-hud .ovt-cell[data-k="hp"] .ovt-val') > _fs(
                page, '#ovt-hud .ovt-cell[data-k="level"] .ovt-val')
            # HIT-TARGETS: still display-only (the drag handle is the one zone).
            zones = page.evaluate(
                "() => ['ovt-hud','ovt-board'].flatMap(i => [...document.getElementById(i)"
                ".querySelectorAll('[data-rc-zone]')].filter(n => !n.classList.contains('ovx-handle'))"
                ".map(n => n.className))")
            assert zones == [], zones
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{name} unknown vitals]: {errors[:3]}"
    assert len({json.dumps(v) for v in sizes.values()}) == 1, sizes


def test_tft_overlay_typography_and_hierarchy(mock_server, pw_browser):
    """TYPOGRAPHY + HIERARCHY: overlay type scale, nothing clipped, HP reads
    first."""
    ctx, page, errors = _open(pw_browser, mock_server, _fixture("tft_overlay_feed"))
    try:
        _wait_tft(page)
        hp = _fs(page, '#ovt-hud .ovt-cell[data-k="hp"] .ovt-val')
        stage = _fs(page, '#ovt-hud .ovt-cell[data-k="stage"] .ovt-val')
        unit = _fs(page, "#ovt-board .ovt-unit-name")
        label = _fs(page, "#ovt-hud .ovt-lab")
        opp = _fs(page, "#ovt-lobby .ovt-opp")
        assert stage >= 16, f"value {stage}px under the 16px value floor"
        assert unit >= 13 and opp >= 13, f"chips {unit}/{opp}px under the 13px overlay chip token"
        assert label >= 11, f"label {label}px under the 11px overlay head token"
        assert hp > stage > unit > label, (hp, stage, unit, label)
        assert page.eval_on_selector("#ovt-hud .ovt-lab", "e => getComputedStyle(e).textTransform") == "uppercase"
        clipped = page.evaluate(
            "() => [...document.querySelectorAll("
            "'#ovt-hud .ovt-val, #ovt-hud .ovt-time, #ovt-board .ovt-unit-name, #ovt-lobby .ovt-opp')]"
            ".filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)")
        assert clipped == [], f"clipped text: {clipped}"
        assert "Fiddlesticks" in page.eval_on_selector_all(
            "#ovt-board .ovt-unit-name", "els => els.map(e => e.textContent)")
        # S135 UI audit MUST-FIX 1: the head rows carry the nested backing (the
        # bare 0.58 frame put the gold title at a median 2.2:1 over the sky
        # behind the default spot).
        head_alpha = page.eval_on_selector_all(
            ".ovt-panel .ovt-head",
            "els => els.map(e => { const m = /rgba?\\(([^)]+)\\)/.exec(getComputedStyle(e).backgroundColor);"
            " const p = m ? m[1].split(',').map(Number) : [0, 0, 0, 0];"
            " return p.length > 3 ? p[3] : 1; })")
        assert len(head_alpha) == 3 and min(head_alpha) >= 0.85, head_alpha
        # MUST-FIX 2: the eliminated chip reads at the chip size, dimmed no
        # further than the "-" placeholders (alpha 0.45, the 4.5:1 floor).
        out_fs = _fs(page, "#ovt-lobby .ovt-opp.is-out")
        assert out_fs >= 13 and out_fs == opp, (out_fs, opp)
        out_alpha = page.eval_on_selector(
            "#ovt-lobby .ovt-opp.is-out",
            "e => { const p = /rgba?\\(([^)]+)\\)/.exec(getComputedStyle(e).color)[1].split(',').map(Number);"
            " return p.length > 3 ? p[3] : 1; }")
        assert out_alpha >= 0.45, out_alpha
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tft typography]: {errors[:3]}"


def test_tft_overlay_hit_targets_and_tft_menu(mock_server, pw_browser):
    """HIT-TARGETS: widget bodies stay click-through (the only zone inside a TFT
    widget is its drag handle); the launcher menu in TFT lists the TFT panels,
    every action row keeps the 42px target."""
    ctx, page, errors = _open(pw_browser, mock_server, _fixture("tft_overlay_live"))
    try:
        _wait_tft(page)
        zones = page.evaluate(
            "() => ['ovt-hud','ovt-board','ovt-lobby'].flatMap(i => {"
            " const el = document.getElementById(i);"
            " const z = [...el.querySelectorAll('[data-rc-zone]')];"
            " if (el.hasAttribute('data-rc-zone')) z.push(el);"
            " return z.filter(n => !n.classList.contains('ovx-handle')).map(n => i + ':' + n.className); })")
        assert zones == [], f"interactive zones inside display-only TFT widgets: {zones}"
        assert page.eval_on_selector("#ovt-hud", "e => !!e.querySelector(':scope > .ovx-handle')")
        # S135 UI audit: the drag handle (top-right corner) must not sit on the
        # head row's right-aligned clock / board count.
        covered = page.evaluate(
            "() => ['ovt-hud','ovt-board'].filter(i => {"
            " const el = document.getElementById(i);"
            " const h = el.querySelector(':scope > .ovx-handle').getBoundingClientRect();"
            " const t = el.querySelector('.ovt-time').getBoundingClientRect();"
            " return Math.min(h.right, t.right) - Math.max(h.left, t.left) > 0.5"
            " && Math.min(h.bottom, t.bottom) - Math.max(h.top, t.top) > 0.5; })")
        assert covered == [], f"drag handle covers the head text in {covered}"
        page.click("#w-launcher")
        page.wait_for_function(
            "() => document.querySelector('#ovx-launcher-menu.ovx-menu-open .ovx-menu-prow')", timeout=5_000)
        assert _text(page, "#ovx-launcher-menu .ovx-menu-head") == "TFT PANELS"
        labels = page.eval_on_selector_all(
            "#ovx-launcher-menu .ovx-menu-toggle", "els => els.map(e => e.textContent.slice(4))")
        assert labels == ["TFT Vitals", "TFT Lobby HP", "TFT Board"], labels
        heights = page.eval_on_selector_all(
            "#ovx-launcher-menu .ovx-menu-row", "els => els.map(e => e.getBoundingClientRect().height)")
        assert heights and min(heights) >= 42, heights
        SCRATCH.mkdir(exist_ok=True)
        page.screenshot(path=str(SCRATCH / "overlay_tft_menu_1080.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tft menu]: {errors[:3]}"


def test_sr_overlay_keeps_the_league_panels_and_menu(mock_server, pw_browser):
    """Control: an SR payload paints no TFT widget and the menu stays the League
    panel list."""
    ctx, page, errors = _open(pw_browser, mock_server, _fixture("sr"))
    try:
        page.wait_for_function(
            "() => document.body.classList.contains('ovx-ready')"
            " && document.body.dataset.ovxGame === 'lol'", timeout=15_000)
        visible = page.evaluate(_VISIBLE_WIDGETS_JS)
        assert not (TFT_IDS & set(visible)), sorted(visible)
        assert page.evaluate("() => !document.getElementById('ovt-hud')"), "no TFT mount outside TFT"
        page.click("#w-launcher")
        page.wait_for_function(
            "() => document.querySelector('#ovx-launcher-menu.ovx-menu-open .ovx-menu-prow')", timeout=5_000)
        assert _text(page, "#ovx-launcher-menu .ovx-menu-head") == "PANELS"
        labels = page.eval_on_selector_all(
            "#ovx-launcher-menu .ovx-menu-toggle", "els => els.map(e => e.textContent.slice(4))")
        assert "Coach Call" in labels and "ARAM Balance" in labels, labels
        assert not any(lbl.startswith("TFT") for lbl in labels), labels
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr control]: {errors[:3]}"
