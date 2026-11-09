"""RM-1696 - ruff PT012 (pytest.raises block with more than one statement) held at zero tree-wide.

PT012 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39, line length
120): 7 findings in 5 test modules, none anywhere else (no production code, no vendored kit, no DS package). Why it
matters: a ``pytest.raises`` body that holds a nested ``with``, a ``try`` or several statements passes when ANY line
of it raises the expected type, so a setup line that starts raising hides the line under test.

Each of the 7 bodies is reduced to ONE simple statement and the old multi-line body moved into a local helper
with the same statements in the same order:

- ``tests/test_process_start_tripwire_rm880d.py`` (3): ``_run_swallowing_errors`` and ``_run_worker_thread``
  helpers; the nested ``no_process_start()`` blocks become one multi-item ``with`` (same entry and exit order).
- ``tests/test_scoped_fs_fault_rm411.py``: ``_body_that_fails`` (the shim assert, then the raise).
- ``tests/test_external_source_http_exception_failsoft_s144q69.py`` and its augment twin: ``_drain``.
- ``tests/test_collection_idiom_ratchet_s144p141.py``: ``_handle_then_reraise`` (the bare re-raise fixture).

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding, and it scans every tracked
``.py`` file with no exemption.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_FIXED = (
    "tests/test_augment_external_source_http_exception_failsoft_s144q69.py",
    "tests/test_collection_idiom_ratchet_s144p141.py",
    "tests/test_external_source_http_exception_failsoft_s144q69.py",
    "tests/test_process_start_tripwire_rm880d.py",
    "tests/test_scoped_fs_fault_rm411.py",
)

_PROBE = (
    "import pytest\n\n\n"
    "def test_x():\n"
    "    with pytest.raises(ValueError):\n"
    "        a = 1\n"
    "        raise ValueError(a)\n"
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", "PT012", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_multi_statement_raises_block_anywhere_in_the_tree():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = sorted(
        f"{rel}:{d['location']['row']}"
        for d in _ruff(["."])
        if (rel := relative_posix(Path(d["filename"]).resolve())) in tracked
    )
    assert not found, f"ruff PT012 findings: {found}"


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=_PROBE)
    assert {d["code"] for d in found} == {"PT012"}


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw
