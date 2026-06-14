"""Cross-machine SMB push - the only path from Legion -> Game-PC for file writes.

Every Legion->Game-PC file op goes through ``push()``. Anything else bypasses
Agent 0's evaluator and is a bug.

Contract (S11.4, S7):
  * Share: ``\\\\192.168.8.237\\RCClient\\`` (persistent cmdkey-stored creds).
  * Writable zones: ``forwarder\\``, ``web\\``. Anything else is rejected.
  * Atomic write: local -> ``<remote>.tmp`` -> ``os.replace`` over UNC.
  * Backup: existing remote file copied to
    ``\\\\192.168.8.237\\RCClient\\backup\\<YYYYMMDD-HHMMSS>-<label>\\<basename>``
    before the overwrite lands.
  * Verify: SHA-256 of uploaded bytes == SHA-256 of local source.
  * Log: every push -> ``logs/agents/agent2.log`` with SEND/ERROR prefixes.
  * Fail-closed: if the share is unreachable, raise ``SmbUnavailable`` so the
    scheduler can retry the task.

Also exposes ``trigger_forwarder_restart()`` - writes the current ISO timestamp
to ``forwarder/restart_trigger.txt``. Forwarder Agent on Game-PC polls that
file's mtime and self-restarts on change.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

SHARE_UNC = r"\\192.168.8.237\RCClient"
ALLOWED_SUBDIRS = ("forwarder", "web")
FORWARDER_RESTART_SIGNAL = SHARE_UNC + r"\forwarder\restart_trigger.txt"

logger = logging.getLogger("agent2.smb_push")


class SmbUnavailable(RuntimeError):
    """Raised when the SMB share is unreachable. Caller should retry later."""


class SmbRejected(ValueError):
    """Raised when an input violates contract (bad subdir, traversal, etc.)."""


class SmbVerifyFailed(RuntimeError):
    """Raised when post-write SHA-256 does not match source."""


def share_reachable() -> bool:
    try:
        return os.path.exists(SHARE_UNC)
    except OSError:
        return False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ts_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


_LABEL_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitise_label(label: str) -> str:
    """Audit L3: strip Windows-unsafe characters from the label so the
    backup dir `<ts>-<label>` doesn't fail mkdir on `:`, `\\`, `/`, etc.
    """
    cleaned = _LABEL_SAFE.sub("-", label or "unlabeled")
    # Collapse runs of dashes and trim leading/trailing dots.
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned or "unlabeled"


def _validate_subdir(remote_subdir: str) -> str:
    sub = remote_subdir.strip().strip("\\/").lower()
    if sub not in ALLOWED_SUBDIRS:
        raise SmbRejected(
            f"remote_subdir {remote_subdir!r} not in allowlist {ALLOWED_SUBDIRS}"
        )
    return sub


def _backup_existing(remote_path: Path, label: str) -> Path | None:
    if not remote_path.exists():
        return None
    safe = _sanitise_label(label)
    backup_dir = Path(SHARE_UNC) / "backup" / f"{_ts_stamp()}-{safe}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_target = backup_dir / remote_path.name
    shutil.copy2(remote_path, backup_target)
    logger.info("SEND backup %s -> %s", remote_path, backup_target)
    return backup_target


def push(
    local_path: str | os.PathLike,
    remote_subdir: Literal["forwarder", "web"],
    label: str,
    remote_name: str | None = None,
) -> dict:
    """Push ``local_path`` into ``\\\\192.168.8.237\\RCClient\\<remote_subdir>\\``.

    ``label`` tags the backup directory name. ``remote_name`` overrides the
    destination basename; defaults to the local filename.

    Returns a dict: ``{"remote": str, "sha256": str, "backup": str|None, "bytes": int}``.
    """
    local = Path(local_path)
    if not local.is_file():
        raise SmbRejected(f"local_path is not a file: {local}")

    sub = _validate_subdir(remote_subdir)
    if not share_reachable():
        raise SmbUnavailable(f"{SHARE_UNC} is not reachable from this host")

    remote_root = Path(SHARE_UNC) / sub
    remote_root.mkdir(parents=True, exist_ok=True)
    remote_path = remote_root / (remote_name or local.name)

    # Reject traversal attempts.
    try:
        remote_path.resolve().relative_to(Path(SHARE_UNC).resolve())
    except ValueError as e:
        raise SmbRejected(f"path escapes share root: {remote_path}") from e

    expected_sha = _sha256(local)
    backup = _backup_existing(remote_path, label)

    tmp_path = remote_path.with_suffix(remote_path.suffix + ".tmp")
    try:
        shutil.copyfile(local, tmp_path)
        os.replace(tmp_path, remote_path)
    except OSError as e:
        # Best-effort cleanup of .tmp if replace never happened.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        logger.error("ERROR push %s -> %s: %s", local, remote_path, e)
        raise SmbUnavailable(f"SMB write failed for {remote_path}: {e}") from e

    actual_sha = _sha256(remote_path)
    if actual_sha != expected_sha:
        logger.error("ERROR verify mismatch remote=%s expected=%s got=%s", remote_path, expected_sha, actual_sha)
        raise SmbVerifyFailed(
            f"checksum mismatch after write: expected {expected_sha}, got {actual_sha}"
        )

    size = remote_path.stat().st_size
    logger.info(
        "SEND push label=%s bytes=%d sha256=%s remote=%s backup=%s",
        label, size, actual_sha, remote_path, backup,
    )
    return {
        "remote": str(remote_path),
        "sha256": actual_sha,
        "backup": str(backup) if backup else None,
        "bytes": size,
    }


def trigger_forwarder_restart(label: str = "manual") -> dict:
    """Write the current ISO timestamp to the forwarder restart-signal file.

    Uses ``push()`` semantics so the write is logged, checksummed, and backed
    up. Forwarder polls this file's mtime and self-restarts on change.
    """
    if not share_reachable():
        raise SmbUnavailable(f"{SHARE_UNC} unreachable")
    payload = datetime.now(timezone.utc).isoformat().encode("utf-8")
    # Write through a local tmp so push()'s checksum pipeline is consistent.
    local_tmp = Path(os.environ.get("TEMP", ".")) / f"rc-restart-trigger-{int(time.time())}.txt"
    local_tmp.write_bytes(payload)
    try:
        return push(local_tmp, "forwarder", f"restart-{label}", remote_name="restart_trigger.txt")
    finally:
        try:
            local_tmp.unlink()
        except OSError:
            pass
