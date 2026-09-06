"""Gaps the lane 8 cycle 27 mutation pass found in its OWN new tests.

Written by the merger, not by the slice agents, because the mutation run is
what exposed them: mutating `lib/http/client.py` in three places left the
two agent-authored test files completely green.

  M8  the empty-string filter in `_parse_blocklist` was removed  -> SURVIVED
  M9  the scheme guard at the top of `request()` was removed     -> SURVIVED
  M10 the `finally` that releases the half-open probe slot       -> untested

M9 is very nearly an EQUIVALENT mutant and is worth spelling out. Deleting
the guard does not let a `file://` url through, because `is_blocked()` also
rejects a non-allowlisted scheme, so `request()` still raises `Blocked`. What
changes is only the MESSAGE - the caller is told the hostname was blocked
when the real reason was the scheme. That is a diagnostic regression rather
than a security one, so the guard is pinned by asserting what the error
SAYS. The alternative was to delete the redundant guard; keeping it and
making it load-bearing is the better trade because a caller debugging a
refused url needs to know which rule refused it.

M10 covers a guard on a non-default call path, which is the standing way a
guard ships untested: every ordinary request settles the probe slot through
`_on_success`, so nothing exercised the exception route.
"""
from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
import time
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lib.http.client as http_client  # noqa: E402
from lib.http.client import Blocked, HttpClient  # noqa: E402


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class EmptyBlocklistEntriesAreDropped(unittest.TestCase):
    """M8: a stray empty string must not block the entire internet.

    `host.endswith("")` is True for every hostname, so a single empty entry
    in `suffixes` - a trailing comma in a hand-edited JSON file is enough -
    would silently deny every outbound fetch in the tree.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_an_empty_suffix_does_not_block_every_host(self) -> None:
        p = self.tmp / "bl.json"
        _write(p, {"hostnames": [], "suffixes": ["", "   ", ".ru"]})
        c = HttpClient(p)
        self.assertEqual(c.blocklist_state, "ok")
        self.assertFalse(
            c.is_blocked("https://ddragon.leagueoflegends.com/x"),
            "an empty suffix made endswith('') true for every host, denying "
            "every outbound fetch",
        )

    def test_a_real_suffix_alongside_an_empty_one_still_denies(self) -> None:
        p = self.tmp / "bl.json"
        _write(p, {"hostnames": [], "suffixes": ["", ".ru"]})
        c = HttpClient(p)
        self.assertTrue(c.is_blocked("https://site.ru/x"))
        self.assertEqual(c._blocklist_suffixes, (".ru",))

    def test_an_empty_hostname_entry_is_dropped(self) -> None:
        p = self.tmp / "bl.json"
        _write(p, {"hostnames": ["", "  ", "reddit.com"], "suffixes": []})
        c = HttpClient(p)
        self.assertEqual(c._blocklist_hosts, {"reddit.com"})
        self.assertFalse(c.is_blocked("https://ddragon.leagueoflegends.com/x"))
        self.assertTrue(c.is_blocked("https://reddit.com/x"))


class ARefusedSchemeSaysItWasTheScheme(unittest.TestCase):
    """M9: the refusal reason must name the scheme, not the hostname.

    Both the scheme guard and `is_blocked()` refuse a `file://` url, so the
    only observable difference is the message. Without this the guard can be
    deleted and every other test stays green.
    """

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.client = HttpClient(http_client._BLOCKLIST_PATH)

    def test_file_scheme_refusal_names_the_scheme(self) -> None:
        with self.assertRaises(Blocked) as ctx:
            self.client.request("GET", "file://localhost/etc/passwd")
        msg = str(ctx.exception)
        self.assertIn("scheme", msg.lower())
        self.assertIn("file", msg)
        self.assertNotIn(
            "hostname blocked", msg,
            "a scheme rejection reported itself as a hostname block, which "
            "sends the reader to the blocklist file for an answer that is "
            "not there",
        )

    def test_ftp_scheme_refusal_names_the_scheme(self) -> None:
        with self.assertRaises(Blocked) as ctx:
            self.client.request("GET", "ftp://example.com/x")
        self.assertIn("scheme", str(ctx.exception).lower())

    def test_a_genuinely_blocked_host_still_says_hostname(self) -> None:
        """The other side of the same coin - do not over-rotate."""
        with self.assertRaises(Blocked) as ctx:
            self.client.request("GET", "https://reddit.com/r/x")
        self.assertIn("hostname blocked", str(ctx.exception))


class TheHalfOpenProbeSlotIsAlwaysReleased(unittest.TestCase):
    """M10: an exception no handler anticipates must not wedge the host.

    `_check_breaker` admits exactly one probe by setting `probe_in_flight`.
    `http.client.IncompleteRead` is an HTTPException, NOT an OSError, so it
    escapes both `except` arms in `request()`. Without the `finally` the flag
    stays True and every later call to that hostname raises CircuitOpen
    forever - the breaker never closes because no probe can ever run again.
    """

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.host = "ddragon.leagueoflegends.com"
        self.url = f"https://{self.host}/api/versions.json"

    def _client_with_an_elapsed_open_breaker(self) -> tuple[HttpClient, object]:
        c = HttpClient(http_client._BLOCKLIST_PATH)
        st = c._host_state(self.host)
        st.failures = http_client.BREAKER_THRESHOLD
        st.opened_at = time.monotonic() - (http_client.BREAKER_COOLDOWN_SEC + 1.0)
        return c, st

    def test_probe_slot_released_when_the_response_read_raises(self) -> None:
        c, st = self._client_with_an_elapsed_open_breaker()
        self.assertFalse(st.probe_in_flight)
        with mock.patch.object(c, "_opener") as opener:
            opener.open.side_effect = IncompleteRead(b"partial")
            with self.assertRaises(IncompleteRead):
                c.get(self.url)
        self.assertFalse(
            st.probe_in_flight,
            "the half-open probe slot leaked, so this hostname is wedged "
            "CircuitOpen for the life of the process",
        )

    def test_a_wedged_slot_would_block_the_next_probe(self) -> None:
        """Proves the leak MATTERS - this is why the flag has to be cleared."""
        c, st = self._client_with_an_elapsed_open_breaker()
        st.probe_in_flight = True
        with self.assertRaises(http_client.CircuitOpen):
            c._check_breaker(self.host, time.monotonic())

    def test_probe_slot_released_on_an_ordinary_success(self) -> None:
        c, st = self._client_with_an_elapsed_open_breaker()
        # `read` takes an optional amount because the real
        # http.client.HTTPResponse.read does, and the client passes one once
        # RM-351's byte cap is in force. It must also EXHAUST - a stub that
        # answers b"ok" forever turns the bounded read into a 16 MiB loop.
        # Widened 2026-09-06; the observed body is still b"ok".
        remaining = io.BytesIO(b"ok")
        resp = mock.Mock(
            read=lambda amt=None: (
                remaining.read() if amt is None else remaining.read(amt)
            ),
            getheaders=lambda: [],
            status=200,
            url=self.url,
        )
        ctx = mock.MagicMock()
        ctx.__enter__ = mock.Mock(return_value=resp)
        ctx.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(c, "_opener") as opener:
            opener.open.return_value = ctx
            got = c.get(self.url)
        self.assertEqual(got.status, 200)
        self.assertFalse(st.probe_in_flight)
        self.assertIsNone(st.opened_at, "a successful probe must close the breaker")


if __name__ == "__main__":
    unittest.main()
