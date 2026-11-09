"""S144-P-270 - a bundle of small ruff "dead weight" rules held at a shrink-only baseline.

Rules: F841 (assigned, never read), C420 / C416 (a comprehension that is a plain ``dict.fromkeys`` / ``list`` /
``dict`` call), PERF402 / PERF403 (a for-loop that copies a list or builds a dict), PLC3002 (a lambda called on the
spot), PIE807 (``lambda: {}`` where ``dict`` does), PIE810 (chained ``startswith``) and PLW0602 (``global`` with no
assignment). None of them is in ``ruff.toml`` (F841 is ignored there as noisy for callbacks), so nothing enforced them.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39) over the tracked tree: 20 findings. Eight sit in
the two fenced trees below (the DS engine and the vendored kit). Of the 12 held-scope findings, two were fixed here
(``tools/gated_g416_counter_chips.py`` ``comp_inputs`` called a lambda inline; ``tests/test_rc_facts_launcher_cutover_a45d.py``
patched ``_health_all`` with ``lambda: {}``) and ten remained in ``_BASELINE``, each in a file this lane may not edit:
frozen (``app/_game_lifecycle.py``, ``app/_loop.py``, ``core/log_setup.py``, ``lcu/lcu_client.py``,
``ops/rc_supervisor.py``), PKG-owned (``ops/launcher/update_cycle.py``, ``tools/build_portable.py``,
``tests/test_launcher_first_run.py``, ``tests/test_launcher_key_read_rm810.py``). The tenth, the DS extractor
``tools/daemon_slayer_abilities_extract.py`` (a PERF403 copy loop), was fixed in S144-P-526 and left the baseline.

RET504 is left out on purpose: its firing changed between ruff 0.15 and 0.17 (``tests/_ruff_version.py``), so a count
of it is not portable. Every rule above has been stable across both.

The count per file can only fall: a file that reaches zero must leave ``_BASELINE`` and a new finding anywhere fails.
The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding.
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

_RULES = "F841,C420,C416,PERF402,PERF403,PLC3002,PIE807,PIE810,PLW0602"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site in a file the repo lane may not edit.
_BASELINE: dict[str, int] = {
    "app/_game_lifecycle.py": 1,  # frozen
    "app/_loop.py": 1,  # frozen
    "core/log_setup.py": 1,  # frozen
    "lcu/lcu_client.py": 1,  # frozen
    "ops/rc_supervisor.py": 1,  # frozen
    "ops/launcher/update_cycle.py": 1,  # PKG-owned
    "tools/build_portable.py": 1,  # PKG-owned
    "tests/test_launcher_first_run.py": 1,  # PKG-owned (tests/test_launcher_*)
    "tests/test_launcher_key_read_rm810.py": 1,  # PKG-owned (tests/test_launcher_*)
}
_FIXED = (
    "tools/gated_g416_counter_chips.py",
    "tests/test_rc_facts_launcher_cutover_a45d.py",
    "tools/daemon_slayer_abilities_extract.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
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
    assert not over, f"ruff findings above the baseline, file: count: {over}"


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


@pytest.mark.parametrize("src, code", [
    ("def f():\n    x = 1\n", "F841"),
    ("fn = (lambda p: p + 1)(2)\n", "PLC3002"),
    ("import collections\nd = collections.defaultdict(lambda: {})\n", "PIE807"),
    ("def f(s):\n    return s.startswith('a') or s.startswith('b')\n", "PIE810"),
    ("def f(rows):\n    return {k: None for k in rows}\n", "C420"),
    ("def f(rows):\n    return [r for r in rows]\n", "C416"),
    ("def f(rows):\n    out = []\n    for r in rows:\n        out.append(r)\n    return out\n", "PERF402"),
    ("def f(rows):\n    out = {}\n    for k, v in rows:\n        out[k] = v\n    return out\n", "PERF403"),
    ("_X = 1\n\n\ndef f():\n    global _X\n    return _X\n", "PLW0602"),
])
def test_every_rule_in_the_bundle_fires_on_its_pattern(src, code):
    """A positive control per shape: a rule that silently stopped firing would pass the ratchet for nothing."""
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=src)
    assert code in {d["code"] for d in found}, (code, found)
