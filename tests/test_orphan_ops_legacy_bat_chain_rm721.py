"""RM-721 (d) dead-launcher drift guard: the legacy ops/*.bat start chain stays archived.

ops/autostart_on_login.bat (a Startup-folder target) ran
ops/launch_new_system.bat, which killed every pythonw.exe, started
ops/rc_supervisor.py and a hidden ops/run_self_healing_watchdog.ps1, and
passed that watchdog `--ConfigPath` where the script declares `$ConfigPath`
(the known latent bug, ops/audit/P2_FINDINGS.md). Both were archived to
docs/_archive/2026-10/ in session 144 (repo lane, git mv, history kept)
because the chain was dead on two independent facts:

  1. NOTHING RUNS IT. A read-only `schtasks /Query /FO CSV /V` (s134 research
     lane cycle 14, 396 task rows) named neither file, nor rc_bootstrap /
     install_startup; the user Startup folder held no RC shortcut; outside
     tests and docs the only file that ran launch_new_system.bat was
     autostart_on_login.bat, and no tracked installer registers
     autostart_on_login.bat. The live start path is the RC-Supervisor
     scheduled task (docs/OPERATIONS.md).
  2. Fixing it would WAKE a dormant watchdog: correcting the flag makes the
     watchdog read its config for the first time, on a chain nobody starts.

The tools/build_portable.py `_BOOT_FILES` / `_KILL_FILES` entries are KEPT on
purpose: those lists keep a file OUT of the portable bundle, so they still
guard against a re-added copy shipping, and
tests/test_build_portable_bundle_pkg.py asserts exclusion_reason() for the
autostart path. ops/start_ops.bat and ops/run_self_healing_watchdog.ps1 are
NOT part of this retirement.

If you find yourself restoring either file, first confirm a real caller
exists; the archived copies are the reference.
"""
from __future__ import annotations

import subprocess

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_RETIRED = {
    "ops/launch_new_system.bat": "docs/_archive/2026-10/launch_new_system.bat",
    "ops/autostart_on_login.bat": "docs/_archive/2026-10/autostart_on_login.bat",
}
_NAMES = ("launch_new_system", "autostart_on_login")
# Live files allowed to name the retired pair, each with its reason.
_KEPT = {
    # The bundle exclusion lists (see the module docstring).
    "tools/build_portable.py",
    # A comment only (it names the RC_ROOT variable the bat set); rc-shell/**
    # is the main session's in s144, so the merger re-words it and then
    # drops this entry.
    "rc-shell/src/rc_root.js",
}


def _tracked(rel: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--", rel], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    return out.strip() == rel


@pytest.mark.parametrize("rel", sorted(_RETIRED))
def test_legacy_bat_stays_out_of_ops(rel: str) -> None:
    assert not (REPO_ROOT / rel).exists(), (
        f"{rel} reappeared. The legacy ops/*.bat start chain is dormant (no "
        "scheduled task or Startup shortcut runs it); RC starts from the "
        "RC-Supervisor task. Confirm a real caller before restoring it."
    )
    assert not _tracked(rel)


@pytest.mark.parametrize("rel", sorted(_RETIRED.values()))
def test_legacy_bat_archive_copy_is_tracked(rel: str) -> None:
    # Archived with git mv, so the copy stays tracked even though .gitignore
    # ignores the _archive/ path (a cp + git add would have been refused).
    assert (REPO_ROOT / rel).is_file()
    assert _tracked(rel), f"{rel} is not in the git index"


def test_the_kept_neighbours_are_still_present() -> None:
    # Anchor: the absence checks above must not pass under a wrong root, and
    # the chain's neighbours that are NOT retired stay.
    for rel in ("ops/start_ops.bat", "ops/run_self_healing_watchdog.ps1",
                "ops/rc_supervisor.py", "tools/build_portable.py"):
        assert (REPO_ROOT / rel).is_file(), rel


def test_no_live_tracked_code_names_the_retired_pair() -> None:
    """No runnable or config file outside _KEPT names either bat.

    Dated history (every *.md, docs/, BACKLOG.md) and tests/ (this guard
    names the files) are out of scope; data/ and web/data/ are bulk game
    data. *.xml covers the tracked UTF-16 task XMLs, decoded.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.json", "*.yml",
                "*.yaml", "*.js", "*.mjs", "*.html", "*.xml")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel or rel in _KEPT:
            continue
        scanned += 1
        raw = path.read_bytes()
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        if any(name in text for name in _NAMES):
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the retired bat chain: {offenders}"
