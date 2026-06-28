"""Retirement contract for smb_push - the 2-PC Legion -> Game-PC SMB push path.

RETIRED (ADR-011 1-PC consolidation 2026-05-29 + ADR-012 bridge decommission
2026-06-24, resolved_decisions phase3-d026): Game-PC is out of the pipeline and
the \\192.168.8.237\\RCClient share has no receiving end, so the push path is
dead code pending a separate cleanup pass (mirror of the Brawl-retirement
deadcode pattern, phase3-d019). These tests pin the retired contract: the share
is never reachable and push() / trigger_forwarder_restart() hard-fail with a
clear ADR pointer so no future ephemeral agent re-wires the dead path.

The pure helpers (_sanitise_label, the exception taxonomy) stay importable and
are covered separately by test_quality_pass.py - the module is neutered, not
deleted, so the gatekeeper P-audit-h1 traversal guard keeps its standing
safety net.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.agent2_backend import smb_push


def test_share_reachable_is_hard_false() -> None:
    # Hard False (not network-probed) post-retirement - there is no remote to
    # reach, so the legacy skip-gates short-circuit without a probe.
    assert smb_push.share_reachable() is False


def test_push_raises_retired(tmp_path: Path) -> None:
    src = tmp_path / "x.txt"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError) as exc:
        smb_push.push(src, remote_subdir="web", label="retired-probe")
    msg = str(exc.value).lower()
    assert "retired" in msg
    assert "adr-011" in msg or "adr-012" in msg


def test_trigger_forwarder_restart_raises_retired() -> None:
    with pytest.raises(RuntimeError) as exc:
        smb_push.trigger_forwarder_restart(label="retired-probe")
    assert "retired" in str(exc.value).lower()


def test_pure_helpers_still_importable() -> None:
    # The label sanitiser + exception taxonomy stay on the module surface;
    # test_quality_pass.py imports _sanitise_label directly.
    assert smb_push._sanitise_label("a:b") == "a-b"
    assert issubclass(smb_push.SmbUnavailable, RuntimeError)
