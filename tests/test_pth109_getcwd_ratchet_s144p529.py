"""S144-P-529 - ruff PTH109 (os.getcwd replaceable by Path.cwd) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 26 findings in 12 files, 19 of them in the
vendored kit (``ops/fleet_kit/``, byte-pinned by MANIFEST.json, fenced below). Of the other seven, five became
``Path.cwd()`` (four tests that save and restore the working directory around an import that ``os.chdir``s, and
``tools/precommit_gate.py``, which hands the cwd to ``_git`` as a string, so it spells ``str(pathlib.Path.cwd())``:
``Path.cwd()`` is ``os.getcwd()`` underneath, so the value is unchanged).

The last site, ``tests/test_launcher_update_cycle_pkg6c.py``, matches the launcher-test exclusion the main session owns,
so it sits in ``_BASELINE`` at one finding. The baseline only shrinks: ANY new finding, or a second finding in a
baselined file, fails ``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding, and ``--preview`` because PTH109 is preview-only in this ruff.
"""
from __future__ import annotations

import collections
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

_RULE = "PTH109"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "tests/test_launcher_update_cycle_pkg6c.py": 1,  # launcher-test exclusion: the main session owns it
}
_FIXED = (
    "tests/phase7_polish/test_start_daemon_slayer_logging.py",
    "tests/test_port_handoff_residuals_rm834.py",
    "tests/test_port_handoff_restart_race.py",
    "tests/test_routes_recordings.py",
    "tools/precommit_gate.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULE} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: the rule does fire on the pattern it exists for."""
    probe = "import os\ncwd = os.getcwd()\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == [_RULE]


def test_precommit_gate_root_fallback_is_the_process_cwd(monkeypatch, tmp_path):
    """Behaviour pin: the spelling change keeps the cwd string the gate falls back to."""
    gate = _load_by_path("_s144p529_precommit_gate", "tools/precommit_gate.py")
    seen: list = []

    def fake_git(args, root):
        seen.append(root)
        return ""

    monkeypatch.setattr(gate, "_git", fake_git)
    monkeypatch.setattr(gate, "_root_from_command", lambda command: None)
    monkeypatch.setattr(gate, "_staged_added", lambda root: (_ for _ in ()).throw(_Stop(root)))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(_Stop) as stop:
        gate._gate_commit("git commit -m x", False)
    assert stop.value.args[0] == str(Path.cwd())
    assert seen == [str(Path.cwd())]


class _Stop(Exception):
    pass


def _load_by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
