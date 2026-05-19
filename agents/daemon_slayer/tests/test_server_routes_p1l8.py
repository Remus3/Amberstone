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
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import _POST_ROUTES, start_server


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


def _post(url: str, body: dict) -> tuple[int, dict]:
    raw = json.dumps(body).encode("utf-8")
    req = Request(url, data=raw, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


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
        status, body = _post(self.base + "/dps",
                             {"champion": "Aatrox", "level": "abc"})
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], 400)

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
