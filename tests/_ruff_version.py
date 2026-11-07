"""RM-1657 - the ruff a ruff-semantics ratchet was measured against.

Some ratchet facts belong to one ruff, not to the tree. ruff 0.17 stopped firing
BLE001 on a handler that logs with exc_info=True and stopped firing RET504 at two
baselined sites, so run 42003344193 (.github/ci/requirements-ci.txt, ruff 0.17.2)
reads directives and baseline rows differently from ruff 0.15.12. Such a check
reads only the ruff it was measured against.

RM-1974 (a): the local ruff moved to 0.17.3 on 2026-11-05, so both ratchets were
re-measured on one tree with ruff 0.15.16, 0.17.2 (the CI pin) and 0.17.3. The
two 0.17 runs read identically; every delta from 0.15 is that BLE001 / RET504
change (named in each ratchet's docstring), so MEASURED_RUFF is now (0, 17) and
the CI runs these checks instead of skipping them.
"""
from __future__ import annotations

import re
import subprocess
import sys

MEASURED_RUFF = (0, 17)


def ruff_minor() -> tuple[int, int]:
    """(major, minor) of the ruff this interpreter runs."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                          capture_output=True, text=True, timeout=60, **kwargs)
    m = re.search(r"(\d+)\.(\d+)\.", proc.stdout)
    assert m, f"no version in {proc.stdout!r} {proc.stderr[-200:]!r}"
    return int(m.group(1)), int(m.group(2))


def fail_if_the_landing_box_moved(minor: tuple[int, int]) -> None:
    """The caller is about to skip for ``minor``. Off Windows that is the CI's newer ruff;
    on the box that lands code it means the local ruff moved, and a silent skip would
    retire these ratchets, so re-measure and move MEASURED_RUFF instead."""
    assert sys.platform != "win32", (
        f"the local ruff is {minor}, not the measured {MEASURED_RUFF}: re-measure (RM-1657)")
