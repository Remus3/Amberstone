"""Multi-state reference frames (vision calibrator enabler).

Feature (2026-07-05): the calibrator can only calibrate OCR boxes against ONE
native reference still per HUD config. Elements that only render in a transient
game state (death_timer when self is dead, enemy_deaths when enemies are dead)
are not depicted on the base still, so their boxes cannot be positioned.

This slice lets the operator ingest operator-provided full-screen native
screenshots as NAMED reference states (base + arbitrary labels such as
self_dead), and switch which state the calibrator overlays:

  core.vision_profiles
    reference_path(ck, state)      -> base file for None/""/"base"; __<state>.jpg else
    load_reference(state=...)      -> the named state still
    save_reference_image(state=...)-> writes the named state file
    list_reference_states(ck)      -> ["base", ...ingested]
    ingest_reference_from_path(src, state, ck)
                                   -> read image, require dims == profile base,
                                      save via save_reference_image(force); reject
                                      a dims mismatch / a base-or-empty label.

  dashboard.routes_vision_calibrator
    GET  /api/vision-frame?source=reference&state=<state> -> load_reference(state=state)
    GET  /api/vision-reference-states -> {ok, states:[{state, exists, width, height}]}
    POST /api/vision-reference {state, path} -> ingest_reference_from_path -> 200/400

The flat profile + native-OCR consume schema stay untouched (a box is
position-only). Backward compatible: state None gives the old base path
byte-for-byte. No test touches real data/ (dirs are monkeypatched to tmp_path).
Handlers never leak a raw exception (CLAUDE.md error rule).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from PIL import Image

from core import vision_profiles as vp
from dashboard import routes_vision_calibrator as vc


# -- storage: core.vision_profiles ------------------------------------

class ReferencePathTests(unittest.TestCase):
    def test_base_path_has_no_state_suffix(self):
        p = vp.reference_path("cfgX")
        self.assertTrue(p.name.endswith(".jpg"))
        self.assertNotIn("__", p.name)

    def test_state_path_has_double_underscore_state(self):
        p = vp.reference_path("cfgX", "self_dead")
        self.assertIn("__self_dead", p.name)
        self.assertTrue(p.name.endswith(".jpg"))

    def test_base_state_equals_no_state(self):
        self.assertEqual(vp.reference_path("cfgX", "base"), vp.reference_path("cfgX"))
        self.assertEqual(vp.reference_path("cfgX", ""), vp.reference_path("cfgX"))
        self.assertEqual(vp.reference_path("cfgX", None), vp.reference_path("cfgX"))


class _RefStore(unittest.TestCase):
    """Base for tests that need REFERENCE_DIR + PROFILES_DIR redirected to a
    tmp dir and a tiny base profile so no real data/ is touched."""

    CK = "cfgTiny"
    BASE = [120, 80]

    def setUp(self):
        import tempfile

        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._old_ref = vp.REFERENCE_DIR
        self._old_prof = vp.PROFILES_DIR
        vp.REFERENCE_DIR = self.tmp / "ref"
        vp.PROFILES_DIR = self.tmp / "prof"
        vp.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        vp.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        # tiny base profile so load_profile(ck)["base"] == [120, 80]
        vp.save_profile(self.CK, {"hp": [1, 2, 3, 4]}, self.BASE)

    def tearDown(self):
        vp.REFERENCE_DIR = self._old_ref
        vp.PROFILES_DIR = self._old_prof

    def _png(self, w, h):
        p = self.tmp / f"src_{w}x{h}.png"
        Image.new("RGB", (w, h), (10, 20, 30)).save(p, format="PNG")
        return p


class IngestTests(_RefStore):
    def test_ingest_happy_path_writes_state_file(self):
        src = self._png(120, 80)
        res = vp.ingest_reference_from_path(str(src), "self_dead", config_key=self.CK)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["state"], "self_dead")
        self.assertEqual(res["config_key"], self.CK)
        self.assertTrue(vp.reference_path(self.CK, "self_dead").exists())
        loaded = vp.load_reference(config_key=self.CK, state="self_dead")
        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["width"], 120)
        self.assertEqual(loaded["height"], 80)

    def test_ingest_dims_mismatch_rejected_and_not_written(self):
        src = self._png(60, 40)
        res = vp.ingest_reference_from_path(str(src), "self_dead", config_key=self.CK)
        self.assertFalse(res["ok"])
        self.assertIn("60", str(res.get("error", "")))
        self.assertIn("120", str(res.get("error", "")))
        self.assertFalse(vp.reference_path(self.CK, "self_dead").exists())

    def test_ingest_rejects_base_and_empty_label(self):
        src = self._png(120, 80)
        for bad in ("base", "", "   "):
            res = vp.ingest_reference_from_path(str(src), bad, config_key=self.CK)
            self.assertFalse(res["ok"], bad)
        # base still file never created by a rejected ingest
        self.assertFalse(vp.reference_path(self.CK, "base").exists())

    def test_ingest_unreadable_path_is_friendly(self):
        res = vp.ingest_reference_from_path(str(self.tmp / "nope.png"), "s",
                                            config_key=self.CK)
        self.assertFalse(res["ok"])
        self.assertIn("cannot read", res.get("error", ""))


class ListReferenceStatesTests(_RefStore):
    def test_empty_when_nothing_saved(self):
        self.assertEqual(vp.list_reference_states(config_key=self.CK), [])

    def test_base_plus_ingested_sorted(self):
        # create the base still, then ingest a state
        vp.save_reference_image(Image.new("RGB", (120, 80)), config_key=self.CK,
                                force=True)
        vp.ingest_reference_from_path(str(self._png(120, 80)), "self_dead",
                                      config_key=self.CK)
        states = vp.list_reference_states(config_key=self.CK)
        self.assertEqual(states, ["base", "self_dead"])


# -- routes: dashboard.routes_vision_calibrator -----------------------

class _FakeHandler:
    def __init__(self, path: str):
        self.path = path
        self.sent = None  # (code, payload, ctype)

    def _send(self, code, body, ctype):
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = body
        self.sent = (code, payload, ctype)


class ReferenceStatesRouteTests(unittest.TestCase):
    def test_states_route_shape(self):
        states = [
            {"state": "base", "exists": True, "width": 2560, "height": 1440},
            {"state": "self_dead", "exists": True, "width": 2560, "height": 1440},
        ]
        with _patch(vc.vp, "list_reference_states", lambda config_key=None: ["base", "self_dead"]), \
                _patch(vc.vp, "load_reference",
                       lambda config_key=None, state=None: {"ok": True, "width": 2560, "height": 1440}):
            h = _FakeHandler("/api/vision-reference-states")
            vc._serve_reference_states_get(h)
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        got = {(s["state"], s["exists"]) for s in payload["states"]}
        self.assertEqual(got, {(s["state"], s["exists"]) for s in states})

    def test_states_route_registered_in_get_routes(self):
        self.assertTrue(any(m("/api/vision-reference-states")
                            for m, _ in vc.GET_ROUTES))


class ReferencePostRouteTests(unittest.TestCase):
    def test_ingest_happy_returns_ok_payload(self):
        with _patch(vc.vp, "ingest_reference_from_path",
                    lambda path, state, config_key=None: {
                        "ok": True, "state": state, "width": 2560, "height": 1440,
                        "config_key": "cfgX"}):
            h = _FakeHandler("/api/vision-reference")
            vc._serve_reference_post(h, {"state": "self_dead", "path": "C:/x.png"})
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["state"], "self_dead")

    def test_missing_fields_return_400(self):
        for body in ({}, {"state": "s"}, {"path": "p"}, {"state": "", "path": "p"},
                     {"state": "s", "path": ""}):
            h = _FakeHandler("/api/vision-reference")
            vc._serve_reference_post(h, body)
            code, payload, _ = h.sent
            self.assertEqual(code, 400, body)
            self.assertFalse(payload["ok"])

    def test_ingest_failure_returns_400(self):
        with _patch(vc.vp, "ingest_reference_from_path",
                    lambda path, state, config_key=None: {
                        "ok": False, "error": "dims mismatch"}):
            h = _FakeHandler("/api/vision-reference")
            vc._serve_reference_post(h, {"state": "s", "path": "p"})
        code, payload, _ = h.sent
        self.assertEqual(code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "dims mismatch")

    def test_post_route_registered(self):
        self.assertTrue(any(m("/api/vision-reference")
                            for m, _ in vc.POST_ROUTES))


class FrameStatePassthroughTests(unittest.TestCase):
    def test_state_param_passed_into_load_reference(self):
        seen = {}

        def _load_reference(config_key=None, state=None):
            seen["state"] = state
            return {"ok": True, "b64": "B", "width": 2560, "height": 1440,
                    "age_s": 1.0, "config_key": "c", "format": "jpeg"}

        with _patch(vc.vp, "load_reference", _load_reference):
            h = _FakeHandler("/api/vision-frame?source=reference&state=self_dead")
            vc._serve_frame_get(h)
        self.assertEqual(seen.get("state"), "self_dead")
        code, payload, _ = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])


class _patch:
    """Tiny context-manager monkeypatch (setattr on enter, restore on exit)."""

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


class NoBannedCodepointsTests(unittest.TestCase):
    def test_no_banned_codepoints(self):
        text = pathlib.Path(__file__).read_text(encoding="utf-8")
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"test file banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
