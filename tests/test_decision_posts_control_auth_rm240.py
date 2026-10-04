"""RM-240: the decision-resolving POSTs are REJECTED without the control token.

Asserted by rejection, not by tuple membership (a membership-only test would
be vacuous in exactly the way the RM-134 guard was).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dashboard import _handler
from tests.test_control_endpoint_auth import _make_post_handler, _patch_dispatch

DECISION_POSTS = ("/api/decisions/abc123", "/api/decisions/respond_active")


@pytest.mark.parametrize("path", DECISION_POSTS)
def test_decision_post_rejected_without_token(monkeypatch, path):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler(path, body=b'{"choice": 0}')
    h.do_POST()
    assert sent[-1][0] == 401
    assert calls == [], "record_choice path reached without the token"


@pytest.mark.parametrize("path", DECISION_POSTS)
def test_decision_post_passes_with_token(monkeypatch, path):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler(path, token_header="s3cret", body=b'{"choice": 0}')
    h.do_POST()
    assert len(calls) == 1


def test_decision_reads_are_not_control_endpoints():
    assert not _handler.is_control_endpoint("/api/decisions")


def test_the_panel_sends_the_token_header():
    js = (Path(_handler.__file__).resolve().parent.parent / "web" / "js"
          / "panels" / "coach_decisions.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem("rc_dash_token")' in js
