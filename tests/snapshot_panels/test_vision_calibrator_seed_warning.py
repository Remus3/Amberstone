"""The vision calibrator must tell the truth about an UNTUNED seed.

LEDGER 1227 filed web/vision_calibrator.html:233 as wrong twice: it said
"from legacy" for a tier-2 derived seed, and hardcoded "2560" on a machine
that may be 3440 or 5120 wide. It also filed the consequence - an operator
can promote a derived seed to a permanent calibration by clicking Save
without ever dragging a box.

Reading the page for the fix surfaced a THIRD defect that subsumes both:
loadRegions() writes the seed warning into #status and boot then calls
loadFrame(), which overwrites #status unconditionally, so the warning was
never on screen by the time anyone could read it. A wording fix alone would
have shipped a correct sentence nobody sees.

These tests own the seeded-state contract end to end: provenance, the real
base, survival past boot, and the Save arming guard.
"""

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"

# Mutated per-test before the page is opened; the handler reads it live.
_STORE = {"regions": {}}


def _handler_cls():
    class _H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB_DIR), **kw)

        def log_message(self, *_):
            pass

        def _json(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            _STORE["posts"] = _STORE.get("posts", 0) + 1
            try:
                _STORE["last_post"] = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                _STORE["last_post"] = {}
            self._json({"ok": True, "saved": 21, "config_key": "test"})

        def do_GET(self):  # noqa: N802
            p = self.path.split("?")[0]
            if p == "/api/vision-reference-states":
                self._json({"ok": True, "states": [{"state": "base"}]})
            elif p == "/api/vision-regions":
                self._json(_STORE["regions"])
            elif p == "/api/vision-frame":
                # Default is deliberately unavailable: loadFrame then takes
                # its early return, which is the exact path that used to
                # clobber the seed warning out of #status.
                self._json(_STORE.get("frame")
                           or {"ok": False, "error": "no frame in test"})
            else:
                super().do_GET()

    return _H


@pytest.fixture(scope="module")
def calib_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler_cls())
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _open(pw_browser, base_url, payload, frame=None):
    _STORE["regions"] = payload
    _STORE["frame"] = frame
    _STORE["posts"] = 0
    ctx = pw_browser.new_context(viewport={"width": 1600, "height": 900})
    page = ctx.new_page()
    page.goto(f"{base_url}/vision_calibrator.html")
    # Boot is loadStates -> loadRegions -> loadFrame; wait for the last one
    # to have run so the clobber would already have happened.
    page.wait_for_function("() => document.getElementById('status')"
                           ".textContent.indexOf('loading') === -1")
    return ctx, page


_DERIVED = {"ok": True, "regions": {"hp": [1, 2, 3, 4]},
            "base": [3440, 1440], "source": "resolution_seed", "seeded": True}
_LEGACY = {"ok": True, "regions": {"hp": [1, 2, 3, 4]},
           "base": [2560, 1440], "source": "legacy_seed", "seeded": True}
_TUNED = {"ok": True, "regions": {"hp": [1, 2, 3, 4]},
          "base": [2560, 1440], "source": "profile", "seeded": False}


class TestSeedWarningIsHonest:
    def test_derived_seed_is_not_described_as_legacy(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            warn = page.inner_text("#seedwarn")
            assert "legacy" not in warn.lower(), warn
            assert "derived" in warn.lower(), warn
        finally:
            ctx.close()

    def test_derived_seed_names_the_real_base_not_a_hardcoded_2560(
            self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            warn = page.inner_text("#seedwarn")
            assert "3440x1440" in warn, warn
            assert "2560" not in warn, warn
        finally:
            ctx.close()

    def test_legacy_seed_says_legacy_and_names_the_1080p_source(
            self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _LEGACY)
        try:
            warn = page.inner_text("#seedwarn").lower()
            assert "legacy" in warn, warn
            assert "1920x1080" in warn, warn
        finally:
            ctx.close()

    def test_warning_survives_the_frame_load_that_used_to_clobber_it(
            self, calib_server, pw_browser):
        # The regression this file exists for: #status is rewritten by
        # loadFrame, so the warning must NOT live in #status.
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            assert page.is_visible("#seedwarn")
            status = page.inner_text("#status")
            assert "frame unavailable" in status, status
            assert page.is_visible("#seedwarn"), "seed warning clobbered by boot"
        finally:
            ctx.close()

    def test_a_tuned_profile_shows_no_warning(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _TUNED)
        try:
            assert not page.is_visible("#seedwarn")
        finally:
            ctx.close()


class TestSaveArmingGuard:
    def test_save_on_an_untouched_seed_does_not_post(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.toLowerCase().includes('again')")
            assert _STORE["posts"] == 0, "an untouched seed was promoted on one click"
        finally:
            ctx.close()

    def test_second_click_confirms_and_posts(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.toLowerCase().includes('again')")
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.includes('SAVED')")
            assert _STORE["posts"] == 1
        finally:
            ctx.close()

    def test_editing_a_box_disarms_the_guard_and_saves_on_one_click(
            self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _DERIVED)
        try:
            page.click(".region")           # select
            page.keyboard.press("ArrowRight")  # a real edit
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.includes('SAVED')")
            assert _STORE["posts"] == 1
        finally:
            ctx.close()

    def test_a_tuned_profile_saves_on_one_click(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _TUNED)
        try:
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.includes('SAVED')")
            assert _STORE["posts"] == 1
        finally:
            ctx.close()


class TestRegionsAreLaidOutInProfileSpace:
    """Found by the UI audit, live on Legion: the boxes were positioned by
    the FRAME's pixel size while the coordinates come from the PROFILE base.
    The two are routinely different - the live capture path serves a halved
    1280x720 frame while the active profile base is 2560x1440 - so every box
    was drawn at double scale, up to 2471px right on a 1265px page, and the
    page was unusable for its one job. The frame is a BACKDROP; region
    geometry belongs to the profile base."""

    # A deliberately undecodable image: loadFrame resolves on img.onerror and
    # takes width/height from the JSON, which is what the layout must use.
    _HALVED = {"ok": True, "width": 1280, "height": 720, "age_s": 1.0,
               "format": "jpeg", "b64": "not-a-real-jpeg"}

    def test_no_box_escapes_the_stage_when_frame_and_profile_base_differ(
            self, calib_server, pw_browser):
        payload = {"ok": True,
                   "regions": {"timer": [2476, 5, 2537, 34],
                               "level": [977, 1404, 998, 1424]},
                   "base": [2560, 1440], "source": "resolution_seed",
                   "seeded": True}
        ctx, page = _open(pw_browser, calib_server, payload, frame=self._HALVED)
        try:
            over = page.evaluate(
                """() => {
                  const s = document.querySelector('#stage').getBoundingClientRect();
                  return [...document.querySelectorAll('.region')]
                    .map(e => { const r = e.getBoundingClientRect();
                                return {n: e.dataset.name,
                                        over: Math.round(r.right - s.right),
                                        under: Math.round(r.bottom - s.bottom)}; })
                    .filter(o => o.over > 1 || o.under > 1);
                }"""
            )
            assert over == [], f"regions escaped the stage: {over}"
        finally:
            ctx.close()

    def test_page_does_not_scroll_horizontally(self, calib_server, pw_browser):
        payload = {"ok": True, "regions": {"timer": [2476, 5, 2537, 34]},
                   "base": [2560, 1440], "source": "resolution_seed",
                   "seeded": True}
        ctx, page = _open(pw_browser, calib_server, payload, frame=self._HALVED)
        try:
            scrolls = page.evaluate(
                "() => document.documentElement.scrollWidth > "
                "document.documentElement.clientWidth + 1")
            assert not scrolls, "calibrator scrolls horizontally"
        finally:
            ctx.close()

    def test_save_stamps_the_profile_base_not_the_backdrop_size(
            self, calib_server, pw_browser):
        # Posting [1280,720] against 2560-space coordinates would halve every
        # future crop, which is the same class of silent base/coordinate
        # mismatch as the layout bug above.
        payload = {"ok": True, "regions": {"timer": [2476, 5, 2537, 34]},
                   "base": [2560, 1440], "source": "profile", "seeded": False}
        ctx, page = _open(pw_browser, calib_server, payload, frame=self._HALVED)
        try:
            page.click("#save")
            page.wait_for_function("() => document.getElementById('status')"
                                   ".textContent.includes('SAVED')")
            assert _STORE["last_post"]["base"] == [2560, 1440], _STORE["last_post"]
        finally:
            ctx.close()

    def test_a_box_at_the_profile_right_edge_lands_at_the_stage_right_edge(
            self, calib_server, pw_browser):
        payload = {"ok": True, "regions": {"edge": [2540, 0, 2560, 20]},
                   "base": [2560, 1440], "source": "resolution_seed",
                   "seeded": True}
        ctx, page = _open(pw_browser, calib_server, payload, frame=self._HALVED)
        try:
            gap = page.evaluate(
                """() => {
                  const s = document.querySelector('#stage').getBoundingClientRect();
                  const r = document.querySelector('.region').getBoundingClientRect();
                  return Math.abs(r.right - s.right);
                }"""
            )
            assert gap < 3, f"right-edge region landed {gap}px from the edge"
        finally:
            ctx.close()


class TestHitTargets:
    """UI-fixture audit HIT-TARGETS phase: every clickable meets --hit-min
    (web/css/tokens.css:119, 42px) and carries a :focus-visible affordance.
    This page ships its own inline <style> and does NOT load tokens.css, so
    the token has to be defined locally - an undefined CSS var fails silently
    and would inherit instead of erroring (memory
    reference_css_undefined_var_fails_silently)."""

    def test_hit_min_token_is_defined_on_this_page(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _TUNED)
        try:
            val = page.evaluate(
                "() => getComputedStyle(document.documentElement)"
                ".getPropertyValue('--hit-min').trim()")
            assert val == "42px", f"--hit-min resolved to {val!r}"
        finally:
            ctx.close()

    def test_every_clickable_meets_the_42px_minimum(self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _LEGACY)
        try:
            small = page.evaluate(
                """() => [...document.querySelectorAll('button, input')]
                     .map(e => ({ id: e.id || e.className,
                                  h: Math.round(e.getBoundingClientRect().height) }))
                     .filter(o => o.h > 0 && o.h < 42);"""
            )
            assert small == [], f"below --hit-min: {small}"
        finally:
            ctx.close()

    def test_every_clickable_has_a_focus_visible_affordance(
            self, calib_server, pw_browser):
        ctx, page = _open(pw_browser, calib_server, _LEGACY)
        try:
            page.focus("#save")
            styled = page.evaluate(
                """() => {
                  const e = document.getElementById('save');
                  const c = getComputedStyle(e);
                  return {w: c.outlineWidth, style: c.outlineStyle};
                }"""
            )
            assert styled["style"] != "none", styled
            assert float(styled["w"].replace("px", "")) >= 2, styled
        finally:
            ctx.close()


class TestPageHygiene:
    def test_source_is_7bit_ascii(self):
        raw = (WEB_DIR / "vision_calibrator.html").read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        assert not bad, f"non-ASCII bytes at {bad[:5]}"

    def test_no_html_entity_renders_a_non_ascii_glyph(self, calib_server, pw_browser):
        # &middot; is ASCII in source but paints U+00B7 on screen; the repo
        # rule is about authored content, and a rendered glyph is content.
        ctx, page = _open(pw_browser, calib_server, _TUNED)
        try:
            txt = page.inner_text("body")
            bad = sorted({c for c in txt if ord(c) > 0x7F})
            assert not bad, f"non-ASCII rendered: {bad}"
        finally:
            ctx.close()
