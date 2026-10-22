"""RM-268 (with RM-266 / RM-267 / RM-268): residues of the vision_server/_relay.py
audit (lane 8 cycle 25), exercised against the REAL Handler on a loopback
port.

RM-266: /lcu-cmd-result hand-rolled the lookup lcu_get_result exists for;
        one lookup now, and the served row is a COPY.
RM-267: /stats was the only unauthenticated data GET on :8889.
RM-268: /lcu-cmd queued any JSON value (list, string, number) as `cmd`;
        a non-object body now gets a fixed 400 token and NOTHING is queued.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from vision_server import _relay
from vision_server._config import AUTH_HEADER, AUTH_TOKEN
from vision_server._http import Handler

@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    with _relay._lcu_cmd_lock:
        _relay._lcu_cmd_queue.clear()
        _relay._lcu_cmd_results.clear()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
        with _relay._lcu_cmd_lock:
            _relay._lcu_cmd_queue.clear()
            _relay._lcu_cmd_results.clear()


def _req(port, path, body=None, auth=True):
    headers = {AUTH_HEADER: AUTH_TOKEN} if auth else {}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, headers=headers,
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# -- RM-268 ------------------------------------------------------------------

@pytest.mark.parametrize("body", [b"[1,2]", b'"x"', b"5", b"null", b"true"])
def test_non_object_lcu_cmd_is_400_and_queues_nothing(server, body):
    status, payload = _req(server, "/lcu-cmd", body)
    assert status == 400
    assert payload == {"error": "body must be a JSON object"}
    assert len(_relay._lcu_cmd_queue) == 0


def test_object_lcu_cmd_is_still_queued(server):
    status, payload = _req(server, "/lcu-cmd", b'{"action": "accept"}')
    assert status == 200
    assert isinstance(payload["id"], int)
    assert len(_relay._lcu_cmd_queue) == 1


def test_non_object_lcu_cmd_done_is_400(server):
    status, payload = _req(server, "/lcu-cmd-done", b"[1]")
    assert status == 400
    assert payload == {"error": "body must be a JSON object"}
    assert _relay._lcu_cmd_results == {}


def test_lcu_cmd_done_records_result(server):
    status, _ = _req(server, "/lcu-cmd-done", b'{"id": 7, "result": {"ok": 1}}')
    assert status == 200
    assert _relay._lcu_cmd_results[7]["result"] == {"ok": 1}


# -- RM-760c -----------------------------------------------------------------
# A body that is not valid JSON at all used to fall through to the generic
# `except Exception` in do_POST: HTTP 500 "internal error". Malformed text,
# invalid UTF-8, a 5000-digit integer (int-max-str-digits ValueError) and
# 100k-deep nesting (RecursionError) are all bad INPUT, so they get a fixed
# 400 token that never echoes parser text, and nothing is queued.

_BAD_JSON_BODIES = {
    "malformed": b"{x",
    "invalid_utf8": b'{"a": "\xff"}',
    "long_int": b"1" * 5000,
    "deep_nesting": b"[" * 100000,
}


@pytest.mark.parametrize("path", ["/lcu-cmd", "/lcu-cmd-done"])
@pytest.mark.parametrize("name", sorted(_BAD_JSON_BODIES))
def test_bad_json_lcu_body_is_400_and_queues_nothing(server, path, name):
    status, payload = _req(server, path, _BAD_JSON_BODIES[name])
    assert status == 400
    assert payload == {"error": "invalid JSON body"}
    assert len(_relay._lcu_cmd_queue) == 0
    assert _relay._lcu_cmd_results == {}


def test_server_still_serves_after_deep_nesting(server):
    _req(server, "/lcu-cmd", _BAD_JSON_BODIES["deep_nesting"])
    status, payload = _req(server, "/lcu-cmd", b'{"action": "accept"}')
    assert status == 200
    assert isinstance(payload["id"], int)


@pytest.mark.parametrize("path", ["/vision", "/coach", "/ocr"])
@pytest.mark.parametrize("name", sorted(_BAD_JSON_BODIES))
def test_bad_json_inference_body_is_bad_json_not_500(server, path, name):
    # The inference handlers already answer 200 {"error": "bad_json"} for a
    # ValueError; deep nesting raised RecursionError past that catch.
    status, payload = _req(server, path, _BAD_JSON_BODIES[name])
    assert status == 200
    assert payload == {"error": "bad_json"}
