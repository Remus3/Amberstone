"""RM-1740 - ruff ISC002 (backslash-continued implicit string concatenation) is held at zero tree-wide.

ISC002 is not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated --line-length 120`` (target
py39) over the tracked Python: 9 findings in 9 test modules, every one a string literal continued onto the next line
with a backslash (``assert x, "a" \\`` newline ``"b"``). Each is now wrapped in parentheses, the house style for a
multi-line message. Parentheses change no value: a string literal split across lines is the same constant before and
after, and the 9 touched modules still collect and pass.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline is empty and only
shrinks. ISC001 (two literals on one line) is a separate rule: its only two hits are in ``ops/rc_supervisor.py``
(frozen), so it is not part of this guard.

``ops/fleet_kit/`` is out of scope (s162): it is vendored byte-for-byte and pinned by its MANIFEST.json, so RC cannot
fix a finding there. Kit v30 brought one ISC002 into ``fleet_rewrite.py`` and reddened this guard. A fence, not a
baseline row, so the next kit version cannot trip it either; ``test_fence_hides_only_manifest_pinned_kit_files`` keeps
the fence off RC-authored code and ``test_an_rc_authored_finding_is_still_counted`` proves the count path. Precedent:
the sibling ISC001 guard ``tests/test_isc001_same_line_concat_ratchet_s144p507.py`` (``_OUT_OF_SCOPE``).
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

_RULES = ("ISC002",)
# Vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json: MAIN's bytes, never RC-authored.
_VENDORED = "ops/fleet_kit/"
_OUT_OF_SCOPE = (_VENDORED,)
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = set()


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _count(findings: list[dict], tracked: set[str]) -> dict[str, int]:
    counts: collections.Counter = collections.Counter()
    for d in findings:
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


@pytest.fixture(scope="module")
def tracked() -> set[str]:
    files = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    return files


@pytest.fixture(scope="module")
def tree_counts(tracked) -> dict[str, int]:
    return _count(_ruff(["."]), tracked)


def test_no_new_isc002_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """ISC002 reports a backslash-continued literal pair and stays quiet on the parenthesised form."""
    bad = 'x = "a" \\\n    "b"\n'
    good = 'x = ("a"\n     "b")\ny = "one" "two"\n'
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []


_BAD = 'x = "a" \\\n    "b"\n'


@pytest.mark.parametrize("rel", ["core/build_order.py", "ops/launcher/update_cycle.py", "tests/conftest.py"])
def test_an_rc_authored_finding_is_still_counted(rel, tracked):
    """The vendored fence drops the kit only: the same finding under an RC-authored path is counted and fails."""
    found = _ruff(["--stdin-filename", rel, "-"], stdin=_BAD)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _count(found, tracked) == {rel: 1}
    assert rel not in _BASELINE
    kit = _ruff(["--stdin-filename", _VENDORED + "fleet_rewrite.py", "-"], stdin=_BAD)
    assert {d["code"] for d in kit} == set(_RULES), kit
    assert _count(kit, tracked) == {}


def test_fence_hides_only_manifest_pinned_kit_files(tracked):
    """Every tracked .py the fence drops is a MANIFEST.json-pinned kit file, so no RC-authored file hides there."""
    manifest = json.loads((REPO_ROOT / _VENDORED / "MANIFEST.json").read_text(encoding="utf-8"))
    fenced = {rel for rel in tracked if rel.startswith(_OUT_OF_SCOPE)}
    assert fenced, f"no tracked .py under {_VENDORED}: the fence guards nothing, drop it"
    unpinned = sorted(rel for rel in fenced if rel[len(_VENDORED):] not in manifest["files"])
    assert not unpinned, f"not pinned by MANIFEST.json, so RC-authored and in scope: {unpinned}"
