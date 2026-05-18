"""Integration test for smb_push - actually writes to the SMB share.

Skips gracefully when the share is unreachable (Game-PC off).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from agents.agent2_backend import smb_push


@pytest.fixture(autouse=True)
def _require_share():
    if not smb_push.share_reachable():
        pytest.skip(f"{smb_push.SHARE_UNC} unreachable - Game-PC likely off")


def test_push_web_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "test-from-supervisor.txt"
    payload = b"rc-phase3-integration-test\n"
    src.write_bytes(payload)

    result = smb_push.push(src, remote_subdir="web", label="phase3-integration", remote_name="test-from-supervisor.txt")

    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["backup"] is None                # no prior file
    remote = Path(result["remote"])
    assert remote.exists()
    assert remote.read_bytes() == payload

    # Clean up remote file so the share stays tidy.
    try:
        remote.unlink()
    except OSError:
        pass


def test_push_web_overwrites_creates_backup(tmp_path: Path) -> None:
    """Audit P-audit-m1 - exercise the backup branch.

    Push same remote filename twice with different payloads; assert the
    second result carries a backup path whose contents match the first
    payload, and the remote file now matches the second payload.
    """
    remote_name = "test-backup-path.txt"
    src1 = tmp_path / "src1.txt"
    src2 = tmp_path / "src2.txt"
    payload1 = b"first-payload-" + os.urandom(8).hex().encode()
    payload2 = b"second-payload-" + os.urandom(8).hex().encode()
    src1.write_bytes(payload1)
    src2.write_bytes(payload2)

    # First push - no backup expected.
    r1 = smb_push.push(src1, remote_subdir="web", label="m1-initial", remote_name=remote_name)
    assert r1["backup"] is None
    remote = Path(r1["remote"])
    assert remote.read_bytes() == payload1

    # Second push to same remote - must back up the prior payload.
    r2 = smb_push.push(src2, remote_subdir="web", label="m1-overwrite", remote_name=remote_name)
    assert r2["backup"] is not None, "backup path should exist on overwrite"
    backup = Path(r2["backup"])
    assert backup.exists()
    assert backup.read_bytes() == payload1, "backup must carry the first payload"
    assert remote.read_bytes() == payload2, "remote must now carry the second payload"

    # Tidy.
    try:
        remote.unlink()
        backup.unlink()
        # Best-effort rmdir of the backup timestamp folder.
        try:
            backup.parent.rmdir()
        except OSError:
            pass
    except OSError:
        pass


def test_push_rejects_bad_subdir(tmp_path: Path) -> None:
    src = tmp_path / "x.txt"
    src.write_bytes(b"x")
    with pytest.raises(smb_push.SmbRejected):
        smb_push.push(src, remote_subdir="etc", label="bad-subdir")  # type: ignore[arg-type]


def test_push_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(smb_push.SmbRejected):
        smb_push.push(tmp_path / "nope.txt", remote_subdir="web", label="missing")
