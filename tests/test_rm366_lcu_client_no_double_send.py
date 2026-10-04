"""RM-366 - a pooled LCU write that faults AFTER its bytes are on the wire must
be transmitted exactly ONCE end to end, across BOTH the pool and the caller's
legacy urlopen fallback.

RM-345 stopped the pool replaying a POST/PATCH, but returned the same None
for "gave up after sending" as for "pool unavailable", and
lcu/lcu_client.py `_request` treated that None as "fall through to urlopen",
re-sending the identical method and body (3 sends down to 2, not 1). The
give-up is now distinguishable (core.lcu_pool.SENT_UNCONFIRMED), while a
request that faulted BEFORE it was fully written still falls through.

Drives the real LcuClient._request against the real HttpsConnectionPool with
a fake connection factory (the RM-345 test's fake shape) and a counting
urlopen stub, so every transmission on either path is counted.
"""
from __future__ import annotations

import http.client
import io
import unittest
from unittest import mock

from core import lcu_pool
from lcu import lcu_client


class _Resp:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _Conn:
    def __init__(self, sent, mode):
        self.sent = sent
        self.mode = mode

    def request(self, method, path, body=None, headers=None):
        if self.mode == "refuse":
            raise ConnectionRefusedError("nothing listening")
        self.sent.append(("pool", method, path, body))

    def getresponse(self):
        if self.mode == "drop":
            raise http.client.RemoteDisconnected("peer closed")
        return _Resp()

    def close(self):
        pass


class _UrlopenResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _drive(method, mode):
    sent = []
    pool = lcu_pool.HttpsConnectionPool(
        connection_factory=lambda h, p: _Conn(sent, mode))

    def _urlopen(req, context=None, timeout=None):
        sent.append(("urlopen", req.get_method(), req.full_url, req.data))
        return _UrlopenResp(b'{"via": "urlopen"}')

    client = lcu_client.LcuClient()
    client._port = 54321
    client._auth = "cmlvdDpwdw=="
    with mock.patch.dict("os.environ", {"RC_LCU_POOL": "1"}), \
            mock.patch.object(lcu_pool, "get_shared_pool", return_value=pool), \
            mock.patch.object(lcu_client.urllib.request, "urlopen", side_effect=_urlopen), \
            mock.patch.object(client, "_refresh_conn_if_changed"):
        out = client._request(method, "/lol-matchmaking/v1/ready-check/accept",
                              data={"x": 1})
    return out, sent


class EndToEndExactlyOnceTests(unittest.TestCase):
    def test_post_faulting_in_getresponse_is_sent_once_total(self):
        out, sent = _drive("POST", "drop")
        self.assertIsNone(out)
        self.assertEqual(1, len(sent), f"transmissions: {sent}")
        self.assertEqual("pool", sent[0][0])

    def test_patch_faulting_in_getresponse_is_sent_once_total(self):
        out, sent = _drive("PATCH", "drop")
        self.assertIsNone(out)
        self.assertEqual(1, len(sent), f"transmissions: {sent}")

    def test_unsent_post_still_falls_through_to_urlopen(self):
        # Connect refused inside conn.request(): never fully written, so the
        # legacy path may (and must) still try it once.
        out, sent = _drive("POST", "refuse")
        self.assertEqual({"via": "urlopen"}, out)
        self.assertEqual([("urlopen", "POST")], [(s[0], s[1]) for s in sent])

    def test_get_dropped_twice_still_falls_through(self):
        # Idempotent: pool retries once then gives up with plain None; the
        # urlopen fallback is still allowed for a read.
        out, sent = _drive("GET", "drop")
        self.assertEqual({"via": "urlopen"}, out)
        self.assertEqual(["pool", "pool", "urlopen"], [s[0] for s in sent])

    def test_pool_success_unchanged(self):
        out, sent = _drive("POST", "ok")
        self.assertEqual({"ok": True}, out)
        self.assertEqual(1, len(sent))


class PoolContractTests(unittest.TestCase):
    def test_default_contract_still_returns_plain_none(self):
        sent = []
        pool = lcu_pool.HttpsConnectionPool(
            connection_factory=lambda h, p: _Conn(sent, "drop"))
        self.assertIsNone(pool.request("127.0.0.1", 1, "POST", "/x", body=b"{}"))

    def test_opt_in_returns_sentinel_only_when_sent(self):
        sent = []
        pool = lcu_pool.HttpsConnectionPool(
            connection_factory=lambda h, p: _Conn(sent, "drop"))
        self.assertIs(lcu_pool.SENT_UNCONFIRMED, pool.request(
            "127.0.0.1", 1, "POST", "/x", body=b"{}", distinguish_sent=True))
        pool2 = lcu_pool.HttpsConnectionPool(
            connection_factory=lambda h, p: _Conn(sent, "refuse"))
        self.assertIsNone(pool2.request(
            "127.0.0.1", 1, "POST", "/x", body=b"{}", distinguish_sent=True))

    def test_sentinel_is_falsy(self):
        self.assertFalse(lcu_pool.SENT_UNCONFIRMED)


if __name__ == "__main__":
    unittest.main()
