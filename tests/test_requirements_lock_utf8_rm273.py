"""RM-273: requirements.lock must stay UTF-8 (no BOM) so grep audits see it.

A PowerShell 5.1 `pip freeze > requirements.lock` redirect writes UTF-16LE,
which made `grep -c certifi requirements.lock` return 0 on a file that
carried certifi, and produced a false finding (RM-255). The sibling guard
below keeps any OTHER tracked file from silently going UTF-16, except Task
Scheduler XML exports, whose own prolog declares UTF-16 (schtasks format).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / "requirements.lock"

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def test_requirements_lock_is_utf8_without_bom():
    raw = LOCK.read_bytes()
    assert raw, "requirements.lock is empty"
    assert not raw.startswith(_UTF16_BOMS), "requirements.lock is UTF-16"
    assert not raw.startswith(b"\xef\xbb\xbf"), "requirements.lock has a UTF-8 BOM"
    text = raw.decode("utf-8")  # raises on non-UTF-8
    assert b"\r\n" not in raw, "requirements.lock must be LF-only"
    # The byte-level grep the RM-255 audit ran must now find a pin.
    assert raw.count(b"certifi==") == 1
    assert len([ln for ln in text.splitlines() if "==" in ln]) >= 50


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout
    return [REPO / p.decode("utf-8") for p in out.split(b"\0") if p]


def test_no_tracked_file_is_utf16_except_declared_task_xml():
    files = _tracked_files()
    assert len(files) > 1000, "git index enumeration came back near-empty"
    offenders = []
    for path in files:
        try:
            with path.open("rb") as fh:
                head = fh.read(200)
        except OSError:
            continue
        if not head.startswith(_UTF16_BOMS):
            continue
        prolog = head.decode("utf-16", errors="replace")
        if path.suffix.lower() == ".xml" and 'encoding="UTF-16"' in prolog:
            continue
        offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == [], f"UTF-16 tracked files invisible to grep: {offenders}"
