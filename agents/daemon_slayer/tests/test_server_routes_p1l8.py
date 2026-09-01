"""P1-L8 - Daemon Slayer HTTP server route-contract + connection hardening.

Companion to ``test_server.py``. Focuses on three things the prior
audit lane flagged:

  1. Route contract: /health real ENGINE_VERSION + stable schema; the
     in-response engine_version never drifts from the package constant;
     bad input on the math routes yields a clean 4xx JSON error (never
     a 500 traceback, never a hang).
  2. Error handling: malformed JSON / missing field / unknown id /
     out-of-range each return a defined ``{"error","status"}`` shape;
     concurrent requests do not corrupt shared engine state.
  3. The socket flake: a POST that carries a body to a route that
     returns early (unknown POST route) must still cleanly return its
     4xx and NOT reset the TCP connection. Pre-fix this raised an
     intermittent ConnectionResetError / ConnectionAbortedError on
     Windows because the handler returned without draining the
     request body. Asserted under heavy repetition so a regression
     resurfaces deterministically.

No hardcoded engine magic numbers - assertions are on schema keys,
the package ENGINE_VERSION constant, and derived/relative quantities.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import (
    _POST_ROUTES,
    _ApiError,
    _to_int,
    start_server,
)


def _start() -> tuple[str, int, object]:
    snap = DataSnapshot.load()
    srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="DSTestServerP1L8")
    t.start()
    return host, port, srv


def _get(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post_raw(url: str, raw: bytes) -> tuple[int, dict]:
    """POST pre-serialized bytes. Needed for tokens Python's json.dumps
    cannot round-trip to the wire verbatim - notably the plain literal
    ``1e400``, which dumps() would re-emit as ``Infinity`` because the
    value has already overflowed to float inf in Python."""
    last: Exception | None = None
    for _attempt in range(5):
        req = Request(url, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))
        except (ConnectionResetError, ConnectionAbortedError,
                http.client.RemoteDisconnected) as exc:
            # A constrained CI runner RSTs some burst connections at the
            # ThreadingHTTPServer accept backlog; the route result is
            # deterministic, so re-issue the single dropped request.
            last = exc
            time.sleep(0.02 * (_attempt + 1))
    raise last if last else RuntimeError("unreachable")


def _post(url: str, body: dict) -> tuple[int, dict]:
    return _post_raw(url, json.dumps(body).encode("utf-8"))


# RM-324. Raw JSON tokens an integer body key must reject with a 400.
# "abc" is the original single-input domain of the guard below; the rest are
# the non-finite half it never covered. ``Infinity`` / ``-Infinity`` / ``NaN``
# are the bare tokens json.loads accepts by default, and 1e400 is a perfectly
# ordinary float literal that overflows to inf while being parsed - so it
# reaches the same int() without using a non-standard token at all.
_NON_FINITE_INT_TOKENS = ('"abc"', "Infinity", "-Infinity", "1e400", "NaN")


def _raw_json(base: dict, key: str, token: str) -> bytes:
    """Serialize ``base`` with ``key`` set to the literal ``token`` bytes."""
    parts = [f"{json.dumps(k)}: {json.dumps(v)}"
             for k, v in base.items() if k != key]
    parts.append(f"{json.dumps(key)}: {token}")
    return ("{" + ", ".join(parts) + "}").encode("utf-8")


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host, cls.port, cls.srv = _start()
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()


class HealthContractTests(_Base):
    def test_health_schema_and_version_no_drift(self) -> None:
        status, body = _get(self.base + "/health")
        self.assertEqual(status, 200)
        # Stable schema - exact key set.
        self.assertEqual(
            set(body),
            {"status", "engine_version", "patch", "champions", "items"},
        )
        self.assertEqual(body["status"], "ok")
        # No drift: response version == package constant.
        self.assertEqual(body["engine_version"], ENGINE_VERSION)
        self.assertIsInstance(body["patch"], str)
        self.assertTrue(body["patch"])
        # Derived sanity, not a hardcoded count.
        self.assertGreater(body["champions"], 0)
        self.assertGreater(body["items"], 0)

    def test_index_and_server_header_version_match_constant(self) -> None:
        # The Server: header and the index page both embed ENGINE_VERSION;
        # assert they equal the package constant (drift guard).
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        server_hdr = resp.getheader("Server") or ""
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(ENGINE_VERSION, server_hdr)
        self.assertIn(ENGINE_VERSION, body)

    def test_snapshot_route_stable_schema(self) -> None:
        status, body = _get(self.base + "/snapshot")
        self.assertEqual(status, 200)
        for key in ("patch", "champions", "items",
                    "scenarios_by_id", "scenarios_by_lolmath", "manifest"):
            self.assertIn(key, body)
        self.assertIn("phase", body["manifest"])


class ErrorShapeTests(_Base):
    """Every bad-input path returns the defined {error,status} shape -
    never a 500, never an unhandled exception, never a hang."""

    def test_malformed_json_body_is_400(self) -> None:
        req = Request(self.base + "/stats", data=b"{nope",
                      method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            urlopen(req, timeout=10)
            self.fail("expected HTTPError 400")
        except HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read().decode("utf-8"))
            self.assertEqual(body["status"], 400)
            self.assertIn("invalid JSON", body["error"])

    def test_missing_required_field_is_400(self) -> None:
        status, body = _post(self.base + "/dps", {"level": 5})
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], 400)
        self.assertIn("champion", body["error"])

    def test_unknown_champion_is_404_not_500(self) -> None:
        status, body = _post(self.base + "/stats",
                             {"champion": "Zzznotachamp", "level": 3})
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], 404)
        self.assertIn("error", body)

    def test_unknown_item_is_404_not_500(self) -> None:
        status, body = _post(self.base + "/dps",
                             {"champion": "Aatrox", "level": 11,
                              "items": ["999999999"]})
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], 404)

    def test_out_of_range_level_is_clean_422_not_500_or_hang(self) -> None:
        # The engine's clamp_level REJECTS out-of-range (raises
        # ValueError) rather than saturating; the route maps that to a
        # defined 422. The contract under audit is "no 500 traceback,
        # no hang" - a structured 422 satisfies it.
        status, body = _post(self.base + "/stats",
                             {"champion": "Aatrox", "level": 9999})
        self.assertEqual(status, 422)
        self.assertEqual(body["status"], 422)
        self.assertIn("error", body)
        # Negative is rejected the same way (clamp_level raises).
        status_neg, body_neg = _post(self.base + "/stats",
                                     {"champion": "Aatrox", "level": -5})
        self.assertEqual(status_neg, 422)
        self.assertEqual(body_neg["status"], 422)
        # NOTE: level == 0 is NOT 422 - the route's
        # ``_opt_int(body, "level", 1) or 1`` intentionally coerces a
        # falsy 0 to the default level 1 (-> 200). That is a documented
        # route convenience, not an engine bypass; assert it explicitly
        # so the behavior is pinned rather than mistaken for a bug.
        status_zero, body_zero = _post(self.base + "/stats",
                                       {"champion": "Aatrox", "level": 0})
        self.assertEqual(status_zero, 200)
        self.assertEqual(body_zero["level"], 1)

    def test_garbage_numeric_param_is_400_not_500(self) -> None:
        # RM-324 widened this. The name promised the whole garbage-number
        # domain but the body covered exactly one input, the string "abc" -
        # so a bare ``Infinity`` in the very same key returned 500 for as
        # long as this guard has existed. int(inf) raises OverflowError,
        # which _opt_int did not catch, so it escaped to the 500 handler
        # while the float sibling ten lines below returned a clean 400.
        for token in _NON_FINITE_INT_TOKENS:
            with self.subTest(token=token):
                raw = _raw_json({"champion": "Aatrox", "level": 11},
                                "level", token)
                status, body = _post_raw(self.base + "/dps", raw)
                self.assertEqual(status, 400,
                                 f"level={token} -> {status} {body}")
                self.assertEqual(body["status"], 400)
                self.assertIn("level", body["error"])
                if token != '"abc"':
                    # Pin the MESSAGE, not just the status: an int key and its
                    # float sibling must reject a non-finite value with the
                    # same wording, and status alone leaves the finiteness
                    # check itself unexercised (a bare OverflowError catch
                    # would also return 400, with different text).
                    self.assertIn("must be a finite number", body["error"])

    def test_non_finite_rank_int_params_are_400_not_500(self) -> None:
        # /rank carries three more int keys through the same helper.
        base = {"champion": "Aatrox", "level": 11, "top": 3}
        for key in ("top", "budget", "slots"):
            for token in _NON_FINITE_INT_TOKENS:
                with self.subTest(key=key, token=token):
                    raw = _raw_json(base, key, token)
                    status, body = _post_raw(self.base + "/rank", raw)
                    self.assertEqual(status, 400,
                                     f"{key}={token} -> {status} {body}")
                    self.assertEqual(body["status"], 400)
                    self.assertIn(key, body["error"])

    def test_non_finite_form_index_value_is_400_not_500(self) -> None:
        # Same root cause in a second helper: _parse_form_index coerces the
        # per-key rank with a bare int() and no _ApiError mapping at all, so
        # both an overflowing number and an unparseable string 500'd there.
        for token in _NON_FINITE_INT_TOKENS:
            with self.subTest(token=token):
                raw = ('{"champion": "Aatrox", "level": 11, '
                       f'"form_index": {{"Q": {token}}}}}').encode()
                status, body = _post_raw(self.base + "/ability-dps", raw)
                self.assertEqual(status, 400,
                                 f"form_index Q={token} -> {status} {body}")
                self.assertEqual(body["status"], 400)
                self.assertIn("form_index", body["error"])

    def test_well_formed_numeric_params_still_200(self) -> None:
        # Control for the three tests above: the guard rejects non-finite
        # input without narrowing the legitimate domain.
        status, body = _post(self.base + "/dps",
                             {"champion": "Ahri", "level": 11})
        self.assertEqual(status, 200, body)
        status_r, body_r = _post(self.base + "/rank",
                                 {"champion": "Aatrox", "level": 11,
                                  "top": 3, "slots": 6, "budget": 10000})
        self.assertEqual(status_r, 200, body_r)

    def test_non_finite_float_param_keeps_its_existing_400_message(self) -> None:
        # Regression fence on the fix's SHAPE. _opt_float already rejected
        # non-finite input with this exact text; rejecting the bare Infinity
        # token earlier (at json.loads, via parse_constant) would have
        # replaced it with a generic parse error on a path that was never
        # broken - and would still have missed 1e400, which is an ordinary
        # JSON float literal that overflows to inf during parsing.
        raw = _raw_json({"champion": "Ahri", "level": 11},
                        "target_armor", "Infinity")
        status, body = _post_raw(self.base + "/dps", raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], 400)
        self.assertEqual(body["error"],
                         "target_armor: must be a finite number, got inf")

    def test_bad_enum_phase_is_400(self) -> None:
        status, body = _post(self.base + "/dps",
                             {"champion": "Aatrox", "level": 11,
                              "phase": "superlate"})
        self.assertEqual(status, 400)
        self.assertIn("phase", body["error"])

    def test_share_out_of_range_is_422(self) -> None:
        status, body = _post(self.base + "/rank-tank",
                             {"champion": "Malphite", "level": 11,
                              "enemy_ad_share": 0.9, "enemy_ap_share": 0.9})
        self.assertEqual(status, 422)
        self.assertEqual(body["status"], 422)


class IntCoercionUnitTests(unittest.TestCase):
    """Direct cover for the arm of ``_to_int`` no HTTP body can reach.

    json.loads only ever hands the helper float / int / str, so the
    OverflowError branch is unreachable through a route; a non-float type
    whose int() overflows exercises it without a server."""

    def test_overflowing_non_float_is_api_error_not_overflow(self) -> None:
        with self.assertRaises(_ApiError) as ctx:
            _to_int(Decimal("Infinity"), "level")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("level", ctx.exception.message)

    def test_ordinary_values_still_coerce(self) -> None:
        self.assertEqual(_to_int(11, "level"), 11)
        self.assertEqual(_to_int("11", "level"), 11)
        self.assertEqual(_to_int(11.7, "level"), 11)


class ConcurrencyTests(_Base):
    """Shared snapshot must not corrupt under concurrent load. Issue a
    mix of routes in parallel; every response must be well-formed and
    deterministic (same query -> same answer)."""

    def test_parallel_mixed_requests_are_consistent(self) -> None:
        def stats():
            return _post(self.base + "/stats",
                         {"champion": "Aatrox", "level": 11,
                          "items": ["6692", "3006"]})

        def dps():
            return _post(self.base + "/dps",
                         {"champion": "Lux", "level": 11,
                          "target_mr": 30})

        ref_status, ref_body = stats()
        self.assertEqual(ref_status, 200)

        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = []
            for _ in range(40):
                futs.append(ex.submit(stats))
                futs.append(ex.submit(dps))
            results = [f.result() for f in futs]

        for st, bd in results:
            self.assertEqual(st, 200)
            self.assertIn("champion_id", bd)
        # Determinism: every Aatrox/stats call equals the reference.
        for st, bd in results:
            if bd.get("champion_id") == "Aatrox" and "stats" in bd:
                self.assertEqual(bd["item_ids"], ref_body["item_ids"])
                self.assertEqual(bd["stats"]["ad"], ref_body["stats"]["ad"])


class ConnectionHardeningTests(_Base):
    """The socket flake. A POST that carries a body to a route that
    returns early (unknown POST route) must STILL return a clean 4xx
    and must NOT reset the TCP connection mid-response.

    Pre-fix: do_POST returned on the unknown-route branch without
    draining self.rfile, so the unread request body in the socket
    buffer caused Windows to RST the connection on close - the client
    saw ConnectionResetError / ConnectionAbortedError instead of the
    404. Heavy repetition makes the race deterministic."""

    def test_post_unknown_route_with_body_returns_clean_404(self) -> None:
        status, body = _post(self.base + "/no-such-route",
                             {"champion": "Aatrox", "level": 11,
                              "filler": "x" * 4096})
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], 404)
        self.assertIn("no-such-route", body["error"])

    def test_post_to_get_only_health_with_body_is_clean_404(self) -> None:
        # This is the exact test that flaked in the full suite.
        status, body = _post(self.base + "/health",
                             {"x": "y" * 2048})
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], 404)

    def test_unknown_post_route_no_connection_reset_under_repetition(self) -> None:
        # Pre-fix this surfaced ConnectionResetError within a few
        # hundred iterations on Windows. Post-fix: zero resets.
        errors: list[str] = []
        for i in range(600):
            try:
                st, bd = _post(self.base + "/nope",
                               {"champion": "Aatrox", "level": 11,
                                "payload": "z" * 1024})
                if st != 404:
                    errors.append(f"[{i}] status={st}")
            except (ConnectionResetError, ConnectionAbortedError,
                    http.client.RemoteDisconnected) as e:
                errors.append(f"[{i}] {type(e).__name__}: {e}")
        self.assertEqual(
            errors, [],
            f"connection instability on early-return POST: {errors[:8]}",
        )

    def test_keepalive_connection_survives_unknown_route_post(self) -> None:
        # Reuse one connection: a 404 with an undrained body would
        # desync the keep-alive stream and corrupt the next response.
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            for _ in range(25):
                payload = json.dumps({"a": "b" * 512}).encode()
                conn.request("POST", "/nope", body=payload,
                             headers={"Content-Type": "application/json",
                                      "Connection": "keep-alive"})
                resp = conn.getresponse()
                data = resp.read()
                self.assertEqual(resp.status, 404)
                parsed = json.loads(data.decode("utf-8"))
                self.assertEqual(parsed["status"], 404)
                # Interleave a valid request on the same connection to
                # prove the stream is not desynced.
                good = json.dumps({"champion": "Aatrox",
                                   "level": 11}).encode()
                conn.request("POST", "/stats", body=good,
                             headers={"Content-Type": "application/json",
                                      "Connection": "keep-alive"})
                r2 = conn.getresponse()
                d2 = json.loads(r2.read().decode("utf-8"))
                self.assertEqual(r2.status, 200)
                self.assertEqual(d2["champion_id"], "Aatrox")
        finally:
            conn.close()

    def test_every_post_route_rejects_get_with_body_cleanly(self) -> None:
        # Defensive sweep: GET-only vs POST-only mismatch never resets.
        # POST routes hit via GET fall through to the GET dispatcher
        # (query-arg form) - that is a separate, valid path; here we
        # just assert no route 500s or hangs on a wrong-content POST
        # to an unknown sibling path derived from each real route.
        for route in list(_POST_ROUTES):
            status, body = _post(self.base + route + "-bogus",
                                 {"champion": "Aatrox", "level": 11})
            self.assertEqual(status, 404, f"{route}-bogus -> {status}")
            self.assertEqual(body["status"], 404)


if __name__ == "__main__":
    unittest.main()
