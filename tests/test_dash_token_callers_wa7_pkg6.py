# arch: PKG-6 WA7 - gated control callers send X-RC-Token | section=tests | frozen=no
"""PACKAGING_PLAN residual WA7 (PKG-6): three callers of RC_DASH_TOKEN-gated
control endpoints sent no X-RC-Token - the auto-accept toggle
(web/js/main.js), the coach-choice POST (web/js/panels/coach_choices.js) and
the calibrator ingest (web/vision_calibrator.html). The shell injects the
per-install token for its own windows (rc-shell/src/main.js
installTokenHeader); a plain browser needs the page to send
localStorage.rc_dash_token like every other gated caller. Each fetch is
pinned here, and each path is pinned as a control endpoint so the header is
not decoration.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from dashboard import _handler as handler

REPO = Path(__file__).resolve().parent.parent

CALLERS = (
    ("web/js/main.js", "/api/lcu/auto-accept"),
    ("web/js/panels/coach_choices.js", "/api/coach-choice"),
    ("web/vision_calibrator.html", "/api/vision-reference"),
)


@pytest.mark.parametrize("rel,endpoint", CALLERS)
def test_every_gated_fetch_sends_the_token(rel, endpoint):
    text = (REPO / rel).read_text(encoding="utf-8")
    sites = [m.start() for m in re.finditer(r'fetch\("' + re.escape(endpoint) + r'"', text)]
    assert sites, f"{rel} still calls {endpoint}"
    for at in sites:
        call = text[at:at + 400]
        assert "X-RC-Token" in call, f"{rel}:{text.count(chr(10), 0, at) + 1} sends no X-RC-Token"
        assert "rc_dash_token" in text[max(0, at - 200):at + 400], "the stored token"


@pytest.mark.parametrize("_rel,endpoint", CALLERS)
def test_each_endpoint_is_a_gated_control_endpoint(_rel, endpoint):
    assert handler.is_control_endpoint(endpoint), endpoint
