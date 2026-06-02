"""1-PC self-heal for the Live Client relay (vision_server/_relay.py).

After the Game-PC -> Legion consolidation League runs on this host, so the
:8889 liveclient relay can read Riot's :2999 in-process when the relayed
snapshot is stale/missing. This makes the RC-LiveClientRelay agent an
optimization (pre-warms the cache) rather than a hard dependency: if it dies,
get_latest_liveclient() self-reads :2999 and coaching continues.

Contract:
  - a FRESH relayed POST short-circuits the self-read (zero :2999 traffic).
  - a STALE/missing cache + a reachable :2999 -> self-read populates + serves.
  - a self-read failure (no game / :2999 down) -> empty snapshot, no crash.
  - self-reads are throttled so a no-game steady state never hammers :2999.
  - a remote GAME_HOST (legacy 2-PC override) never self-reads (Riot's :2999
    binds localhost-only on the remote box; the relay agent stays primary).
"""
from __future__ import annotations

import time
import unittest

from vision_server import _relay


class LiveClientSelfHealTests(unittest.TestCase):
    def setUp(self):
        _relay._reset_self_read_state()
        self._orig_fetch = _relay._fetch_liveclient_direct
        self._orig_host = _relay.GAME_HOST
        self.calls = []

    def tearDown(self):
        _relay._fetch_liveclient_direct = self._orig_fetch
        _relay.GAME_HOST = self._orig_host
        _relay._reset_self_read_state()

    def _stub_fetch(self, ret):
        def _f():
            self.calls.append(time.time())
            return ret
        _relay._fetch_liveclient_direct = _f

    def test_fresh_post_short_circuits_self_read(self):
        self._stub_fetch({"x": 1})
        _relay.handle_upload_liveclient(b'{"gameData": {"gameTime": 5}}')
        out = _relay.get_latest_liveclient()
        self.assertEqual(out.get("data"), {"gameData": {"gameTime": 5}})
        self.assertEqual(self.calls, [])  # fresh POST -> no :2999 read

    def test_stale_cache_self_reads_2999(self):
        self._stub_fetch({"gameData": {"gameTime": 99}})
        out = _relay.get_latest_liveclient()  # cache empty/stale -> self-read
        self.assertEqual(out.get("data"), {"gameData": {"gameTime": 99}})
        self.assertEqual(out.get("source"), "self_read")
        self.assertEqual(len(self.calls), 1)

    def test_self_read_failure_returns_empty(self):
        self._stub_fetch(None)  # :2999 down / no game
        out = _relay.get_latest_liveclient()
        self.assertIsNone(out.get("data"))
        self.assertEqual(len(self.calls), 1)

    def test_self_read_throttled(self):
        self._stub_fetch(None)
        _relay.get_latest_liveclient()
        _relay.get_latest_liveclient()  # within throttle window
        self.assertEqual(len(self.calls), 1)

    def test_remote_host_no_self_read(self):
        _relay.GAME_HOST = "10.1.2.3"
        self._stub_fetch({"gameData": {"gameTime": 7}})
        out = _relay.get_latest_liveclient()
        self.assertIsNone(out.get("data"))
        self.assertEqual(self.calls, [])  # remote -> relay agent stays primary

    def test_no_banned_codepoints(self):
        # Hard-rule ban: em/en-dashes + smart quotes. Pre-existing U+2500
        # box-drawing dividers are operator-gated retro-sweep, not this slice.
        text = (
            __import__("pathlib").Path(_relay.__file__).read_text(encoding="utf-8")
        )
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"_relay.py has banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
