"""Lane 8 cycle 27 - deep audit of lib/http/client.py (the outbound HTTP gate).

lib/http/client.py is the single chokepoint every third-party fetch in the tree
is supposed to pass through. Its whole reason to exist is the deny list in
lib/http/blocklist.json plus a polite UA, a per-host rate limit and a breaker.
Until this cycle it carried ZERO tests, and three ways past the deny gate were
measured live on 2026-08-30 against the real module:

  W1  TRAILING-DOT HOST BYPASS. ``is_blocked()`` matches
      ``urlparse(url).hostname`` against the deny set verbatim. A fully
      qualified DNS name may carry a trailing root dot, and that name resolves
      IDENTICALLY to the dotless form, but "reddit.com." is not in the set and
      "reddit.com.".endswith("reddit.com") is False, so BOTH halves of the
      matcher fall open:
          is_blocked("https://reddit.com/r/x")  -> True
          is_blocked("https://reddit.com./r/x") -> False   <- same site
          is_blocked("https://site.ru./x")      -> False   <- suffix ".ru"
      Blocklist ENTRIES are equally unnormalized, so a deny row authored as
      "evil.example." never matches the plain host either.

  W2  NO SCHEME ALLOWLIST, AND THE DEFAULT OPENER HAS A FileHandler. Nothing
      constrains the scheme. urllib's default opener includes FileHandler, so
      "file://localhost/<path>" survives is_blocked() (hostname is "localhost")
      and reaches urlopen, which opens the LOCAL FILE. Measured on this box the
      bytes are read into ``body`` and the call then dies at
      ``resp.getheaders()`` with AttributeError - the read happened, only the
      return did not. "file:///..." and "data:..." are blocked TODAY, but only
      by accident of the empty-hostname rule, not by any scheme policy;
      "ftp://example.com/x", "gopher://example.com/x" and the scheme-less
      "//example.com/x" all sail straight through.

  W3  REDIRECTS ARE UNCHECKED. The default opener also carries
      HTTPRedirectHandler, and the deny gate runs exactly once, on the URL the
      caller passed. An allowed host that answers 302 with a Location pointing
      at a denied host is followed and fetched. Proven here with two loopback
      servers: the "denied" server records the hit.

TARGET BEHAVIOUR these tests are written against (they are RED until the
merger lands the fix in lib/http/client.py):

  1. Hostnames are lowercased AND stripped of trailing dots before matching, on
     both the incoming URL and the blocklist entries.
  2. A module-level ALLOWED_SCHEMES = ("http", "https"). is_blocked() is True
     for anything else, and request() raises lib.http.client.Blocked for it -
     before urlopen is called at all.
  3. Redirects are still followed, but every redirect TARGET is re-checked. A
     302 into a denied host raises Blocked instead of fetching, and the denied
     host is never contacted. A 302 into an allowed URL still succeeds.
  4. None of the already-correct behaviour regresses.

Portability notes for CI:
  - Fully offline. Nothing resolves or contacts an external name. The two
    servers bind 127.0.0.1 on an OS-chosen port; the denied host is spelled
    "localhost" so that it is a DIFFERENT hostname string from "127.0.0.1"
    while still being loopback if the pre-fix code wrongly connects to it.
    Once the fix lands, that name is never resolved at all.
  - Every blocklist used here is written into a per-test temp dir. The repo's
    real lib/http/blocklist.json is never read or mutated.
  - MIN_INTERVAL_SEC = 1.0 makes _rate_gate sleep on the SECOND request to a
    given host from a given client, so each test builds its own HttpClient and
    issues at most one real request per host.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from lib.http import client as http_client


def _write_blocklist(directory, hostnames, suffixes):
    """Write a throwaway blocklist.json and return its Path."""
    path = Path(directory) / "blocklist.json"
    payload = {"version": 1, "hostnames": list(hostnames), "suffixes": list(suffixes)}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _FakeHttpResponse:
    """Minimal stand-in for an HTTPResponse, for the urlopen spy."""

    def __init__(self, url):
        self.status = 200
        self.url = url
        self._rest = b"spy-body"

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amt=None):
        # `amt` accepted because the real http.client.HTTPResponse.read takes
        # it and the client passes it once RM-351's byte cap is in force.
        # Widened 2026-09-06; a single call still yields the whole spy body.
        if amt is None:
            return b"spy-body"
        head, self._rest = self._rest[:amt], self._rest[amt:]
        return head

    def getheaders(self):
        return [("Content-Type", "text/plain")]


class _UrlopenSpy:
    """Records every URL that reaches urlopen and answers with a fake 200."""

    def __init__(self):
        self.calls = []

    def __call__(self, req, **kwargs):
        url = getattr(req, "full_url", None) or str(req)
        self.calls.append(url)
        return _FakeHttpResponse(url)


class _LoopbackServer:
    """Throwaway HTTP server on 127.0.0.1, OS-chosen port.

    ``routes`` maps a path to ("redirect", location) or ("body", text). The
    dict is read at request time, so a caller may fill in a route that needs
    this server's own port after construction.
    """

    def __init__(self, routes):
        self.routes = routes
        self.hits = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                outer.hits.append(self.path)
                action = outer.routes.get(self.path)
                if action is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                kind, payload = action
                if kind == "redirect":
                    self.send_response(302)
                    self.send_header("Location", payload)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = payload.encode("ascii")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _ClientTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rc-lane8-c27-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def make_client(self, hostnames=(), suffixes=()):
        return http_client.HttpClient(blocklist_path=_write_blocklist(self.tmpdir, hostnames, suffixes))

    def attempt(self, client, method, url, timeout=10.0):
        """Run request() and reduce the outcome to one comparable string.

        assertRaises would hide WHY a test is red when the current code raises
        something else entirely (the file:// path dies in getheaders, an
        unreachable host raises HttpError). One string keeps the failure line
        readable.
        """
        try:
            resp = client.request(method, url, timeout=timeout)
        except http_client.Blocked:
            return "Blocked"
        except Exception as exc:  # noqa: BLE001 - the point is to name whatever came out
            return f"{type(exc).__name__}: {exc}"
        return f"completed status={resp.status} final_url={resp.url} body={resp.body!r}"


class TestHostNormalization(_ClientTestBase):
    """W1 - the deny matcher must normalize hosts before comparing."""

    def test_trailing_dot_host_bypasses_the_hostname_denylist(self):
        """W1: 'reddit.com.' is the same site as 'reddit.com' and must be denied."""
        cli = self.make_client(hostnames=["reddit.com"])
        self.assertTrue(cli.is_blocked("https://reddit.com/r/x"), "control: the dotless form must stay blocked")
        self.assertTrue(
            cli.is_blocked("https://reddit.com./r/x"),
            "a trailing root dot is a legal FQDN spelling that resolves to the same host, "
            "so it must not fall out of the hostname deny set",
        )

    def test_trailing_dot_plus_uppercase_bypasses_the_hostname_denylist(self):
        """W1: case folding alone is not enough - 'REDDIT.COM.' must be denied too."""
        cli = self.make_client(hostnames=["reddit.com"])
        self.assertTrue(
            cli.is_blocked("https://REDDIT.COM./x"),
            "host normalization must lowercase AND strip the trailing dot, not just lowercase",
        )

    def test_trailing_dot_host_bypasses_the_suffix_denylist(self):
        """W1: 'site.ru.'.endswith('.ru') is False, so the suffix half falls open."""
        cli = self.make_client(suffixes=[".ru"])
        self.assertTrue(cli.is_blocked("https://site.ru/x"), "control: the dotless form must stay blocked")
        self.assertTrue(
            cli.is_blocked("https://site.ru./x"),
            "the suffix matcher runs on the raw host, so a trailing root dot defeats every suffix row",
        )

    def test_repeated_trailing_dots_bypass_the_denylist(self):
        """W1: normalization must strip every trailing dot, not just one."""
        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        self.assertTrue(cli.is_blocked("https://reddit.com../x"), "'reddit.com..' must normalize to 'reddit.com'")
        self.assertTrue(cli.is_blocked("https://site.ru../x"), "'site.ru..' must normalize to 'site.ru'")

    def test_denylist_entry_with_a_trailing_dot_still_denies_the_plain_host(self):
        """W1: entries are unnormalized too, so an FQDN-spelled deny row matches nothing."""
        cli = self.make_client(hostnames=["Evil.Example."])
        self.assertTrue(
            cli.is_blocked("https://evil.example/x"),
            "a blocklist row authored as an FQDN must still deny the plain host - "
            "normalization has to run on BOTH sides of the comparison",
        )
        self.assertTrue(cli.is_blocked("https://evil.example./x"), "and on the FQDN-spelled URL")


class TestExistingDenyBehaviourDoesNotRegress(_ClientTestBase):
    """Behaviour that is already correct today and must survive the fix."""

    def test_plain_denied_host_is_still_denied(self):
        """Non-regression: the ordinary exact-hostname match must keep working."""
        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        self.assertTrue(cli.is_blocked("https://reddit.com/r/leagueoflegends"))
        self.assertTrue(cli.is_blocked("http://reddit.com/r/x"))
        self.assertTrue(cli.is_blocked("https://anything.ru/x"))

    def test_hostname_match_is_still_case_insensitive(self):
        """Non-regression: DNS is case-insensitive and the matcher already honoured that."""
        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        self.assertTrue(cli.is_blocked("https://ReDdIt.CoM/x"))
        self.assertTrue(cli.is_blocked("https://Site.RU/x"))

    def test_ordinary_allowed_https_url_is_still_permitted(self):
        """Non-regression: the fix must not turn the gate into a deny-everything."""
        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        self.assertFalse(cli.is_blocked("https://ddragon.leagueoflegends.com/api/versions.json"))
        self.assertFalse(cli.is_blocked("http://127.0.0.1:8888/api/state"))

    def test_url_with_no_hostname_is_still_denied(self):
        """Non-regression: a URL the parser cannot pin to a host must fail closed."""
        cli = self.make_client(hostnames=["reddit.com"])
        self.assertTrue(cli.is_blocked(""))
        self.assertTrue(cli.is_blocked("/relative/path"))
        self.assertTrue(cli.is_blocked("://example.com/x"))


class TestSchemeAllowlist(_ClientTestBase):
    """W2 - only http and https may leave this client."""

    def test_allowed_schemes_constant_exists_and_is_http_only(self):
        """W2: the policy needs one named constant, not a literal buried in a branch."""
        schemes = getattr(http_client, "ALLOWED_SCHEMES", None)
        self.assertIsNotNone(schemes, "lib.http.client must define a module-level ALLOWED_SCHEMES")
        self.assertEqual(tuple(schemes), ("http", "https"), "only http and https may be fetched")

    def test_file_url_with_a_host_is_denied(self):
        """W2: 'file://localhost/...' keeps a hostname, so only a scheme gate stops it."""
        cli = self.make_client(hostnames=["reddit.com"])
        self.assertTrue(
            cli.is_blocked("file://localhost/etc/passwd"),
            "the default urllib opener contains FileHandler, so an unchecked file:// URL "
            "is a local filesystem read through the HTTP client",
        )
        self.assertTrue(cli.is_blocked("file://localhost/C:/Windows/win.ini"))

    def test_non_http_schemes_with_a_resolvable_host_are_denied(self):
        """W2: ftp, gopher and a scheme-less '//host/path' all pass the host check today."""
        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        for url in (
            "ftp://example.com/x",
            "gopher://example.com/x",
            "//example.com/x",
            "ws://example.com/x",
        ):
            with self.subTest(url=url):
                self.assertTrue(cli.is_blocked(url), "scheme is not in ALLOWED_SCHEMES")

    def test_hostless_non_http_schemes_stay_denied(self):
        """W2 non-regression: these are denied today only by the empty-host rule.

        A scheme allowlist must not accidentally make them reachable.
        """
        cli = self.make_client(hostnames=["reddit.com"])
        for url in ("file:///etc/passwd", "file:///C:/Windows/win.ini", "data:text/plain,hello"):
            with self.subTest(url=url):
                self.assertTrue(cli.is_blocked(url))

    def test_request_refuses_the_file_scheme_before_urlopen_is_reached(self):
        """W2: request() must raise Blocked without letting file:// touch the opener."""
        cli = self.make_client()
        spy = _UrlopenSpy()
        with mock.patch("urllib.request.urlopen", spy):
            outcome = self.attempt(cli, "GET", "file://localhost/etc/passwd")
        self.assertEqual(outcome, "Blocked", f"urlopen saw {spy.calls!r}")
        self.assertEqual(spy.calls, [], "a file:// URL must never reach the urllib opener")

    def test_request_refuses_the_ftp_scheme_before_urlopen_is_reached(self):
        """W2: the same gate must cover every non-http scheme, not just file://."""
        cli = self.make_client()
        spy = _UrlopenSpy()
        with mock.patch("urllib.request.urlopen", spy):
            outcome = self.attempt(cli, "GET", "ftp://example.com/x")
        self.assertEqual(outcome, "Blocked", f"urlopen saw {spy.calls!r}")
        self.assertEqual(spy.calls, [], "an ftp:// URL must never reach the urllib opener")

    def test_request_on_a_file_url_must_not_read_a_local_file(self):
        """W2, end to end: today the bytes of a real local file are read into the response.

        No mock here on purpose - this drives the genuine urllib FileHandler
        against a file in this test's own temp dir, so it proves the vector
        rather than asserting about it. Measured pre-fix on win32: request()
        reads the file and then dies at resp.getheaders() with AttributeError,
        which means the disclosure already happened.
        """
        secret = Path(self.tmpdir) / "local-secret.txt"
        secret.write_text("LANE8-CYCLE27-LOCAL-FILE-CONTENT", encoding="utf-8")
        url = secret.as_uri().replace("file:///", "file://localhost/", 1)
        self.assertTrue(url.startswith("file://localhost/"), "sanity: built a hosted file URL")
        cli = self.make_client()
        outcome = self.attempt(cli, "GET", url, timeout=5.0)
        self.assertEqual(
            outcome,
            "Blocked",
            f"request() must reject file:// with Blocked before urllib opens the path; got {outcome}",
        )


class TestRedirectContainment(_ClientTestBase):
    """W3 - the deny gate must be re-applied to every redirect target."""

    def test_redirect_into_a_denied_host_raises_blocked_and_never_connects(self):
        """W3: an allowed host 302s into a denied host and the client fetches it today.

        Two loopback servers. The denied one is addressed as "localhost" purely
        so its hostname STRING differs from the allowed "127.0.0.1"; both are
        the same loopback interface, which is what lets this assert that the
        denied server was never contacted. After the fix that name is never
        resolved, so the test stays offline on every platform.
        """
        denied = _LoopbackServer({"/denied": ("body", "SHOULD-NEVER-BE-FETCHED")})
        self.addCleanup(denied.close)
        denied_url = f"http://localhost:{denied.port}/denied"
        front = _LoopbackServer({"/start": ("redirect", denied_url)})
        self.addCleanup(front.close)

        cli = self.make_client(hostnames=["localhost"])
        start_url = f"http://127.0.0.1:{front.port}/start"
        self.assertFalse(cli.is_blocked(start_url), "precondition: the entry URL is allowed")
        self.assertTrue(cli.is_blocked(denied_url), "precondition: the redirect target is denied")

        outcome = self.attempt(cli, "GET", start_url)
        self.assertEqual(
            outcome,
            "Blocked",
            f"a 302 into a denied host must raise Blocked; denied server saw {denied.hits!r}",
        )
        self.assertEqual(
            denied.hits,
            [],
            "Blocked must be raised BEFORE the connection to the denied host, not after fetching it",
        )

    def test_redirect_into_an_allowed_url_still_succeeds(self):
        """W3 non-regression: containment must not stop following legitimate redirects."""
        routes = {"/final": ("body", "FINAL-BODY")}
        front = _LoopbackServer(routes)
        self.addCleanup(front.close)
        routes["/start"] = ("redirect", f"http://127.0.0.1:{front.port}/final")

        cli = self.make_client(hostnames=["reddit.com"], suffixes=[".ru"])
        resp = cli.get(f"http://127.0.0.1:{front.port}/start", timeout=10.0)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"FINAL-BODY")
        self.assertTrue(resp.url.endswith("/final"), f"final URL was {resp.url!r}")
        self.assertEqual(front.hits, ["/start", "/final"], "both hops must actually happen")


if __name__ == "__main__":
    unittest.main()
