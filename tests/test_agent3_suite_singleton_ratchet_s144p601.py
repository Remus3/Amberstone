"""S144-P-601 - ruff PGH003, C408 and PLW1510 are held in agents/agent3_testing/suite/.

None of the three is selected by ruff.toml, and the earlier agent-3 suite ratchet
(tests/test_agent3_suite_idiom_ratchet_s144p231.py) holds PLR0402 / C420 / SIM117 only.
Measured 2026-11-09 with ``ruff check --isolated --target-version py39 --line-length 120``:
four findings in three modules outside the one baseline row below.

- PGH003 (a blanket ``# type: ignore``) in test_warm_ui_watchdog.py lines 92 and 93: the same two
  assignments at lines 44-45 and 68-69 of the module already say ``[assignment]``; the two
  stragglers now say it too. Comment-only change.
- C408 in test_agent0.py ``_valid_task``: ``dict(op=...)`` spelled as a literal with the same five
  keys, so ``base.update(overrides)`` and ``Task(**base)`` see an identical mapping.
- PLW1510 in test_supervisor.py: the ``taskkill`` call states ``check=False``. That is the
  Python default, so the bytes run and the behaviour are identical; the keyword only records that
  a non-zero exit is meant to be ignored.

Baseline (deliberate, not converted): ``conftest.py`` forwards the kit launch to the real
``subprocess.run`` with ``**kw`` at call time, so a ``check=`` keyword would collide with one the
caller passes, and the lambda is a late-bound wrapper (the stubs patch ``subprocess.run`` after
import), so PLW0108's "inline the inner function" would freeze the wrong callable. That row
reads one PLW1510 and one PLW0108 finding; the set only shrinks, and a row that stops offending
fails ``test_baseline_is_exact`` until it is dropped.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_RULES = ("PGH003", "C408", "PLW1510", "PLW0108")
_DIR = "agents/agent3_testing/suite/"
# file -> {rule: count} that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "agents/agent3_testing/suite/conftest.py": {"PLW0108": 1, "PLW1510": 1},
}
_FIXED = (
    "agents/agent3_testing/suite/test_agent0.py",
    "agents/agent3_testing/suite/test_supervisor.py",
    "agents/agent3_testing/suite/test_warm_ui_watchdog.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin,
        check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _suite_files() -> list[str]:
    files = [p for p in repo_files(REPO_ROOT, ("*.py",))
             if relative_posix(p).startswith(_DIR)]
    assert files, "the agent-3 suite enumerated to nothing"
    return [str(p) for p in files]


def _counts() -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for d in _ruff(_suite_files()):
        rel = relative_posix(Path(d["filename"]).resolve())
        row = counts.setdefault(rel, {})
        row[d["code"]] = row.get(d["code"], 0) + 1
    return counts


def test_no_new_findings():
    counts = _counts()
    new = {f: c for f, c in counts.items() if _BASELINE.get(f) != c}
    assert not new, f"ruff {_RULES} findings beyond the baseline, file: {{rule: count}}: {new}"


def test_baseline_is_exact():
    counts = _counts()
    stale = [f for f in _BASELINE if counts.get(f) != _BASELINE[f]]
    assert not stale, f"baseline rows that no longer match the tree (drop or update them): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_the_task_helper_mapping_keeps_its_five_keys():
    """The literal that replaced ``dict(...)`` carries the same keys and values."""
    sys.path.insert(0, str(REPO_ROOT))
    from agents.agent3_testing.suite import test_agent0

    task = test_agent0._valid_task()
    assert (task.op, task.originating_agent, task.payload_ext, task.tag) == (
        "push-web-ui", "5", ".html", "ui-update")
    assert task.remote_path == r"\\192.0.2.237\RCClient\web\index.html"
    assert test_agent0._valid_task(tag="x").tag == "x"


def test_probe_is_live():
    """The rules report their patterns and stay quiet on the sound spellings, so an empty scan is real."""
    bad = ("import subprocess\n"
           "d = dict(a=1)\n"
           "x = d  # type: ignore\n"
           "subprocess.run(['x'])\n"
           "f = lambda: g()\n")
    good = ("import subprocess\n"
            "d = {'a': 1}\n"
            "x = d  # type: ignore[assignment]\n"
            "subprocess.run(['x'], check=False)\n")
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
