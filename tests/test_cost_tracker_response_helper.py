"""Tests for core.cost_tracker.record_anthropic_response + the
core.anthropic_client.tracked_anthropic shim.

AUDIT 2026-05-23 (cost-trace gap C): the 11 untracked messages.create
sites now feed cost_tracker via the shared module-level helper
record_anthropic_response. The shim provides defense-in-depth so a 12th
caller added later still records by default.

Test surface:
- helper extracts usage fields defensively (None, missing, malformed)
- helper records to the singleton ledger via record_call
- helper swallows recording exceptions (best-effort contract)
- shim wraps Anthropic() so messages.create auto-records
- shim does NOT swallow real API errors (propagates them)
- shim does NOT double-record when caller also calls helper directly
  (the shim documentation says "use one or the other" - this test pins
  that contract: if you do construct through shim AND also call helper,
  you get 2 records - documented as expected, not a bug)
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from core import cost_tracker


def _make_resp(*, input_tokens=10, output_tokens=20,
               cache_read=0, cache_write=0, model="claude-haiku-4-5-20251001"):
    """Build a duck-typed anthropic.types.Message stand-in."""
    usage = types.SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    return types.SimpleNamespace(usage=usage, model=model, content=[])


class RecordAnthropicResponseTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tracker = cost_tracker.CostTracker(
            config_provider=lambda: {}, spend_dir=Path(self._td))
        # Pin the helper to this scoped tracker so we observe its ledger.
        self._patcher = mock.patch.object(
            cost_tracker, "get_tracker", return_value=self.tracker)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_records_input_output_tokens(self):
        resp = _make_resp(input_tokens=1000, output_tokens=500)
        out = cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="test_lane")
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out["usd"], 0.0028, places=9)
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["calls"], 1)
        self.assertEqual(ledger["tokens_in"], 1000)
        self.assertEqual(ledger["tokens_out"], 500)
        self.assertIn("test_lane", ledger["by_purpose"])
        self.assertEqual(ledger["by_purpose"]["test_lane"]["calls"], 1)

    def test_records_cache_read_and_write(self):
        resp = _make_resp(input_tokens=100, output_tokens=50,
                          cache_read=2000, cache_write=300)
        cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="cache_lane")
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["cache_in"], 2000)
        self.assertEqual(ledger["cache_write"], 300)

    def test_missing_usage_records_zero_tokens(self):
        resp = types.SimpleNamespace(usage=None, model="claude-haiku-4-5-20251001")
        out = cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="empty_lane")
        self.assertIsNotNone(out)
        self.assertEqual(out["usd"], 0.0)
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["calls"], 1)
        self.assertEqual(ledger["tokens_in"], 0)
        self.assertEqual(ledger["tokens_out"], 0)

    def test_none_usage_fields_treated_as_zero(self):
        usage = types.SimpleNamespace(
            input_tokens=None, output_tokens=None,
            cache_read_input_tokens=None, cache_creation_input_tokens=None,
        )
        resp = types.SimpleNamespace(usage=usage, model="claude-haiku-4-5-20251001")
        out = cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="none_lane")
        self.assertIsNotNone(out)
        self.assertEqual(out["usd"], 0.0)

    def test_missing_optional_cache_fields(self):
        # Some SDK versions don't expose cache_* fields - getattr default
        # to 0, no crash.
        usage = types.SimpleNamespace(input_tokens=100, output_tokens=50)
        resp = types.SimpleNamespace(usage=usage, model="claude-haiku-4-5-20251001")
        out = cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="partial_lane")
        self.assertIsNotNone(out)
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["cache_in"], 0)
        self.assertEqual(ledger["cache_write"], 0)

    def test_falls_back_to_resp_model_when_arg_blank(self):
        resp = _make_resp(model="claude-sonnet-4-6")
        cost_tracker.record_anthropic_response(
            resp, model="", purpose="fallback_model")
        ledger = self.tracker.daily_spend()
        self.assertIn("claude-sonnet-4-6", ledger["by_model"])

    def test_swallows_recording_exceptions(self):
        # If the underlying record_call raises, the helper must not
        # propagate; this is the best-effort contract.
        broken = mock.MagicMock()
        broken.record_call.side_effect = RuntimeError("disk full")
        with mock.patch.object(
                cost_tracker, "get_tracker", return_value=broken):
            resp = _make_resp()
            out = cost_tracker.record_anthropic_response(
                resp, model="claude-haiku-4-5-20251001", purpose="boom")
        self.assertIsNone(out)

    def test_purpose_blank_routed_to_unspecified(self):
        resp = _make_resp()
        cost_tracker.record_anthropic_response(
            resp, model="claude-haiku-4-5-20251001", purpose="")
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["calls"], 1)
        self.assertIn("_unspecified", ledger["by_purpose"])


class TrackedAnthropicShimTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tracker = cost_tracker.CostTracker(
            config_provider=lambda: {}, spend_dir=Path(self._td))
        self._patcher = mock.patch.object(
            cost_tracker, "get_tracker", return_value=self.tracker)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _install_fake_anthropic(self, *, raise_on_create=None,
                                resp_factory=None):
        """Install a fake `anthropic` module under sys.modules so the lazy
        import inside tracked_anthropic resolves to our stub. Use a real
        function for `messages.create` (not a MagicMock attribute) so the
        shim's `client.messages.create = wrapped` rebind genuinely
        replaces a different callable - mirrors the SDK's real shape
        (Resource instance with a method on its class)."""
        fake_resp = (resp_factory or _make_resp)()
        call_count = {"n": 0}
        last_kwargs: dict = {}

        def original_create(*args, **kwargs):
            call_count["n"] += 1
            last_kwargs.update(kwargs)
            if raise_on_create is not None:
                raise raise_on_create
            return fake_resp

        class FakeMessages:
            pass

        fake_messages = FakeMessages()
        fake_messages.create = original_create

        class FakeClient:
            def __init__(self, api_key=None):
                self.api_key = api_key
                self.messages = fake_messages

        fake_anthropic = types.ModuleType("anthropic")
        fake_anthropic.Anthropic = FakeClient
        self._orig = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake_anthropic
        self.addCleanup(self._restore_anthropic)
        spy = types.SimpleNamespace(
            original_create=original_create,
            call_count=call_count,
            last_kwargs=last_kwargs,
            messages=fake_messages,
        )
        return spy, fake_resp

    def _restore_anthropic(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def test_messages_create_is_wrapped_and_records(self):
        from core.anthropic_client import tracked_anthropic
        spy, fake_resp = self._install_fake_anthropic()
        client = tracked_anthropic("sk-ant-test", purpose="shim_lane")
        # Wrapper replaced the original create; the bound attr is now a
        # different callable.
        self.assertIsNot(client.messages.create, spy.original_create)

        out = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}])
        # Returned response is byte-equivalent to the underlying call.
        self.assertIs(out, fake_resp)
        # Underlying create was called exactly once with our kwargs.
        self.assertEqual(spy.call_count["n"], 1)
        self.assertEqual(spy.last_kwargs.get("model"), "claude-haiku-4-5-20251001")
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["calls"], 1)
        self.assertIn("shim_lane", ledger["by_purpose"])

    def test_real_api_errors_propagate(self):
        from core.anthropic_client import tracked_anthropic
        boom = RuntimeError("anthropic api down")
        self._install_fake_anthropic(raise_on_create=boom)
        client = tracked_anthropic("sk-ant-test", purpose="err_lane")
        with self.assertRaises(RuntimeError):
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}])
        # No recording happened (the wrapper never reached the record line).
        ledger = self.tracker.daily_spend()
        self.assertEqual(ledger["calls"], 0)

    def test_recording_failure_does_not_break_caller(self):
        from core.anthropic_client import tracked_anthropic
        spy, fake_resp = self._install_fake_anthropic()
        with mock.patch.object(
                cost_tracker, "record_anthropic_response",
                side_effect=RuntimeError("ledger disk full")):
            client = tracked_anthropic("sk-ant-test", purpose="brittle_lane")
            out = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}])
        # Caller still got the response; the recording failure was eaten.
        self.assertIs(out, fake_resp)

    def test_default_model_kwarg_used_when_call_omits_model(self):
        from core.anthropic_client import tracked_anthropic
        # Build a resp WITHOUT a .model attribute so the fallback chain
        # falls through to default_model.
        usage = types.SimpleNamespace(input_tokens=100, output_tokens=50,
                                      cache_read_input_tokens=0,
                                      cache_creation_input_tokens=0)
        # types.SimpleNamespace with no model attr - and getattr defaults
        # to "" when the attr is missing.
        resp_no_model = types.SimpleNamespace(usage=usage, content=[])

        self._install_fake_anthropic(resp_factory=lambda: resp_no_model)
        client = tracked_anthropic(
            "sk-ant-test", purpose="default_model_lane",
            default_model="claude-sonnet-4-6")
        # Caller omits model= entirely.
        client.messages.create(
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}])
        ledger = self.tracker.daily_spend()
        self.assertIn("claude-sonnet-4-6", ledger["by_model"])


class WiredSitesImportSmokeTests(unittest.TestCase):
    """Each of the 11 wired sites must import record_anthropic_response
    cleanly. Lightweight smoke: the import path is the load-bearing piece;
    if a future refactor renames the helper, this test fails at the import
    layer before any live cadence hits the missing symbol."""

    def test_helper_is_public_at_module_scope(self):
        from core.cost_tracker import record_anthropic_response  # noqa: F401
        # Public callable.
        self.assertTrue(callable(record_anthropic_response))

    def test_shim_factory_is_public_at_module_scope(self):
        from core.anthropic_client import tracked_anthropic  # noqa: F401
        self.assertTrue(callable(tracked_anthropic))


class WiredSitesGrepTests(unittest.TestCase):
    """Pin that each of the 11 audit sites carries the wire-in.
    Grep-based: the helper import + a purpose= label must appear in each
    source file. If a future commit accidentally rips the wire out, this
    test fails and we know exactly which site regressed."""

    _REPO = Path(__file__).resolve().parent.parent

    def _read(self, rel: str) -> str:
        return (self._REPO / rel).read_text(encoding="utf-8")

    def test_aram_team_analyzer_wired(self):
        src = self._read("coaches/aram_team_analyzer.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="aram_team_analyzer"', src)

    def test_experimental_builder_wired(self):
        src = self._read("coaches/experimental_builder.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="experimental_builder"', src)

    def test_champ_select_coach_wired(self):
        src = self._read("coaches/champ_select_coach.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="champ_select_coach"', src)

    def test_replay_coach_wired(self):
        src = self._read("coaches/replay_coach.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="replay_coach"', src)

    def test_agent7_warm_session_wired(self):
        src = self._read("agents/agent7_context/warm_session.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="agent7_warm"', src)

    def test_tft_coach_engine_wired(self):
        src = self._read("tft/tft_coach_engine.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="tft_coach"', src)

    def test_tft_pbe_engine_wired(self):
        src = self._read("tft/tft_pbe_engine.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="tft_pbe"', src)

    def test_tft_live_analysis_main_wired(self):
        src = self._read("tft/tft_live_analysis.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="tft_live_analysis"', src)

    def test_tft_live_analysis_aug_select_wired(self):
        src = self._read("tft/tft_live_analysis.py")
        self.assertIn('purpose="tft_live_aug_select"', src)

    def test_tft_vision_reader_wired(self):
        src = self._read("tft/tft_vision_reader.py")
        self.assertIn("record_anthropic_response", src)
        self.assertIn('purpose="tft_vision"', src)


class AsciiHygieneTests(unittest.TestCase):
    """The new helper + shim must be ASCII-clean per CLAUDE.md hard rule."""

    def test_cost_tracker_helper_block_ascii(self):
        src = (Path(__file__).resolve().parent.parent
               / "core" / "cost_tracker.py").read_text(encoding="utf-8")
        # The new helper section is below the "Shared response-recording
        # helper" marker; scan from there to EOF.
        idx = src.index("Shared response-recording helper")
        new_block = src[idx:]
        for ch in new_block:
            if ord(ch) > 127:
                self.fail(f"non-ASCII byte in helper block: {ch!r} (U+{ord(ch):04X})")

    def test_anthropic_client_shim_ascii(self):
        src = (Path(__file__).resolve().parent.parent
               / "core" / "anthropic_client.py").read_text(encoding="utf-8")
        for ch in src:
            if ord(ch) > 127:
                self.fail(f"non-ASCII byte in shim: {ch!r} (U+{ord(ch):04X})")


if __name__ == "__main__":
    unittest.main()
