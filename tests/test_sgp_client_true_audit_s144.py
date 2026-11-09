"""s144 true-audit (S144-T-586): core/sgp_client.py hardening.

The service-gateway client sends a session Bearer token to a Riot host and
parses a body RC did not author. Each class below pins one measured defect:

- the default transport FOLLOWED a 30x and urllib's redirect handler copies
  every request header except Content-Length / Content-Type onto the new
  request, so the Bearer token went to whatever host (and scheme, http
  included) the Location header named;
- an HTTPError (every non-2xx) was returned without being closed, leaking
  the response socket per refused page;
- the PUUID was interpolated raw into the URL path, so "a/../x?y=1#" rewrote
  the path and query, and a space or control character made urllib raise
  InvalidURL out of a method documented "never raises";
- a token carrying CR / LF (or None) was sent as a header ("Bearer None"), or
  raised ValueError out of http.client; _extract_token accepted it, so the
  next token candidate was never tried;
- start / count accepted bool, negative and non-int values (int("x") raised);
- http.client.HTTPException (IncompleteRead) and ValueError escaped the
  transport, and a deeply nested body raised RecursionError out of the parse;
- a non-dict entry in "games" was handed to callers typed list[dict].

Everything is offline: a fake transport, a fake opener, or a loopback
http.server this file starts and stops.
"""
from __future__ import annotations

import http.client
import http.server
import io
import json
import logging
import threading
import urllib.error

import pytest

from core import sgp_client

_PUUID = "p" * 20 + "-_AZaz09"
_TOKEN = "eyJhbGciOi.payload-part_x.sig+/="


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _body(games):
    return json.dumps({"games": games}).encode()


@pytest.fixture(autouse=True)
def _sgp_on(monkeypatch):
    monkeypatch.setenv("RC_SGP", "1")


# ---------------------------------------------------------------- redirects


class _Server:
    """Loopback server: /start answers 302 to /landing; /landing records the
    Authorization header it was sent; /forbidden answers 403."""

    def __init__(self):
        self.landing_auth = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib name
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header(
                        "Location", f"http://127.0.0.1:{outer.port}/landing")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/landing":
                    outer.landing_auth.append(self.headers.get("Authorization"))
                    body = _body([{"i": 1}])
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(403)
                self.send_header("Content-Length", "4")
                self.end_headers()
                self.wfile.write(b"nope")

            def log_message(self, *_a):
                return

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, name="sgp-test-server", daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def server(monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    srv = _Server()
    try:
        yield srv
    finally:
        srv.close()


class TestRedirectNeverCarriesTheToken:
    def test_302_is_reported_not_followed(self, server):
        status, body = sgp_client._urllib_transport(
            f"http://127.0.0.1:{server.port}/start",
            {"Authorization": "Bearer SECRET-TOKEN"},
        )
        assert status == 302
        assert body == b""
        assert server.landing_auth == []

    def test_plain_403_still_reports_its_code(self, server):
        assert sgp_client._urllib_transport(
            f"http://127.0.0.1:{server.port}/forbidden", {}) == (403, b"")


class TestHttpErrorIsClosed:
    def test_http_error_response_is_closed(self, monkeypatch):
        # The exception is kept referenced (as a traceback cycle, a log
        # record's exc_info or a debugger would), so only an explicit close
        # releases the response; refcount collection cannot hide a missing one.
        fp = io.BytesIO(b"denied")
        raised = []

        def boom(_request, timeout=None):
            exc = urllib.error.HTTPError("https://h/x", 403, "Forbidden", {}, fp)
            raised.append(exc)
            raise exc

        monkeypatch.setattr(sgp_client, "_open", boom)
        assert sgp_client._urllib_transport("https://h/x", {}) == (403, b"")
        assert raised
        assert fp.closed


class TestTransportFaultsNeverEscape:
    @pytest.mark.parametrize(
        "exc",
        [
            http.client.IncompleteRead(b"part"),
            http.client.InvalidURL("bad url"),
            ValueError("Invalid header value"),
        ],
        ids=["incomplete-read", "invalid-url", "value-error"],
    )
    def test_default_transport_maps_fault_to_zero(self, monkeypatch, exc):
        def boom(_request, timeout=None):
            raise exc

        monkeypatch.setattr(sgp_client, "_open", boom)
        assert sgp_client._urllib_transport("https://h/x", {}) == (0, b"")

    @pytest.mark.parametrize(
        "exc",
        [OSError("down"), ValueError("bad"), http.client.IncompleteRead(b"")],
        ids=["oserror", "valueerror", "incomplete-read"],
    )
    def test_injected_transport_fault_returns_empty(self, exc):
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=_Transport([exc]))
        assert client.match_history(_PUUID) == []

    @pytest.mark.parametrize(
        "reply", [None, (200,), (200, "text"), ("200", b"{}"), (True, b"{}")])
    def test_malformed_transport_reply_returns_empty(self, reply):
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=_Transport([reply]))
        assert client.match_history(_PUUID) == []


# ---------------------------------------------------------------- puuid


class TestPuuidIsAPathSegment:
    @pytest.mark.parametrize(
        "puuid",
        ["a/../../x?y=1#", "has space", "line\nbreak", "", "x" * 200,
         None, 123, b"bytes"],
        ids=["traversal", "space", "newline", "empty", "too-long", "none",
             "int", "bytes"],
    )
    def test_bad_puuid_is_refused_before_any_request(self, puuid):
        transport = _Transport([(200, _body([{"i": 1}]))])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        assert client.match_history(puuid) == []
        assert list(client.iter_match_history(puuid)) == []
        assert transport.calls == []

    def test_real_shape_puuid_is_sent_verbatim(self):
        transport = _Transport([(200, _body([{"i": 1}]))])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        assert client.match_history(_PUUID) == [{"i": 1}]
        url = transport.calls[0][0]
        assert f"/player/{_PUUID}/SUMMARY?" in url

    def test_url_builder_quotes_the_puuid(self):
        url = sgp_client.match_history_url("https://h", "a/../x?y#", 0, 20)
        assert url == (
            "https://h/match-history-query/v1/products/lol/player/"
            "a%2F..%2Fx%3Fy%23/SUMMARY?startIndex=0&count=20"
        )


class TestPagingArguments:
    @pytest.mark.parametrize(
        ("start", "count"),
        [(-1, 20), (0, 0), (0, -5), (True, 20), (0, True), ("x", 20),
         (0, "20"), (0.5, 20), (None, 20)],
    )
    def test_bad_start_or_count_is_refused(self, start, count):
        transport = _Transport([(200, _body([{"i": 1}]))])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        assert client.match_history(_PUUID, start=start, count=count) == []
        assert transport.calls == []

    @pytest.mark.parametrize(
        ("page_size", "max_games"),
        [(0, 10), (-3, 10), (True, 10), (5, True), (5, "10"), ("5", 10)],
    )
    def test_bad_iter_arguments_make_no_request(self, page_size, max_games):
        transport = _Transport([(200, _body([{"i": 1}]))] * 3)
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        assert list(client.iter_match_history(
            _PUUID, page_size=page_size, max_games=max_games)) == []
        assert transport.calls == []

    def test_url_builder_rejects_bool_and_negative(self):
        for start, count in ((True, 1), (0, False), (-1, 1), (0, -1)):
            with pytest.raises(ValueError):
                sgp_client.match_history_url("https://h", _PUUID, start, count)


# ---------------------------------------------------------------- token


class TestTokenShape:
    @pytest.mark.parametrize(
        "token",
        ["TK\r\nX-Evil: 1", "has space", "", None, 5, "\x00abc"],
        ids=["crlf", "space", "empty", "none", "int", "nul"],
    )
    def test_unusable_token_sends_nothing(self, token):
        transport = _Transport([(200, _body([{"i": 1}]))])
        client = sgp_client.SgpClient("NA1", token, transport=transport)
        assert client.match_history(_PUUID) == []
        assert transport.calls == []

    def test_crlf_candidate_falls_through_to_the_next_endpoint(self):
        answers = {
            sgp_client.TOKEN_ENDPOINTS[0]: {"accessToken": "abc\r\nX-Evil: 1"},
            sgp_client.TOKEN_ENDPOINTS[1]: {"accessToken": _TOKEN},
        }
        token, source = sgp_client.acquire_token(lambda e: answers.get(e))
        assert token == _TOKEN
        assert source == sgp_client.TOKEN_ENDPOINTS[1]

    def test_token_never_reaches_a_log_or_repr(self, caplog):
        caplog.set_level(logging.DEBUG, logger="core.sgp_client")
        transport = _Transport([
            (403, b""), OSError("down"), (200, b"not json"), (500, b"x")])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        for _ in range(4):
            client.match_history(_PUUID)
        assert _TOKEN not in caplog.text
        assert _TOKEN not in repr(client)


# ---------------------------------------------------------------- body


class TestBodyParse:
    def test_deeply_nested_body_returns_empty(self):
        body = b'{"games": ' + b"[" * 200000 + b"]" * 200000 + b"}"
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=_Transport([(200, body)]))
        assert client.match_history(_PUUID) == []

    def test_non_dict_games_are_dropped(self):
        body = _body([{"i": 0}, 5, "x", None, [1], {"i": 1}])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=_Transport([(200, body)]))
        assert client.match_history(_PUUID) == [{"i": 0}, {"i": 1}]

    def test_paging_counts_the_raw_page_not_the_kept_rows(self):
        full = _body([{"i": 0}, 5, {"i": 2}])
        short = _body([{"i": 9}])
        transport = _Transport([(200, full), (200, short)])
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        got = list(client.iter_match_history(_PUUID, page_size=3, max_games=100))
        assert got == [{"i": 0}, {"i": 2}, {"i": 9}]
        assert len(transport.calls) == 2
        assert "startIndex=3&count=3" in transport.calls[1][0]

    def test_full_pages_of_dropped_entries_stay_bounded(self):
        junk = _body([1, 2, 3])
        transport = _Transport([(200, junk)] * 50)
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        got = list(client.iter_match_history(_PUUID, page_size=3, max_games=9))
        assert got == []
        assert len(transport.calls) == 3

    def test_oversized_page_still_stops_at_max_games(self):
        big = _body([{"i": n} for n in range(10)])
        transport = _Transport([(200, big)] * 5)
        client = sgp_client.SgpClient("NA1", _TOKEN, transport=transport)
        got = list(client.iter_match_history(_PUUID, page_size=3, max_games=5))
        assert got == [{"i": n} for n in range(5)]
        assert len(transport.calls) == 1
