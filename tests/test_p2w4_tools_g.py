r"""P2 cycle-14 slice G regression tests (packaging / install / boot / cert / gates).

Covers FIX-NOW defects found auditing the slice-G tool surface:

  1. tools/headless_run.ps1 used a bare ``py`` launcher to run
     slice_orchestrator.py on the resume path. Bare ``py`` on Legion resolves
     via PEP 514 to a dep-less pymanager runtime (the same incident class
     tests/test_bare_py_ban.py guards), so the resume-manifest read would have
     run under a pytest-/deps-less interpreter. The launcher must pin the
     canonical interpreter by absolute path (with a PATH ``python`` fallback,
     mirroring the tools/*.cmd wrappers). The bare-py guard's own regex misses
     the ``& py "$var\tools\..."`` quoted-variable spelling, so this is a
     direct-content regression in addition.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HEADLESS_RUN = _REPO_ROOT / "tools" / "headless_run.ps1"

# The pin is still ABSOLUTE (bare ``py`` is the whole defect), but the
# account-specific prefix is now expanded by PowerShell from $env:LOCALAPPDATA
# rather than baked in - see tests/test_no_hardcoded_home_path.py. The property
# being asserted is unchanged: the launcher must name the Python314 install by
# an absolute path, not a launcher shim.
_CANONICAL_PY = (
    r"$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
)

# Bare ``py`` (optionally ``py.exe``) followed by a runnable argument, in any
# of the spellings the launcher could use: a quoted/unquoted variable path, a
# repo-relative tools path, a *.py target, or a module/-3 flag. This is a
# superset of tests/test_bare_py_ban.py so the quoted ``"$repo\tools\..."``
# form is caught here even though the repo-wide guard's regex skips it.
_BARE_PY_BROAD = re.compile(
    r"""(^|[^\w.-])py(\.exe)?\s+(-m\s|-3|["']?\$|["']?[A-Za-z]:|tools[\\/]|[\w.\\/-]+\.py\b)"""
)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_headless_run_exists():
    assert _HEADLESS_RUN.is_file(), f"missing: {_HEADLESS_RUN}"


def test_headless_run_has_no_bare_py_launcher():
    offenders = [
        f"{i}: {ln.strip()}"
        for i, ln in enumerate(_lines(_HEADLESS_RUN), 1)
        if _BARE_PY_BROAD.search(ln)
    ]
    assert not offenders, (
        "tools/headless_run.ps1 invokes a bare `py` launcher (resolves to a "
        "dep-less pymanager runtime); pin the canonical absolute interpreter:\n"
        + "\n".join(offenders)
    )


def test_headless_run_pins_canonical_interpreter():
    body = _HEADLESS_RUN.read_text(encoding="utf-8")
    assert _CANONICAL_PY in body, (
        "tools/headless_run.ps1 must reference the canonical absolute Python "
        "interpreter path for the resume-manifest read"
    )
