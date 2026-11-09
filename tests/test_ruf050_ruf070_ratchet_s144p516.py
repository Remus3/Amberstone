"""RUF050 (empty ``if``) and RUF070 (assign before ``yield``) hold at their baseline (S144-P-516).

Both are ruff PREVIEW rules and ruff.toml selects neither, so nothing held the count. RUF050 flags an ``if``
whose body is only ``pass``; RUF070 flags ``x = value`` immediately followed by ``yield x`` where ``x`` is not
read afterwards (spell it ``yield value``).

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file: 1
RUF050 and 3 RUF070 findings in 4 files. Three are fixed here with no behaviour change:
tools/hotfix_ranged_only_melee_loadouts.py (an ``if changed: pass`` and the ``changed`` flag that only fed it),
tests/test_extract_champion_profiles_no_import_write_s144p25.py and tests/test_feature_policy_vod_record.py (a
fixture that assigned and yielded the same value).

The fourth stays, as a NAMED exception: tests/test_live_write_tracer_selftest.py ``control`` assigns ``result``
INSIDE ``with _private_base(...)`` and yields AFTER the block, so the private base is torn down before any arm reads
the result. Inlining the yield would move it inside the ``with`` and keep the base alive for the whole module-scoped
fixture - a behaviour change, so ruff's suggestion does not apply. The baseline only shrinks: an entry that stops
offending fails ``test_baseline_is_exact`` until it is dropped.

``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair proves the preview selection is live.
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

_RULES = "RUF050,RUF070"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)

# path -> the rule it is allowed to keep, with the reason in the module docstring.
_BASELINE = {
    "tests/test_live_write_tracer_selftest.py": "RUF070",
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _tree_findings() -> dict[str, set[str]]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found: dict[str, set[str]] = {}
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            found.setdefault(rel, set()).add(d["code"])
    return found


def test_no_new_findings():
    new = {rel: sorted(codes) for rel, codes in _tree_findings().items()
           if codes != {_BASELINE.get(rel)}}
    assert not new, f"RUF050 / RUF070 findings outside the named baseline: {new}"


def test_baseline_is_exact():
    found = _tree_findings()
    stale = sorted(rel for rel in _BASELINE if rel not in found)
    assert not stale, f"baseline entries that no longer offend (drop them): {stale}"
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_an_empty_if():
    assert _probe("def f(x):\n    if x:\n        pass\n") == {"RUF050"}


def test_probe_sees_an_assign_before_yield():
    assert _probe("def f():\n    v = compute()\n    yield v\n") == {"RUF070"}


def test_a_used_value_and_a_real_branch_are_quiet():
    assert _probe(
        "def f(x):\n    v = compute()\n    yield v\n    print(v)\n    if x:\n        return 1\n"
    ) == set()
