"""RUF056 (a falsy ``dict.get`` fallback in a boolean position) holds at its baseline (S144-P-520).

RUF056 is a ruff PREVIEW rule and ruff.toml does not select it, so nothing held the count. It flags
``bool(d.get(k, False))`` / ``if d.get(k, 0):`` where the fallback is already falsy, so ``d.get(k)`` (default
``None``) reads the same in that position. A missing key and a stored falsy value both land on the same branch.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file:
21 findings in 12 files. 15 sites in 7 files are fixed here with no behaviour change (agents/daemon_slayer/
cc_pairing.py, its r197 drift test, coaches/loadout_resolver.py, core/daemon_slayer_client.py (8),
scripts/rewind_scraper.py, tools/gated_lx02_payload_check.py (2), tools/lcu_agent.py).

Six stay, as NAMED exceptions with a count each (the baseline only shrinks):
- core/game_snapshot.py (4): a FROZEN file (CLAUDE.md); a fix there needs the adjudicator gate.
- agents/daemon_slayer/hps.py (1) and lcu/lcu_rune_writer.py (1): lane/ds changes both and has not landed, so
  editing them here would collide with it; the next cycle after that landing converts both and drops them.

An entry whose count no longer matches fails ``test_baseline_is_exact`` until it is lowered or dropped.
``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair proves the preview selection is live.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULE = "RUF056"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)

# path -> findings it may keep (reasons in the module docstring).
_BASELINE = {
    "core/game_snapshot.py": 4,
    "agents/daemon_slayer/hps.py": 1,
    "lcu/lcu_rune_writer.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _tree_counts() -> Counter:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found: Counter = Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            found[rel] += 1
    return found


def test_no_new_findings():
    new = {rel: n for rel, n in _tree_counts().items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"RUF056 findings beyond the named baseline (drop the falsy fallback): {new}"


def test_baseline_is_exact():
    found = _tree_counts()
    stale = {rel: (n, found.get(rel, 0)) for rel, n in _BASELINE.items() if found.get(rel, 0) != n}
    assert not stale, f"baseline entries whose count moved (baseline, found) - lower or drop them: {stale}"
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_a_falsy_fallback_in_bool():
    assert _probe("d = {}\nx = bool(d.get('k', False))\n") == {"RUF056"}


def test_probe_sees_a_zero_fallback_in_a_condition():
    assert _probe("d = {}\nif d.get('k', 0):\n    pass\n") == {"RUF056"}


def test_a_truthy_or_bare_get_is_quiet():
    assert _probe("d = {}\nx = bool(d.get('k'))\ny = d.get('k', 5)\nz = d.get('k', False)\n") == set()
