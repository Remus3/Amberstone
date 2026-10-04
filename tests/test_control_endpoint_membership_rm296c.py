"""RM-296c: /api/lcu-cmd (and the routes that reach the SAME LCU command
queue) are control endpoints - a recorded decision, asserted by REJECTION
with RC_DASH_TOKEN set, not by tuple membership alone.
"""
from __future__ import annotations

import pytest

from dashboard import _handler
from tests.test_control_endpoint_auth import _make_post_handler, _patch_dispatch

QUEUE_WRITERS = ("/api/lcu-cmd", "/api/loadout/apply", "/api/sr-draft/apply")
READ_ONLY = ("/api/lcu-cmd-result", "/api/loadout/list", "/api/loadout/rune-pages")


@pytest.mark.parametrize("path", QUEUE_WRITERS)
def test_queue_writers_are_rejected_without_token(monkeypatch, path):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler(path)
    h.do_POST()
    assert sent[-1][0] == 401
    assert calls == []


@pytest.mark.parametrize("path", QUEUE_WRITERS)
def test_queue_writers_pass_with_token(monkeypatch, path):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    calls = _patch_dispatch(monkeypatch)
    h, sent = _make_post_handler(path, token_header="s3cret")
    h.do_POST()
    assert len(calls) == 1


@pytest.mark.parametrize("path", READ_ONLY)
def test_read_only_siblings_are_not_members(path):
    assert not _handler.is_control_endpoint(path)


def test_every_lcu_queue_proxy_route_is_a_member():
    """Sibling sweep: the set of dashboard modules that POST to the vision
    server's /lcu-cmd queue is pinned, so a NEW queue writer fails here and
    forces a membership decision instead of landing as an omission."""
    from pathlib import Path
    root = Path(_handler.__file__).resolve().parent
    owners = set()
    for f in root.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        if "8889/lcu-cmd\"" in src or "8889/lcu-cmd'" in src:
            owners.add(f.name)
    assert owners == {"routes_loadout.py", "routes_sr_draft.py"}, owners
    for p in QUEUE_WRITERS:
        assert _handler.is_control_endpoint(p)
