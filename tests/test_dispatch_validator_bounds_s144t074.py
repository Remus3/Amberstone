"""s144 true-audit cycle 74: dashboard/_dispatch.py POST body validator bounds.

Measured before the fix (one 1 MiB body, the handler's own cap,
``dashboard/_handler.py`` ``_MAX_POST_BYTES``): POST /api/ds-preview with
``{"champion": "a", "items": [0, 0, ...]}`` - a route OUTSIDE the control
endpoint set, so any LAN peer reaches it - produced 524268 pydantic errors,
and ``_validate_request_body`` logged ONE WARNING LINE PER ERROR (524268 lines
through the rc.dispatch handler chain, far past the 3 MB x 4 files per-day log
ceiling, so one request evicted the whole day's logs) and returned all of them,
so ``dispatch_post`` wrote a 35.5 MB 400 body. A forbidden extra key on
/api/input or /api/command was echoed back VERBATIM as the field label (a
512 KiB key came back as a 524288-character ``field``).

THE FIX: the validator returns at most ``_MAX_FIELD_ERRORS`` entries plus one
summary entry carrying the total, caps every field label and message, and logs
ONE summary line per rejected request.
"""
from __future__ import annotations

import json
import logging

from dashboard import _dispatch
from dashboard._dispatch import _validate_request_body

_FLOOD = 5000


def _warn_records(caplog):
    return [r for r in caplog.records
            if r.name == "rc.dispatch" and r.levelno == logging.WARNING]


class _H:
    def __init__(self, path):
        self.path = path
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def _flood_body():
    return {"champion": "Ahri", "items": [0] * _FLOOD}


def test_error_flood_logs_one_summary_line(caplog):
    with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
        errs = _validate_request_body("/api/ds-preview", _flood_body())
    assert errs, "the flood body must still be rejected"
    recs = _warn_records(caplog)
    assert len(recs) == 1, f"{len(recs)} warning lines for one request"
    msg = recs[0].getMessage()
    assert str(_FLOOD) in msg, msg            # the total is recorded
    assert "items.0" in msg, msg              # and the first field named
    assert len(msg) < 2000, len(msg)


def test_error_flood_response_is_capped(monkeypatch):
    hits = []
    monkeypatch.setattr(_dispatch, "_gather_post",
                        lambda: [(lambda p: True,
                                  lambda h, b: hits.append(b))])
    h = _H("/api/ds-preview")
    assert _dispatch.dispatch_post(h, _flood_body()) is True
    assert hits == [], "a rejected body was dispatched"
    status, payload, ctype = h.sent
    assert status == 400 and ctype == "application/json"
    out = json.loads(payload)
    assert out["error"] == "bad_request_body"
    fields = out["fields"]
    assert len(fields) <= _dispatch._MAX_FIELD_ERRORS + 1, len(fields)
    assert len(payload) < 8192, len(payload)
    # The shown entries are the FIRST errors, in pydantic's order.
    assert fields[0]["field"] == "items.0", fields[0]
    # The last entry says how many were not shown, so nothing is silent.
    assert str(_FLOOD - _dispatch._MAX_FIELD_ERRORS) in fields[-1]["msg"], \
        fields[-1]
    assert all(set(f) == {"field", "msg"} for f in fields), fields


def test_few_errors_are_not_truncated():
    errs = _validate_request_body("/api/ds-preview",
                                  {"champion": "Ahri", "items": [0, 1, 2]})
    assert [e["field"] for e in errs] == ["items.0", "items.1", "items.2"]
    assert not any("not shown" in e["msg"] for e in errs), errs


def test_exactly_the_cap_has_no_summary_entry():
    n = _dispatch._MAX_FIELD_ERRORS
    errs = _validate_request_body("/api/ds-preview",
                                  {"champion": "Ahri", "items": [0] * n})
    assert len(errs) == n, len(errs)
    assert not any("not shown" in e["msg"] for e in errs), errs


def test_forbidden_key_label_is_capped(caplog):
    key = "k" * 100_000
    with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
        errs = _validate_request_body("/api/input", {"text": "x", key: 1})
    assert errs and len(errs) == 1, errs
    label = errs[0]["field"]
    assert label.startswith("k" * 32), label[:40]
    assert len(label) <= _dispatch._MAX_FIELD_CHARS + 32, len(label)
    assert "chars)" in label, label[-40:]     # the clip is marked, not silent
    for r in _warn_records(caplog):
        assert len(r.getMessage()) < 2000, len(r.getMessage())


def test_short_forbidden_key_still_named():
    errs = _validate_request_body("/api/command",
                                  {"command": "refresh", "rogue": 1})
    assert [e["field"] for e in errs] == ["rogue"], errs


def test_module_docstring_has_no_legacy_fallback_claim():
    # _handler.do_POST sends 404 when dispatch_post returns False; there is no
    # legacy elif chain in web_dashboard any more.
    doc = _dispatch.__doc__ or ""
    assert "legacy elif" not in doc, doc
    assert "404" in doc, doc
