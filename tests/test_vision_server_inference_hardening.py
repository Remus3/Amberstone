"""Lane 8 cycle 20 - vision_server/_inference.py audit regression suite.

Every test here is named for one weakness measured on the pre-fix file and was
confirmed RED against it before the fix landed. The module is the :8889
inference trust boundary: it parses a JSON body RC did not author, forwards an
untrusted image to the Anthropic API, and parses a model response that RC does
not control either.

Three input surfaces, all reached through ``do_POST`` in ``vision_server/_http``:
``/vision``, ``/coach``, ``/ocr``.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vision_server import _inference as inf  # noqa: E402
from vision_server import _stats as st  # noqa: E402


class _Blk:
    """Stand-in for an Anthropic content block."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage


def _client_returning(content):
    """A fake Anthropic client whose messages.create returns ``content``."""
    cap = {}

    def _create(**kw):
        cap.update(kw)
        return _Resp(content)

    c = types.SimpleNamespace()
    c.messages = types.SimpleNamespace(create=_create)
    c.captured = cap
    return c


def _png_b64(w: int, h: int) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _StubClient:
    """Context manager swapping vision_server._inference._get_client."""

    def __init__(self, content):
        self._content = content
        self._orig = None
        self.client = None

    def __enter__(self):
        self._orig = inf._get_client
        self.client = _client_returning(self._content)
        inf._get_client = lambda: self.client
        return self.client

    def __exit__(self, *a):
        inf._get_client = self._orig
        return False


def _errors(kind: str) -> int:
    return st.get_stats()["stats"].get(kind, {}).get("errors", 0)


def _calls(kind: str) -> int:
    return st.get_stats()["stats"].get(kind, {}).get("calls", 0)


class WrongTypedBodyTests(unittest.TestCase):
    """A merely-WRONG body must not raise out of the handler.

    Pre-fix every case below raised TypeError/AttributeError, which
    ``do_POST`` turned into a bare HTTP 500 "internal error" with no stats
    record, so malformed traffic was both mislabelled and invisible.
    """

    def test_vision_non_object_body_returns_error_not_raises(self):
        r = inf.handle_vision(b"[1,2]")
        self.assertIn("error", r)

    def test_coach_non_object_body_returns_error_not_raises(self):
        r = inf.handle_coach(b"[1,2]")
        self.assertIn("error", r)

    def test_ocr_non_object_body_returns_error_not_raises(self):
        r = inf.handle_ocr(b"[1,2]")
        self.assertIn("error", r)

    def test_vision_undecodable_body_returns_error_not_raises(self):
        r = inf.handle_vision(b"not json at all")
        self.assertIn("error", r)

    def test_ocr_string_crops_returns_error_not_raises(self):
        """crops="stage_round": `in` succeeds on a str, indexing does not."""
        r = inf.handle_ocr(json.dumps({"crops": "stage_round"}).encode())
        self.assertIn("error", r)

    def test_ocr_list_crops_returns_error_not_raises(self):
        r = inf.handle_ocr(json.dumps({"crops": ["stage_round"]}).encode())
        self.assertIn("error", r)

    def test_vision_non_string_image_returns_error_not_raises(self):
        for bad in ({"a": 1}, 12345, ["x"], True):
            with self.subTest(bad=bad):
                r = inf.handle_vision(json.dumps({"image_b64": bad}).encode())
                self.assertIn("error", r)

    def test_coach_non_string_prompt_returns_error_not_raises(self):
        for bad in ({"a": 1}, 12345, ["x"]):
            with self.subTest(bad=bad):
                r = inf.handle_coach(json.dumps({"prompt": bad}).encode())
                self.assertIn("error", r)

    def test_crop_to_primary_survives_non_string_input(self):
        """The pre-fix except-handler itself raised: it called .startswith
        on the same non-string that had just failed b64decode."""
        for bad in ({"a": 1}, 12345):
            with self.subTest(bad=bad):
                out, mt = inf._crop_to_primary(bad)
                self.assertTrue(mt.startswith("image/"))

    def test_malformed_body_is_recorded_in_stats(self):
        """Invisible failures are the reason a bad feed goes unnoticed."""
        before = _calls("vision")
        inf.handle_vision(b"[1,2]")
        self.assertGreater(_calls("vision"), before)


class ParseJsonContractTests(unittest.TestCase):
    """``_parse_json`` is annotated ``-> dict | None`` and every live consumer
    isinstance-gates the result. Pre-fix it returned lists, ints, strings and
    bools straight through, and handle_vision then counted them ok=True."""

    def test_non_dict_json_is_rejected(self):
        for raw in ("[1,2,3]", "123", '"hello"', "true", "null"):
            with self.subTest(raw=raw):
                self.assertIsNone(inf._parse_json(raw))

    def test_dict_json_still_parses(self):
        self.assertEqual(inf._parse_json('{"a": 1}'), {"a": 1})

    def test_fenced_dict_json_still_parses(self):
        fenced = "```json\n{\"a\": 1}\n```"
        self.assertEqual(inf._parse_json(fenced), {"a": 1})

    def test_embedded_dict_json_still_parses(self):
        self.assertEqual(inf._parse_json('noise {"a": 1} noise'), {"a": 1})

    def test_non_dict_model_output_is_counted_as_an_error(self):
        with _StubClient([_Blk(type="text", text="[1,2,3]")]):
            before = _errors("vision")
            r = inf.handle_vision(json.dumps({"image_b64": "x"}).encode())
            self.assertIn("error", r)
            self.assertGreater(_errors("vision"), before)


class ContentBlockShapeTests(unittest.TestCase):
    """``resp.content[0].text`` assumed a non-empty list whose first block is
    a text block. An empty list raised IndexError; a leading thinking block
    raised AttributeError - the exact class CLAUDE.md names."""

    def test_vision_survives_empty_content(self):
        with _StubClient([]):
            r = inf.handle_vision(json.dumps({"image_b64": "x"}).encode())
            self.assertIn("error", r)

    def test_coach_survives_empty_content(self):
        with _StubClient([]):
            r = inf.handle_coach(json.dumps({"prompt": "hi"}).encode())
            self.assertIn("error", r)

    def test_vision_survives_leading_thinking_block(self):
        with _StubClient([_Blk(type="thinking", thinking="..."),
                          _Blk(type="text", text='{"gold": 5}')]):
            r = inf.handle_vision(json.dumps({"image_b64": "x"}).encode())
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(r["result"], {"gold": 5})

    def test_coach_survives_leading_thinking_block(self):
        with _StubClient([_Blk(type="thinking", thinking="..."),
                          _Blk(type="text", text="do the thing")]):
            r = inf.handle_coach(json.dumps({"prompt": "hi"}).encode())
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(r["text"], "do the thing")

    def test_coach_with_only_a_thinking_block_reports_error(self):
        with _StubClient([_Blk(type="thinking", thinking="...")]):
            r = inf.handle_coach(json.dumps({"prompt": "hi"}).encode())
            self.assertIn("error", r)


class ModelFieldTests(unittest.TestCase):
    """The model is caller-controlled. A strict allowlist would break the
    Sonnet escalation path (modes/shared_vision.py:273 passes SONNET_MODEL),
    so the guard validates SHAPE, not membership."""

    def test_wellformed_model_is_forwarded(self):
        with _StubClient([_Blk(type="text", text='{"a":1}')]) as c:
            inf.handle_vision(json.dumps(
                {"image_b64": "x", "model": "claude-sonnet-4-5-20250929"}).encode())
            self.assertEqual(c.captured["model"], "claude-sonnet-4-5-20250929")

    def test_non_string_model_is_rejected(self):
        for bad in ({"a": 1}, 12345, ["m"]):
            with self.subTest(bad=bad):
                r = inf.handle_vision(json.dumps(
                    {"image_b64": "x", "model": bad}).encode())
                self.assertIn("error", r)

    def test_absurdly_long_model_is_rejected(self):
        r = inf.handle_vision(json.dumps(
            {"image_b64": "x", "model": "claude-" + "a" * 500}).encode())
        self.assertIn("error", r)

    def test_model_with_control_characters_is_rejected(self):
        for bad in ("claude-x\nInjected: 1", "claude-x\r\nX", "../../etc/passwd"):
            with self.subTest(bad=bad):
                r = inf.handle_vision(json.dumps(
                    {"image_b64": "x", "model": bad}).encode())
                self.assertIn("error", r)

    def test_coach_rejects_malformed_model(self):
        r = inf.handle_coach(json.dumps(
            {"prompt": "hi", "model": {"a": 1}}).encode())
        self.assertIn("error", r)


class OcrResourceTests(unittest.TestCase):
    """``_pre`` upscaled every crop 3-4x linear (9-16x pixels) with no bound.
    Measured pre-fix: a 5 KB 1000x1000 PNG became a 16 MB resident buffer at
    scale=4, a ~3000x wire-to-memory amplification under a 10 MiB body cap."""

    def test_oversized_crop_is_refused_not_upscaled(self):
        """Asserts the MECHANISM, not the absence of a key.

        A blank oversized crop yields no "gold" key either way - with the cap
        it is refused, without it OCR simply reads nothing - so
        assertNotIn("gold") is vacuous and SURVIVED this exact mutation. The
        discriminating observable is the stats ring: a refused crop is a
        counted FAILURE, an unreadable one is a clean read.
        """
        big = _png_b64(inf._OCR_MAX_CROP_PX + 10, 8)
        before = _errors("ocr")
        r = inf.handle_ocr(json.dumps({"crops": {"gold": big}}).encode())
        self.assertNotIn("gold", r.get("result", {}))
        self.assertGreater(_errors("ocr"), before)

    def test_decompression_bomb_is_skipped_not_raised(self):
        """PIL's DecompressionBombError subclasses Exception directly, so it
        was covered by no entry in the pre-fix _OCR_EXC tuple and escaped as
        an HTTP 500. Lower the threshold so a small crop trips the real
        check."""
        from PIL import Image
        orig = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = 16
            before = _errors("ocr")
            r = inf.handle_ocr(json.dumps(
                {"crops": {"gold": _png_b64(64, 64)}}).encode())
            self.assertNotIn("error", r)
            self.assertGreater(_errors("ocr"), before)
        finally:
            Image.MAX_IMAGE_PIXELS = orig

    def test_reasonable_crop_is_still_processed(self):
        """The cap must not refuse a real calibrated crop."""
        small = _png_b64(120, 40)
        r = inf.handle_ocr(json.dumps({"crops": {"gold": small}}).encode())
        self.assertNotIn("error", r)

    def test_too_many_crop_keys_are_refused(self):
        crops = {f"k{i}": _png_b64(8, 8)
                 for i in range(inf._OCR_MAX_CROPS + 5)}
        r = inf.handle_ocr(json.dumps({"crops": crops}).encode())
        self.assertIn("error", r)

    def test_non_string_crop_value_is_skipped_not_raised(self):
        """Two guards cover this jointly - the isinstance check in _pre and
        TypeError in _OCR_EXC - so removing EITHER alone is an equivalent
        mutant (measured: both survived). The mutation that matters is the
        combined one, and it is what this test is pinned against."""
        before = _errors("ocr")
        r = inf.handle_ocr(json.dumps({"crops": {"gold": {"a": 1}}}).encode())
        self.assertNotIn("gold", r.get("result", {}))
        self.assertGreater(_errors("ocr"), before)

    def test_undecodable_crop_is_skipped_not_raised(self):
        r = inf.handle_ocr(json.dumps(
            {"crops": {"gold": "!!!not-base64!!!"}}).encode())
        self.assertNotIn("gold", r.get("result", {}))

    def test_ocr_records_error_when_every_crop_fails(self):
        """Pre-fix _record("ocr", ok=True) was unconditional, so a call where
        every crop threw was indistinguishable from a clean read."""
        before = _errors("ocr")
        inf.handle_ocr(json.dumps(
            {"crops": {"gold": "!!!x!!!", "level": "!!!y!!!"}}).encode())
        self.assertGreater(_errors("ocr"), before)


class SecretHandlingTests(unittest.TestCase):
    """This module holds the only Anthropic client that runs vision calls, so
    it sits directly on the API-key path. No value it RETURNS may carry the
    key: the returned dict is serialised straight onto the wire by
    ``vision_server/_http._j``."""

    _FAKE = "sk-ant-api03-DEADBEEF-not-a-real-key"

    def test_error_returns_never_carry_the_api_key(self):
        bodies = [b"[1,2]", b"not json",
                  json.dumps({"image_b64": "x", "model": {"a": 1}}).encode(),
                  json.dumps({"image_b64": ""}).encode()]
        for b in bodies:
            with self.subTest(body=b[:24]):
                self.assertNotIn("sk-ant-", json.dumps(inf.handle_vision(b)))
                self.assertNotIn("sk-ant-", json.dumps(inf.handle_coach(b)))

    def test_a_raising_client_does_not_return_the_key_to_the_caller(self):
        """The handler re-raises, and vision_server/_http._err500 redacts to
        'internal error'. Pin that this module never RETURNS the secret."""
        orig = inf._get_client

        def _boom():
            c = types.SimpleNamespace()

            def _create(**kw):
                raise RuntimeError("401 unauthorized for key " + self._FAKE)

            c.messages = types.SimpleNamespace(create=_create)
            return c

        inf._get_client = _boom
        try:
            with self.assertRaises(RuntimeError):
                inf.handle_coach(json.dumps({"prompt": "hi"}).encode())
        finally:
            inf._get_client = orig

    def test_parse_failed_raw_echo_is_bounded(self):
        """handle_vision echoes the model's raw text on a parse failure. It is
        model output, not RC state, but it must stay bounded."""
        with _StubClient([_Blk(type="text", text="z" * 5000)]):
            r = inf.handle_vision(json.dumps({"image_b64": "x"}).encode())
            self.assertLessEqual(len(r.get("raw", "")), 200)


class SiblingBodyHandlerTests(unittest.TestCase):
    """Root-cause siblings on the same :8889 do_POST dispatch table.

    ``_inference`` was the audited file, but the wrong-typed-body class is a
    property of the dispatch convention, not of one module, so the grep for
    siblings is part of the fix (CLAUDE.md "Engine / Build Conventions").
    Both defects below were measured on the pre-fix files.
    """

    def test_upload_frame_rejects_non_object_body(self):
        """_frame.py guarded the DECODE but not the SHAPE: valid JSON that is
        not an object reached `.get` and raised AttributeError."""
        from vision_server import _frame
        r = _frame.handle_upload_frame(b"[1,2]")
        self.assertIn("error", r)

    def test_upload_frame_still_rejects_undecodable_body(self):
        from vision_server import _frame
        r = _frame.handle_upload_frame(b"not json")
        self.assertIn("error", r)

    def test_upload_lcu_does_not_echo_raw_exception_text(self):
        """_relay.py returned f"bad_json: {e}", leaking the decoder's byte
        offset and document context past the redaction _err500 applies to
        every RAISED error."""
        from vision_server import _relay
        r = _relay.handle_upload_lcu(b"{definitely not json")
        self.assertEqual(r.get("error"), "bad_json")
        blob = json.dumps(r)
        for leak in ("line 1", "column", "char ", "Expecting"):
            self.assertNotIn(leak, blob)


if __name__ == "__main__":
    unittest.main()
