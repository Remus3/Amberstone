"""Vision calibrator profile wiring: native-reference-frame load + profile
save/read via the ?source= querystring on the existing calibrator routes.

Feature (2026-07-05): the calibrator page needs to load the per-HUD-config
NATIVE reference frame (core.vision_profiles.load_reference) and read/write a
PER-PROFILE region set (load_profile / save_profile) instead of only the legacy
single data/vision_regions.json. The routes gain a ?source= param:

  GET  /api/vision-frame?source=reference   -> native reference still (+ base)
  GET  /api/vision-regions?source=profile   -> the active profile's regions/base
                                               (legacy_seed boxes get scaled to
                                               the reference base, seeded=True)
  POST /api/vision-regions  {regions, base, source:"profile"}
                                            -> validate + save_profile (400 on a
                                               bad shape, save NOT called)

No source keeps the legacy behavior byte-for-byte. Handlers never leak a raw
exception (CLAUDE.md error rule).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_vision_calibrator as vc


class _FakeHandler:
    """Minimal stand-in for the dashboard request handler. Captures the single
    _send(code, body, ctype) the route emits so a test can inspect it."""

    def __init__(self, path: str):
        self.path = path
        self.sent = None  # (code, payload_dict, ctype)

    def _send(self, code, body, ctype):
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = body
        self.sent = (code, payload, ctype)


class FrameSourceTests(unittest.TestCase):
    def test_reference_source_returns_reference_payload(self):
        ref = {
            "ok": True, "b64": "REFB64", "width": 2560, "height": 1440,
            "age_s": 12.0, "config_key": "cfgX", "format": "jpeg",
        }
        with _patch(vc.vp, "load_reference", lambda config_key=None: ref):
            h = _FakeHandler("/api/vision-frame?source=reference")
            vc._serve_frame_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["b64"], "REFB64")
        self.assertEqual(payload["width"], 2560)
        self.assertEqual(payload["height"], 1440)
        self.assertEqual(payload["format"], "jpeg")
        self.assertEqual(payload["base"], [2560, 1440])

    def test_reference_source_passes_error_through(self):
        ref = {"ok": False, "error": "no reference captured yet", "config_key": "z"}
        with _patch(vc.vp, "load_reference", lambda config_key=None: ref):
            h = _FakeHandler("/api/vision-frame?source=reference")
            vc._serve_frame_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "no reference captured yet")

    def test_no_source_uses_relay_unchanged(self):
        sentinel = {"ok": True, "b64": "RELAY", "width": 1920, "height": 1080,
                    "format": "jpeg", "age_s": 0.5}
        with _patch(vc, "fetch_frame", lambda: dict(sentinel)):
            h = _FakeHandler("/api/vision-frame")
            vc._serve_frame_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertEqual(payload["b64"], "RELAY")


class RegionsGetSourceTests(unittest.TestCase):
    def test_profile_source_returns_regions_and_base_as_is(self):
        prof = {
            "config_key": "cfgX", "base": [2560, 1440],
            "regions": {"hp": [10, 20, 30, 40]}, "source": "profile",
        }
        with _patch(vc.vp, "load_profile", lambda config_key=None: prof):
            h = _FakeHandler("/api/vision-regions?source=profile")
            vc._serve_regions_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["regions"], {"hp": [10, 20, 30, 40]})
        self.assertEqual(payload["base"], [2560, 1440])
        self.assertEqual(payload["source"], "profile")
        self.assertFalse(payload["seeded"])

    def test_legacy_seed_scales_boxes_to_reference_base(self):
        # legacy_seed base is 1920x1080; a 2560x1440 reference -> sx=sy=4/3.
        prof = {
            "config_key": "cfgX", "base": [1920, 1080],
            "regions": {"hp": [900, 300, 1200, 600]}, "source": "legacy_seed",
        }
        ref = {"ok": True, "width": 2560, "height": 1440}
        with _patch(vc.vp, "load_profile", lambda config_key=None: prof), \
                _patch(vc.vp, "load_reference", lambda config_key=None: ref):
            h = _FakeHandler("/api/vision-regions?source=profile")
            vc._serve_regions_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["seeded"])
        self.assertEqual(payload["base"], [2560, 1440])
        # 900*4/3=1200, 300*4/3=400, 1200*4/3=1600, 600*4/3=800
        self.assertEqual(payload["regions"]["hp"], [1200, 400, 1600, 800])

    def test_legacy_seed_without_reference_falls_back_to_2560x1440(self):
        prof = {
            "config_key": "cfgX", "base": [1920, 1080],
            "regions": {"hp": [960, 540, 1920, 1080]}, "source": "legacy_seed",
        }
        ref = {"ok": False, "error": "none"}
        with _patch(vc.vp, "load_profile", lambda config_key=None: prof), \
                _patch(vc.vp, "load_reference", lambda config_key=None: ref):
            h = _FakeHandler("/api/vision-regions?source=reference")  # alias
            vc._serve_regions_get(h)
        code, payload, _ = h.sent
        self.assertEqual(payload["base"], [2560, 1440])
        self.assertTrue(payload["seeded"])

    def test_no_source_uses_legacy_load_regions(self):
        with _patch(vc, "load_regions", lambda: {"legacy": [1, 2, 3, 4]}):
            h = _FakeHandler("/api/vision-regions")
            vc._serve_regions_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["regions"], {"legacy": [1, 2, 3, 4]})
        self.assertNotIn("seeded", payload)  # legacy path unchanged


class RegionsPostSourceTests(unittest.TestCase):
    def test_profile_save_calls_save_profile_with_validated_regions(self):
        calls = {}

        def _save_profile(config_key, regions, base):
            calls["args"] = (config_key, regions, base)
            return {"ok": True, "count": len(regions), "config_key": config_key}

        body = {
            "regions": {"hp": [10, 20, 30, 40]},
            "base": [2560, 1440],
            "source": "profile",
        }
        with _patch(vc.vp, "active_config_key", lambda: "cfgX"), \
                _patch(vc.vp, "save_profile", _save_profile):
            h = _FakeHandler("/api/vision-regions")
            vc._serve_regions_post(h, body)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["saved"], 1)
        self.assertEqual(payload["config_key"], "cfgX")
        self.assertEqual(payload["target"], "profile")
        ck, regions, base = calls["args"]
        self.assertEqual(ck, "cfgX")
        self.assertEqual(regions, {"hp": [10, 20, 30, 40]})
        self.assertEqual(base, [2560, 1440])

    def test_invalid_regions_returns_400_and_does_not_save(self):
        called = {"n": 0}

        def _save_profile(*a, **k):
            called["n"] += 1
            return {"ok": True, "count": 0, "config_key": "x"}

        body = {
            "regions": {"hp": [9, 9, 1, 1]},  # inverted / zero-area
            "base": [2560, 1440],
            "source": "profile",
        }
        with _patch(vc.vp, "active_config_key", lambda: "cfgX"), \
                _patch(vc.vp, "save_profile", _save_profile):
            h = _FakeHandler("/api/vision-regions")
            vc._serve_regions_post(h, body)
        code, payload, _ = h.sent
        self.assertEqual(code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(called["n"], 0)  # save_profile never called

    def test_base_key_without_source_still_routes_to_profile(self):
        calls = {"n": 0}

        def _save_profile(config_key, regions, base):
            calls["n"] += 1
            return {"ok": True, "count": len(regions), "config_key": config_key}

        body = {"regions": {"hp": [1, 2, 3, 4]}, "base": [2560, 1440]}
        with _patch(vc.vp, "active_config_key", lambda: "cfgX"), \
                _patch(vc.vp, "save_profile", _save_profile):
            h = _FakeHandler("/api/vision-regions")
            vc._serve_regions_post(h, body)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertEqual(payload["target"], "profile")
        self.assertEqual(calls["n"], 1)

    def test_legacy_body_uses_save_regions_path(self):
        calls = {}

        def _save_regions(obj):
            calls["obj"] = obj
            return (True, None, len(obj))

        body = {"regions": {"hp": [1, 2, 3, 4]}}  # no base, no source
        with _patch(vc, "save_regions", _save_regions):
            h = _FakeHandler("/api/vision-regions")
            vc._serve_regions_post(h, body)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["saved"], 1)
        self.assertNotIn("target", payload)  # legacy path unchanged
        self.assertEqual(calls["obj"], {"hp": [1, 2, 3, 4]})


class NoBannedCodepointsTests(unittest.TestCase):
    def test_no_banned_codepoints(self):
        text = pathlib.Path(vc.__file__).read_text(encoding="utf-8")
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"routes_vision_calibrator.py banned codepoints: {hits}")


class _patch:
    """Tiny context-manager monkeypatch (setattr on enter, restore on exit) so
    the suite never touches real data/ - vision_profiles is fully stubbed."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value
        self._had = False
        self._old = None

    def __enter__(self):
        self._had = hasattr(self.obj, self.name)
        if self._had:
            self._old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        if self._had:
            setattr(self.obj, self.name, self._old)
        else:
            delattr(self.obj, self.name)
        return False


if __name__ == "__main__":
    unittest.main()
