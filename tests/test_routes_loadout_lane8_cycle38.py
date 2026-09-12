# arch: lane 8 cycle 38 hardening tests for dashboard/routes_loadout | section=tests | frozen=no
"""Lane 8 cycle 38: dashboard/routes_loadout.py trust-boundary hardening.

`/api/lcu-cmd` is the dashboard edge in front of the LCU command queue that
`RC-LCUAgent` drains and executes against the running League client. Whatever
crosses it reaches a privileged local API, so the edge is the last place a
malformed body can be stopped.

MEASURED LIVE 2026-08-31 against the running dashboard (pid 47076):

    POST /api/lcu-cmd {"cmd":"bogus_cmd"}  -> HTTP 400          (correct)
    POST /api/lcu-cmd {"cmd":123}          -> curl exit 56, no response
    POST /api/lcu-cmd {"cmd":{"a":1}}      -> curl exit 56, no response
    POST /api/lcu-cmd {"cmd":true}         -> curl exit 56, no response

`curl` exit 56 is "failure with receiving network data": the connection was
closed with NO HTTP RESPONSE AT ALL. The 400 case appears in the log at
`_handler.py:157`; the other three appear NOWHERE, because the request died
before the handler could log it. The failure is invisible on the wire and in
the log at the same time, which is why it survived.

Root cause: `_serve_lcu_cmd_post` reads `(payload.get("cmd") or "").strip()`
OUTSIDE its own `try:`. A truthy non-string `cmd` raises AttributeError there,
and `dashboard/_handler.py` `do_POST` wraps `_dispatch.dispatch_post` in no
try at all, so the exception unwinds into the stdlib, which closes the socket
and prints a traceback to stderr - and RC runs under `pythonw.exe`, which has
no console for that traceback to reach.

The harness mirrors `tests/test_rune_pages_route.py`: a FakeHandler capturing
the `_send(status, body, ctype)` triple, driven straight against the handler.
"""
from __future__ import annotations

import json

import pytest

from dashboard import routes_loadout as mod


class FakeHandler:
    """Minimal StubHandler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/lcu-cmd") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


def _post_cmd(payload) -> tuple:
    """Drive _serve_lcu_cmd_post and return (status, parsed_body, ctype).

    Deliberately does NOT wrap the call: if the handler raises, the test
    fails with that exception, which is the exact production symptom.
    """
    h = FakeHandler()
    mod._serve_lcu_cmd_post(h, payload)
    assert h.sent is not None, "handler returned without sending a response"
    status, body, ctype = h.sent
    return status, json.loads(body.decode("utf-8")), ctype


# ------------------------------------------------------- D1: non-string cmd
# Every one of these is a truthy non-str, so `or ""` does not rescue it and
# `.strip()` raises. Each was measured to produce NO HTTP RESPONSE live.
@pytest.mark.parametrize("bad_cmd", [
    123,
    12.5,
    True,
    {"a": 1},
    ["accept_ready"],
    {"accept_ready"},
])
def test_non_string_cmd_returns_400_and_never_raises(bad_cmd):
    status, body, ctype = _post_cmd({"cmd": bad_cmd})
    assert status == 400
    assert ctype == "application/json"
    assert body["error"] == "unknown_lcu_cmd"


def test_missing_cmd_key_returns_400():
    status, body, _ = _post_cmd({})
    assert status == 400
    assert body["error"] == "unknown_lcu_cmd"


@pytest.mark.parametrize("falsy_cmd", [None, "", 0, [], {}])
def test_falsy_cmd_returns_400(falsy_cmd):
    # Characterization: these already worked, because `or ""` catches them
    # before .strip(). Pinned so the D1 fix cannot regress them.
    status, body, _ = _post_cmd({"cmd": falsy_cmd})
    assert status == 400
    assert body["error"] == "unknown_lcu_cmd"


def test_unknown_string_cmd_returns_400_with_allowed_list():
    # Characterization of the path that already behaved (measured live: 400).
    status, body, _ = _post_cmd({"cmd": "bogus_cmd"})
    assert status == 400
    assert body["error"] == "unknown_lcu_cmd"
    assert body["cmd"] == "bogus_cmd"
    assert "accept_ready" in body["allowed"]


def test_rejected_cmd_is_not_echoed_as_a_non_string():
    # The 400 envelope echoes `cmd` back. It must be JSON-safe whatever came
    # in - a set or a non-str must not break json.dumps of the error body.
    status, body, _ = _post_cmd({"cmd": {"nested": ["x"]}})
    assert status == 400
    assert isinstance(body["cmd"], str)


# ------------------------------------------- D1 (sibling): the other handlers
# A non-string `champion` reaches .strip() in the loadout/list + rune-pages
# handlers too. Those DO sit inside a try, so they collapse to a 500 rather
# than killing the connection - but a client type error is not a server
# error, and a 500 tells the operator to look in the logs for an RC fault
# that does not exist.
@pytest.mark.parametrize("handler,path", [
    (mod._serve_loadout_list_post, "/api/loadout/list"),
    (mod._serve_rune_pages_post, "/api/loadout/rune-pages"),
])
@pytest.mark.parametrize("bad_champ", [123, True, {"a": 1}, ["Jinx"]])
def test_non_string_champion_is_a_client_error_not_a_server_error(
        handler, path, bad_champ):
    h = FakeHandler(path)
    handler(h, {"champion": bad_champ})
    assert h.sent is not None
    status, body, _ = h.sent
    assert status == 400, f"{path} returned {status} for a wrong-typed champion"
    assert json.loads(body.decode("utf-8"))["error"] == "champion required"


# ------------------------------------------------ D5: override_summoners bools
def test_override_summoners_rejects_booleans():
    """`isinstance(True, int)` is True in Python, so the old guard admitted
    `[true, false]`. The NON-user-build path then assigned the pair into the
    outbound LCU command with no int() conversion while the user-build path
    ran int() - two paths, same input, different wire bytes.

    SEVERITY SCOPED to the evidence: the adversarial pass established that
    the boolean never reaches the League client, because `tools/lcu_agent.py:657`
    does `int(cmd.get("d", 0))` and both paths converge on spell id 1. So this
    is an inconsistent trust boundary, NOT a wrong-summoner bug in production.
    It is still worth closing: the agent's coercion is incidental to its
    implementation, not a contract this edge is entitled to lean on.
    """
    assert mod._coerce_override_summoners([True, False]) is None
    assert mod._coerce_override_summoners([True, 4]) is None


@pytest.mark.parametrize("pair", [
    [-1, 4],           # negative id
    [4, 10 ** 9],      # absurd id
    [4],               # too short
    [4, 6, 14],        # too long
    ["4", "6"],        # strings, not ints
    "46",              # not a list
    None,
    {"d": 4, "f": 6},
])
def test_override_summoners_rejects_malformed(pair):
    assert mod._coerce_override_summoners(pair) is None


def test_override_summoners_accepts_a_real_pair():
    assert mod._coerce_override_summoners([4, 14]) == (4, 14)


# ------------------------------------------------------- D4: honest ok/queued
def test_apply_reports_failure_when_every_enqueue_fails(monkeypatch):
    """`_serve_loadout_apply_post` returned {"ok": True} even when all three
    enqueues raised, because `_enqueue` swallows and only appends on success.
    The route claimed the push landed when nothing reached the LCU.
    """
    def _boom(cmd_obj):
        raise OSError("vision server down")

    monkeypatch.setattr(mod, "_post_lcu_cmd", _boom)
    monkeypatch.setattr(
        mod, "_resolve_variant",
        lambda champ, variant, mode, ov: {
            "ok": True, "mode": "sr", "label": "x",
            "rune_cmd": {"cmd": "apply_runes"},
            "item_cmd": None, "summ_cmd": None, "raw_items": [],
        },
    )
    h = FakeHandler("/api/loadout/apply")
    mod._serve_loadout_apply_post(h, {"champion": "Jinx", "variant": "v1"})
    assert h.sent is not None
    status, body, _ = h.sent
    payload = json.loads(body.decode("utf-8"))
    assert payload["queued"] == []
    assert payload["failed"] == ["apply_runes"]
    assert payload["ok"] is False, "route claimed success with nothing queued"


def test_apply_reports_ok_when_the_enqueue_lands(monkeypatch):
    monkeypatch.setattr(mod, "_post_lcu_cmd", lambda cmd_obj: b"{}")
    monkeypatch.setattr(
        mod, "_resolve_variant",
        lambda champ, variant, mode, ov: {
            "ok": True, "mode": "sr", "label": "x",
            "rune_cmd": {"cmd": "apply_runes"},
            "item_cmd": None, "summ_cmd": None, "raw_items": [],
        },
    )
    h = FakeHandler("/api/loadout/apply")
    mod._serve_loadout_apply_post(h, {"champion": "Jinx", "variant": "v1"})
    status, body, _ = h.sent
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["queued"] == ["apply_runes"]
    assert payload["failed"] == []


# ------------------------------------------------- D3: HTTPError close hygiene
def test_lcu_cmd_result_closes_the_upstream_error_response(monkeypatch):
    """The HTTPError is closed on the error path.

    CLAIM CORRECTED. This was first filed as a socket leak; the adversarial
    pass REFUTED that and the correction is recorded rather than dropped.
    CPython `urllib.request` (request.py lines 1333-1335) closes the socket immediately after
    `getresponse()` and an amt-less CPython `http.client` (client.py line 505) `read()` calls
    `_close_conn()`, so no descriptor leaks - 300 iterations against a local
    404 server moved the handle count by zero. What remains is a
    ResourceWarning from `urllib.response.addbase`. This test therefore
    guards HYGIENE, not a leak, and is labelled so no future reader inflates
    it back into a security finding.
    """
    import urllib.error

    closed = []

    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            self.code = 404
            self._body = b'{"error":"pending"}'

        def read(self):
            return self._body

        def close(self):
            closed.append(True)

    def _boom(req, timeout=None):
        raise FakeHTTPError()

    monkeypatch.setattr(mod, "_urlopen", _boom)
    h = FakeHandler("/api/lcu-cmd-result?id=7")
    mod._serve_lcu_cmd_result_get(h)
    assert closed == [True], "upstream HTTPError response was never closed"


def test_lcu_cmd_result_requires_an_id():
    h = FakeHandler("/api/lcu-cmd-result")
    mod._serve_lcu_cmd_result_get(h)
    status, body, _ = h.sent
    assert status == 400
    assert json.loads(body.decode("utf-8"))["error"] == "id required"


# ------------------------------------------------- D2: the prose was FALSE
def test_module_docstring_does_not_claim_downstream_revalidation():
    """MEASURED: `vision_server/_relay.lcu_queue_command` appends the command
    dict to the queue VERBATIM, and no allowlist exists anywhere in
    `vision_server/`. The old comment "The vision server also revalidates"
    named a component that does no validation at all.

    The replacement is deliberately NOT "this is the sole gate" - that
    overcorrection was refuted too. `tools/lcu_agent.py` name-dispatches and
    coerces fields, so a second gate does exist, one hop further on. The
    docstring must say both things, so this pins both.
    """
    src = mod.__doc__ or ""
    # A bare `"also revalidates" not in src` is the wrong assertion: the
    # docstring QUOTES the false claim in order to refute it, so the
    # substring is legitimately present. A negative rules out without
    # pinning down (feedback_negative_assertion_rules_out_without_pinning_down);
    # assert the positive facts the docstring must carry instead.
    quoted = src.index("also revalidates")
    verdict = src.index("MEASURED FALSE")
    assert verdict > quoted, "the quoted claim must be marked false right after it"
    assert "PIPE, not a gate" in src
    assert "lcu_agent" in src, "must name where the real second gate is"
    assert "SOLE" not in src, "refuted overcorrection must not creep back"


# --------------------------------------------- A1: validate-vs-forward mismatch
def test_whitespace_padded_cmd_is_forwarded_normalized(monkeypatch):
    """The edge validated the STRIPPED name but forwarded the payload
    UNSTRIPPED, so `{"cmd":" accept_ready "}` passed here and then failed at
    `lcu_agent.py:422` ("unknown cmd") - this route reporting acceptance for
    a command guaranteed to be a no-op.
    """
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"id": 1}'

    def _capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(mod, "_urlopen", _capture)
    monkeypatch.setitem(__import__("sys").modules, "web_dashboard",
                        type("M", (), {"_VISION_TOKEN": "t"})())
    status, _, _ = _post_cmd({"cmd": "  accept_ready  ", "extra": 1})
    assert status == 200
    assert seen["body"]["cmd"] == "accept_ready", "forwarded an unstripped verb"
    assert seen["body"]["extra"] == 1, "sibling keys must still pass through"


# ------------------------------ A3: raw exception text into the champ-select UI
def test_result_body_scrubs_the_agents_raw_exception_text():
    """`tools/lcu_agent.py:1694` fills `err` with `f"{type(exc).__name__}: {exc}"`,
    `vision_server/_http.py:148` returns the record verbatim on 200, and
    `web/js/panels/champ_select.js:1330-1331` renders `"X Lock failed: " + err`.
    A raw `PermissionError: [WinError 5] ...` was therefore painted onto the
    champ-select lock button - the absolute CLAUDE.md Error Handling rule.
    """
    raw = b'{"ok": false, "err": "PermissionError: [WinError 5] C:\\\\secret"}'
    out = json.loads(mod._scrub_result_err(raw))
    assert out["ok"] is False, "pass-through fields must be untouched"
    assert out["err"] == "command failed - see logs"
    assert "WinError" not in json.dumps(out)
    assert "secret" not in json.dumps(out)


def test_result_scrub_reaches_a_nested_result_record():
    raw = b'{"id": 3, "result": {"ok": false, "err": "OSError: boom"}}'
    out = json.loads(mod._scrub_result_err(raw))
    assert out["result"]["err"] == "command failed - see logs"
    assert out["id"] == 3


@pytest.mark.parametrize("body", [
    b'{"ok": true}',                    # success record, no err
    b'{"ok": false, "err": ""}',        # empty err
    b'{"ok": false, "err": null}',      # non-str err
    b'not json at all',                 # unparseable
    b'[1, 2, 3]',                       # not an object
])
def test_result_scrub_is_a_transparent_passthrough_otherwise(body):
    assert mod._scrub_result_err(body) == body


# --------------------------------------------- D7: prefix suffix-match closed
@pytest.mark.parametrize("path,expected", [
    ("/api/lcu-cmd-result", True),
    ("/api/lcu-cmd-result?id=1", True),
    ("/api/lcu-cmd-resultXYZ", False),
    ("/api/lcu-cmd-resultXYZ?id=1", False),
])
def test_result_route_matcher_rejects_suffix_paths(path, expected):
    matcher = mod.GET_ROUTES[0][0]
    assert matcher(path) is expected


@pytest.mark.parametrize("path,expected", [
    ("/api/loadout/list", True),
    ("/api/loadout/list?x=1", True),
    ("/api/loadout/listEVIL", False),
])
def test_list_route_matcher_rejects_suffix_paths(path, expected):
    matcher = next(m for m, fn in mod.POST_ROUTES
                   if fn is mod._serve_loadout_list_post)
    assert matcher(path) is expected


# ------------------------------- RM-296d: push_* flags read as bare truthiness
# `_serve_loadout_apply_post` read the three push flags with
# `payload.get(k, True)` and consumed them as BARE TRUTHINESS. A JSON body
# {"push_runes": "false"} yields the non-empty string "false", which is truthy,
# so the runes were pushed anyway - the route overwrote the operator's live
# rune page with the one thing the body had just asked it not to touch. Same
# for "0", "no", "off".
#
# Contract pinned here:
#   absent      -> push (the live default, unchanged)
#   real bool   -> as-is (unchanged)
#   string/num  -> parsed off/on spellings
#   ambiguous   -> 400, nothing pushed

_PUSH_KEYS = ("push_runes", "push_items", "push_summoners")
_PUSH_CMD = {
    "push_runes": "apply_runes",
    "push_items": "apply_items",
    "push_summoners": "apply_summoners",
}


def _apply(monkeypatch, body_extra):
    """Drive /api/loadout/apply with all three commands resolvable.

    The resolver stub always offers a rune, item AND summoner command, so
    `queued` names exactly the pushes the flag coercion let through. Returns
    (status, parsed_body, enqueued_cmd_names).
    """
    seen = []

    def _capture(cmd_obj):
        seen.append(cmd_obj.get("cmd"))
        return b"{}"

    monkeypatch.setattr(mod, "_post_lcu_cmd", _capture)
    monkeypatch.setattr(
        mod, "_resolve_variant",
        lambda champ, variant, mode, ov: {
            "ok": True, "mode": "sr", "label": "x",
            "rune_cmd": {"cmd": "apply_runes"},
            "item_cmd": {"cmd": "apply_items"},
            "summ_cmd": {"cmd": "apply_summoners"},
            "raw_items": [],
        },
    )
    h = FakeHandler("/api/loadout/apply")
    payload = {"champion": "Jinx", "variant": "v1"}
    payload.update(body_extra)
    mod._serve_loadout_apply_post(h, payload)
    assert h.sent is not None, "handler returned without sending a response"
    status, raw, _ = h.sent
    return status, json.loads(raw.decode("utf-8")), seen


@pytest.mark.parametrize("key", _PUSH_KEYS)
@pytest.mark.parametrize("off_value", [
    False,          # the already-correct client
    "false",        # THE BUG: truthy non-empty string
    "False",        # case must not matter
    " off ",        # whitespace must not matter
    "no",
    "off",
    "n",
    "0",            # 0-as-string, truthy in Python
    "",             # blank form field
    0,              # real JSON zero
    0.0,
])
def test_explicit_falsey_push_flag_turns_that_push_off(
        monkeypatch, key, off_value):
    status, body, seen = _apply(monkeypatch, {key: off_value})
    assert status == 200
    suppressed = _PUSH_CMD[key]
    assert suppressed not in seen, (
        f"{key}={off_value!r} still pushed {suppressed}")
    # The other two are untouched by one flag being off.
    for other in _PUSH_KEYS:
        if other != key:
            assert _PUSH_CMD[other] in seen
    assert body["ok"] is True
    assert suppressed not in body["queued"]


def test_omitted_push_flags_still_push_everything(monkeypatch):
    """The live contract. Only an EXPLICITLY supplied falsey value may turn a
    push off; a body that never mentions the key keeps push-everything."""
    status, body, seen = _apply(monkeypatch, {})
    assert status == 200
    assert sorted(seen) == sorted(_PUSH_CMD.values())
    assert sorted(body["queued"]) == sorted(_PUSH_CMD.values())


@pytest.mark.parametrize("key", _PUSH_KEYS)
def test_explicit_true_bool_is_unchanged(monkeypatch, key):
    status, body, seen = _apply(monkeypatch, {key: True})
    assert status == 200
    assert _PUSH_CMD[key] in seen


@pytest.mark.parametrize("key", _PUSH_KEYS)
@pytest.mark.parametrize("on_value", ["true", "True", " on ", "yes", "y",
                                      "1", 1, 1.0])
def test_explicit_truthy_spellings_keep_that_push_on(
        monkeypatch, key, on_value):
    status, body, seen = _apply(monkeypatch, {key: on_value})
    assert status == 200
    assert _PUSH_CMD[key] in seen


def test_all_three_flags_off_pushes_nothing(monkeypatch):
    status, body, seen = _apply(
        monkeypatch, {k: "false" for k in _PUSH_KEYS})
    assert status == 200
    assert seen == []
    assert body["queued"] == []


@pytest.mark.parametrize("key", _PUSH_KEYS)
@pytest.mark.parametrize("ambiguous", [
    "maybe",
    "FALSE!",
    2,          # truthy under the old read, but not a boolean
    -1,
    3.7,
    None,       # JSON null is NOT the same statement as an absent key
    [],
    ["false"],
    {},
    {"v": False},
])
def test_ambiguous_push_flag_is_a_400_and_pushes_nothing(
        monkeypatch, key, ambiguous):
    """A value the server cannot read is not consent to overwrite a live rune
    page. Defaulting ambiguity to push is the original defect; defaulting it
    to skip is a silent failure of the operator's intent behind a green
    status. Reject, the way the sibling `dismiss` flag does at
    `dashboard/routes_diag.py:347-350` for the same wrong-type class."""
    status, body, seen = _apply(monkeypatch, {key: ambiguous})
    assert status == 400, f"{key}={ambiguous!r} was accepted"
    assert seen == [], "a rejected body must not enqueue anything"
    assert body["error"] == "bad_push_flag"
    assert body["field"] == key


def test_bad_push_flag_does_not_preempt_the_champion_check(monkeypatch):
    """Error precedence is unchanged: a body missing champion+variant still
    reports that first, whatever its flags look like."""
    monkeypatch.setattr(mod, "_post_lcu_cmd", lambda cmd_obj: b"{}")
    h = FakeHandler("/api/loadout/apply")
    mod._serve_loadout_apply_post(h, {"push_runes": "maybe"})
    status, raw, _ = h.sent
    assert status == 400
    assert json.loads(raw.decode("utf-8"))["error"] == (
        "champion+variant required")
