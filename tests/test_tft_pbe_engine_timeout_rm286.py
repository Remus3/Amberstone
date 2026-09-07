"""
Lane 8 (Headless-True-Audit) - RM-286 regression test for
`tft/tft_pbe_engine.py`.

WHAT RM-286 SAYS: `TftPbeCoachEngine.__init__` sets `self._timeout = 20` at
`tft/tft_pbe_engine.py:353` and re-reads it from `config/coach_settings.json`
at `:360`, but the value is READ NOWHERE. The `self._client.messages.create`
call at `:434` passes only `model` / `max_tokens` / `system` / `messages`, so
the request inherits the Anthropic SDK default (600s). That matters because
`_run_safe` at `:404` takes `self._lock` with `blocking=False` and holds it
across the whole call, so while one request hangs every later `submit` logs
"TFT PBE coach busy - skipping" and the overlay goes stale for up to ten
minutes.

RED AT HEAD: this module was RED at HEAD (commit 506f81e8, before any fix).
THE EXACT REASON IT WAS RED: `messages.create` was reached and its kwargs were
recorded, but the recorded kwargs contained no `timeout` key at all - the
assertion failed on `assertIn("timeout", seen)` with the recorded key set
being exactly `['model', 'max_tokens', 'system', 'messages']`. It was NOT red
from an import error, a missing state key, or a fake-object AttributeError:
each test first asserts that `messages.create` actually fired, so an
early-return (for example the `core.cost_tracker` spend gate) would report a
distinct failure message.

GREEN AFTER: `messages.create(...)` additionally receives
`timeout=self._timeout`.

Shape mirrors tests/test_tft_coach_engine_audit.py TestRequestTimeout, which
pins the same defect on the sibling live TFT engine.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tft.tft_pbe_engine import TftPbeCoachEngine

# _build_prompt reads every state key through `.get(...)` with a default
# (tft/tft_pbe_engine.py:190-200), so this minimal pair is sufficient to drive
# a full _run without a KeyError. stage/round are supplied because they select
# the round type through GOD_ROUNDS / PVE_ROUNDS / BOON_ROUND at :205-215.
_STATE = {"stage": 2, "round": 1}


def _engine(tmp: Path) -> TftPbeCoachEngine:
    """Build an engine without touching the real key file or the real env."""
    with patch.object(TftPbeCoachEngine, "_read_key_file", return_value=""):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            return TftPbeCoachEngine(tmp / "tft_pbe_coaching_data.json")


class _FakeText:
    """`_run` reads `response.content[0].text` at tft/tft_pbe_engine.py:449."""

    text = "Action: ROLL"


class _FakeResponse:
    content = [_FakeText()]


def _install_recording_client(eng: TftPbeCoachEngine) -> dict:
    """Swap in a client whose messages.create records its kwargs."""
    seen: dict = {}

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            seen["_called"] = True
            return _FakeResponse()

    eng._client = type("C", (), {"messages": _Msgs()})()
    return seen


class TestRequestTimeout(unittest.TestCase):
    """RM-286 - self._timeout is assigned twice and read nowhere, so the
    Anthropic request carries no timeout while self._lock is held."""

    def _drive(self, timeout_value):
        """Run one _run() and return (recorded kwarg names, recorded kwargs).

        The kwarg NAMES are returned separately so an assertion failure prints
        a four-item list rather than the whole cached system prompt.
        """
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            eng._timeout = timeout_value
            seen = _install_recording_client(eng)
            eng._run(dict(_STATE))
        self.assertTrue(
            seen.pop("_called", False),
            "messages.create never fired - _run returned early (spend gate or "
            "missing client), so this run says nothing about the timeout "
            "kwarg.",
        )
        return sorted(seen), seen

    def test_configured_timeout_reaches_the_api_call(self):
        names, seen = self._drive(7)
        self.assertIn(
            "timeout", names,
            "messages.create carried no timeout kwarg, so the request "
            "inherits the SDK default (600s) while self._lock is held",
        )
        self.assertEqual(seen["timeout"], 7)

    def test_a_different_configured_timeout_also_propagates(self):
        """Guards against a hardcoded literal being passed instead of the
        value config/coach_settings.json actually configured."""
        names, seen = self._drive(33)
        self.assertIn(
            "timeout", names,
            "messages.create carried no timeout kwarg",
        )
        self.assertEqual(seen["timeout"], 33)

    def test_default_timeout_is_finite_and_positive(self):
        """The engine default must be a usable bound - a None or 0 timeout
        would restore the unbounded-hang behaviour RM-286 describes."""
        with tempfile.TemporaryDirectory() as d:
            eng = _engine(Path(d))
            self.assertIsInstance(eng._timeout, (int, float))
            self.assertGreater(eng._timeout, 0)


if __name__ == "__main__":
    unittest.main()
