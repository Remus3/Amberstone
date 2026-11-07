"""S144-P-303 / S144-P-305 - PLW1514 (a text-mode ``open`` / ``Path.read_text`` / ``write_text`` with no ``encoding=``) held at zero in production code and, since S144-P-305, in ``tests/``.

Without ``encoding=`` Python decodes with the locale code page: cp1252 on a stock Windows box, so a UTF-8 file with
one non-ASCII byte (a champion name, a localized ability string) either raises or is silently mojibaked, and the same
script behaves differently under ``PYTHONUTF8=1``. The rule is a ruff PREVIEW rule and ruff.toml does not select it.

Measured 2026-11-06 with ``ruff check --isolated --preview --select PLW1514``: 19 findings in the tracked tree.
Twelve production sites in six files (``scripts/discover_champion_codes.py``, ``tools/ds_block_scanner.py``,
``tools/ds_cond_inspect.py``, ``tools/ds_cond_pair_prefilter.py``, ``tools/ds_execute_prefilter.py``,
``tools/rofl_archiver.py``) now pass ``encoding="utf-8"`` (JSON the DS pipeline wrote as UTF-8, and the ASCII LCU
lockfile). The rest is out of scope here and is filed, not hidden: ``ops/fleet_kit`` is vendored byte-for-byte,
``agents/daemon_slayer`` (its tests included) belongs to the DS lane.

S144-P-305 (2026-11-06): the three remaining ``tests/`` sites (``test_precommit_gate_stdin_fault_rm783.py``,
``test_repin_designed_negative_rc5.py``, ``test_repin_subagent_cli_rm795.py``) now say ``encoding="utf-8"`` and
``tests/`` plus ``*/tests/`` leave the out-of-scope list. The one test-code finding left is in
``agents/daemon_slayer/tests/test_effects_expansion.py`` (DS lane, filed).

The baseline is empty on purpose: a new finding anywhere in scope fails ``test_no_new_findings``. The run uses NO config
(``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULE = "PLW1514"
_OUT_OF_SCOPE = (
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
_FIXED = (
    "scripts/discover_champion_codes.py",
    "tools/ds_block_scanner.py",
    "tools/ds_cond_inspect.py",
    "tools/ds_cond_pair_prefilter.py",
    "tools/ds_execute_prefilter.py",
    "tools/rofl_archiver.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not rel.startswith(_OUT_OF_SCOPE)


@pytest.fixture(scope="module")
def findings() -> list[str]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and _in_scope(rel):
            out.append(f"{rel}:{d['location']['row']}")
    return out


def test_no_new_findings(findings):
    assert not findings, f"ruff {_RULE} (text-mode I/O with no encoding=) in production code: {findings}"


def test_the_rule_still_detects_a_bare_read_text():
    """Positive control: a clean tree must not be a rule that stopped firing."""
    hits = _ruff(["--select", _RULE, "--stdin-filename", "probe.py", "-"],
                 stdin="from pathlib import Path\nPath('x').read_text()\n")
    assert [h["code"] for h in hits] == [_RULE]
    ok = _ruff(["--select", _RULE, "--stdin-filename", "probe.py", "-"],
               stdin="from pathlib import Path\nPath('x').read_text(encoding='utf-8')\n")
    assert ok == []


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_files_stay_in_scope_and_exist(rel):
    assert _in_scope(rel)
    assert (REPO_ROOT / rel).is_file()
