"""RM-314 - the four untimed vision-path `messages.create` call sites.

WHAT RM-314 SAYS (`BACKLOG.md:63`): four production `messages.create` call
sites pass no `timeout=`, and no `anthropic.Anthropic(...)` construction
anywhere in the repo passes one either, so each of the four inherits the
Anthropic SDK default of 600 s. The per-call kwarg is therefore the only
bound that exists. The four sites are:

  1. `modes/shared_vision.py:389`      GameVisionReader._extract
  2. `tft/tft_vision_reader.py:186`    TftVisionReader._extract_local
  3. `vision_server/_inference.py:246` handle_vision
  4. `vision_server/_inference.py:291` handle_coach

RE-VERIFIED this run by an AST sweep over every tracked `.py` outside
`tests/` and `docs/`: 20 production `messages.create` sites exist,
14 carry `timeout` and 6 do not; the 6 are exactly these 4 plus
`tft/tft_live_analysis.py:391` and `:457`, which are RM-302 and out of scope
here. The same sweep found 17 `anthropic.Anthropic(...)` constructions, every
one passing exactly `api_key` + `base_url` and none passing `timeout`. (The
row body's "12" is understated; `BACKLOG.md` carries its own correction to 17,
and `tests/test_anthropic_base_url_pin.py` already enumerates the 17.)

RED AT HEAD: every test below was RED before the fix. THE EXACT REASON: the
fake client recorded the call and the recorded kwargs were exactly
`['max_tokens', 'messages', 'model']` (sites 1, 2 and 4) or
`['max_tokens', 'messages', 'model', 'system']` (site 3), so
`assertIn("timeout", kwargs)` failed. It was NOT red from an import error or
a missing fixture key: each test first asserts `messages.create` actually
fired, so an early return (the cost-tracker spend gate, the moon_proxy relay
short-circuit, a bad-model rejection) reports a distinct failure message.

WHY THESE VALUES, per site rather than one blanket constant. Evidence used:
  - The repo convention at the 14 already-timed sites: 20 s for a full coach
    turn with a system prompt (`coaches/aram_coach.py:1105`,
    `arena_coach.py:806`, `brawl_coach.py:503`, `replay_coach.py:225`,
    `tft_coach_engine.py:605`, `tft_pbe_engine.py:353`), 15 s for a shorter
    follow-up, 12 s for champ select, 10 s for the shortest arena call.
  - The only measured latency distribution in the repo,
    `data/coach_trace.jsonl`, n=200 ARAM coach calls: p50 5972 ms,
    p90 7049 ms, p99 10950 ms, max 26000 ms. That site ships `timeout=20`.
  - The live vision-server `/stats` ring was probed this run (uptime 96106 s)
    and holds ZERO vision and ZERO coach samples, so no per-site live
    percentile exists to cite and none is invented here.
  - Loop cadences, which bound how long a hung call may stall its caller:
    ARAM 25.0 s (`coaches/aram_coach.py:571`, fast mode 6.0 s at `:583`),
    Arena 20.0 s (`:426`), Brawl 18.0 s (`:206`), TFT 15.0 s
    (`tft/tft_live_analysis.py:223`).
  - `core/moon_proxy.py:28` `TIMEOUT_S = 8`. moon_proxy is the SOLE in-repo
    client of `:8889/vision` and `:8889/coach` (`core/moon_proxy.py:108`
    and `:151`), and it abandons the request at 8 s.

  Site 1, 20 s: Sonnet-4.6 (`modes/shared_vision.py:110`, `:273`) over a
    full-screen frame. Slowest model of the four, and it is the LAST resort -
    it only runs after the relay path already failed, so cutting it short
    means no vision at all for that cycle. 20 s keeps a hung call inside
    roughly one Arena/Brawl cycle (20.0 / 18.0 s) and matches the repo
    ceiling for Sonnet-class work. Worst case per cycle becomes 8 s relay
    plus 20 s direct = 28 s, against 8 + 600 = 608 s today.
  Site 2, 15 s: Haiku (`tft/tft_live_analysis.py:220` forwards a model
    defaulting to claude-haiku-4-5), over four stitched crops that
    `_CROP_REGIONS` documents as ~350 tiles against ~1400 for a full frame,
    i.e. a quarter of the image tokens. Cheaper model AND a much smaller
    payload than site 1, so it does not need site 1 headroom. 15 s equals the
    TFT scan cadence exactly, so a hung local extract cannot outlive the
    round it was scanning, and it still clears the p99 of the one measured
    distribution (10.95 s).
  Sites 3 and 4, 10 s EACH. These two ARE different call shapes - site 3
    sends an image plus a cache_control system block at max_tokens=1400,
    site 4 is text-only at max_tokens=600 - and that difference was checked
    rather than assumed. It is not the binding constraint: the same single
    client sits in front of both and abandons at 8 s, so past ~10 s either
    handler is producing a response nobody will read, on a
    ThreadingHTTPServer worker that also serves the 1 Hz LCU upload path.
    10 s is that 8 s client budget plus margin, so the server never abandons
    a request its caller would still have accepted, and it is the value the
    repo already uses for its shortest call (`coaches/arena_coach.py:1077`).

MUTATION: deleting the `timeout=` argument at any one site turns exactly its
own test red on `assertIn`, and turns `test_no_untimed_messages_create_in
_owned_files` red as well. Recorded in the RM-314 commit message.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import vision_server._inference as inference
from modes.shared_vision import GameVisionReader
from tft.tft_vision_reader import TftVisionReader

# The SDK default this row exists to displace. Every site must be far below it.
_SDK_DEFAULT_S = 600

# Chosen per site - see the module docstring for the argument behind each.
SHARED_VISION_TIMEOUT_S = 20
TFT_VISION_TIMEOUT_S = 15
RELAY_VISION_TIMEOUT_S = 10
RELAY_COACH_TIMEOUT_S = 10

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The three files this row owns. `tft/tft_live_analysis.py` is RM-302 and is
# deliberately absent.
_OWNED = (
    "modes/shared_vision.py",
    "tft/tft_vision_reader.py",
    "vision_server/_inference.py",
)


class _Block:
    """A content block shaped like the SDK text block."""

    def __init__(self, text: str) -> None:
        self.text = text


class _Response:
    """Shaped for `resp.content[0].text` and `_first_text(resp)` alike."""

    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]
        # None so the cost-tracker hooks skip cleanly without a usage stub.
        self.usage = None


class _Messages:
    def __init__(self, response: _Response) -> None:
        self.calls: list[dict] = []
        self._response = response

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _Client:
    def __init__(self, text: str = '{"gold": 5}') -> None:
        self.messages = _Messages(_Response(text))


class _Tracker:
    """Permissive stand-in for `core.cost_tracker.get_tracker()`.

    The real tracker can refuse the call (`allow_call`) or disable the gate
    (`gate_disabled`); either returns before `messages.create` is reached,
    which is exactly the early return these tests must not silently hit.
    """

    def allow_call(self) -> bool:
        return True

    def gate_disabled(self, _name: str) -> bool:
        return False

    def record_call(self, **_kwargs) -> None:
        return None

    def vision_dedupe_get(self, _key):
        return None


def _permissive_tracker():
    return patch("core.cost_tracker.get_tracker", lambda: _Tracker())


class _TimeoutKwargCase(unittest.TestCase):
    """Shared assertions so each site is judged the same way."""

    def assert_timeout_reached(self, calls, expected: int, site: str) -> None:
        # Non-vacuity gate first: a test that never reached the SDK call would
        # otherwise pass its "no bad timeout" reading by never looking.
        self.assertEqual(
            len(calls), 1,
            f"{site}: messages.create fired {len(calls)} times, expected exactly 1 - "
            "the call site was not reached, so this test proves nothing",
        )
        kwargs = calls[0]
        self.assertIn(
            "timeout", kwargs,
            f"{site}: messages.create received {sorted(kwargs)} with no timeout key, "
            f"so the request inherits the SDK default of {_SDK_DEFAULT_S}s",
        )
        self.assertEqual(
            kwargs["timeout"], expected,
            f"{site}: timeout reached the call as {kwargs['timeout']!r}, expected {expected}",
        )
        self.assertLess(
            kwargs["timeout"], _SDK_DEFAULT_S,
            f"{site}: a timeout of {kwargs['timeout']!r} is no tighter than the SDK default",
        )
        self.assertGreater(
            kwargs["timeout"], 0,
            f"{site}: a non-positive timeout is refused by the API on every call",
        )


class TestSharedVisionTimeout(_TimeoutKwargCase):
    """`modes/shared_vision.py` GameVisionReader._extract."""

    def _reader(self):
        reader = GameVisionReader("sk-ant-test")
        client = _Client()
        reader._client = client
        # USE_RELAY True short-circuits into core.moon_proxy and never reaches
        # the direct SDK call this row is about. The class documents the
        # per-instance override at modes/shared_vision.py:252.
        reader.USE_RELAY = False
        return reader, client

    def test_extract_passes_timeout_to_messages_create(self):
        reader, client = self._reader()
        with _permissive_tracker():
            reader._extract("aGVsbG8=")
        self.assert_timeout_reached(
            client.messages.calls, SHARED_VISION_TIMEOUT_S,
            "modes/shared_vision.py GameVisionReader._extract",
        )

    def test_timeout_is_the_only_kwarg_added(self):
        """The fix must not disturb the existing request shape."""
        reader, client = self._reader()
        with _permissive_tracker():
            reader._extract("aGVsbG8=")
        self.assertEqual(
            sorted(client.messages.calls[0]),
            ["max_tokens", "messages", "model", "timeout"],
        )


class TestTftVisionReaderTimeout(_TimeoutKwargCase):
    """`tft/tft_vision_reader.py` TftVisionReader._extract_local."""

    def _reader(self):
        reader = TftVisionReader("sk-ant-test")
        client = _Client()
        reader._client = client
        return reader, client

    def test_extract_local_passes_timeout_to_messages_create(self):
        reader, client = self._reader()
        # _extract_local is called directly: _extract tries core.moon_proxy
        # first (tft/tft_vision_reader.py:174) and returns before the SDK call
        # whenever the relay answers.
        reader._extract_local("aGVsbG8=")
        self.assert_timeout_reached(
            client.messages.calls, TFT_VISION_TIMEOUT_S,
            "tft/tft_vision_reader.py TftVisionReader._extract_local",
        )

    def test_timeout_is_the_only_kwarg_added(self):
        reader, client = self._reader()
        reader._extract_local("aGVsbG8=")
        self.assertEqual(
            sorted(client.messages.calls[0]),
            ["max_tokens", "messages", "model", "timeout"],
        )


class TestVisionServerRelayTimeouts(_TimeoutKwargCase):
    """`vision_server/_inference.py` handle_vision (:246), handle_coach (:291)."""

    def test_handle_vision_passes_timeout_to_messages_create(self):
        client = _Client()
        with patch.object(inference, "_get_client", lambda: client), _permissive_tracker():
            inference.handle_vision(json.dumps({"image_b64": "aGVsbG8="}).encode())
        self.assert_timeout_reached(
            client.messages.calls, RELAY_VISION_TIMEOUT_S,
            "vision_server/_inference.py handle_vision",
        )

    def test_handle_coach_passes_timeout_to_messages_create(self):
        client = _Client(text="Action: ROLL")
        with patch.object(inference, "_get_client", lambda: client), _permissive_tracker():
            inference.handle_coach(json.dumps({"prompt": "what now"}).encode())
        self.assert_timeout_reached(
            client.messages.calls, RELAY_COACH_TIMEOUT_S,
            "vision_server/_inference.py handle_coach",
        )

    def test_the_two_relay_sites_are_separately_bounded(self):
        """Each handler must carry its own kwarg.

        Guards against a fix that bounds one handler and leaves the other on
        the SDK default while the suite still reads green overall.
        """
        vision_client = _Client()
        coach_client = _Client(text="Action: ROLL")
        with patch.object(inference, "_get_client", lambda: vision_client), _permissive_tracker():
            inference.handle_vision(json.dumps({"image_b64": "aGVsbG8="}).encode())
        with patch.object(inference, "_get_client", lambda: coach_client), _permissive_tracker():
            inference.handle_coach(json.dumps({"prompt": "what now"}).encode())
        self.assertIn("timeout", vision_client.messages.calls[0])
        self.assertIn("timeout", coach_client.messages.calls[0])
        # Different call shapes, same binding constraint - see the docstring.
        self.assertEqual(
            sorted(vision_client.messages.calls[0]),
            ["max_tokens", "messages", "model", "system", "timeout"],
        )
        self.assertEqual(
            sorted(coach_client.messages.calls[0]),
            ["max_tokens", "messages", "model", "timeout"],
        )


class TestNoUntimedCallSiteRemains(unittest.TestCase):
    """Durable sweep over the three files this row owns.

    The per-site tests above pin the four sites that exist today. This one
    fails if a NEW untimed `messages.create` is added to any of the three,
    which is how the defect got in.
    """

    def test_no_untimed_messages_create_in_owned_files(self):
        offenders = []
        found = 0
        for rel in _OWNED:
            path = _REPO_ROOT / rel
            self.assertTrue(path.is_file(), f"{rel} does not exist on disk")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "create":
                    continue
                owner = func.value
                if not (isinstance(owner, ast.Attribute) and owner.attr == "messages"):
                    continue
                found += 1
                if not any(kw.arg == "timeout" for kw in node.keywords):
                    offenders.append(f"{rel}:{node.lineno}")
        # Non-vacuity: an AST sweep that matched nothing would pass silently.
        self.assertEqual(
            found, 4,
            f"expected 4 messages.create sites across {list(_OWNED)}, found {found} - "
            "the sweep pattern no longer matches the code it guards",
        )
        self.assertEqual(offenders, [], f"messages.create with no timeout=: {offenders}")


if __name__ == "__main__":
    unittest.main()
